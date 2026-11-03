"""Validate current experiment artifacts, never grant scores or attest GPU execution."""
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import re

from server.config import MODEL, REVISION, KV_MODEL, KV_REVISION

LIMIT=256000

def reject_constant(value): raise ValueError('Non-finite JSON value: '+value)
def data(path, *, lines=False):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>LIMIT:
        raise ValueError('Missing/oversized/symlink evidence file: '+path.name)
    text=path.read_text(encoding='utf-8')
    return [json.loads(line,parse_constant=reject_constant) for line in text.splitlines()] if lines else json.loads(text,parse_constant=reject_constant)
def need(value,message):
    if not value: raise ValueError(message)
def number(value): return type(value) in (int,float) and math.isfinite(value)
def digest(value): return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
def sha(value): return isinstance(value,str) and re.fullmatch('[a-f0-9]{64}',value)

def verify(directory,case,commit=None):
    directory=Path(directory)
    need(not any(p.is_symlink() for p in [directory,*directory.parents]),'Symlink output directory')
    m=data(directory/'manifest.json'); rows=data(directory/'raw.jsonl',lines=True); summary=data(directory/'summary.json')
    need(m['case']==case and m['complete'] is True,'Wrong case or incomplete execution')
    need(re.fullmatch('[a-f0-9]{40}',m['commit']) is not None,'Full source commit required')
    if commit: need(m['commit']==commit,'Source commit mismatch')
    need(m['model']==(KV_MODEL if case=='kv' else MODEL),'Wrong experiment model')
    need(m['revision']==(KV_REVISION if case=='kv' else REVISION),'Wrong model revision')
    need(isinstance(m['gpu'],str) and 'RTX 4090' in m['gpu'],'Expected actual RTX 4090 GPU identity')
    need(all(m['software'].get(k) for k in ('torch','transformers','sglang')) and m.get('cuda'),'Missing software/CUDA versions')
    p=m['parameters']
    fields={'kv':('variant','length','repeat'),'attention':('variant','length','repeat'),
            'prefix':('variant','group','repeat','index')}[case]
    variants={'kv':['cache_on','cache_off'],'attention':['math','flash'],'prefix':['on','off']}[case]
    expected=set(itertools.product(variants,*([['shared','unique'],range(3),range(8)] if case=='prefix' else
                                               [[128,512,1024] if case=='attention' else [128,512],range(3)])))
    keys=[tuple(r[k] for k in fields) for r in rows]
    need(len(keys)==len(set(keys)) and set(keys)==expected,'Missing/duplicate/extra raw matrix rows')
    for r in rows:
        if case!='prefix':
            need(number(r['elapsed_ms']) and r['elapsed_ms']>0,'Invalid GPU timing')
            need(all(type(r[k]) is int and r[k]>=0 for k in ('peak_allocated_bytes','peak_reserved_bytes')),'Invalid memory counters')
            need(number(r['max_abs_error']) and r['max_abs_error']>=0,'Invalid numerical error')
    if case=='kv':
        need(p['lengths']==[128,512] and p['decode_tokens']==32 and p['warmup']>=1 and p['repeats']==3 and p['dtype']=='float32','Wrong KV parameters')
        need(p.get('tf32') is False,'FP32 KV must disable TF32')
        for r in rows:
            need(r['dtype']=='float32' and r['decode_tokens']==32 and r['atol']==.001,'Wrong KV precision/decode contract')
            need(r['max_abs_error']<=.001 and r['top1_agreement']==1.0,'KV logits/top1 failed')
            need(sha(r['input_hash']) and sha(r['continuation_hash']),'Missing input/continuation hash')
        for length in (128,512):
            need(len({(r['input_hash'],r['continuation_hash']) for r in rows if r['length']==length})==1,'KV inputs differ')
        bpt=2*28*2*128*4
        need((summary['layers'],summary['KV_heads'],summary['head_dim'],summary['dtype_bytes'],summary['KV_bytes_per_token'])==(28,2,128,4,bpt),'KV capacity formula mismatch')
        need({r['length'] for r in summary['measurements']}=={128,512} and len(summary['measurements'])==2,'KV capacity matrix')
        for r in summary['measurements']:
            need(r['KV_bytes_one_request']==bpt*(r['length']+32) and r['KV_bytes_eight_requests']==8*bpt*(r['length']+32),'KV capacity excludes decode/incorrect bytes')
    elif case=='attention':
        need(p['warmup']>=5 and p['groups']==3 and p['iterations']==10 and p['dtype']=='bfloat16' and p['causal'] is True and p['dropout']==0,'Wrong attention parameters')
        for length in (128,512,1024):
            group=[r for r in rows if r['length']==length]
            need(len({tuple(r['input_hashes']) for r in group})==1,'Attention tensors differ')
            for r in group:
                need(r['shape']==r['output_shape']==[1,8,length,64] and len(r['input_hashes'])==3 and all(sha(x) for x in r['input_hashes']),'Invalid Q/K/V shape/hash')
                need(r['max_abs_error']<=.02 and r['atol']==r['rtol']==.02,'Attention numerical tolerance failed')
            for variant in variants:
                operators=data(directory/f'{variant}-{length}-operators.json')
                need(isinstance(operators,list) and all(isinstance(o,str) for o in operators),'Missing profiler operators')
                marker='_scaled_dot_product_flash_attention' if variant=='flash' else '_scaled_dot_product_attention_math'
                need(any(marker in o for o in operators),'Requested attention backend not evidenced')
    else:
        need(p['prefix_tokens']==512 and p['requests']==8 and p['repeats']==3,'Wrong prefix parameters')
        inputs=data(directory/'inputs.json')
        need(set(inputs)=={'shared','unique'} and all(len(g)==8 for g in inputs.values()),'Prefix input matrix')
        need(len({tuple(x[:512]) for x in inputs['shared']})==1 and len({tuple(x[:512]) for x in inputs['unique']})==8,'Shared/unique prefix identities')
        for ids in itertools.chain(*inputs.values()):
            need(len(ids)>512 and all(type(i) is int and i>=0 for i in ids),'Invalid prefix token IDs')
        for r in rows:
            ids=inputs[r['group']][r['index']];cached=r['cached_tokens']
            need(r['input_hash']==digest(ids) and r['prefix_hash']==digest(ids[:512]) and r['prefix_length']==512 and r['input_tokens']==len(ids),'Prefix hashes/input count mismatch')
            need(type(cached) is int and cached>=0,'Missing real cached_tokens counter')
            expected_hit=(cached==0 if r['variant']=='off' else cached>=512 if r['group']=='shared' and r['index']>0 else cached<512)
            need(expected_hit,'Cache hit invariant failed')
            need(r['transport_ok'] is True and r['output'].strip()=='OK','Prefix transport/output failed')
            need(number(r['ttft_ms']) and r['ttft_ms']>=0 and number(r['e2e_ms']) and r['e2e_ms']>=r['ttft_ms'],'Prefix timing missing')
            need(r['cache_state']==('cold' if r['index']==0 else 'hot' if r['variant']=='on' and r['group']=='shared' else 'subsequent'),'Prefix cold/hot label mismatch')
        for variant,group,repeat in itertools.product(variants,['shared','unique'],range(3)):
            need(data(directory/f'{variant}-{group}-{repeat}-flush.json')['status']==200,'Cache flush not acknowledged')
    return {'schema':'llm-experiment-verification/1','case':case,'commit_sha':m['commit'],'rows':len(rows),
            'passed':True,'official_score':False,'limitation':'Validates recorded artifacts; does not independently attest GPU execution or grant points.'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--case',choices=['kv','prefix','attention'],required=True)
    p.add_argument('--directory',type=Path,required=True);p.add_argument('--commit');args=p.parse_args()
    try: result=verify(args.directory,args.case,args.commit)
    except (ValueError,KeyError,TypeError,OSError) as exc:
        result={'case':args.case,'passed':False,'official_score':False,'reason':str(exc)}
    print(json.dumps(result,allow_nan=False));return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
