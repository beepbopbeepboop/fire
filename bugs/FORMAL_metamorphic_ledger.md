# FORMAL_metamorphic_ledger: what `tools/formal_metamorph.py` has measured, and what came of it

**This is the ledger metamorphic sweeps are recorded in.** One row per sweep (corpus, seed, index range, programs, pairs, both architectures, the tally as the tool printed it), then one entry per BACKEND finding with what happened to it, and one for each defect the TOOL turned out to have — because those cost more than the backend bugs did and a metamorphic tool's own defects are invisible in a tally of passes.

`bugs/FORMAL_fuzz_ledger.md` is the differential fuzzer's ledger and the two read together: `formal_fuzz` asks "does the image answer what CPython answers", this one asks "do two builds of the same meaning answer the same". See §3 for why the second question reaches a class the first cannot.

## 0z. Status 2026-10-09 (`formal262-docs`): §6 item 1 is CLOSED — the `struct` decision is made, and the three files are driven

`normalise_mojo` now translates a `struct`, scoped to the case where a decision
is forced rather than guessed, and the examples corpus is **93 of 93 driven**
(`test_formal_metamorph.py` 62/62; the examples sweep of §2 prints no
"NOT measured" line, 0 findings, 0 `transform-invalid`/`transform-crash`, and 20
programs firing a normalising rule where it was 17). The DECISION §6 item 1 asked
for is this:

* **A field declared an INTEGER type reads `0` on this path, so the translation
  writes `0`.** `Point()` zero-initialises every field before any store, measured
  on BOTH architectures through the ORIGINAL `struct` build and on CPython through
  the twin — which is why `self.x = 0` is the meaning of `x: Int` here and not an
  invented value. `_STRUCT_ZERO_TYPE_RE` is the closed set (`Int`/`UInt` with an
  optional `8`/`16`/`32`/`64`), so the decision is one table rather than a rule
  reading the type.
* **Every other struct stays unmeasured and names `struct`.** A field whose type
  is not in that set is a value this tool will not guess at, and a struct with an
  explicit `__init__` is a construction body this tool does not model; both keep
  the old outcome (reported, never silently dropped). The coverage assertion now
  requires that NOTHING is unmeasured, so a new undrivable example fails the
  suite rather than lowering a number.
* **It is checked per file and not argued.** `example_program` sets `verbatim` for
  a struct file, so `check_pair`'s step 0 builds the file AS WRITTEN and requires
  the same answer as the twin on every backend — which is where a wrong decision
  about a field's value would be found. The three files (`wide_recv`,
  `struct_point`, `struct_method`) answer `4`/`1`/`5` on CPython and both
  architectures, original and twin alike.

**And a latent rule defect fell out of it: `FN_DECL_RE` removed `fn` without
putting `def` back.** The replacement was the indent capture alone, so `fn f(n):`
became `f(n):` — a note that fired and a file that still could not parse. It was
invisible because the only `fn` example, `wide_recv.mojo`, was unmeasured for the
`struct` reason anyway; making the struct translatable is what reached the broken
`fn`. The rule now rewrites to `def`, which is what its own coverage fixture
(`("fn g(n):…", ("fn ",), ("def g(n):",))`) always claimed and never executed,
because the fixture was only checked on the `text is None` path.

## 0. Status 2026-10-07 (`formal126-docs`): the tool's own suite was RED in five
## places on `master`, and the two that are the TOOL's are fixed at the root

`test_formal_metamorph.py` is this ledger's instrument, and on `master` it ran
5 failures in 55 tests. Three were one stale MOCK — `TheDriver._run_check_pair`
stubbed `formal_fuzz.cpython_answer` with a bare `(exit, stdout)` tuple, which
`formal_fuzz.has_oracle` stopped accepting when it grew `OracleAnswer` — and two
were the tool and its corpus:

* **A THIRTEENTH defect in a TRANSFORM, and the oracle found it.** §5's table is
  twelve; `reorder` swapped a container store past the read that observes it by
  another name — `a = o.v` then `o.v[0] = 62` moved past `w = a[0]`, printed
  `46` where CPython prints `62`. Caught on `refs:0` of `formal_fuzz`'s `refs`
  mix. It is in §5, and the NAME-level independence test could not state it: the
  shared object is not a shared name. `_function_aliases` closes it.
* **ELEVEN examples were unmeasured for ONE missing decorator name.** The
  refinement corpus's `@refines(Specs.abs64; 64)` is not valid Python — the `;`
  inside the parentheses — and the normaliser's proof-decorator rule listed
  `@spec`/`@require`/`@ensure` and not `@refines`. Named, and the eleven
  (`absval`, `bigconst`, `bitops`, `chain`, `fact`, `identity`, `localmul`,
  `nonzero`, `pair`, `shiftlr`, `sum`) are driven. The three `struct` files
  (`wide_recv`, `struct_point`, `struct_method`) stay the documented exclusion,
  and the coverage assertion now asks WHY a file is unmeasured rather than
  "all but one" — §6's second half.

The suite is 56/56 after the change. Nothing else in this file moves: no sweep
in §2 re-ran, and the tool's tally was never the thing that was wrong.

**Status 2026-10-07 (`work/formal143-docs`): the suite was RED, for five reasons, and none of them had been seen because `test_formal_metamorph.py` is in no bucket — `python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_metamorph.py` was `FAILED (failures=5)` and is now `Ran 59 tests … OK`. Three were a stale MOCK and two were real.** Read this before §2a's coverage claims, which §5's rows and §6's list below predate.

* **`reorder` was UNSOUND on an ALIASED pair, and this is the thirteenth defect in §5, not a new class.** The `refs` mix (index 0, `--stmts 8 14`) binds two names to one list (`A32 = h31.b23`) and then stores through one and reads through the other:

      A32[0] = 46        # …A32 aliases h31.b23
      w34 = A32[0]       # prints 62 in the original…
      h31.b23[0] = 62

  `reorder` swapped the store and the read. The two statements' names are disjoint (`{h31}` against `{A32, w34}`), which is all `t_reorder`'s independence test looked at, so the twin printed `46` where the original printed `62` — a real metamorphic violation manufactured by the harness, exactly the shape §5 warns about. **Fixed at the root**: `t_reorder` now merges the two statements' name sets through `_alias_classes`, a union-find over the function's direct aliasing assignments (`A32 = h31.b23`, `A35 = L20`, `A47 = A32`), before any of its conflict rules run. Only a DIRECT assignment whose value is an existing object establishes an alias; a call result is treated as fresh, and a name is merged even when the aliasing store and the use are on different paths — over-approximating can only refuse a swap. Measured: the reorder twin is sound over all 27 mixes × indexes 0-5, and the hand-written rows are `ReorderAliasing`. The control (`c = [b[0], 4]`, a fresh list) is still swappable, so the rule refuses the alias and nothing else.
* **Eleven examples were refused by CPython, and the cause was one decorator missing from the removal rule.** `@refines(Specs.factorial64; 20)` is a proof-layer annotation whose arguments are not Python at all; `normalise_mojo` removed `@spec`/`@require`/`@ensure` and not it, so every file carrying it died at line 11. Adding `refines` to `PROOF_DECORATOR_RE` moves the examples corpus from **79 of 93 driven to 90 of 93** — §6's item 3 and §2a's "before" numbers are now one corpus behind.
* **The remaining 3 unmeasured examples are the documented `struct` decision and only that.** `wide_recv.mojo` was §6 item 1's single unmeasured file; `struct_point.mojo` and `struct_method.mojo` are the other two. `test_the_examples_corpus_is_mostly_measured` asserted `driven >= len(stems) - 1`, which the new struct files broke; it now asserts the REASON instead (every unmeasured stem must be unmeasured for the `struct` decision, never for a spelling the normaliser can remove), which is the same claim and does not rot as the corpus grows.
* **Three driver tests were mocking a return shape that no longer exists** (`cpython_answer` returns `(OracleAnswer, reason)` since the `OracleAnswer` type landed, and the mock returned a bare `((0, ""), "")`), so `check_pair` read its own oracle as `not-answerable` and the three rows asserting `match`/`CROSS-MACHINE-REFUSAL` failed for a reason that had nothing to do with the tool. Updated to `F.OracleAnswer(0, "")`. That is a test defect, not a §5 tool defect, and is named here so the next reader does not go looking for a driver regression.

**What this does NOT close:** §6's four items are unchanged — the `struct` decision (now named as the 3 stems above), the stdlib sweep, the two rare transforms, and the `int_only` lower bound. Nothing here is a new SWEEP; it is the suite going from red to green with the two real defects fixed.

**Status 2026-10-07 (`work/formal160-docs`): FOUR tool defects and two stale
test expectations were red, and they are fixed. `test_formal_metamorph.py` was
55 tests with 5 failures; it is 55/55 now.** Two are `reorder` soundness holes
that §5's table did not carry, both caught by the file's own
`test_every_transform_preserves_the_meaning`:

* **An ALIAS made two names look independent.** `A32 = h31.b23` makes `A32[0]`
  and `h31.b23[0]` one memory, and `reorder` swapped `h31.b23[0] = 62` past
  `w34 = A32[0]` — the two statements mention no name in common, and the
  printed value moved 62 → 46 (generated `refs:0`). This branch's
  `Analysis.alias_closure` and `_reference_aliases` are the relation it
  consulted; the same fix's form in the merged tree is `_alias_classes`/
  `_canonical` (the Status entries above name it), a sound over-approximation
  built from assignments whose RHS is a Name/Attribute/Subscript.
* **The call-reachability rule asked only about WRITES.** `_reachable_by_a_call`
  is the names a CALL may READ OR WRITE, so `w13 = G8` swapped past
  `print(bump11(1))` — which writes `G8` — moved the printed value 32 → 33
  (generated `globals:3`). The rule now asks about reads too.

