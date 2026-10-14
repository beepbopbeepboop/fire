# HARD BUG (performance): `_walk_ast` re-scan blowup for large transitive-import graphs

## Status (2026-10-02, this pass — the doc's stated BLOCKER is measured away; what remains is two hazards, both named with their sites)

The 2026-10-02 Phase 9 entry below ends with the reason `_walk_ast` is the
one cost left, and it is a design objection rather than a measurement:

> `_walk_ast` returns a fresh `list`, and its callers do everything with lists:
> `for n in _walk_ast(body)`, `result.extend(_walk_ast(child))`, and several
> that then sort or filter the result. A memo keyed on `id()` would hand the
> SAME list object to every caller, and **one caller mutating it corrupts
> every later reader** — a silent wrong answer from a performance change...
> Making it safe needs either a read-only sequence type threaded through every
> caller, or a per-caller-keyed cache, and neither is a narrow change to a
> shared utility.

**The mutation half of that is now measured, and it is one call site.** Every
`_walk_ast` call in the tree, classified by what it does with the result:

| | count |
|---|---|
| total call sites | **69** |
| `for ... in`, `yield from`, `any()`, `all()`, `list()` — read-only by construction | **63** |
| bound to a name (`_nodes = _walk_ast(body)`), then immediately `for node in _nodes` | **5** |
| other | 0 |
| **mutate the returned list in place** | **1**, and it is not a caller |

The one is `mojo/middle/exprtypes.py`'s own docstring describing
`_walk_ast_into`'s accumulator — `_walk_ast_into` takes an `out` list and
appends to it, which is the accumulator, not a consumer of `_walk_ast`'s
return value. So the "thread a read-only sequence type through every caller"
half of the objection has **nothing to thread through**: 68 of 69 sites never
touch the list, and the 69th iterates it once. That is why Phase 5 could
already rewrite the walk as an accumulator without touching a single call
site, and it is the same fact Phase 5 could not see from the inside.

This is worth having as a number because it changes the shape of the fix: the
memo does not need a new return type, a per-caller cache, or a
migration. It needs the existing `list` plus a check.

### The two hazards that are left, with their sites

1. **Write-invalidation from AST mutation.** This is the real one and it is
   the trap this doc has already fallen into twice (Phase 5's write analysis,
   Phase 7's superset analysis). `grep -c '\.fields\.append|\.body\.append|
   \.args\.append|\.handlers\.append'` over `mojo/backend_gimple/` and
   `mojo/middle/` is **20 sites**, and three of them are exactly the shape
   that matters: `module_gen.py:4159`, `:4246` and `:4442` all do
   `s.fields.append(VarDecl(name=fn, ...))` on a `StructDef` that other passes
   walk. A memo keyed on `id(structdef)` filled before one of those appends
   and read after it returns a walk that does not contain the new field —
   a wrong artifact, not a slow one. There are also whole-statement
   REPLACEMENTS (`_inline_single_use_task_composition`,
   `_normalize_await_kwargs`) which are safe by id-change rather than by
   discipline.

2. **`id()` reuse.** The key is an address, so a freed node's id can be handed
   to a different node. Phase 2's `_field_scan_var_cache` gets away with it
   because the AST is pinned by `_all_transitive_stmts_ordered` for the whole
   compile — but `_walk_ast` is also called on temporary subtrees
   (`_walk_ast(stmt)` at `module_gen.py:4259`/`:4274`/`:4295`, and
   `_walk_ast(node)` over a `MemberExpr` chain), so a weak reference to the
   node is required, not a bare id.

### Step 3 landed 2026-10-05 (`work/bugs7-4`): the census is now a CHECK

`test_gimple.py`'s `no_walk_ast_caller_mutates_what_it_is_handed`, beside
`walk_ast_dataclass_cache_is_transparent`, walks every `.py` under `mojo/` and
`formal/` with `ast`, finds every call of the shared `_walk_ast`, and reports
any that MUTATES what it was handed — `.append`/`.extend`/`.sort`, an assignment
to an index of it, `+=`, `del`. **67 call sites, none mutating** on this tree,
against the 69 this doc's hand census counted (the closure has moved).

Two things the executable form got right that a hand census cannot, both found
by running it:

* **A copy is not a handover.** The first version matched any assignment that
  CONTAINED the call and reported three sites that do not exist:
  `mojo/middle/coro.py`'s `_inner = {id(x) for x in _walk_ast(aw.value)}` is a
  set LITERAL and `_inner.add(...)` mutates that set, not the walk's list — so
  the assignment's value must BE the call, not merely contain it.
* **A name is not a slot.** Two of the three were `_rets`, which is bound twice
  in one 6 000-line `module_gen.py` function — once from a comprehension over the
  walk and once as a dict — so a whole-function scan of every use of the name
  conflated two different objects. The scan is therefore scoped from the
  binding statement to the NEXT binding of the same name, which is the region
  where a handed object is actually live under that name.

A third came out of proving the check rather than running it: `_ast.AugAssign`
was listed as a rebinding, which made the region end AT the `+=` line and the
scan skip its own line — so `ns = _walk_ast(b); ns += [1]` reported clean. It is
a HAZARD and not a rebinding, because `list.__iadd__` mutates in place and
returns the same object, and it is now absent from the binding list on purpose.

Verified not vacuous, and verified in both directions: 15 hand-written programs
(one per shape, including all six mutators, the copy-by-display case, the
rebound-before-use case and the `for`-target rebinding) classified correctly by
the same code, and with a `.append` and then an `+=` injected into
`mojo/middle/closures.py`'s `_local_defs` the check names that one site and the
run goes 385/1; with the injection removed, 386/0.

**This is the part of the fix that was worth landing on its own whether or not
the memo ever is**, and it is now in the everyday gate.

### The exact next step

1. A generation counter bumped by every AST-mutating site — the 20 above, plus
   the rewriter passes — and included in the memo key. That converts hazard 1
   from "be careful" into "a stale entry is unreachable", which is the only
   form of this fix that is worth landing at all.
2. `weakref`-keyed entries (or a strong ref held alongside the entry, which is
   the same cost) for hazard 2.
3. Return the SAME list to every caller, with a check that keeps it that way:
   `test_gimple.py` already has `walk_ast_dataclass_cache_is_transparent`
   proving the walk's CONTENT and ORDER are unchanged, and the census above
   should become a check — "no call site of `_walk_ast` mutates its result" —
   so the property is enforced rather than true today. That check is cheap, is
   what makes the memo safe to add later, and is worth landing on its own
   whether or not the memo ever is.
4. Byte-identical generated C on the 160-module chain and on
   `Lib/socket.py`, as every phase in this series has done, plus the three
   suites the Phase 9 entry lists.

**Not attempted this pass.** This is a light-worker branch with four compiled-
path changes already on it, and CLAUDE.md's own definition of done for a change
to `mojo/middle/exprtypes.py` is the full gate plus a byte-identity anchor,
neither of which was available here. The census and the hazard census above
are what the pass was for: they turn "it needs a read-only sequence type
threaded through every caller, and that is not narrow" into "there is one call
site to think about and it is not a caller".

**State: OPEN — the CLOSED banner this doc carried until 2026-09-26 was wrong.**
Phases 1-6 did land, and the AST-node-visit blowup the doc's own Symptom
section measured IS gone (numbers below). But the underlying shape — per-level
work proportional to *cumulative* tree size, summed over N levels, i.e. O(N²) —
survives in a different unit of work, and is now the single largest consumer in
a profile. Do not read "Phase 6 removed the last quadratic rescan" as the bug
being fixed; see the 2026-09-26 entry for the measurement and the named site.

**State as of 2026-09-30 (Phase 8, below): the site that entry names is now
fixed** — the per-level rescan over generated C text is gone, and what is left
at `_dedup_variadic_externs` is the one per-level cost that is not a rescan (a
`'\n'.join` of the output the caller asked for). The doc stays OPEN because the
other three items in "Remaining work" are untouched, but the headline "34% of
the run, still superlinear" no longer describes this function.

**State as of 2026-10-02 (Phase 9, below): one of those three is now measured
on a fresh profile, and the answer is that only one of them is still worth
anything.** Re-profiling the doc's own benchmark shape (a synthetic struct
chain, `class` + class attrs + `__init__` self-assigns + a method + a libc
call per module) at n=20/40/80/160 gives a per-doubling ratio of **2.95x then
3.62x** — still superlinear, so the shape the doc exists to kill is still
here. But the profile's rank-1 is `_walk_ast_into` itself, not any of the three
named candidates, and the two of those three that still appear are cheap.
Phase 9 removed the last of the per-visit `dataclasses` reflection from it
(96.2% fewer calls, byte-identical output). What is left is honest, measured
and named below; nothing in "Remaining work" was silently declared done.

