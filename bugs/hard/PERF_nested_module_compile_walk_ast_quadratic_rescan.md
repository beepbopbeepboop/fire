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

**Phase 3 implemented and verified 2026-08-18** (see "Phase 3 implementation
notes" below) — for `_infer_param_types` (gen_module's Pass 1.3 unannotated-
parameter type inference, one of the ~13 previously-unmemoized `imported_
stmts`/`all_functions`/`all_structs_for_methods` consumers), identified as
the largest remaining SAFE target by a fresh profile of current `master`
(668 commits ahead of the Phase 2 state — the profile shape had shifted
noticeably; see "Remaining work" below for the full updated ranking,
including two costlier-but-riskier consumers that were considered and
deliberately NOT touched this round).

**Phase 4 implemented and verified 2026-08-23** (see "Phase 4
implementation notes" below) — two consumers, chosen by a FRESH cProfile
of the current tree (the shape had shifted again since 08-18): (a) Pass
2c's `_infer_return_elem_type`, whose PER-CALL seeding from the whole
tree-shared `func_return_types` dict had become the single dominant cost
(74.0s cumtime of a 129.3s profiled run, ~500M interpreted
`dict.setdefault` calls) — fixed by hoisting one snapshot per Pass-2c
run, exactly the "quadratic rescan" pattern this doc exists to kill; and
(b) `_calls_in_stmts`, memoized per top-level statement like Phase 2
(its four gen_module consumer sites include a fixpoint loop that
re-collected every caller body 4x per level). Behavior-identity is
proven by BYTE-IDENTICAL generated C on the largest succeeding
whole-program case (`Lib/socket.py`, 20,168,554 bytes, `cmp` clean).

### Phase 4 implementation notes (2026-08-23)

A fresh baseline `cProfile` of `Lib/contextlib.py` on the then-current
tree (post-Phases-1..3) re-ranked the remaining consumers — the old
ranking was stale:

| rank | function | cumtime | ncalls | note |
|---|---|---|---|---|
| 1 | `_infer_return_elem_type` | 74.04s | 275,262 | Pass 2c fixpoint — its own frame + 32.05s / 501.9M `dict.setdefault` child calls = the per-call re-seeding |
| 2 | `_dedup_variadic_externs` | 6.09s | 38 | C-text post-processing, out of scope (unchanged from 08-18) |
| 3 | `_class_attr_ctype` caller loop | 4.80s | 11.76M | still entangled with time-dependent `struct_field_types` state (line 926's `cur is None or cur in ('int','int64_t')` branch can flip between levels); NOT touched, same reasoning as 08-18 |
| 4 | `_collect_self_assigns` | 4.92s | 29,471 | still mutates struct ASTs; NOT touched |
| 5 | `_calls_in_stmts` | 3.13s | 201,928/34,408 primitive | **chosen target (b)** |

**(a) Pass 2c seeding hoist.** Reading `_infer_return_elem_type`
(gimple_gen_resolve.py) showed where the 500M setdefaults live: every
call builds its hermetic scratch `var_types` from scratch by iterating
the ENTIRE tree-shared `func_return_types` dict one `setdefault` at a
time — O(|func_return_types|) interpreted work × 275k calls (once per
function per Pass-2c iteration per nesting level), i.e. precisely this
doc's O(N²)-in-tree-size rescan shape, relocated by the earlier phases
into the seeding step. The fix exploits a provable invariant rather
than adding a cache: NOTHING reachable from within one Pass-2c run can
mutate `func_return_types` during that run (the loop body only scans
bodies via this function and writes only `self._return_elem_types`; the
two `func_return_types[...] = ...` write sites in gimple_gen_resolve.py
live in `_register_link_imports`/`_register_reflected_struct`, which are
unreachable from the scan). So `gen_module`'s Pass 2c now takes ONE
`dict(self.func_return_types)` snapshot before the fixpoint loop and
passes it to every call as a new optional `_base_var_types` kwarg; the
function copies that snapshot at C speed (`dict(base)`) instead of
re-seeding entry-by-entry. Seeding PRECEDENCE is preserved exactly
(params > func_return_types > `KNOWN_LEAF_RETS`: params were assigned
before the frt setdefault loop and still win by being assigned after
the copy; KLR still loses to both via setdefault). Callers without the
kwarg keep the byte-for-byte legacy path. No var_types iteration-order
dependence exists downstream (verified by grep: only key lookups).

**(b) `_calls_in_stmts` per-statement memoization.** Same pattern as
Phase 2, new shared-by-reference `self._calls_in_stmts_cache` dict
(declared next to the Phase 2/3 caches in `__init__`, shared into every
temp_gen in `_compile_imported_module`'s sharing block). Safe to cache
the WHOLE per-statement contribution (not just syntactic candidates)
because, unlike Phases 2/3, there is NO time-dependent filter here at
all: the traversal is a pure function of each statement's subtree
(`_collect_calls` reads no mutable gen state — its only gen call,
`_fstring_sub_exprs`, re-parses the StringLiteral's own text), and all
four gen_module consumer sites only READ the collected nodes
(isinstance/`.func.name`/`.args` inspection — no mutation, no identity
comparison). Mutation safety was checked explicitly: the only passes
that rewrite bodies AFTER these scans run (`_inline_single_use_task_
composition`/`_normalize_await_kwargs`) either replace statements with
fresh objects (new ids → natural cache miss) or mutate exclusively
inside AwaitExpr subtrees, which `_collect_calls` never descends into
(it has no AwaitExpr case) — so no stale entry is observable. The
per-statement walk itself (`_collect_calls_in_stmt`) reproduces the old
loop body verbatim (same attribute order, recursion still through the
memoized entry point so nested lists are cached too).

### Validation (2026-08-23, Phase 4)

Direct (non-profiled) wall-clock timing of
`gimple_codegen.compile_to_gimple(src, do_imports=True, ...)`,
back-to-back runs, same machine (heavily contended by concurrent agent
builds throughout — reported as measured):

| file | before | after |
|---|---|---|
| `Lib/contextlib.py` (fails at the same documented async-codegen point both sides) | 38.65s / 38.63s / 39.08s | 19.21s / 18.98s / 18.75s |
| `Lib/socket.py` (SUCCEEDS) | 142.09s / 132.57s | 100.47s |

~2.1x on contextlib.py, ~1.3-1.4x on socket.py. Correctness anchor:
socket.py's GENERATED C IS BYTE-IDENTICAL before/after (`cmp` clean,
20,168,554 bytes both sides) — pure performance change, zero output
difference. cProfile diff, contextlib.py, same method as Phase 3:

| metric | before | after |
|---|---|---|
| total profiled time | 129.3s | 54.6s |
| `_infer_return_elem_type` cumtime | 74.04s | 5.55s (−93%) |
| `dict.setdefault` calls | 501.9M / 32.0s | gone from top-45 |
| `_calls_in_stmts` cumtime | 3.13s / 201,928 calls | gone from top-45 |
| total function calls | 939.3M | 420.2M |

Full quality gate (2026-08-23):
1. `python3 test_gimple.py` — 250 passed, 0 failed.
2. `python3 test_module_cache.py` — 76 passed, 0 failed.
3. `make check-selfhost` — clean (`✓ self-host compiles + links clean`).
4. From-scratch stdlib dylib rebuild — exit 0, 0 `skip <module>:` lines
   (baseline before the change also 0 — no increase).

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

### Phase 3 implementation notes (2026-08-18)

By this date `master` had advanced 668 commits past the Phase 2 state, so
the profile shape was re-derived from scratch (`cProfile` around
`gimple_codegen.compile_to_gimple(src, do_imports=True, ...)`, same two
worst-case files, current `master`) rather than assumed unchanged. Direct
children of `gen_module` in the fresh `contextlib.py` profile, ranked by
own cumulative time (`ps.stats[...]` callers-of-`gen_module` breakdown,
not just top-level `sort_stats('cumulative')`, since most of these passes
are inlined directly in `gen_module`'s own frame rather than behind one
wrapper function):

| rank | function | cumtime | ncalls | consumer / Pass |
|---|---|---|---|---|
| 1 | `_dedup_variadic_externs` | 7.76s | 38 | NOT an `imported_stmts` AST consumer — post-hoc string dedup of already-generated C text (`parts`), out of this bug's scope |
| 2 | `_class_attr_ctype` | 6.09s | 11.76M | Pass 1.1 (`all_struct_defs`, class-body container-attr typing) |
| 3 | `_collect_self_assigns` | 6.03s | 29471 | Pass 1.2 (`all_structs_for_methods`, struct-field-from-`__init__`-assignment inference) |
| 4 | (raw `isinstance` calls in `gen_module`'s own frame) | 5.95s | 115.4M | spread across the ~13 consumers' own `isinstance(s, StructDef)`/`isinstance(s, FunctionDef)` filters, not attributable to one |
| 5 | `_infer_param_types` | 5.18s | 40174 | **Pass 1.3 (`all_functions`/`all_structs_for_methods`, unannotated-parameter type inference) — chosen target** |
| 6 | `_calls_in_stmts` | 3.38s | 34408 | `self._calls_in_stmts(imported_stmts, _ctor_calls)` (ctor-call scan) |
| 7 | `_scan_body_for_local_field_access` | 3.27s | 78 | Phase 2's own target — already memoized; residual cost is the now-larger tree's cheap candidate-list re-filtering, not `_walk_ast` |

Rank 5, `_infer_param_types`, was chosen over the nominally-larger ranks 2
and 3 for safety reasons, following this doc's own "pick a different safe
consumer instead" guidance:

- **Rank 3 (`_collect_self_assigns`, Pass 1.2)** was checked first since
  it's the largest of the three close contenders. Rejected: it directly
  **mutates the struct AST itself** (`s.fields.append(VarDecl(...))`) as
  a side effect, and its own body reads `self.struct_field_types` (line
  `elif cn in self.struct_field_types:`) — the same time-dependent-filter
  trap as Phase 2, but *additionally* entangled with `param_types` (built
  per-call from `self._resolve_type(ptype)` and `self._ctor_lit_param_
  types[s.name]`, both themselves potentially call-order-dependent) and a
  genuine AST-mutation side effect rather than a pure dict-mutation. The
  mutation is idempotent today only because a separately-maintained
  `already = set(self.struct_field_types[s.name].keys())` snapshot guards
  it — correctly memoizing this consumer would require caching raw
  per-assignment syntactic shape (target field name + value-node kind)
  while re-deriving the type from three separate live pieces of state on
  every call, a materially more complex and higher-risk change than
  Phase 2's or Phase 3's split. Set aside as a candidate for a future,
  more carefully-scoped pass.
- **Rank 2 (`_class_attr_ctype`, Pass 1.1)** is a cheap, pure, non-
  recursive function of one AST node (`v`) — its own cost is genuinely
  just call-count amplification. Its caller loop was not ruled unsafe,
  but was not chosen this round because a closer read found it
  entangled with adjacent struct-inheritance-merge logic in the same
  `for s in all_struct_defs:` block (`_merge_struct_inheritance`,
  base-class field lookups reading `self.struct_field_types` a few lines
  above); isolating just the `_class_attr_ctype` sub-loop cleanly enough
  to memoize independently, without accidentally changing the adjacent
  inheritance-merge behavior it's interleaved with, needs its own
  dedicated pass rather than being folded into this one. Left for a
  future iteration.
- **Rank 5 (`_infer_param_types`, Pass 1.3, the chosen target)**: read in
  full. `analyze_param_usage(func.body, pname)` — the expensive part,
  a custom recursive `scan_nodes`/`scan_expr` walk of the whole function
  body — is a **pure function of `(func.body, pname)`**: grepping every
  line of `analyze_param_usage`/`scan_nodes`/`scan_expr`/`_track_
  derivation` for `self.` found zero references. Its result (`fields_
  accessed, function_calls, is_subscripted, is_string_method, is_
  iterated, is_char_compared`) is consumed by cheap decision logic
  *after* the scan that references exactly two `self.*` values:
  `self._KNOWN_SIGS` (a `dict` class attribute, confirmed via grep never
  assigned to anywhere — `_KNOWN_SIGS\[.*\] *=`/`.update`/`.pop`/
  `.setdefault` all return zero matches — genuinely invariant for the
  whole compilation) and `self.struct_field_types` (the same monotonically
  -growing, time-dependent state Phase 2 already had to work around).
  Same shape as Phase 2, one level removed: cache the raw scan result
  (pure), always re-run the `self.struct_field_types` match fresh.

Implementation: a new `self._param_usage_scan_cache: dict` (keyed by
`(id(func), pname)`), declared next to `_field_scan_var_cache`/
`_field_scan_member_cache` in `__init__` and shared by reference into
every `temp_gen` in the same sharing block in `_compile_imported_module`.
`_infer_param_types`'s per-parameter loop now checks this cache before
calling `analyze_param_usage`; the returned 6-tuple (read-only after
return, confirmed by inspection — no caller mutates any of its elements)
is cached verbatim on first computation and reused on every subsequent
call for the same `(func, pname)` anywhere in the tree. The final
type-inference decision logic (the `self.struct_field_types` lookup and
everything before it) is untouched and still runs fresh on every call.

### Validation (2026-08-18, Phase 3)

`cProfile` diff, `Lib/contextlib.py`, same machine, back-to-back runs
(before = current `master` via `git stash`, after = this fix popped back
in), profiler-overhead numbers (not representative of real wall time, but
directly comparable to each other and to the doc's own Phase 1/2 method):

| metric | before | after |
|---|---|---|
| `analyze_param_usage` calls | 76628 | 3504 (−95%) |
| `analyze_param_usage` cumtime | 3.784s | 0.211s |
| `_infer_param_types` cumtime | 6.533s | 2.512s (−62%) |
| `gen_module` cumtime (whole run) | 81.849s | 76.818s |
| total function calls (whole run) | 434.9M | 413.9M |

Direct (non-profiled) wall-clock timing on `Lib/contextlib.py`, 3 runs
each, before/after, same contended machine (the machine had substantial
unrelated background load throughout this session — `load average` ~6.6
on 18 cores, an unrelated `VoxelGame` process pegged at 100% CPU — so
run-to-run variance was large; reported honestly rather than cherry-picked):

| | run 1 | run 2 | run 3 |
|---|---|---|---|
| before | 20.04s | 23.94s | 19.91s |
| after | 17.36s | 19.00s | 22.35s |

Best-of-3 (least noise-affected): 19.91s → 17.36s, a real but modest
~13% wall-clock improvement — much smaller than Phase 2's dramatic win,
consistent with `_infer_param_types` being roughly 6-8% of `gen_module`'s
total cumulative cost per the profile table above (one of ~13 remaining
consumers, not the dominant one anymore — Phase 2 already fixed the
single dominant one). `Lib/socket.py` (the doc's other named worst case,
now large enough to actually complete and produce output): direct
before/after run produced **byte-identical generated C** (`diff` clean,
20223755 bytes both sides) — confirms this is a pure performance change
with zero output/behavior difference, exactly as required. Wall-clock on
`socket.py` itself (119.6s before, 127.5s after) was within this run's
noise band and not treated as a meaningful signal either way — the
`cProfile`-based, consumer-specific measurement above is the trustworthy
signal for this phase, same reasoning the doc's own Phase 1 section used
when its wall-clock delta on `contextlib.py` came back smaller than
expected.

Full 5-part quality gate (2026-08-18, current `master` + this fix,
default job counts — `compile_stdlib.py` run with NO `-j` override per
its own documented default of `os.cpu_count()`, not hardcoded to `-j8`):
1. `python3 test_gimple.py` — 248 passed, 0 failed.
2. `python3 test_module_cache.py` — 76 passed, 0 failed.
3. `make check-selfhost` — clean (`✓ self-host compiles + links clean`).
4. From-scratch stdlib dylib rebuild — clean, 0 `skip <module>:` lines,
   exit 0.
5. `python3 compile_stdlib.py` (default jobs) — 664/664 passed, 0
   unexpected failures (unchanged from baseline).

### Remaining work (not attempted)

Updated 2026-08-23 after Phase 4 (fresh profile in the Phase 4 notes
above). The single dominant consumer is now fixed; what remains, in
order:

- `_class_attr_ctype`'s Pass 1.1 caller loop (`all_struct_defs`,
  ~4.80s post-Phase-4) — still entangled with time-dependent
  `struct_field_types` state and adjacent inheritance-merge logic;
  unchanged from the 08-18 analysis.
- `_collect_self_assigns`' Pass 1.2 caller loop
  (`all_structs_for_methods`, ~4.92s) — still mutates the struct AST
  directly and depends on three separately-evolving pieces of state;
  unchanged from the 08-18 analysis.
- `_dedup_variadic_externs` (~5.7s) — NOT an `imported_stmts` AST
  consumer (post-hoc string dedup of generated C text); out of this
  bug's scope, as classified on 08-18.
- The remaining smaller consumers (`_infer_local_var_types` Pass 1.3b,
  ~1.17s post-Phase-4 — would need the Phase-3-style pure-scan/
  time-dependent-filter split since it calls state-dependent
  `_quick_type` per assignment; the Pass 2c residual scan walks
  themselves, ~5.5s, which could be halved by a within-Pass-2c-run
  result cache keyed on `(id(func), _prepass_struct)` since all their
  inputs are provably frozen for one run — not attempted, following
  this doc's one-consumer-at-a-time discipline now that no single
  remaining line dominates).


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
