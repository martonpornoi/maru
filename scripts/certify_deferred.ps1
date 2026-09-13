[CmdletBinding()]
param([string] $Base = "origin/main")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$TaskClock = [Diagnostics.Stopwatch]::StartNew()
$TaskRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$TaskArtifacts = [IO.Path]::GetFullPath((Join-Path $TaskRoot ".local-ci"))
if ($TaskArtifacts -ne (Join-Path $TaskRoot ".local-ci") -or
    -not $TaskArtifacts.StartsWith($TaskRoot + [IO.Path]::DirectorySeparatorChar)) {
    throw "Development evidence must remain in the exact repository artifact directory."
}
$TaskUv = Get-Command uv -ErrorAction SilentlyContinue
$TaskUvPath = if ($null -ne $TaskUv) { $TaskUv.Source } else { Join-Path $TaskRoot ".tools/bin/uv.exe" }

function Invoke-DevelopmentCheck {
    param([string] $Executable, [string[]] $Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Development check failed: $Executable $($Arguments -join ' ')" }
}

Push-Location $TaskRoot
try {
    $TaskStatus = & git status --porcelain
    if ($LASTEXITCODE -ne 0 -or $TaskStatus) { throw "Development acceptance requires a clean exact commit." }
    $TaskHead = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $TaskHead -notmatch '^[0-9a-f]{40}$') { throw "Invalid candidate commit." }
    $TaskBase = (& git rev-parse --verify "$Base^{commit}").Trim()
    if ($LASTEXITCODE -ne 0 -or $TaskBase -notmatch '^[0-9a-f]{40}$') { throw "Invalid base commit." }
    $TaskMode = & $TaskUvPath run --locked --all-groups python scripts/ci_development_policy.py mode
    if ($LASTEXITCODE -ne 0 -or $TaskMode -ne "deferred") { throw "Deferred acceptance is not enabled by repository policy." }
    $TaskPolicyHash = (Get-FileHash scripts/ci_postgresql_policy.json -Algorithm SHA256).Hash

    # Preserve prior evidence outside this exact task-owned directory before rerunning.
    if (Test-Path -LiteralPath $TaskArtifacts) { Remove-Item -LiteralPath $TaskArtifacts -Recurse -Force }
    New-Item -ItemType Directory -Path (Join-Path $TaskArtifacts "reports") -Force | Out-Null
    $TaskTemporary = New-Item -ItemType Directory -Path (Join-Path $TaskArtifacts "tmp") -Force
    $env:TEMP = $TaskTemporary.FullName
    $env:TMP = $TaskTemporary.FullName
    $env:TMPDIR = $TaskTemporary.FullName
    $env:MYPY_CACHE_DIR = Join-Path $TaskArtifacts "mypy"
    $env:CI = "true"
    $env:MARU_DATABASE_URL = "postgresql://maru:maru@127.0.0.1:1/maru_unit_no_database"
    Write-Host "Development acceptance for ${TaskHead}: PostgreSQL and combined coverage DEFERRED under #48 / ADR 0100."
    Invoke-DevelopmentCheck $TaskUvPath @("run", "--locked", "python", "scripts/ci_changes.py", "plan", "--base", $TaskBase, "--head", $TaskHead, "--github-output", (Join-Path $TaskArtifacts "plan.outputs"))
    Invoke-DevelopmentCheck $TaskUvPath @("run", "--locked", "python", "scripts/validate_actions_allowlist.py")
    & (Join-Path $PSScriptRoot "check.ps1") -SkipPythonTests
    Invoke-DevelopmentCheck $TaskUvPath @("run", "--locked", "pytest", "tests/unit", "-q", "-p", "no:cacheprovider", "--basetemp=$TaskArtifacts/tmp/unit", "--junitxml=$TaskArtifacts/reports/unit.xml")
    $TaskFinalStatus = & git status --porcelain
    if ($LASTEXITCODE -ne 0 -or $TaskFinalStatus -or (& git rev-parse HEAD).Trim() -ne $TaskHead -or
        (Get-FileHash scripts/ci_postgresql_policy.json -Algorithm SHA256).Hash -ne $TaskPolicyHash) {
        throw "Candidate or policy changed during development acceptance."
    }
    [ordered]@{
        schema_version = 4
        result = "postgresql_deferred"
        development_checks = "passed"
        commit = $TaskHead
        base_commit = $TaskBase
        policy_sha256 = $TaskPolicyHash.ToLowerInvariant()
        restoration_issue = 48
        elapsed_seconds = [math]::Round($TaskClock.Elapsed.TotalSeconds, 3)
        completed_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
        postgresql_executed = $false
        combined_branch_coverage = $null
        measured_timing_headroom = $null
        isolated_postgres_instances = 0
        gates = @("locked_dependencies", "python_static_analysis", "numpy_documentation", "sphinx_html", "django_and_openapi_contracts", "staff_console", "dependency_security", "unit_tests")
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $TaskArtifacts "certification.json") -Encoding utf8
    Write-Host "Development checks passed for $TaskHead; PostgreSQL and combined coverage remain DEFERRED."
}
finally { Pop-Location }
