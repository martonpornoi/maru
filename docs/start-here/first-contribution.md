# Make a first contribution

**Audience:** New code and documentation contributors\
**Outcome:** Choose a small improvement, verify it, and open a useful draft pull
request\
**Reading time:** 5 minutes; implementation time depends on the task

You can help without understanding every Maru module or operating a convention.
A correction to a confusing instruction, a reproducible bug, or a focused test
is a useful contribution. If you know furry convention operations, explain the
job a person needs to finish and the exception that makes it difficult. Use
fictional examples without real attendees, volunteers, or private records.

## Choose one outcome

| Contribution | Useful evidence |
| --- | --- |
| Improve a setup instruction | The failing step, your OS/tool versions, and the corrected command's observed result. |
| Report or reproduce a bug | A synthetic starting state, exact steps, expected result, and actual result. |
| Improve a form or keyboard journey | The role, page, action, observed barrier, and a check that the proposed change resolves it. |
| Add a test or fix | One missing behavior or regression, the owning module, and a focused test. |

Browse [issues labelled good first issue](https://github.com/martonpornoi/maru/issues?q=is%3Aissue%20is%3Aopen%20label%3A%22good%20first%20issue%22)
for prepared tasks. The list may be empty; labels are not a promise of available
work. Use [Discussions](https://github.com/martonpornoi/maru/discussions) for
setup help or an idea that still needs scoping. Small documentation corrections
can go directly to a pull request. Discuss substantial behavior changes before
investing in an implementation.

## Prepare your branch

Read [Contributing](https://github.com/martonpornoi/maru/blob/main/CONTRIBUTING.md).
If you do not have write access, fork the repository on GitHub and clone your
fork. From an up-to-date local `main`, create a branch:

```sh
git switch -c docs/clearer-setup
uv sync --locked --all-groups
```

Use a name appropriate to your change. For material work, follow
[`AGENTS.md`](https://github.com/martonpornoi/maru/blob/main/AGENTS.md): read
[current state](../project/CURRENT.md), [roadmap](../project/ROADMAP.md), and
only the relevant requirement, module guide, accepted decisions, code, and
tests. These instructions apply whether or not you use an agent.

## Get feedback before a full run

For documentation, the link, navigation, and requirement checks need no
running PostgreSQL service:

```sh
uv run python scripts/validate_docs.py
git diff --check
```

Render changed pages with the warning-fatal documentation build described in
[development setup](../development/setup.md#contributor-documentation).
Read the rendered result as well as the Markdown. For code, use the affected
module's tests and the [testing strategy](../quality/testing-strategy.md).
Focused checks help iteration; they are not complete pre-review certification.

## Open a reviewable draft

Explain the problem, the resulting behavior, the checks you ran, and anything
still unverified. A draft lets others review scope while you finish the work.
Draft updates intentionally do not pass the protected `PR gate`.

Before marking the pull request ready, install the repository push guard and
follow [local certification](../development/local-certification.md) for the
complete clean-commit checks. Keep requirements, tests, documentation, and the
current handoff consistent when the change is material. GitHub independently
checks the merge candidate; a first-time fork's run may need maintainer approval.
That approval permits the run and does not accept the contribution.

The [repository governance guide](../development/repository-governance.md)
owns detailed review, destructive-change, and merge rules. All contributions
remain subject to the existing security, privacy, and tenant boundaries.

**Next:** Choose one outcome and create its branch. If you are stuck on setup,
post the failing command and sanitized error in Discussions.
