# Module catalog

**Audience:** Contributors changing production behavior or cross-module
contracts\
**Outcome:** Identify the owning module and its supported public boundary\
**Reading time:** 2 minutes plus the selected module guide

Open the [implemented-module overview](README.md) first. It distinguishes
implemented modules from future product capabilities and links each owner.
Individual guides document data, invariants, commands, queries, events,
permissions, consumers, failure behavior, tests, and known limitations.

Do not import another module's private implementation or move a cross-module
write into a generic helper. Use the documented public boundary and review the
[architecture overview](../architecture/overview.md) when ownership is unclear.

```{toctree}
:hidden:
:maxdepth: 1
:glob:

README
[a-hj-z]*
id*
```
