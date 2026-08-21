# Third-party notices

Maru-owned source code is licensed under the Apache License, Version 2.0, as
provided in [LICENSE](LICENSE). Maru application and Python distributions also
contain the bundled Staff Console components listed below. Those components
remain licensed under the MIT License; Maru's Apache-2.0 license does not
replace their terms.

This notice covers the JavaScript runtime code compiled into
`src/maru/core/static/staff-console/app.js`. The release image's generated SBOM
records its built dependency inventory. The Python and pnpm lock files record
resolved development and runtime inputs, including packages that are not
necessarily shipped in every distribution; they are not substitutes for this
bundled-code notice.

## Bundled Staff Console components

The direct dependency versions come from
[`frontends/staff-console/package.json`](frontends/staff-console/package.json).
The exact transitive resolution, including Scheduler, is fixed by
[`frontends/staff-console/pnpm-lock.yaml`](frontends/staff-console/pnpm-lock.yaml).
The upstream source links use the verified React `v19.2.8` tag.

| Component | Version | Relationship | Package provenance | Upstream source |
| --- | --- | --- | --- | --- |
| React | `19.2.8` | Direct Staff Console runtime dependency | [`react@19.2.8`](https://www.npmjs.com/package/react/v/19.2.8) | [`packages/react` at `v19.2.8`](https://github.com/facebook/react/tree/v19.2.8/packages/react) |
| React DOM | `19.2.8` | Direct Staff Console runtime dependency | [`react-dom@19.2.8`](https://www.npmjs.com/package/react-dom/v/19.2.8) | [`packages/react-dom` at `v19.2.8`](https://github.com/facebook/react/tree/v19.2.8/packages/react-dom) |
| Scheduler | `0.27.0` | Transitive runtime dependency of React DOM | [`scheduler@0.27.0`](https://www.npmjs.com/package/scheduler/v/0.27.0) | [`packages/scheduler` at `v19.2.8`](https://github.com/facebook/react/tree/v19.2.8/packages/scheduler) |

All three packages contain the following license and copyright notice.

## MIT License text

MIT License

Copyright (c) Meta Platforms, Inc. and affiliates.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
