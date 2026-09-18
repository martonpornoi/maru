# Programme owned HTTPS and genuine setup preparation

Date: 2026-09-18

## Outcome

Continue #108 from protected PR #170 with a policy-fenced native HTTPS context and
three real-owner setup compositions. NFR-013, IDN-001/002/004/005, AUD-001 and the
existing Programme setup/role contracts under ADRs 0081/0100/0106 are unchanged.
This is test-only preparation, not successful startup, P01–P12 acceptance, human
approval, production hosting or supported-profile activation. No source migration,
production route, current profile, ACL or PostgreSQL-policy change is included.

## Boundaries

- Fresh loopback TLS leaf, SAN only `127.0.0.1`, server-only/non-CA, bounded original
  lease, exclusive certificate files in an owned temporary directory. No trust
  store installation. Secure session/CSRF cookies and HTTPS redirects are mandatory.
- Actual guarded WSGI construction and real dependency health precede yielding.
  The parent trusts only its fixture certificate and refuses proxies, redirects,
  large/invalid health responses and non-OK dependencies. Public static finders do
  not expose media or fixture secrets. Request query logging is suppressed.
- The owned web process self-exits on its original deadline or parent-pipe EOF;
  these guards arm before native readiness. Bounded normal process shutdown precedes
  certificate cleanup and verified database disposal. Crash-left expired synthetic
  files require exact-directory cleanup, never broad Docker or workspace cleanup.
- Closed setup modes require a genuinely ready runtime and authenticated platform
  administrator with no adopted organization/edition/person state. Fresh separate
  synthetic people use actual bootstrap, in-memory delivered verification token,
  real challenge consumption and password authentication; no verified flag writes.
- Two distinct synthetic controllers respond through their own owner commands.
  Existing Executive Board/Maru-operator roots are retained unchanged; an exact
  setup retry recovers the receipt. Two initial operational grants use explicit
  Edition coordination and Department intake recipes, with the second actual
  authenticated synthetic controller approving each request. No catch-all roles.
- The fixed setup child uses bounded private stdin/stdout pipes for credentials;
  nothing secret enters arguments, public readiness, web environment or persistent
  fixture files. Result handles redact passwords. Worker secrets remain separate.
  Real worker refresh is explicit and cannot extend the lease or fake heartbeats.

## Verification and limits

Focused database-free feedback passed 124 cases in 0.74s before the additional
watchdog-ordering test. These cover real certificate/key parsing and mocked
process/owner composition, including refusal and ordered cleanup. Initial pytest
execution hit an inaccessible shared temporary root; rerunning in a fresh
workspace-owned temporary directory passed. No permissions were weakened.

Complete database-free feedback passed 10,692 cases in 61.02s, including the added
watchdog-ordering case. Three existing Django URL-field transition warnings remain.
Ruff and diff checks passed. Clean exact-head retained certification and protected
delivery are pending at this snapshot. Native PostgreSQL remains deferred: no suite collection,
Docker/database/migration/schema-only check, real server or browser was executed.
Three maintained host-only HTTPS/setup cases join the six provisioning and four
transport cases under #102; they are debt, not successful acceptance or timings.

## Continue

Complete the remaining integrated personas, purpose-specific grants, real private
file scanner, continuity trust and P02–P12 content/isolation/failure paths. Then
restore required PostgreSQL policy through protected delivery and measure actual
native headroom/coverage, resolve logical restore #97, gather #109 and genuinely
human #92 evidence, and only finally promote the supported profile. #108/#48 stay
open; no synthetic person's actions substitute for representative-human approval.
