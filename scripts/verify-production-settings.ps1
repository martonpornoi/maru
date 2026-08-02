$ErrorActionPreference = "Stop"

$localUv = Join-Path $PSScriptRoot "..\.tools\bin\uv.exe"
$uvCommand = if (Test-Path -LiteralPath $localUv) { $localUv } else { "uv" }
$localPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$env:UV_CACHE_DIR = Join-Path $PSScriptRoot "..\.uv-cache"
$env:UV_PROJECT_ENVIRONMENT = Join-Path $PSScriptRoot "..\.venv"

$env:MARU_SETTINGS_MODULE = "maru.settings.production"
$env:MARU_SECRET_KEY = "verification-only-not-a-production-secret-at-least-50-characters"
$env:MARU_ALLOWED_HOSTS = "maru.example.invalid"
$env:MARU_DATABASE_URL = "postgresql://maru:maru@127.0.0.1:5432/maru"
$env:MARU_RUNTIME_DATABASE_ROLE = "maru_runtime"
$env:MARU_PUBLIC_BASE_URL = "https://maru.example.invalid"
$env:MARU_DEFAULT_FROM_EMAIL = "registration@example.com"
$env:MARU_EMAIL_HOST = "smtp.example.invalid"
$env:MARU_EMAIL_PORT = "587"
$env:MARU_EMAIL_HOST_USER = "verification-user"
$env:MARU_EMAIL_HOST_PASSWORD = "verification-password"
$env:MARU_EMAIL_USE_TLS = "true"
$env:MARU_EMAIL_USE_SSL = "false"
$env:MARU_CSRF_TRUSTED_ORIGINS = (
    "https://maru.example.invalid,https://register.maru.example.invalid"
)
$env:MARU_PAYMENT_RETURN_ORIGINS = "https://register.maru.example.invalid"
$env:MARU_PAYMENT_PROVIDER_HOSTS = (
    "payments.example.invalid,checkout.example.invalid"
)
$env:MARU_REGISTRATION_CLIENT_ORIGINS = (
    "https://register.maru.example.invalid"
)
$env:MARU_MEDIA_SCANNER = "clamav"
$env:MARU_MEDIA_SCANNER_HOST = "scanner.internal"
$env:MARU_OFFLINE_MANIFEST_SECRET = (
    "verification-only-offline-manifest-secret-value"
)
foreach ($exactProvenanceRequired in @("false", "true")) {
    $env:MARU_REQUIRE_EXACT_AUTHORITY_PROVENANCE = $exactProvenanceRequired
    if (Test-Path -LiteralPath $localPython) {
        & $localPython src/manage.py check --deploy
    }
    else {
        & $uvCommand run python src/manage.py check --deploy
    }
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
