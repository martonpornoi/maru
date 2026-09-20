# Identity invitation writer generation and recovery

This procedure implements ADR 0110 for IDN-013/014, NFR-013 and OPS-009.
It is not authorization to deploy, activate production policy or send email.

## Controlled installation

Stop old web and worker writers for a deployment cutover. Apply Identity
`0023_invitation_writer_cutover` as the migration owner after `0022`. Its table
lock serializes challenge writes; no retained data is rewritten, no new table
is introduced and no runtime relation or function privilege is added.

The existing check already requires inert legacy delivery fields on invitation
challenges. The generation guard preserves that contract and prevents conversion
into or out of the invitation purpose. Current generic challenge services reject
invitation or unknown purposes before token, query or abuse-state work. Resume
only the corresponding current web/worker release, never mixed old writers.

Require the complete invitation readiness report. The generation probe separately
observes the migration record, exact native function body and attributes,
owner-only ACL and sole enabled row trigger. A constant, migration recorder entry,
schema-only pass or successful public signup is insufficient. Key coverage,
approved retention policy, genuine worker heartbeats, runtime-role checks and
search plans are still mandatory. Registration retains its separate gate.

## Failure and recovery

Missing, disabled, rebound or modified native enforcement keeps readiness closed.
Investigate using metadata and count-only reports; never log invitation tokens,
recipient addresses, encrypted envelopes or private exception payloads. Do not
disable constraints or manually forge migration or worker evidence to recover.

An unused database may reverse this migration normally. Reversal obtains exclusive
locks and refuses before dropping enforcement if any invitation, invitation
challenge or transition evidence remains. After use, use a reviewed fix-forward
migration or a verified whole-system restore preserving the writer generation,
keys, canonical delivery and retention evidence. Never delete evidence merely to
permit a downgrade. Ordinary verification/recovery challenges are not themselves
a reason to refuse an otherwise unused invitation-generation reversal.

## Acceptance boundaries

Native tests cover fresh and populated upgrade, unchanged retained challenge
identity, obsolete-writer rejection, unused reversal and post-use refusal, plus
metadata drift. Public verification/recovery and invitation delivery/retention
regressions remain required. The real isolated Programme startup must pass the
unchanged full invitation readiness gate before Programme acceptance can proceed.
Component tests do not certify host-only journeys, production recovery or human
acceptance.
