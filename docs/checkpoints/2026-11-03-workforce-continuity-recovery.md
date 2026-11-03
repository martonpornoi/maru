# Workforce continuity and isolated recovery evidence

## Scope

The drill used protected commit 32517c2e16f3f679942ebd296e5b7e285dc66b8f,
which contains [PR #238](https://github.com/martonpornoi/maru/pull/238).
It prepared two populated fictional Workforce-only editions in one disposable
PostgreSQL container. No web or worker process was started. All ten preserved
fixtures stayed stopped and unchanged.

## Results

The first attempt stopped on a helper assertion. The second proved a clean
stop and a same-volume start with internal PostgreSQL readiness. Its
authenticated probe reused the previous dynamically allocated loopback port.
Docker's forwarding records show that restart allocated a different port.

The final attempt read the current binding for the exact container and volume
and reconnected as the restricted runtime role. The same-volume restart
preserved the original state and passed Guidance and authority readiness.
PostgreSQL created a custom-format dump and restored it to a separate database
in the same disposable container. Both commands exited successfully.

The restored database matched the 323 original public-table row fingerprints
and database owner and ACL. Both Workforce-only edition profiles matched.
All 223 excluded-model row counts stayed at zero. Restricted-runtime,
Guidance and authority readiness passed after restore. The source database
matched its baseline after restart and after the clone restore.

The drill exited nonzero on its additional all-table attribute-slot
comparison. Logical restore preserved visible column order and compacted five
dropped slots across three tables. The removed slots were slot 2 in
`django_content_type`, slot 7 in `organizations_organization`, and slots 17
through 19 in `registration_attendeeregistrationprofile`. The changed
catalog slots are distinct from the runtime readiness and row-fingerprint
results. Full catalog fidelity remains unverified. The disposable container,
volume and its internal dump were removed after the evidence was captured.

## Remaining work

[#22](https://github.com/martonpornoi/maru/issues/22) remains open. The offline
validator, revision comparison and authorized rota establish bounded parts of
the package. Trusted live identity and scope mapping, confirmation and
application, minimized reconciliation, scoped continuity/history/exit and
governed stop, restart, expansion and decommission still require technical
work. A representative restore or point-in-time recovery, operational
acceptance and owner approval remain separate gates.

See the [adoption and recovery runbook](../operations/workforce-only-adoption-and-recovery.md)
for the readiness and cutover evidence to retain.
