"""Recompute two-case causal controls, including incomplete and negative runs.

Run from the repository root using .venv-benchmark/bin/python. This checks
archived observations; it does not execute a GPU or produce an official score.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
from benchmarks.serving_benchmark import load_tokenizer, output_valid

OUT = Path(__file__).resolve().parent
RAW = OUT / 'raw'
config = json.loads((ROOT / 'benchmarks/acceptance.json').read_text())
tokenizer = load_tokenizer(config, local_files_only=True)
inputs = json.loads((RAW / 'input-cases.json').read_text())
known = {x['id']: x for x in inputs['cases']}
for workload, concurrency, repeat, ident in [('short', 4, 1, 'short-3'), ('long', 16, 2, 'long-12')]:
    path = (ROOT / 'results/gpu/daytona/20261105T082811-bench/serving' /
            f'baseline-{workload}-c{concurrency}-r{repeat}-inputs.json')
    original = next(x for x in json.loads(path.read_text()) if x['id'] == ident)
    assert {k: v for k, v in known[ident].items() if k != 'canonical_ids'} == original
    assert known[ident]['canonical_ids'] == tokenizer.apply_chat_template(
        original['messages'], tokenize=True, add_generation_prompt=True)
    assert len(known[ident]['canonical_ids']) == original['input_tokens']

controls = []
for directory in sorted(RAW.glob('*-control-v*')):
    report = json.loads((directory / 'report.json').read_text())
    assert report['official_score'] is False and report['diagnostic_only'] is True
    assert hashlib.sha256((directory / 'probe.py').read_bytes()).hexdigest() == report['control_code_sha256']
    groups = Counter()
    for row in report['rows']:
        assert row['expected'] == known[row['id']]['expected']
        assert row['quality_pass'] == output_valid(row['text'], row['expected'])
        label = row.get('mode', row.get('implementation'))
        groups[(label, 'attempts')] += 1
        groups[(label, 'correct')] += row['quality_pass']
        if 'generated_tokens' in row:
            tokens = row['generated_tokens']
            assert tokenizer.decode(tokens, skip_special_tokens=True) == row['text']
            assert len(tokens) == len(row['choices'])
            assert [x['selected_id'] for x in row['choices']] == tokens
            assert all(x['selected_id'] == x['top'][0]['id'] for x in row['choices'])
        else:
            response = json.loads((directory / f'{label}-{row["id"]}.json').read_text())
            actual = response['text'] if label == 'native-canonical' else response['choices'][0]['message']['content']
            assert actual == row['text']
    if directory.name.startswith('input-'):
        assert report['engine_stopped'] is True
        for comparison in report['input_comparison']:
            assert comparison['ids_equal'] is True
            assert comparison['runtime_ids'] == known[comparison['id']]['canonical_ids']
        if report['complete']:
            assert len(report['rows']) == 8
    elif report['complete']:
        assert len(report['rows']) == 4
    controls.append({'name': directory.name, 'source_commit': report['source_commit'],
        'complete': report['complete'], 'samples': len(report['rows']),
        'correct': sum(x['quality_pass'] for x in report['rows']),
        'error_type': report.get('error_type'),
        'groups': [{'variant': label, 'samples': groups[(label, 'attempts')],
                    'correct': groups[(label, 'correct')]}
                   for label in sorted({x[0] for x in groups})]})
assert len(controls) == 8
assert sum(x['samples'] for x in controls) == 31
assert sum(x['correct'] for x in controls) == 2
assert not any(x['complete'] and x['samples'] == x['correct'] for x in controls)

probabilities = []
base = RAW / 'input-sampling-control-v2'
for ident, needle, offset, expected in [('short-3', '9173', 2, '1'),
                                        ('long-12', '"units": 82', len('"units": '), '7')]:
    response = json.loads((base / f'chat-logprobs-{ident}.json').read_text())
    choice = response['choices'][0]
    text = choice['message']['content']
    events = choice['logprobs']['content']
    # SGLang includes the EOS decision in logprobs but trims it from content.
    assert ''.join(x['token'] for x in events) == text + tokenizer.eos_token
    position = text.rindex(needle) + offset
    cursor = 0
    for index, event in enumerate(events):
        if cursor == position:
            assert len(event['token']) == 1
            target = next(x for x in event['top_logprobs'] if x['token'] == expected)
            probabilities.append({'id': ident, 'output_token_index': index,
                'selected': event['token'], 'expected_next_character': expected,
                'selected_logprob': event['logprob'], 'expected_logprob': target['logprob'],
                'logprob_gap': event['logprob'] - target['logprob']})
            break
        cursor += len(event['token'])
    else:
        raise AssertionError('Missing error-decision logprob')

review = {'schema': 'accuracy-causal-review/1', 'official_score': False,
    'integrity_pass': True, 'all_correct_controls': 0, 'controls': controls,
    'error_decisions': probabilities,
    'limitations': ['Two archived inputs only, not a full matrix or general accuracy estimate.',
        'Independent Hugging Face controls omit JSON grammar and are diagnostic only.',
        'Precision/residual variants change intermediate arithmetic; no production default was changed.',
        'Matching errors across paths do not prove that all possible engine bugs are excluded.',
        'No GPU attestation, threshold confirmation, fixed release, or formal evaluation.'],
    'artifact_sha256': {str(p.relative_to(RAW)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted(RAW.rglob('*')) if p.is_file()}}
(OUT / 'review.json').write_text(json.dumps(review, indent=2, allow_nan=False) + '\n')
print(json.dumps({'integrity_pass': True, 'controls': len(controls),
    'completed_generations': 31, 'correct': 2, 'all_correct_controls': 0}))
