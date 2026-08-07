# HARD BUG: `_reset_func()` wipes global-scope container element/value-type inference before ANY function body can read it — including the already-shipped fix it silently undermines

## Status

Unfixed. Root-caused 2026-08-06 while investigating
bugs/COMPILE_FAIL_Apple_testbed___main__.md's `invalid operands to
binary / (have 'char *' and 'int64_t')` error. Started as an attempt at
a narrow, additive fix (teach `gen_module`'s Phase 1.7 global prescan to
also record a global DICT literal's VALUE type, mirroring the already-
shipped fix for global LIST literals' ELEMENT type — commit `fd29316`,
`bugs/COMPILE_FAIL_importlib__bootstrap_external.md`). That fix was
implemented, and confirmed CORRECT and REACHED by tracing (Phase 1.7
genuinely records `self._dict_val_types['TEST_SLICES'] = 'char *'`) —
but instrumented testing then showed it has **zero effect** on any
function body's own compiled output. Reverted (not committed) once the
real, deeper cause below was confirmed, per this session's standing
"don't land a fix that doesn't work, and don't chase a newly-revealed
wide-blast-radius mechanism without a dedicated pass" policy.

## Symptom (as observed via the abandoned attempted fix)

A module-level global container's element/value type, recorded by
`gen_module`'s Phase 1.7 pre-scan (`self._elem_types[gname]` for lists,
`self._dict_val_types[gname]` for dicts — the side-tables
`_lower_IdentExpr`'s "Module-level global variable" branch reads from
when materializing a global read into a local temp), is **silently
discarded before the FIRST function body is even looked at** — not
"sometimes lost across some functions", but unconditionally, for every
function, including the first one compiled.

## Root cause

`_reset_func()` (`gimple_codegen.py:4019`) runs at the very start of
`gen_func` (`gimple_codegen.py:20566`, first line of the method) and
unconditionally reinitializes both side-tables to near-empty:
```python
self._elem_types:      dict[str, str]   = {}
...
self._dict_val_types:  dict[str, str]   = {
    '_BIN_OPS': 'char *', '_GD_BIN_OPS': 'char *',
}
```
This reset exists for a real, necessary reason — it's also where
`_actual_types`/`_bound_method_ret_types`/etc. reset, all with the same
documented rationale ("temp names (`_tN`) recycle across functions, so
a stale entry from one function would mis-type a same-named temp in the
next"). That rationale is correct for anything keyed by a **temp**
name. But `_elem_types`/`_dict_val_types` are ALSO used to key entries
by a **global variable's own Python name** (`gname`, e.g.
`'path_separators'`/`'TEST_SLICES'`) — a name that is NOT a recycled
temp and does NOT need per-function isolation; it means the same thing
in every function that reads it. `_reset_func` doesn't distinguish the
two kinds of key at all — it wipes both indiscriminately.

`gen_module`'s call order is: Phase 1.7 (pre-scan, populates
`_elem_types`/`_dict_val_types` for every module-level global container
literal) → "Phase 2a: generate all function bodies" (loops over every
top-level `FunctionDef`, calling `self.gen_func(stmt)` for each). The
FIRST thing `gen_func` does is call `_reset_func()` — so Phase 1.7's
global-scope entries are gone before even the first function's first
statement is processed. Confirmed by direct instrumentation (see
Minimal repro below): a traced `_lower_IdentExpr('TEST_SLICES')` call,
occurring from deep inside the real (only) compile pass for a function
body, observes `self._dict_val_types.get('TEST_SLICES') is None` — despite
Phase 1.7 having unconditionally set it moments earlier, at the very
same `self` instance (confirmed via `id(self)`) and confirmed via a
full `traceback.format_stack()` dump that this genuinely is the Phase
2a `gen_func` call site (`gimple_codegen.py:29461`), not some earlier
speculative/dry-run pass.

## This ALSO retroactively undermines the already-shipped `_elem_types` fix

The list/tuple sibling of my attempted dict fix — `_elem_types[gname]`
for a global list literal, shipped in commit `fd29316` specifically to
fix `Lib/importlib/_bootstrap_external.py`'s `path_sep =
path_separators[0]` — is written to the EXACT SAME dict, reset by the
EXACT SAME `_reset_func()` call, at the EXACT SAME point in the EXACT
SAME per-function compile sequence. A hand-written repro mirroring that
fix's own motivating shape (global list, read via `container[0]` inside
a function OTHER than `_toplevel`) shows the identical failure: the
reading function's own return type is inferred `int64_t` (not `char
*`), and its body calls `mojo_list_get_int` (not `mojo_list_get_str`).
That fix evidently still closed the ORIGINAL reported error for
`_bootstrap_external.py` (confirmed by this session's own quality-gate
runs at the time) — almost certainly because that file's real trigger
shape differs in some detail from my hand-reduced repro (worth
re-examining, not done here — out of scope for this write-up), not
because the general mechanism actually works. This write-up doesn't
claim `fd29316` should be reverted (it measurably fixed a real error,
gate-verified); it claims the underlying mechanism it relies on is less
robust than its own commit message suggests, and a large class of
similar-looking global-container-read cases likely still silently
default to the wrong C type today.

## Minimal repro

```python
# dict case
TEST_SLICES = {"iOS": "ios-arm64_x86_64-simulator"}

