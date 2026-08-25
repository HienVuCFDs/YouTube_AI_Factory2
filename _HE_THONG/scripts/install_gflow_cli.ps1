param(
    [string]$Version = "0.59.0",
    [switch]$Login
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$venvRoot = Join-Path $projectRoot "_THU_NGHIEM\gflow-cli\.venv"
$venvPython = Join-Path $venvRoot "Scripts\python.exe"
$gflowExe = Join-Path $venvRoot "Scripts\gflow.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    py -3.13 -m venv $venvRoot
}

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install "gflow-cli==$Version"
& $gflowExe --version

if ($Login) {
    & $gflowExe auth login --profile default --browser chrome
} else {
    & $gflowExe auth status --profile default
}
