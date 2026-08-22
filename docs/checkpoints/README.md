# Checkpoint system

The checkpoint system lets a maintainer or agent resume work without reading the
entire repository or relying on conversation history.

## Two checkpoint levels

### Current handoff

`docs/project/CURRENT.md` is the authoritative concise status. It is updated by
every material task and contains only:

- current phase and working outcome;
- accepted decisions;
- verification actually performed;
- known risks and unfinished work;
- the next smallest sensible actions.

### Milestone snapshots

Files in this directory are append-only historical snapshots for:

- accepted project foundations;
- completed vertical slices;
- releases;
- important migrations;
- major architecture changes;
- incidents that materially change design or operations.

Do not edit a milestone snapshot to reflect later reality. Add a new checkpoint.
ADR 0073 records one bounded exception: unnecessary external convention names
were sanitized from currently rendered prose while the original public evidence
remains in Git history. That ethical terminology correction does not authorize
ordinary checkpoint rewriting.

## Naming

```text
YYYY-MM-DD-short-descriptive-slug.md
```

If multiple checkpoints share a date, append `-02`, `-03`, and so on.

## Snapshot template

```markdown
# Checkpoint: Outcome

- Date:
- Phase:
- Related requirements:
- Related ADRs:

## Outcome

## Decisions

## Changed areas

## Verification

## Data, migration, and deployment notes

## Known risks and incomplete work

## Recommended next actions
```

Git tags may identify released or migration-sensitive checkpoints once the
project has releases. Repository checkpoint files remain the readable source.
