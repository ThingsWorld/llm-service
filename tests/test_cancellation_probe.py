"""Check that the explicit GPU probe ignores role/empty events using CPU HTTP mocks."""
import asyncio
import json
import sys
from experiments import cancellation


def test_probe_cancels_only_after_nonempty_content_and_measures_counter_delta(tmp_path,monkeypatch):
    class Response:
        text='synthetic metrics, not GPU evidence'
        def __init__(self,value):self.value=value
        def json(self):return self.value
    class Client:
        def __init__(self,*a,**kw):self.closed=7;self.streams=[]
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def get(self,*a,**kw):
            return Response({'active':0,'queued':0,'counters':{'abort_acknowledged':self.closed}})
        def stream(self,*a,**kw):
            owner=self
            class Stream:
                status_code=200
                headers={'X-Request-ID':'synthetic-request'}
                def raise_for_status(self):pass
                async def __aenter__(self):return self
                async def __aexit__(self,*args):
                    assert self.nonempty_seen
                    owner.closed+=1
                async def aiter_lines(self):
                    self.nonempty_seen=False
                    yield 'data: '+json.dumps({'choices':[{'delta':{'role':'assistant','content':''}}]})
                    self.nonempty_seen=True
                    yield 'data: '+json.dumps({'choices':[{'delta':{'content':'first'}}]})
                    raise AssertionError('probe should cancel immediately after first content')
            stream=Stream();self.streams.append(stream);return stream
    monkeypatch.setattr(cancellation.httpx,'AsyncClient',Client)
    monkeypatch.setenv('API_KEY','synthetic-cpu-test-key')
    monkeypatch.setenv('PORT','8000');monkeypatch.setenv('MODEL_ID','synthetic-model')
    out=tmp_path/'probe';monkeypatch.setattr(sys,'argv',['cancellation','--out',str(out)])
    asyncio.run(cancellation.main())
    result=json.loads((out/'results.json').read_text())
    assert result['abort_acknowledged_delta']==20 and len(result['rows'])==20
    assert result['official_score'] is False