## Status (2026-10-02, Phase 9 — `_walk_ast_into` asks "is this class a dataclass" once per CLASS, not once per node visit)

### What changed

`_walk_ast_into` (`mojo/middle/exprtypes.py`) already cached
`dataclasses.fields(node)` per class — that is Phase 5, and it is the reason
the reflection cost is not what it was. What it did NOT cache is the question
one line above: `dataclasses.is_dataclass(node)`, asked on **every node
visit**, to decide which of the two arms to take. Both are pure functions of
`type(node)` and both are static for the life of the process, so the answer
now lives in a second per-class dict, `_WALK_DATACLASS_CACHE`, keyed on the
same `type(node)` the field-name cache already used.

### Measured

160-module struct chain, `compile_to_gimple(do_imports=True)`. The metric is
`dataclasses.is_dataclass` call COUNT, which is profiler-independent (this doc
established that cProfile inflates per-call sites enormously and that wall
clock is the honest end-to-end column — see Phase 7's own note):

| metric | before | after |
|---|---|---|
| `is_dataclass` calls | 4,371,942 | **164,375 (−96.2%)** |
| `_walk_ast` calls | 164,662 | 164,662 (unchanged) |
| wall clock (n=160) | 7.32s | 7.45s (within noise) |
| generated C, n=160 chain | 1,986,475 bytes | byte-identical (md5 `6a7d7caf1b928d2c4999c24b9837cde1` both sides) |

**The wall clock did not move, and that is the honest headline.** 1.42s of a
23.3s profiled run (6.1%) was attributed to those calls, and cProfile charges
~0.34 µs of its own overhead per call — 4.2M calls is ~1.4s of the profiler's
own cost, which is very nearly the whole attributed figure. The real saving is
the difference between 4.2M `is_dataclass` calls (each an `isinstance` walk up
`cls.__mro__` plus a `__dataclass_fields__` lookup) and 164K dict hits, which
at ~0.2 µs each is ~0.8s of the *unprofiled* 7.3s… which the wall column does
not show either, because the machine was contended and the run-to-run spread
is larger than that. This is a small win, honestly measured and honestly
reported as such; it is not a phase that changes the complexity class.

### Equivalence evidence

- **Byte-identical generated C** on the 160-module chain (1,986,475 bytes, same
  md5 both sides) and on a real large succeeding case: `Lib/socket.py` from
  the CPython 3.14.6 tree at `/Users/mrs/net/Python-3.14.6`, 1,149,048 bytes,
  md5 `99b5c680b25453d0837606bbfe1344ef` both sides, 34.5s vs 36.2s wall.
- **`test_gimple.py`'s `walk_ast_dataclass_cache_is_transparent`** asserts the
  invariant that matters, which is NOT the call count: the node list the cached
  walk produces must equal, node for node and in order, what a verbatim
  pre-cache body produces. The failure mode a cache could have here is a walk
  that silently STOPS descending — the dataclass test runs *before* the scalar
  early-return precisely because on the self-hosted compiled path every AST
  node is an int64_t-boxed pointer and so tests as an `int` (that ordering's
  own comment) — and a stopped descent is a wrong artifact, not a slow one.
  Verified the test bites: sabotaging the cache to answer "not a dataclass"
  for everything turns it red (`probe StructDef: 44 nodes, got 1`) and takes
  11 other tests with it.
- Driven over a real parsed module (real AST node types, not stand-ins) and
  over the arms the cache has to keep apart: a genuine dataclass, a plain
  non-dataclass object, a `type` object — which returns before the dataclass
  question is asked and so must never gain a cache entry, asserted explicitly —
  and the scalars.

### What is left, precisely — a fresh profile, and a re-ranking of "Remaining work"

The three candidates "Remaining work" has listed since 2026-08-18 were each
re-measured against this profile rather than trusted, and the result is worth
recording because two of the three are no longer worth doing:

| candidate | verdict on a fresh n=160 profile |
|---|---|
| `_class_attr_ctype`'s Pass 1.1 caller loop | **does not appear** in the top 18 by `tottime` or by `cumtime`. The 08-18 analysis ("entangled with time-dependent `struct_field_types` and adjacent inheritance-merge logic") is why it was never attempted, and on this benchmark it is not the cost it was assumed to be. Whether that generalises to a benchmark that exercises class attributes harder is NOT established here — this chain's class attrs are two scalars, not containers. |
| The Pass 2c residual scan (`_infer_return_elem_type`) | **does not appear.** Phase 4 hoisted its seeding; what is left is ~0 in this profile. The doc's own "not recommended without new evidence" stands, and this is that absence of evidence, measured. |
| `_collect_self_assigns` / `_collect_self_reads` | 26,080 calls, 1.75s cumtime of a 23.3s run (7.5%). **Still the largest of the three, and still untouchable for the reason Phase 3 gives** — it mutates struct ASTs directly (`s.fields.append(...)`), so memoizing it means caching raw syntactic shape and re-deriving the type from three live pieces of state on every call. |
| `_dedup_variadic_externs` | **gone from the profile** (Phases 7 and 8). |

So one of the three is a real 7.5% and structurally blocked, and the other two
are not costs in this benchmark. That is the honest state of the list, and it
is why this entry does not close the doc.

### The site that IS the remaining cost

Rank 1 by `tottime` is `_walk_ast_into` (4,742,278 calls, 3.59s tottime,
**6.81s cumtime = 29% of the profiled run**) and rank 2 is `builtins.isinstance`
(58,059,832 calls, 3.38s) which is mostly called *from* it — five `isinstance`
tests per node visit, re-decided every time. `_walk_ast` itself is entered
164,662 times, i.e. ~1,023 whole-subtree walks per module at n=160, and each
one is a fresh recursive descent.

This is the same per-level-rescans-cumulative-tree shape the doc exists to
kill, one level up from Phase 8: the memoized per-statement caches
(`_field_scan_var_cache`, `_calls_in_stmts_cache`, `_param_usage_scan_cache`)
cover the *consumers* that Phase 2-4 enumerated, and `_walk_ast` — the shared
utility every one of them calls — is not among them, so a consumer nobody
memoized still walks the cumulative tree at every level.

**Not attempted, and the reason is specific.** `_walk_ast` returns a fresh
`list`, and its callers do everything with lists: `for n in _walk_ast(body)`,
`result.extend(_walk_ast(child))`, and several that then sort or filter the
result. A memo keyed on `id()` (the pattern Phase 2 established for
`_scan_body_for_local_field_access`) would hand the SAME list object to every
caller, and one caller mutating it corrupts every later reader — a silent wrong
answer from a performance change, which is the trap this doc has already
fallen into twice (Phase 5's write-invalidation analysis, Phase 7's superset
analysis). Making it safe needs either a read-only sequence type threaded
through every caller, or a per-caller-keyed cache, and neither is a narrow
change to a shared utility. It is the right next phase and it needs its own
proof, not a drive-by.

### Not run, owed by the integrator

Worker pass only: `make gate`, `compile_stdlib.py`, `build_stdlib_dylib.py`,
`mojoc`, the bootstrap stages. The change adds 6 lines to a file INSIDE the
compiled closure, so the checks that can only see the self-hosted binary's own
lowering of it (`mojoc` builds, `stage2`/`stage3`,
`stdlib-dylib`'s `skip <module>:` count vs baseline — must not increase — and
`stdlib-syntax`'s unexpected-failure count vs baseline — must not increase) are
exactly the ones still owed. `test_gimple.py` 349 passed / 1 failed,
`test_gimple_runner.py` 266 passed / 2 failed,
`test_module_cache.py` 83/0, `test_link_mode.py` 13/0,
`test_silent_noop_iter.py` 16/16 — every failure byte-identical to the
parent commit's run.

## Status (2026-09-30, Phase 8 — the output text's parse is DERIVED, so the parent stops rescanning the child's whole blob)

Phase 7's own "What is left, precisely" said the only remaining way to make
this sub-quadratic was to stop re-deriving both name sets from the whole corpus
on every call, and rejected a shared running `concrete` set as a superset of any
one level's corpus. This phase takes the other road it did not name: it does not
share state across levels at all — it makes each level's own computation
*derive* the parse of the text it is about to hand back, so the parent's very
first read of that text is a cache hit instead of a fresh byte-by-byte scan.

**The shape.** `_dedup_variadic_externs` is called once per `gen_module_impl`
and is handed the CUMULATIVE `parts`; the parent's parts contain each imported
module's whole output blob (`imported_code.append(code)`,
module_gen.py:1733). Phase 7 memoized per part TEXT, which made the scan O(one
scan per distinct text) — but a blob is a distinct text the instant it is born,
and its parse is *exactly the union of the parses of the parts that produced
it*, which the child level had just read from the same cache. So half of all
parse volume was spent re-deriving from scratch, byte by byte, what the child
had derived a moment earlier. Phase 8 publishes that derivation
(`_record_output_parse`): `_DEDUP_EXTERN_PARTS_CACHE[out] = (concrete,
variadic)` where `out` is the text just returned. Per-level parse volume
becomes the bytes THAT level added, not the cumulative corpus.

**Why it is not an assumption.** `'\n'.join(parts)` changes the parse at exactly
one place: where a `;`-delimited fragment SPANS parts. So every such run is read
back with the same per-fragment function the parts themselves were parsed with
(`_fragment_names`, factored out of `_parse_part` for that reason) and must
carry exactly the names its pieces carried separately; when any run fails,
nothing is published and the parent parses the text exactly as before. The
shapes that break it are not guessable and each one was found by a differential
harness, not by argument:

- a run can straddle THREE OR MORE parts — an empty part has no `;` either, so
  the join's own newline passes straight through it (`['extern int a (int', '',
  'extern int a (...)']`);
- a piece that names NOTHING can still complete the other piece's declaration:
  `extern int late (int` has no closing paren, and glued to `char * g2000
  (char *)` it becomes one fragment that DOES name `late` — so a
  "neither side carried a name, so the merge is harmless" fast path is unsound,
  and the cheap skip has to be on `_is_extern_decl` instead;
- two pieces naming DIFFERENT functions cannot both survive (a fragment carries
  at most one concrete and one variadic name), and the comparison has to be
  against EVERY piece, not the first: `extern int a (int)` + `extern int a
  (int)` + `extern "C" ... b (...)` with no `;` anywhere is ONE fragment whose
  `find('(')`/`rfind(')')` span all three — naming `a`, swallowing `b`, equal
  to the first piece and different from the union.

Also two provably-equivalent short circuits on the parse itself: a fragment, or
a whole part, with no `extern` substring cannot satisfy any of the accepted
declaration shapes, so it skips the `.split('\n')`/strip work entirely (the
whole-part one matters because `.split(';')` materializes one str per
statement — tens of thousands for a multi-MB blob).

**Measured.** `std/format/tstring.mojo` (a real 228-level closure; "bytes
parsed" is the cache-miss volume, i.e. what actually got scanned in Python,
and is profiler-independent):

| metric | before | after |
|---|---|---|
| bytes parsed | 733,616,248 | 10,924,140 (**−98.5%**) |
| time inside `_dedup_variadic_externs` (summed over the 228 levels) | 4.010s | 0.662s (**−83%**) |
| cumulative corpus handed to the function | 755,419,799 | 755,419,799 (unchanged — see below) |
| live cache entries at exit | 22,352 | 22,353 |
| wall clock | 125.2s | 124.2s (within noise; the machine was contended) |

Synthetic struct chain (the doc's own benchmark shape: a `class` with attrs,
`__init__` self-assigns and a method per module, plus a libc call so extern
declarations actually exist), cumulative corpus per level unchanged:

| n | levels | corpus scanned before | after | time in fn before | after |
|---|---|---|---|---|---|
| 20 | 20 | 3.84 MB | 0.17 MB | 0.019s | 0.005s |
| 40 | 40 | 16.6 MB | 0.31 MB | 0.077s | 0.015s |
| 80 | 80 | 76.8 MB | 0.59 MB | 0.330s | 0.057s |

**What is left, precisely.** The corpus is still handed to the function at every
level and is still O(cumulative) — that is inherent to the output, not a
rescan: the parent's text genuinely CONTAINS every descendant's text, so
producing it costs one `'\n'.join` per level (one memcpy of bytes the caller
requires as a single str). What is gone is the per-byte Python-level
re-reading of it. Two residual per-level costs remain, and neither can change
output: the `'\n'.join`, and one dict lookup per part plus one `concrete.add`
per name in that part's entry. The second is *cheaper* than it was — a derived
entry is the child's already-deduplicated name SET, where a fresh parse is a
LIST, so a part declared once per module in the closure now costs one `add`
per level instead of one per declaration. Measured as the count of names folded
across the 80 levels of the n=80 chain: 3,240 before, 158 after. It is still
O(the corpus's extern names) per level, and making THAT O(delta) needs the
shared running `concrete` set this doc already rejected twice as a superset; it
stays rejected.

**Equivalence evidence.** Generated C BYTE-IDENTICAL on two large succeeding
real cases — `std/io/io.mojo` (28,318,118 bytes, md5
`248e44fd29f532280b5d212726dfc9a8`) and `std/format/tstring.mojo` (8,021,416
bytes, md5 `f7ac69d1b240328ac7181f134ee34b9d`) — and on the synthetic chain at
every size measured, each `cmp`-clean from a fixed module directory so the
`#line` directives are stable too: n=20 263,458 bytes md5
`be03542847a1bd17e3e869d795374e52`, n=40 525,278 bytes md5
`d18d3d1ef28569d712a4ad18fa1e9bed`, n=80 1,120,918 bytes md5
`83feabd12315910be3af32c660f27e81`. Differential harness (old body verbatim,
private memo, vs new): exhaustive over all 8,400 pairs and triples, and
175,692 4- and 5-tuples, of a 20-piece adversarial set built from
empty/whitespace/`;`-only parts and unterminated extern fragments in both
arities; 4,000 randomized corpora; a multi-level simulation (each level's parts
contain the previous level's output) over 300 seeds with EVERY published entry
compared against an independent parse of that text; real generated C split into
random chunks at 7 chunkings; and repeat-call stability (a warm cache must not
change a second answer).

**Gate** (2026-09-30, worker pass only): `python3 test_gimple.py` 333 passed /
0 failed, including the new `dedup_variadic_externs_cache_is_a_faithful_parse`;
`python3 test_module_cache.py` 83 passed / 0 failed;
`test_silent_noop_iter.py` 16 passed / 0 failed (the change adds a `for` loop
over a local list inside a nested helper, so the loop-lowering suite is the one
that would notice if it were not lowered).

**NOT RUN, and owed by the integrator** — this pass was a light worker and
deliberately did not run `make gate`, `compile_stdlib.py` or
`build_stdlib_dylib.py`. The change adds code to a file INSIDE the compiled
closure, so the checks that can only see the self-hosted binary's own lowering
of it are exactly the ones still owed: `mojoc` builds, the three `stage*`
self-host steps, `stdlib-dylib`'s `skip <module>:` count vs baseline (must not
increase), `stdlib-syntax`'s unexpected-failure count vs baseline (must not
increase), `ab-native` and `native-dumpfull` (expected red for a documented
pre-existing reason — `bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md`
— and must not get redder).


## Status (2026-09-26, Phase 7 — `_dedup_variadic_externs`: one pass + per-part memo; the residual is now provably the corpus, not the rescan)

Fixed the double scan and made every byte-stable part free. The function is
`mojo/backend_gimple/emit_infra.py:_dedup_variadic_externs`, reached once per
`gen_module_impl` through the `self._dedup_variadic_externs` shim.

**What changed.** Two things, both in that one function:

- **Two passes → one.** The old shape scanned every fragment twice, once to
  build the `concrete` name set and once to decide each part's fate,
  re-deriving `paren`/`close`/`params`/`name` the second time. It could not
  be collapsed only because `concrete` is incomplete until every part has
  been read — but a per-part `_parse_part` returning `(concrete, variadic)`
  name lists lets the drop test become a membership question asked
  afterwards, so the parse is shared instead of repeated. The predicate is
  unchanged: a part is dropped iff one of its variadic names is in the
  tree-wide `concrete` set, and an empty parameter list still decides
  nothing in either direction (the old pass 1 skipped it via
  `params not in ('...', '')`, the old pass 2 via `params != '...'`).
- **Per-part memo, process-global** (`_DEDUP_EXTERN_PARTS_CACHE`), keyed by
  the part's exact text. Sound with no invalidation logic because the cached
  value is a pure function of the key — the whole text of the part, with
  nothing time-dependent in it — unlike the `_field_scan_var_cache` /
  `_calls_in_stmts_cache` family. Same shape as `_WALK_FIELD_NAMES_CACHE`;
  a free function has no gen instance to hang it on. Lookup is cheap rather
  than merely correct because CPython caches a str's hash on the object.

**Measured** (160-module struct chain; `_is_extern_decl` call count is the
doc's own "4.47M calls" metric in this unit, and is profiler-independent):

| metric | before | after |
|---|---|---|
| `_is_extern_decl` calls, n=160 | 11,188,407 | 5,411,601 (−52%) |
| `_dedup_variadic_externs` cumtime, n=160 | 12.97s (34% of run) | 12.47s (not top-8) |
| total function calls, n=160 | 311,230,595 | 249,144,568 (−20%) |
| total profiled time, n=160 | 38.64s | 33.26s (−14%) |
| part-lookup hit rate, n=40 | n/a | 89.8% (14,426 lookups, 1,476 misses) |

Direct wall clock, before/after interleaved on the same machine: n=40
5.69s→5.46s, n=80 6.32s→6.21s, n=160 10.33s→9.41s. The win is real but
noticeably smaller than the 34% the profile attributed, and the reason is
worth recording rather than hiding: **cProfile inflates this site
enormously**, because it charges per-call overhead to a function called
11.2M times. The call-count halving above is the trustworthy number; the
wall-clock column is the honest end-to-end one.

**Equivalence evidence.** Byte-identity anchor: the full generated artifact
for a 160-module chain, same generated module sources both sides, `cmp`
clean — 4,025,900 bytes, md5 `e3ac15998b324c44604f688946f3dcab` both sides.
Differential harness, old body vs new body on real generated text: whole-file
(498,600 chars) identical; 6 fragment arrangements (all `;`-pieces, first 50,
every 7th, per-line split, `[text, '', text]`, reversed) identical;
repeat-call stability (the cache must not change a second answer) identical;
9 hand-built edge shapes identical (variadic-before-concrete and
concrete-before-variadic, empty param list, unbalanced `(`/`)`, `extern *
foo (...)` vs a concrete prototype, a `#line ".../external_b.mojo"`
directive that must NOT read as `extern`, empty-string parts, a fragment
with no `;` terminator, one name declared both ways).

**Gate** (2026-09-26): `make check` 5/7 with `modcache` (client object 9320
bytes) and `no-new-casts` (34 vs baseline 28) failing — both byte-identical
to the pre-change baseline. `stdlib-dylib` and `stdlib-syntax` 2/2, 0 skip
lines. `mojoc` builds; `ab-native` 0/30 and `native-dumpfull`
(`./mojoc fire.py --dump-full` → exit −11) unchanged from baseline.
`bootstrap`: stage1-transitive and stage2-cc pass, stage2-dumps all exit
−11 — the pre-existing self-hosted SIGSEGV, untouched by this phase. The
`emit_calls.py` env-struct fix earlier in this series is what makes
stage2-cc pass at all. The user's own separate tree (`~/net/gcc-fire/gcc`,
`rm fire.ci; make`) still regenerates and links `fire1` with this change in
the compiled closure.

**What is left, precisely.** The residual is still superlinear
(`_is_extern_decl` calls per doubling: 41,691 → 184,021 → 933,481 for
n=20/40/80, i.e. ~4.4x then ~5.1x), and it is now *provably* the corpus
rather than a rescan that a cache could have absorbed. Instrumenting the
misses at n=40: 1,839 missed parts totalling 13.9 MB, largest 728 KB and
growing with the tree, with the top 5 alone 24.6% of missed bytes. So the
texts that miss are not a small unstable remainder — a module's emitted
`parts` genuinely *is* O(its import closure), because `do_imports` inlines
each imported module's output, so the corpus handed to this function really
does grow with the tree at every level. 89.8% of lookups hit (the
byte-stable parts), and the misses carry essentially all the fragments.

That means the only remaining way to make this sub-quadratic is to stop
re-deriving both name sets from the whole corpus on every call, and maintain
them incrementally as parts are appended, at the single place parts are
appended. **That is not attempted here and is not obviously safe**: a shared
running set is a superset of any one level's own corpus whenever a module's
text differs between two levels (which the miss data says it does), so it
could drop a part that the per-level computation would have kept — a silent
output change, which is exactly the trap the write-invalidation analysis in
"Phase 5 implementation notes" rejected for the Pass 2c cache. It needs its
own pass, with its own proof that the running set is exactly the per-level
corpus's set, not a superset.

**(Superseded 2026-09-30 by the Phase 8 entry above, which took the other
road: it keeps the per-level computation exactly as it is and instead makes
each level publish the parse of the text it returns, so the parent's read of
that text is a hit. The shared running set above is still rejected, still for
the superset reason.)**

So the doc stays OPEN, but the honest headline is now narrow: the AST-node
rescan this was named for is fixed and has been for several phases; the
per-level re-derivation over generated C text is halved and cached, and what
remains is a corpus-size cost that no per-call cache can remove.

## Status (2026-09-26 — the CLOSED banner is withdrawn; the rescan is reduced, not eliminated)

Re-measured the doc's own headline metric on the current tree, with `cas`
defeated (every generated module's source made unique per run, since
`compile_to_gimple`'s imported-module path is CAS-served and would otherwise
report a warm cache rather than a compile). Metric: total `_walk_ast_into`
node visits, i.e. exactly the "4.47M calls" the Symptom section reports, as a
function of the number of modules in a linear import chain.

**Function-only chain — LINEAR, the original defect is genuinely fixed:**

| modules | node visits | ratio |
|---|---|---|
| 20 | 6,532 | |
| 40 | 12,832 | 1.96x |
| 80 | 25,432 | 1.98x |
| 160 | 50,632 | 1.99x |

A clean 2x per doubling, ~316 visits per module, flat. For comparison the
Symptom section's 36-module `contextlib.py` case cost 4,473,166 `_walk_ast`
calls; a 36-module chain costs ~11k today. That is the win, and it is real.

**Struct/class-attr chain — still SUPERLINEAR.** Repeating the same
measurement with a `class` per module (class attrs `A`/`B`/`var D`,
`__init__` self-assigns, a method) so the struct-shaped consumers the
"Remaining work" list names are actually exercised:

| modules | node visits | ratio | per-module |
|---|---|---|---|
| 20 | 38,585 | | 1,929 |
| 40 | 96,696 | 2.51x | 2,417 |
| 80 | 273,136 | 2.83x | 3,414 |
| 160 | 866,016 | 3.17x | 5,413 |

Per-module cost nearly triples from n=20 to n=160, and the per-doubling ratio
is *rising* (2.51 → 2.83 → 3.17). Total work is ~n^1.7 and still steepening.
So the unmemoized consumers this doc's "Remaining work" section names are
live exactly as written.

**The dominant remaining site, and it is the one the doc wrote off.**
`cProfile` of the 160-module struct chain (38.6s profiled, 311M calls):

| rank | function | cumtime | ncalls | note |
|---|---|---|---|---|
| 1 | `_dedup_variadic_externs` | 12.97s | 161 | **34% of the run** |
| 2 | `_is_extern_decl` (nested in it) | 11.41s | **11,188,407** | ~69.5k statements re-scanned per call |
| 3 | `ast_rewriter.rewrite` | 7.04s | 430 | per-module parse/rewrite, legitimately linear |
| 4 | `_selfhost_module_scalar_globals` | 6.28s | 161 | see below |

`_dedup_variadic_externs` (emit_infra.py:3080, called once per
`gen_module_impl`) is handed the ENTIRE accumulated `parts` — the generated C
text of every module compiled so far, across the whole tree — and scans it
TWICE end to end, once to build the `concrete` set and once to decide what to
drop, calling `_is_extern_decl` (a per-line `.split`) on every `;`-delimited
fragment each time. Per level that is O(cumulative emitted text); over N
levels, O(N²). This is **the same bug this doc exists to kill, measured in
generated-C fragments instead of AST nodes** — the identical "re-walk the
cumulative total at every level" shape, and it is 4x larger than the largest
AST-walking consumer left.

It was ruled out of scope on 08-18 and again on 08-25 on the grounds that it
is "NOT an `imported_stmts` AST consumer (post-hoc string dedup of generated
C text)". That classification is what left the O(N²) alive under a CLOSED
banner: the unit of work is irrelevant to the complexity class, and this site
is the one the doc's own metric now points at.