The other two are in the normaliser and the tests: `normalise_mojo` removed
`@spec`/`@require`/`@ensure` but not `@refines(Specs.factorial64; 20)`, whose
Mojo-only arguments CPython's parser refuses, so ELEVEN examples (`fact`,
`sum`, `absval`, `bitops`, `chain`, `bigconst`, `identity`, `localmul`,
`nonzero`, `pair`, `shiftlr`) were undrivable; and the driver's unit tests
mocked `cpython_answer` with a bare `(exit, stdout)` tuple, which
`oracle_answer` rejects, so three cross-machine verdict tests read
`not-answerable`. §6 item 1's "one unmeasured example" is therefore three
`struct` files now (`wide_recv`, `struct_point`, `struct_method`), which is
the documented non-goal rather than the `@refines` hole.

**Status 2026-10-13 (merging `work/formal192-docs`): the branch carried a
parallel record of the SAME six defects, so its Status section is deduped
into the entries above rather than kept as a second copy. Its one addition
to the merged tree is the read-hazard hunk itself: the merged code still
asked only about WRITES (`a.writes & reach`) when the branch was merged, and
the check is now `(a.reads | a.writes) & reach` in both directions — what the
2026-10-07 entry above describes and measured in advance (`globals:3`,
32 → 33). The branch's alias mechanism (`Analysis.alias_closure` and
`_reference_aliases`) is the parallel form of `_alias_classes`, and its
hand-written pin is covered by `ReorderAliasing`. Measured on the merged
tree: `test_formal_metamorph.py` is 62/62 (the file has grown since the 160
entry's 55), peak 0.2 GB; `test_formal_mlir_precedence.py` is 40/0.**

**Status 2026-10-13 (`work/formal402-docs`): §6 item 4 is MEASURED, and the
measurement is a sound broadening of `swap_add`'s operand predicate.** The item
asked for the remaining `int_only` decline reasons "measured rather than guessed
at". Measured they are, and the reading splits the row in two:

* one half is `int_only`-bound — a `+` operand that is a name the analysis
  cannot prove integer (a subscript, an attribute, a comprehension target, a
  string store). Broadening the OPERAND predicate cannot reach those, and the
  numbers say so: `refs` stays 2/8 and `comps` moves 2→3 and no further.
* the other half was the predicate being too NARROW about a name it HAD
  classified: `_operand_ok` accepted only an int literal or a bare name in
  `int_only`, so a `+` written as an EXPRESSION was declined even when both
  sides were provably integers. `unpack`'s `u1 * 1 + u2 * 2` is the shape and
  neither operand is a name.

So `_operand_ok` is now `Analysis.is_int_expr` — the analysis's own `_int_expr`
at the published `int_only` — and the soundness argument is unchanged (`+` is
commutative over integers; `_int_expr` declines a subscript, an attribute and
every container, so nothing whose commutativity is in doubt is admitted).
Measured over the 27 generator mixes at `--stmts 10 30`, seed `x402`, 8 programs
each, driving the transform itself rather than a predicate stand-in: **146 of
216 programs had a `swap_add` candidate before and 156 after**, on `argshape`
7→8, `comps` 2→3, `environ` 4→5, `limits` 1→4, `slicing` 2→3, `strings` 5→6,
`strmeth` 4→5 and `unpack` 3→4. `strfmt` did NOT move, and that is the useful
negative: its declines are `int_only`-bound, which is the other half of the
reading. Pinned by `test_formal_metamorph.py`'s `product_operands` program (a
`MUST_APPLY` row) and `test_an_expression_operand_is_an_int_when_its_leaves_
are` (accepted both ways, a string `+` declined); the CPython gate over all 27
mixes is what keeps the broadening sound.

## 1. The rule this ledger keeps

A row is a MEASUREMENT of a run, never a target. What makes a row worth reading is the TRANSFORM table beside it, not its tally: a run where `inline_helper` skipped every program and one where it answered 200 pairs are the same tally, and the second measured something the first did not.

The anti-rot is the per-transform table the tool prints on every run, which is why `test_formal_metamorph.py::MUST_APPLY` exists: a transformation that stops applying reports the same clean tally as one that never worked. `test_no_transform_is_measured_on_nothing` checks that the table of "must apply somewhere" and the table of transformations cannot drift apart in either direction.

## 2. Sweeps

Machine: 18-core arm64 macOS, `python3` 3.14.7. Every sweep `-j 6` and BOTH backends. Peak memory across every sweep in this file: **0.2 GB** (`tools/memslot.py --gb 8`, which kills at 8), so nothing here is within an order of magnitude of the 3-4 GB line in `doc/POLICY_memory_over_4gb.md`.

**Sweep 1** — `calls`, seed `metamorph`, indexes 0-59, `--stmts 8 14`, **600 pairs**, 265.6 s. 60 match, 0 findings. Peak 0.2 GB.
**Sweep 2** — `formal/examples`, **41 programs / 410 pairs**, 153.2 s. 41 match, 0 findings, 1 program carrying a pre-existing `DIVERGENCE` (`udivmod`, §4). Peak 0.1 GB.
**Sweep 3** — the remaining twenty mixes at 20 programs each: `core`, `lists`, `classes`, `containers`, `globals`, `generics`, `strmeth`, `signed`, `strings`, `argshape`, `slicing`, `closures`, `unpack`, `bignum`, `chains`, `loopelse`, `tryfinally`, `strfmt`, `fstrings`, `limits`, **4000 pairs**, 20 mix runs. 0 findings, 0 `transform-invalid`, 0 `transform-crash`.

Total on the tool's own sweeps: **5010 pairs over 22 corpora, both architectures**. Peak 0.2 GB.

## 2a. The second session's sweeps, and the two rules that made them worth running

The first session's §6 said the tool's reach was its problem, and named four
things. Two of them turned out to be *reachability of the analysis*, not of the
corpus, and fixing them is what §2b is about; the other two (Mojo-only syntax, an
entry point that takes arguments) were coverage holes in the examples corpus and
are `normalise_mojo` / `example_program`.

**Sweep 4** — `formal/examples`, after both: **51 programs / 510 pairs**, 108.8 s,
`-j 6`, both architectures. 51 match, 0 findings, 0 `transform-invalid`,
0 `transform-crash`, 0 `NORMALISES-*`. 1 file not measured (`wide_recv`, `struct`).
Peak 0.2 GB. **Before: 41 programs / 410 pairs.** The one `DIVERGENCE` is still
`udivmod` (§4) and is still not this ledger's.

**Sweep 5** — the five mixes the integer classification changed most: `core`,
`containers`, `argshape`, `lists`, `loopelse`, 20 programs each at
`--stmts 8 20`, **1000 pairs**, both architectures, 62-73 s per mix. 100 match,
0 findings, 0 `transform-invalid`, 0 `transform-crash`. Peak 0.2 GB. The
per-transform table is what makes this row worth reading rather than its tally:

| mix | `swap_add` before | after |
|---|---|---|
| `core` | 4 of 20 | **19 of 20** |
| `containers` | **0 of 20** | **18 of 20** |
| `argshape` | 5 of 20 | **16 of 20** |
| `lists` | 7 of 20 | **19 of 20** |
| `loopelse` | 9 of 20 | **20 of 20** |

**Sweep 6** — the soundness sweep that is NOT a build, because the property it
checks is about the transforms rather than about the backends. Seed `mm-r3`,
indexes 0-59, all 22 mixes, `--stmts 8 24`, all ten transformations:
**8971 CPython pairs, 0 `transform-invalid`.** Per transform: `if_true` 1320,
`reorder` 1320, `rename` 1314, `dead_local` 1309, `noop_loop` 1301, `swap_add`
923, `extract` 653, `def_order` 397, `extra_param` 397, `inline_helper` 37.
No build, no memslot pressure worth naming (well under 0.1 GB), and it is the
cheapest thing in this file per unit of coverage: it is what catches a defect in
a transform before any image exists, and it found the twelfth one in §5.

**Sweep 7 — the LARGE-PROGRAM sweep, and the only one that found anything.** Every
row above is `--stmts 8 20` or `8 24`. All 22 mixes at `--stmts 30 60`, 8
programs each, **1760 pairs**, both architectures, `-j 4`, 3.8-112.9 s per mix.
**0 findings, 0 `transform-invalid`, 0 `transform-crash`** — after the three
fixes in §5b, each of which was a false positive on ten programs or seven.
Peak 0.3 GB.

Three reasons this row exists and the others do not substitute for it:

* **programs are 3x the frame.** Every one of §2's programs is small, so a rule
  that is only wrong on large programs is indistinguishable from a rule that is
  right. `REFUSAL-DIVERGES` compared LINE NUMBERS, and it fired on 10 of 10
  `limits` programs here and on none of the 440 in §2's sweep 6 — because a small
  program has no refusal to quote a line from.
* **the `refused by backend` line is what makes the row readable at all.** Every
  program of `limits` and of `fstrings` is REFUSED on both machines, which the
  tally reported as `match` — so "1760 pairs, 0 findings" is 160 of those pairs
  measuring nothing, and before the line existed the screen said `match 10` and
  nothing else.
* **`CROSS-MACHINE-REFUSAL` is new** and this sweep is what reached it: 1 of 8
  `slicing` programs, where x86-64 refused a slice view for the container budget
  and arm64 built it. That one is the DOCUMENTED asymmetry (§4b), so the sweep
  reports it as a measurement rather than a finding — which is the point of the
  row: it says how often the budget is the binding constraint, and a reader can
  now see the answer instead of inferring it from a clean tally.

## 2b. 2026-10-07 (`formal112-docs`): the alias hazard in `reorder`, and the `@refines` decorator group

Two defects were found by running the file's own suite rather than by a sweep,
and both are the shape this ledger exists to record: a tool defect is invisible
in a tally, and a coverage hole reads as a clean number.

