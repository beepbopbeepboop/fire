# 18 of 52 `formal/examples` have no accepted Lean proof on this tree, and `test_formal.py`'s `EXPECTED_FAILURES` names 7 of them

**Area:** FORMAL, arm64 — the proof layer over `formal/examples/*.mojo`.
**Found 2026-10-05 on `work/formal30-proof-regression`** while seeding the
baseline for the proof-regression ratchet, and **pre-existing**: every row below
is measured on this tree's own bytes, and three of them were re-measured
through `fire.py build --formal` (the driver's own path, not this tool's) to
make sure the instrument was not inventing them.
**Status: NOT FIXED, and deliberately not marked either.** The next step is
below and it is per-family, not a one-line edit.

## What was run

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label census-seed -- \
      python3 -u tools/formal_proof_census.py --write-baseline
52 measured, 0 kept from the old baseline
== formal proof census, arm64: 52 examples
   52 examples: 34 of them reach a proof Lean accepted, …
   proved           34
   lean-rejected    12
   refused           4
   too-large         2   <- not a verdict on the proof
```

Every row is `formal.build.compile_formal(prove=True, check=True)` — the call
`fire.py build --formal` makes — through `formal/lean.py::run_lean`'s bounds.
The committed record is `tools/formal_proof_census_baseline.json`, one row per
example with its status, its reason, its `sorry` count, its
`native_decide`/`bv_decide` site count and its timings; the instrument is
`tools/formal_proof_census.py` and the corpus-wide discussion is
`bugs/FORMAL_proof_coverage_census_2026-10-03.md` §0.8.

**Three of these were checked a second way**, through the driver and not
through the census, because "the tool says so" is not a finding:

```console
$ python3 fire.py build --formal -o .tmp/sum.aout --backend=arm64 formal/examples/sum.mojo
… sum_proof.lean:2880:16: error: Tactic `rfl` failed: …            # exit 1
$ python3 fire.py build --formal -o .tmp/either.aout --backend=arm64 formal/examples/either.mojo
either_proof.lean:2600:8: error: (kernel) excessive memory consumption detected   # exit 1
$ python3 fire.py build --formal -o .tmp/udivmod.aout --backend=arm64 formal/examples/udivmod.mojo
build: universal theorem: 2 calls this walk cannot follow (0x100000450 -> …)      # exit 1
$ python3 fire.py build --formal -o .tmp/ret42.aout --backend=arm64 formal/examples/ret42.mojo
                                                                      # exit 0
