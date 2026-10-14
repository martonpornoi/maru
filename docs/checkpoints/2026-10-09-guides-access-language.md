# Plain shared Access explanations

- Date: 2026-10-09
- Status: Focused source and changed-component browser checks complete
- Requirements: UX-006, UX-029, UX-031
- Decision: [ADR 0116](../architecture/decisions/0116-approachable-convention-work.md)

After the separately preserved [theme component checks](2026-10-09-guides-admin-theme.md),
this bounded Guides-only change replaces three shared presentation strings.
The unresolved scope says **This page** and explains: "This page has its own
access rules. You cannot change who has access from this page." Fixed-policy
summaries use **Rules for this page**.

Review of `knowledge/access_views.py` found that real Guides access-request,
approval and removal screens use the fixed summary while offering their own
independently authorized actions. A global "Access cannot be changed here"
label would have contradicted those actions, so it was rejected before editing.
The generic fallback seen in synthetic previews is not proof that actual setup
routes use it: Announcements setup supplies an explicit platform explanation.

Only display text changes. Policy values, exact targets, audiences, allowed
actions, management URLs and signed-token behavior remain unchanged. Existing
rendering tests cover escaped scope text, unresolved private context omission
and absent generic management links; a concrete Guides access test retains its
own request/removal links and independent-approval explanation. The focused
rendering, token, access and activation batch passes **62 cases in 1.70 seconds**.
Scoped static checks and final hashes are retained in ignored
`.tools/guidance-development/access-copy-01/`.

The original theme/browser evidence remains intact and predates this copy delta.
The changed-component verification below is separate. No database, container,
native test, account, runtime grant, profile, migration or other worktree changed;
no authenticated workflow acceptance is claimed.

## Changed-component browser verification

The guarded renderer produced the generic fallback and the actual Guides access
workspace, each in light and dark, using real templates and existing synthetic
unit projections. Nine template origins and twenty-nine assets are hash-bound;
all fourteen cumulative source paths matched their freeze. Rendering attempted
zero database, network or subprocess calls. The preserved output is
`rendered-20261009T213703069445Z/manifest.json`, SHA-256
`b55120b76211a2e06a823a32fb3d49cc643691f284494b38e9999c9caab40efc`.

The parent checked **eight combinations** on `127.0.0.1:8776`: four pages at
**320** and **1280 pixels**. Each kept its expected theme, one H1 and one main
landmark, with no horizontal overflow or console warnings/errors. The fallback
summary reads **Access / This page / Rules for this page**. Return opens the
exact approved explanation; the disclosure has no links. Space closes it and
the 3-pixel focus outline remains visible. Expanding it caused no overflow at
320 pixels in dark mode.

The concrete **Manage access to guides** page keeps **Rules for this page**,
the independent second-person explanation, and the original **Request access
for someone** and **Remove this assignment** destinations. Return opens its
native summary with a 3-pixel focus outline and no overflow. Its 320-pixel dark
screenshot was inspected. No access action or form was submitted.

The owner closed tab 16, reset the viewport and stopped only HTTP session 16575;
exit 1 was expected from Ctrl-C. Exact supplied observations are retained in
ignored `browser-parent-evidence.json`. The earlier twenty-four theme cases
remain bound to the source before this copy delta. Both sets are synthetic
presentation evidence, not authenticated role, live workflow, native SQL,
specialist accessibility, operational or production acceptance.
