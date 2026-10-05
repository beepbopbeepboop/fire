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
| 4 | `sgt8` | `lean-rejected` | `sgt8_proof.lean:2332:41: unsolved goals n : UInt64 …` — a narrow-typed-parameter round trip | **no** | `FORMAL_arm64_a_narrow_typed_parameter_makes_the_universal_contract_false.md` |
| 5 | `sle8` | `lean-rejected` | `sle8_proof.lean:2332:41`, byte-identical to #4's goal | **no** | as #4 |
| 6 | `ug8` | `lean-rejected` | `ug8_proof.lean:2212:41`, the same family | **no** | as #4 |
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