# Programme scanner endpoint portability repair

Date: 2026-09-16. PR #146 remains a partial #108 delivery; #108/#48 stay open.

## Actual failure and cause

Initial head `21a5e58fb36caf579bdd72d23560d2b02f349569` passed all eight local
retained gates in 312.676s, with 8,642 units in 53.97s and 93 frontend tests.
The schema-4 deferred receipt SHA-256 is
`70e3959b7beb47b86c42dd4c3bcd5acc32065bd55c90a04483623a3bf2758420`.
All five evidence artifacts were archived and hash-verified before replacement.

[Hosted unit job 104592741445](https://github.com/martonpornoi/maru/actions/runs/35032088974/job/104592741445)
ran Python 3.12.14 and failed the `::ffff:127.0.0.1` endpoint case: 8,641 passed,
one failed, three existing warnings, in 98.32s. Local Python reports 3.12.0 and
classifies this address's `is_loopback` as false. The hosted behavior exposed a
library classification difference, not a flaky scanner or database timeout.

## Repair and evidence boundary

The transport contract intentionally admits native loopback addresses, not
IPv4-mapped IPv6 alternatives. Reject `IPv6Address.ipv4_mapped` explicitly before
any socket connection, regardless of the library's loopback classification.
Retain the original negative test and add the equivalent hexadecimal spelling.
Two additional tests force the newer loopback classification; both failed locally
before the repair, reproducing the hosted issue without changing the installed
interpreter or reaching a real socket. After the repair, all 83 focused cases pass
in 0.56s and complete database-free feedback passes 8,645 cases in 54.54s, with the
same three URLField warnings. Changed strict types, whole Ruff lint and documentation
validation (572 Markdown files/four skills/215 requirements) also pass.
The [standard-library contract](https://docs.python.org/3.12/library/ipaddress.html#ipaddress.IPv6Address.ipv4_mapped)
defines the mapped-address discriminator.

No test, endpoint restriction, timeout, CI gate or deferral boundary is weakened.
No machine interpreter, lockfile, database, schema, profile, runtime privilege,
external scanner or production route is changed. The original local receipt is
historical evidence only; fresh full database-free feedback, clean exact-commit
retained certification and independent hosted acceptance are required for the
corrected candidate before normal protected merge. PostgreSQL remains skipped.

The unfinished provenance/custody/viewer work and unanswered bounded schema-only
request remain as recorded in CURRENT and #108. This repair does not complete
intake, #109 integrated evidence or the #102/#97/#92 activation gates.
