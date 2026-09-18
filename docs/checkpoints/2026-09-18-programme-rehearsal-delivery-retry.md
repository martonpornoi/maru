# Programme rehearsal composition: protected delivery retry

Date: 2026-09-18
Pull request: [#164](https://github.com/martonpornoi/maru/pull/164)

The initial composition head `21758543e0a2558f3b8b0cfef18cea3e6f93f495`
completed all eight retained local gates against protected base
`2e3ddb13c06122a7c73a491d17d64e4bc071662e` in **332.971 seconds**.
The exact run passed **10,285 units in 59.80s** and **103 frontend cases**.
Receipt v4 reports `postgresql_deferred`, development passed, zero database
instances and null combined coverage/headroom. Its SHA256 is
`9CFBE6CF1DCCEDA37F97085F4DC8D1B325111C994A7CD06C35B4521B2DA2243B`.
Receipt, plan, unit JUnit and both package artifacts were copied with matching
hashes to `.tools/certification-evidence/issue108-2175854-deferred/`.

Hosted exact-head run **35297257457** passed: units **2m18s**, quality **9m51s**,
aggregate PR gate **3s**. All three CodeQL analysis jobs completed successfully,
but the JavaScript job in managed run **35297255137** reported a timeout waiting
for its uploaded SARIF to finish processing. The combined CodeQL check remained
neutral, reporting the missing `/language:javascript-typescript` configuration.
The analyses API returned only Python and Actions for this exact PR head;
GitHub consequently reported `BLOCKED`, despite `MERGEABLE` content and no
reviews, unresolved threads or closing-issue references.

GitHub refused both the individual JavaScript-job retry and whole managed-run
retry. On resumption the same missing result remained. This documentation-only
update preserves the actual checkpoint and requests a fresh ordinary synchronize
analysis, with fresh local certification before push. It does not change source,
tests, workflows, settings, rulesets, profile activation or the deferred database
policy. No prior receipt or hosted result is presented as acceptance of the new
head. Merge remains conditional on its complete protected acceptance; no bypass,
merge or main synchronization has occurred at this checkpoint.

#108 and #48 remain open. This delivery recovery adds no product scope and does
not complete the disposable runner, native installation, realistic setup/roles,
P01–P12 rehearsal or the #102/#97/#92/#109 final acceptance gates.
