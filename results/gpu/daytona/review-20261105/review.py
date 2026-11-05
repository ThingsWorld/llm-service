"""Recheck this imported practice run on CPU; exit 0 means evidence consistency.

From the repository root: .venv-benchmark/bin/python \
    results/gpu/daytona/review-20261105/review.py
Uses the frozen tokenizer cache. No GPU, service calls, or official scoring.
"""
from collections import Counter
from datetime import datetime, timezone
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import sys

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
from benchmarks import serving_benchmark as benchmark
from experiments.verify_evidence import verify

BASE = ROOT / 'results/gpu/daytona'
OUT = Path(__file__).resolve().parent
BENCH = BASE / '20261105T082811-bench'
SERVING = BENCH / 'serving'
SMOKE = BASE / '20261105T082520-smoke'
EXPERIMENTS = BASE / '20261105T085121-experiments'
COMMIT = '1cbc12e510e2b8c7daa49ae6b8944e9baff99db3'


def load(path):
    return json.loads(path.read_text())


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def need(condition, message):
    if not condition:
        raise ValueError(message)


config = load(BENCH / 'acceptance.json')
need((BENCH / 'acceptance.json').read_bytes() ==
     (ROOT / 'benchmarks/acceptance.json').read_bytes(), 'Acceptance bytes differ')
for directory in (SMOKE, BENCH, EXPERIMENTS):
    context = load(directory / 'context.json')
    need(context['commit_sha'] == COMMIT and
         (directory / 'commit.txt').read_text().strip() == COMMIT, 'Source mismatch')
    need(context['execution_environment'] == 'daytona' and
         'RTX 4090' in context['gpu'] and context['official_score'] is False,
         'Context mismatch')

tokenizer = benchmark.load_tokenizer(config, local_files_only=True)
target_map = {(t['workload'], t['concurrency']): t for t in config['targets']}
all_summaries, failed_outputs, profile_reports = [], [], []
csv_rows = []
for profile in ('baseline', 'optimized'):
    manifest = load(SERVING / f'{profile}-benchmark-manifest.json')
    need(manifest['acceptance'] == config and
         manifest['config_sha256'] == sha(BENCH / 'acceptance.json') and
         manifest['official_score'] is False, 'Benchmark manifest mismatch')
    identity = load(SERVING / f'{profile}-serving-identity.json')
    need(identity['decoding_policy'] == config['decoding_policy'], 'Sampling drift')
    for field in ('model_id', 'model_revision'):
        need(identity[field] == config[field], 'Model drift')
    raw = rows(SERVING / f'{profile}-serving-raw.jsonl')
    summaries = load(SERVING / f'{profile}-serving-summary.json')
    need(len(raw) == 384 and len({r['id'] for r in raw}) == 384, 'Raw row matrix')
    need(len(rows(SERVING / f'{profile}-serving-warmup.jsonl')) == 48, 'Warmup matrix')
    need(len(summaries) == 8 and len({(s['workload'], s['concurrency'])
                                     for s in summaries}) == 8, 'Summary matrix')
    expected_by_key = {}
    for spec_index, spec in enumerate(config['workloads']):
        for concurrency, repeat in itertools.product(config['concurrencies'], range(3)):
            name = f'{profile}-{spec["id"]}-c{concurrency}-r{repeat}-inputs.json'
            saved = load(SERVING / name)
            salt = manifest['seed'] + spec_index * 1000000 + concurrency * 10000 + repeat * 100
            regenerated = benchmark.build_workload(tokenizer, spec, salt, 16,
                                                   config['workload_version'])
            need(saved == regenerated, 'Saved inputs differ from regenerated workload')
            if profile == 'optimized':
                need((SERVING / name).read_bytes() ==
                     (SERVING / name.replace('optimized-', 'baseline-', 1)).read_bytes(),
                     'Baseline and optimized inputs differ')
            for item in saved:
                expected_by_key[(spec['id'], concurrency, repeat, item['id'])] = item
    observed = set()
    for row in raw:
        key = (row['workload'], row['concurrency'], row['repeat'], row['workload_id'])
        need(key not in observed and key in expected_by_key, 'Duplicate/extra raw request')
        observed.add(key)
        item = expected_by_key[key]
        need(row['input_tokens'] == item['input_tokens'], 'Input token count differs')
        need(row['output_tokens'] == len(tokenizer.encode(row['text'], add_special_tokens=False)),
             'Visible output token count differs')
        quality = row['ok'] and benchmark.output_valid(row['text'], item['expected'])
        need(row['quality_pass'] == quality, 'Quality flag differs')
        if row['ok'] and not quality:
            failed_outputs.append({'id': row['id'], 'profile': profile,
                                   'text': row['text'], 'expected': item['expected']})
    need(observed == set(expected_by_key), 'Missing raw requests')
    for summary in summaries:
        cell = [r for r in raw if (r['workload'], r['concurrency']) ==
                (summary['workload'], summary['concurrency'])]
        computed = benchmark.summarize(cell, summary['window_seconds'],
                                       target_map.get((summary['workload'], summary['concurrency'])))
        for key, value in computed.items():
            if key == 'token_count_source':
                continue  # Public controller copy and repo label differ; numbers are retokenized above.
            actual = summary[key]
            need(math.isclose(value, actual, rel_tol=1e-10, abs_tol=1e-9)
                 if type(value) in (float, int) else actual == value,
                 'Summary recomputation differs: ' + key)
        csv_rows.append({**{k: summary[k] for k in ('profile', 'workload', 'concurrency',
                        'requests', 'successful', 'quality_pass', 'output_tokens_per_second',
                        'ttft_p95_ms', 'tpot_p95_ms', 'e2e_p95_ms', 'success_rate', 'quality_rate',
                        'slo_attainment', 'quality_goodput')},
                         **{field.replace('_ms', '_p50_ms'): benchmark.percentile(
                             [r[field] for r in cell if r['quality_pass']], .5)
                            for field in ('ttft_ms', 'tpot_ms', 'e2e_ms')}})
    profile_reports.append({'profile': profile, 'requests': len(raw),
                            'successful': sum(r['ok'] for r in raw),
                            'quality_pass': sum(r['quality_pass'] for r in raw),
                            'errors': dict(Counter(r['error'] for r in raw if r['error']))})
    all_summaries.extend(summaries)

