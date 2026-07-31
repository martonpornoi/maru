# Controlled reset and page-by-page rebuild

Status: Preservation snapshot verified; baseline choice required
Last updated: 2026-07-31

This ledger preserves the current Maru implementation while the product
experience is reconsidered from a deliberately small baseline. It is the
resume point if the desktop app or development process stops.

## Why this reset exists

The current implementation contains substantial tested domain behavior, but
the administration experience has been reorganized several times and no
longer gives the product owner confidence that each page has one clear place
and purpose. Further navigation patches would compound that uncertainty.

The reset therefore separates two concerns:

1. preserve the current source, documents, requirements, tasks, tests, and Git
   history as recoverable evidence; and
2. decide what "empty" means before changing or deleting the working tree.

## Recovery snapshot

Target:
`C:\Users\TheMw\AppData\Local\Temp\Maru-reset-snapshot-20260731-171759`

The snapshot must contain:

- a copy of the repository-owned working tree, including modified and
  untracked source, documents, tasks, tests, migrations, and built assets;
- a Git bundle containing all committed refs and history;
- a binary-safe patch of tracked working-tree changes;
- a machine-readable Git status and snapshot inventory; and
- checksums for the recovery artifacts and copied repository files.

Regenerable environments and caches (`.venv`, dependency caches,
`node_modules`, bytecode, coverage, and tool caches) are excluded from the
working-tree copy. The existing PostgreSQL databases are retained in place and
are not dropped, flushed, or treated as part of an empty baseline.

## Reset checklist

### Preservation

- [x] Copy repository-owned working files to the dated temporary directory.
- [x] Create and verify the Git history bundle.
- [x] Export tracked dirty changes as a binary-safe patch.
- [x] Record untracked files, exclusions, source HEAD, branch, and repository
  status.
- [x] Hash the copied files and recovery artifacts.
- [x] Confirm the original working tree and databases were not modified by the
  snapshot operation.

Verified snapshot inventory:

- source branch: `main`;
- source HEAD: `ca37acb7f612a450a98585c3b4d5c8d4a2807de8`;
- copied repository-owned files: 651;
- copied size: about 9.1 MB;
- complete Git bundle: verified by `git bundle verify`; and
- `maru` and `marucon_rehearsal`: retained unchanged in PostgreSQL.

### Baseline decision

- [ ] Choose **empty experience** or **empty codebase**:
  - Empty experience: retain the tested Django/domain/security foundation but
    expose only sign-in and one minimal administration home. Reintroduce pages
    one at a time. This is the recommended baseline.
  - Empty codebase: create a new minimal Django project and re-earn every
    domain behavior, migration, permission, and operational guarantee from the
    preserved evidence.
- [ ] Define the only routes and records visible in the baseline.
- [ ] Decide whether the rebuild happens in this working tree, a new branch,
  or a sibling worktree.
- [ ] Define a new empty PostgreSQL database name; do not reuse or erase
  `maru` or `marucon_rehearsal`.
- [ ] Add a superseding ADR before changing the accepted UI architecture.

### Page-by-page contract

No second page starts until the current page has an agreed contract and has
been inspected in the running application. For every page, record:

- its single purpose and primary user;
- where it belongs in navigation and why;
- the minimum information shown;
- allowed actions and exact authorization boundary;
- empty, loading, success, validation, denied, and failure states;
- desktop and narrow layout evidence;
- automated behavior, permission, and tenant-isolation tests; and
- affected requirements, ADRs, module docs, and operator guidance.

Proposed initial sequence after the baseline decision:

1. Sign in.
2. Empty administration home.
3. First administrator and platform state.
4. Organization record.
5. Convention series record.
6. Edition record and edition selector.
7. Person/account record.
8. Organization structure.
9. Registration template and edition form.
10. Attendee self-registration.

The sequence is provisional. It exists to make discussion concrete, not to
pre-approve later pages.

## Resume point

The recovery snapshot and Preservation checklist are complete. Obtain the
product owner's explicit choice between an empty experience and an empty
codebase. Do not reset, delete, move, or overwrite the current working tree
before that choice.
