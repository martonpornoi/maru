# Guides and inherited Announcements admin theme

- Date: 2026-10-09
- Status: Focused source and synthetic component-browser checks complete
- Requirements: UX-007, UX-008, UX-010, UX-031
- Decision: [ADR 0116](../architecture/decisions/0116-approachable-convention-work.md)

The local Guides preservation snapshot is
`4c4393ec4cba6607f6c08cf725ebb8ad12689ec1`. This separate follow-up repairs
light text over the baseline cream body in dark mode: the two owner bases now
carry the existing `baseline-unified-admin` body class. Their setup and task
children inherit the same fix. Shared Core dark breadcrumb tokens now specify
both foreground and link colors; the light token block stays unchanged.
The shared event-context line uses `--body-quiet-color` inside the existing
admin body class, matching other secondary text in each theme.
No form, action, destination, actor admission or content projection changed.

The production scope is `knowledge/base.html`, `announcements/base.html` and
`core/admin-help.css`, plus the single context-line selector in `core/baseline.css`.
Existing owner view, setup/form, accessibility and brand suites passed **98 cases
in 4.65 seconds**, then **98 in 2.51 seconds** after the context-line correction.
No new mirrored class/token test was added. Source whitespace and documentation checks accompany the final manifest.

Ignored evidence is under `.tools/guidance-development/theme-repair-01/`.
`source-before.json` binds the clean snapshot; `focused.log` and `focused.xml`
retain the unit result. The renderer emits twelve pages from actual templates,
forms and URL reversal: setup choices, new-event setup and workspace, in each
owner's light and dark appearance. Twenty-four template origins and thirty
static assets are hash-bound, with before/after source equality. Database,
outbound-network and subprocess guards recorded **zero attempted calls**.
An explicit UTF-8 declaration and theme preference are the only preview HTML
injections; shell availability and owner presentation data are synthetic,
without real accounts or authority.

The first preview manifest,
`rendered-20261009T212050356838Z/manifest.json`, SHA-256
`78a6cc51d8c3f1e42e5ca8aaaf4faf26787f21a11697791feec2cdd287108c5c`,
is preserved. The parent's browser check found a preview-only missing charset
and a real shared context-line contrast defect: fixed light-color text over the
dark body. Actual Django responses already specify UTF-8; only the ignored
renderer needed that declaration. The shared context selector is the bounded
production correction. Other branches inherit the finding but are untouched;
previous Service body/heading measurements did not measure this context line.

The corrected preview is `rendered-20261009T212252376203Z/manifest.json`, SHA-256
`2f137599a4c702678c6e242efb817750b36b44b3d48435d30203f3baefc1533f`.
The parent subsequently browser-checked this exact preview; preparation itself
started no server or browser. The findings are recorded below. Static preview
and focused tests do not prove authenticated role isolation, native workflow,
specialist accessibility, independent-person, operational or production acceptance.

Only this Guides checkout changes. Announcements' frozen certification source,
all migration bytes, observed pins and runtime permissions remain untouched.
The recorded Guides native routing blocker and remaining acceptance gates stay
open; Programme #48 remains deferred.

## Component-browser verification

The parent checked **24 cases** on the fresh loopback origin `127.0.0.1:8772`:
twelve pages at **320 × 800** and **1280 × 800**, retaining each page's selected
light/dark theme. All used UTF-8, one H1 and one main landmark; none had page-level
horizontal overflow. Every form control had a label. Console warnings/errors
were empty. Narrow Guides and dark desktop Announcements screenshots were
visually inspected. The exact supplied measurements and cleanup report are in
ignored `browser-parent-evidence.json`, bound to the corrected preview manifest.

| Visible text | Light foreground / background RGB | Dark foreground / background RGB |
| --- | --- | --- |
| Body | 7,27,58 / 250,243,227 | 255,250,240 / 3,13,29 |
| Event context | 103,89,67 / 250,243,227 | 195,206,221 / 3,13,29 |
| Breadcrumb | 7,27,58 / 238,218,178 | 255,250,240 / 24,48,82 |
| Breadcrumb link | 92,60,18 / 238,218,178 | 227,196,134 / 24,48,82 |

Workspace action links measured **44 pixels** high and the setup submit button
**46.59375 pixels**. Setup-choice/back links remain ordinary text links with
**19-pixel** geometry; this evidence does not claim every link is 44 pixels.
At 320 pixels in dark mode, Return opened the native Access disclosure, Space
closed it, and a **3-pixel** focus outline remained visible without overflow.

An initial arrow encoding artifact came from a stale cached stylesheet decoded
under the older static HTML. Source bytes are correct UTF-8; the fresh origin
rendered the down-arrow correctly in all 24 cases. This was not a production
encoding defect, and prior evidence is preserved. No forms were submitted.
The owner closed tab 12, reset the viewport and stopped the exact owned HTTP
sessions 22758 and 75779; the latest exit 1 was expected from Ctrl-C.

These are synthetic presentation checks only. Current-actor authorization,
source/tenant isolation, full workflow, native SQL and broader acceptance remain
separate and unproved by these components.
