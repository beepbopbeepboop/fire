# HARD BUG (performance): `_walk_ast` re-scan blowup for large transitive-import graphs

## Status

Root cause CONFIRMED (2026-08-06, exact lines identified — not just inferred
from profile shape as before). Concrete phased fix plan below. Not yet
implemented — this is a real architectural change touching ~15 call sites
with genuine ordering-sensitivity risk, deliberately not attempted in the
same pass as the planning.

## Symptom

`python3 mojo.py build <file>.py` (`do_imports=True`) takes minutes (or
times out entirely against the 60-90s harness timeout) for any file whose
transitive import graph is moderately large, even though the file itself
is small and the actual GIMPLE/C++ codegen for it is fast in isolation.

Confirmed via `Lib/contextlib.py` (imports `abc`, `collections`,
`functools`, `os`, `sys`, `types`, `warnings`, ...) — `cProfile`:

```
86320467 function calls (80837078 primitive calls) in 19.968 seconds
[after a 20s SIGALRM interrupt, build had not completed]

ncalls    tottime  cumtime  filename:lineno(function)
1         0.000    19.966   gimple_codegen.py:31258(compile_to_gimple_with_cpp)
36/1      0.843    19.906   gimple_codegen.py:24713(gen_module)
64/3      0.006    19.881   gimple_codegen.py:4127(_compile_imported_module)
4473166/6376  3.816   8.858  gimple_codegen.py:2037(_walk_ast)
35        0.527     8.014   gimple_codegen.py:26255(_scan_body_for_local_field_access)
```

`_walk_ast` called **4.47 million times** for just 36 nested `gen_module`
invocations (one per transitively-imported module).

## Root cause (CONFIRMED — exact mechanism)

`gen_module`'s Phase 0 (`do_imports=True` branch, ~gimple_codegen.py:25490-
25498):

```python
# Also collect stmts from transitively compiled modules (compiled by sub-temp-gens).
# These may not be in imported_stmts if a sub-gen compiled them first (e.g. mojo_compiler
# compiled via gimple_codegen before the outer gen could compile it directly).
already_in_stmts = set(id(s) for s in imported_stmts)
for mod_name, mod_stmts in self._module_stmts.items():
    for s in mod_stmts:
        if id(s) not in already_in_stmts:
            imported_stmts.append(s)
            already_in_stmts.add(id(s))
```

`self._module_stmts` (gimple_codegen.py:3703) is a single dict, created
once at the OUTERMOST `GimpleGen.__init__`, and shared BY REFERENCE into
every nested `temp_gen` created by `_compile_imported_module`
(`temp_gen._module_stmts = self._module_stmts`, line ~4311). Every module
anywhere in the transitive tree writes its own entry into this SAME dict
right after compiling (`self._module_stmts[module_name] = stmts`, line
~4329) — so by the time the k-th module (in compile order) runs its own
`gen_module`, `self._module_stmts` already contains all `k-1` previously
-compiled modules' stmts, cumulative across the WHOLE tree, not just this
module's own ancestors/direct imports.

