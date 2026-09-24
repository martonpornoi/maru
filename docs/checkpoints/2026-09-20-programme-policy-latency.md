# Programme policy round-trip correction

- Date: 2026-09-20
- Scope: #198, required by #108/#48 and bundled with #189 integration
- State: local implementation and focused verification; not protected delivery

## Diagnosis

The extended functional journey passed in 1,749.93s, but individual room,
Department, edition and archive responses exceeded the maintained 15-second
HTTP limit. That diagnostic success is not normal performance acceptance.

A separate shortened genuine-runtime cProfile run observed:

| Actual successful HTML output | Queries | Profiled elapsed | In ordinary policy |
| --- | ---: | ---: | ---: |
| Room | 15,480 | 26.077s | 20.443s |
| Department | 32,108 | 54.042s | 44.904s |

These are instrumented times, not uninstrumented latency benchmarks. The edition
profile was consumed by an intentionally denied cross-scope request (404), so it
does not establish a successful edition-output profile. The shortened run ended
deliberately with `operator_profile_complete_not_acceptance` after 1,068.13s.
It recorded coarse timings/function names/counts only, not SQL, parameters,
credentials or private HTTP contents. Its owned fixture was disposed.

## Correction and limits

[ADR 0112](../architecture/decisions/0112-native-point-in-time-policy-observation.md)
reuses the already fingerprinted native exact-issuance validator for every fresh
non-locking policy observation. Each check retains the original issuance ordinal,
principal, capability, current target and instant. Marker/latch observation,
adoption, role-purpose and field rules remain unchanged. No cache, substituted
source, missing owner recheck, longer timeout or native-failure fallback is added.

Single-issuance and lock-capable writer validation, deterministic control-source
selection and persistent-horizon proofs retain independent Python validation.
No function, schema, ACL, profile or stored evidence changes for this correction.

## Verification so far

- Red regression: two new tests failed against the old policy dispatch; two
  missing-source/independent-writer cases already passed.
- Four new policy units plus ten existing provenance units: 14 passed in 0.30s.
- Exact navigation/currentness differential, native representation roots,
  provenance and required-contract tests: 41 passed in 78.20s. Four new cases
  compare complete native/Python decisions for direct/role authority at
  Organization/Edition scope before and after exact ancestor revocation, with
  at most ten client queries per decision and no cached permission.
- Adjacent policy, activation and writer-boundary cases: 48 passed in 44.97s.
- Complete fast suite: 12,676 passed in 77.89s, with three existing URL-field
  warnings. Evidence: `.tools/programme-exit-bundle-units-16.xml`.
- Focused lint/format and documentation validation passed (665 Markdown files,
  four repository skills, 215 requirements). The unchanged bounded genuine
  populated journey is in progress; no performance acceptance claimed.

Preserve `.tools/programme-native-policy-1.xml` and `-2.xml`. The profiling report
is `.tools/programme-populated-runtime-profile-13.xml`, deliberately failed and
never a certification receipt. Keep #198 and its parents open until successful
unmodified evidence and exact-head protected delivery; #190/#97/#92/#109 and final
profile promotion remain separate incomplete outcomes.
