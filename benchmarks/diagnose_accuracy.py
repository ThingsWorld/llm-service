"""Replay affected full cells and fresh controls against an existing native service.

Loopback only. No setup, GPU allocation, retries, output repair, or scoring.
Uses exactly the normal neutral SSE request path; raw failures are retained.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit

import httpx

from .serving_benchmark import (build_workload, chat_tokens, decoding_matches,
                                load_tokenizer, request_once, summarize)
from server.config import MODEL, REVISION

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'results/gpu/daytona/20261105T082811-bench/serving'


def loopback_url(value):
    url = urlsplit(value)
    if (url.scheme != 'http' or url.hostname not in ('localhost', '127.0.0.1') or
            url.username or url.password or url.query or url.fragment or url.path not in ('', '/')):
        raise argparse.ArgumentTypeError('Use a loopback HTTP URL without credentials or a path')
    return value.rstrip('/')


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def cases(config, tokenizer, seed):
    if seed == 20261018:
        raise ValueError('Fresh control seed must differ from the archived run')
    result = []
    for index, (workload, concurrency, repeat) in enumerate((('short', 4, 1), ('long', 16, 2))):
        spec = next(w for w in config['workloads'] if w['id'] == workload)
        name = f'baseline-{workload}-c{concurrency}-r{repeat}-inputs.json'
        items = json.loads((ARCHIVE / name).read_text())
        original = build_workload(tokenizer, spec,
                                 20261018 + index * 1000000 + concurrency * 10000 + repeat * 100,
                                 16, config['workload_version'])
        if items != original:
            raise ValueError('Archived inputs differ from frozen generator')
        for kind, values in [('archived', items), ('fresh', build_workload(
                tokenizer, spec, seed + index * 1000000 + concurrency * 10000 + repeat * 100,
                16, config['workload_version']))]:
            if any(chat_tokens(tokenizer, item['messages']) != spec['input_tokens'] for item in values):
                raise ValueError('Input token length differs')
            result.append({'id': f'{kind}-{workload}-c{concurrency}', 'concurrency': concurrency,
                           'workload': workload, 'kind': kind, 'items': values})
    return result


async def run(args, config, tokenizer, key, report):
    async with httpx.AsyncClient(timeout=None, trust_env=False,
                                limits=httpx.Limits(max_connections=32)) as client:
        info_response = await client.get(args.base_url + '/info',
            headers={'Authorization': 'Bearer ' + key}, timeout=10)
        info_response.raise_for_status()
        info = info_response.json()
        if (info.get('mode') != 'native' or info.get('engine_version') != '0.5.9' or info.get('model_id') != MODEL or
                info.get('model_revision') != REVISION or not decoding_matches(info, config)):
            raise ValueError('Expected native fixed-model service with neutral decoding')
        report['runtime'] = {k: info.get(k) for k in ('mode', 'profile', 'model_id', 'model_revision', 'config', 'engine_version', 'commit')}
        response = await client.get(args.engine_base_url + '/server_info', timeout=10)
        response.raise_for_status()
        server_args = response.json()  # SGLang 0.5.9 exposes flattened ServerArgs.
        fields = ('model_path', 'revision', 'version', 'dtype', 'attention_backend', 'sampling_defaults',
                  'enable_fp32_lm_head', 'enable_deterministic_inference', 'max_running_requests',
                  'disable_radix_cache', 'disable_cuda_graph')
        report['engine_arguments'] = {k: server_args.get(k) for k in fields}
        if (server_args.get('version') != '0.5.9' or server_args.get('model_path') != MODEL or server_args.get('revision') != REVISION or
                server_args.get('dtype') != 'bfloat16' or server_args.get('sampling_defaults') != 'openai' or
                server_args.get('enable_fp32_lm_head') != info['config'].get('fp32_lm_head', False)):
            raise ValueError('Engine identity or FP32 head differs from gateway declaration')
        selected = cases(config, tokenizer, args.seed)
        write(args.out / 'inputs.json', selected)
        with (args.out / 'raw.jsonl').open('x') as raw:
            for case in selected:
                for route, base in [('gateway', args.base_url), ('engine', args.engine_base_url)]:
                    measured, seconds = [], 0
                    for repeat in range(args.repeats):
                        queue = asyncio.Queue()
                        for item in case['items']:
                            queue.put_nowait(item)
                        async def worker():
                            while not queue.empty():
                                item = queue.get_nowait()
                                row = await request_once(client, base, key if route == 'gateway' else '',
                                    config['model_id'], item, tokenizer, config['deadline_seconds'],
                                    f'accuracy-{case["id"]}-{route}-r{repeat}-{item["id"]}')
                                row.update(case=case['id'], route=route, repeat=repeat,
                                           expected=item['expected'])
                                raw.write(json.dumps(row, allow_nan=False) + '\n')
                                raw.flush()
                                measured.append(row)
                        start = asyncio.get_running_loop().time()
                        await asyncio.gather(*(worker() for _ in range(case['concurrency'])))
                        seconds += asyncio.get_running_loop().time() - start
                    summary = {'case': case['id'], 'route': route, **summarize(measured, seconds)}
                    report['summaries'].append(summary)
                    write(args.out / 'report.json', report)
                    print(f'{case["id"]}/{route}: {summary["quality_pass"]}/{summary["requests"]} correct', flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', type=loopback_url, default='http://127.0.0.1:8000')
    parser.add_argument('--engine-base-url', type=loopback_url, default='http://127.0.0.1:30000')
    parser.add_argument('--seed', type=int, default=20261105)
    parser.add_argument('--repeats', type=int, choices=range(1, 4), default=3)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    key = os.environ.get('LLM_API_KEY') or os.environ.get('API_KEY')
    if not key:
        parser.error('Set API_KEY or LLM_API_KEY privately')
    if args.out.exists():
        parser.error('Output directory must be new; preserve previous attempts')
    config_path = ROOT / 'benchmarks/acceptance.json'
    config = json.loads(config_path.read_text())
    args.out.mkdir(parents=True)
    report = {'schema': 'llm-accuracy-diagnostic/1', 'official_score': False,
              'started_at': datetime.now(timezone.utc).isoformat(), 'complete': False,
              'all_correct': None, 'summaries': [], 'fresh_seed': args.seed,
              'commit_sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'working_tree_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT)),
              'acceptance_sha256': hashlib.sha256(config_path.read_bytes()).hexdigest(),
              'limitation': 'Separate requests can have different cache/batch histories. '
                            'Diagnostic route differences alone do not establish a gateway bug. '
                            'No SLO or official score; rerun full official workload after a candidate change.'}
    try:
        tokenizer = load_tokenizer(config, local_files_only=True)
        asyncio.run(run(args, config, tokenizer, key, report))
        report['complete'] = True
        report['all_correct'] = all(s['quality_pass'] == s['requests'] for s in report['summaries'])
    except (OSError, ValueError, KeyError, httpx.HTTPError) as exc:
        report['error_type'] = type(exc).__name__  # Never log an HTTP body or credentials.
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        write(args.out / 'report.json', report)
    print(json.dumps({'complete': report['complete'], 'all_correct': report['all_correct'],
                      'official_score': False}))
    return 0 if report['complete'] and report['all_correct'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