Not attempted yet. It looks like a self-contained, low-risk fix — the two
passes share one parse per fragment (the second re-derives `paren`/`close`/
`params`/`name` the first already computed), and a per-fragment-text memo
would collapse the repeated per-level rescans. It is still a change to
compiled-path codegen, so it owes the full quality gate and a byte-identity
anchor, which is why it is named here rather than landed in the same pass as
the measurement.

Separately, the other three named items in "Remaining work" are unchanged and
still unmeasured against this doc's metric: `_class_attr_ctype`'s Pass 1.1
caller loop, the Pass 2c residual scan, and
`_collect_self_assigns`/`_collect_self_reads`. Given
`_dedup_variadic_externs` is 34% of the run, it is the one to do first; the
`_class_attr_ctype` entanglement analysis (unchanged since 08-18) should be
re-run against a post-fix profile rather than trusted as still-current.

## Status (2026-09-25, Phase 6 — `_selfhost_extracted_fn_index` no longer built for non-selfhost compiles)

A fresh cProfile of `Lib/contextlib.py` on the current tree (post-Phase-5,
and post the generator/try-finally work landed since) found one new,
self-contained, provably-safe win that is NOT any of the three candidates
the "Remaining work" list had ruled out.

**The defect.** `_selfhost_gen_self_param_ctype`
(`mojo/middle/funcs_shared.py`) guards on two independent conditions: that
the `gen`/`self` first param belongs to a function this compiler's own
backend files actually define (answered by `_selfhost_extracted_fn_index`),
and that this compile is a self-hosting one
(`gen._selfhost_gimplegen_registered`). The second check is a single
attribute read and the first is a full parse of every `gimple_*.py` /
`mojo/middle` / `mojo/backend_gimple` file — but the EXPENSIVE one ran
first. `_selfhost_gen_self_param_ctype` is asked about a `gen`/`self` first
param on essentially every parameter of every function in every compile,
while `_selfhost_gimplegen_registered` is only ever set for an entry point
under this compiler's own source dir. So **every ordinary user/stdlib
compile built the whole index and then discarded the answer.** That is
`compile_stdlib.py`'s per-worker-process cost, every `fire.py build`, and
every test-suite process, all for nothing.

