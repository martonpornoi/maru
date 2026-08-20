[CmdletBinding()]
param(
    [ValidateRange(1, 12)]
    [int] $IntegrationShards = 8
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$env:UV_CACHE_DIR = Join-Path $RepositoryRoot ".uv-cache"
$ArtifactRoot = [IO.Path]::GetFullPath((Join-Path $RepositoryRoot ".local-ci"))
$RepositoryPrefix = [IO.Path]::GetFullPath($RepositoryRoot).TrimEnd(
    [IO.Path]::DirectorySeparatorChar
) + [IO.Path]::DirectorySeparatorChar
if (-not $ArtifactRoot.StartsWith($RepositoryPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Certification artifacts must remain inside the repository."
}

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
        [string[]] $Arguments
    )

    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        $RenderedArguments = $Arguments -join " "
        throw "Command failed ($LASTEXITCODE): $Executable $RenderedArguments"
    }
}

function Start-IsolatedPostgres {
    param(
        [Parameter(Mandatory)]
        [string] $Name
    )

    Write-Host "Starting isolated PostgreSQL container $Name..."
    Invoke-Checked $Docker @(
        "run", "--detach", "--rm", "--name", $Name,
        "--env", "POSTGRES_DB=maru",
        "--env", "POSTGRES_USER=maru",
        "--env", "POSTGRES_PASSWORD=maru",
        "--publish", "127.0.0.1::5432",
        "--health-cmd", "pg_isready -U maru -d maru",
        "--health-interval", "2s",
        "--health-timeout", "3s",
        "--health-retries", "30",
        $PostgresImage
    )

    $Healthy = $false
    for ($Attempt = 1; $Attempt -le 90; $Attempt += 1) {
        $Health = (& $Docker "inspect" "--format" "{{.State.Health.Status}}" $Name).Trim()
        if ($LASTEXITCODE -ne 0) {
            throw "Could not inspect PostgreSQL container $Name."
        }
        if ($Health -eq "healthy") {
            $Healthy = $true
            break
        }
        Start-Sleep -Seconds 1
    }
    if (-not $Healthy) {
        throw "PostgreSQL container $Name did not become healthy."
    }

    $PublishedPort = (& $Docker "port" $Name "5432/tcp" | Select-Object -First 1).Trim()
    if ($LASTEXITCODE -ne 0 -or $PublishedPort -notmatch "(?<port>[0-9]+)$") {
        throw "Could not resolve the published port for $Name."
    }
    return [int] $Matches.port
}

function Start-TestProcess {
    param(
        [Parameter(Mandatory)]
        [string] $Name,
        [Parameter(Mandatory)]
        [string[]] $Arguments,
        [Parameter(Mandatory)]
        [int] $DatabasePort
    )

    $StandardOutput = Join-Path $LogDirectory "$Name.stdout.log"
    $StandardError = Join-Path $LogDirectory "$Name.stderr.log"
    $CoverageFile = Join-Path $CoverageDirectory ".coverage.$Name"
    $Environment = @{
        COVERAGE_FILE = $CoverageFile
        MARU_DATABASE_URL = "postgresql://maru:maru@127.0.0.1:$DatabasePort/maru"
    }
    $Process = Start-Process `
        -FilePath $Python `
        -ArgumentList $Arguments `
        -WorkingDirectory $RepositoryRoot `
        -NoNewWindow `
        -PassThru `
        -RedirectStandardOutput $StandardOutput `
        -RedirectStandardError $StandardError `
        -Environment $Environment
    return [PSCustomObject]@{
        Name = $Name
        Process = $Process
        StandardOutput = $StandardOutput
        StandardError = $StandardError
    }
}

function Show-TestLog {
    param(
        [Parameter(Mandatory)]
        [PSCustomObject] $Job
    )

    Write-Host "`n===== $($Job.Name) standard output ====="
    if (Test-Path -LiteralPath $Job.StandardOutput) {
        Get-Content -LiteralPath $Job.StandardOutput
    }
    if ((Test-Path -LiteralPath $Job.StandardError) -and
        (Get-Item -LiteralPath $Job.StandardError).Length -gt 0) {
        Write-Host "`n===== $($Job.Name) standard error ====="
        Get-Content -LiteralPath $Job.StandardError
    }
}

$Uv = Resolve-RequiredCommand -Name "uv" -FallbackPaths @(
    ".tools/bin/uv.exe",
    ".tools/uv.exe"
)
$Docker = Resolve-RequiredCommand -Name "docker"
$Git = Resolve-RequiredCommand -Name "git"
$PowerShell = Resolve-RequiredCommand -Name "pwsh"
$PostgresImage = "postgres:17.11-alpine@sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73"

