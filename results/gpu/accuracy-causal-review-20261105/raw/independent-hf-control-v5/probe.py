"""Independent fixed-model BF16 diagnostic, no SGLang and no answer repair."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

os.environ['HF_HUB_OFFLINE']='1'
os.environ['TOKENIZERS_PARALLELISM']='false'
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.insert(0,str(Path.cwd()))
from benchmarks.serving_benchmark import output_valid
from server.config import MODEL, REVISION

out=Path('results/environment/self-managed-20261105/independent-hf-control-v5')
out.mkdir(parents=True,exist_ok=False)
cases=json.loads((Path.home()/'.cache/llm-accuracy-tools/input-sampling-cases.json').read_text())
report={'official_score':False,'diagnostic_only':True,'complete':False,'rows':[],
        'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'control_code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'model_id':MODEL,'revision':REVISION,'dtype':'bfloat16',
        'versions':{'torch':torch.__version__,'transformers':__import__('transformers').__version__},
        'limitation':'Independent Transformers generation without JSON grammar. Diagnostic only; not the service or an acceptance run.'}
model=None
try:
    assert torch.cuda.is_available()
    assert torch.cuda.mem_get_info()[0] > 20*1024**3
    torch.set_num_threads(8)
    torch.backends.cuda.matmul.allow_tf32=False
    tokenizer=AutoTokenizer.from_pretrained(MODEL,revision=REVISION,local_files_only=True)
    start=time.monotonic()
    model=AutoModelForCausalLM.from_pretrained(MODEL,revision=REVISION,local_files_only=True,
        torch_dtype=torch.bfloat16,attn_implementation='eager').to('cuda:0').eval()
    report['load_seconds']=time.monotonic()-start
    report['residual_dtype']='float32'
    report['weight_dtype']='bfloat16'
    original_embedding=model.model.embed_tokens.forward
    def embedding_fp32(*args, **kwargs):
        return original_embedding(*args, **kwargs).float()
    model.model.embed_tokens.forward=embedding_fp32
    import types
    def norm_to_bf16(module, hidden):
        values=hidden.float()
        values=values*torch.rsqrt(values.pow(2).mean(-1,keepdim=True)+module.variance_epsilon)
        return (module.weight.float()*values).to(torch.bfloat16)
    for module in model.modules():
        if type(module).__name__=='Qwen2RMSNorm':
            module.forward=types.MethodType(norm_to_bf16,module)
    for implementation in ['eager','sdpa']:
        model.set_attn_implementation(implementation)
        for item in cases['cases']:
            ids=torch.tensor([item['canonical_ids']],dtype=torch.long,device='cuda')
            start=time.monotonic()
            with torch.inference_mode():
                output=model.generate(input_ids=ids,attention_mask=torch.ones_like(ids),
                    max_new_tokens=item['max_tokens'],do_sample=False,repetition_penalty=1.0,
                    temperature=1.0,top_p=1.0,top_k=50,return_dict_in_generate=True,output_scores=True)
            torch.cuda.synchronize()
            tokens=output.sequences[0,len(item['canonical_ids']):].tolist()
            text=tokenizer.decode(tokens,skip_special_tokens=True)
            choices=[]
            for token,scores in zip(tokens,output.scores):
                values,indices=torch.log_softmax(scores[0].float(),dim=-1).topk(5)
                choices.append({'selected_id':token,'selected_text':tokenizer.decode([token]),
                    'top':[{'id':i,'text':tokenizer.decode([i]),'logprob':v}
                           for i,v in zip(indices.tolist(),values.tolist())]})
            row={'id':item['id'],'implementation':implementation,'text':text,'expected':item['expected'],
                 'quality_pass':output_valid(text,item['expected']),'elapsed_seconds':time.monotonic()-start,
                 'generated_tokens':tokens,'choices':choices}
            report['rows'].append(row)
            (out/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
            print(json.dumps({k:v for k,v in row.items() if k not in ('choices','generated_tokens')}),flush=True)
            del output,ids
    report['complete']=True
except (Exception,KeyboardInterrupt) as exc:
    report['error_type']=type(exc).__name__
    report['error_message']=str(exc)[:300]
finally:
    del model
    torch.cuda.empty_cache()
    report['gpu_free_bytes_after_cleanup']=torch.cuda.mem_get_info()[0]
    (out/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
print(json.dumps({'complete':report['complete'],'correct':sum(r['quality_pass'] for r in report['rows'])}),flush=True)
raise SystemExit(0 if report['complete'] and all(r['quality_pass'] for r in report['rows']) else 1)
