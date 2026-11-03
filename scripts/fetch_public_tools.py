"""Refresh the nine taskbook GPU clients into a NEW directory; no inference."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile
import urllib.request

BASE='https://agentist.org/lab/llm-lab/'
EXPECTED={'selftest.py','serving_benchmark.py','measurement.py','acceptance.json',
          'prose_workload.py','prose-bank.txt','acceptance-v3.pending.json',
          'acceptance-v4.pending.json','acceptance-v5.pending.json'}

def fetch(name):
    url=BASE+name
    with urllib.request.urlopen(url,timeout=30) as response:
        if response.status!=200 or response.geturl()!=url:
            raise RuntimeError('Unexpected public download status/redirect')
        data=response.read(2000001)
    if len(data)>2000000:raise RuntimeError('Public file too large')
    return data

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path);args=p.parse_args()
    root=args.out
    if root:
        if root.exists() or any(p.is_symlink() for p in [root,*root.parents]):
            p.error('Output must be a new directory without symlink parents')
        root.mkdir(parents=True)
    else:
        cache=Path('.cache');cache.mkdir(exist_ok=True)
        root=Path(tempfile.mkdtemp(prefix='public-tools-v5-',dir=cache))
    raw_manifest=fetch('tools-manifest.json');manifest=json.loads(raw_manifest)
    hashes=manifest.get('files_sha256')
    if (manifest.get('schema')!='llm-public-tools/1' or not isinstance(hashes,dict) or set(hashes)!=EXPECTED
        or any(not isinstance(v,str) or not re.fullmatch('[a-f0-9]{64}',v) for v in hashes.values())):
        raise RuntimeError('Unexpected manifest; do not execute downloaded code')
    for name in sorted(EXPECTED):
        content=fetch(name)
        if hashlib.sha256(content).hexdigest()!=hashes[name]:raise RuntimeError('Hash mismatch: '+name)
        (root/name).write_bytes(content)
    c=json.loads((root/'acceptance.json').read_bytes())
    if (c.get('workload_version')!='typed-json-numbered-records-prose-exact-input/5'
        or c.get('workload_version')!=manifest.get('workload_version')
        or c.get('model_id')!='Qwen/Qwen2.5-7B-Instruct'
        or c.get('model_revision')!='a09a35458c702b33eeacc393d103063234e8bc28'
        or c.get('response_format')!={'type':'json_object'}):
        raise RuntimeError('Current public tools differ from the taskbook; confirm before inference')
    (root/'tools-manifest.json').write_bytes(raw_manifest)
    print(root.resolve())

if __name__=='__main__':main()
