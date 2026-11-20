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
scp -q work/G1/items.jsonl work/G1/gpu_readers.py work/G1/launch.py $H:$W/inputs/G1/
log "inputs copied"

# The models need Python 3.12+ and transformers 5.10+: a separate venv_g1 in the workspace (built once with uv).
ssh $H "$W/venv_g1/bin/python -c 'import torch, transformers, karpo_decision, accelerate; print(\"torch\", torch.__version__, \"transformers\", transformers.__version__)'"
log "environment ready"

for m in "${MODELS[@]}"; do
  gpus=1; free=24; [[ $m == karpo31 || $m == clef27 ]] && { gpus=2; free=36; }
  for phase in smoke full; do
    extra=""; [[ $phase == smoke ]] && extra="--limit 8 --batch 2"
    log "$m $phase on $gpus card(s)"
    # The Hugging Face token (if this Mac is logged in) goes over ssh's stdin: never on a command line other users of
    # the shared host could see with ps, never written to disk there.
    tok="${HF_TOKEN_FILE:-$HOME/.cache/huggingface/token}"
    { [ -s "$tok" ] && cat "$tok" || echo; } | ssh $H "read -r t; [ -n \"\$t\" ] && export HF_TOKEN=\"\$t\"; unset t; cd $W/outputs/G1 && ORDERGUARD_NUM_GPUS=$gpus ORDERGUARD_MIN_FREE_GIB=$free ORDERGUARD_TIMEOUT_SECONDS=14400 \
      $W/run_job.sh $W/inputs/G1/launch.py --model $m --items $W/inputs/G1/items.jsonl --out-dir $W/outputs/G1 $extra" \
      || { log "$m $phase FAILED (see the job log on the host); moving on"; break; }
  done
  scp -q "$H:$W/outputs/G1/scores_${m}*.jsonl" work/G1/ 2>/dev/null || true
  log "$m scores pulled: $(wc -l < work/G1/scores_${m}.jsonl 2>/dev/null || echo 0) of $(wc -l < work/G1/items.jsonl)"
done
.venv/bin/python work/G1/score.py | tee work/G1/table.md
