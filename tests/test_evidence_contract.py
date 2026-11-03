"""Synthetic verifier regression tests; these are not GPU experiment evidence."""
import copy
import json
from pathlib import Path
import pytest
from experiments.verify_evidence import verify
from server.config import KV_MODEL,KV_REVISION


def fixture_files(directory):
    manifest={'case':'kv','time':'2026-11-03T00:00:00Z','complete':True,'commit':'a'*40,
        'model':KV_MODEL,'revision':KV_REVISION,'gpu':'synthetic fixture RTX 4090 (not real execution)',
        'cuda':'synthetic','software':{'torch':'synthetic','transformers':'synthetic','sglang':'synthetic'},
        'parameters':{'lengths':[128,512],'decode_tokens':32,'warmup':1,'repeats':3,'dtype':'float32','tf32':False}}
    rows=[{'variant':v,'length':n,'repeat':r,'dtype':'float32','decode_tokens':32,
        'input_hash':'b'*64,'continuation_hash':'c'*64,'elapsed_ms':1,'peak_allocated_bytes':100,
        'peak_reserved_bytes':100,'max_abs_error':.0001,'top1_agreement':1.0,'atol':.001,'rtol':.0001}
        for v in ('cache_on','cache_off') for n in (128,512) for r in range(3)]
    bpt=2*28*2*128*4
    summary={'layers':28,'KV_heads':2,'head_dim':128,'dtype_bytes':4,'KV_bytes_per_token':bpt,
        'measurements':[{'length':n,'KV_bytes_one_request':bpt*(n+32),'KV_bytes_eight_requests':8*bpt*(n+32)} for n in (128,512)]}
    def write():
        (directory/'manifest.json').write_text(json.dumps(manifest))
        (directory/'raw.jsonl').write_text('\n'.join(json.dumps(r) for r in rows)+'\n')
        (directory/'summary.json').write_text(json.dumps(summary))
    write()
    return manifest,rows,summary,write


@pytest.mark.parametrize('mutation',['missing','duplicate','error','top1','capacity','incomplete','nan','hash','symlink'])
def test_current_verifier_rejects_invalid_records(tmp_path,mutation):
    m,rows,s,write=fixture_files(tmp_path)
    assert verify(tmp_path,'kv')['official_score'] is False
    if mutation=='missing':rows.pop()
    if mutation=='duplicate':rows.append(copy.deepcopy(rows[0]))
    if mutation=='error':rows[0]['max_abs_error']=.0011
    if mutation=='top1':rows[0]['top1_agreement']=.99
    if mutation=='capacity':s['measurements'][0]['KV_bytes_one_request']-=32*s['KV_bytes_per_token']
    if mutation=='incomplete':m['complete']=False
    if mutation=='nan':rows[0]['elapsed_ms']=float('nan')
    if mutation=='hash':rows[0]['continuation_hash']='d'*64
    write()
    if mutation=='symlink':
        original=tmp_path/'raw.jsonl';original.rename(tmp_path/'real.jsonl');original.symlink_to(tmp_path/'real.jsonl')
    with pytest.raises(ValueError):verify(tmp_path,'kv')
