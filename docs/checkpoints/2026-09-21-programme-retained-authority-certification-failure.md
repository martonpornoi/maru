# Programme retained-authority recovery: certification failure

Date: 2026-09-21. Failed local certification, not delivery or acceptance.

Exact candidate `b2e88af4f0e6468180893ad248e5e617a4fe2fca`, base
`b056aa253a39df2648752daf35ac5a158a9950d7`, ran complete history with 71 planned
shards and at most eight databases. All 13,190 certification units passed in
180.93s; fifteen native shards passed, containing 577 cases without failures,
errors or skips. Their longest measured job was 889.453s.

Shard 14 failed both `revoked_grant` and `role_bundle` cases of
`test_notice_authority_blocks_downgrade_before_any_successor_recorder_changes`.
The older fence correctly rejected contraction, but Events 0016/0017 and Workforce
0030 had already reversed. The strict unchanged-recorder assertion therefore caught
a real partial-successor recovery gap for retained authority without native witness
rows. Shard 14 took 821.953s including cleanup; its three selected cases ended with
two failures and one pass. This was not a timeout or exhausted headroom.

Fail-fast cancelled the other seven active shards. All 23 started containers report
removed. There is no successful certification receipt. The complete failed pool,
JUnit reports and logs are preserved in
`.tools/certification-evidence/programme-exit-b2e88af-notice-failed`; the outer
transcript is `.tools/programme-certification-b2e88af.log`. The transcript does not
capture all nested native-command output and must not be advertised as such.

Events 0017 already protects native witnesses/dependency keys and remains immutable
once applied. Before retrying, audit the joined boundary's other retained authority,
setup, approval, starter, notice and archive fences and extend it additively. Preserve
the old owner preflights and unchanged-recorder assertions. Focused regression and
fresh full exact-head local/hosted acceptance remain mandatory. No production or
profile activation occurred and no issue was closed on this failed evidence.

The separately validated human-session documentation was fast-forwarded into the
bundle after the failure, so its eventual delivery can share the corrected candidate
instead of requiring another costly native feature certification. It supplies no
human or browser pass.
