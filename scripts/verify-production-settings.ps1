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
$env:MARU_IDENTITY_INVITATION_ENCRYPTION_KEY_ID = "verification-key-2026-08"
$env:MARU_IDENTITY_INVITATION_PUBLIC_KEY_B64 = (
    "LS0tLS1CRUdJTiBQVUJMSUMgS0VZLS0tLS0KTUlJQklqQU5CZ2txaGtpRzl3MEJBUUVGQUFPQ0" +
    "FROEFNSUlCQ2dLQ0FRRUF0TVUwd1ZQVVZwSzZEOFU5RXVjOQpIY3Irc2YrL3l5ay9ya3NEYTdT" +
    "YWpDR0lqSDFCOVZKSG0wZnh1am52azk5SWhPNHdkZ3BKeXltNUlIdUd0cmtoCm5JSTlvdHRGRF" +
    "RqWHlSKzZ5Yis3a0NkTlRvU2xoU1lFaitPYnFiTXJaaTBFdHZrRmFTYzl3SHV3WFZVMHFSTG8K" +
    "SHhUdUpwMXkxQmNMY1dLd0xjSU9mUmJMdTJpMEJ3eDN4YytLV3FLUFM5ZVNta0tKUnh3VE1obG" +
    "d3OGNBK3dQUApBRm1uQXZQRnVLRUxnYXVseEw3L2FkdFJsaTEvZVpiNm4wWjZKS09iWGJHWmo1" +
    "bEtPVEw5OHpUWURpRXlzcFdDClF6OTZmd3A5R0xLeHlob0dUSmdaV2JqMlE0ZUoxRjFGMFMraE" +
    "xPZmdtS3RtNkNYQzgzYzRmUWhzQnFzNkdnREwKWFFJREFRQUIKLS0tLS1FTkQgUFVCTElDIEtF" +
    "WS0tLS0tCg=="
)
$env:MARU_IDENTITY_INVITATION_DIGEST_ACTIVE_KEY_ID = (
    "verification-digest-2026-08"
)
$verificationDigestKey = [Convert]::ToBase64String([byte[]](1..32))
$env:MARU_IDENTITY_INVITATION_DIGEST_KEYS_JSON = (
    "{`"verification-digest-2026-08`":`"$verificationDigestKey`"}"
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
