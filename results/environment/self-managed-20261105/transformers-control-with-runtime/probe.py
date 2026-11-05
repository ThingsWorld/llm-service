import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import httpx

sys.path.insert(0, str(Path.cwd()))
from server.config import configuration
from server.supervisor import engine_command
from scripts.native_setup import configure_runtime_environment, validate_jit_tools
from benchmarks.serving_benchmark import output_valid

def interrupted(*_):
    raise KeyboardInterrupt()

for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(sig, interrupted)
os.environ['SGLANG_PYTHON'] = sys.executable
os.environ['BENCH_PROFILE'] = 'optimized'
runtime_environment = configure_runtime_environment(sys.executable, sys.executable)
validate_jit_tools()
_, cfg = configuration()
command = engine_command(cfg) + ['--model-impl', 'transformers']
out = Path('results/environment/self-managed-20261105/transformers-control-with-runtime')
out.mkdir(parents=True, exist_ok=False)
report = {'official_score': False, 'diagnostic_only': True, 'complete': False,
          'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
          'control_code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'command': command, 'rows': [], 'runtime_environment': runtime_environment,
          'limitation': 'Manual SGLang model-implementation control; two direct nonstream cases, not a full matrix.'}
log = (out/'engine.log').open('w')
process = subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True)
try:
    with httpx.Client(base_url='http://127.0.0.1:30000', timeout=45, trust_env=False) as client:
        deadline = time.monotonic()+240
        while time.monotonic()<deadline:
            if process.poll() is not None:
                raise RuntimeError('control_engine_exited')
            try:
                if client.get('/health',timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            raise RuntimeError('control_startup_deadline')
        actual = client.get('/server_info').json()
        report['actual'] = {k:actual.get(k) for k in ['model_impl','model_path','revision','dtype','attention_backend','enable_fp32_lm_head','disable_radix_cache']}
        assert actual['model_impl']=='transformers'
        root=Path('results/gpu/daytona/20261105T082811-bench/serving')
        for w,c,r,ident in [('short',4,1,'short-3'),('long',16,2,'long-12')]:
            item=next(i for i in json.loads((root/f'baseline-{w}-c{c}-r{r}-inputs.json').read_text()) if i['id']==ident)
            body={'model':os.environ['MODEL_ID'],'messages':item['messages'],'max_tokens':item['max_tokens'],
                  'temperature':0,'response_format':item['response_format'],'stream':False}
            response=client.post('/v1/chat/completions',json=body)
            response.raise_for_status()
            text=response.json()['choices'][0]['message']['content']
            row={'id':ident,'text':text,'expected':item['expected'],'quality_pass':output_valid(text,item['expected'])}
            report['rows'].append(row)
            print(json.dumps(row),flush=True)
        report['complete']=True
except (Exception, KeyboardInterrupt) as exc:
    report['error_type']=type(exc).__name__
finally:
    if process.poll() is None:
        os.killpg(process.pid,signal.SIGTERM)
        try:process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL)
            process.wait()
    log.close()
    report['engine_stopped']=True
    (out/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
print(json.dumps({'complete':report['complete'],'correct':sum(r['quality_pass'] for r in report['rows']),'engine_stopped':True}),flush=True)
