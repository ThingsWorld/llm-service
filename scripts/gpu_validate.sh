#!/usr/bin/env bash
# Explicitly run on the user's existing Daytona; never allocates a machine.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
stage="${1:-smoke}"
case "$stage" in smoke|bench|experiments) ;; *) echo 'Usage: bash scripts/gpu_validate.sh smoke|bench|experiments'; exit 2;; esac
: "${API_KEY:?set the ordinary inference key privately}"
: "${ADMIN_API_KEY:?set the independent admin key privately}"
: "${KEY_HASH_SECRET:?set a stable private pepper of at least 32 bytes}"
export DATA_DIR="${DATA_DIR:-$PWD/.data}"
export HOST="${HOST:-127.0.0.1}" PORT="${PORT:-8000}"
export MODEL_ID=Qwen/Qwen2.5-7B-Instruct
export MODEL_REVISION=a09a35458c702b33eeacc393d103063234e8bc28
export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
# Prevent a leftover CPU endpoint from silently becoming the GPU deployment.
unset ENGINE_BASE_URL CONTRACT_TEST
gpu_identity=$(nvidia-smi --query-gpu=name,uuid,driver_version,memory.total --format=csv,noheader)
[[ "$gpu_identity" == *'RTX 4090'* && "$gpu_identity" != *$'\n'* ]] || { echo 'Expected one RTX 4090; stop and confirm hardware'; exit 1; }
git diff --exit-code --quiet
git diff --cached --exit-code --quiet
out="results/daytona/$(date -u +%Y%m%dT%H%M%S)-$stage"
mkdir -p "$out"
git rev-parse HEAD > "$out/commit.txt"
printf '%s\n' "$gpu_identity" > "$out/gpu.txt"
if [[ "$stage" == smoke ]]; then
  BENCH_PROFILE=baseline bash setup.sh
  cp "$DATA_DIR/gateway.pid" "$out/baseline-first.pid"
  BENCH_PROFILE=baseline bash setup.sh
  cmp "$DATA_DIR/gateway.pid" "$out/baseline-first.pid"
  BENCH_PROFILE=optimized bash setup.sh
  .venv/bin/python scripts/check_control_plane.py --base-url "http://127.0.0.1:$PORT" --suite live --out "$out/control-plane-live.json"
  .venv/bin/python -m experiments.cancellation --out "$out/cancellation"
elif [[ "$stage" == bench ]]; then
  : "${BENCH_PYTHON:?provide the pinned 4.51.3 benchmark-client Python; see requirements-benchmark.lock}"
  tools=$(python3 scripts/fetch_public_tools.py)
  cp "$tools/tools-manifest.json" "$out/tools-manifest.json"
  cp "$tools/acceptance.json" "$out/acceptance.json"
  for profile in baseline optimized; do
    BENCH_PROFILE="$profile" bash setup.sh
    "$BENCH_PYTHON" "$tools/serving_benchmark.py" --base-url "http://127.0.0.1:$PORT" \
      --profile "$profile" --config "$tools/acceptance.json" --seed 20261018 \
      --local-files-only --out "$out/serving"
  done
else
  export BENCH_PROFILE=optimized
  MODEL_ID=Qwen/Qwen2.5-1.5B-Instruct MODEL_REVISION=989aa7980e4cf806f80c7fef2b1adb7bc71aa306 \
    bash experiments/run.sh --case kv --out "$out/kv"
  bash experiments/run.sh --case attention --out "$out/attention"
  bash experiments/run.sh --case prefix --out "$out/prefix"
  for name in kv attention prefix; do
    .venv/bin/python -m experiments.verify_evidence --case "$name" --directory "$out/$name" --commit "$(git rev-parse HEAD)"
  done
  bash setup.sh
fi
echo "GPU evidence saved in $out. Interpret measured results; this script grants no official score."
