# Keep a Workforce rota copy

Use this for a synthetic `workforce_only@1` edition when you need a portable or
printed copy of Shift planning. It is the first operating-copy slice of
[#22](https://github.com/martonpornoi/maru/issues/22), not a complete continuity
or recovery package. Keep your separately approved incumbent fallback.

## Download or print

1. Use your own active, verified account and select the intended organization
   and edition.
2. Open **Workforce → Shift planning**.
3. Under **Keep an operating copy**, choose **Download rota package** or
   **Print rota**. Printing uses your browser's normal Print command.
4. Check the edition, observation time and time zone before using the copy.
   Protect the saved ZIP, HTML, PDF and paper as personal staffing data.

You need both current Shift read and Shift management authority, plus complete
edition-metadata read authority. Ordinary volunteers and read-only planners do
not receive the export links. Possessing a link or a saved UUID grants nothing.
The destination checks authority again. Unsupported profiles, missing authority
and incomplete fields do not produce a partially redacted export.

If the whole projection, required audit or package cannot be produced, the
response contains no rota content. Return to Shift planning and try again after
the dependency or volume problem has been resolved. Do not treat an unavailable
or empty result as an all-clear.

## Contents and integrity

| Member | Meaning |
| --- | --- |
| `rota.json` | UTF-8, version-one Shift and retained-commitment snapshot. |
| `schema.json` | Closed JSON Schema 2020-12 for that exact interchange format. |
| `rota.html` | Self-contained, escaped print copy; no remote assets or scripts. |
| `README.txt` | Portable instructions and explicit limitations. |
| `manifest.json` | Byte lengths and SHA256 hashes for the other four members. |

Extract only these fixed member names to a fresh directory. Verify each length
and hash against the manifest before relying on a transferred copy. Validate
`rota.json` against `schema.json` with a JSON Schema 2020-12 validator. The hashes
detect accidental corruption; an attacker can replace the whole package and its
manifest, so obtain copies through your approved channel. Opening HTML locally
does not authenticate the exporter or check current Maru permissions.

## Check a saved ZIP locally

In a Maru source checkout with its locked environment installed, run:

```powershell
.\.venv\Scripts\python.exe -B -m maru.workforce.rota_integrity "C:\Copies\rota.zip"
```

Use the already installed environment directly; `-B` prevents Python bytecode
cache writes. No dependency installer or environment synchronization is needed.
On other systems use that environment's Python with the same `-B -m` arguments.

The command needs only the saved file. It does not start Django, contact Maru or
another service, extract files, open HTML, or alter the source copy. Success
prints the fixed five-member count, four matched content hashes and total
uncompressed bytes. It does not print edition, person, path or rota content.

**A successful check means that the bytes match the supplied manifest.** It
does not authenticate a sender or make HTML safe to open. An attacker can replace
both data and hashes. Obtain the copy through an approved channel, then separately
validate `rota.json` against `schema.json` with a trusted JSON Schema 2020-12
validator before using it. The command reads the supplied schema as bytes; it
does not execute it or follow references. Matching integrity is not evidence of
current permission, freshness, coverage, readiness or a restored database.

| Boundary | Limit or behavior |
| --- | --- |
| Archive | One regular file, at most 16 MiB plus 64 KiB. |
| Complete uncompressed contents | At most 16 MiB across all five members, including the manifest. |
| Manifest | At most 8 KiB; exact version-one root and four file entries; no duplicate JSON keys or extra fields. |
| ZIP directory | At most 4 KiB, checked before entries are constructed; exactly five fixed names. |
| Supported ZIP form | One disk, ordinary terminal end record, stored or deflated regular members with matching local/central headers and contiguous member bytes; no ZIP64, data descriptors, archive/member comments, encryption, duplicates or special files. |

The checker measures the complete stored or deflated contents and CRC. A small
declared ZIP size cannot hide extra bytes or bypass either uncompressed limit;
deflated data must reach its actual stream end without trailing compressed bytes.
ZIP64 locators are refused before directory entries are constructed. File opening
uses a nonblocking descriptor where supported, then checks that same descriptor is
regular, so a Unix pipe needs no writer to receive a refusal.

These additional limits include the current exporter output. Repackaging a ZIP
may produce a refused form even when its contents look similar; obtain a fresh
authorized export rather than editing the checker or manifest to force a pass.

Exit `0` means matched integrity, `1` means refusal, and `2` means invalid command
arguments. A refusal prints one fixed code and asks for a fresh authorized copy:

Invalid arguments print only `invalid_arguments` guidance, without echoing a
rejected path or option. Keep a path containing spaces within quotes as shown
above, and provide exactly one saved ZIP path.

| Code | Next action |
| --- | --- |
| `unavailable_file` | Check that the selected file is readable and regular. |
| `archive_too_large`, `contents_too_large` | Keep the source; obtain a bounded export from the authorized organizer. |
| `unsupported_archive_layout`, `unsupported_member`, `invalid_members` | Do not unpack or open the copy; obtain the original exporter ZIP. |
| `invalid_archive`, `invalid_manifest`, `content_mismatch` | Treat the transfer as damaged or unsupported and request a fresh copy. |

No partial success, extraction or repair mode is provided. Follow the existing
personal-data custody and retention policy for refused copies too. This command
does not complete #22's import, reconciliation, history/exit or restore scope.

## Version-one field meanings

| Object | Fields and meaning |
| --- | --- |
| Root | `format` is `maru.workforce-rota`; `version` is `1`; `observed_at` is the UTC snapshot observation time; `limitations` states the copy boundary; `shifts` is the complete bounded inventory. |
| `scope` | Exact `organization_id`, `series_id`, `edition_id`, edition name/version/lifecycle, local start/end dates, IANA `time_zone`, and immutable profile code/version. |
| Shift identity | `id` and `version` identify the retained demand revision; `position_id`, Department name and Position title provide operating context. |
| Shift terms | Title, lifecycle status, UTC and offset-bearing local start/end, location, briefing, supervision, required headcount, break and minimum rest. |
| Coverage | `claimed_count`, `confirmed_count` and `remaining_count`; the last is capacity without a claim, not a promise of confirmed staffing. |
| Commitment | Retained `id`, `version`, display label and status, captured Availability/qualification-current booleans and UTC rest end. No platform account ID is supplied. |

UUIDs are stable record references, not credentials. Display labels are not
unique person identifiers. Demand states are Draft, Open, Locked, Cancelled and
Completed. Commitment states are Claimed, Confirmed, Removed and Completed.
Removed rows remain visible but do not cover work. A claim is not confirmation;
captured suitability does not establish future suitability or readiness.

UTC instants preserve absolute ordering. Local instants retain their UTC offset
and the IANA zone identifies daylight-saving rules. Both dates are printed for
overnight work. Every demand and commitment version describes its captured row;
changes made after observation do not update the file or paper.

## Privacy, limits and manual fallback

The copy excludes exact Availability calendars, identity contact fields,
application/onboarding documents, decision reasons, authority records and all
unrelated module data. Operational briefing and supervision text remain private
work instructions and may themselves contain personal information.

The whole existing planner inventory is limited to 1,024 demands and 4,096
retained commitments in total. The complete uncompressed package and individual
print output are limited to 16 MiB. These are refusal limits, not pagination or
truncation instructions. An empty valid edition produces an explicit empty copy.

Record approved manual notes separately. Paper changes and edited JSON do not
change Maru. Before resuming, an authorized organizer must compare live versions
and current suitability and use the existing governed commands, including their
independent confirmation and conflict rules. This increment supplies no importer
or automatic reconciliation. It is not a complete history/exit archive, backup,
restore, timekeeping record, profile expansion or decommissioning tool.

Each successful print or download records minimized `workforce.rota.export`
evidence under the existing Workforce-personal retention class. That marker does
not set a legal retention duration. The organization must approve copy custody,
access, retention, disposal and any operational manual procedure before real use.

See [Workforce-only adoption and recovery](workforce-only-adoption-and-recovery.md),
[the page contract](../product/page-contracts/shift-planning-and-my-shifts.md),
and [ADR 0127](../architecture/decisions/0127-bounded-workforce-rota-portability.md).
