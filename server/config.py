import os
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'Qwen/Qwen2.5-7B-Instruct'
REVISION = 'a09a35458c702b33eeacc393d103063234e8bc28'

KV_MODEL = 'Qwen/Qwen2.5-1.5B-Instruct'
KV_REVISION = '989aa7980e4cf806f80c7fef2b1adb7bc71aa306'

def configuration():
    profile = os.environ.get('BENCH_PROFILE', 'baseline')
    if profile not in ('baseline', 'optimized'):
        raise ValueError('unknown profile')
    cfg = yaml.safe_load((ROOT / 'configs' / (profile + '.yaml')).read_text())
    for env, field, minimum, maximum in [('MAX_RUNNING_REQUESTS', 'max_running_requests', 1, 32),
                                 ('GATEWAY_SLOTS', 'gateway_slots', 1, 64),
                                 ('GATEWAY_QUEUE', 'gateway_queue', 0, 112)]:
        if env in os.environ:
            value = int(os.environ[env])
            if not minimum <= value <= maximum:
                raise ValueError(env + ' outside supported range')
            cfg[field] = value
    if cfg['gateway_slots'] + cfg['gateway_queue'] > 120:
        raise ValueError('gateway_slots + gateway_queue must not exceed 120')
    if 'PREFIX_CACHE' in os.environ:
        if os.environ['PREFIX_CACHE'] not in ('0', '1'):
            raise ValueError('PREFIX_CACHE must be 0 or 1')
        cfg['prefix_cache'] = os.environ['PREFIX_CACHE'] == '1'
    if 'ATTENTION_BACKEND' in os.environ:
        if os.environ['ATTENTION_BACKEND'] not in ('triton', 'flashinfer'):
            raise ValueError('Unsupported ATTENTION_BACKEND')
        cfg['attention_backend'] = os.environ['ATTENTION_BACKEND']
    # Opt-in numerical diagnostic: keep model weights/BF16 contract and sampling
    # unchanged; SGLang computes the final vocabulary projection in FP32.
    for name, field in [('FP32_LM_HEAD', 'fp32_lm_head'),
                        ('DETERMINISTIC_INFERENCE', 'deterministic_inference'),
                        ('TRITON_ATTENTION_REDUCE_IN_FP32', 'triton_attention_reduce_in_fp32')]:
        value = os.environ.get(name, '0')
        if value not in ('0', '1'):
            raise ValueError(name + ' must be 0 or 1')
        cfg[field] = value == '1'
    if cfg['triton_attention_reduce_in_fp32'] and cfg['attention_backend'] != 'triton':
        raise ValueError('TRITON_ATTENTION_REDUCE_IN_FP32 requires ATTENTION_BACKEND=triton')
    if cfg['deterministic_inference'] and cfg['attention_backend'] == 'flashinfer' and cfg['prefix_cache']:
        raise ValueError('Deterministic FlashInfer disables Radix Cache; use Triton or explicitly disable the cache')
    # These are SGLang 0.5.9's effective defaults under the explicit OpenAI policy.
    # The API accepts temperature overrides; only its request default is zero.
    if cfg.get('sampling_defaults') == 'openai':
        cfg.update(repetition_penalty=1.0, top_p=1.0, top_k=-1,
                   request_temperature_default=0.0)
    return profile, cfg
