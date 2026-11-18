#!/usr/bin/env bash
set -uo pipefail

W=/data_ft_7/wilson/wan2.1_robotics_research/workspaces/claude_unrelated_test_20261119/orderguard_s1
VENV="$W/venv"

fail() {
  printf 'run_job: %s\n' "$*" >&2
  exit 2
}

[[ $# -ge 1 ]] || fail "usage: $0 SCRIPT.py [SCRIPT_ARGS...]"
[[ -x "$VENV/bin/python" ]] || fail "workspace Python environment is missing: $VENV/bin/python"
command -v nvidia-smi >/dev/null || fail "nvidia-smi is unavailable"
command -v timeout >/dev/null || fail "GNU timeout is unavailable"
command -v flock >/dev/null || fail "flock is unavailable"

requested_script=$1
shift
if [[ "$requested_script" = /* ]]; then
  script_path=$(realpath "$requested_script") || fail "script does not exist: $requested_script"
else
  script_path=$(realpath "$W/$requested_script") || fail "script does not exist: $requested_script"
fi
case "$script_path" in
  "$W"/*) ;;
  *) fail "script must be inside the OrderGuard workspace: $W" ;;
esac
[[ -f "$script_path" ]] || fail "not a file: $script_path"

timeout_seconds=${ORDERGUARD_TIMEOUT_SECONDS:-3600}
[[ "$timeout_seconds" =~ ^[1-9][0-9]*$ ]] || fail "ORDERGUARD_TIMEOUT_SECONDS must be a positive integer"
min_free_gib=${ORDERGUARD_MIN_FREE_GIB:-16}
[[ "$min_free_gib" =~ ^[0-9]+([.][0-9]+)?$ ]] || fail "ORDERGUARD_MIN_FREE_GIB must be a positive number of GiB"
min_free_mib=$(awk -v gib="$min_free_gib" 'BEGIN { if (gib <= 0) exit 2; printf "%.0f", int(gib * 1024 + 0.999999) }') || fail "invalid ORDERGUARD_MIN_FREE_GIB"

mkdir -p "$W/logs" "$W/tmp" "$W/hf_home/hub" "$W/xdg_cache" "$W/outputs"
exec 9>"$W/logs/.run_job.lock"
flock -n 9 || fail "another OrderGuard job is already running"

stamp=$(date -u +%Y%m%dT%H%M%SZ)
job_name=$(basename "$script_path")
job_name=${job_name%.*}
log_file="$W/logs/${stamp}_${job_name}_$$.log"

export ORDERGUARD_WORKSPACE="$W"
export ORDERGUARD_INPUTS="$W/inputs"
export ORDERGUARD_OUTPUTS="$W/outputs"
export ORDERGUARD_LOG="$log_file"
export ORDERGUARD_MIN_FREE_GIB="$min_free_gib"
export HF_HOME="$W/hf_home"
export HF_HUB_CACHE="$W/hf_home/hub"
export HF_ASSETS_CACHE="$W/hf_home/assets"
export TORCH_HOME="$W/hf_home/torch"
export XDG_CACHE_HOME="$W/xdg_cache"
export PIP_CACHE_DIR="$W/pip_cache"
export TMPDIR="$W/tmp"
export CUDA_DEVICE_ORDER=PCI_BUS_ID

printf 'workspace=%s\nscript=%s\ntimeout_seconds=%s\nminimum_free_gib=%s\nlog=%s\n' \
  "$W" "$script_path" "$timeout_seconds" "$min_free_gib" "$log_file" | tee -a "$log_file"

snapshot_gpus() {
  nvidia-smi --query-gpu=index,name,memory.free,utilization.gpu --format=csv,noheader,nounits
}

declare -A a6000_seen stable last_free last_util util_sum util_n
max_mean_util=${ORDERGUARD_MAX_MEAN_UTIL:-50}
sample_count=16
sample_interval=2
printf 'GPU idle scan: %s samples, %s seconds apart (30-second window); selection: lowest mean utilization (refuse if all > ORDERGUARD_MAX_MEAN_UTIL, default 50%%) with >=%s MiB free\n' \
  "$sample_count" "$sample_interval" "$min_free_mib" | tee -a "$log_file"
scan_start_ns=$(date +%s%N)

for ((sample=0; sample<sample_count; sample++)); do
  sample_elapsed_ns=$(( $(date +%s%N) - scan_start_ns ))
  snapshot=$(snapshot_gpus 2>&1) || {
    printf 'nvidia-smi sample %s failed:\n%s\n' "$((sample + 1))" "$snapshot" | tee -a "$log_file" >&2
    exit 2
  }
  printf 'GPU sample %s/%s at +%d.%03ds (index, name, MiB free, utilization %%):\n%s\n' \
    "$((sample + 1))" "$sample_count" "$((sample_elapsed_ns / 1000000000))" "$(((sample_elapsed_ns % 1000000000) / 1000000))" "$snapshot" | tee -a "$log_file"

  unset sample_seen
  declare -A sample_seen=()
  while IFS=, read -r idx name free_mib util_pct; do
    idx=${idx//[[:space:]]/}
    name=$(printf '%s' "$name" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
    free_mib=${free_mib//[[:space:]]/}
    util_pct=${util_pct//[[:space:]]/}
    [[ "$idx" =~ ^[0-9]+$ ]] || continue
    [[ "$name" == *A6000* ]] || continue
    sample_seen["$idx"]=1
    if [[ -z ${a6000_seen[$idx]+x} ]]; then
      a6000_seen["$idx"]=1
      if (( sample == 0 )); then stable["$idx"]=1; else stable["$idx"]=0; fi
    fi
    if [[ "$free_mib" =~ ^[0-9]+$ ]]; then last_free["$idx"]=$free_mib; else last_free["$idx"]=0; fi
    if [[ "$util_pct" =~ ^[0-9]+$ ]]; then last_util["$idx"]=$util_pct; else last_util["$idx"]=999; fi
    if [[ "$util_pct" =~ ^[0-9]+$ ]]; then util_sum["$idx"]=$(( ${util_sum[$idx]:-0} + util_pct )); util_n["$idx"]=$(( ${util_n[$idx]:-0} + 1 )); else stable["$idx"]=0; fi
  done <<< "$snapshot"

  for idx in "${!a6000_seen[@]}"; do
    if [[ -z ${sample_seen[$idx]+x} ]]; then
      stable["$idx"]=0
    fi
  done
  unset sample_seen
  if (( sample + 1 < sample_count )); then
    next_sample_ns=$((scan_start_ns + (sample + 1) * sample_interval * 1000000000))
    sleep_ns=$((next_sample_ns - $(date +%s%N)))
    if (( sleep_ns > 0 )); then
      sleep "$(awk -v ns="$sleep_ns" 'BEGIN { printf "%.3f", ns / 1000000000 }')"
    fi
  fi
done

# Refresh utilization and free memory immediately before selection.
final_snapshot=$(snapshot_gpus 2>&1) || {
  printf 'final nvidia-smi query failed:\n%s\n' "$final_snapshot" | tee -a "$log_file" >&2
  exit 2
}
printf 'Final pre-launch GPU snapshot (index, name, MiB free, utilization %%):\n%s\n' "$final_snapshot" | tee -a "$log_file"
declare -A final_seen=()
while IFS=, read -r idx name free_mib util_pct; do
  idx=${idx//[[:space:]]/}
  name=$(printf '%s' "$name" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
  free_mib=${free_mib//[[:space:]]/}
  util_pct=${util_pct//[[:space:]]/}
  [[ "$idx" =~ ^[0-9]+$ ]] || continue
  [[ "$name" == *A6000* ]] || continue
  final_seen["$idx"]=1
  if [[ "$free_mib" =~ ^[0-9]+$ ]]; then last_free["$idx"]=$free_mib; else last_free["$idx"]=0; fi
  if [[ "$util_pct" =~ ^[0-9]+$ ]]; then last_util["$idx"]=$util_pct; else last_util["$idx"]=999; fi
  if [[ ! "$util_pct" =~ ^[0-9]+$ ]]; then stable["$idx"]=0; fi
done <<< "$final_snapshot"
for idx in "${!a6000_seen[@]}"; do
  if [[ -z ${final_seen[$idx]+x} ]]; then
    stable["$idx"]=0
  fi
done

best_idx=
best_free=-1
best_mean=1000
for idx in "${!a6000_seen[@]}"; do
  free_mib=${last_free[$idx]:-0}
  n=${util_n[$idx]:-0}
  (( n > 0 )) || continue
  mean=$(( ${util_sum[$idx]} / n ))
  printf "gpu %s: mean_util=%s%% over %s samples, free=%s MiB\n" "$idx" "$mean" "$n" "$free_mib" | tee -a "$log_file"
  if [[ ${stable[$idx]:-0} == 1 ]] && (( free_mib >= min_free_mib && mean <= max_mean_util )); then
    if (( mean < best_mean || (mean == best_mean && free_mib > best_free) )); then
      best_idx=$idx; best_free=$free_mib; best_mean=$mean
    fi
  fi
done

[[ -n "$best_idx" ]] || {
  printf "refusing to run: no A6000 had mean utilization <=%s%% over 30 seconds with >=%s MiB free\n" "$max_mean_util" "$min_free_mib" | tee -a "$log_file" >&2
  exit 2
}

export CUDA_VISIBLE_DEVICES="$best_idx"
export ORDERGUARD_GPU_PHYSICAL_INDEX="$best_idx"
printf 'selected_physical_gpu=%s\nselected_free_mib=%s\nCUDA_VISIBLE_DEVICES=%s\nlog=%s\n' \
  "$best_idx" "$best_free" "$CUDA_VISIBLE_DEVICES" "$log_file" | tee -a "$log_file"

cd "$W"
set +e
timeout --signal=TERM --kill-after=30s "${timeout_seconds}s" "$VENV/bin/python" "$script_path" "$@" 2>&1 | tee -a "$log_file"
job_status=${PIPESTATUS[0]}
set -e
printf 'job_exit_status=%s\n' "$job_status" | tee -a "$log_file"
exit "$job_status"

