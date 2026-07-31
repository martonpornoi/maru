# Controlled reset preservation checkpoint

Date: 2026-07-31
Status: Preservation complete; baseline choice pending

## Reason

The product owner concluded that repeated administration-menu and page-shell
changes were not producing a coherent product. They requested preservation of
the current implementation followed by a basic, empty baseline and a
page-by-page rebuild.

## Preserved state

Recovery directory:
`C:\Users\TheMw\AppData\Local\Temp\Maru-reset-snapshot-20260731-171759`

The recovery directory contains:

- `working-tree/`: repository-owned files, including modified and untracked
  source, documents, tasks, tests, migrations, and built application assets;
- `maru-history.bundle`: all committed refs and complete Git history, verified
  with `git bundle verify`;
- `tracked-working-tree.patch`: binary-safe tracked changes;
- `git-status.txt`: branch and dirty-state inventory;
- `working-tree-sha256.csv`: 651 copied-file hashes; and
- `recovery-artifacts-sha256.csv` plus `snapshot-inventory.json`.

Regenerable virtual environments, dependencies, coverage, bytecode, and tool
caches were excluded. The resulting working-tree copy is about 9.1 MB. The
existing `maru` and `marucon_rehearsal` PostgreSQL databases remain in place
and were not changed by the preservation operation.

## Safety boundary

No reset, deletion, move, branch switch, database flush, or database drop has
occurred. The temporary recovery directory can eventually be cleaned by the
operating system, so it must be moved to durable storage before any future
irreversible reset.

## Required next decision

Choose one baseline before implementation continues:

1. **Empty experience (recommended):** keep the tested Django, domain,
   authorization, audit, and migration foundation but expose only Sign in and
   one minimal administration home. Reintroduce and approve pages one at a
   time.
2. **Empty codebase:** start a new minimal Django project and re-implement every
   domain behavior and safety guarantee from the preserved requirements and
   tests.

Then choose this working tree, a new branch, or a sibling worktree; create a
new empty database; supersede the accepted UI architecture with a new ADR; and
build only the first agreed page. The detailed crash-safe checklist is
`docs/project/RESET_REBUILD.md`.
