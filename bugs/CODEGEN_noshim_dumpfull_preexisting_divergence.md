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

## Root-cause investigation (2026-09-13, continued further — two real findings)

Instrumented `_compile_imported_module`/`gen_module_impl` with temporary
`print()` tracing (env-var-gated at first, then a plain module-level
`bool` constant after `os.environ.get()` itself turned out to be
self-host-unreliable — see Finding 2 below) and rebuilt `mojoc` to trace
exactly what happens compiling `gimple_gen_coro.py`.

**Finding 1 (REAL BUG, FIXED, commit-worthy on its own)**: the trace
showed thousands of `vars: unavailable in compiled mode` messages fire
the instant `gimple_gen_coro.py`'s compile starts. Root cause:
`gimple_gen_coro.py` uses `for k, v in vars(node).items():` (10+ call
sites) to walk AST nodes generically, where `node`'s static type is
deliberately unknown (it needs to handle many different node types
uniformly). `_lower_call`'s `vars()` special case
(`gimple_gen_calls.py` ~line 1534) only routed through the real
`_mojo_dispatch_asdict` reflection helper `if gimple_exprtypes.
_struct_name_of(at) in gen.struct_field_types` (i.e. only when the
STATIC type happens to be known) — otherwise it fell through to the
generic "unresolved builtin" weak-stub path (print-and-return-0, a
no-op). But `_mojo_dispatch_asdict(void *obj)` (gimple_module_gen.py)
is ALREADY a fully general RUNTIME dispatcher — it reads the object's
own type tag via `mojo_read_type_tag_safe` and picks the matching
`_mojo_asdict_<struct>` at runtime, needing no static proof at all.
**FIXED**: removed the static-type gate entirely; `vars(x)` now always
routes through `_mojo_dispatch_asdict` (casting through `void *`).
Confirmed fixed: `vars:` print count in the `--dump-full` trace dropped
from thousands to exactly 0. `compile_stdlib.py` and the container-cast
counter both still pass after the fix (no regression). This means
`gimple_gen_coro.py`'s own generic AST-node introspection was silently
returning empty dicts instead of the node's real fields, throughout
the ENTIRE self-hosted build (not just for `gimple_gen_coro.py` itself)
— a separate, real correctness bug beyond just this gate's failure,
now fixed.

**Finding 2 (root cause of the module-drop, NOT fixed, needs careful
follow-up)**: even after Finding 1's fix, `gimple_gen_coro` still
compiles to `code_len=0` self-hosted. The trace (before the vars() fix
masked it with noise) showed the module-compile's `except Exception as
e:` handler in `gimple_gen_resolve.py` catching:
`AttributeError: environ` (a SEPARATE finding — see below) and, in an
earlier still-cleaner trace, exactly:
`zip() lowering needs a tuple loop target`
— the literal message `_gen_for_zip` (`gimple_gen_loops.py:1030`)
raises for `for (_n, a), pk in zip(real_params, param_kinds):`
(`gimple_gen_coro.py:2481` — a nested-tuple `zip()` target, an
explicitly-unsupported shape by design). This raise is SUPPOSED to be
caught locally by the `try/except` in `_gen_stmt_ForStmt`
(`gimple_gen_stmts.py` ~line 2731), which rolls back and falls through
to `_gen_for_iter(node)` — and does so successfully in the shim (the
shim's `--dump-full` contains gimple_gen_coro's full compiled content).
Self-hosted, the exact same exception is instead caught only by the
much-outer MODULE-level handler, meaning the intended LOCAL catch is
being skipped somehow. **Root cause not yet isolated** — ruled out
"try/except doesn't work at all self-hosted" (a standalone 2-level
nested try/except repro, built and RUN as an ordinary compiled target
program via `mojo.py build`, correctly caught a `ValueError` raised
from a helper two calls deep), and ruled out "only one unprotected call
site" (`_gen_for_zip` has exactly one caller, and it IS wrapped in
try/except). The exact mechanism by which THIS SPECIFIC try/except
fails to catch, only when the code compiling it is itself running
self-hosted, is still unknown.

**Finding 3 (separate, real, worth its own follow-up)**: `os.environ.get(...)`
itself raises `AttributeError: environ` in some self-hosted contexts
(discovered as an artifact of debug instrumentation — do not assume
`os.environ` is safe to use in this codegen's own source without
testing first).

**Important operational lesson learned the hard way**: setting a
debug-tracing module-level constant to `True` (to make the trace
`print()`s active) — even though it's a plain Python `bool` with no
apparent relationship to codegen logic — broke `make mojoc`'s own
SHIM-compiled build entirely (`error: invalid use of undefined type
'struct _gimple_gen_coro_toplev'`, `'struct _reflect_toplev'`). This
compiler does WHOLE-FUNCTION type unification (already documented
elsewhere in this codebase re: the `_mn`/`module_name` loop-variable
gotcha in this exact function) — adding new code to a self-hosted
function, even genuinely dead/inert-at-runtime code behind an `if
False:`-shaped guard, can still shift how OTHER variables in that same
function get statically type-inferred by THIS compiler's own
self-compilation, breaking things that had nothing to do with the
change. All temporary debug instrumentation for Findings 2/3 was
reverted (`git checkout --`) rather than left in the tree, even
disabled — confirmed `make mojoc` rebuilds clean (0 errors) again
afterward. **Any further debugging here should default to gdb on the
actual `mojoc` binary (per `HOW-TO-DEBUG.html`) rather than adding new
source-level tracing to the compiler's own self-hosted functions**,
given this demonstrated fragility.

## Next steps (not attempted this pass)

- Root-cause Finding 2 (why this specific try/except fails to catch
  self-hosted) via gdb on the `mojoc` binary — set a breakpoint on
  `mojo_raise`/the try-frame push/pop primitives, single-step through
  the actual generated GIMPLE for `_gen_stmt_ForStmt`'s zip branch, and
  see exactly which try-frame is "current" at the moment of the raise.
- Investigate Finding 3 (`os.environ` self-host reliability) separately
  — check whether it's a general lowering gap or context-specific.
- This is genuinely open-ended (matches the multi-day effort shape of
  prior instances of this bug class per project memory) — Finding 1 is
  a real, complete, verified fix landed this session; Findings 2/3 are
  diagnostic progress, not fixes.
