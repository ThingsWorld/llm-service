"""Synthetic CPU transport checks, never GPU accuracy evidence."""
import argparse
import json

import httpx
import pytest

from benchmarks import diagnose_accuracy as diagnostic
from server.config import MODEL, REVISION


class Tokenizer:
    def encode(self, text, **kwargs): return list(text)


def fixture(monkeypatch, *, engine_fp32=False):
    expected = {'id': 91173, 'city': 'Paris', 'units': 39}
    items = [{'id': name, 'messages': [{'role': 'user', 'content': name}], 'expected': expected,
              'input_tokens': 512, 'max_tokens': 96, 'response_format': {'type': 'json_object'}}
             for name in ('good', 'bad')]
    monkeypatch.setenv('API_KEY', 'synthetic-private-key-for-diagnostic')
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    monkeypatch.setattr(diagnostic, 'load_tokenizer', lambda *a, **kw: Tokenizer())
    monkeypatch.setattr(diagnostic, 'cases', lambda *a: [
        {'id': 'synthetic-only', 'concurrency': 2, 'items': items}])
    calls = []
    def handler(request):
        if request.url.path == '/info':
            return httpx.Response(200, json={'mode': 'native', 'engine_version': '0.5.9',
                'model_id': MODEL, 'model_revision': REVISION, 'profile': 'optimized',
                'config': {'sampling_defaults': 'openai', 'repetition_penalty': 1.0,
                           'top_p': 1.0, 'top_k': -1, 'fp32_lm_head': False}})
        if request.url.path == '/server_info':
            return httpx.Response(200, json={'model_path': MODEL, 'revision': REVISION,
                'version': '0.5.9', 'dtype': 'bfloat16', 'sampling_defaults': 'openai',
                'enable_fp32_lm_head': engine_fp32, 'api_key': 'synthetic-engine-secret'})
        body = json.loads(request.content)
        calls.append(body)
        assert body['temperature'] == 0 and body['response_format'] == {'type': 'json_object'}
        assert 'repetition_penalty' not in body
        if request.url.port == 30000:
            assert 'synthetic-private-key' not in request.headers.get('authorization', '')
        value = {**expected, 'id': 9173} if body['messages'][0]['content'] == 'bad' else expected
        text = json.dumps(value)
        events = [{'choices': [{'delta': {'content': part}, 'finish_reason': None}]}
                  for part in text]  # Split repeated digits across SSE events.
        events.append({'choices': [{'delta': {}, 'finish_reason': 'stop'}],
                       'usage': {'completion_tokens': len(text)}})
        stream = ''.join('data: ' + json.dumps(e) + '\n\n' for e in events) + 'data: [DONE]\n\n'
        return httpx.Response(200, headers={'Content-Type': 'text/event-stream'}, text=stream)
    original_client = httpx.AsyncClient
    monkeypatch.setattr(diagnostic.httpx, 'AsyncClient',
                        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    return calls


def test_diagnostic_preserves_completed_wrong_answers_and_all_attempts(tmp_path, monkeypatch, capsys):
    calls = fixture(monkeypatch)
    out = tmp_path / 'new-output'
    assert diagnostic.main(['--out', str(out), '--repeats', '1']) == 1
    report = json.loads((out / 'report.json').read_text())
    assert report['complete'] is True and report['all_correct'] is False
    assert report['official_score'] is False and len(calls) == 4
    assert all(s['requests'] == s['successful'] == 2 and s['quality_pass'] == 1
               for s in report['summaries'])
    raw = [json.loads(s) for s in (out / 'raw.jsonl').read_text().splitlines()]
    assert len(raw) == 4
    bad = [r for r in raw if not r['quality_pass']]
    assert len(bad) == 2 and all(r['ok'] and r['error'] is None for r in bad)
    assert all(json.loads(r['text'])['id'] == 9173 and r['expected']['id'] == 91173 for r in bad)
    public = (out / 'report.json').read_text() + (out / 'raw.jsonl').read_text() + capsys.readouterr().out
    assert 'synthetic-private-key' not in public and 'synthetic-engine-secret' not in public


def test_diagnostic_rejects_effective_engine_precision_drift_before_inference(tmp_path, monkeypatch):
    calls = fixture(monkeypatch, engine_fp32=True)
    out = tmp_path / 'new-output'
    assert diagnostic.main(['--out', str(out)]) == 1
    report = json.loads((out / 'report.json').read_text())
    assert report['complete'] is False and report['all_correct'] is None and calls == []


@pytest.mark.parametrize('url', ['https://example.com', 'http://127.0.0.1@evil.test',
                               'http://127.0.0.1:8000/path', 'http://localhost:8000?key=private'])
def test_diagnostic_rejects_non_loopback_or_credential_urls(url):
    with pytest.raises(argparse.ArgumentTypeError):
        diagnostic.loopback_url(url)