Push-Location $RepositoryRoot
$Containers = [Collections.Generic.List[string]]::new()
try {
    $WorkingTree = (& $Git "status" "--porcelain").Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect the Git working tree."
    }
    if ($WorkingTree) {
        throw "Certification requires a clean working tree so evidence matches one exact commit."
    }

    $Commit = (& $Git "rev-parse" "HEAD").Trim()
    if ($LASTEXITCODE -ne 0 -or $Commit -notmatch "^[0-9a-f]{40}$") {
        throw "Could not resolve the exact Git commit under certification."
    }

    if (Test-Path -LiteralPath $ArtifactRoot) {
        Remove-Item -LiteralPath $ArtifactRoot -Recurse -Force
    }
    $CoverageDirectory = New-Item -ItemType Directory -Path (
        Join-Path $ArtifactRoot "coverage-parts"
    ) -Force
    $LogDirectory = New-Item -ItemType Directory -Path (
        Join-Path $ArtifactRoot "logs"
    ) -Force
    $ReportDirectory = New-Item -ItemType Directory -Path (
        Join-Path $ArtifactRoot "reports"
    ) -Force

    Write-Host "Certifying exact commit $Commit with $IntegrationShards integration shards."
    Invoke-Checked $Docker @("info", "--format", "{{.ServerVersion}}")
    Invoke-Checked $Uv @("sync", "--all-groups", "--locked")
    $Python = Join-Path $RepositoryRoot ".venv/Scripts/python.exe"
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw "The locked Windows virtual environment was not created."
    }

    $RunToken = "$($Commit.Substring(0, 10))-$PID".ToLowerInvariant()
    $Jobs = [Collections.Generic.List[object]]::new()

    $UnitContainer = "maru-cert-unit-$RunToken"
    $Containers.Add($UnitContainer)
    $UnitPort = Start-IsolatedPostgres -Name $UnitContainer
    $Jobs.Add((Start-TestProcess `
        -Name "unit" `
        -DatabasePort $UnitPort `
        -Arguments @(
            "-m", "pytest", "tests/unit", "-q", "-p", "no:cacheprovider",
            "--cov=maru", "--cov-report=", "--cov-fail-under=0",
            "--junitxml=$ReportDirectory/unit.xml", "--durations=25"
        )))

    for ($Shard = 1; $Shard -le $IntegrationShards; $Shard += 1) {
        $ContainerName = "maru-cert-integration-$Shard-$RunToken"
        $Containers.Add($ContainerName)
        $Port = Start-IsolatedPostgres -Name $ContainerName
        $Jobs.Add((Start-TestProcess `
            -Name "integration-$Shard" `
            -DatabasePort $Port `
            -Arguments @(
                "scripts/run_ci_test_shard.py",
                "--shard-index", "$Shard",
                "--shard-count", "$IntegrationShards",
                "--", "-q", "-p", "no:cacheprovider",
                "--cov=maru", "--cov-report=", "--cov-fail-under=0",
                "--junitxml=$ReportDirectory/integration-$Shard.xml",
                "--durations=25"
            )))
    }

    $RepositoryGateError = $null
    try {
        Write-Host "Running static, documentation, contract, frontend, and security gates..."
        Invoke-Checked $PowerShell @(
            "-NoProfile", "-File", "scripts/check.ps1", "-SkipPythonTests"
        )
    }
    catch {
        $RepositoryGateError = $_
        Write-Error -ErrorAction Continue "Repository gates failed: $_"
    }

    $FailedJobs = [Collections.Generic.List[string]]::new()
    foreach ($Job in $Jobs) {
        $Job.Process.WaitForExit()
        Show-TestLog -Job $Job
        if ($Job.Process.ExitCode -ne 0) {
            $FailedJobs.Add("$($Job.Name) ($($Job.Process.ExitCode))")
        }
        else {
            Write-Host "$($Job.Name) passed."
        }
    }

    if ($null -ne $RepositoryGateError -or $FailedJobs.Count -gt 0) {
        if ($FailedJobs.Count -gt 0) {
            Write-Error -ErrorAction Continue (
                "Failed test processes: " + ($FailedJobs -join ", ")
            )
        }
        throw "Maru certification failed."
    }

    Invoke-Checked $Python @(
        "-m", "coverage", "combine", "$CoverageDirectory"
    )
    Invoke-Checked $Python @(
        "-m", "coverage", "report", "--fail-under=90"
    )
    Invoke-Checked $Python @(
        "-m", "coverage", "xml", "-o", (Join-Path $ArtifactRoot "coverage.xml")
    )
    Invoke-Checked $Python @(
        "-m", "coverage", "html", "-d", (Join-Path $ArtifactRoot "htmlcov")
    )

    $FinalWorkingTree = (& $Git "status" "--porcelain").Trim()
    if ($LASTEXITCODE -ne 0 -or $FinalWorkingTree) {
        throw "Certification changed tracked repository content; generated artifacts are stale."
    }

    $Evidence = [ordered]@{
        schema_version = 1
        result = "success"
        commit = $Commit
        completed_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
        integration_shards = $IntegrationShards
        isolated_postgres_instances = $IntegrationShards + 1
        branch_coverage_minimum_percent = 90
        gates = @(
            "locked_dependencies",
            "python_static_analysis",
            "numpy_documentation",
            "sphinx_html",
            "django_and_openapi_contracts",
            "staff_console",
            "dependency_security",
            "unit_tests",
            "postgresql_integration_tests",
            "combined_branch_coverage"
        )
    }
    $Evidence | ConvertTo-Json -Depth 4 | Set-Content `
        -LiteralPath (Join-Path $ArtifactRoot "certification.json") `
        -Encoding utf8
    Write-Host "Maru certification passed for exact commit $Commit."
}
finally {
    foreach ($Container in $Containers) {
        & $Docker "rm" "--force" $Container 2>$null | Out-Null
    }
    Pop-Location
}
