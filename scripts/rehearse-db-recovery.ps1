param(
    [string]$SourceDatabase = "maru",
    [string]$DrillDatabase = "maru_restore_drill"
)

$ErrorActionPreference = "Stop"

if ($DrillDatabase -notmatch "^maru_restore_drill(?:_[a-z0-9]+)?$") {
    throw "Drill database must use the maru_restore_drill[_suffix] namespace."
}
if ($SourceDatabase -notmatch "^maru(?:_[a-z0-9]+)*$") {
    throw "Source database must use the maru[_suffix] namespace."
}
if ($SourceDatabase -eq $DrillDatabase) {
    throw "Source and drill databases must be different."
}

$backupPath = "/tmp/maru-recovery-drill.dump"
$created = $false

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

    & docker compose @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed with exit code $LASTEXITCODE."
    }
}

try {
    Invoke-Compose exec -T postgres pg_dump `
        --username maru `
        --dbname $SourceDatabase `
        --format custom `
        --file $backupPath

    Invoke-Compose exec -T postgres dropdb `
        --username maru `
        --if-exists `
        $DrillDatabase
    Invoke-Compose exec -T postgres createdb `
        --username maru `
        --template template0 `
        $DrillDatabase
    $created = $true

    Invoke-Compose exec -T postgres pg_restore `
        --username maru `
        --dbname $DrillDatabase `
        --exit-on-error `
        $backupPath

    $validationQuery = @"
SELECT json_build_object(
  'database', current_database(),
  'migrations', (SELECT COUNT(*) FROM django_migrations),
  'accounts', (SELECT COUNT(*) FROM identity_account),
  'organizations', (SELECT COUNT(*) FROM organizations_organization),
  'editions', (SELECT COUNT(*) FROM events_eventedition),
  'audit_events', (SELECT COUNT(*) FROM audit_auditevent),
  'outbox_messages', (SELECT COUNT(*) FROM effects_outboxmessage)
)::text;
"@
    $validation = & docker compose exec -T postgres psql `
        --username maru `
        --dbname $DrillDatabase `
        --tuples-only `
        --no-align `
        --command $validationQuery
    if ($LASTEXITCODE -ne 0) {
        throw "Restore validation query failed with exit code $LASTEXITCODE."
    }

    $evidence = [ordered]@{
        status = "passed"
        source_database = $SourceDatabase
        restored_database = $DrillDatabase
        validated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        restored_counts = ($validation.Trim() | ConvertFrom-Json)
        cleanup_on_exit = $true
    }
    $evidence | ConvertTo-Json -Depth 4
}
finally {
    if ($created) {
        Invoke-Compose exec -T postgres dropdb `
            --username maru `
            --if-exists `
            $DrillDatabase
    }
    Invoke-Compose exec -T postgres rm -f -- $backupPath
}