**`reorder` was unsound through an ALIAS, and CPython caught it as
`transform-invalid` before any build.** `A32 = h31.b23` binds `A32` to the same
list as `h31.b23`, so `h31.b23[0] = 62` and `w34 = A32[0]` are one cell — but the
independence test compares names as SPELLED, saw writes `{h31}` against reads
`{A32}`, and swapped them. The generated `refs:0` program printed `46` where the
original printed `62`. `_alias_groups` is the fix: an assignment whose right-hand
side is a name, an attribute or a subscript unions its target with the root of
that expression, transitively and without regard to where the assignment sits
(a conditional alias is a possible alias, and a possible alias is a refusal). The
equivalence is applied to every read/write/escape set before the comparisons, so
it can only ADD refusals. Two rows pin it: `test_reorder_refuses_a_pair_that_
aliases_through_a_binding` (every pair in that program aliases, so `reorder` must
decline the whole function) and `test_reorder_still_swaps_two_independent_
container_writes` (two DISTINCT lists must still be exchangeable, so the rule was
not made sound by refusing all memory traffic). This is §5's defect shape one
more time — the alias is the same class as the closure cell (#6) and the global
(#7), reached through a binding instead of a call.

**The examples corpus's largest unmeasured group was `@refines`.** `PROOF_
DECORATOR_RE` removed `@spec`/`@require`/`@ensure` and not `@refines`, so the
eleven examples that spell it (`absval`, `bigconst`, `bitops`, `chain`, `fact`,
`identity`, `localmul`, `nonzero`, `pair`, `shiftlr`, `sum`) were refused with
CPython's own "invalid syntax" at the decorator's line. It is the same class as
the three the rule already covers — a decorator the PROOF layer reads and the
run-time path never sees — so it goes through the same parenthesis-depth scan
(its argument list wraps and contains a `;`). Measured: the examples corpus was
**93 stems, 90 measured / 3 unmeasured** after this change, where it was 79/14
before, and all three remaining were the one documented `struct` decision
(`struct_method`, `struct_point`, `wide_recv`) — **since made and driven; §0z is
the decision and 93 of 93 is the figure it leaves.** `test_the_examples_corpus_is_
mostly_measured` asserts that no example is left unmeasured, so a future example
that cannot be driven for a NEW reason fails the suite instead of lowering a
number nobody reads.

**And three `TheDriver` rows were stale against the `OracleAnswer` type.** They
stubbed `cpython_answer` with a bare `(exit, stdout)` tuple, which `oracle_answer`
no longer recognises (it is a `NamedTuple`), so every one of them read as
`not-answerable`. Fixed in the test, not the tool: the stub now returns
`F.OracleAnswer(0, "")`, which is the same shape the real function returns.

## 3. What metamorphic testing reaches that differential testing cannot, and the measurement

`formal_fuzz` finds a miscompile only where the program PRINTS the value whose lowering is wrong. That is a property of the program, not of the backend, and it is structural: a register-allocation bug in a frame slot the program never prints is invisible to a corpus whose programs all have the same shape.

The measurement that the two questions are not the same question, and that this one is not a slower version of the other:

* **`if True:` was read as a branch by `read_before_store`'s CFG**, so a store inside a constant-true guard did not dominate the reads after it. Every such program was REFUSED — on BOTH architectures — with a sentence asserting "CPython raises UnboundLocalError for that program", which is false. Found as `TWIN-DIVERGES` on **8 of 30** programs of a `calls` sweep (one machine lowered the original and refused the twin), minimised to 12 lines, fixed at the root in `formal/model.py::_build_cfg`, with ten regression rows (six in `test_formal_read_before_store.py`, three each way, and four in `test_formal_run.py` on both backends). **The oracle would not have found it**: the program is one `formal_fuzz` would generate, and `formal_fuzz` reports a refusal as a refusal — a correct answer to "does the image compute this program", not a bug.
* **`k = -1` bound nothing in the CFG's preheader table**, so `for i in range(k)` with `k = -1` was undecidable, the loop target was treated as bound, and a read of `i` after the loop was accepted — on a program CPython refuses with `UnboundLocalError` for every probe value. Found by the same fold (`_cfg_int_literal` gained `UnaryOp('-', IntLiteral(1))`, which `_range_is_nonempty` had been folding for itself). Before/after table in `formal/model.py`'s docstring; rows `for_range_bound_decided_negative_refused` / `_positive_ok`.

## 4. The one `DIVERGENCE` in the examples sweep, and why it is not filed here

`formal/examples/udivmod.mojo` is `(n / 7) + (n % 7)` over `0`, `5`, `-5`. CPython answers `0.0`, `5.714…`, `1.285…`; both images answer `0`, `5`, `2`. `/` is INTEGER division on this path, and `n % 7` takes the sign of the divisor.

This is a real disagreement and it is **not** this tool's to file or attribute: `formal_fuzz.py` owns the differential queue with its own `KNOWN_DIVERGENCES` / `neutralise` / `blame` machinery, and this is a semantics gap in both backends rather than an x86-64 bug. So the tool reports it as `DIVERGENCE-<ARCH>` — counted, printed, named as `formal_fuzz`'s queue, and excluded from its own exit status. An earlier version reported it as a finding, which is the failure this split exists to prevent: see §5.

## 5. Defects in the TOOL, which cost more than the backend bugs and are invisible in a tally

Thirteen, all caught by the tool's own CPython gate (`CPython(P) == CPython(T)`, run on BOTH sides before any backend is asked) or by the examples/classes/closures corpora. The gate is the reason each of them is a unit-test failure rather than a filed bug. The thirteenth is §2b's alias hazard, and it is the same `reorder` family as #4-#7 reached through a binding (`A = B`) rather than a call.

| # | what | how it showed | verdict it would have produced |
|---|---|---|---|
| 1 | `rename` renamed a parameter's USES but not its `ast.arg` | 6 of 30 `calls` programs, `not-answerable` | a `NameError` twin reported as a tool result |
| 2 | `global G` read as a LOCAL (the declaration is line 1, the conflicting store line 9) | 1 `globals` program, `not-answerable` | `rename` rewriting a global's reads |
| 3 | a `DictComp` has neither `elt` nor `keywords` | 6 programs, `transform-crash` | the whole `containers` mix unmeasurable |
| 4 | `reorder` treated `print(…)` beside `print(…)` as independent | 13 programs, `transform-invalid` | **every** backend bug |
| 5 | `reorder` read `L8[0] = 31` as a statement that writes nothing | 2 `lists` programs | the same |
| 6 | `reorder` swapped `c = 9` past the call that reads a closure's cell | 1 hand-written program | the same |
| 7 | `reorder` swapped `G = 57` past a call that mutates `G` from another function | 2 of 20 `globals` | the same |
| 8 | `inline_helper` substituted parameters one at a time and CAPTURED (`f(b, 2)` into `f(a, b)`) | 4 `closures` programs | the same |
| 9 | `inline_helper` asked the PROGRAM's parent index about a fresh subtree, so no substitution happened at all | 4 `closures` programs | a twin with a raw parameter name |
| 10 | a comprehension's target was bound in the ENCLOSING function, and a PEP 750 `TemplateStr` was invisible to the "source text" check | 9 `fstrings` + hand-written corpus | `rename` renaming half a name |
| 11 | `extract` deleted a binding a nested scope captures | 7 of 20 `closures` | a printed number moving |
| 12 | `_bind_body` refused to descend into a nested `def` **except when the `def` WAS the statement**, so `global G6` inside `def bump7` was read as a declaration of the MODULE and `G6` was dropped from `module_bindings` — which is the set `reorder`'s `_reachable_by_a_call` consults | 1 of 5910 pairs in the §2a sweep 6, `stress-mm:18` of `globals` | `G6 = 9` exchanged with `print(bump9(5))`, and the printed value moved from 14 to 25 |
| 13 | `reorder` treated a container store and a read of the SAME OBJECT under another name as independent — `a = o.v` then `o.v[0] = 62` swapped past `w = a[0]` | `refs:0` of the `refs` mix, `transform-invalid` on the CPython gate; the printed value moved 62 → 46 | the transform shipping a store past the read that observes it |

Twelve is one more than the eleven above and it is the one worth reading twice,
because its two consequences pull in OPPOSITE directions and the over-approximating
one hid it: the module scope also collected `main`'s locals, which made
`_reachable_by_a_call` refuse swaps it need not refuse — a silent loss of pairs that
looked exactly like a corpus with no independent statement pairs. The
under-approximating one was the `global`, and it is the only defect in this file
that lived in the SCOPE BUILDER rather than in a transform. **A measurement that
only counts the verdicts would have seen a clean sweep.**

**Thirteen is the FIRST one the corpus reached through a shape rather than a
trivial pair**, and it is the same lesson as #12 from the other side: #4, #5, #6
and #7 are four versions of "the two statements DO interact and the name test
said they do not", and #13 is the fifth — a store and a read of one object under
two names. It is the thirteenth only because the `refs` mix is new; the class is
as old as the `lists` mix. That is the argument for keeping the corpus growing
instead of curating it: the oracle cannot see a hole in a shape the corpus does
not draw.

Plus three that were about the TARGET's representation rather than the transforms, and would have been filed as backend bugs:

* **a constructor's body is INLINED at the construction site** (`formal/build.py`), so its shape IS the construction. `if_true` / `noop_loop` / `dead_local` inside `__init__` were declined — correctly, with a message naming the construct — and the tool was calling that `TWIN-DIVERGES`. Now `_is_constructor`.
* **a method's receiver is identified by the NAME of its first parameter** (`formal/model.py::RECEIVER_PARAMETER_SPELLINGS`), so `rename` deleted it: 20 of 30 `classes` programs came out `TWIN-DIVERGES` with `C5.m15() is declared with parameters and no receiver`. The spellings are imported, not re-spelled.
* **`_loop_target_defs` / the loop-target question** — not reached; recorded here because the `if <constant>:` rule touches the same preheader machinery and a reader should know the sweep did not exercise it.

## 5a. The one place the oracle CANNOT check the tool, and the gate that can

Everything in §5 was caught by comparing the two programs on CPython. **A
NORMALISING RULE is the one thing that check cannot see**, because normalisation
moves P and T together: a rule that changed the meaning would leave the oracle
comparing a program with itself. So the rewriting is checked against the file AS
WRITTEN, by the machine — `check_pair::_normalisation` re-runs the verbatim file on
every backend and requires the same answer (`NORMALISES-DIFFERLY-<arch>`), and a
verbatim spelling that will not build is `NORMALISES-UNCOMPARABLE` rather than a
skip, because nothing then established that the removal preserved anything.

Measured: 16 of the 90 driven examples are measured in a dialect this tool
rewrote (`absval`, `bigconst`, `bitops`, `chain`, `count`, `fact`, `fib`,
`identity`, `localmul`, `nonzero`, `pair`, `shiftlr`, `sum` — proof decorators;
`var_typed_loop`, `vardecl`, `vardecl_typed`, `vardecl_unused` — `var`), and
**every one was re-run on both backends as written and answered the same**. It
costs no build when no rule fired, which is the whole generated corpus and 74 of
the 90.

**`@refines` was the fourteenth rule gap and it was the largest single one.** The
proof-decorator rule named `@spec`/`@require`/`@ensure` and not `@refines`, which
the corpus grew when the refinement files landed — so the eleven `@refines`
examples (`absval`, `bigconst`, `bitops`, `chain`, `fact`, `identity`,
`localmul`, `nonzero`, `pair`, `shiftlr`, `sum`) were reported as "CPython still
declines it: invalid syntax (line 11)" and dropped. The rule now names all four,
and the three examples still unmeasured are the ones that declare a `struct`,
which is a DECISION and not a rule (`test_the_examples_corpus_is_mostly_measured`
asserts exactly that set now rather than a bare floor).

**2026-10-07 (`formal126-docs`): the number to the left is 7 of 51 because that
was the tree it was taken on; the tree now has a THIRD decorator.** Eleven
refinement examples (`absval`, `bigconst`, `bitops`, `chain`, `fact`, `identity`,
`localmul`, `nonzero`, `pair`, `shiftlr`, `sum`) spell
`@refines(Specs.abs64; 64)`, which is not valid Python — the `;` inside the
parentheses is a `SyntaxError` — so they were in the "CPython still declines it"
bucket until `PROOF_DECORATOR_RE` learned the name. `@refines` is the same shape
as `@spec`/`@require`/`@ensure`: read by the proof layer, invisible to the
run-time path, and `_drop_proof_decorators` already consumes its wrapped
arguments. The `NORMALISES-DIFFERLY` gate covers them exactly as it covers the
seven: the verbatim file keeps its annotation, and the two answers must agree.

**2026-10-08: the dialect set grew by the eleven `@refines(…)` examples** (`absval`,
`bigconst`, `bitops`, `chain`, `fact`, `identity`, `localmul`, `nonzero`, `pair`,
`shiftlr`, `sum`), which the proof layer added after the measurement above. They are
measured through the same verbatim-vs-normalised comparison every other rewritten
file is, so a rule that removed more than the annotation would be
`NORMALISES-DIFFERLY-<arch>` rather than a silent extra example in the tally.

## 5b. Three defects that only a LARGE-PROGRAM sweep could reach, and what each would have been filed as

Sweep 7 is the row that found them and the reason §2's rows did not is in §2's own
words: a small program has no refusal, and a rule that only fires on a refusal has
nothing to fire on. All three are in `tools/formal_metamorph.py` and all three are
the same shape — **the comparison was right about the sentence and wrong about
something the sentence POINTS AT**.

| what | measured | would have been filed as |
|---|---|---|
| `REFUSAL-DIVERGES` compared LINE NUMBERS, and six of the ten transformations move every line below the one they add | 10 of 10 `limits` programs at `--stmts 30 60`, every one the identical sentence at `line 46` and `line 51` | a backend that refuses the same program in two words |
| …and QUOTED SOURCE. The generator spells `F'v={s1} '`, `ast.unparse` spells it `f'v={s1} '`, and a twin is an AST always, and the refusal quotes the token the parser kept | 7 of 8 `fstrings` programs, every one the same construct | as above |
| a `+` in the advice sentence ("build the text with `+` once that is lowered") was folded or not according to whether `+` appeared ANYWHERE in the program | 2 of 8, and it is why the rule needs "more than one character" | as above, intermittently — which is worse, because it would have been a finding nobody could reproduce |

And one that is not a comparison at all: **every finding was written with an EMPTY
reproducer.** `main` writes `<stem>.mojo` from the program record, and `rec["text"]`
was only ever set on a normalisation failure — so all ten of the first sweep's
findings shipped with the diagnostic in `findings.json` and nothing to feed it
back in. A finding nobody can re-run is a claim, not a finding.

The fourth thing sweep 7 reached is a **verdict that did not exist**:
`CROSS-MACHINE-REFUSAL`. Every other verdict here compares two answers from ONE
backend, so a program x86-64 refused and arm64 answered agreed with itself twice
and read as `match`. 1 of 8 `slicing` programs is that shape — and §4b is what it
turned out to be.

## 4b. The one cross-machine asymmetry, and why it is not a finding

`sweep 7`'s `slicing` program: x86-64 refuses with

    build: a slice view does not fit in the frame: it needs 520 bytes and this
    function has 152 left for containers.

and arm64 builds it and answers. This is **documented and deliberate**, and the
tree says so in the place that counts: `tools/formal_fuzz.py`'s note on the
constant it imports reads "`formal/model.py::CONTAINER_BUDGET` is the smaller of
the two and the one a program has to fit to build on both machines". A program over
x86-64's budget answers on arm64 and is refused on x86-64 by design.

So the tool counts it, names it, and prints one line per program:

    cross-machine refusals that are the DOCUMENTED container-budget asymmetry,
    not findings: 1
      metamorph:4:slicing: x86_64 refused it and arm64 answered …

**Narrow on purpose.** The exemption is the message head
`formal_fuzz.FRAME_BLOB_REFUSAL_HEAD` and nothing else: a refusal about a
construct in either direction is still a `CROSS-MACHINE-REFUSAL`, or the exemption
would be a blanket one. And it is reported rather than dropped, because "how many
programs were over the budget" is a measurement of the corpus and "none" is not.

## 6. Where the ledger's numbers came from, and what would change them

Every row in §2 is reproducible from the seed and the index range:

    python3 tools/memslot.py --gb 8 --label mm -- python3 tools/formal_metamorph.py \
        -n 60 --mix calls --stmts 8 14 -j 6
    python3 tools/memslot.py --gb 8 --label mm -- python3 tools/formal_metamorph.py \
        -n 0 --examples formal/examples -j 6
    python3 tools/memslot.py --gb 8 --label mm -- python3 tools/formal_metamorph.py \
        -n 20 --mix core --stmts 8 20 -j 6

`tools/formal_metamorph.py --list-transforms` says what each transformation is FOR; `test_formal_metamorph.py` asserts that the soundness property holds over a hand-written corpus of 14 programs (one per documented rule), every generator mix, and every drivable example — and the two argument-taking examples (`twoparams`, `subscript_var`) are driven rather than silently unanswered. **The examples count in this sentence was 51 of 51 and the corpus has grown since (93 files, **all 93 drivable as of 2026-10-09 —
§0z**); the current figure is a fact about `example_corpus()` rather than about a
run, and §0/§0z/§5a/§6 hold what landed.**

**What is NOT measured here**, and is the next thing a session should do. The
first three items of the previous session's list and this list's item 1 are now
DONE (§2a and §0z respectively); these are the three that remain:

1. **Three `formal/examples` files are unmeasured, all for a `struct` body:
   `wide_recv.mojo`, `struct_point.mojo` and `struct_method.mojo`** (§2b records
   the count moving 14 → 3 when `@refines` joined the proof-decorator rule). The
   rules remove `@spec`/`@require`/`@ensure`/`@refines`, `var` and `fn` and
   nothing else, deliberately: a Python `class` body of bare annotations has no
   attributes, so `p.get_y()` reads a name that was never assigned while the
   struct's field reads `0` — a real disagreement with CPython manufactured by
   the translation rather than found by it. Giving each field an initialiser is a
   judgement about what a struct's fields are worth, not a removal of syntax. So
   the next step is a DECISION about `struct`, not another rule. (It was one file
   when this item was written; `struct_point` and `struct_method` joined the
   corpus since, which is exactly why the coverage check asks WHY a file is
   unmeasured rather than counting — §0 and §5a.)
2. **No metamorphic sweep of the stdlib.** `formal/hostmods/*.mojo` is the largest
   body of real source this backend must keep working, and a metamorphic pair over
   it needs the import machinery the fuzzer does not have. This is the largest
   remaining hole and the most expensive to close, and it is the one to pick next
   if the session can afford a build.
3. **`inline_helper` reaches 37 of the 8971 sweep-6 pairs** — the rarest transform
   by an order of magnitude, because the corpus has almost no single-`return`
   helper. `def_order` needs a run of two or more top-level definitions, which
   `core` and `lists` do not have at all (§2a's sweep 5 shows `def_order skip=20`
   on four of five mixes). Adding mixes is `formal_fuzz`'s call, not this
   ledger's; the honest reading is that **these two transforms are measured on the
   examples corpus and barely measured on the generated one**, which is the
   opposite of what §2's twenty-mix sweep implied by its tally.
# FORMAL_metamorphic_ledger: what `tools/formal_metamorph.py` has measured, and what came of it

**This is the ledger metamorphic sweeps are recorded in.** One row per sweep (corpus, seed, index range, programs, pairs, both architectures, the tally as the tool printed it), then one entry per BACKEND finding with what happened to it, and one for each defect the TOOL turned out to have — because those cost more than the backend bugs did and a metamorphic tool's own defects are invisible in a tally of passes.

`bugs/FORMAL_fuzz_ledger.md` is the differential fuzzer's ledger and the two read together: `formal_fuzz` asks "does the image answer what CPython answers", this one asks "do two builds of the same meaning answer the same". See §3 for why the second question reaches a class the first cannot.

## 0z. Status 2026-10-09 (`formal262-docs`): §6 item 1 is CLOSED — the `struct` decision is made, and the three files are driven

`normalise_mojo` now translates a `struct`, scoped to the case where a decision
is forced rather than guessed, and the examples corpus is **93 of 93 driven**
(`test_formal_metamorph.py` 62/62; the examples sweep of §2 prints no
"NOT measured" line, 0 findings, 0 `transform-invalid`/`transform-crash`, and 20
programs firing a normalising rule where it was 17). The DECISION §6 item 1 asked
for is this:

* **A field declared an INTEGER type reads `0` on this path, so the translation
  writes `0`.** `Point()` zero-initialises every field before any store, measured
  on BOTH architectures through the ORIGINAL `struct` build and on CPython through
  the twin — which is why `self.x = 0` is the meaning of `x: Int` here and not an
  invented value. `_STRUCT_ZERO_TYPE_RE` is the closed set (`Int`/`UInt` with an
  optional `8`/`16`/`32`/`64`), so the decision is one table rather than a rule
  reading the type.
* **Every other struct stays unmeasured and names `struct`.** A field whose type
  is not in that set is a value this tool will not guess at, and a struct with an
  explicit `__init__` is a construction body this tool does not model; both keep
  the old outcome (reported, never silently dropped). The coverage assertion now
  requires that NOTHING is unmeasured, so a new undrivable example fails the
  suite rather than lowering a number.
* **It is checked per file and not argued.** `example_program` sets `verbatim` for
  a struct file, so `check_pair`'s step 0 builds the file AS WRITTEN and requires
  the same answer as the twin on every backend — which is where a wrong decision
  about a field's value would be found. The three files (`wide_recv`,
  `struct_point`, `struct_method`) answer `4`/`1`/`5` on CPython and both
  architectures, original and twin alike.

**And a latent rule defect fell out of it: `FN_DECL_RE` removed `fn` without
putting `def` back.** The replacement was the indent capture alone, so `fn f(n):`
became `f(n):` — a note that fired and a file that still could not parse. It was
invisible because the only `fn` example, `wide_recv.mojo`, was unmeasured for the
`struct` reason anyway; making the struct translatable is what reached the broken
`fn`. The rule now rewrites to `def`, which is what its own coverage fixture
(`("fn g(n):…", ("fn ",), ("def g(n):",))`) always claimed and never executed,
because the fixture was only checked on the `text is None` path.

## 0. Status 2026-10-07 (`formal126-docs`): the tool's own suite was RED in five
## places on `master`, and the two that are the TOOL's are fixed at the root

`test_formal_metamorph.py` is this ledger's instrument, and on `master` it ran
5 failures in 55 tests. Three were one stale MOCK — `TheDriver._run_check_pair`
stubbed `formal_fuzz.cpython_answer` with a bare `(exit, stdout)` tuple, which
`formal_fuzz.has_oracle` stopped accepting when it grew `OracleAnswer` — and two
were the tool and its corpus:

* **A THIRTEENTH defect in a TRANSFORM, and the oracle found it.** §5's table is
  twelve; `reorder` swapped a container store past the read that observes it by
  another name — `a = o.v` then `o.v[0] = 62` moved past `w = a[0]`, printed
  `46` where CPython prints `62`. Caught on `refs:0` of `formal_fuzz`'s `refs`
  mix. It is in §5, and the NAME-level independence test could not state it: the
  shared object is not a shared name. `_function_aliases` closes it.
* **ELEVEN examples were unmeasured for ONE missing decorator name.** The
  refinement corpus's `@refines(Specs.abs64; 64)` is not valid Python — the `;`
  inside the parentheses — and the normaliser's proof-decorator rule listed
  `@spec`/`@require`/`@ensure` and not `@refines`. Named, and the eleven
  (`absval`, `bigconst`, `bitops`, `chain`, `fact`, `identity`, `localmul`,
  `nonzero`, `pair`, `shiftlr`, `sum`) are driven. The three `struct` files
  (`wide_recv`, `struct_point`, `struct_method`) stay the documented exclusion,
  and the coverage assertion now asks WHY a file is unmeasured rather than
  "all but one" — §6's second half.

The suite is 56/56 after the change. Nothing else in this file moves: no sweep
in §2 re-ran, and the tool's tally was never the thing that was wrong.

**Status 2026-10-07 (`work/formal143-docs`): the suite was RED, for five reasons, and none of them had been seen because `test_formal_metamorph.py` is in no bucket — `python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_metamorph.py` was `FAILED (failures=5)` and is now `Ran 59 tests … OK`. Three were a stale MOCK and two were real.** Read this before §2a's coverage claims, which §5's rows and §6's list below predate.

* **`reorder` was UNSOUND on an ALIASED pair, and this is the thirteenth defect in §5, not a new class.** The `refs` mix (index 0, `--stmts 8 14`) binds two names to one list (`A32 = h31.b23`) and then stores through one and reads through the other:

      A32[0] = 46        # …A32 aliases h31.b23
      w34 = A32[0]       # prints 62 in the original…
      h31.b23[0] = 62

  `reorder` swapped the store and the read. The two statements' names are disjoint (`{h31}` against `{A32, w34}`), which is all `t_reorder`'s independence test looked at, so the twin printed `46` where the original printed `62` — a real metamorphic violation manufactured by the harness, exactly the shape §5 warns about. **Fixed at the root**: `t_reorder` now merges the two statements' name sets through `_alias_classes`, a union-find over the function's direct aliasing assignments (`A32 = h31.b23`, `A35 = L20`, `A47 = A32`), before any of its conflict rules run. Only a DIRECT assignment whose value is an existing object establishes an alias; a call result is treated as fresh, and a name is merged even when the aliasing store and the use are on different paths — over-approximating can only refuse a swap. Measured: the reorder twin is sound over all 27 mixes × indexes 0-5, and the hand-written rows are `ReorderAliasing`. The control (`c = [b[0], 4]`, a fresh list) is still swappable, so the rule refuses the alias and nothing else.
* **Eleven examples were refused by CPython, and the cause was one decorator missing from the removal rule.** `@refines(Specs.factorial64; 20)` is a proof-layer annotation whose arguments are not Python at all; `normalise_mojo` removed `@spec`/`@require`/`@ensure` and not it, so every file carrying it died at line 11. Adding `refines` to `PROOF_DECORATOR_RE` moves the examples corpus from **79 of 93 driven to 90 of 93** — §6's item 3 and §2a's "before" numbers are now one corpus behind.
* **The remaining 3 unmeasured examples are the documented `struct` decision and only that.** `wide_recv.mojo` was §6 item 1's single unmeasured file; `struct_point.mojo` and `struct_method.mojo` are the other two. `test_the_examples_corpus_is_mostly_measured` asserted `driven >= len(stems) - 1`, which the new struct files broke; it now asserts the REASON instead (every unmeasured stem must be unmeasured for the `struct` decision, never for a spelling the normaliser can remove), which is the same claim and does not rot as the corpus grows.
* **Three driver tests were mocking a return shape that no longer exists** (`cpython_answer` returns `(OracleAnswer, reason)` since the `OracleAnswer` type landed, and the mock returned a bare `((0, ""), "")`), so `check_pair` read its own oracle as `not-answerable` and the three rows asserting `match`/`CROSS-MACHINE-REFUSAL` failed for a reason that had nothing to do with the tool. Updated to `F.OracleAnswer(0, "")`. That is a test defect, not a §5 tool defect, and is named here so the next reader does not go looking for a driver regression.

**What this does NOT close:** §6's four items are unchanged — the `struct` decision (now named as the 3 stems above), the stdlib sweep, the two rare transforms, and the `int_only` lower bound. Nothing here is a new SWEEP; it is the suite going from red to green with the two real defects fixed.

**Status 2026-10-07 (`work/formal160-docs`): FOUR tool defects and two stale
test expectations were red, and they are fixed. `test_formal_metamorph.py` was
55 tests with 5 failures; it is 55/55 now.** Two are `reorder` soundness holes
that §5's table did not carry, both caught by the file's own
`test_every_transform_preserves_the_meaning`:

* **An ALIAS made two names look independent.** `A32 = h31.b23` makes `A32[0]`
  and `h31.b23[0]` one memory, and `reorder` swapped `h31.b23[0] = 62` past
  `w34 = A32[0]` — the two statements mention no name in common, and the
  printed value moved 62 → 46 (generated `refs:0`). This branch's
  `Analysis.alias_closure` and `_reference_aliases` are the relation it
  consulted; the same fix's form in the merged tree is `_alias_classes`/
  `_canonical` (the Status entries above name it), a sound over-approximation
  built from assignments whose RHS is a Name/Attribute/Subscript.
* **The call-reachability rule asked only about WRITES.** `_reachable_by_a_call`
  is the names a CALL may READ OR WRITE, so `w13 = G8` swapped past
  `print(bump11(1))` — which writes `G8` — moved the printed value 32 → 33
  (generated `globals:3`). The rule now asks about reads too.

The other two are in the normaliser and the tests: `normalise_mojo` removed
`@spec`/`@require`/`@ensure` but not `@refines(Specs.factorial64; 20)`, whose
Mojo-only arguments CPython's parser refuses, so ELEVEN examples (`fact`,
`sum`, `absval`, `bitops`, `chain`, `bigconst`, `identity`, `localmul`,
`nonzero`, `pair`, `shiftlr`) were undrivable; and the driver's unit tests
mocked `cpython_answer` with a bare `(exit, stdout)` tuple, which
`oracle_answer` rejects, so three cross-machine verdict tests read
`not-answerable`. §6 item 1's "one unmeasured example" is therefore three
`struct` files now (`wide_recv`, `struct_point`, `struct_method`), which is
the documented non-goal rather than the `@refines` hole.

**Status 2026-10-13 (merging `work/formal192-docs`): the branch carried a
parallel record of the SAME six defects, so its Status section is deduped
into the entries above rather than kept as a second copy. Its one addition
to the merged tree is the read-hazard hunk itself: the merged code still
asked only about WRITES (`a.writes & reach`) when the branch was merged, and
the check is now `(a.reads | a.writes) & reach` in both directions — what the
2026-10-07 entry above describes and measured in advance (`globals:3`,
32 → 33). The branch's alias mechanism (`Analysis.alias_closure` and
`_reference_aliases`) is the parallel form of `_alias_classes`, and its
hand-written pin is covered by `ReorderAliasing`. Measured on the merged
tree: `test_formal_metamorph.py` is 62/62 (the file has grown since the 160
entry's 55), peak 0.2 GB; `test_formal_mlir_precedence.py` is 40/0.**

**Status 2026-10-13 (`work/formal402-docs`): §6 item 4 is MEASURED, and the
measurement is a sound broadening of `swap_add`'s operand predicate.** The item
asked for the remaining `int_only` decline reasons "measured rather than guessed
at". Measured they are, and the reading splits the row in two:

* one half is `int_only`-bound — a `+` operand that is a name the analysis
  cannot prove integer (a subscript, an attribute, a comprehension target, a
  string store). Broadening the OPERAND predicate cannot reach those, and the
  numbers say so: `refs` stays 2/8 and `comps` moves 2→3 and no further.
* the other half was the predicate being too NARROW about a name it HAD
  classified: `_operand_ok` accepted only an int literal or a bare name in
  `int_only`, so a `+` written as an EXPRESSION was declined even when both
  sides were provably integers. `unpack`'s `u1 * 1 + u2 * 2` is the shape and
  neither operand is a name.

So `_operand_ok` is now `Analysis.is_int_expr` — the analysis's own `_int_expr`
at the published `int_only` — and the soundness argument is unchanged (`+` is
commutative over integers; `_int_expr` declines a subscript, an attribute and
every container, so nothing whose commutativity is in doubt is admitted).
Measured over the 27 generator mixes at `--stmts 10 30`, seed `x402`, 8 programs
each, driving the transform itself rather than a predicate stand-in: **146 of
216 programs had a `swap_add` candidate before and 156 after**, on `argshape`
7→8, `comps` 2→3, `environ` 4→5, `limits` 1→4, `slicing` 2→3, `strings` 5→6,
`strmeth` 4→5 and `unpack` 3→4. `strfmt` did NOT move, and that is the useful
negative: its declines are `int_only`-bound, which is the other half of the
reading. Pinned by `test_formal_metamorph.py`'s `product_operands` program (a
`MUST_APPLY` row) and `test_an_expression_operand_is_an_int_when_its_leaves_
are` (accepted both ways, a string `+` declined); the CPython gate over all 27
mixes is what keeps the broadening sound.

## 1. The rule this ledger keeps

A row is a MEASUREMENT of a run, never a target. What makes a row worth reading is the TRANSFORM table beside it, not its tally: a run where `inline_helper` skipped every program and one where it answered 200 pairs are the same tally, and the second measured something the first did not.

The anti-rot is the per-transform table the tool prints on every run, which is why `test_formal_metamorph.py::MUST_APPLY` exists: a transformation that stops applying reports the same clean tally as one that never worked. `test_no_transform_is_measured_on_nothing` checks that the table of "must apply somewhere" and the table of transformations cannot drift apart in either direction.

## 2. Sweeps

Machine: 18-core arm64 macOS, `python3` 3.14.7. Every sweep `-j 6` and BOTH backends. Peak memory across every sweep in this file: **0.2 GB** (`tools/memslot.py --gb 8`, which kills at 8), so nothing here is within an order of magnitude of the 3-4 GB line in `doc/POLICY_memory_over_4gb.md`.

**Sweep 1** — `calls`, seed `metamorph`, indexes 0-59, `--stmts 8 14`, **600 pairs**, 265.6 s. 60 match, 0 findings. Peak 0.2 GB.
**Sweep 2** — `formal/examples`, **41 programs / 410 pairs**, 153.2 s. 41 match, 0 findings, 1 program carrying a pre-existing `DIVERGENCE` (`udivmod`, §4). Peak 0.1 GB.
**Sweep 3** — the remaining twenty mixes at 20 programs each: `core`, `lists`, `classes`, `containers`, `globals`, `generics`, `strmeth`, `signed`, `strings`, `argshape`, `slicing`, `closures`, `unpack`, `bignum`, `chains`, `loopelse`, `tryfinally`, `strfmt`, `fstrings`, `limits`, **4000 pairs**, 20 mix runs. 0 findings, 0 `transform-invalid`, 0 `transform-crash`.

Total on the tool's own sweeps: **5010 pairs over 22 corpora, both architectures**. Peak 0.2 GB.

## 2a. The second session's sweeps, and the two rules that made them worth running

The first session's §6 said the tool's reach was its problem, and named four
things. Two of them turned out to be *reachability of the analysis*, not of the
corpus, and fixing them is what §2b is about; the other two (Mojo-only syntax, an
entry point that takes arguments) were coverage holes in the examples corpus and
are `normalise_mojo` / `example_program`.

**Sweep 4** — `formal/examples`, after both: **51 programs / 510 pairs**, 108.8 s,
`-j 6`, both architectures. 51 match, 0 findings, 0 `transform-invalid`,
0 `transform-crash`, 0 `NORMALISES-*`. 1 file not measured (`wide_recv`, `struct`).
Peak 0.2 GB. **Before: 41 programs / 410 pairs.** The one `DIVERGENCE` is still
`udivmod` (§4) and is still not this ledger's.

**Sweep 5** — the five mixes the integer classification changed most: `core`,
`containers`, `argshape`, `lists`, `loopelse`, 20 programs each at
`--stmts 8 20`, **1000 pairs**, both architectures, 62-73 s per mix. 100 match,
0 findings, 0 `transform-invalid`, 0 `transform-crash`. Peak 0.2 GB. The
per-transform table is what makes this row worth reading rather than its tally:

| mix | `swap_add` before | after |
|---|---|---|
| `core` | 4 of 20 | **19 of 20** |
| `containers` | **0 of 20** | **18 of 20** |
| `argshape` | 5 of 20 | **16 of 20** |
| `lists` | 7 of 20 | **19 of 20** |
| `loopelse` | 9 of 20 | **20 of 20** |

**Sweep 6** — the soundness sweep that is NOT a build, because the property it
checks is about the transforms rather than about the backends. Seed `mm-r3`,
indexes 0-59, all 22 mixes, `--stmts 8 24`, all ten transformations:
**8971 CPython pairs, 0 `transform-invalid`.** Per transform: `if_true` 1320,
`reorder` 1320, `rename` 1314, `dead_local` 1309, `noop_loop` 1301, `swap_add`
923, `extract` 653, `def_order` 397, `extra_param` 397, `inline_helper` 37.
No build, no memslot pressure worth naming (well under 0.1 GB), and it is the
cheapest thing in this file per unit of coverage: it is what catches a defect in
a transform before any image exists, and it found the twelfth one in §5.

**Sweep 7 — the LARGE-PROGRAM sweep, and the only one that found anything.** Every
row above is `--stmts 8 20` or `8 24`. All 22 mixes at `--stmts 30 60`, 8
programs each, **1760 pairs**, both architectures, `-j 4`, 3.8-112.9 s per mix.
**0 findings, 0 `transform-invalid`, 0 `transform-crash`** — after the three
fixes in §5b, each of which was a false positive on ten programs or seven.
Peak 0.3 GB.

Three reasons this row exists and the others do not substitute for it:

* **programs are 3x the frame.** Every one of §2's programs is small, so a rule
  that is only wrong on large programs is indistinguishable from a rule that is
  right. `REFUSAL-DIVERGES` compared LINE NUMBERS, and it fired on 10 of 10
  `limits` programs here and on none of the 440 in §2's sweep 6 — because a small
  program has no refusal to quote a line from.
* **the `refused by backend` line is what makes the row readable at all.** Every
  program of `limits` and of `fstrings` is REFUSED on both machines, which the
  tally reported as `match` — so "1760 pairs, 0 findings" is 160 of those pairs
  measuring nothing, and before the line existed the screen said `match 10` and
  nothing else.
* **`CROSS-MACHINE-REFUSAL` is new** and this sweep is what reached it: 1 of 8
  `slicing` programs, where x86-64 refused a slice view for the container budget
  and arm64 built it. That one is the DOCUMENTED asymmetry (§4b), so the sweep
  reports it as a measurement rather than a finding — which is the point of the
  row: it says how often the budget is the binding constraint, and a reader can
  now see the answer instead of inferring it from a clean tally.

## 2b. 2026-10-07 (`formal112-docs`): the alias hazard in `reorder`, and the `@refines` decorator group

Two defects were found by running the file's own suite rather than by a sweep,
and both are the shape this ledger exists to record: a tool defect is invisible
in a tally, and a coverage hole reads as a clean number.

**`reorder` was unsound through an ALIAS, and CPython caught it as
`transform-invalid` before any build.** `A32 = h31.b23` binds `A32` to the same
list as `h31.b23`, so `h31.b23[0] = 62` and `w34 = A32[0]` are one cell — but the
independence test compares names as SPELLED, saw writes `{h31}` against reads
`{A32}`, and swapped them. The generated `refs:0` program printed `46` where the
original printed `62`. `_alias_groups` is the fix: an assignment whose right-hand
side is a name, an attribute or a subscript unions its target with the root of
that expression, transitively and without regard to where the assignment sits
(a conditional alias is a possible alias, and a possible alias is a refusal). The
equivalence is applied to every read/write/escape set before the comparisons, so
it can only ADD refusals. Two rows pin it: `test_reorder_refuses_a_pair_that_
aliases_through_a_binding` (every pair in that program aliases, so `reorder` must
decline the whole function) and `test_reorder_still_swaps_two_independent_
container_writes` (two DISTINCT lists must still be exchangeable, so the rule was
not made sound by refusing all memory traffic). This is §5's defect shape one
more time — the alias is the same class as the closure cell (#6) and the global
(#7), reached through a binding instead of a call.

**The examples corpus's largest unmeasured group was `@refines`.** `PROOF_
DECORATOR_RE` removed `@spec`/`@require`/`@ensure` and not `@refines`, so the
eleven examples that spell it (`absval`, `bigconst`, `bitops`, `chain`, `fact`,
`identity`, `localmul`, `nonzero`, `pair`, `shiftlr`, `sum`) were refused with
CPython's own "invalid syntax" at the decorator's line. It is the same class as
the three the rule already covers — a decorator the PROOF layer reads and the
run-time path never sees — so it goes through the same parenthesis-depth scan
(its argument list wraps and contains a `;`). Measured: the examples corpus was
**93 stems, 90 measured / 3 unmeasured** after this change, where it was 79/14
before, and all three remaining were the one documented `struct` decision
(`struct_method`, `struct_point`, `wide_recv`) — **since made and driven; §0z is
the decision and 93 of 93 is the figure it leaves.** `test_the_examples_corpus_is_
mostly_measured` asserts that no example is left unmeasured, so a future example
that cannot be driven for a NEW reason fails the suite instead of lowering a
number nobody reads.

**And three `TheDriver` rows were stale against the `OracleAnswer` type.** They
stubbed `cpython_answer` with a bare `(exit, stdout)` tuple, which `oracle_answer`
no longer recognises (it is a `NamedTuple`), so every one of them read as
`not-answerable`. Fixed in the test, not the tool: the stub now returns
`F.OracleAnswer(0, "")`, which is the same shape the real function returns.

## 3. What metamorphic testing reaches that differential testing cannot, and the measurement

`formal_fuzz` finds a miscompile only where the program PRINTS the value whose lowering is wrong. That is a property of the program, not of the backend, and it is structural: a register-allocation bug in a frame slot the program never prints is invisible to a corpus whose programs all have the same shape.

The measurement that the two questions are not the same question, and that this one is not a slower version of the other:

* **`if True:` was read as a branch by `read_before_store`'s CFG**, so a store inside a constant-true guard did not dominate the reads after it. Every such program was REFUSED — on BOTH architectures — with a sentence asserting "CPython raises UnboundLocalError for that program", which is false. Found as `TWIN-DIVERGES` on **8 of 30** programs of a `calls` sweep (one machine lowered the original and refused the twin), minimised to 12 lines, fixed at the root in `formal/model.py::_build_cfg`, with ten regression rows (six in `test_formal_read_before_store.py`, three each way, and four in `test_formal_run.py` on both backends). **The oracle would not have found it**: the program is one `formal_fuzz` would generate, and `formal_fuzz` reports a refusal as a refusal — a correct answer to "does the image compute this program", not a bug.
* **`k = -1` bound nothing in the CFG's preheader table**, so `for i in range(k)` with `k = -1` was undecidable, the loop target was treated as bound, and a read of `i` after the loop was accepted — on a program CPython refuses with `UnboundLocalError` for every probe value. Found by the same fold (`_cfg_int_literal` gained `UnaryOp('-', IntLiteral(1))`, which `_range_is_nonempty` had been folding for itself). Before/after table in `formal/model.py`'s docstring; rows `for_range_bound_decided_negative_refused` / `_positive_ok`.

## 4. The one `DIVERGENCE` in the examples sweep, and why it is not filed here

`formal/examples/udivmod.mojo` is `(n / 7) + (n % 7)` over `0`, `5`, `-5`. CPython answers `0.0`, `5.714…`, `1.285…`; both images answer `0`, `5`, `2`. `/` is INTEGER division on this path, and `n % 7` takes the sign of the divisor.

This is a real disagreement and it is **not** this tool's to file or attribute: `formal_fuzz.py` owns the differential queue with its own `KNOWN_DIVERGENCES` / `neutralise` / `blame` machinery, and this is a semantics gap in both backends rather than an x86-64 bug. So the tool reports it as `DIVERGENCE-<ARCH>` — counted, printed, named as `formal_fuzz`'s queue, and excluded from its own exit status. An earlier version reported it as a finding, which is the failure this split exists to prevent: see §5.

## 5. Defects in the TOOL, which cost more than the backend bugs and are invisible in a tally

Thirteen, all caught by the tool's own CPython gate (`CPython(P) == CPython(T)`, run on BOTH sides before any backend is asked) or by the examples/classes/closures corpora. The gate is the reason each of them is a unit-test failure rather than a filed bug. The thirteenth is §2b's alias hazard, and it is the same `reorder` family as #4-#7 reached through a binding (`A = B`) rather than a call.

| # | what | how it showed | verdict it would have produced |
|---|---|---|---|
| 1 | `rename` renamed a parameter's USES but not its `ast.arg` | 6 of 30 `calls` programs, `not-answerable` | a `NameError` twin reported as a tool result |
| 2 | `global G` read as a LOCAL (the declaration is line 1, the conflicting store line 9) | 1 `globals` program, `not-answerable` | `rename` rewriting a global's reads |
| 3 | a `DictComp` has neither `elt` nor `keywords` | 6 programs, `transform-crash` | the whole `containers` mix unmeasurable |
| 4 | `reorder` treated `print(…)` beside `print(…)` as independent | 13 programs, `transform-invalid` | **every** backend bug |
| 5 | `reorder` read `L8[0] = 31` as a statement that writes nothing | 2 `lists` programs | the same |
| 6 | `reorder` swapped `c = 9` past the call that reads a closure's cell | 1 hand-written program | the same |
| 7 | `reorder` swapped `G = 57` past a call that mutates `G` from another function | 2 of 20 `globals` | the same |
| 8 | `inline_helper` substituted parameters one at a time and CAPTURED (`f(b, 2)` into `f(a, b)`) | 4 `closures` programs | the same |
| 9 | `inline_helper` asked the PROGRAM's parent index about a fresh subtree, so no substitution happened at all | 4 `closures` programs | a twin with a raw parameter name |
| 10 | a comprehension's target was bound in the ENCLOSING function, and a PEP 750 `TemplateStr` was invisible to the "source text" check | 9 `fstrings` + hand-written corpus | `rename` renaming half a name |
| 11 | `extract` deleted a binding a nested scope captures | 7 of 20 `closures` | a printed number moving |
| 12 | `_bind_body` refused to descend into a nested `def` **except when the `def` WAS the statement**, so `global G6` inside `def bump7` was read as a declaration of the MODULE and `G6` was dropped from `module_bindings` — which is the set `reorder`'s `_reachable_by_a_call` consults | 1 of 5910 pairs in the §2a sweep 6, `stress-mm:18` of `globals` | `G6 = 9` exchanged with `print(bump9(5))`, and the printed value moved from 14 to 25 |
| 13 | `reorder` treated a container store and a read of the SAME OBJECT under another name as independent — `a = o.v` then `o.v[0] = 62` swapped past `w = a[0]` | `refs:0` of the `refs` mix, `transform-invalid` on the CPython gate; the printed value moved 62 → 46 | the transform shipping a store past the read that observes it |

Twelve is one more than the eleven above and it is the one worth reading twice,
because its two consequences pull in OPPOSITE directions and the over-approximating
one hid it: the module scope also collected `main`'s locals, which made
`_reachable_by_a_call` refuse swaps it need not refuse — a silent loss of pairs that
looked exactly like a corpus with no independent statement pairs. The
under-approximating one was the `global`, and it is the only defect in this file
that lived in the SCOPE BUILDER rather than in a transform. **A measurement that
only counts the verdicts would have seen a clean sweep.**

**Thirteen is the FIRST one the corpus reached through a shape rather than a
trivial pair**, and it is the same lesson as #12 from the other side: #4, #5, #6
and #7 are four versions of "the two statements DO interact and the name test
said they do not", and #13 is the fifth — a store and a read of one object under
two names. It is the thirteenth only because the `refs` mix is new; the class is
as old as the `lists` mix. That is the argument for keeping the corpus growing
instead of curating it: the oracle cannot see a hole in a shape the corpus does
not draw.

Plus three that were about the TARGET's representation rather than the transforms, and would have been filed as backend bugs:

* **a constructor's body is INLINED at the construction site** (`formal/build.py`), so its shape IS the construction. `if_true` / `noop_loop` / `dead_local` inside `__init__` were declined — correctly, with a message naming the construct — and the tool was calling that `TWIN-DIVERGES`. Now `_is_constructor`.
* **a method's receiver is identified by the NAME of its first parameter** (`formal/model.py::RECEIVER_PARAMETER_SPELLINGS`), so `rename` deleted it: 20 of 30 `classes` programs came out `TWIN-DIVERGES` with `C5.m15() is declared with parameters and no receiver`. The spellings are imported, not re-spelled.
* **`_loop_target_defs` / the loop-target question** — not reached; recorded here because the `if <constant>:` rule touches the same preheader machinery and a reader should know the sweep did not exercise it.

## 5a. The one place the oracle CANNOT check the tool, and the gate that can

Everything in §5 was caught by comparing the two programs on CPython. **A
NORMALISING RULE is the one thing that check cannot see**, because normalisation
moves P and T together: a rule that changed the meaning would leave the oracle
comparing a program with itself. So the rewriting is checked against the file AS
WRITTEN, by the machine — `check_pair::_normalisation` re-runs the verbatim file on
every backend and requires the same answer (`NORMALISES-DIFFERLY-<arch>`), and a
verbatim spelling that will not build is `NORMALISES-UNCOMPARABLE` rather than a
skip, because nothing then established that the removal preserved anything.

Measured: 16 of the 90 driven examples are measured in a dialect this tool
rewrote (`absval`, `bigconst`, `bitops`, `chain`, `count`, `fact`, `fib`,
`identity`, `localmul`, `nonzero`, `pair`, `shiftlr`, `sum` — proof decorators;
`var_typed_loop`, `vardecl`, `vardecl_typed`, `vardecl_unused` — `var`), and
**every one was re-run on both backends as written and answered the same**. It
costs no build when no rule fired, which is the whole generated corpus and 74 of
the 90.

**`@refines` was the fourteenth rule gap and it was the largest single one.** The
proof-decorator rule named `@spec`/`@require`/`@ensure` and not `@refines`, which
the corpus grew when the refinement files landed — so the eleven `@refines`
examples (`absval`, `bigconst`, `bitops`, `chain`, `fact`, `identity`,
`localmul`, `nonzero`, `pair`, `shiftlr`, `sum`) were reported as "CPython still
declines it: invalid syntax (line 11)" and dropped. The rule now names all four,
and the three examples still unmeasured are the ones that declare a `struct`,
which is a DECISION and not a rule (`test_the_examples_corpus_is_mostly_measured`
asserts exactly that set now rather than a bare floor).

**2026-10-07 (`formal126-docs`): the number to the left is 7 of 51 because that
was the tree it was taken on; the tree now has a THIRD decorator.** Eleven
refinement examples (`absval`, `bigconst`, `bitops`, `chain`, `fact`, `identity`,
`localmul`, `nonzero`, `pair`, `shiftlr`, `sum`) spell
`@refines(Specs.abs64; 64)`, which is not valid Python — the `;` inside the
parentheses is a `SyntaxError` — so they were in the "CPython still declines it"
bucket until `PROOF_DECORATOR_RE` learned the name. `@refines` is the same shape
as `@spec`/`@require`/`@ensure`: read by the proof layer, invisible to the
run-time path, and `_drop_proof_decorators` already consumes its wrapped
arguments. The `NORMALISES-DIFFERLY` gate covers them exactly as it covers the
seven: the verbatim file keeps its annotation, and the two answers must agree.

**2026-10-08: the dialect set grew by the eleven `@refines(…)` examples** (`absval`,
`bigconst`, `bitops`, `chain`, `fact`, `identity`, `localmul`, `nonzero`, `pair`,
`shiftlr`, `sum`), which the proof layer added after the measurement above. They are
measured through the same verbatim-vs-normalised comparison every other rewritten
file is, so a rule that removed more than the annotation would be
`NORMALISES-DIFFERLY-<arch>` rather than a silent extra example in the tally.

## 5b. Three defects that only a LARGE-PROGRAM sweep could reach, and what each would have been filed as

Sweep 7 is the row that found them and the reason §2's rows did not is in §2's own
words: a small program has no refusal, and a rule that only fires on a refusal has
nothing to fire on. All three are in `tools/formal_metamorph.py` and all three are
the same shape — **the comparison was right about the sentence and wrong about
something the sentence POINTS AT**.

| what | measured | would have been filed as |
|---|---|---|
| `REFUSAL-DIVERGES` compared LINE NUMBERS, and six of the ten transformations move every line below the one they add | 10 of 10 `limits` programs at `--stmts 30 60`, every one the identical sentence at `line 46` and `line 51` | a backend that refuses the same program in two words |
| …and QUOTED SOURCE. The generator spells `F'v={s1} '`, `ast.unparse` spells it `f'v={s1} '`, and a twin is an AST always, and the refusal quotes the token the parser kept | 7 of 8 `fstrings` programs, every one the same construct | as above |
| a `+` in the advice sentence ("build the text with `+` once that is lowered") was folded or not according to whether `+` appeared ANYWHERE in the program | 2 of 8, and it is why the rule needs "more than one character" | as above, intermittently — which is worse, because it would have been a finding nobody could reproduce |

And one that is not a comparison at all: **every finding was written with an EMPTY
reproducer.** `main` writes `<stem>.mojo` from the program record, and `rec["text"]`
was only ever set on a normalisation failure — so all ten of the first sweep's
findings shipped with the diagnostic in `findings.json` and nothing to feed it
back in. A finding nobody can re-run is a claim, not a finding.

The fourth thing sweep 7 reached is a **verdict that did not exist**:
`CROSS-MACHINE-REFUSAL`. Every other verdict here compares two answers from ONE
backend, so a program x86-64 refused and arm64 answered agreed with itself twice
and read as `match`. 1 of 8 `slicing` programs is that shape — and §4b is what it
turned out to be.

## 4b. The one cross-machine asymmetry, and why it is not a finding

`sweep 7`'s `slicing` program: x86-64 refuses with

    build: a slice view does not fit in the frame: it needs 520 bytes and this
    function has 152 left for containers.

and arm64 builds it and answers. This is **documented and deliberate**, and the
tree says so in the place that counts: `tools/formal_fuzz.py`'s note on the
constant it imports reads "`formal/model.py::CONTAINER_BUDGET` is the smaller of
the two and the one a program has to fit to build on both machines". A program over
x86-64's budget answers on arm64 and is refused on x86-64 by design.

So the tool counts it, names it, and prints one line per program:

    cross-machine refusals that are the DOCUMENTED container-budget asymmetry,
    not findings: 1
      metamorph:4:slicing: x86_64 refused it and arm64 answered …

**Narrow on purpose.** The exemption is the message head
`formal_fuzz.FRAME_BLOB_REFUSAL_HEAD` and nothing else: a refusal about a
construct in either direction is still a `CROSS-MACHINE-REFUSAL`, or the exemption
would be a blanket one. And it is reported rather than dropped, because "how many
programs were over the budget" is a measurement of the corpus and "none" is not.

## 6. Where the ledger's numbers came from, and what would change them

Every row in §2 is reproducible from the seed and the index range:

    python3 tools/memslot.py --gb 8 --label mm -- python3 tools/formal_metamorph.py \
        -n 60 --mix calls --stmts 8 14 -j 6
    python3 tools/memslot.py --gb 8 --label mm -- python3 tools/formal_metamorph.py \
        -n 0 --examples formal/examples -j 6
    python3 tools/memslot.py --gb 8 --label mm -- python3 tools/formal_metamorph.py \
        -n 20 --mix core --stmts 8 20 -j 6

`tools/formal_metamorph.py --list-transforms` says what each transformation is FOR; `test_formal_metamorph.py` asserts that the soundness property holds over a hand-written corpus of 14 programs (one per documented rule), every generator mix, and every drivable example — and the two argument-taking examples (`twoparams`, `subscript_var`) are driven rather than silently unanswered. **The examples count in this sentence was 51 of 51 and the corpus has grown since (93 files, **all 93 drivable as of 2026-10-09 —
§0z**); the current figure is a fact about `example_corpus()` rather than about a
run, and §0/§0z/§5a/§6 hold what landed.**

**What is NOT measured here**, and is the next thing a session should do. The
first three items of the previous session's list and this list's item 1 are now
DONE (§2a and §0z respectively); these are the three that remain:

1. **Three `formal/examples` files are unmeasured, all for a `struct` body:
   `wide_recv.mojo`, `struct_point.mojo` and `struct_method.mojo`** (§2b records
   the count moving 14 → 3 when `@refines` joined the proof-decorator rule). The
   rules remove `@spec`/`@require`/`@ensure`/`@refines`, `var` and `fn` and
   nothing else, deliberately: a Python `class` body of bare annotations has no
   attributes, so `p.get_y()` reads a name that was never assigned while the
   struct's field reads `0` — a real disagreement with CPython manufactured by
   the translation rather than found by it. Giving each field an initialiser is a
   judgement about what a struct's fields are worth, not a removal of syntax. So
   the next step is a DECISION about `struct`, not another rule. (It was one file
   when this item was written; `struct_point` and `struct_method` joined the
   corpus since, which is exactly why the coverage check asks WHY a file is
   unmeasured rather than counting — §0 and §5a.)
2. **No metamorphic sweep of the stdlib.** `formal/hostmods/*.mojo` is the largest
   body of real source this backend must keep working, and a metamorphic pair over
   it needs the import machinery the fuzzer does not have. This is the largest
   remaining hole and the most expensive to close, and it is the one to pick next
   if the session can afford a build.
3. **`inline_helper` reaches 37 of the 8971 sweep-6 pairs** — the rarest transform
   by an order of magnitude, because the corpus has almost no single-`return`
   helper. `def_order` needs a run of two or more top-level definitions, which
   `core` and `lists` do not have at all (§2a's sweep 5 shows `def_order skip=20`
   on four of five mixes). Adding mixes is `formal_fuzz`'s call, not this
   ledger's; the honest reading is that **these two transforms are measured on the
   examples corpus and barely measured on the generated one**, which is the
   opposite of what §2's twenty-mix sweep implied by its tally.
4. **`Analysis.int_only` is still a lower bound, and §0a has now MEASURED where
   it stops (2026-10-13).** §2a raised `swap_add` reach from 133 to 275 of 440
   programs; on this tree it reached 351 of 540, and 376 once the operand
   predicate stopped requiring a bare name or a literal (`int_only` itself did
   not move — see §0a for the census and the 12 mixes that gained). The
   remaining decline reasons, measured rather than guessed, are §0a's list: a
   `BinOp`/name/subscript/attribute operand that is not provably an int, a call
   refused on purity, and 83 programs with no `+` at all. **The advice this item
   carried — "MEASURE the remaining decline reasons as §2a did rather than guess
   at them" — is what §0a did, so read it there rather than here.**

   `work/formal402-docs` measured this item independently the same day, on a
   narrower subset (27 mixes at `--stmts 10 30`, seed `x402`: `swap_add` reach
   146 → 156 of 216 programs, with the remainder spread over `environ` 6/20,
   `unpack` 4/20, `strfmt` 3/20, `limits` 2/20 and `slicing` 7/20). Both
   numbers agree on the answer to the item's own question — the operand
   predicate was the narrow thing, and after it was widened what is left is
   operands no operand predicate can reach — so the two measurements are kept
   as two scopes of one measurement rather than as a disagreement.

## 7. What sweep 7 did NOT settle, and it is the honest end of this ledger

Sweep 7 is the largest sweep in this file — 1760 pairs at 3x the frame, both
architectures — and it found **no backend bug**. That is a result, and it is worth
being precise about what it is a result ABOUT:

* **it is a result about the shape.** Every generated program is a flat `main` with
  locals, integer arithmetic, `print`, and the occasional helper. Register
  allocation, frame layout, spill placement and stack alignment are properties of
  code with *many live ranges across calls*, and this corpus has almost no calls at
  all — `inline_helper` skipped every program of sweep 7, and `extra_param` skipped
  every program of `core`, `limits`, `lists` and `loopelse`. So "no finding" here
  is much weaker evidence about those four bug classes than the pair count suggests.
* **the one cross-machine asymmetry it reached was a budget, not a miscompile**
  (§4b), which is the more likely outcome at 3x the frame: the first thing a large
  program meets is the container budget, not a wrong value.
* **the deepest reach it has into register allocation is indirect** — `rename` and
  `swap_add` change what the allocator sees without changing the program, and they
  are the two transforms that apply to nearly every program. That is real coverage
  of slot ASSIGNMENT. It is not coverage of spilling, of callee-saved handling, or
  of anything that needs a call frame to exist.

So the next session should not read this file as "the backend is right about 10,000
pairs of the same program twice". It should read §6's item 2 — the stdlib — as the
place where the shapes this corpus does not have actually live, and it should read
`model.stack_floor_depth`'s per-architecture figure (60 frames on arm64 against
480 on x86-64, one BYTE budget over two frame sizes) as the place where a measured
asymmetry turned up on a shape the corpus does have.
