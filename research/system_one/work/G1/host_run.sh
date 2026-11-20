#!/usr/bin/env bash
# G1: run the four self-hosted decision models on the GPU host through the OrderGuard job wrapper, then pull scores.
# Usage (from research/system_one): bash work/G1/host_run.sh [models...]   default: karpo9 clefflash karpo31 clef27
set -euo pipefail
cd "$(dirname "$0")/../.."
W=/data_ft_7/wilson/wan2.1_robotics_research/workspaces/claude_unrelated_test_20261119/orderguard_s1
MODELS=("$@")
[[ $# -gt 0 ]] || MODELS=(karpo9 clefflash karpo31 clef27)
H=wilson-gpu
log() { echo "$(date -u +%FT%TZ) G1: $*"; }

ssh -o BatchMode=yes -o ConnectTimeout=20 $H "mkdir -p $W/inputs/G1 $W/outputs/G1"
scp -q work/G1/items.jsonl work/G1/gpu_readers.py $H:$W/inputs/G1/
log "inputs copied"

# One-time environment: the models need transformers 5.10+, accelerate and Karpo's own package (Python 3.12+).
ssh $H "cd $W && venv/bin/python -c 'import sys; assert sys.version_info >= (3, 12), sys.version' && \
  (venv/bin/python -c 'import karpo_decision, accelerate' 2>/dev/null || \
   nice -n 10 venv/bin/pip install -q -U 'transformers>=5.10' accelerate safetensors pillow huggingface_hub \
     'karpo-decision @ git+https://github.com/machinepulse-ai/karpo-decision') && \
  venv/bin/python -c 'import torch, transformers, karpo_decision; print(\"torch\", torch.__version__, \"transformers\", transformers.__version__)'"
log "environment ready"

for m in "${MODELS[@]}"; do
  gpus=1; free=24; [[ $m == karpo31 || $m == clef27 ]] && { gpus=2; free=44; }
  for phase in smoke full; do
    extra=""; [[ $phase == smoke ]] && extra="--limit 8 --batch 2"
    log "$m $phase on $gpus card(s)"
    ssh $H "cd $W/outputs/G1 && ORDERGUARD_NUM_GPUS=$gpus ORDERGUARD_MIN_FREE_GIB=$free ORDERGUARD_TIMEOUT_SECONDS=14400 \
      $W/run_job.sh $W/inputs/G1/gpu_readers.py --model $m --items $W/inputs/G1/items.jsonl --out-dir $W/outputs/G1 $extra" \
      || { log "$m $phase FAILED (see the job log on the host); moving on"; break; }
  done
  scp -q "$H:$W/outputs/G1/scores_${m}*.jsonl" work/G1/ 2>/dev/null || true
  log "$m scores pulled: $(wc -l < work/G1/scores_${m}.jsonl 2>/dev/null || echo 0) of $(wc -l < work/G1/items.jsonl)"
done
.venv/bin/python work/G1/score.py | tee work/G1/table.md
