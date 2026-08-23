# Architecture & security

**Audience:** Contributors changing system boundaries, data, authorization,
integrations, or operational behavior\
**Outcome:** Find the architecture and security contract that governs a change\
**Reading time:** 3 minutes to choose a source

Begin with the [architecture overview](overview.md). Maru remains a modular
monolith: modules own their data, cross-module writes use explicit application
services, and external integrations remain adapters.

## Core architecture

- [Domain model](../domain/domain-model.md) defines the shared domain language.
- [Activity, audit, and history](activity-audit-and-history.md) separates user
  history from control evidence.
- [Reporting and automation](reporting-and-automation.md) describes safe derived
  views and automation boundaries.
- [Integrations and extensions](integrations-and-extensions.md) defines adapter
  and extension expectations.
- [Resilience and offline operation](resilience-and-offline.md) explains
  degraded-mode and recovery architecture.

## Security model

- [Authorization](../security/authorization-model.md) is deny-by-default and
  explicitly scoped.
- [Data classification and retention](../security/data-classification-and-retention.md)
  governs purpose, visibility, and disposal.
- [Threat model](../security/threat-model.md) identifies trust boundaries and
  required controls.

## Decisions

[Architecture decision records](decisions/index.md) preserve durable choices
and their consequences. Use the catalog to locate a relevant decision; do not
read the complete history sequentially.

```{toctree}
:hidden:
:maxdepth: 1

overview
../domain/domain-model
activity-audit-and-history
reporting-and-automation
integrations-and-extensions
resilience-and-offline
../security/authorization-model
../security/data-classification-and-retention
../security/threat-model
decisions/index
```