checks = []
for target in config['targets']:
    summary = next(s for s in all_summaries if s['profile'] == 'optimized' and
                   (s['workload'], s['concurrency']) == (target['workload'], target['concurrency']))
    metrics = []
    for threshold, limit in target.items():
        if not threshold.endswith(('_min', '_max')):
            continue
        metric = threshold.rsplit('_', 1)[0]
        actual = summary[metric]
        passed = actual >= limit if threshold.endswith('_min') else actual <= limit
        metrics.append({'metric': metric, 'actual': actual, 'threshold': limit, 'passed': passed})
    checks.append({'workload': target['workload'], 'concurrency': target['concurrency'],
                   'passed': all(m['passed'] for m in metrics), 'metrics': metrics})

mechanisms = [verify(EXPERIMENTS / case, case, COMMIT) for case in ('kv', 'attention', 'prefix')]
cancellation = load(SMOKE / 'cancellation/results.json')
need(len(cancellation['rows']) == 20 and cancellation['abort_acknowledged_delta'] == 20 and
     all(r['snapshot']['active'] == r['snapshot']['queued'] == 0 for r in cancellation['rows']),
     'Cancellation evidence differs')
for trace in (EXPERIMENTS / 'attention').glob('*.trace.json'):
    declared = load(trace.with_name(trace.name.replace('.trace.json', '-trace-sha256.json')))
    need(sha(trace) in declared.values(), 'Profiler trace hash differs')

report = {'schema': 'daytona-import-review/1', 'reviewed_at': datetime.now(timezone.utc).isoformat(),
          'source_commit_sha': COMMIT, 'official_score': False, 'integrity_pass': True,
          'limitation': 'CPU recheck of user-returned practice artifacts, not independent GPU attestation. '
                        'Summary durations are recorded client windows, not reconstructed wall clocks.',
          'input_regeneration_pass': True, 'independent_retokenization_pass': True,
          'summary_recomputation_pass': True, 'profile_totals': profile_reports,
          'optimized_target_checks': checks, 'all_optimized_targets_pass': all(c['passed'] for c in checks),
          'failed_outputs': failed_outputs, 'mechanisms': mechanisms,
          'pending': ['long/C16 quality 47/48 < 0.99', 'short/C4 output mismatch in both profiles',
                      'prefix-specific SLO uncalibrated', 'isolated auth/ledger overhead comparison',
                      'clean fixed-snapshot rebuild and official grading',
                      'smoke setup idempotency has PID files but no full setup stdout'],
          'artifact_sha256': {str(p.relative_to(BASE)): sha(p)
                              for p in sorted(BASE.rglob('*')) if p.is_file() and OUT not in p.parents}}
archive = ROOT / '.cache/incoming/llm-daytona-results.tar.gz'
if archive.is_file():
    report['received_archive_sha256'] = sha(archive)
(OUT / 'review.json').write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
with (OUT / 'serving.csv').open('w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=list(csv_rows[0]), lineterminator='\n')
    writer.writeheader()
    writer.writerows(csv_rows)
print(json.dumps({'integrity_pass': True, 'all_optimized_targets_pass': report['all_optimized_targets_pass'],
                  'profile_totals': profile_reports, 'mechanism_rows': [m['rows'] for m in mechanisms]}, indent=2))
