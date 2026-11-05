"""CPU recheck of company GPU diagnostics; never converts them into formal scores.

Run from repository root with .venv-benchmark/bin/python. Inputs, visible token
counts, typed answers and summaries are recomputed, including failed attempts.
"""
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
from benchmarks.diagnose_accuracy import cases
from benchmarks.serving_benchmark import load_tokenizer, output_valid, summarize

OUT = Path(__file__).resolve().parent
BASE = ROOT / 'results/gpu/self-managed'
config = json.loads((ROOT / 'benchmarks/acceptance.json').read_text())
tokenizer = load_tokenizer(config, local_files_only=True)
reports, table, failures = [], [], []
for directory in sorted(BASE.glob('*/accuracy')):
    report = json.loads((directory / 'report.json').read_text())
    context = json.loads((directory.parent / 'context.json').read_text())
    assert report['complete'] is True and report['official_score'] is False
    assert report['commit_sha'] == context['commit_sha'] == report['runtime']['commit']
    assert context['execution_environment'] == 'self-managed'
    inputs = json.loads((directory / 'inputs.json').read_text())
    assert inputs == cases(config, tokenizer, report['fresh_seed'])
    raw = [json.loads(line) for line in (directory / 'raw.jsonl').read_text().splitlines()]
    assert len(raw) == len({r['id'] for r in raw}) == 384
    expected = {(c['id'], i['id']): i for c in inputs for i in c['items']}
    expected_matrix = {(case, item, route, repeat) for case, item in expected
                       for route in ('gateway', 'engine') for repeat in range(3)}
    assert {(r['case'], r['workload_id'], r['route'], r['repeat']) for r in raw} == expected_matrix
    for row in raw:
        item = expected[(row['case'], row['workload_id'])]
        assert row['expected'] == item['expected']
        assert row['input_tokens'] == item['input_tokens']
        assert row['output_tokens'] == len(tokenizer.encode(row['text'], add_special_tokens=False))
        assert row['quality_pass'] == (row['ok'] and output_valid(row['text'], item['expected']))
        if row['ok'] and not row['quality_pass']:
            failures.append({'run': directory.parent.name, 'id': row['id'],
                             'route': row['route'], 'text': row['text'], 'expected': row['expected']})
    assert len(report['summaries']) == 8
    args = report['engine_arguments']
    for summary in report['summaries']:
        selected = [r for r in raw if (r['case'], r['route']) == (summary['case'], summary['route'])]
        assert len(selected) == 48
        computed = summarize(selected, summary['window_seconds'])
        for field, value in computed.items():
            actual = summary[field]
            assert (math.isclose(value, actual, rel_tol=1e-10, abs_tol=1e-9)
                    if type(value) in (float, int) else value == actual), field
        table.append({'run': directory.parent.name, 'source_commit': report['commit_sha'],
                      'backend': args['attention_backend'], 'fp32_lm_head': args['enable_fp32_lm_head'],
                      'deterministic': args['enable_deterministic_inference'],
                      'triton_reduce_fp32': args.get('triton_attention_reduce_in_fp32', False),
                      'case': summary['case'], 'route': summary['route'], 'attempts': len(selected),
                      'successful': summary['successful'], 'correct': summary['quality_pass'],
                      'client_transport_errors': sum(r['error'] == 'LocalProtocolError' for r in selected)})
    reports.append({'run': directory.parent.name, 'source_commit': report['commit_sha'],
                    'engine_arguments': args, 'attempts': len(raw),
                    'successful': sum(r['ok'] for r in raw), 'correct': sum(r['quality_pass'] for r in raw),
                    'errors': dict(Counter(r['error'] for r in raw if r['error'])),
                    'all_correct': report['all_correct']})
assert reports, 'No imported diagnostic runs'
supplementary = []
supplementary_hashes = {}
env = ROOT / 'results/environment/self-managed-20261105'
known = {i['id']: i['expected'] for c in cases(config, tokenizer, 20261105)
         if c['kind'] == 'archived' for i in c['items']}
for name in ('transformers-control', 'transformers-control-with-runtime'):
    directory = env / name
    if not directory.exists():
        continue
    control = json.loads((directory / 'report.json').read_text())
    assert hashlib.sha256((directory / 'probe.py').read_bytes()).hexdigest() == control['control_code_sha256']
    assert control['official_score'] is False and control['engine_stopped'] is True
    for row in control['rows']:
        assert row['expected'] == known[row['id']]
        assert row['quality_pass'] == output_valid(row['text'], row['expected'])
    supplementary.append({'name': name, 'complete': control['complete'],
                          'samples': len(control['rows']),
                          'correct': sum(r['quality_pass'] for r in control['rows']),
                          'source_commit': control['source_commit']})
    for p in directory.iterdir():
        if p.is_file():
            supplementary_hashes[str(p.relative_to(env))] = hashlib.sha256(p.read_bytes()).hexdigest()
review = {'schema': 'self-managed-accuracy-review/1', 'official_score': False, 'integrity_pass': True,
          'runs': reports, 'failed_outputs': failures,
          'supplementary_controls': supplementary, 'supplementary_artifact_sha256': supplementary_hashes,
          'limitation': '16 distinct inputs per cell repeated three times; separate configurations and '
                        'routes can have different cache/batch histories. This is practice diagnosis, '
                        'not independent GPU attestation or the full 768-request performance matrix.',
          'artifact_sha256': {str(p.relative_to(BASE)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sorted(BASE.rglob('*')) if p.is_file()}}
(OUT / 'review.json').write_text(json.dumps(review, indent=2, allow_nan=False) + '\n')
with (OUT / 'comparison.csv').open('w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=list(table[0]), lineterminator='\n')
    writer.writeheader()
    writer.writerows(table)
print(json.dumps({'integrity_pass': True, 'runs': len(reports), 'attempts': sum(r['attempts'] for r in reports),
                  'successful': sum(r['successful'] for r in reports),
                  'all_correct_runs': sum(r['all_correct'] for r in reports)}, indent=2))
