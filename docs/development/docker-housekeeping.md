# Local Docker housekeeping

**Audience:** Contributors maintaining a local Docker Desktop installation\
**Outcome:** Distinguish retained test resources from persistent or unrelated data\
**Reading time:** 4 minutes

Stopped containers and unreferenced volumes are different resources. A stopped
container is not a running database, but its volumes can still contain needed
data. Docker's reclaimable-size estimate is not evidence of disposable content
or permission to delete it. Disk cleanup is not a test-performance benchmark.

## Inventory before proposing deletion

These commands read resource metadata, not database contents or credentials:

```powershell
docker ps -a --format '{{.ID}}|{{.Names}}|{{.Image}}|{{.State}}'
docker compose ls -a
docker system df
docker volume ls --format '{{.Name}}|{{.Labels}}'
docker volume ls --filter dangling=true --format '{{.Name}}'
```

For each exact candidate container, inspect only its relevant metadata:

```powershell
docker inspect --format '{{json .Mounts}}|{{json .Config.Labels}}' <container-id>
```

Do not dump container environments, logs, secret mounts, or database contents
into tickets or public evidence. Keep machine-specific inventories local.
Record exact container IDs/names, mount names, ownership labels, running state,
the originating run/receipt, and the proposed retention or deletion decision.

## Preserve persistent and uncertain resources

The repository's `compose.yaml` deliberately uses the named Maru PostgreSQL
volume. It is persistent development data, not a certification shard. Confirm
its actual mount through inspection; do not infer its identity solely from a
name. Preserve it unless the owner explicitly approves a database reset with
the required backup/recovery plan.

Likewise, keep resources belonging to another project. An anonymous name or
`dangling=true` means neither Maru ownership nor synthetic content. Detached
volumes left by old runs may have lost the only container-to-run association;
absence of labels is uncertainty, not deletion authority. Leave uncertain
resources untouched until their owner and retention decision are established.

## Remove only an approved synthetic run

After the owner approves the exact disposable run and any required evidence has
been retained, use its existing runbook and twelve-character run ID:

- [Runtime rehearsal cleanup](../operations/synthetic-oci-runtime-rehearsal.md#evidence-failure-and-cleanup).
- [Static-delivery rehearsal cleanup](../operations/synthetic-oci-static-delivery-rehearsal.md#evidence-failure-and-cleanup).

Both runners validate the complete expected namespace and exact ownership
labels before cleanup. They remove containers with `docker rm --force
--volumes`: Docker removes associated anonymous volumes, including the
image-declared PostgreSQL data volume on a one-shot helper, but not named
volumes. Named rehearsal volumes still require the separate exact-name,
label-verified removal. See the
[Docker removal contract](https://docs.docker.com/reference/cli/docker/container/rm/).

The runners do not search for and delete unrelated orphaned volumes. Their
retention options stop containers without deleting containers or volumes;
retained secret volumes remain sensitive local material until approved cleanup.
Certification already starts its own disposable containers with `--rm`; do not
replace that lifecycle with manually retained, unlabeled databases.

Never substitute global pruning, broad name filters, or another project's
Compose teardown for an exact approved cleanup. After cleanup, verify the
run-owned container/network/volume inventory is empty and any previously
recorded anonymous mounts are absent. Independently verify protected resources
are unchanged. Report exact removals and whether they are recoverable;
synthetic database/credential deletion is irreversible without a backup.

## Prevent recurrence

Use the maintained certifier and rehearsal runners. Keep an intentionally
retained run's sanitized receipt and explicit cleanup decision. After a crash,
inspect its exact inventory before resuming or removing it. Do not infer that a
process ending proves cleanup succeeded. No automated age-based pruning or
cross-project deletion policy is established by this guide.