def helper():
    base = "/tmp/xcframework"
    full = base / TEST_SLICES["iOS"]   # Path.__truediv__, `/` overload
    print(full)

helper()
```
```
error: invalid operands to binary / (have 'char *' and 'int64_t') [-Wint-conversion-adjacent]
```
(exact GCC wording varies) — because `TEST_SLICES["iOS"]` inside
`helper()`'s body resolves to `int64_t` (the `_dict_val_of` default),
not `char *`, so the `/` operator's `op == '/' and rt == 'char *'`
path-join dispatch (`gimple_codegen.py:9157`) never fires and the
generic arithmetic fallback emits a bare (invalid) `char * / int64_t`.

```python
# list case (mirrors the ALREADY-SHIPPED fd29316 fix's own motivating shape)
path_separators = ["/", "\\"]

def get_sep():
    return path_separators[0]

def main():
    print(get_sep())

main()
```
Compiles (no GCC error — bit-pattern happens to round-trip), but
`get_sep`'s declared C return type is wrongly `int64_t`, and its body
calls `mojo_list_get_int` where it should call `mojo_list_get_str` —
confirmed via direct inspection of the generated C, not just an error
count. A real value bug, not (in this instance) a compile failure.

## Real-world instance

`Apple/testbed/__main__.py:176`: `test_framework_path =
xc_framework_path / TEST_SLICES[platform]`, where `TEST_SLICES =
{"iOS": "ios-arm64_x86_64-simulator"}` is a module-level dict literal
and the read happens inside a function (not `_toplevel`). Also lines
135 and 400 (`... / TEST_SLICES[platform] / ...` / `...
TEST_SLICES[context.platform]`), same root cause, each a separate GCC
error in the full build.

## What a real fix needs

1. Distinguish "global-name key" entries from "temp-name key" entries
   in `_elem_types`/`_dict_val_types` (and audit whether any of the
   OTHER tables `_reset_func` clears — `_actual_types`,
   `_bound_method_ret_types`, `_nested_elem_types` — have the same
   global-vs-temp key confusion; not checked here, likely similarly
   affected given they're reset alongside the same two tables for the
   same stated reason).
2. Introduce a genuinely persistent (never reset by `_reset_func`)
   home for Phase 1.7's global-scope inferences — e.g.
   `self._global_elem_types`/`self._global_dict_val_types`, populated
   once by Phase 1.7 and consulted by `_lower_IdentExpr`'s global-read
   branch INSTEAD of (or in addition to, with the global table taking
   priority) the per-function-scoped `_elem_types`/`_dict_val_types`.
   `_reset_func` itself should not need to change at all under this
   design — the fix is entirely in adding the persistent table and
   updating the ~2 read sites in `_lower_IdentExpr`, not in touching
   the reset routine.
3. Re-verify `fd29316`'s own motivating file
   (`Lib/importlib/_bootstrap_external.py`) still compiles clean
   afterward, AND add a real value-correctness test (not just a
   compile-success test) for both the list and dict shapes — this
   whole bug class is invisible to `compile_stdlib.py`'s "compiles and
   links" bar, exactly like `bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_int64.md`.
4. Full quality gate (this touches `_lower_IdentExpr`, a function
   called from virtually every expression in every module this
   compiler processes — the single highest-traffic function in the
   whole codegen, per its own docstring elsewhere in this file).

## Risk

High. `_lower_IdentExpr`'s global-variable branch is used by
EVERY read of EVERY module-level global, in every function, in every
file this compiler compiles — this is about as hot and broadly-shared a
code path as exists in `gimple_codegen.py`. It is also, confirmed by
the `get_sep` repro above, entangled with RETURN-TYPE inference (one of
the three machinery classes this session's CLAUDE.md explicitly flags
as high-risk / two-real-regressions-already territory). Do not attempt
without a dedicated session: implement step 2 alone first, re-run the
FULL 5-step quality gate, and only then consider whether steps 1/3 are
still needed.
