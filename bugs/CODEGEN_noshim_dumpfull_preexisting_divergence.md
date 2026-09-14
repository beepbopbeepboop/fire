# CODEGEN_noshim_dumpfull_preexisting_divergence: check-noshim-dumpfull fails on b00955c itself

## Status (2026-09-13 — found, NOT fixed, confirmed pre-existing)

`make check-noshim-dumpfull` (`test_noshim_dumpfull.py`, added in commit
`b00955c` as DESIGN.html R6) fails:

```
✗ MOJO_NO_SHIM=1 ./mojoc output DIFFERS from the shim's own --dump-full
output: shim=32886825 bytes, no-shim=~27-28MB, first differing byte at
offset 2390 - the self-hosted binary is miscompiling itself even though
it exited 0
```

**Confirmed pre-existing, not caused by the same-day R3 cast-migration
session**: reproduced identically (same failure, same offset 2390) after
`git stash`-ing every R3-session change back to the exact `b00955c` tree
state and rebuilding `mojoc` from scratch (`rm -f mojoc && make mojoc`).
`b00955c`'s own commit message added this check but — per
`design-container-typing-audit` project memory — "Full gate NOT re-run
after b00955c — only syntax + one real do_imports=True compile check."
This check was added but never actually run to see if it passed; it
doesn't.

The failing byte offset (2390) is very early in the `--dump-full` output
and consistent across multiple independent rebuilds, suggesting a
systematic divergence (e.g. a preamble/header section or an early-defined
symbol) rather than something deep in per-function body codegen. The
overall size gap (~5MB, shim larger) matches the same shape as the
`selfhost-dump-full-module-drop` project memory's prior incident — some
whole section or set of modules is present in the shim's build but
missing from the self-hosted `mojoc`'s own compiled path.

## Root-cause investigation (2026-09-13, continued)

Diffed the actual `.ci` output at offset 2390: the self-hosted (no-shim)
build's forward-declaration list is missing `void
_gimple_gen_coro_toplevel(void);` entirely — present in the shim's output,
absent from the no-shim one. Confirmed this isn't just the declaration:
`grep -c "_gimple_gen_coro_" ` finds 380 occurrences in the shim's `.ci`
vs only 26 in the no-shim one — the self-hosted `mojoc` is dropping nearly
all of `gimple_gen_coro.py`'s own compiled content from its transitive
closure when compiling `mojo.py --dump-full`, matching the
`selfhost-dump-full-module-drop` project memory's prior incident shape
(a whole sibling module silently missing, exit code 0).

**Ruled out:**
- Not caused by this session's R3 work (see Status above — reproduces
  identically on the pristine `b00955c` tree).
- Not simply "imported without an `as alias`" (unlike its ~10 sibling
  `gimple_*` imports in `gimple_codegen.py`, `import gimple_gen_coro` has
  no alias) — built a minimal 2-module isolated repro (one aliased import,
  one bare) and both modules were fully compiled in both the shim and
  no-shim `--dump-full` output; the drop did not reproduce in isolation.

**Still open**: something specific to `gimple_gen_coro.py`'s own content
(2600+ lines, includes large multi-line C-template string literals) or
its position among `gimple_codegen.py`'s real ~20-module import graph
triggers the self-hosted-only drop; the minimal repro didn't capture
whichever factor that is. Next step needs either bisecting
`gimple_gen_coro.py`'s content (comment out large chunks, see when the
drop stops) or instrumenting `_compile_imported_module` (gimple_module_
gen.py) to log when it returns empty/`None` code for a module, run under
`MOJO_NO_SHIM=1`, and see what it reports for `gimple_gen_coro` — this
needs the gdb/instrumentation methodology in `HOW-TO-DEBUG.html`, not
attempted this pass (open-ended; matches the multi-day effort shape of
prior instances of this bug class per project memory).
