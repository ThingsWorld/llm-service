"""Explicit cancellation probe of an existing service; no machine allocation."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import httpx

async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out;out.mkdir(parents=True,exist_ok=False)
    headers={'Authorization':'Bearer '+os.environ['API_KEY']}
    base='http://127.0.0.1:'+os.environ['PORT'];rows=[]
    async with httpx.AsyncClient(timeout=30,trust_env=False) as client:
        (out/'engine-before.txt').write_text((await client.get('http://127.0.0.1:30000/metrics')).text)
        before=(await client.get(base+'/metrics',headers=headers)).json()['counters']['abort_acknowledged']
        for i in range(20):
            first=None;started=time.monotonic()
            async with client.stream('POST',base+'/v1/chat/completions',headers=headers,json={
                'model':os.environ['MODEL_ID'],'messages':[{'role':'user','content':'Write a very long numbered list of different animals, at least 500 entries.'}],
                'max_tokens':2048,'stream':True}) as response:
                response.raise_for_status();rid=response.headers['X-Request-ID']
                async for line in response.aiter_lines():
                    if not line.startswith('data:'):continue
                    data=line[5:].strip()
                    if data=='[DONE]':break
                    value=json.loads(data)
                    if value.get('error'):raise RuntimeError('upstream error before cancellation content')
                    if any(c.get('delta',{}).get('content') for c in value.get('choices',[])):
                        first=time.monotonic();break
                if first is None:raise RuntimeError('no nonempty content before cancellation')
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                snapshot=(await client.get(base+'/metrics',headers=headers)).json()
                if snapshot['active']==snapshot['queued']==0 and snapshot['counters']['abort_acknowledged']>=before+i+1:break
                await asyncio.sleep(.05)
            else:raise RuntimeError('cancellation did not release gate or acknowledge abort')
            rows.append({'iteration':i,'request_id':rid,'ttft_ms':(first-started)*1000,'snapshot':snapshot})
        final=(await client.get(base+'/metrics',headers=headers)).json()
        (out/'engine-after.txt').write_text((await client.get('http://127.0.0.1:30000/metrics')).text)
        (out/'results.json').write_text(json.dumps({'time':datetime.now(timezone.utc).isoformat(),
            'rows':rows,'final':final,'abort_acknowledged_delta':final['counters']['abort_acknowledged']-before,
            'official_score':False,'limitation':'Gateway acknowledgements plus engine metrics are diagnostic; inspect raw engine evidence.'},indent=2)+'\n')
        assert final['active']==final['queued']==0
        assert final['counters']['abort_acknowledged']-before>=20
        print(json.dumps({'cancellation_cycles':20,'final':final}))
if __name__=='__main__':asyncio.run(main())