The fix is a pure reordering of two side-effect-free conditions (both must
hold, so the result is unchanged): the registration check now runs first,
so the index is simply never built when it cannot be used.

**Measured.** cProfile attributed 21.1s of cumtime to
`_selfhost_extracted_fn_index` (715 calls, with `py_tokenize` /
`parse_module` / `_rewrite_node` underneath) — but cProfile inflates that
heavily. Timing the build directly gives **~1.5s for 448 entries**, so the
real win is ~1.5s once per process. Small in absolute terms and a rounding
error against a whole-stdlib sweep, but a real fraction of a quick
`fire.py build small.mojo`, and free. Confirmed the index genuinely is
skipped now (its cache key stays absent after a complete `Lib/contextlib.py`
compile) and still IS built when needed.

**Equivalence evidence** (stronger than this doc's usual byte-identity
bar, because the edit is to a file inside the compiled closure):
`--dump-full`-equivalent `compile_to_gimple(fire_compiler.py,
do_imports=True)` before and after is **byte-identical once every `#line`
directive is removed** (`diff` of the two `#line`-stripped files: 0
differing lines). The raw files differ only in `#line` numbers, which is
expected and not a regression: the edit adds comment lines to
`mojo/middle/funcs_shared.py`, and that file is itself in the compiled
closure, so every subsequent function's recorded line number shifts. The
self-hosting path still works — the index still builds for a self-host
entry point, and the output still types 464 `gen`/`self` first params as
`GimpleGen *`.

