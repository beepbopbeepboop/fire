# Gate: bootstrap-stage2-dumps:array_ops_jit.mojo is red on master

**Job:** `bootstrap-stage2-dumps:array_ops_jit.mojo`. Filed by the full gate at `c0182fd365`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

## Done when

`python3 tools/suite.py bootstrap-stage2-dumps` is green against a
`stage2/mojo` built from this tree (which needs
`bootstrap-stage1-transitive` -> `bootstrap-stage2-cc` first), and
`test_gimple.py::test_every_lazily_initialised_generator_table_exists`
passes (it pins the class of NULL lazy table this item hit).

**Landed 2026-11-21:** every `if not hasattr(gen, ...)` lazy table initializer
on `GimpleGen` is now declared in `__init__` (the `_global_slot_info` one this
item's crash went through included), so the compiled compiler cannot reach a
NULL MojoDict/MojoSet/MojoList through that pattern; the test named above scans
`gimple_codegen.py`, `mojo/backend_gimple/` and `mojo/middle/closures.py` for a
new guard and for a declared container type that disagrees with it. Only the
stage2 rebuild is left.

Reproduce on master (`python3 tools/suite.py bootstrap-stage2-dumps:array_ops_jit.mojo`), then fix the cause.

## Gate ledger

- **Last known working:** `d0c0a1cc57` integrate bug-codegen-stdlib-syntax-six-files-red
- **First known not working:** `0b0316114e` integrate fix-gate-formal-host-import-shapes
- **Seen red in the full gate at:** `8a4b0af29f` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-8a4b0af2.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-bootstrap-stage2-dumps:array_ops_jit.mojo.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