```

`test_formal.py`'s `main` splits a failed example into `KNOWN-GAP` (named in
`EXPECTED_FAILURES`) and `FAIL` (not named), and only the second counts. So on
this tree the `formal` suite job reports **11 `FAIL`s it has never been told
about**.

## The 18, by family, and the 11 that are undeclared

`EXPECTED_FAILURES` has seven entries: `count`, `countdown`, `fib`, `pow2`,
`subscript_var`, `wge`, `wide_recv`.

| # | example | status | the site it stops at | declared? | whose |
|---:|---|---|---|---|---|
| 1 | `fact` | `lean-rejected` | `fact_proof.lean:2880:16: Tactic 'rfl' failed` — the return-frame read `mem_read_u64 (mem_write_u64 … (st.sp - …)) (st.sp - 8)` | **no** | the family of #2, #3, #6, #7 |
| 2 | `sqsum` | `lean-rejected` | `sqsum_proof.lean:3250:16`, the same goal | **no** | as #1 |
| 3 | `sum` | `lean-rejected` | `sum_proof.lean:2880:16`, the same goal | **no** | as #1 |
| 4 | `sgt8` | **PASS (2026-10-05)** | was `lean-rejected` on `sgt8_proof.lean:2332:41: unsolved goals n : UInt64 …` — a narrow typed parameter's truncation with no range hypothesis on the theorem, so Lean refused the file with no `sorry` in it. The universal theorem now carries `nw : n < 128` and the truncation discharges against it; 0 admitted `sorry`. Pinned by `test_formal_call_proof_gen.py::TestANarrowTypedParameterGetsItsRange`. Note the obligation is now spelled `t32s (t32u (t8s n))` — the extra `t32u` is the 32-bit intermediate of `SXTB`-then-`SXTW` — so the `t32s (t8s n)` this row used to quote no longer matches the generator's text | **n/a — fixed** | — |
| 5 | `sle8` | **PASS (2026-10-05)** | as #4; the obligation was byte-identical to #4's | **n/a — fixed** | — |
| 6 | `ug8` | **PASS (2026-10-05)** | as #4, and its obligation is the different `t8u n = n` entirely | **n/a — fixed** | — |
| 7 | `both` | `too-large` | `both_proof.lean:2600:8: (kernel) excessive memory consumption detected` | **no** | Lean's own `-M`, not the proof |
| 8 | `either` | `too-large` | `either_proof.lean:2600:8` — **the same line as #7** | **no** | as #7 |
| 9 | `sum_range` | `lean-rejected` | `sum_range_proof.lean:3136:175: unsolved goals s : Arm64State … h : mem_read_u64 s.mem (s.sp + …)` | **no** | `FORMAL_a_conditions_operand_read_through_an_earlier_stores_slot.md` |
| 10 | `udivmod` | `refused` (generate) | `universal theorem: 2 calls this walk cannot follow (0x100000450 -> 0x1000004ec (opaque), 0x1000004bc -> 0x1000004ec (opaque))` | **no** | `FORMAL_arm64_the_universal_theorem_cannot_follow_a_call_into_the_same_image.md` |
| 11 | `floordiv` | `refused` (generate) | the same universal-theorem refusal, two call sites | **no** | as #10 |
| — | `count` | `lean-rejected` | `count_proof.lean:2587:16`, the #1 goal | yes | `FORMAL_three_examples_fail_their_proofs_on_master.md` |
| — | `pow2` | `lean-rejected` | `pow2_proof.lean:2880:16`, the #1 goal | yes | as above |
| — | `countdown` | `lean-rejected`, **2 holes** | `countdown_proof.lean:61:57: ⊢ (if sKey 0 < sKey (UInt64.ofNat m) then 1 else 0) = if 0 < UInt64…` | yes | `CODEGEN_arm64_cmp_flags_and_loop_signedness.md` §Still open 3 |
| — | `wge` | `lean-rejected`, **1 hole** | `wge_proof.lean:61:57: ⊢ (if sKey 1 ≤ sKey (UInt64.ofNat m) then 1 else 0) = …` | yes | as above |
| — | `fib` | `lean-rejected` | `fib_proof.lean:41:71: case pos n : UInt64 … (if sKey n ≤ sKey 1 then (some …))` | yes | tree-recursion `FrameOk` (the doc's own reason) |
| — | `subscript_var` | `refused` (generate) | `model: a ListExpr has no value in the semantic model` | yes | the representation work |
| — | `wide_recv` | `refused` (generate) | `model: a struct field read has no value in the semantic model` | yes | `FORMAL_wide_recv_model_has_no_domain_for_a_struct.md` |

**Three families, and two of them are one subject each.** The
`Tactic 'rfl' failed` rows (#1, #2, #3 and the two declared ones) are the
epilogue's `x30` read through a materialised address, which
`bugs/FORMAL_three_examples_fail_their_proofs_on_master.md` diagnosed and which
is claimed by that doc's write set. The narrow-typed-parameter rows (#4, #5, #6)
are the `t32s (t8s n) = n` obligation and have a doc of their own. The
universal-theorem refusals (#10, #11) are the per-function CFG walk's inability
to follow a call into the same image, also with a doc. **`both`/`either` (#7,
#8) are the odd ones out and the most interesting**: the identical site line in
two unrelated programs says this is Lean's memory ceiling meeting a shared
library lemma rather than anything in either example, and it is recorded as
`too-large`, which is explicitly **not a verdict on the proof** — so it is not
something a reader should take as "the proof is wrong".

**The `sorry` column is a separate reading and it is small.** Three of the
rejected proofs admit holes — `countdown` 2, `sum_range` 1, `wge` 1 — and every
`proved` example admits **zero** holes and zero admitted host contracts. So the
34 green rows are green in the strong sense, and the three hole-bearing rows are
all already declared.

## Next step

Per family, and in this order:

1. **`fact`, `sqsum`, `sum` (#1–#3).** These are the same goal as the two
   declared ones, so whoever closes `count`/`pow2` closes three more rows for
   free. Nothing to do until then but **not to mark them**: `expect` forgives
   `FAIL`, so marking them would put a green in the suite over a proof that does
   not check. If they must be declared to get `formal` green, each entry needs
   its measured reason, not "same as count".
2. **`sgt8`, `sle8`, `ug8` (#4–#6)** are `FORMAL_arm64_a_narrow_typed_-
   parameter_makes_the_universal_contract_false.md`'s, and that doc is claimed.
   Check its claim before doing anything here.
3. **`floordiv`, `udivmod` (#10, #11)** generate no proof at all, so they cannot
   be fixed by a tactic — `FORMAL_arm64_the_universal_theorem_cannot_follow_a_
   call_into_the_same_image.md` says the fix is a return-address map in the
   machine framework. They are also the two rows whose status is decided before
   Lean runs, so they cost nothing to keep re-checking.
4. **`both`, `either` (#7, #8)** need a decision about Lean's ceiling, not about
   the proof. `formal/lean.py` sets `LEAN_MEMORY_MB = 6144` for one generated
   proof and argues in its own comment that the project's 4 GB line cannot be
   enforced by capping Lean. So the honest options are to raise the ceiling for
   these two and record what they cost, or to record them as *too large for the
   checker* and stop reading them as failures. **What must not happen is marking
   them `EXPECTED_FAILURES` without saying which of the two it is**, because
   `(kernel) excessive memory consumption` is not a verdict and
   `test_formal.py`'s own comment says a `KNOWN-GAP` is "known unproven".
5. **`sum_range` (#9)** has a doc and a claim; check it.

## Why this is filed and not fixed here

`test_formal.py` is another area, and the fix is eleven separate judgements
about eleven different proofs. The ratchet
(`tools/formal_proof_census.py`, `formal-proof-census` in `tools/suite.py`) now
makes this exact question cheap to ask on every gate: it prints the per-example
status table and fails when one of these rows gets worse, so the list above is a
starting measurement rather than a thing that has to be re-derived by hand.
## Status, 2026-10-05 (`formal31-3`): item 4's DECISION is taken, and the two
## tools that answer the question now answer it the same way

Item 4 said the honest options are *"to raise the ceiling for these two and
record what they cost, or to record them as too large for the checker and stop
reading them as failures"*, and that *"what must not happen is marking them
`EXPECTED_FAILURES` without saying which of the two it is"*.

**The decision is the second option, and nothing is marked.** The first is
already measured false and `formal/lean.py`'s own comment on `LEAN_MEMORY_MB`
says why in as many words: capping Lean at the project's 4 GB line is not paying
the debt, it is breaking the build (with `-M 4096` the `lib/ProofLib.lean` build
dies with exactly this sentence), so at some size a proof stops being CHECKED
and the only true statement is "the checker ran out". `both` and `either` are at
that size, and there is no budget that would make them cheap.

### The defect was a DISAGREEMENT, not a missing marker

`tools/formal_proof_census.py` had it right and had had it for a while: its
`NOT_A_VERDICT` class is `{"too-large", "bound-exceeded"}`, its rank table gives
both the same rank on purpose, and its docstring says the number is the absence
of a measurement. **`test_formal.py` had no such class** — three tags, `PASS` /
`KNOWN-GAP` / `FAIL`, so `both` and `either` were `FAIL` in the suite and
`too-large` in the census for one sentence, which is the disagreement this
document's §4 is really about and not the marking it is phrased as.

**And the sentence had TWO readers.** `tools/formal_proof_census.py` carried its
own `_LEAN_MEMORY_RE`; nothing in `formal/` knew the phrase. `formal/lean.py` is
the module that SETS `-M`, so it is now the only place that can say both halves
of the claim — that the sentence is a bound firing and that the bound is ours —
through `lean_refused_on_its_own_memory_ceiling(text)`, which returns the LINE
Lean said rather than a boolean, so a caller prints the message instead of
paraphrasing it. The census's copy is deleted and it asks that function.

### What landed

  * `formal/lean.py::LEAN_MEMORY_REFUSAL_RE` and
    `lean_refused_on_its_own_memory_ceiling`.
  * `tools/formal_proof_census.py::_classify_failure` asks it; its own regex is
    gone. Its `NOT_A_VERDICT` and its ranks are unchanged, so the committed
    `formal_proof_census_baseline.json` reads exactly as it did.
  * **`test_formal.py` grows a FOURTH tag, `TOO-LARGE`**, reported on its own
    line of the summary and NOT inside `FAIL`. It is deliberately not
    `KNOWN-GAP` either, and `EXPECTED_FAILURES`'s own comment now says why:
    "known unproven" is a claim about the proof, and the whole content of this
    class is that nobody has one — plus the practical half, which is that Lean
    is not run at all for a stem expected to fail, so a ceiling firing on a
    marked stem is not something the runner could even observe.
  * The decision was lifted out of the `concurrent.futures` loop into a pure
    `test_formal.py::classify_stem(stem, passed, detail, expected_failures)`,
    because the alternative is that the only reader of this question in that file
    cannot be reached by anything — which is why `test_formal_proof_census.py`
    could test the census tool's version of it and not the runner's.

**The tests are `test_formal_proof_census.py`'s new
`TestRunnerClassification`, five rows and no Lean run at all** (54 tests, 0
failures; 49 before): a pass, a rejection, a marked stem — where the marker wins
over a ceiling, with the reason — both spellings of the ceiling classified
`TOO-LARGE`, and **the row that is the point: the two readers are asked the same
question about the same three sentences and must agree.** That last row is what
fails if either grows its own copy of the regex, which is cheaper than finding
out from a suite that reports a correct proof as wrong because the checker gave
up.

### What is NOT done here, and whose it is

Items 1, 2 and 3 are **other work** and were not touched: `fact`, `sqsum`,
`sum` are `FORMAL_three_examples_fail_their_proofs_on_master.md`'s, and they
still fail on the same epilogue `x30` read — re-measured 2026-10-05 as
`PASS=4 KNOWN-GAP=0 FAIL=3 TOO-LARGE=0` over `sgt8 sle8 ug8 n8 fact sqsum sum`,
i.e. the four narrow-parameter stems PASS and those three FAIL. `floordiv`,
`udivmod` are `FORMAL_arm64_the_universal_theorem_cannot_follow_a_call_into_the_
same_image.md`'s; `sum_range` is
`FORMAL_a_conditions_operand_read_through_an_earlier_stores_slot.md`'s.

**Items 4, 5 and 6 are no longer anybody's, because they are no longer broken.**
They were a narrow typed parameter's truncation reaching the kernel with no range
hypothesis on the theorem — `def sgt8(n: Int8)` narrowing the incoming word and
the CFG walk then asking Lean for a round trip that is FALSE over the theorem's
unconstrained `n`. The fix put `nw : n < 128` on the universal theorem and the
truncation now discharges against it. **The document that owned this is deleted,
which is why the reasoning is written out in the table above instead of cited:**
a citation of a deleted document survives its subject, and nothing reported that
these rows had stopped being true — the gap
`tools/dangling_doc_refs.py` does not cover, since its ratchet counts citations
rather than checking them. `bugs/FORMAL_a_surviving_citation_is_not_checked.md`
is that gap's document.

**And `test_formal.py` is one of the eight Lean-checking formal gate tests that
are `disabled=`,** so the four re-measurements above were taken by running it
directly rather than by a gate, and the integration run over the whole corpus
belongs to whoever re-enables that job.
