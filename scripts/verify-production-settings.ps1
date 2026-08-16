$ErrorActionPreference = "Stop"

$localUv = Join-Path $PSScriptRoot "..\.tools\bin\uv.exe"
$uvCommand = if (Test-Path -LiteralPath $localUv) { $localUv } else { "uv" }
$localPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$verificationScript = Join-Path $PSScriptRoot "verify_production_settings.py"
$env:UV_CACHE_DIR = Join-Path $PSScriptRoot "..\.uv-cache"
$env:UV_PROJECT_ENVIRONMENT = Join-Path $PSScriptRoot "..\.venv"

if (Test-Path -LiteralPath $localPython) {
    & $localPython $verificationScript
}
else {
    & $uvCommand run python $verificationScript
}
exit $LASTEXITCODE
