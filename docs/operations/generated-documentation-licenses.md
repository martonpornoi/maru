# Generated documentation third-party licenses

Maru's generated contributor site contains browser assets produced by the
locked documentation toolchain. The project content remains covered by Maru's
Apache-2.0 license, while the following redistributed assets retain their
upstream terms.

| Component | Locked version | Distributed site content | License evidence |
| --- | --- | --- | --- |
| Maru | This build | Project-authored documentation, theme overrides, and source reference | [Apache-2.0 text](../_static/licenses/Maru-Apache-2.0-LICENSE.txt) |
| Sphinx | `8.2.3` | Search, highlighting, navigation, and base-theme JavaScript/CSS | [BSD-2-Clause text](../_static/licenses/Sphinx-LICENSE.txt) |
| sphinxcontrib-mermaid | `1.2.3` | Inline diagram bootstrap, fullscreen, zoom, and styling code | [BSD-2-Clause text](../_static/licenses/Sphinxcontrib-Mermaid-LICENSE.txt) |
| Furo | `2025.12.19` | Site theme JavaScript, CSS, and source maps | [MIT text](../_static/licenses/Furo-LICENSE.txt) |
| Pygments | `2.20.0` | Generated syntax-highlighting CSS | [BSD-2-Clause text](../_static/licenses/Pygments-LICENSE.txt) |
| normalize.css | `8.0.1` | Browser normalization rules compiled into Furo's CSS | [MIT text and copyright notice](../_static/licenses/Normalize-LICENSE.txt) |
| Gumshoe | `5.1.2` | Patched scrollspy compiled into Furo's JavaScript | [MIT text and copyright notice](../_static/licenses/Gumshoe-LICENSE.txt) |

Furo's generated `furo.js.LICENSE.txt` also travels beside its JavaScript, but
its compact banner is not a substitute for Gumshoe's complete notice above.
Likewise, Furo's normalize.css header identifies the component but not its full
copyright and permission text.

## External diagram runtime

ADR 0072 accepts a narrow browser-runtime dependency for the public contributor
site. `sphinxcontrib-mermaid` loads Mermaid `11.16.1` (MIT) and D3 `7.9.0`
(ISC) from exact-version jsDelivr package paths. The optional
`@mermaid-js/layout-elk` integration is explicitly disabled because no
maintained Maru diagram uses it. These external packages are not copied into
the generated archive; the extension-authored bootstrap and presentation code
is copied inline and remains covered by the extension notice above.

The accepted network prefixes are exactly:

- `https://cdn.jsdelivr.net/npm/mermaid@11.16.1/`; and
- `https://cdn.jsdelivr.net/npm/d3@7.9.0/`.

An exact package may load further files below its own versioned prefix. No
`latest`, unversioned package path, alternate script origin, analytics script,
or application credential is accepted. GitHub Pages does not give this project
a repository-controlled strict response-header Content Security Policy, and
the extension emits inline initialization. A CDN outage can therefore prevent
diagram enhancement, and compromise of accepted upstream delivery could run
script in the public documentation origin. That origin contains public static
content only, has no Maru authentication, secret, or personal-data authority,
and is isolated from GitHub cookies by the `github.io` public-suffix boundary.
This bounded availability and supply-chain risk is accepted for GH-007 rather
than adding a second JavaScript lock/build pipeline or a browser-bearing
pre-renderer solely for four maintained diagrams.

Mermaid `11.16.1` is intentional rather than the extension's older default: it
is the first v11 release patched for the 2026-08-04 moderate CSS sibling-
selector injection advisory. Maru does not accept a known-affected browser
runtime merely because diagram source is maintainer-controlled.

The first deployment and every diagram-runtime change must inspect a maintained
Mermaid page in a real browser. Require the diagram to become SVG, no browser
console error, and no script request outside the two accepted prefixes and the
same-origin generated site. Reconsider vendoring or pre-rendering before a
custom domain, strict documentation CSP, offline-site guarantee, authenticated
content, or materially larger diagram corpus. Review the upstream
[Mermaid license](https://github.com/mermaid-js/mermaid/blob/mermaid%4011.16.1/LICENSE)
and [D3 license](https://github.com/d3/d3/blob/v7.9.0/LICENSE) whenever either
exact version changes.

All seven complete license texts live under `docs/_static/licenses/`, so Sphinx
copies them into every generated site. That makes the project and browser-asset
terms available in ordinary contributor-documentation artifacts as well as in
future static hosting and release archives.

The release workflow removes Sphinx's `.doctrees` cache and places Maru's
`LICENSE` and root `THIRD_PARTY_NOTICES.md` beside the generated site before
creating the documentation archive. These notices describe the exact locked
build represented by `uv.lock`; update this page and the copied license texts
whenever the documentation asset versions change.
