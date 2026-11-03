"""Real HTTP signal barrier: first content must arrive BEFORE engine completion.

This is controlled CPU inference only. UTF-8 is split across writes, role/content
events are merged, and transport completion is under a test-owned Event.
"""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import socket
import subprocess
import sys
import threading
import time

import httpx
import pytest

from server.config import MODEL, REVISION


@pytest.fixture
def gated_gateway(tmp_path, monkeypatch):
    release = threading.Event()
    calls = []
    aborts = []
    class Engine(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def send_json(self, value):
            data=json.dumps(value).encode()
            self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_GET(self): self.send_json({'status':'ready'})
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path=='/tokenize':return self.send_json({'count':100})
            if self.path=='/abort_request':
                aborts.append(body['rid']);release.set();return self.send_json({'ok':True})
            calls.append(body['rid'])
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            def event(obj):return ('data: '+json.dumps(obj,ensure_ascii=False)+'\n\n').encode()
            try:
                first=event({'choices':[{'delta':{'role':'assistant'},'finish_reason':None}]})
                first+=event({'choices':[{'delta':{'content':'中文首段'},'finish_reason':None}]})
                # Deliberately cut the UTF-8 encoding inside every multibyte char.
                for byte in first:
                    self.wfile.write(bytes([byte]));self.wfile.flush()
                assert release.wait(5), 'test did not release engine finish barrier'
                if body['rid'] in aborts:return
                self.wfile.write(event({'choices':[{'delta':{'content':'，末段'},'finish_reason':'stop'}]}))
                self.wfile.write(event({'choices':[],'usage':{'prompt_tokens':100,'completion_tokens':50,'total_tokens':150}}))
                self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError):pass
    fixture=ThreadingHTTPServer(('127.0.0.1',0),Engine)
    thread=threading.Thread(target=fixture.serve_forever,daemon=True);thread.start()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env={**os.environ,'API_KEY':'cpu-stream-synthetic-key','ENGINE_BASE_URL':f'http://127.0.0.1:{fixture.server_port}',
         'CONTRACT_TEST':'1','MODEL_ID':MODEL,'MODEL_REVISION':REVISION,'RUNTIME_DIR':str(tmp_path/'runtime')}
    process=subprocess.Popen([sys.executable,'-m','uvicorn','server.app:factory','--factory',
                              '--host','127.0.0.1','--port',str(port),'--no-access-log'],env=env,
                              stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    client=httpx.Client(base_url=f'http://127.0.0.1:{port}',trust_env=False,timeout=2,
                        headers={'Authorization':'Bearer '+env['API_KEY']})
    try:
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            assert process.poll() is None
            try:
                if client.get('/healthz').status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(.03)
        else:raise AssertionError('gateway failed to start')
        yield client,release,calls,aborts
    finally:
        release.set();client.close();process.terminate()
        try:process.wait(timeout=8)
        except subprocess.TimeoutExpired:process.kill();process.wait()
        fixture.shutdown();fixture.server_close();thread.join(timeout=2)


def test_first_content_arrives_before_finish_signal_and_utf8_survives(gated_gateway):
    client,release,calls,_=gated_gateway
    seen=[]
    with client.stream('POST','/v1/chat/completions',json={'model':MODEL,
            'messages':[{'role':'user','content':'streaming barrier'}],'max_tokens':80,'stream':True}) as response:
        assert response.status_code==200
        for line in response.iter_lines():
            seen.append(line)
            if '中文首段' in line:
                assert not release.is_set()
                release.set()
    text='\n'.join(seen)
    assert '中文首段' in text and '，末段' in text and 'data: [DONE]' in text
    ledger=client.get('/v1/usage').json()
    assert len(calls)==1 and ledger['items'][0]['cost_micro_usd']==500
    assert client.get('/metrics').json()['active']==0
