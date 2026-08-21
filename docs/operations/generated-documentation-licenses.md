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
copyright and permission text. Mermaid `11.12.1`,
`@mermaid-js/layout-elk` `0.2.0`, and D3 `7.9.0` are loaded by the generated
site as external browser resources rather than copied into the documentation
archive. Their network, Content Security Policy, and license posture remains a
separate deployment review; the notice above covers the extension-authored
code that is copied inline into generated pages.

All seven complete license texts live under `docs/_static/licenses/`, so Sphinx
copies them into every generated site. That makes the project and browser-asset
terms available in ordinary contributor-documentation artifacts as well as in
future static hosting and release archives.

The release workflow removes Sphinx's `.doctrees` cache and places Maru's
`LICENSE` and root `THIRD_PARTY_NOTICES.md` beside the generated site before
creating the documentation archive. These notices describe the exact locked
build represented by `uv.lock`; update this page and the copied license texts
whenever the documentation asset versions change.