**Still not attempted**, per "Remaining work" below: the three candidates
already ruled out (`_class_attr_ctype`'s Pass 1.1 caller loop's entanglement
with time-dependent `struct_field_types` state; the Pass 2c residual-scan
cache, disproven by Phase 5's own write-invalidation analysis; and
`_collect_self_assigns`/`_collect_self_reads` mutating struct ASTs, which
rules out naive memoization). The profile's rank-1 consumer is still the
`isinstance` builtin (283s / 7.6B calls), spread across every consumer's
per-node type dispatch with no single attributable site. Two smaller
candidates the profile surfaced but that are self-host-specific and did not
clear the bar on this pass: `_infer_list_elem_type` (35.7s / 271M calls)
and `_param_ctype` (22.1s / 375K calls).

## Status (re-verified 2026-08-26, worktree fix/rest-remainder19c — no new phase attempted; Phase 5's "Remaining work" list re-read, none newly safe)

Re-read the "Remaining work" section fresh with today's assignment's
explicit instruction not to force a risky change here. All three listed
candidates are unchanged and still correctly assessed as unfavorable:
`_class_attr_ctype`'s Pass 1.1 caller loop remains entangled with
time-dependent `struct_field_types` state and adjacent inheritance-merge
logic (the same reasoning since 08-18); the Pass 2c residual scan cache
idea is proven unsafe by Phase 5's own writeup (`_return_elem_types`
feedback through `_quick_container_elem` breaks any whole-run cache);
`_collect_self_assigns`/`_collect_self_reads` still mutate struct ASTs
directly, ruling out a naive memoization the same way Phase 2 originally
had to work around for its own sibling consumer. No new profiling done
this pass (none of this campaign's other 9 docs touch `gen_module`'s
hot paths in a way that would shift the profile shape), and this doc's
own established verification bar (byte-identical generated C on a large
succeeding whole-program case) means any attempted fix would need the
same rigor as Phases 1-5 to be trustworthy — not undertaken here given
none of the three candidates cleared the safety bar. No code change.

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

