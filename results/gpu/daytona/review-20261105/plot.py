"""Reproduce practice-run figures: .venv-analysis/bin/python <this file>."""
import csv
import json
from pathlib import Path
from statistics import median

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent
BASE = OUT.parent
rows = list(csv.DictReader((OUT / 'serving.csv').open()))
colors = {'baseline': '#52677b', 'optimized': '#087e8b'}
plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})


def save(fig, name):
    fig.savefig(OUT / f'{name}.png', dpi=160, bbox_inches='tight')
    plt.close(fig)


fields = [('output_tokens_per_second', 'Correct output tokens/s'),
          ('ttft_p95_ms', 'TTFT p95 (ms)'), ('tpot_p95_ms', 'TPOT p95 (ms/token)'),
          ('e2e_p95_ms', 'E2E p95 (ms)')]
fig, axes = plt.subplots(2, 4, figsize=(16, 7), layout='constrained')
for i, workload in enumerate(('short', 'long')):
    for j, (field, title) in enumerate(fields):
        ax = axes[i, j]
        for profile, color in colors.items():
            cell = [r for r in rows if r['workload'] == workload and r['profile'] == profile]
            ax.plot([int(r['concurrency']) for r in cell], [float(r[field]) for r in cell],
                    marker='o', label=profile, color=color)
        ax.set(xscale='log', xticks=[1, 4, 8, 16], xlabel='Client concurrency',
               title=f'{workload}: {title}')
        ax.set_xticklabels(['1', '4', '8', '16'])
        ax.grid(alpha=.2)
        if j in (1, 3):
            ax.set_yscale('log')
        if i == j == 0:
            ax.legend()
fig.suptitle('Daytona RTX 4090 practice run | source 1cbc12e510e2\n'
             'Latency percentiles condition on correct successes; see failure rates below. No official score.')
save(fig, 'serving-performance')

fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout='constrained')
for ax, workload in zip(axes, ('short', 'long')):
    for profile, color in colors.items():
        cell = [r for r in rows if r['workload'] == workload and r['profile'] == profile]
        x = [int(r['concurrency']) for r in cell]
        ax.plot(x, [float(r['quality_rate']) * 100 for r in cell], marker='o', color=color,
                label=f'{profile}: correct')
        ax.plot(x, [float(r['success_rate']) * 100 for r in cell], linestyle='--', color=color,
                label=f'{profile}: successful')
    ax.axhline(99, linestyle=':', color='#b23a48', label='99% quality requirement at C8/C16')
    ax.set(title=workload, xlabel='Client concurrency', ylabel='Percent of all attempts',
           ylim=(0, 104), xticks=[1, 4, 8, 16])
    ax.grid(alpha=.2)
axes[0].legend(fontsize=8, loc='lower left')
fig.suptitle('Failures are retained in all-attempt denominators | 48 requests per point')
save(fig, 'serving-quality')

def raw(case):
    return [json.loads(line) for line in
            (BASE / '20261105T085121-experiments' / case / 'raw.jsonl').read_text().splitlines()]


fig, axes = plt.subplots(1, 3, figsize=(14, 4), layout='constrained')
for case, ax, variants, scale in [('kv', axes[0], ('cache_off', 'cache_on'), 1),
                                 ('attention', axes[1], ('math', 'flash'), 1000)]:
    data = raw(case)
    lengths = sorted({r['length'] for r in data})
    for variant in variants:
        ax.plot(lengths, [median(r['elapsed_ms'] for r in data
                                if r['length'] == n and r['variant'] == variant) * scale
                          for n in lengths], marker='o', label=variant)
    ax.set(xlabel='Input length', ylabel='Median elapsed (ms)' if case == 'kv' else 'Median elapsed (us)',
           title='KV: 32 decode tokens, FP32' if case == 'kv' else 'Attention: BF16 SDPA')
    ax.legend()
    ax.grid(alpha=.2)
data = raw('prefix')
labels = [('off', 'shared', 'off/shared'), ('on', 'shared', 'on/shared hot'),
          ('off', 'unique', 'off/unique'), ('on', 'unique', 'on/unique')]
axes[2].bar([label for _, _, label in labels],
            [median(r['ttft_ms'] for r in data if r['variant'] == variant and
                    r['group'] == group and (variant != 'on' or group != 'shared' or r['index'] > 0))
             for variant, group, _ in labels], color=['#52677b', '#087e8b', '#52677b', '#087e8b'])
axes[2].set(title='Prefix: measured TTFT', ylabel='Median TTFT (ms)')
axes[2].tick_params(axis='x', labelrotation=25)
fig.suptitle('Independent mechanism experiments | each uses its own specified workload; no shared SLO')
save(fig, 'mechanisms')
