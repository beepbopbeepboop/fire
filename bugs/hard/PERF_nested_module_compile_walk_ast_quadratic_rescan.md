# HARD BUG (performance): `_walk_ast` re-scan blowup for large transitive-import graphs

## Status

Root cause CONFIRMED (2026-08-06, exact lines identified — not just inferred
from profile shape as before). Concrete phased fix plan below.

**Phase 1 implemented and verified 2026-08-07** (see "Phase 1 implementation
notes" below).

**Phase 2 implemented and verified 2026-08-07** (see "Phase 2 implementation
notes" below) — for `_scan_body_for_local_field_access` specifically, the
single biggest line in the original profile. This is a REAL, measured
wall-clock win: `Lib/contextlib.py` (the doc's own worst-case profiling
target) dropped from 44.2s (Phase 1 alone) to 10.9s; `Lib/socket.py` went
from >120s (did not complete within a 2-minute cap — a confirmed timeout
under any 60-90s harness budget) to 61.4s and now actually SUCCEEDS
(previously never observed to finish). The other ~13 `imported_stmts`
consumers listed in the original Phase 2 plan are NOT yet memoized —
extending the same treatment to them, one at a time with independent
verification, remains a valid follow-up if more perf headroom is needed
(`socket.py`'s 61.4s is a big improvement but still not fast).

### Phase 1 implementation notes

Implemented exactly as planned: a new pair of shared-by-reference
containers (`self._all_transitive_stmts_ordered: list`,
`self._all_transitive_stmts_ids: set`, declared next to
`self._module_stmts` in `__init__`, shared into every nested `temp_gen`
the same way `_module_stmts` is) is incrementally appended to, once per
statement ever, right where `_compile_imported_module` sets
`self._module_stmts[module_name] = stmts` on a successful compile. The
O(current total tree size) reconciliation loop in `gen_module`'s
`do_imports=True` Phase 0 (previously `for mod_name, mod_stmts in
self._module_stmts.items(): for s in mod_stmts: ...`) now does a single
incremental pass over the pre-flattened `_all_transitive_stmts_ordered`
list instead, with the same id-based dedup against the current level's
own `imported_stmts` as before. Because the flat list is built by
appending each module's stmts in the exact same per-module order
`_module_stmts.items()` iteration would visit them (dict insertion
order), the final `imported_stmts` content and order at every level is
byte-identical to before — a pure complexity improvement, not a
behavior change. Confirmed via the full 5-part quality gate (below);
`compile_stdlib.py -j8` in particular would have caught any change in
`imported_stmts` content (it affects codegen output, which several of
that suite's 664 files depend on being stable) and reports the identical
664/664, 0-unexpected result as baseline.

**Honest empirical finding on wall-clock impact**: a direct, uninstrumented
timing comparison (`time.time()` around `gc.compile_to_gimple(src,
do_imports=True, ...)`, `git stash` on `gimple_codegen.py` alone for the
"before" run) on `Lib/contextlib.py` — the doc's own original profiling
target — showed **no measurable difference**: ~44-45s both before and
after Phase 1 alone (this run ultimately fails with an unrelated
`async def`/coroutine-codegen "cannot compile" error after Phase 0
completes, same failure point before and after, so the comparison is
apples-to-apples). This is consistent with the plan's own prediction
("Phase 1 alone should measurably cut wall time, though NOT fix the
fundamental O(N²) `_walk_ast` total from Phase 2") in direction, but the
magnitude on this specific file is smaller than "measurably cut" implied
— Phase 2's per-statement memoization (still unimplemented) is where the
doc's own profile says the actual `_walk_ast` call-count reduction (and
therefore most of the wall-clock win) has to come from; Phase 1 alone
only removes the redundant dict-to-list re-flattening step feeding into
those scans, not the scans' own O(N²) repeated-visit cost. Landed anyway
because it's a genuine, verified, zero-risk complexity improvement and a
correctness-preserving prerequisite for Phase 2 (Phase 2's plan
explicitly builds on `imported_stmts` having stable, well-understood
provenance) — just not, on its own, sufficient to close out this bug or
unblock the timeout-affected files (`Lib/poplib.py` was independently
confirmed fast regardless, ~7s wall time — see below; `contextlib.py`
itself was NOT observed to complete within a 60-90s budget before this
change either, so no file's pass/fail status against a timeout harness
changes as a result of Phase 1 alone).

`Lib/poplib.py` (one of the doc's other named affected files) was
re-checked directly: `python3 mojo.py build Lib/poplib.py` completes in
~7s wall time (well within any reasonable timeout) — either it was never
as badly affected as `contextlib.py`'s 36-module worst case, or an
unrelated prior fix already improved it; not otherwise investigated
further here.

### Quality gate (2026-08-07, Phase 1)

1. `python3 test_gimple.py` — 247 passed, 0 failed.
2. `python3 test_module_cache.py` — 76 passed, 0 failed.
3. `make check-selfhost` — clean.
4. From-scratch stdlib dylib rebuild — clean, 0 `skip <module>:` lines.
5. `python3 compile_stdlib.py -j8` — 664/664 passed, 0 unexpected
   failures (unchanged from baseline).

### Phase 2 implementation notes

Implemented for exactly one consumer, `_scan_body_for_local_field_access`
(gen_module's 4th struct-field completeness pass, the single biggest line
in the original profile) — per the doc's own "one consumer at a time"
guidance, the other ~13 `imported_stmts` consumers are untouched.

The function used to call `_walk_ast(body)` twice per invocation (once to
build a `name -> struct` `local_types` map from `VarDecl`/constructor-call
sites, once to resolve `MemberExpr` field accesses against it), with
`body` (`imported_stmts` in particular) growing to O(total transitive tree
size) at every one of the N nesting levels — O(N^2) total node visits,
exactly the profile's dominant cost.

Since `_walk_ast(list_of_stmts)` is exactly the concatenation of
`_walk_ast([s])` for each top-level statement `s` in the list (confirmed
by reading `_walk_ast`'s own definition — no cross-statement state), the
expensive per-node subtree walk of each INDIVIDUAL top-level statement can
be memoized by `id(stmt)` and reused verbatim across every later call that
also includes that same statement object, tree-wide — a new
`self._field_scan_var_cache`/`self._field_scan_member_cache` pair, shared
by reference into every `temp_gen` exactly like `_all_transitive_stmts_
ordered` (same sharing block in `_compile_imported_module`).

**The subtlety that made this non-trivial** (why a naive "skip already-
visited nodes" memoization is NOT safe here, contrary to what the
Phase-2-plan text's literal wording might suggest): three of the original
filters applied while building `local_types` are NOT pure functions of the
statement's own AST content — they're time-/call-dependent:
- `ann in self.struct_field_types` — `struct_field_types` grows
  monotonically as unrelated structs are discovered elsewhere during
  compilation, so whether a given candidate type name counts as "a known
  struct" can flip from false to true AFTER a statement was first visited.
- `ann not in self._selfhost_hardcoded_struct_names` — a per-`gen_module`
  -call snapshot (`frozenset(self.struct_field_types.keys())` taken at a
  fixed point in that call), so it can differ across different calls/
  instances even for the exact same statement.
- `ann != own_struct_name` — an explicit per-call parameter (always `None`
  at both of this function's current call sites, but not guaranteed to
  stay that way).

Caching the FILTERED result at first-visit time would silently and
PERMANENTLY miss any candidate whose governing struct becomes known only
on a later call — a real correctness regression, not just a missed
optimization. The actual fix: the cache stores only the raw SYNTACTIC
candidates (name/type-name pairs matching the `VarDecl`-with-annotation or
`x = Ctor(...)` shape, and `MemberExpr`-with-`IdentExpr`-obj sites minus
dunder members, which have no time-dependent filter and are safe to
prefilter into the cache) — the three time-dependent filters above are
still re-applied fresh, in full, on EVERY call, against the cached
candidate list. This is a cheap plain-list iteration (no `_walk_ast`), and
reproduces the original per-call semantics exactly: it's precisely a
memoization of the expensive AST traversal, not a memoization of the
filtered result.

Also considered and rejected: making `local_types` itself a persistent,
ever-growing shared dict (rather than freshly rebuilt from the current
`body` on every call) to let the FIRST loop skip already-visited `VarDecl`
nodes outright. Analysis showed this changes behavior in a real (if
obscure) scenario: two co-incidentally-same-named local variables in
UNRELATED statements from DIFFERENT modules, where the type-establishing
one is compiled later than the accessing one — the current (both-before-
and-after-this-fix) per-call-fresh-rebuild semantics guarantee eventual
resolution once both are jointly present in some call's body (which the
OUTERMOST/last call's `imported_stmts`, being the union of literally
everything compiled anywhere in the tree, always achieves); a globally-
persistent `local_types` with node-level skip does not have the same
guarantee at INTERMEDIATE levels and could resolve a field earlier than
before, changing that intermediate level's own generated code. Rejected
in favor of the safer, provably-behavior-identical per-statement
candidate-list caching described above.

### Validation (2026-08-07, Phase 2)

Direct `gimple_codegen.compile_to_gimple(src, do_imports=True, ...)`
wall-clock timing (no profiler overhead), `git stash` on `gimple_codegen.py`
alone for the "before" (Phase-1-only) run, same machine, same process:

| file | before (Phase 1 only) | after (Phase 2) |
|---|---|---|
| `Lib/contextlib.py` | 44.23s (fails at the same unrelated async/coroutine-codegen point both before and after — apples to apples) | 10.90s (same failure point) |
| `Lib/socket.py` | did not complete within a 2-minute cap (>120s — a confirmed timeout under any 60-90s harness budget) | 61.37s, **succeeds** (9.86 MB of generated C) |

A `cProfile` run of the `contextlib.py` case after the fix shows
`_scan_body_for_local_field_access`'s own cumulative time dropping from
8.014s (35 calls, pre-fix baseline profile in the "Symptom" section above)
to 2.486s (78 calls, post-fix) — consistent with the wall-clock win.

Full 5-part quality gate, unchanged from Phase 1's baseline:
1. `python3 test_gimple.py` — 247 passed, 0 failed.
2. `python3 test_module_cache.py` — 76 passed, 0 failed.
3. `make check-selfhost` — clean.
4. From-scratch stdlib dylib rebuild — clean, 0 `skip <module>:` lines.
5. `python3 compile_stdlib.py -j8` — 664/664 passed, 0 unexpected
   failures (unchanged from baseline).

### Remaining work (not attempted)

The other ~13 `imported_stmts` consumers in `gen_module` (`all_struct_
defs`, `all_functions`, `all_structs_for_methods`, `all_scan`, `all_
global_scan`, the method-dispatch scan, the mods scan, etc.) are still
full `_walk_ast(imported_stmts)` passes, still O(N^2) tree-wide in
principle — `socket.py`'s 61.4s (down from a >120s timeout, but still slow)
is consistent with real remaining cost there. Each would need the same
per-consumer classification (side-effect-free/shared-state-only vs.
emits-per-visit-once, per the original plan's "Risk" section) before
applying the same candidate-cache pattern — genuinely one-at-a-time,
independently-verified work, not attempted here for time-budget reasons
now that the single biggest offender is fixed.

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
