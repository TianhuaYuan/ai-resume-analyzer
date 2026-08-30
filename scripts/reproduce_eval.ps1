param(
  [string]$RunJsonl = "",
  [string]$Output = "artifacts/eval_scored.json"
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "[1/3] validating deterministic dataset"
py -3 evals/generate_dataset.py
py -3 evals/validate_dataset.py
py -3 evals/validate_manifests.py
if (!(Test-Path "evals/baselines.json") -or !(Test-Path "evals/model_tiers.json") -or !(Test-Path "evals/fault_matrix.json")) {
  throw "evaluation manifests are incomplete"
}

if ([string]::IsNullOrWhiteSpace($RunJsonl)) {
  Write-Host "[2/3] no model run supplied; dataset-only reproducibility check complete"
  Write-Host "[3/3] provide -RunJsonl artifacts/<run>.jsonl to score a real run"
  exit 0
}

Write-Host "[2/3] scoring run: $RunJsonl"
py -3 evals/score_run.py --run $RunJsonl --out $Output
Write-Host "[3/3] scored artifact: $Output"
