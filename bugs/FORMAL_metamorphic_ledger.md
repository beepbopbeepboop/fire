# FORMAL_metamorphic_ledger: what `tools/formal_metamorph.py` has measured, and what came of it

**This is the ledger metamorphic sweeps are recorded in.** One row per sweep (corpus, seed, index range, programs, pairs, both architectures, the tally as the tool printed it), then one entry per BACKEND finding with what happened to it, and one for each defect the TOOL turned out to have — because those cost more than the backend bugs did and a metamorphic tool's own defects are invisible in a tally of passes.

`bugs/FORMAL_fuzz_ledger.md` is the differential fuzzer's ledger and the two read together: `formal_fuzz` asks "does the image answer what CPython answers", this one asks "do two builds of the same meaning answer the same". See §3 for why the second question reaches a class the first cannot.

## 1. The rule this ledger keeps

A row is a MEASUREMENT of a run, never a target. What makes a row worth reading is the TRANSFORM table beside it, not its tally: a run where `inline_helper` skipped every program and one where it answered 200 pairs are the same tally, and the second measured something the first did not.

The anti-rot is the per-transform table the tool prints on every run, which is why `test_formal_metamorph.py::MUST_APPLY` exists: a transformation that stops applying reports the same clean tally as one that never worked. `test_no_transform_is_measured_on_nothing` checks that the table of "must apply somewhere" and the table of transformations cannot drift apart in either direction.

## 2. Sweeps

Machine: 18-core arm64 macOS, `python3` 3.14.7. Every sweep `-j 6` and BOTH backends. Peak memory across every sweep in this file: **0.2 GB** (`tools/memslot.py --gb 8`, which kills at 8), so nothing here is within an order of magnitude of the 3-4 GB line in `bugs/PERF_memory_over_4gb_is_a_bug.md`.

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

## 3. What metamorphic testing reaches that differential testing cannot, and the measurement

`formal_fuzz` finds a miscompile only where the program PRINTS the value whose lowering is wrong. That is a property of the program, not of the backend, and it is structural: a register-allocation bug in a frame slot the program never prints is invisible to a corpus whose programs all have the same shape.

The measurement that the two questions are not the same question, and that this one is not a slower version of the other:

* **`if True:` was read as a branch by `read_before_store`'s CFG**, so a store inside a constant-true guard did not dominate the reads after it. Every such program was REFUSED — on BOTH architectures — with a sentence asserting "CPython raises UnboundLocalError for that program", which is false. Found as `TWIN-DIVERGES` on **8 of 30** programs of a `calls` sweep (one machine lowered the original and refused the twin), minimised to 12 lines, fixed at the root in `formal/model.py::_build_cfg`, with ten regression rows (six in `test_formal_read_before_store.py`, three each way, and four in `test_formal_run.py` on both backends). **The oracle would not have found it**: the program is one `formal_fuzz` would generate, and `formal_fuzz` reports a refusal as a refusal — a correct answer to "does the image compute this program", not a bug.
* **`k = -1` bound nothing in the CFG's preheader table**, so `for i in range(k)` with `k = -1` was undecidable, the loop target was treated as bound, and a read of `i` after the loop was accepted — on a program CPython refuses with `UnboundLocalError` for every probe value. Found by the same fold (`_cfg_int_literal` gained `UnaryOp('-', IntLiteral(1))`, which `_range_is_nonempty` had been folding for itself). Before/after table in `formal/model.py`'s docstring; rows `for_range_bound_decided_negative_refused` / `_positive_ok`.

## 4. The one `DIVERGENCE` in the examples sweep, and why it is not filed here

`formal/examples/udivmod.mojo` is `(n / 7) + (n % 7)` over `0`, `5`, `-5`. CPython answers `0.0`, `5.714…`, `1.285…`; both images answer `0`, `5`, `2`. `/` is INTEGER division on this path, and `n % 7` takes the sign of the divisor.

This is a real disagreement and it is **not** this tool's to file or attribute: `formal_fuzz.py` owns the differential queue with its own `KNOWN_DIVERGENCES` / `neutralise` / `blame` machinery, and this is a semantics gap in both backends rather than an x86-64 bug. So the tool reports it as `DIVERGENCE-<ARCH>` — counted, printed, named as `formal_fuzz`'s queue, and excluded from its own exit status. An earlier version reported it as a finding, which is the failure this split exists to prevent: see §5.

## 5. Defects in the TOOL, which cost more than the backend bugs and are invisible in a tally

Twelve, all caught by the tool's own CPython gate (`CPython(P) == CPython(T)`, run on BOTH sides before any backend is asked) or by the examples/classes/closures corpora. The gate is the reason each of them is a unit-test failure rather than a filed bug.

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

Twelve is one more than the eleven above and it is the one worth reading twice,
because its two consequences pull in OPPOSITE directions and the over-approximating
one hid it: the module scope also collected `main`'s locals, which made
`_reachable_by_a_call` refuse swaps it need not refuse — a silent loss of pairs that
looked exactly like a corpus with no independent statement pairs. The
under-approximating one was the `global`, and it is the only defect in this file
that lived in the SCOPE BUILDER rather than in a transform. **A measurement that
only counts the verdicts would have seen a clean sweep.**

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

Measured: 7 of the 51 examples are measured in a dialect this tool rewrote
(`count`, `fact`, `fib`, `sum` — proof decorators; `vardecl`, `vardecl_typed`,
`vardecl_unused` — `var`), and **all 7 were re-run on both backends as written and
answered the same**. It costs no build when no rule fired, which is the whole
generated corpus and 45 of the 52 examples.

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

`tools/formal_metamorph.py --list-transforms` says what each transformation is FOR; `test_formal_metamorph.py` asserts that the soundness property holds over a hand-written corpus of 14 programs (one per documented rule), every generator mix, and every drivable example — and now that **51 of the 51** examples have a CPython oracle, which is what makes the two argument-taking examples (`twoparams`, `subscript_var`) part of the property rather than silently unanswered.

**What is NOT measured here**, and is the next thing a session should do. The
first three items of the previous session's list are now DONE and are recorded in
§2a; these are the four that remain:

1. **One `formal/examples` file is unmeasured: `wide_recv.mojo`**, for its
   `struct Point:`. The rules remove `@spec`/`@require`/`@ensure`, `var` and `fn`
   and nothing else, deliberately: a Python `class` body of bare annotations has no
   attributes, so `p.get_y()` reads a name that was never assigned while the
   struct's field reads `0` — a real disagreement with CPython manufactured by the
   translation rather than found by it. Giving each field an initialiser is a
   judgement about what a struct's fields are worth, not a removal of syntax. So
   the next step is a DECISION about `struct`, not another rule.
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
4. **`Analysis.int_only` is still a lower bound, and where it now stops is not
   written down.** §2a raised `swap_add` reach from 133 to 275 of 440 programs, so
   the four questions it lacked were worth 142 programs — and the remaining 165 are
   spread over `environ` (6/20), `unpack` (4/20), `strfmt` (3/20), `limits` (2/20)
   and `slicing` (7/20), which are now the mixes to look at. A future session
   should MEASURE the remaining decline reasons as §2a did rather than guess at
   them; that is the one piece of advice here this file has to earn twice.

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
`bugs/FORMAL_the_stack_floor_budget_is_in_bytes_so_x86_64_allows_8x_the_recursion_depth_arm64_does.md`
as the place where a measured asymmetry turned up on a shape the corpus does have.