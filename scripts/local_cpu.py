"""Reproduce public HTTP diagnostics locally; never impersonates GitHub Actions.

The official soft_runner is restricted to GitHub-hosted runners. This separate
developer harness starts an isolated fixture and the real setup --contract-test,
then invokes only the public HTTP checker. No GPU or platform score is involved.
"""
import argparse
import ast
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import httpx

ROOT = Path(__file__).resolve().parents[1]


def stamp():
    return datetime.now(timezone.utc).isoformat()


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def source_identity():
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True))
    digest = hashlib.sha256()
    for directory in ('server', 'control_plane', 'agent', 'configs', 'migrations', 'scripts', 'tests'):
        for path in sorted((ROOT / directory).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                digest.update(str(path.relative_to(ROOT)).encode() + b'\0' + path.read_bytes() + b'\0')
    return {'commit_sha': sha, 'working_tree_dirty': dirty, 'source_files_sha256': digest.hexdigest()}


def download_tools():
    workflow = (ROOT / '.github/workflows/llm-soft.yml').read_text()
    pins = ast.literal_eval(next(line.strip().split(' = ', 1)[1] for line in workflow.splitlines()
                                if line.strip().startswith('pins = ')))
    directory = ROOT / '.cache/soft-tools'
    directory.mkdir(parents=True, exist_ok=True)
    for name in ('soft_check.py', 'credential_fixture.py'):
        path = directory / name
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != pins[name]:
            url = 'https://agentist.org/lab/llm-lab/soft/' + name
            with urllib.request.urlopen(url, timeout=30) as response:
                if response.status != 200 or response.geturl() != url:
                    raise RuntimeError('Unexpected public tool redirect/status')
                data = response.read(300001)
            if len(data) > 300000 or hashlib.sha256(data).hexdigest() != pins[name]:
                raise RuntimeError('Public tool hash mismatch: ' + name)
            path.write_bytes(data)
    return directory


def wait_ready(url, timeout=15):
    deadline = time.monotonic() + timeout
    with httpx.Client(timeout=1, trust_env=False) as client:
        while time.monotonic() < deadline:
            try:
                if client.get(url).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(.05)
    raise RuntimeError('Local CPU service readiness timeout')


@contextmanager
def sandbox():
    tools = download_tools()
    with tempfile.TemporaryDirectory(prefix='llm-local-cpu-') as directory:
        fixture_port, gateway_port = free_port(), free_port()
        env = dict(os.environ)
        env.update(API_KEY=secrets.token_urlsafe(32), ADMIN_API_KEY=secrets.token_urlsafe(32),
                   KEY_HASH_SECRET=secrets.token_urlsafe(32), FIXTURE_CONTROL_KEY=secrets.token_urlsafe(32),
                   DATA_DIR=str(Path(directory) / 'data'), HOST='127.0.0.1', PORT=str(gateway_port),
                   ENGINE_BASE_URL=f'http://127.0.0.1:{fixture_port}', FIXTURE_PORT=str(fixture_port),
                   MODEL_ID='Qwen/Qwen2.5-7B-Instruct',
                   MODEL_REVISION='a09a35458c702b33eeacc393d103063234e8bc28',
                   FIXTURE_MODEL='Qwen/Qwen2.5-7B-Instruct', BENCH_PROFILE='optimized',
                   BOOTSTRAP_PYTHON=sys.executable, SOURCE_COMMIT=source_identity()['commit_sha'],
                   GITHUB_REPOSITORY='ThingsWorld/llm-service', CUDA_VISIBLE_DEVICES='')
        # Fixture controller authority is not available to the submitted gateway.
        gateway_env = {k: v for k, v in env.items() if not k.startswith('FIXTURE_')}
        fixture = subprocess.Popen([sys.executable, str(tools / 'credential_fixture.py')],
                                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = f'http://127.0.0.1:{gateway_port}'
        logpath = Path(directory) / 'setup.log'
        try:
            wait_ready(env['ENGINE_BASE_URL'] + '/health')
            with logpath.open('w') as log:
                result = subprocess.run(['bash', 'setup.sh', '--contract-test'], cwd=ROOT, env=gateway_env,
                                        stdout=log, stderr=log, timeout=180)
            if result.returncode:
                raise RuntimeError('Local CPU setup failed; private log: ' + str(logpath))
            yield env, gateway_env, base, tools
        finally:
            subprocess.run(['bash', 'setup.sh', '--stop'], cwd=ROOT, env=gateway_env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=50)
            fixture.terminate()
            try:
                fixture.wait(timeout=5)
            except subprocess.TimeoutExpired:
                fixture.kill()
                fixture.wait()


def holds_socket(pid, port):
    """Prove gateway.pid owns the listening port before injecting SIGKILL."""
    inodes = set()
    for path in (Path('/proc/net/tcp'), Path('/proc/net/tcp6')):
        for line in path.read_text().splitlines()[1:]:
            fields = line.split()
            if int(fields[1].split(':')[-1], 16) == port and fields[3] == '0A':
                inodes.add('socket:[' + fields[9] + ']')
    return any(os.readlink(fd) in inodes for fd in Path(f'/proc/{pid}/fd').iterdir())


def crash_checks(env, gateway_env, base):
    checks = []
    with httpx.Client(base_url=base, timeout=15, trust_env=False) as client:
        auth = {'Authorization': 'Bearer ' + env['API_KEY']}
        control = {'Authorization': 'Bearer ' + env['FIXTURE_CONTROL_KEY']}
        fixture = env['ENGINE_BASE_URL']
        for window in ('unknown_usage', 'journalled_usage'):
            plan = {'delay': 30 if window == 'unknown_usage' else 0,
                    'pause_after_usage': 30 if window == 'journalled_usage' else 0,
                    'omit_usage': False, 'fail_before': False}
            client.post(fixture + '/__fixture/configure', headers=control, json=plan).raise_for_status()
            payload = {'model': env['MODEL_ID'], 'messages': [{'role': 'user', 'content': 'Crash window'}],
                       'max_tokens': 80, 'stream': True, 'stream_options': {'include_usage': True}}
            with client.stream('POST', '/v1/chat/completions', headers=auth, json=payload) as response:
                response.raise_for_status()
                rid = response.headers['X-Request-ID']
                for line in response.iter_lines():
                    if (window == 'unknown_usage' and 'fixture ' in line) or (window == 'journalled_usage' and '"usage"' in line):
                        break
                else:
                    raise AssertionError('Crash signal not reached')
                pid = int((Path(env['DATA_DIR']) / 'gateway.pid').read_text())
                assert holds_socket(pid, int(env['PORT'])), 'gateway.pid does not hold listener'
                before = client.get('/v1/usage', headers=auth).json()['summary']['cost_micro_usd']
                started = time.monotonic()
                os.kill(pid, signal.SIGKILL)
            with tempfile.TemporaryFile() as log:
                subprocess.run(['bash', 'setup.sh', '--contract-test'], cwd=ROOT, env=gateway_env,
                               stdout=log, stderr=log, check=True, timeout=60)
            wait_ready(base + '/healthz')
            ledger = client.get('/v1/usage', headers=auth).json()
            row = next(r for r in ledger['items'] if r['request_id'] == rid)
            expected = 'adjusted_unknown' if window == 'unknown_usage' else 'completed'
            assert row['status'] == expected
            assert ledger['summary']['reserved_micro_usd'] == ledger['summary']['reserved_tokens'] == 0
            delta = ledger['summary']['cost_micro_usd'] - before
            assert delta == (0 if window == 'unknown_usage' else 500)
            if window == 'unknown_usage':
                assert row['cost_micro_usd'] is None and row['input_tokens'] is None
                audit = client.get('/admin/audit', headers={'Authorization': 'Bearer ' + env['ADMIN_API_KEY']}).json()
                assert any(r['request_id'] == rid and r['event'] == 'credit_adjustment' and
                           r['detail']['usage_known'] is False for r in audit['items'])
            # An idempotent setup after recovery cannot charge a second time.
            new_pid = (Path(env['DATA_DIR']) / 'gateway.pid').read_text()
            with tempfile.TemporaryFile() as log:
                subprocess.run(['bash', 'setup.sh', '--contract-test'], cwd=ROOT, env=gateway_env,
                               stdout=log, stderr=log, check=True, timeout=60)
            assert (Path(env['DATA_DIR']) / 'gateway.pid').read_text() == new_pid
            assert client.get('/v1/usage', headers=auth).json()['summary']['cost_micro_usd'] == before + delta
            elapsed = time.monotonic() - started
            assert elapsed < 60
            checks.append({'test_id': window, 'expected': expected + ' within 60s; no duplicate charge',
                           'actual': {'status': row['status'], 'cost_micro_usd': row['cost_micro_usd'],
                                      'recovered_seconds': round(elapsed, 3)}, 'passed': True,
                           'evidence': {'request_id': rid, 'actual_sigkill': True, 'listener_pid_verified': True}})
        client.post(fixture + '/__fixture/configure', headers=control,
                    json={'delay': 0, 'pause_after_usage': 0}).raise_for_status()
        assert client.post('/v1/chat/completions', headers=auth, json={**payload, 'stream': False}).status_code == 200
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    identity, started = source_identity(), stamp()
    with sandbox() as (env, gateway_env, base, tools):
        report_path = args.out / 'interfaces.json'
        result = subprocess.run([sys.executable, str(tools / 'soft_check.py'), '--base-url', base,
                                 '--fixture-url', env['ENGINE_BASE_URL'], '--out', str(report_path)],
                                env=env, cwd=ROOT, timeout=180)
        report = json.loads(report_path.read_text())
        report.update(**identity, execution_environment='local_cpu_developer_reproduction',
                      github_actions_executed=False)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        if result.returncode:
            return result.returncode
        subprocess.run([sys.executable, 'scripts/check_control_plane.py', '--suite', 'mock',
                        '--base-url', base, '--out', str(args.out / 'control-plane.json')],
                       env=env, cwd=ROOT, check=True, timeout=180)
        recovery = {'schema': 'credential-service-test/1', 'suite': 'mock', 'official_score': False,
                    **identity, 'started_at': started, 'checks': crash_checks(env, gateway_env, base),
                    'finished_at': stamp(), 'execution_environment': 'local_cpu_actual_processes'}
        (args.out / 'recovery.json').write_text(json.dumps(recovery, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
