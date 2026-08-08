# HARD BUG: `_reset_func()` wipes global-scope container element/value-type inference before ANY function body can read it — including the already-shipped fix it silently undermines

## Status (FIXED 2026-08-08)

Fixed directly (not delegated to a background agent, per this task's own
"dedicated session" guidance) as part of a broader pass through this
session's previously-held-back architectural bugs. Implemented the exact
design this doc's own "What a real fix needs" section proposed (a
persistent, never-`_reset_func`-cleared home for Phase 1.7's global
inferences), but discovered — via direct testing, not assumed safe — a
real, additional shadowing hazard the original design didn't anticipate,
described in full below.

### The fix

1. Two new instance attributes, initialized once in `__init__`
   (mirroring the existing `_field_elem_types`/`_field_dict_val_types`
   pattern, which is explicitly "intentionally NOT reset" for the
   identical reason): `self._global_elem_types: dict[str, str] = {}`
   and `self._global_dict_val_types: dict[str, str] = {}`.
2. `_phase17_infer_global_type` (Phase 1.7) now also writes into these
   persistent tables. Also added the previously entirely-missing
   dict-VALUE-type case (only list/tuple element-type capture existed
   before — a global dict literal's value type had no Phase 1.7
   tracking at all).
3. `_reset_func` seeds the per-function `_elem_types`/`_dict_val_types`
   from these persistent tables instead of starting empty. This means
   **zero of the ~80 existing consumer call sites needed to change** —
   they still just do `self._elem_types.get(name)` exactly as before;
   only what the table starts as changed.

### The shadowing hazard (found via testing, not in the original plan)

The straightforward version of step 3 above — seed `_elem_types`
unconditionally from `_global_elem_types` — causes a **real, confirmed
segfault**: a local variable or parameter that happens to share a
global container's bare name (e.g. a function-local `path_separators =
[42, 43]` shadowing the module-level `path_separators: list[str]`)
inherited the GLOBAL's seeded element type for its own static
return-type inference. That inference is a syntactic pre-pass that runs
BEFORE the function's own body is generated statement-by-statement, so
it has no notion of "this name gets locally reassigned partway
through" — only "is there currently an entry in the table for this
bare name." The actual body-generation write sites (e.g.
`_gen_stmt_AssignStmt`) DO correctly overwrite `_elem_types` once
reached, but the early pre-pass reads the (wrong, global-seeded) value
first, producing a function whose C return type disagrees with what
its body actually computes — confirmed via direct `.ci` inspection: a
function declared to return `char *` while its body actually returns
an `int64_t` cast through a pointer, a hard type-confusion bug that
segfaults at runtime.

**Fixed** by adding `_locally_bound_names(body, params)` — a helper
that mirrors real Python's own scoping rule (any assignment target, or
parameter, anywhere in a function makes that name local for the WHOLE
function, unless `global NAME` is declared) — walking `AssignStmt`,
`MultiAssignStmt`, `AugAssignStmt`, `VarDecl`, `ForStmt` targets,
`WithStmt` `as` targets, and every parameter name (recursing through
`IfStmt`/`WhileStmt`/`ForStmt`/`TryStmt`/`WithStmt` bodies, but NOT
into nested `FunctionDef`/`LambdaExpr` — their own separate scope).
`_reset_func` now excludes any name in this set from the global-table
seed entirely, so a shadowing local/parameter starts with NO entry
(exactly like today's pre-fix behavior for that one name), while every
genuinely-global name still gets seeded correctly. All 5 `_reset_func`
call sites (`gen_func`, `_gen_lifted_closure`, `_gen_struct_method`,
`_gen_toplevel`, and the harmless `__init__`-time first call before
Phase 1.7 has even run) were updated to pass their own body/params.

### Verification

- The two original minimal repros (global list `path_separators =
  ["/", "\\"]` read via `path_separators[0]` inside a non-toplevel
  function; global dict `TEST_SLICES` read via subscript inside a
  non-toplevel function) — both now compile AND **run**, printing the
  real value (`"/"`, `"ios-arm64_x86_64-simulator"`), not a raw pointer
  bit pattern as a decimal integer.
- Three shadowing repros (local reassignment, function parameter, and a
  normal same-function global read, all sharing one bare name) — all
  three now produce correct values (`42`, `99`, `"/"`) with zero
  crashes. The parameter-shadowing and local-shadowing cases both
  SEGFAULTED before the `_locally_bound_names` guard was added (real
  regressions caught by testing, not theoretical).
- `Lib/importlib/_bootstrap_external.py` (the original `fd29316` fix's
  motivating file): unaffected, its one remaining error is the
  already-documented, unrelated `_write_atomic` implicit-declaration
  gap.
- `Apple/testbed/__main__.py` (this doc's own real-world instance): all
  three originally-documented `TEST_SLICES[platform]`/
  `TEST_SLICES[context.platform]` errors (lines 135, 176, 400) are
  gone. One unrelated, separate error remains at line 225 (`source /
  ... / test_framework_path.readlink()`, a `char* / int` path-join
  issue with nothing to do with global container inference) — out of
  scope for this fix.
- Corpus spot-check: `json/__init__.py`, `enum.py`, `argparse.py`,
  `os.py`, `Lib/collections/__init__.py` all build with 0 errors;
  `typing.py`'s large pre-existing error cluster (675) is unaffected.
- `test_gimple_runner.py` (compiled-AND-RUN suite): 17/18 passing,
  1 pre-existing failure confirmed identical on unmodified master via
  `git stash` (not a regression).
- Full 5-part mandated gate: `test_gimple.py` 247/247,
  `test_module_cache.py` 76/76, `make check-selfhost` clean,
  from-scratch stdlib dylib rebuild 0 skips, `compile_stdlib.py -j8`
  664/664 0 unexpected (unchanged from baseline).

## Original status (2026-08-06, historical)

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