**Phase 5 implemented and verified 2026-08-25** (see "Phase 5
implementation notes" below). The doc's previously suggested Phase 5
(a within-Pass-2c-run result cache keyed on `(id(func), _prepass_struct)`)
was evaluated FIRST and found **UNSAFE as stated** — the scan's inputs are
NOT frozen for one Pass-2c run: `_quick_container_elem` resolves call
elements through `gen._return_elem_types`
(gimple_gen_infra.py:_quick_container_elem, `.get(key)` on the very dict
Pass 2c's fixpoint loop writes), which is precisely how callee elem types
propagate to callers across iterations ("so the fixpoint propagates callee
elem types to their callers", its own docstring). Freezing iteration-1
results would change the fixpoint outcome whenever propagation needs >1
iteration — i.e. exactly the cases the loop exists for. Instead, a FRESH
cProfile re-ranked the remaining consumers again and gave a different,
safer winner: `_walk_ast` ITSELF — the shared whole-program traversal
utility this bug is named after — was spending ~29s of its 71.8s
cumulative time re-doing `dataclasses.is_dataclass` + `dataclasses.fields`
reflection for EVERY node visit (56.5M + 16.1M calls in one profiled run)
plus per-subtree list extend-churn. Fixed centrally (per-class field-name
cache computed once via the real `dataclasses.fields()`, accumulator-style
walk helper): traversal order/content proven IDENTICAL (differential check
node-by-node over parsed ASTs of contextlib.py/socket.py plus synthetic
try/finally/fstring/lambda shapes; identical 66,607,301 visit counts in
before/after profiles), `Lib/socket.py` generated C BYTE-IDENTICAL
(`cmp` clean, same md5), socket.py wall 106.4s→97.3s, contextlib.py
interleaved A/B 78-79s→71s.

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
re-checked directly: `python3 fire.py build Lib/poplib.py` completes in
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

### Phase 5 implementation notes (2026-08-25)

**Why the previously suggested Phase 5 was rejected (negative result,
verified by code reading).** The 08-23 "Remaining work" entry proposed
halving the ~5.5s Pass-2c residual scan walks "by a within-Pass-2c-run
result cache keyed on `(id(func), _prepass_struct)` since all their
inputs are provably frozen for one run". That premise is FALSE. The
scan's result depends on `gen._return_elem_types`: `_infer_return_elem_
type`'s helpers (`_collect_local_container_elems` →
`_quick_container_elem`, gimple_gen_infra.py) resolve a `CallExpr`
return value's element type via `gen._return_elem_types.get(key)` — the
SAME dict the Pass-2c fixpoint loop itself writes after every function.
That lookup is not incidental; it is the propagation mechanism ("call
elements resolve through _return_elem_types so the fixpoint propagates
callee elem types to their callers", the function's own docstring).
Within one run, iteration k+1 legitimately sees different
`_return_elem_types` than iteration k did (both intra-iteration, as
writes happen per-function while the loop advances, and inter-
iteration), so any whole-run result cache freezes iteration-1 values
and can change which entries land in `_return_elem_types` — and with
them the generated C — whenever elem-type propagation takes ≥2
iterations. Rejected as unsafe; only a write-invalidation or dependency-
graph scheme could be correct, and both are materially more complex and
higher-risk than the win justifies (the whole residual is ~3% of the
run). This is also why Phase 4's seeding hoist was safe while this is
not: `func_return_types` is genuinely frozen during one Pass-2c run
(nothing reachable from the scan writes it — verified then);
`_return_elem_types` is written BY the loop that surrounds the scan.

**What was done instead: make `_walk_ast` itself cheaper.** A fresh
cProfile of `Lib/contextlib.py` on this branch's tree (post-Phases-1..4;
shape had shifted again) ranked, among non-`isinstance` consumers:

| rank | function | cumtime | ncalls | note |
|---|---|---|---|---|
| 1 | `_walk_ast` | 71.77s | 66.6M node visits | the shared traversal utility — of which ~29s was `dataclasses.is_dataclass` (56.5M calls) + `dataclasses.fields` (16.1M calls) re-reflection performed for EVERY visited node, plus `list.extend` churn (67.3M calls, 4.74s) from building/discarding a fresh list per subtree |
| 2 | `_scan_body_for_local_field_access` chain | 66.91s | 114 | Phase 2's memoized consumer — residual cost is its own first-visit-per-statement `_walk_ast` work through rank 1 (2345 distinct statements tree-wide, properly hitting the shared id-keyed caches) |
| 3 | `_class_attr_ctype` | 39.42s | 101.4M | Pass 1.1 caller loop in gen_module_impl's frame — unchanged analysis (time-dependent `struct_field_types` + adjacent inheritance-merge entanglement); NOT touched |
| 4 | `_collect_self_assigns` | 8.33s | 50842 | mutates struct ASTs; NOT touched |
| 5 | `_infer_return_elem_type` (Pass 2c residual) | 10.13s | 485494 | see rejection above |

Rank 1 subsumes rank 2 and part of everything else that walks ASTs, so
the fix was applied centrally to `_walk_ast` itself
(gimple_exprtypes.py), touching NO consumer logic:

- New module-level `_WALK_FIELD_NAMES_CACHE: dict[type, tuple]`. On
  first sight of each node class, its field-name tuple is computed ONCE
  with exactly the original semantics — `hasattr(cls,
  '__dataclass_fields__')` (== `dataclasses.is_dataclass` for an
  instance) and the REAL `dataclasses.fields(cls)` (which accepts the
  class and returns the same Field sequence as for an instance,
  including its ClassVar exclusion) mapped over `.name`. Negative
  results (non-dataclasses) are cached as `()` too. Keyed by class, not
  node: a class's dataclass field set is static for the process
  lifetime, so entries cannot go stale.
- New `_walk_ast_into(node, out)` accumulator helper reproduces the old
  traversal exactly — same None skip, same list/tuple flattening
  without emitting the container, same pre-order [node, children in
  fields() declaration order] sequence, same `not isinstance(node,
  type)` guard making a dataclass CLASS object a leaf — just appending
  into one output list instead of extend-copying a fresh list per
  subtree. `_walk_ast(node)` keeps its exact signature and returns a
  fresh flat list as before; all ~48 call sites across gimple_*.py are
  untouched.

Equivalence evidence beyond the gate: a differential harness compared
old-walk vs new-walk output node-by-node (`is` identity, order, count)
over every top-level statement of parsed contextlib.py (29 stmts),
socket.py (38 stmts), synthetic struct/try/finally/f-string/lambda/
nested-container source (2 stmts), plus direct edge values (None,
empty/odd lists, functions, classes, dicts, sets, bools); before/after
profiles show IDENTICAL total visit counts (66,607,301 both sides).

### Validation (2026-08-25, Phase 5)

Byte-identity anchor (this doc's standard): `Lib/socket.py` generated C
via `compile_to_gimple(..., do_imports=True)` — **BYTE-IDENTICAL**
before/after (`cmp` clean, 17,905,426 chars, identical md5
0e947172570668cad46065520cb994ce both sides). Pure performance change.

Wall clock (heavily contended machine throughout — concurrent agent
builds; reported as measured):

| file | before | after |
|---|---|---|
| `Lib/socket.py` (SUCCEEDS) | 106.45s | 97.32s |
| `Lib/contextlib.py` (fails at the same documented async-codegen point both sides; interleaved A/B, file temporarily reverted for "before") | 79.49s / 78.19s | 71.53s / 71.28s |

cProfile diff, contextlib.py, same method as prior phases:

| metric | before | after |
|---|---|---|
| `_walk_ast` cumtime | 71.77s / 66.6M visits | 38.98s / 66.6M visits (−46%, SAME visit count) |
| `dataclasses.is_dataclass` calls | 56.5M / 14.95s | gone from top-45 |
| `dataclasses.fields` calls | 16.1M / 13.84s | gone from top-45 |
| `list.extend` | 67.3M / 4.74s | 61.7M append + no per-subtree copies |
| total profiled time | 334.9s | 281.4s |
| total function calls | 3.030B | 2.823B |

Full quality gate (2026-08-25):
1. `python3 test_gimple.py` — 256 passed, 0 failed.
2. `python3 test_module_cache.py` — 76 passed, 0 failed.
3. `make check-selfhost` — clean (`✓ self-host compiles + links clean`).
4. From-scratch stdlib dylib rebuild — exit 0, 0 `skip <module>:` lines
   (baseline 0 — no increase).

### Remaining work (not attempted)

Updated 2026-08-25 after Phase 5 (fresh post-change profile in
`ctx_after.stats`, contextlib.py). No single remaining line dominates;
the raw top consumer is now the `isinstance` builtin itself (74.4s /
2.10B calls) — spread across every consumer's per-node type dispatch,
not attributable to one fixable site:

- `_class_attr_ctype`'s Pass 1.1 caller loop (`all_struct_defs`,
  ~36.0s profiled / 101.4M calls from gen_module_impl's own frame) —
  still entangled with time-dependent `struct_field_types` state and
  adjacent inheritance-merge logic; unchanged analysis since 08-18.
  Now the largest named non-builtin consumer.
- The Pass 2c residual scan walks (~9.3s profiled / 485k calls of
  `_infer_return_elem_type`) — the previously suggested whole-run
  result cache keyed on `(id(func), _prepass_struct)` is UNSAFE as
  stated; see "Phase 5 implementation notes" for the proof
  (`_return_elem_types` feedback through `_quick_container_elem`).
  Any correct variant needs write-invalidations or a caller→callee
  dependency graph over the fixpoint; complexity/risk outweighs the
  ~3%-of-run win. Not recommended without new evidence.
- `_collect_self_assigns`/`_collect_self_reads` (Pass 1.2, ~5.2s) —
  still mutates struct ASTs directly (`s.fields.append(...)`); the
  same 08-18 analysis holds.
- `_dedup_variadic_externs` (~4.4s) — NOT an `imported_stmts` AST
  consumer (post-hoc string dedup of generated C text); out of this
  bug's scope, as classified on 08-18. **Fixed anyway as Phase 7
  (2026-09-26) and Phase 8 (2026-09-30); the per-level rescan over
  generated C text is gone, see those entries.**


## Symptom

`python3 fire.py build <file>.py` (`do_imports=True`) takes minutes (or
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
