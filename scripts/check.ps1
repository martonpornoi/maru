[CmdletBinding()]
param(
    [switch] $SkipPythonTests
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$env:UV_CACHE_DIR = Join-Path $RepositoryRoot ".uv-cache"

function Resolve-RequiredCommand {
    param(
        [Parameter(Mandatory)]
        [string] $Name,
        [string[]] $FallbackPaths = @()
    )

    $Command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -ne $Command) {
        return $Command.Source
    }
    foreach ($FallbackPath in $FallbackPaths) {
        $Candidate = Join-Path $RepositoryRoot $FallbackPath
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            return $Candidate
        }
    }
    throw "Required command '$Name' is unavailable."
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory)]
        [string] $Executable,
        [Parameter(Mandatory)]
        [string[]] $Arguments,
        [string] $WorkingDirectory = $RepositoryRoot
    )

    Push-Location $WorkingDirectory
    try {
        & $Executable @Arguments
        if ($LASTEXITCODE -ne 0) {
            $RenderedArguments = $Arguments -join " "
            throw "Command failed ($LASTEXITCODE): $Executable $RenderedArguments"
        }
    }
    finally {
        Pop-Location
    }
}

$Uv = Resolve-RequiredCommand -Name "uv" -FallbackPaths @(
    ".tools/bin/uv.exe",
    ".tools/uv.exe"
)
$Pnpm = Resolve-RequiredCommand -Name "pnpm"
$Node = Resolve-RequiredCommand -Name "node"
$Git = Resolve-RequiredCommand -Name "git"

Invoke-Checked $Uv @("lock", "--check")
$PackageDistributionDirectory = Join-Path $RepositoryRoot ".local-ci/package-dist"
if (-not $PackageDistributionDirectory.StartsWith(
    $RepositoryRoot + [IO.Path]::DirectorySeparatorChar
)) {
    throw "Package output escaped the repository root."
}
if (Test-Path -LiteralPath $PackageDistributionDirectory) {
    Remove-Item -LiteralPath $PackageDistributionDirectory -Recurse -Force
}
Invoke-Checked $Uv @(
    "build", "--out-dir", $PackageDistributionDirectory
)
Invoke-Checked $Uv @(
    "run", "python", "scripts/verify_package_artifacts.py",
    "--distribution-directory", $PackageDistributionDirectory
)
Invoke-Checked $Pnpm @(
    "--dir", "frontends/staff-console", "install", "--frozen-lockfile",
    "--store-dir", (Join-Path $RepositoryRoot ".pnpm-store")
)
Invoke-Checked $Uv @(
    "run", "pip-audit", "--cache-dir", (Join-Path $RepositoryRoot ".pip-audit-cache")
)
Invoke-Checked $Pnpm @(
    "--dir", "frontends/staff-console", "audit", "--audit-level", "high"
)
Invoke-Checked $Uv @("run", "ruff", "format", "--check", ".")
Invoke-Checked $Uv @("run", "ruff", "check", ".")
Invoke-Checked $Uv @("run", "mypy", "src")
Invoke-Checked $Uv @("run", "python", "scripts/validate_docs.py")
Invoke-Checked $Uv @("run", "pydoclint", "src", "scripts")
Invoke-Checked $Uv @(
    "run", "python", "scripts/validate_python_docstrings.py", "src", "scripts"
)
Invoke-Checked $Uv @(
    "run", "sphinx-build", "-W", "--keep-going", "--fresh-env", "-j", "auto",
    "-d", "docs/_build/doctrees", "-b", "html", "docs", "docs/_build/html"
)
Invoke-Checked $Uv @(
    "run", "python", "src/manage.py", "makemigrations", "--check", "--dry-run",
    "--settings=maru.settings.local"
)
Invoke-Checked $Uv @(
    "run", "python", "src/manage.py", "check", "--settings=maru.settings.local"
)
Invoke-Checked $Uv @("run", "python", "scripts/verify_production_settings.py")
Invoke-Checked $Uv @(
    "run", "python", "src/manage.py", "spectacular", "--file", "openapi.yaml",
    "--validate", "--settings=maru.settings.local"
)
Invoke-Checked $Pnpm @(
    "--dir", "frontends/staff-console", "run", "generate:api"
)
Invoke-Checked $Git @(
    "diff", "--exit-code", "--", "openapi.yaml",
    "frontends/staff-console/src/api/schema.d.ts"
)
Invoke-Checked $Pnpm @(
    "--dir", "frontends/staff-console", "run", "typecheck"
)
Invoke-Checked $Pnpm @(
    "--dir", "frontends/staff-console", "run", "test"
)
Invoke-Checked $Pnpm @(
    "--dir", "frontends/staff-console", "run", "build"
)
Invoke-Checked $Git @(
    "diff", "--exit-code", "--", "src/maru/core/static/staff-console"
)
$UntrackedStaffConsoleFiles = & $Git @(
    "ls-files", "--others", "--exclude-standard", "--",
    "src/maru/core/static/staff-console"
)
if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect generated Staff Console output."
}
if ($UntrackedStaffConsoleFiles) {
    Write-Host ($UntrackedStaffConsoleFiles -join [Environment]::NewLine)
    throw "Generated Staff Console output is not completely committed."
}
if (-not $SkipPythonTests) {
    Invoke-Checked $Uv @(
        "run", "pytest", "--cov=maru", "--cov-report=term-missing"
    )
}
