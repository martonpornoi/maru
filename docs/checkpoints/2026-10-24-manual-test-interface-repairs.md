# Local manual-test interface repairs — 24 October 2026

## Report, ownership and preserved scope

The maintainer reported missing organization creation, low-contrast actions,
misaligned governance radio buttons, locale-dependent AM/PM pickers, invalid
tutorial question keys, inconsistent volunteer setup titles and a blocked Alex
journey. Repairs map to UX-007/016/024/029/031 and the existing management-shell,
Events/Organizations/Registration and Workforce contracts. They change browser
presentation and documentation, not domain authority, immutable profile meaning,
database schema, API serialization, native guards or the identity boundary.

The prepared `codex/manual-test-from-empty` worktree retains its earlier local
guide changes. Every original source touched by the repair is backed up in the
ignored repair bundle. A custom PostgreSQL dump was saved and read back before
restarting only the exact owned web process; all owning-module model counts were
identical before and after. Existing passwords, sessions, registration definitions,
Departments, editions, governance, worker and inbox were preserved. No manual
records were deleted, reparented, reseeded, accepted or granted new authority.

## Changes

- The organization inventory exposes Create organization beside its resource
  count, keeping the unavailable-inventory state read-only.
- Volunteer setup uses Set up a volunteer team in the menu, document title,
  breadcrumb, heading and action. It requires an explicit create/reuse choice;
  existing choices include stable organization locators. Provisioning workspaces
  link to Finish accountable access before ordinary controllers operate them.
- Shared choice fields use fieldsets/legends and individually labelled radio
  controls, with intrinsic control sizing and horizontal label alignment.
- Action links retain button foreground/background colors after visiting them.
  Panel headers and required/error labels use the theme's contrast colors.
- Shared widgets provide typed `YYYY-MM-DD` dates and 24-hour
  `YYYY-MM-DD HH:mm:ss` local input. Existing domain parsers still own zone, DST,
  precision and validation. Minute fields accept `:00` and reject nonzero seconds;
  no seconds are silently truncated. Existing split application date/clock controls
  remain typed and preserve closed transport/cardinality checks. Staff-console
  typed dates reject guessed formats and invalid calendar rollovers before the
  existing UTC request is produced. Generated frontend assets use the normal build.
- The tutorial uses `badge-name`, `first-visit`, `welcome-note`, `temporary-note`
  and `day-pass`. It explicitly distinguishes its registration and Crew editions,
  specifies the correct series-reuse radio choice, and gives preserving recovery
  instructions for the maintainer's actual two-organizer state. Its 113 checkbox
  positions and existing local-storage key remain unchanged.

## Diagnosis of Alex's access

The first organizer is Active with accepted Alex/Blake Executive Board
appointments. The Crew edition was made under a same-named second organizer,
whose URL ends in `-2`, with a Provisioning Maru-operator representation and no
appointments. Alex's first-organizer authority must not cross this tenant
boundary. The correct continuation is to invite the same existing verified people
as that second organizer's controllers, let each answer in their own session,
then activate its representation. The guide links the exact existing record.
No new account or third edition is needed. A later fresh run should explicitly
reuse the first series instead of entering the existing name as a new foundation.

## Evidence and limits

Focused input/template feedback passed 168 cases. The complete database-free
suite passed 14,432 cases in 87.46 seconds with eleven existing warnings. The
first broad run's two legacy display expectations and 512 global-pytest-temp
permission errors remain recorded; the second run used a fresh owned temp path,
without deleting or changing permissions on the old temp directory. All 124
frontend cases passed and the frontend type-check/normal build passed. Lint,
strict Python types, semantic docstrings, documentation policy and whitespace
checks are part of this repair handoff.

Browser checks used the real platform-admin session for discovery/action labels,
foundation choice, safe governance continuation and registration inputs. Actual
choice widgets were rendered in a synthetic component preview and measured at
312, 614 and 1,024 CSS pixels: six radio controls beside their text, approximately
18.4 pixels wide, and no page overflow. Light/dark screenshots and color checks
are local evidence. Initial stale CSS observations were retained and resolved by
refresh; the maintainer should hard-refresh existing tabs. Viewport overrides and
temporary preview resources are cleaned up. The main test app remains running.

No full local certification, native-history run, hosted acceptance, protected
delivery, broad accessibility matrix or independent-human acceptance is claimed.
The actual Alex/Crew browser continuation remains the maintainer's work after
recipient-owned acceptance; no password was requested or reset. All earlier
production/recovery and #42 boundaries remain open.
