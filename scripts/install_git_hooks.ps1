[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepositoryRoot
try {
    git config --local core.hooksPath .githooks
    if ($LASTEXITCODE -ne 0) {
        throw "Could not configure the repository-managed Git hooks."
    }
    $ConfiguredPath = git config --local --get core.hooksPath
    if ($LASTEXITCODE -ne 0 -or $ConfiguredPath.Trim() -ne ".githooks") {
        throw "The repository-managed Git hook path was not retained."
    }
    Write-Host "Maru Git push guards are active from .githooks."
}
finally {
    Pop-Location
}
