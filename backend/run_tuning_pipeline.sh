#!/usr/bin/env bash
# RAG 参数调优全流水线编排（Phase 1-6 + baseline + Phase 5 终验）
# 严格串行：Phase 2/3/4/6 通过 _load_best 链式继承上一阶段最优参数。
set -o pipefail
cd "$(dirname "$0")"

PY="$(pwd)/.venv/Scripts/python.exe"
GS="eval_data/golden_set_v2.json"
UD="eval_data/resumes"
TS=$(date +%Y%m%d_%H%M%S)
LOG="experiment_results/pipeline_${TS}.log"
mkdir -p experiment_results

# 清空 Chroma 持久化，确保从干净状态重建索引（避免上轮残留 segment 损坏）
rm -rf chroma_data
echo "PIPELINE START $(date)  log=${LOG}" | tee -a "$LOG"

run_eval() {
  local name="$1"; shift
  echo "===== $name =====" | tee -a "$LOG"
  "$PY" -m rag_tuning.evaluate --golden-set "$GS" --upload-dir "$UD" "$@" 2>&1 | tee -a "$LOG"
  echo "[exit=${PIPESTATUS[0]}] $name" | tee -a "$LOG"
}
run_conc() {
  local name="$1"; shift
  echo "===== $name =====" | tee -a "$LOG"
  "$PY" rag_tuning/run_concurrent.py --golden-set "$GS" --upload-dir "$UD" "$@" 2>&1 | tee -a "$LOG"
  echo "[exit=${PIPESTATUS[0]}] $name" | tee -a "$LOG"
}

run_eval "baseline" --baseline
run_eval "phase1"  --phase 1
run_eval "phase2"  --phase 2
run_conc "phase3"  --phase 3 --concurrency 5
run_conc "phase4"  --phase 4 --concurrency 8
run_conc "phase6"  --phase 6 --concurrency 8
run_eval "phase5"  --phase 5

echo "PIPELINE DONE $(date)" | tee -a "$LOG"
