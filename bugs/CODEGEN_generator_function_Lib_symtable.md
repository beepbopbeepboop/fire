# CODEGEN_generator_function: Lib/symtable.py

## Status (updated 2026-08-06)

Re-diagnosed against current master (`2b0c4c5`) — the 2026-07-30
`'flagname' was not declared` .cpp error no longer reproduces.
`symtable.py` has one generator (`yield flagname`, line 302) — it does
NOT appear anywhere in a full `MOJO_DEBUG=1` build log (0 `error:` lines
in the entire ~144K-line output, only warnings; no "not eligible"
refusal naming it either): symtable.py's own generator appears to
compile cleanly through the coroutine path.

`mojo.py build` still exits non-zero, but the failure point wasn't
pinned down in this pass — the gcc/g++ compile stage(s) visible in the
log show zero hard errors, so the actual failure is presumably at a
LATER stage (link, or a companion-.cpp step not captured by this file's
grep-based triage) not yet isolated. This build is also unusually slow
(minutes) — consistent with the already-documented, unrelated
`bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_rescan.md`
perf issue for files with a moderately large transitive import graph,
not a new finding here.

**Classification: very likely NOT a generator-codegen-cluster failure**
(symtable.py's own generator shows zero signal of any problem), but the
true current failure point needs a cleaner re-run (e.g. capturing the
link step's own stderr separately) to state with full confidence. Left
open rather than marked fixed.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/symtable.py
