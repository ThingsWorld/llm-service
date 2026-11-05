"""Private, two-case causal probe. No answer repair and no acceptance score."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import httpx
from transformers import AutoTokenizer

sys.path.insert(0, str(Path.cwd()))
from server.config import MODEL, REVISION, configuration
from server.supervisor import engine_command
from scripts.native_setup import configure_runtime_environment, validate_jit_tools
from benchmarks.serving_benchmark import output_valid

def interrupted(*_):
    raise KeyboardInterrupt()

for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(sig, interrupted)
os.environ.update(MODEL_ID=MODEL, MODEL_REVISION=REVISION, SGLANG_PYTHON=sys.executable,
                  BENCH_PROFILE='optimized', HF_HUB_OFFLINE='1', FP32_LM_HEAD='0',
                  DETERMINISTIC_INFERENCE='0', TRITON_ATTENTION_REDUCE_IN_FP32='0',
                  ATTENTION_BACKEND='flashinfer')
runtime_environment = configure_runtime_environment(sys.executable, sys.executable)
validate_jit_tools()
_, cfg = configuration()
command = engine_command(cfg) + ['--log-requests', '--log-requests-level', '2']
out = Path('results/environment/self-managed-20261105/input-sampling-control-v2')
out.mkdir(parents=True, exist_ok=False)
cases = json.loads((Path.home()/'.cache/llm-accuracy-tools/input-sampling-cases.json').read_text())
tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION, local_files_only=True)
report = {'official_score': False, 'diagnostic_only': True, 'complete': False,
          'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
          'control_code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'command': command, 'rows': [], 'runtime_environment': runtime_environment,
          'input_comparison': [], 'controller_versions': cases['versions']}
for item in cases['cases']:
    native_ids = tokenizer.apply_chat_template(item['messages'], tokenize=True,
        add_generation_prompt=True, tools=None, reasoning_effort=None, return_dict=False)
    report['input_comparison'].append({'id': item['id'], 'ids_equal': native_ids == item['canonical_ids'],
        'canonical_length': len(item['canonical_ids']), 'runtime_length': len(native_ids),
        'runtime_ids': native_ids})
log = (out/'engine.log').open('w')
process = subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True)
try:
    with httpx.Client(base_url='http://127.0.0.1:30000', timeout=90, trust_env=False) as client:
        deadline = time.monotonic()+300
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
        report['actual'] = {k:actual.get(k) for k in ['model_impl','model_path','revision','dtype',
            'attention_backend','enable_fp32_lm_head','disable_radix_cache','sampling_defaults']}
        for mode in ['chat-default', 'chat-explicit-neutral', 'native-canonical', 'chat-logprobs']:
            for item in cases['cases']:
                flush_deadline=time.monotonic()+5
                while True:
                    flushed=client.get('/flush_cache')
                    if flushed.status_code==200: break
                    if time.monotonic()>flush_deadline: flushed.raise_for_status()
                    time.sleep(0.1)
                body={'model':MODEL, 'messages':item['messages'], 'max_tokens':item['max_tokens'],
                      'temperature':0, 'response_format':item['response_format'], 'stream':False}
                endpoint='/v1/chat/completions'
                if mode=='chat-explicit-neutral':
                    body.update(repetition_penalty=1.0, top_p=1.0, top_k=-1)
                elif mode=='chat-logprobs':
                    body.update(logprobs=True, top_logprobs=10)
                elif mode=='native-canonical':
                    endpoint='/generate'
                    body={'input_ids':item['canonical_ids'], 'sampling_params':{
                        'max_new_tokens':item['max_tokens'], 'temperature':0, 'top_p':1.0,
                        'top_k':-1, 'repetition_penalty':1.0, 'json_schema':'{"type":"object"}'},
                        'stream':False}
                response=client.post(endpoint,json=body)
                data=response.json()
                (out/f'{mode}-{item["id"]}.json').write_text(json.dumps(data,indent=2)+'\n')
                response.raise_for_status()
                text=data['text'] if endpoint=='/generate' else data['choices'][0]['message']['content']
                row={'id':item['id'],'mode':mode,'text':text,'expected':item['expected'],
                     'quality_pass':output_valid(text,item['expected'])}
                report['rows'].append(row)
                (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
                print(json.dumps(row),flush=True)
        report['complete']=True
except (Exception, KeyboardInterrupt) as exc:
    report['error_type']=type(exc).__name__
    report['error_message']=str(exc)[:300]
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
print(json.dumps({'complete':report['complete'],'correct':sum(r['quality_pass'] for r in report['rows']),
                  'engine_stopped':True}),flush=True)
raise SystemExit(0 if report['complete'] and all(r['quality_pass'] for r in report['rows']) else 1)
