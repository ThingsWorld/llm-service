"""Self-test provenance regressions using synthetic shell stubs, never a GPU."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('environment',['self-managed','daytona',None])
def test_gpu_self_test_labels_actual_declared_environment(tmp_path,environment):
    (tmp_path/'scripts').mkdir()
    shutil.copy(ROOT/'scripts/gpu_validate.sh',tmp_path/'scripts/gpu_validate.sh')
    binary=tmp_path/'bin';binary.mkdir()
    stubs={
        'nvidia-smi':'#!/usr/bin/env bash\necho "SYNTHETIC RTX 4090, GPU-test-only, synthetic-driver, 24576 MiB"\n',
        'git':'#!/usr/bin/env bash\nif [[ "$1" == rev-parse ]]; then printf "%040d\\n" 0; fi\n',
    }
    for name,script in stubs.items():
        path=binary/name;path.write_text(script);path.chmod(0o755)
    (tmp_path/'setup.sh').write_text('#!/usr/bin/env bash\nmkdir -p "$DATA_DIR"\necho 12345 > "$DATA_DIR/gateway.pid"\n')
    (tmp_path/'.venv/bin').mkdir(parents=True)
    fake_python=tmp_path/'.venv/bin/python';fake_python.write_text('#!/usr/bin/env bash\nexit 0\n');fake_python.chmod(0o755)
    env={**os.environ,'PATH':str(binary)+':'+os.environ['PATH'],
        'API_KEY':'synthetic-inference-key','ADMIN_API_KEY':'synthetic-admin-key',
        'KEY_HASH_SECRET':'synthetic-pepper-for-provenance-test','DATA_DIR':str(tmp_path/'data')}
    env.pop('LLM_TEST_ENVIRONMENT',None)
    if environment:env['LLM_TEST_ENVIRONMENT']=environment
    result=subprocess.run(['bash','scripts/gpu_validate.sh','smoke'],cwd=tmp_path,env=env,
                          capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
    label=environment or 'unspecified'
    contexts=list((tmp_path/'results/gpu'/label).glob('*/context.json'))
    assert len(contexts)==1
    record=json.loads(contexts[0].read_text())
    assert record['execution_environment']==label and record['official_score'] is False
    assert record['stage']=='smoke' and record['commit_sha']=='0'*40
    assert record['model_id']=='Qwen/Qwen2.5-7B-Instruct'
    assert not (tmp_path/'results/daytona').exists()
    public_text=contexts[0].read_text()+result.stdout+result.stderr
    assert all(env[k] not in public_text for k in ('API_KEY','ADMIN_API_KEY','KEY_HASH_SECRET'))


def test_invalid_environment_label_fails_before_hardware_or_setup(tmp_path):
    (tmp_path/'scripts').mkdir()
    shutil.copy(ROOT/'scripts/gpu_validate.sh',tmp_path/'scripts/gpu_validate.sh')
    env={**os.environ,'LLM_TEST_ENVIRONMENT':'../daytona'}
    result=subprocess.run(['bash','scripts/gpu_validate.sh','smoke'],cwd=tmp_path,env=env,
                          capture_output=True,text=True,timeout=5)
    assert result.returncode==2 and not (tmp_path/'results').exists()
