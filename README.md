![Maru convention operations platform](.github/assets/maru-header.png)

# Maru

**Open-source operations software for furry conventions.**

Maru is being built for the people who organize recurring furry conventions:
volunteer coordinators, programme teams, department leads, and the people
keeping an event running. The aim is to connect work that otherwise lives in
spreadsheets, forms, inboxes, and separate tools, while keeping each organizer's
data and authority clearly scoped. Other community conventions can use the
same foundations.

[Documentation](https://martonpornoi.github.io/maru/) ·
[Run locally](docs/start-here/run-locally.md) ·
[Contribute](CONTRIBUTING.md) ·
[Roadmap](docs/project/ROADMAP.md) ·
[Discussions](https://github.com/martonpornoi/maru/discussions)

[![PR gate](https://github.com/martonpornoi/maru/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/martonpornoi/maru/actions/workflows/ci.yml)
[![Contributor documentation](https://github.com/martonpornoi/maru/actions/workflows/pages.yml/badge.svg?branch=main)](https://github.com/martonpornoi/maru/actions/workflows/pages.yml)

> [!IMPORTANT]
> Maru is under active development. It is not a production-ready release or a
> supported hosted service. Use synthetic data for local exploration and
> contributions; do not use real convention or personal records.

## Start with one useful workflow

A convention should be able to adopt one complete workflow, keep its existing
systems, and expand only when it chooses. A volunteer account must not silently
create an attendee registration or a payment obligation. Imports, exports,
printable fallbacks, and clear exit paths are part of that design.

To try the fictional conventions after installing the [prerequisites](docs/start-here/run-locally.md):

```sh
uv sync --locked --all-groups
uv run --locked python scripts/try_maru.py
```

Open the printed browser link and sign in with the displayed demo account.
**Ctrl+C deletes this disposable preview.** For prerequisite checks, startup
verification, a short browser journey, or a persistent setup, follow
[Run locally](docs/start-here/run-locally.md).

The repository contains these concrete starting points:

| Area | What is available to explore |
| --- | --- |
| Organizer setup | A shared management shell, fictional organizations, recurring convention series, and dated editions with explicit authority. |
| Volunteer coordination | Tested Workforce workflows for structure, positions, assignments, availability, and shifts, including a Workforce-only adoption path. |
| Announcements | A standalone workflow for writing, independent review, manual posting records and corrections while keeping your existing website and social channels. [Try the workflow](docs/operations/announcements.md). |
| Programme Operations | Implemented planning, publication, continuity, and recovery work under isolated synthetic evaluation; activation and human acceptance remain separate gates. |
| Other modules | Bounded Registration, Venue, Logistics, and other slices; consult the module contracts before treating one as a complete workflow. |

These are development and evaluation surfaces. The
[current state](docs/project/CURRENT.md) owns active priorities and verification;
the [maturity guide](docs/start-here/current-maturity.md) explains their limits.
Fictional **MaruCon** and **MaruDance** examples are not customers or endorsements.

## Explore or contribute

| I want to… | Start here |
| --- | --- |
| Understand the idea | [What is Maru?](docs/start-here/what-is-maru.md) — five minutes. |
| Run the application | [Local setup](docs/start-here/run-locally.md) — Python, uv, Docker Compose, and a disposable database. |
| Try a coherent journey | [Product tour](docs/start-here/product-tour.md) — synthetic organizer setup through an event edition. |
| Make a small improvement | [First contribution](docs/start-here/first-contribution.md) — documentation, reproduction, tests, or a scoped fix. |
| Understand the code | [Architecture](docs/architecture/overview.md), [module ownership](docs/modules/index.md), and [generated Python reference](https://martonpornoi.github.io/maru/autoapi/index.html). |

You do not need to understand the entire platform to contribute. Clear bug
reproductions, corrections to setup instructions, accessibility observations,
and focused tests are useful. [Contributing](CONTRIBUTING.md) explains how to
choose work and prepare it for review. Use
[Discussions](https://github.com/martonpornoi/maru/discussions) for setup help and
early ideas, and [Issues](https://github.com/martonpornoi/maru/issues) for bugs
and bounded proposals. Support is best effort.

## Technical foundations

- Python 3.12–3.14, Django 5.2 LTS, and PostgreSQL.
- A modular monolith: modules own their data and expose documented services.
- Django REST Framework, versioned OpenAPI, and embedded React/TypeScript.
- Deny-by-default organization and edition boundaries, audit trails, and
  explicit approval for privileged work.
- Tested migration, recovery, and degraded-operation contracts.

The primary release artifact is an immutable application image in GitHub
Container Registry. [Releases](https://github.com/martonpornoi/maru/releases)
and the [changelog](CHANGELOG.md) describe published candidates; they do not
replace deployment or production acceptance. The
[operations catalog](docs/operations/index.md) contains the evaluator runbooks.
Evaluate candidate images with the
[synthetic OCI runtime rehearsal](docs/operations/synthetic-oci-runtime-rehearsal.md)
and [synthetic OCI static delivery rehearsal](docs/operations/synthetic-oci-static-delivery-rehearsal.md).
Both use synthetic data and provide evaluator evidence, not deployment approval.

## Project policies

Maru-owned code is licensed under [Apache-2.0](LICENSE). Bundled components keep
their [third-party licenses](THIRD_PARTY_NOTICES.md). Contributions follow the
[Code of Conduct](CODE_OF_CONDUCT.md) and [governance](GOVERNANCE.md).
Report vulnerabilities through [Security](SECURITY.md), not public issues;
[Support](SUPPORT.md) explains the available help channels.