The loop above runs at EVERY level of the recursion (it's inside
`gen_module`'s own `if self.do_imports:` block, and every `temp_gen` also
has `do_imports=True`) and unconditionally re-walks the ENTIRE
`self._module_stmts` dict — i.e. ALL modules compiled ANYWHERE in the tree
SO FAR — appending everything not already in this level's *local*
`imported_stmts` list. So `imported_stmts` at level k ends up sized
O(total modules compiled so far across the whole tree), not O(this
module's own direct imports).

`imported_stmts` is then walked by `_scan_body_for_local_field_access`
(twice, via `_walk_ast`) AND by ~13 other consumers throughout the rest of
`gen_module` (`all_struct_defs`, `all_functions`,
`all_structs_for_methods`, `all_scan`, `all_global_scan`, the method-
dispatch scan, the mods scan, etc. — grep `imported_stmts` in
gimple_codegen.py for the full list). Every one of those is effectively
O(current cumulative tree size) at EVERY level. Summed over N levels for a
roughly-linear-chain-shaped import graph, total work is O(1+2+...+N) =
O(N²) — for N=36 this alone is a ~36x multiplier over a single linear
pass, consistent with the observed 4.47M-call blowup (an average module's
own `_walk_ast` node count times a superlinear multiplier, not a flat
per-module constant).

Confirmed NOT a duplicate-recompilation issue: `self._compiled_modules`
(also shared by reference) correctly prevents any module from being fully
recompiled (`_compile_imported_module` → `temp_gen.gen_module(stmts)`)
more than once anywhere in the tree — the profile's "36/1 gen_module
calls" for a 36-module graph confirms this. The blowup is ENTIRELY in how
much each of those 36 calls re-scans on the way through, not in how many
times a module's own compile happens.

## Why the reconciliation loop exists (legitimate purpose, not a mistake)

Its own comment explains it: if a SUB-temp-gen (deeper in the tree) is the
one that first triggers compiling some module Z (because Z is imported by
a deep dependency before it's imported by a shallower one), Z's stmts
never got appended to the SHALLOWER ancestors' own local `imported_stmts`
lists via the normal Phase 0 loop (which only walks THIS level's own
direct `FromImportStmt`/`ImportStmt` targets) — so this reconciliation
step is the only thing that gives ancestor levels visibility into
struct/function definitions from modules compiled solely as a side effect
of a deeper import. That visibility is genuinely needed: `_scan_body_for_
local_field_access` and friends use `imported_stmts` to resolve struct
field types and symbols an ancestor module's OWN code may reference,
regardless of which exact tree level first compiled the defining module.
So this can't just be deleted or restricted to the root level without a
real correctness risk (an ancestor's own struct-field-type inference could
go blind to a struct only "discovered" via a deep sibling import).

## What a real fix needs (phased, in increasing order of risk)

### Phase 1 — cheap, safe, no behavior change: stop re-deriving the delta by rescanning the whole dict every time

Replace the O(current total tree size) reconciliation loop (25490-25498)
with an incrementally-maintained flat structure shared the same way
`_module_stmts` already is:

- Add `self._all_transitive_stmts_ordered: list` and
  `self._all_transitive_stmts_ids: set[int]` next to `self._module_stmts`
  in `__init__` (gimple_codegen.py:3703), both shared by reference into
  every `temp_gen` exactly like `_module_stmts` already is.
- In `_compile_imported_module`, right where `self._module_stmts[module_name]
  = stmts` is set (line ~4329), ALSO do:
  ```python
  for s in stmts:
      sid = id(s)
      if sid not in self._all_transitive_stmts_ids:
          self._all_transitive_stmts_ids.add(sid)
          self._all_transitive_stmts_ordered.append(s)
  ```
  (O(this module's own size), done once per module, ever — not once per
  ancestor level.)
- Replace the reconciliation loop at 25490-25498 with a single pass that
  only appends entries from `self._all_transitive_stmts_ordered` not
  already in THIS level's local `imported_stmts`, using the existing
  `already_in_stmts` id-set — i.e. keep the existing per-level dedup
  logic, just iterate the pre-flattened list instead of re-flattening
  `self._module_stmts.items()` from scratch every time.

This produces the IDENTICAL final `imported_stmts` content at every level
(so zero behavior change, safe to verify via `compile_stdlib.py -j8`
producing an unchanged 664/664 pass count with byte-identical output) —
it only removes the redundant O(N) dict-flattening work that currently
happens at every one of the N levels. Given the profile shows the
reconciliation loop itself (dict iteration + membership checks) directly
precedes and feeds the expensive `_scan_body_for_local_field_access`
calls, this phase alone should measurably cut wall time, though NOT fix
the fundamental O(N²) `_walk_ast` total from Phase 2 below.

### Phase 2 — the real fix for the `_walk_ast` count: memoize per-statement scan work, not just the list construction

Even with Phase 1, `imported_stmts` itself still legitimately grows to
O(total tree size) at each of N levels (that visibility requirement is
real, per the section above) — so `_scan_body_for_local_field_access` and
its ~13 siblings are still each O(current tree size) per level, O(N²)
total, UNLESS the scanners themselves stop re-walking statements they (or
an earlier ancestor level) already fully processed.

Concretely, for `_scan_body_for_local_field_access` specifically (the
single biggest line in the profile): add a shared (by-reference, like
`_compiled_modules`) `self._field_access_scanned_ids: set[int]` set.
Change its first `_walk_ast(body)` loop to skip any node whose `id()` is
already in that set (and add each node's id once visited). Because this
scanner's only effect is mutating the SHARED `self.struct_field_types`
dict in place (never level-local state), a statement already scanned by
ANY ancestor level has already contributed everything it's going to
contribute — re-visiting it a second time from a shallower level is pure
waste, not a correctness requirement. The same treatment should be
applied, one at a time and independently verified, to the other
`imported_stmts` consumers that are provably idempotent/shared-state-only
(most of the ones building `all_*` lists purely for further `isinstance`-
filtered iteration are naturally idempotent; a few — anything that
APPENDS to a list once per visit, e.g. struct/function forward-declaration
emission — need care, since skipping a "already seen" statement there
must still guarantee it was emitted exactly once by WHICHEVER level first
processed it, not zero times).

### Validation

1. Re-profile `contextlib.py` (or an equivalent large-import-graph file)
   after each phase; `_walk_ast` call count should drop from ~4.47M
   towards roughly linear in total transitive source size (a few hundred
   thousand, not millions, for a 36-module graph).
2. `compile_stdlib.py -j8`: 664/664 unchanged, and ideally noticeably
   faster (many stdlib files have moderately deep import graphs even if
   none individually hit contextlib.py's ~36-module extreme).
3. Full quality gate (test_gimple.py, test_module_cache.py, make
   check-selfhost, from-scratch dylib rebuild) — this touches shared,
   heavily-relied-on Phase 0 machinery, so all four must stay green, not
   just compile_stdlib.py.
4. Re-check the specific files this bug is documented as affecting
   (`Lib/contextlib.py`, `Lib/poplib.py`, `Lib/runpy.py`, `Lib/socket.py`,
   and the `Doc/`/`Apple/testbed` ones) — confirm they now complete well
   within the harness's 60-90s timeout.

### Risk / why Phase 2 is real, not "quick"

Import/compile order is currently load-bearing for at least two other
documented behaviors (same-file overload resolution, cross-module symbol
qualification — see `_imported_struct_home`/`_imported_func_home`'s own
docstrings in `_compile_imported_module`). A memoization scheme that skips
re-visiting a statement must not accidentally skip an EMISSION (as opposed
to a pure dict-mutation) that only happens once per visit, or a function/
struct forward declaration could go missing at a level that actually
needed it emitted into ITS OWN local output. Each of the ~13 `imported_
stmts` consumers needs to be individually classified (side-effect-free
scan vs. emits-per-visit) before Phase 2 touches it — start with `_scan_
body_for_local_field_access` alone (confirmed side-effect-free / shared-
dict-only above), verify thoroughly, then extend one consumer at a time
rather than applying the same pattern to all ~13 in one change.
