# Checkpoint: Product and operating-system blueprint

Date: 2026-07-26  
Milestone: Research synthesis and implementation-ready architecture baseline  
Application release: None

## Outcome

The initial idea—one Python/Django content backend for furry conventions—has
been developed into a professional convention operating-system blueprint.
Maru is one canonical event record with focused personal, staff, live,
public, kiosk, scanner, signage, and offline experiences.

The baseline explicitly covers the work that tends to escape registration and
programme tools: governance, decisions, readiness, budgets, contracts,
procurement, accreditation, lodging, travel, access routes, volunteer wellbeing,
stage advance, logistics, assets and custody, service desks, safety boundaries,
art/auction/charity, fursuit facilities, communications, knowledge handover,
closeout, retention, and edition cloning.

## Research incorporated

Public, dated research inspected general operating patterns and specialist
tool categories used around community conventions. The current documentation
retains the synthesized requirements without reusing convention brands or
implying affiliation.

The resulting synthesis is in `docs/research/landscape-2026-07.md`. Source
capabilities are evidence and inspiration; they are not copied code or proof
that one organization endorses Maru.

## Decisions

- Retained Python/Django API-first modular monolith direction.
- Accepted event edition as operational and archival boundary.
- Accepted capability/scope/relationship/field authorization.
- Accepted bounded on-site Relay for selected critical workflows.
- Accepted transactional outbox for required asynchronous work.
- Kept frontend, identity provider, queue/cache, search, storage, and hosting
  provider selections open until implementation evidence supports an ADR.

## Deliverables

- Product vision, lifecycle, capability map, personas, information
  architecture, and key workflows.
- 164 stable requirements.
- Conceptual domain model and five accepted ADRs.
- Authorization, classification/retention, threat, activity/audit, resilience,
  integration, reporting/automation, deployment, and observability designs.
- 25-slice outcome-oriented delivery plan.
- Implementation-ready V00–V02 foundation backlog.

## Verification

- 35 Markdown files.
- 164 requirement identifiers; 164 unique.
- Five ADRs present and indexed.
- All relative Markdown links resolve.
- No common encoding-corruption markers detected.

## Risks carried forward

- Partner discovery and jurisdiction-specific professional review remain
  mandatory.
- Product breadth creates a strong temptation to scaffold empty modules; the
  delivery plan prohibits this in favor of complete vertical slices.
- Policy enforcement, archive integrity, outbox behavior, and PostgreSQL
  concurrency must be proven in code rather than assumed from design.
- Offline Relay details need a later focused prototype and threat review.

## Resume point

Proceed with V00 in `docs/project/BACKLOG.md`. Do not implement downstream
feature modules until the foundation release acceptance proves tenant scoping,
safe settings, PostgreSQL tests, audit, and transactional effects.
