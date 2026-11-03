"""HTTP-only self-checks; never starts a GPU or writes an official score.

Mock requires an already running isolated contract gateway and controlled fixture.
Use scripts/local_cpu.py to prepare that environment. Crash injection/disk scanning
run in the external harness, not this HTTP client. Live uses an existing GPU.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit
import uuid
import httpx

ROOT = Path(__file__).resolve().parents[1]
def stamp(): return datetime.now(timezone.utc).isoformat()

class Checks:
    def __init__(self, base, suite):
        self.client = httpx.Client(base_url=base, timeout=40, trust_env=False)
        self.admin = os.environ['ADMIN_API_KEY']; self.boot = os.environ['API_KEY']
        self.fixture = os.environ.get('ENGINE_BASE_URL', '')
        self.control = os.environ.get('FIXTURE_CONTROL_KEY', '')
        self.created = []
        info = self.call('GET', '/info', key=self.boot); self.model = info['model_id']
        if suite == 'mock':
            p = urlsplit(self.fixture)
            assert info.get('mode') == 'contract-test' and self.control
            assert p.scheme == 'http' and p.hostname == '127.0.0.1' and not p.username and not p.password
        else:
            assert info.get('mode') == 'native' and info['engine_version'] not in ('not-started', 'mock-test-only')

    def raw(self, method, path, *, key=None, data=None, idem=None):
        headers = {'Authorization': 'Bearer ' + (key or self.admin)}
        if idem: headers['Idempotency-Key'] = idem
        return self.client.request(method, path, headers=headers, json=data)
    def call(self, method, path, status=200, **kw):
        r = self.raw(method, path, **kw)
        assert r.status_code == status, f'HTTP {r.status_code}: {method} {path}'
        return r.json()
    def configure(self, **kw):
        self.call('POST', self.fixture+'/__fixture/configure', key=self.control,
                  data={'delay':0, 'pause_after_usage':0, 'omit_usage':False, 'fail_before':False, **kw})
    def state(self): return self.call('GET', self.fixture+'/__fixture/state', key=self.control)
    def tenant(self, **kw):
        values = dict(name='self-test-'+uuid.uuid4().hex[:8], balance_micro_usd=100000,
                      token_limit=100000, rpm_limit=1000, concurrency_limit=120)
        values.update(kw)
        tid = self.call('POST', '/admin/tenants', 201, data=values)['tenant_id']
        self.created.append(tid); return tid
    def issue(self, tid, **kw):
        return self.call('POST', f'/admin/tenants/{tid}/keys', 201, data={'name':'self-test', **kw})
    def payload(self, **kw):
        return {'model':self.model, 'messages':[{'role':'user','content':'Reply with hello.'}],
                'max_tokens':80, 'temperature':0, **kw}
    def generate(self, key, **kw):
        return self.raw('POST', '/v1/chat/completions', key=key, data=self.payload(**kw))
    def usage(self, tid): return self.call('GET', '/admin/usage?tenant_id='+tid)
    def stream(self, key, cancel=False):
        content=''; done=finished=False
        with self.client.stream('POST','/v1/chat/completions',headers={'Authorization':'Bearer '+key},
                                json=self.payload(stream=True)) as r:
            assert r.status_code == 200 and 'text/event-stream' in r.headers['content-type']
            rid=r.headers['X-Request-ID']
            for line in r.iter_lines():
                if not line.startswith('data:'): continue
                data=line[5:].strip()
                if data=='[DONE]': done=True; break
                value=json.loads(data); assert 'error' not in value
                for choice in value.get('choices',[]):
                    part=choice.get('delta',{}).get('content') or ''; content+=part
                    finished |= choice.get('finish_reason') is not None
                    if cancel and part: return rid
        assert done and finished and content
        return rid

    def isolation(self):
        a,b=self.tenant(name='Alice'),self.tenant(name='Bob')
        keys=[self.issue(t) for t in (a,a,b,b)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            assert all(r.status_code==200 for r in pool.map(lambda k:self.generate(k['api_key']),keys))
        for t in (a,b):
            rows=self.usage(t)['items']
            assert len(rows)==2 and all(r['tenant_id']==t for r in rows)
            assert {r['key_id'] for r in rows}=={k['key_id'] for k in keys if k['tenant_id']==t}
        assert self.raw('GET','/v1/usage?tenant_id='+b,key=keys[0]['api_key']).status_code==403
        return {'tenants':2,'keys':4,'concurrent_requests':4,'correct_attribution':4}
    def storage(self):
        tid=self.tenant();k=self.issue(tid)
        assert self.generate(k['api_key']).status_code==200
        listed=self.call('GET',f'/admin/tenants/{tid}/keys')
        assert k['api_key'] not in json.dumps(listed) and 'api_key' not in listed['items'][0]
        assert self.raw('POST','/admin/tenants',key=k['api_key'],data={}).status_code in (401,403)
        return {'list_redacted':True,'admin_denied':True,'disk_scan':'external test, not this HTTP client'}
    def rotate(self):
        tid=self.tenant();old=self.issue(tid)
        assert self.generate(old['api_key']).status_code==200
        new=self.call('POST','/admin/keys/'+old['key_id']+'/rotate',data={})
        assert new['key_id']!=old['key_id'] and new['api_key']!=old['api_key']
        assert self.generate(old['api_key']).status_code==401
        assert self.generate(new['api_key']).status_code==200
        assert {r['key_id'] for r in self.usage(tid)['items']}=={old['key_id'],new['key_id']}
        return {'old_http':401,'new_http':200,'history_preserved':True}
    def invalid_keys(self):
        tid=self.tenant();k=self.issue(tid)
        for _ in range(2):self.call('POST','/admin/keys/'+k['key_id']+'/revoke')
        expired=self.issue(tid,expires_at=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat())
        before=len(self.state()['calls'])
        assert self.generate(k['api_key']).status_code==401
        assert self.generate(expired['api_key']).status_code==401
        active=self.issue(tid)
        self.call('PATCH','/admin/tenants/'+tid,data={'status':'disabled'})
        assert self.generate(active['api_key']).status_code==403
        assert len(self.state()['calls'])==before and self.usage(tid)['summary']['cost_micro_usd']==0
        return {'revoked_http':401,'expired_http':401,'disabled_http':403,'model_calls':0}
    def billing(self):
        tid=self.tenant();key=self.issue(tid)['api_key']
        assert self.generate(key).status_code==200
        self.stream(key) # Deliberately no include_usage option.
        u=self.usage(tid)
        assert len(u['items'])==2
        assert all((r['input_tokens'],r['output_tokens'],r['cost_micro_usd'])==(100,50,500) for r in u['items'])
        assert u['summary']['balance_micro_usd']==99000 and u['summary']['reserved_micro_usd']==0
        return {'tokens_each':[100,50],'charges':[500,500],'total':1000}
    def idempotency(self):
        tid=self.tenant();key=self.issue(tid)['api_key'];idem=uuid.uuid4().hex
        self.configure(delay=.5);before=len(self.state()['calls'])
        try:
            with ThreadPoolExecutor(max_workers=20) as pool:
                rs=list(pool.map(lambda _:self.raw('POST','/v1/chat/completions',key=key,data=self.payload(),idem=idem),range(20)))
        finally:self.configure()
        assert sorted(r.status_code for r in rs)==[200]+[409]*19
        assert len(self.state()['calls'])-before==1 and self.usage(tid)['summary']['cost_micro_usd']==500
        assert self.raw('POST','/v1/chat/completions',key=key,data=self.payload(max_tokens=81),idem=idem).status_code==409
        return {'attempts':20,'model_calls':1,'cost':500,'conflicts':19}
    def reservation(self):
        tid=self.tenant(balance_micro_usd=680);key=self.issue(tid)['api_key']
        self.configure(delay=2);before=len(self.state()['calls'])
        try:
            with ThreadPoolExecutor(max_workers=20) as pool:rs=list(pool.map(lambda _:self.generate(key),range(20)))
        finally:self.configure()
        assert sorted(r.status_code for r in rs)==[200]+[402]*19
        s=self.usage(tid)['summary'];assert s['balance_micro_usd']==180 and s['reserved_micro_usd']==0
        assert len(self.state()['calls'])-before==1
        return {'attempts':20,'admitted':1,'quota_rejections':19,'balance':180,
                'control':'fixture delay; explicit signal barrier additionally verified in CPU transaction test'}
    def limits(self):
        tid=self.tenant(rpm_limit=1);keys=[self.issue(tid)['api_key'] for _ in range(2)]
        assert self.generate(keys[0]).status_code==200
        r=self.generate(keys[1]);assert r.status_code==429 and 'Retry-After' in r.headers
        tid=self.tenant(token_limit=150);keys=[self.issue(tid)['api_key'] for _ in range(2)]
        assert self.generate(keys[0],max_tokens=50).status_code==200
        assert self.generate(keys[1],max_tokens=50).status_code==402
        tid=self.tenant(concurrency_limit=1);keys=[self.issue(tid)['api_key'] for _ in range(2)]
        self.configure(delay=1)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:rs=list(pool.map(self.generate,keys))
            assert sorted(r.status_code for r in rs)==[200,429]
        finally:self.configure()
        return {'shared_rpm':429,'shared_token_limit':402,'shared_concurrency':429}
    def cancel(self):
        tid=self.tenant();key=self.issue(tid)['api_key'];self.configure(delay=2)
        try:
            rid=self.stream(key,cancel=True);deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                state=self.state();metrics=self.call('GET','/metrics',key=self.boot)
                if rid in state['aborted'] and metrics['active']==metrics['queued']==0:break
                time.sleep(.05)
            else:raise AssertionError('cancel did not propagate')
            row=next(r for r in self.usage(tid)['items'] if r['request_id']==rid)
            assert row['status'] in ('pending_reconciliation','adjusted_unknown')
            assert row['input_tokens'] is None and row['cost_micro_usd'] is None
            return {'request_id':rid,'abort_observed':True,'active':0,'queued':0,'ledger_status':row['status']}
        finally:self.configure()
    def pricing(self):
        tid=self.tenant();key=self.issue(tid)['api_key'];assert self.generate(key).status_code==200
        self.call('PUT','/admin/pricing',data={'model':self.model,'input_micro_usd_per_token':4,'output_micro_usd_per_token':8})
        try:
            assert self.generate(key).status_code==200
            u=self.usage(tid);assert [r['cost_micro_usd'] for r in u['items']]==[500,800]
            assert len({r['pricing_version'] for r in u['items']})==2 and u['summary']['cost_micro_usd']==1300
            data={'delta_micro_usd':2000,'reason':'synthetic test'};idem=uuid.uuid4().hex
            a=self.call('POST',f'/admin/tenants/{tid}/credits',data=data,idem=idem)
            assert a==self.call('POST',f'/admin/tenants/{tid}/credits',data=data,idem=idem)
            assert self.raw('POST',f'/admin/tenants/{tid}/credits',data={**data,'delta_micro_usd':3000},idem=idem).status_code==409
            assert self.usage(tid)['summary']['balance_micro_usd']==100000-1300+2000
            return {'costs':[500,800],'historic_versions':2,'total':1300,'credit_applied_once':2000}
        finally:
            self.call('PUT','/admin/pricing',data={'model':self.model,'input_micro_usd_per_token':2,'output_micro_usd_per_token':6})
    def live(self):
        evidence=[]
        for name in ('Alice','Bob'):
            tid=self.tenant(name=name);key=self.issue(tid)
            assert self.generate(key['api_key']).status_code==200
            self.stream(key['api_key'])
            r=self.raw('POST','/agent/run',key=key['api_key'],data={'task':'Where is order X91? Return order_id, status and eta_days.',
                'tool_data':{'orders':{'X91':{'status':'shipped','eta_days':6}}}},idem=uuid.uuid4().hex)
            assert r.status_code==200;value=r.json();parent=r.headers['X-Request-ID']
            assert value['answer']=={'order_id':'X91','status':'shipped','eta_days':6}
            u=self.usage(tid);rows=u['items'];child=[row for row in rows if row['parent_request_id']==parent]
            assert len(child)==value['usage']['model_calls']==2
            assert sum(row['output_tokens'] for row in child)==value['usage']['completion_tokens']
            assert len(rows)==5 and all(row['status']=='completed' and row['tenant_id']==tid and row['key_id']==key['key_id'] for row in rows)
            assert sum(row['cost_micro_usd'] for row in rows)==u['summary']['cost_micro_usd']==100000-u['summary']['balance_micro_usd']
            assert u['summary']['reserved_micro_usd']==u['summary']['reserved_tokens']==0
            evidence.append({'tenant_id':tid,'key_id':key['key_id'],'parent_request_id':parent,'model_requests':4,'summary':u['summary']})
        return {'tenants':evidence,'engine':'existing native SGLang'}
    def close(self):
        for tid in self.created:
            try:self.call('PATCH','/admin/tenants/'+tid,data={'status':'disabled'})
            except Exception:pass
        self.client.close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url',default='http://127.0.0.1:8000');p.add_argument('--suite',choices=['mock','live'],required=True)
    p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    if args.out.exists():p.error('Use a new output path')
    if not os.environ.get('API_KEY') or not os.environ.get('ADMIN_API_KEY'):p.error('API_KEY and ADMIN_API_KEY required in environment')
    result={'schema':'credential-service-test/1','suite':args.suite,'official_score':False,
        'commit_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'working_tree_dirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT)),
        'started_at':stamp(),'checks':[],'skipped':[]}
    checks=None
    try:
        checks=Checks(args.base_url,args.suite)
        plan=[(1,'two_tenants',checks.isolation),(2,'key_storage',checks.storage),(3,'rotate',checks.rotate),
            (4,'revoke_expiry_disable',checks.invalid_keys),(5,'exact_billing',checks.billing),
            (6,'concurrent_idempotency',checks.idempotency),(7,'atomic_reservation',checks.reservation),
            (8,'shared_limits',checks.limits),(9,'stream_cancellation',checks.cancel),(11,'price_and_credits',checks.pricing)]
        if args.suite=='mock':
            checks.configure()
            result['skipped']=[{'scenario':10,'reason':'HTTP client cannot SIGKILL; see separate recovery.json from scripts/local_cpu.py'},
                               {'scenario':12,'reason':'Requires real GPU: run --suite live'}]
        else:
            result['skipped']=[{'scenario':n,'reason':'Requires isolated deterministic CPU fixture'} for n in range(1,12)]
            plan=[(12,'live_two_tenant_agent',checks.live)]
        for number,name,function in plan:
            record={'test_id':name,'scenario':number,'expected':'documented HTTP contract assertions','actual':None,'passed':False,'evidence':{}}
            try:record.update(actual='HTTP assertions passed',passed=True,evidence=function())
            except Exception as exc:record['actual']='Failed: '+type(exc).__name__
            result['checks'].append(record)
    except Exception as exc:
        result['checks'].append({'test_id':'prerequisites','expected':'configured own running service','actual':type(exc).__name__,'passed':False,'evidence':{}})
    finally:
        if checks:checks.close()
    result['finished_at']=stamp();args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False)
    summary={'passed':sum(c['passed'] for c in result['checks']),'failed':sum(not c['passed'] for c in result['checks']),
             'skipped':len(result['skipped']),'official_score':False}
    print(json.dumps(summary));return bool(summary['failed'])
if __name__=='__main__':raise SystemExit(main())
