# Checkpoint: Programme verification dependency security repair

- Date: 2026-10-01
- Phase: Protected #203 delivery preparation; acceptance remains pending.
- Related requirements: NFR-001/002/005/013.
- Related ADRs: 0063/0064, 0090, 0098, 0115.

## Outcome and scope

The required dependency audit stopped certification of
`c9a440a11aea16ee2d0010e6e6448782ccb8973c`. It reported urllib3 2.7.0 affected by
CVE-2026-97687, CVE-2026-97688 and CVE-2026-97689, with 2.8.0 listed as the fix.
This is a delivery prerequisite for #203, not a new Programme capability or an
audit waiver. No exploitation or production exposure is asserted.

The [upstream 2.8.0 release](https://github.com/urllib3/urllib3/releases/tag/2.8.0)
fixes HTTPS-proxy TLS configuration and two response-streaming problems. Its
maintainer advisories cover [proxy TLS](https://github.com/urllib3/urllib3/security/advisories/GHSA-8988-9cw3-xx77),
[Deflate streaming](https://github.com/urllib3/urllib3/security/advisories/GHSA-gh4c-6fx4-qh6g)
and [unbounded chunk-size buffering](https://github.com/urllib3/urllib3/security/advisories/GHSA-vxq7-64xx-v4gw).
The proxy fix separates proxy identity and trust settings from destination
settings; no Maru proxy or TLS setting was changed to accommodate it.

## Bounded repair

Add the uv resolution constraint `urllib3>=2.8.0,<3` to `pyproject.toml` and
regenerate `uv.lock` with `uv lock --upgrade-package urllib3==2.8.0`. Exactly one
package version changes, 2.7.0 to 2.8.0, alongside its hashes and matching manifest
constraint. All other versions stay pinned. Constraints restrict resolution
without introducing a dependency, as described in the
[uv settings contract](https://docs.astral.sh/uv/reference/settings/#constraint-dependencies).

The inverse locked dependency tree places urllib3 beneath Requests, used by
pip-audit/CacheControl and Sphinx-related development tooling. The `--no-dev`
inverse tree is empty. No direct urllib3 or Requests import was found in Maru
source, scripts or rehearsal modules. Runtime requirements, production HTTP,
native fixture authority, schema and CI thresholds remain unchanged.

## Failed-attempt preservation

The ordinary certifier starts its unit process and PostgreSQL pool alongside the
other gates. After the audit failed, the maintained `.local-ci/cancel-pool`
control stopped the eight active shards instead of spending hours on a candidate
already known to fail. Zero shards completed successfully; all eight report owned
container removal. These interrupted jobs are not assertion failures or successes.

The unit process completed **13,457 passed / 197.05s**, with three existing warnings.
The one-shot worker exited 1 at 17:00:35 UTC. No certification receipt was created.
Actual worker/pool processes and `maru-cert-*` containers were absent before the
environment changed. All **820** surviving `.local-ci` files were copied and
individually SHA-256 compared under
`.tools/certification-evidence/programme-local-c9a440a-audit-failed/local-ci`;
the sibling inventory and worker logs/metadata preserve the failed audit.
Older interrupted and complete evidence is untouched.

## Verification and remaining delivery

Locked synchronization and `uv lock --check` pass. The unchanged `pip-audit`
reports **no known vulnerabilities** after the update; its JSON result is retained
at `.tools/programme-203-urllib3-20261001-audit.json`. The project itself remains
the normal local-package skip, not an ignored third-party advisory.

Complete fast unit feedback passes **13,457 / 74.45s**, with the same three Django
URL warnings. Documentation validation passes **704 Markdown files, four skills
and 215 requirements**. Repository-wide Ruff lint and formatting checks pass;
all **1,663** Python files already meet formatting, and whitespace checks pass.

Commit the final repair, then perform fresh exhaustive exact-head certification
and independent GitHub acceptance. The earlier eighteen-phase joined result remains precisely
attributed to `0d2a3aa`; it does not certify this later dependency change. No
protected merge, profile promotion, deployment or human pass is claimed here.
