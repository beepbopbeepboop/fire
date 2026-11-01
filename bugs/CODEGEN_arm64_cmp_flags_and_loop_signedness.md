## Status (2026-11-01, round 2 — PARTIAL: the `_go` model block now elaborates; the proof's own callers still do not)

**Landed (commit on `work/bug-codegen-arm64-cmp-flags-and-loop-sig-7981`):**

- The dec-while `_go` block that `3dbec27a6` introduced did NOT typecheck. Both
  theorems failed with `simp made no progress`: `simp [h]` never unfolds the
  `def`, and `simp [h, hm]` cannot turn `¬ n < 2^63` into a fact from
  `2^63 ≤ n`. The text checks in `TestDecWhileSignedModelRegression` could not see
  this, which is why the commit looked right. Reproduced standalone with
  `lean` on the bare block (seconds, no ProofLib). Fixed in
  `formal/arm64_proof_gen.py::_gen_go`: `simp [{f}_go, h]` for the zero lemma;
  `have h' : ¬ n < 2^63 := by omega` then `simp [{f}_go, h']` for the neg lemma.
  The corrected block typechecks standalone.
- `test_formal_call_proof_gen.py::TestDecWhileSignedModelRegression.test_go_block_elaborates_in_lean`
  runs `lean` on the emitted block (skips if `lean` is absent). It fails on the
  pre-fix text and passes now.

**Measured this round:** `python3 -m unittest test_formal_call_proof_gen.TestDecWhileSignedModelRegression`
→ 4 OK. The whole file → 222 run, 14 skipped, 1 ERROR: `TestStepLemmasCoverTheExecutableRegionOnly`
`setUpClass` `KeyError: 4294970372` in `_trap_terminating`. Reproduced identically on
the baseline `ff1c26d3f`, so it is NOT this change; it is the existing
`bugs/formal/FORMAL_call_proofgen_red_on_head.md`.

**Still open (the Lean proof is not yet correct for the signed model):**

1. The emitted `countdown_go_zero` now carries `(h : n < 2^63)`, but its callers
   still supply no hypothesis. Each must be given the sign fact, or the
   conditional rewrite is never applied and the leaf is left unsolved:
   - emitted proof, `simp [mojo, countdown_go_zero]` in `(by intro a _; …)` (the
     exit-x0 leaf of the countdown machine loop), and at the CFG terminal
     `simp [hx0f_*, mojo, countdown_go_zero]`;
   - `_gen_dec_while_block`'s template: `simp [@FN@_go_zero, hz]` (the `hz` branch,
     where `m % S = 0` discharges `0 < 2^63`) and `simp [@FN@_go_zero]` at the end
     of the step case, where the sign fact is NOT available — that one needs the
     `m % 2^64 < 2^63` split.
2. `cond_val` in the same template is stated as `evalExpr ≠ 0 ↔ m % S ≠ 0`. That
   is false for `m % S ≥ 2^63`: `pred_iff` now makes the predicate false there, so
   the left side is `0` while the right side is `true`. It must become
   `… ↔ (m % S ≠ 0 ∧ m % S < 2^63)` (or equivalent), and `prog_correct` needs the
   third case `m % 2^64 ≥ 2^63`: one `runF_while_false` step plus the identity,
   as the planning entry below describes.
3. Not verified: the whole countdown proof, `wdiff` (the canary — its `NE` model
   is unchanged, but it is not re-run this round), and `countdown`/`wge` stay in
   `EXPECTED_FAILURES`.

**Next step:** fix item 1's two lemma-call sites and item 2's `cond_val`
statement, verify the template with `lean` on a copy of the generated proof
(under `memslot`, one run, not the full `test_formal.py`), then add the third
`prog_correct` case.

## Status (2026-11-01 — PLANNING ROUND: the Lean half cannot be verified by a light worker on this machine; the guide below is what the next round executes)

**Measured this round (a real run, not carried forward):**

```
$ python3 tools/memslot.py --gb 8 --label formal-baseline -- python3 test_formal.py -j 1 countdown wdiff wge
  [1/3] KNOWN-GAP  countdown  build/proof failed: lean exceeded 1500s CPU (RLIMIT_CPU) — NOT a verdict
  [2/3] FAIL       wdiff      same
  [3/3] KNOWN-GAP  wge        same
Results for arm64 formal proofs: PASS=0 KNOWN-GAP=2 FAIL=1
real 14m45s   user 30m56s   peak 5.9 GB (ceiling 8.0 GB)
```

So `wdiff` — the canary this document says passes, and which must keep passing
through any model change — does not finish inside the per-proof CPU limit on
this tree. `lib/ProofLib.olean` (54 MB, 11:59) is newer than `ProofLib.lean`
(11:58), so this is not a stale-olean artifact I can see. Whether it is a
regression since the 2026-10-01 `PASS=39` measurement, or a change in the
machine, was NOT investigated. Until one `wdiff` check finishes inside its
limit, no change to `_go` or `pred_iff` can be verified by any quick test.

**Decision for the next round** (both are real work; (a) is the prerequisite):

- (a) Find what Lean spends its CPU on in `wdiff_proof.lean` (the candidates are the
  `simp`/`grind` closers in the ProofLib lemmas it pulls in), make it finish, and
  re-measure. Only then is the signed-model work below checkable.
- (b) If (a) is not tractable, run the three proofs once on the integrator with the
  CPU limit raised, to get true costs before choosing the model work's shape.

**Call-site inventory** (`grep -n _go_zero formal/*.py`, this tree). Every site the
signed `_go` model touches:

- `formal/arm64_proof_gen.py:2331` and `:2350` — the `{f}_go_zero : ∀ n, {f}_go n = 0`
  theorem. `:2331` is the dec-while arm of `_gen_go` (2325–2336) and is the one to
  change; `:2350` is the dec1 arm and must keep its own statement.
- `:2994` (`_go_simp_lemmas`, dec-while) — a NAME in the terminal simp set; the
  name stays, its statement changes.
- `:6315` and `:6417` in `_gen_countdown_loop` (the machine loop's exit-x0 leaf and
  its `hcondDone` closer) — `simp [mojo, go_zero]` is valid only below 2^63 and
  needs the `by_cases` split described in Still-open-3 item 3.
- `:8702` in `_gen_universal_e2e_cfg` — terminal value flow; same signed split.
- `:11519` and `:11570` in `_gen_dec_while_block` (`prog_correct`'s base and step
  cases) — the step needs the `m % 2^64 ≥ 2^63` case: one `runF_while_false` step
  and the identity.
- `:11607` — the `gozero` name binding.

**Not affected, do not touch:** `:2251`, `:2263`, `:2987`, `:6976` are
`{f}_loop_go_zero` of the RANGE loop (`_gen_range_loop_model`), a different model.

**The Lean statements to write first** (structure before soundness, FORMAL.md §11.3):

```
def {f}_go (m : Nat) : UInt64 :=
  if m < 9223372036854775808 then 0 else UInt64.ofNat m
theorem {f}_go_zero (m : Nat) (h : m < 9223372036854775808) : {f}_go m = 0
theorem {f}_go_neg (m : Nat) (h : 9223372036854775808 ≤ m)
    (hm : m < 18446744073709551616) : {f}_go m = UInt64.ofNat m
```

`prog_correct` gains the third case `m % 2^64 ≥ 2^63`. `eval_eq_mojo` must then
conclude `mojo n = n` for a negative `n` through `go (n.toNat % 2^64)` and
`{f}_go_neg`, not through the old unconditional `go_zero`. The sorry budget for any
leaf left open must be stated in the commit. `test_formal.py`'s `EXPECTED_FAILURES`
entries for `countdown` and `wge` stay until those proofs actually pass, and are then
dropped (anti-rot).

**Tests that prove it, in order:**

1. A generator-text test in `test_formal_call_proof_gen.py`: the dec-while block emits
   `{f}_go_zero` WITH its `< 2^63` hypothesis and emits `{f}_go_neg`. No Lean. It fails
   before the change and passes after.
2. `test_formal.py wdiff` — must stay PASS. It is the canary that the change did not
   leak into the unsigned `NE` case. (Blocked until item (a) above.)
3. `test_formal.py countdown wge` — KNOWN-GAP may flip to PASS only when the proofs are
   complete; the `EXPECTED_FAILURES` entries are then removed.

## Status (2026-10-04 — the CFG leaves are NAMED and the census is a measurement; `Still open 3` below is unchanged)

Every `sorry` the CFG walk can emit now carries the name of the site that emits
it (`formal/arm64_proof_gen.py`'s `CFG_LEAF_SITES`), and the two documents that
used to enumerate them by line number had already disagreed — §7 row 7 of
`FORMAL.md` said **seven**, the trust audit of 2026-10-04 said **eight**. Both
were reading a list nobody had written down. That is fixed; §7 row 7 now names
the registry.

**The census over the corpus, which is what the 2026-10-01 entry above could not
give.** 47 of `formal/examples`' 50 files generate an arm64 proof (`subscript_var`
and `wide_recv` are refused by the model, and `sum_range` raised
`ValueError: unsupported cbz taken continuation to 0x100000330` — that last one
was the GENERATION refusal and is FIXED: a `for`-range loop lowers with the test
at the bottom of its body, so its back edge is a conditional branch, and the
loop-discovery scan only asked the unconditional-`b` question; commit `cbf00b9f`
teaches it the conditional arm and adds `while_lt_exit_contract_bottom` to
`lib/ProofLib.lean`. `sum_range` is in the census below on that basis). Over
those 47:

| site | leaves reached | admits (measured by stripping the fallback and reading Lean) |
|---|---|---|
| `walk-terminal` | 324 | 0, over `identity` (4), `udivmod`/`threevar`/`bitops` (4 each), `ifonly` (8), `absval` (8), `sign` (12) |
| `runs-cbz-condition` | 36 | **2 of 6 in `count`** — a branch whose tested register is a spill read whose frame address the SP trackers under-counted by the `sh` bit of the 128 KiB frame (`formal/arm64_proof_gen.py::_addsub_imm_bytes`, now fixed; `fact`/`sum`/`sqsum`/`pow2` are green and `count` still admits for the `x30` return-frame read it is declared on) |
| `runs-ret-x0`, `runs-ret-x30`, `runs-ret-frame-ok-window` | 12 each | 0 in `count` |
| `runs-bl-step` | 7 | 0 in `count` |
| `dec-while-back-edge-decrement`, `-frame-slot` | 12 each | 0 in `wdiff` |
| `loop-cond-flag`, `loop-cond-step` | 3 each | 0 in `wdiff` |
| the five `range-loop-*` sites | 0 | unreachable in this corpus |

`wdiff` with **all fourteen** of its leaves' fallbacks replaced by `done`
typechecks with zero holes, which is the strongest single result here: the
`dec`-while contract's two back-edge obligations and both loop-contract closers
are not holes at all for the shape they were written for.

**One red this entry's `PASS=39 KNOWN-GAP=6 FAIL=0` no longer describes, and it
is pre-existing and not a `sorry`:** `count` fails at proof line 5330
(`bugs/formal/FORMAL_arm64_x30_is_reloaded_from_the_frame.md`). It is not in
`test_formal.py`'s `EXPECTED_FAILURES`.

**The `sgt8`/`sle8` row that used to sit beside it is GONE, and its owner was
deleted with its fix.** These four were **lean-rejected**: `def sgt8(n: Int8)`
narrowed the incoming word (`SXTB` then `SXTW`) and the CFG walk then asked Lean
for `⊢ t32s (t8s n) = n`, which is FALSE over the theorem's unconstrained `n`,
so Lean rejected the file with no `sorry` anywhere. The universal theorem now
carries the range hypothesis that obligation needs (`nw : n < 128`) and the
truncation discharges against it. Re-measured 2026-10-05:

```
$ python3 test_formal.py -j 1 sgt8 sle8 ug8 n8
  [1/4] PASS  sgt8
  [2/4] PASS  sle8
  [3/4] PASS  ug8
  [4/4] PASS  n8
Results for arm64 formal proofs: PASS=4 KNOWN-GAP=0 FAIL=0 TOO-LARGE=0
proof census: 0 admitted `sorry` in the generated file, in 0 of 4 proof(s) checked
```

Note the obligation's spelling also moved: this sentence recorded
`t32s (t8s n)` where the generator emits `t32s (t32u (t8s n))` (the extra
`t32u` is the 32-bit intermediate of `SXTB`-then-`SXTW`), and `ug8`'s is the
different `t8u n = n` entirely. Pinning is in
`test_formal_call_proof_gen.py::TestANarrowTypedParameterGetsItsRange`. The
document that used to own this is deleted, so the fact is recorded here rather
than left to a citation of it — and the mechanism that gap needed is now here
too: `tools/dangling_doc_refs.py::stale_verdicts` reports a `bugs/` document
whose verdict TABLE disagrees with `tools/formal_proof_census_baseline.json`,
which is the half the ratchet above cannot see (it counts citations of documents
that are gone; it does not check that a surviving claim is still true). It found
three rows of exactly this table saying `lean-rejected` beside a document that
had already been corrected, and the three ledger rows it named were replayed
verdicts that no run had ever produced — re-banked with `--remeasure`, which
moved the census from 34 proved to 37.

**The other half of master's sentence is the same fact stated for the
census entry above**: `bugs/formal/FORMAL_arm64_known_proof_gaps.md` records that
these two examples were missing from this file entirely, and the document
that owned them was deleted with the fix — which is why the citation that
used to sit here dangled.

**`Still open 3` below is unchanged and is still the whole of what is left here.**
What is new is that the work is now pinned to two model changes with the sites
that will need them named, instead of "a model change somewhere".

## Status (2026-10-01 — "Still open 3" re-measured; the loop MODELS are still the whole of it)

`test_formal.py` (arm64) on this tree: **`PASS=39 KNOWN-GAP=6 FAIL=0`**, and the
arm64 `sorry` census is **2** — both in `sum_range`, none in `countdown`/`wge`
(they are in `EXPECTED_FAILURES`, so their proof failing is not a hole; the
census only counts declarations in a proof that Lean accepted). The 6 gaps are
`both`, `countdown`, `either`, `fib`, `subscript_var`, `wge`, and two of the
seven sorries the 2026-09-26 entry counted are gone for an unrelated reason
(the recursion contract's forced `B.cond`, `8c1011ae`).

**"Still open 3" below is unchanged and is still the only unfinished thing in
this document.** What is new is that the CODEGEN half is now *measured* rather
than argued, which pins the work to the model side and nothing else:

```
$ cat .tmp/cases/negloop3.mojo
def negloop3():
    n = 0 - 3
    while n > 0:
        n = n - 1
    return n
$ python3 fire.py build --formal --no-prove -o .tmp/cases/negloop3.aout --backend=arm64 …
Built: .tmp/cases/negloop3.aout  [arm64/macho]
$ .tmp/cases/negloop3.aout ; echo $?      # the return value is the exit status
253
$ python3 -c '…same function…'            # -3, and -3 & 0xff = 253
-3
```

So a negative counter really does leave `while n > 0` immediately and is
returned unchanged, and `countdown_go`'s `= 0` is the wrong answer for exactly
the inputs the sign bit selects. The lowering needs no work; the MODEL does.

### The three sites, and what each one has to become

`Still open 3` names the fix in the abstract. These are the concrete places,
all in `formal/arm64_proof_gen.py`, and a session should start here rather than
re-deriving them.

1. **`_go_defs_for`, the `_dec_while_pattern` arm (~line 1091).** Emits
   `def {f}_go : Nat → UInt64 | 0 => 0 | k + 1 => {f}_go k` and
   `{f}_go_zero : ∀ n, {f}_go n = 0` (proved by induction). The model has to
   become `fun m => if m < 9223372036854775808 then 0 else
   UInt64.ofNat (m % 18446744073709551616)`, and `_go_zero` becomes
   `∀ m, m < 9223372036854775808 → {f}_go m = 0`. **Every current caller of
   `_go_zero` passes it as a whole simp set** — `{f}_go_zero` is closed over by
   the exit-x0 leaf of `_gen_countdown_loop` (~line 3211), by the loop
   contract's instantiation (~line 3313), by the CFG walk's terminal value flow
   (~line 4590) and by `_gen_dec_while_block` itself (lines 6352, 6403); it is
   also collected by name at 1413/1419. So each of those is a site that must
   now supply the sign fact, and 1413/1419 need no change (a name, not a
   signature). Grep for `_go_zero`, not for the model.
2. **`_gen_dec_while_block` (~line 6228), the `runF` bridge.** `pred_iff` states
   the source predicate `_PRED` (which `lib/ProofLib.lean`'s `evalExpr` reads
   **signed**, as `sKey l < sKey r`) and proves it with the **unsigned**
   `UInt64.lt_iff_toNat_lt` / `le_iff_toNat_le`. Those agree only for
   `m < 2^63`. This is the reported failure, verbatim from the run:

   ```
   ⊢ (if sKey 0 < sKey (UInt64.ofNat m) then 1 else 0) = if 0 < UInt64.ofNat m then 1 else 0
   ```

   `_PRED` needs the `m < 2^63` conjunct the sign bit forces, proved from
   `(UInt64.ofNat m).toNat = m % 2^64` (the `prelude`'s `ofNat_toNat_mod`
   already exists for exactly this), and `prog_correct`'s `Nat.eq_zero_or_pos
   (m % S)` split needs a third case for `m % 2^64 ≥ 2^63` — one
   `runF_while_false` step plus the identity, which is what the new model says.
   `NE` (`wdiff`) is signedness-independent and must keep its `exact Iff.rfl`;
   `wdiff` passes today and is the canary for "the change did not leak into the
   unsigned case".
3. **`_gen_countdown_loop` (~line 2976), the machine loop contract.** Its
   exit-x0 leaf closes with `simp [mojo, {f}_go_zero]`, which is right only
   because `_go_zero` was unconditional. With the split model the same leaf
   needs a `by_cases` on `arg < 2^63`: below it, the old simp; above it, the
   argument is that the loop never ran and `hcondDone` already pins the exit
   `x0` to the original `done` value, i.e. to `arg` — so the leaf becomes
   `arg = mojo arg` discharged by `UInt64.ofNat_toNat`. That is the shape to
   aim for; the machine half itself is already sound (the measurement above).

The reusable piece, as this document already said, is a signed-order lemma
bridge from `Nat` to the two's-complement word. `lib/ProofLib.lean`'s `sKey`
and its `arm64_flag_*_s` lemmas are the right shape and only need that bridge;
`UInt64.toNat_ofNat'` and `Nat.mod_eq_of_lt` are what carry `m % 2^64`.

## Status (2026-09-27 — NOT ATTEMPTED: the only remaining work here is `formal/`, and that was out of scope this session)

Recorded so the next session with a `formal/` budget does not re-derive this.

"Still open 3" (below) is **entirely** inside `formal/`: the `dec`-while
and `range` loop MODELS, `prog_correct`'s induction split, and two
`sum_range` holes. Nothing in the compiler, the runtime, the interpreter
or the test suites is outstanding for this document — the CODEGEN half
and the 13-case runtime matrix were both complete before this session
(see the 2026-09-26 entry above).

**Not verified this session:** `test_formal.py` was deliberately NOT run
(it is what deadlocked the machine earlier on 2026-09-27, orphaning
`fire.py build --formal` workers on `lib/ProofLib.olean.buildlock`), and
no Lean proof was written or chased. The 91/91 `test_formal_run.py` and
the 38/5/0 arm64 proof census above are the 2026-09-26 numbers, carried
forward unverified.

The next action is unchanged and is the "Optimization"-free part of the
plan recorded below: the `Nat`-to-two's-complement signed-order lemma in
ProofLib, then `pred_iff`/`countdown_go`, then `prog_correct`'s step
case, then `sum_range_loop_cond_flag`.

## Status (2026-09-26 — BOTH halves landed; the loop MODELS are the one remaining gap)

| area | state |
|---|---|
| `B.cond` at every conditional site | landed |
| `for i in range(...)` loop exits | landed |
| Spill-slot displacement sign | landed |
| `while_dec_exit_contract` / `while_lt_exit_contract` parameterised over the loop TEST | **landed** — the register-shaped `cr` is gone |
| The 8 loop-contract `sorry`s (4 files) | **closed** — 0 remaining in those proofs |
| arm64 formal proofs | 38 pass / 5 known-gap / 0 fail (was 40/3/0; the 2 extra known-gaps are new and named below) |
| arm64 `sorry` census | 7 declarations (was 5): the 5 pre-existing `*_compiles_correctly_universal` run-test leaves, plus 2 in `sum_range` |
| x86-64 formal proofs | 43/43, unchanged |
| `test_formal_run.py` | 91/91 (was 33/33) — 15 signedness cases added |
| Unannotated `int` | **now SIGNED**, and `common_type` is signed-wins |
| Loop MODELS (`dec`-while, `range`) still assume a non-negative counter | **OPEN — see "Still open 3"** |

Both halves of this document's "Done when" are met for the CODEGEN and the
13-case runtime matrix; the formal side has two newly-recorded known-gaps, and
they are recorded because the obligation is genuinely unprovable, not merely
unproved (see "Still open 3").

## FIXED 1: signedness — `DEFAULT_INT_TYPE` is signed and `common_type` is signed-wins

`formal/types.py` reports a negated literal as `IntType(64, True)`, because a
negative value cannot be an unsigned one. That fixes literal-vs-literal, and
range counters (whose seed was the unsigned default, so *every* range was
unsigned regardless of bounds). It does **not** fix anything involving a
variable, because an unannotated local gets `DEFAULT_INT_TYPE` — which is
`IntType(64, signed=False)` — and `common_type` resolves mixed
signed/unsigned to **unsigned** (the C rule, documented at
`formal/types.py:63`).

Measured after the fix (every row a real build + run, `test -3 < -5` included
because the negative-of-negative case is the one most likely to be wrong):

| source | result | correct | |
|---|---|---|---|
| `a = -3; if a < 2:` | 1 | 1 | ok — literal vs literal |
| `a = -3; if a < -5:` | 0 | 0 | ok — literal vs negated literal |
| `a = -3; if a > 2:` | 0 | 0 | ok — `>` too, so the inversion is fine |
| `for i in range(2, -3, -1)` | 5 | 5 | ok — counter seed fixed |
| `a = 0 - 3; if a < 2:` | 0 | 1 | **WRONG** — `0 - 3` is a `BinaryOp`, still typeless |
| `a = -3; b = 2; if a < b:` | 0 | 1 | **WRONG** — `b` is an unannotated local, so unsigned |

So the literal-vs-literal case is genuinely closed, in both directions and for
`range` in both directions. What is still broken is narrow and specific:

1. **A negative value produced by arithmetic.** `0 - 3` and, by the same route,
   `n - k` where the result is negative, do not go through `UnaryOp('-', …)`, so
   they keep the bare-literal rule and stay typeless. Folding a constant
   `BinaryOp` in `infer_expr` would cover the literal-literal subcase; the
   general case needs value analysis, which is out of scope here.
2. **Comparing a negative literal against a variable.** This is the deeper one
   and is the design point below.

So the remaining gap is a **consequence of the documented design**, not an
oversight in the fix: unannotated `int` is modelled as `UInt64`, and Python/Mojo
integers are signed and unbounded. Any comparison of a negative quantity
against a variable is still wrong.

**Why this is not a one-line change.** The knob is how `function_var_types`
types an unannotated local, and that decision is shared with the truncator
helpers, the width selection in `CSET`, the shift mnemonics
(`formal/x86_64_codegen.py:967`), and the comparison mnemonics (`:2100`,
`:2135`). Changing the default to signed moves all of them at once. Two
candidate directions, neither cheap:

* **Signedness by assignment.** Type an unannotated local from the type of its
  initializer, so `a = -3` is signed and `b = 2` is... still unsigned, which
  leaves the mixed case broken. Only fully solving the mixed rule (e.g. "signed
  wins" instead of the C rule) fixes the table above, and that changes
  `common_type` for every consumer.
* **Signed default for unannotated `int`.** Matches Python/Mojo semantics, and
  is one line — but it silently reinterprets existing unsigned code paths
  (shift, division, truncators), so it needs the full gate, not a spot check.

**Done when:** the four wrong rows above are right, and arm64 formal 40/3/0 plus
x86-64 43/43 both still hold. Also needs `Int8`/`Int16` negative literals
checked — they currently infer as `Int64`, which is a width mismatch rather than
a signedness one.

## Still open 2: 13 formal sorries, both sites from one root cause

Census at 40/3/0, counted by running Lean over the generated file with
`LEAN_PATH` set (a plain build reports `verified from cache` and never runs
Lean, so grepping its output returns 0 for every file — the wrong answer).

| site | files | cause |
|---|---|---|
| `cd_loop` value-flow goals | 9 | `while_dec_exit_contract`'s test is register-shaped |
| `loop_cond_flag` register half | 4 | same, from the other side |

`while_dec_exit_contract` states its step obligation over
`arm64_reg cr st = 0` (the generator passes `cr = 0`) because it was written for
the `CSET` lowering, which *wrote* the boolean into X0. `B.cond` branches on
`nzcv` and writes no register, so the contract asks for a fact the instruction
no longer produces — and the state at the loop header is arbitrary subject only
to its pc, so no tactic recovers it.

**The fix is one parameterisation**, replacing `arm64_reg cr st = 0` with a
caller-supplied `q : Arm64State → Bool` in `hstep`, `hcondFlag` and the three
internal uses. Verified in a WIP pass: `ProofLib` compiles with the change, and
the countdown shape (`b.ls`, raw code 9) is **fully proved** with no sorry, via

```
simp only [<block defs>, arm64_reg, arm64_set_reg]
rw [mem_read_push_low s.mem s.sp]     -- resolve the STP/LDP pair FIRST
rw [arm64_flag_le]
simp (disch := decide) [mem_read_after_write_u64, ..., u64_ofNat_add]
```

The wall: the closing arithmetic lemma is **per condition code**, not per shape.
`countdown` (raw 9) builds; `wdiff` (raw 0) needs `Iff.rfl`; `wge` (raw 3)
against a bound of 1 needs a `u64_lt_one` sibling of `u64_le_zero_iff`. So the
remaining work is a small table beside `_COND_LEMMA` mapping each raw code to
(flag lemma, arithmetic lemma). Suite went 40/3/0 → 38/3/2 while that was
incomplete, which is why it was reverted rather than committed. The per-step recipe, including the two
tactic orderings that each cost a cycle, is in the "Not open, but easy to
re-break" section above.

**After that:** `while_lt_exit_contract`, the counting generalisation at
`ProofLib` ~3002, has the same register-shaped `hstep` and was not touched, so
the two will drift.

## Not open, but easy to re-break

* **`_STEP_CONDS` overlapping pairs.** Entries 3/5 (SUB/NEG), 4/47 (MUL/MSUB)
  and 48/50 (LSR/LSL) can match the same word. `_step_facts` now decides per
  *word* rather than per table, leaving a shadowed entry unconstrained instead
  of negating it, and `audit_step_table()` enforces (a) the condition sets match
  and (b) for every overlapping pair the table-earlier entry is also
  `ProofLib`-earlier. `test_formal.py` calls it before any Lean runs. The
  tempting alternative — rule out only the entries *before* the chosen one — is
  unsound: the two orders do not agree globally (`B.cond` is model position 18,
  table index 51).
* **Spill slots are below X29.** `_spill_off` returns the distance *down*; the
  `ldur`/`stur` fast path must negate it. The positive form addresses the
  caller's frame and silently corrupts it. Invisible to any single-variable
  test, and it needed >10 locals to show up at all.
* **Every expected value in `test_formal_run.py` must fit in a byte.** A process
  exit status is 8 bits; comparing an 8-bit code against a wider sum produced a
  convincing phantom "14+ spilled locals" bug that cost real time; that retraction is
  summarised in `FORMAL_arm64_instruction_coverage.md`.

## FIXED 2: the 13 loop-contract `sorry`s (the count was 8, in 4 files, not 13 in 9)

The census this document used was wrong, and the way it was wrong is the useful
part. It counted the WORD `sorry` in the generated proofs, which counts
*hypothetical* holes: every `all_goals (first | … | sorry)` fallback keeps the
word even when an earlier alternative won, so the textual count cannot go down.
Worse, the doc counted greps of a plain `lean` run, and a plain run reports
nothing when Lean serves a cached verdict. The real number — declarations Lean
itself reports as "uses `sorry`" — was **8, in 4 files** (`countdown`,
`sum_range`, `wdiff`, `wge`): 4 `loop_cond_flag` register halves and 4 loop-test
`hstep` obligations. The other 5 real holes (`count`, `fact`, `pow2`, `sqsum`,
`sum`, one `*_compiles_correctly_universal` each) are a different root cause and
are still open.

`formal/lean.py::_run_lean` now counts `declaration uses` in the real Lean
output and `check_proof_cached` returns it (4th element; the verdict key moved
to `formal-proof-verdict-v2` because the stored body changed shape).
`test_formal.py` reports the census after every run, so the number is always
authoritative and the loop contract's holes are visible in the tally rather than
in a hand-run grep.

**What closed them**, in `lib/ProofLib.lean` + `formal/arm64_proof_gen.py`:

- `while_dec_exit_contract` and `while_lt_exit_contract` are parameterised over
  `q : Arm64State → Bool` (`true` = leave the loop) instead of a register index
  `cr`. The register shape described the old `CSET`-then-`CBZ` lowering; the
  current lowering branches on the `CMP`'s flags and writes no register, so the
  obligation asked for a value-flow fact no instruction produces.
  `loop_test_def` emits one `def <name>_loop_q` per example, so the `refine`,
  the `hstep` tactic and the `cond_flag` lemma quote one symbol rather than three
  copies of the same expression.
- `_cond_flag_lines` + `_COND_ARITH` close the `cond_flag` leaf: unfold `q`,
  unfold the condition block's state chain, resolve the STP/LDP pair, rewrite
  with the flag lemma for the raw condition code (`_COND_LEMMA`, which already
  covered all ten), then close the arithmetic. The default closer is
  `decide | omega | grind`, which is enough for every shape the 43 examples
  contain.
- `_cond_step_tactic` is now a `by_cases` on `<name>_loop_q s = true` followed
  by `simp [<name>_loop_q, hs, hc]`, and it closes. Nothing is admitted.
- `while_dec_exit_contract`'s induction was also generalised, because a signed
  `int` means a NEGATIVE counter also leaves the loop: `hcondFlag`'s
  `q = true ↔ x19 = 0` became `hcondZero` (`x19 = 0 → q = true`) +
  `hcondStep` (`q ≠ true → x19 ≠ 0`) + `hcondDone` (`q = true → exit x0 = done
  x19`), and the step case splits on the test rather than deriving `¬q` from
  `x19 ≠ 0`. `hcondDone` is a real new obligation — before, the exit block's x0
  was pinned by `hexX0` under `x19 = 0`, which a loop that exits with a nonzero
  counter never satisfies.
- The generator's `loop_exit_x0` lost its `hpc` hypothesis: the obligation is
  pure value flow, its proof never reads `s.pc`, and once the contract was
  parameterised the caller holds the condition block's post-state, whose pc is
  the loop test and NOT the exit branch's target — so the hypothesis was not
  merely unused but unsatisfiable.

## Still open 3: the generated loop MODELS assume a non-negative counter

This is what the signed default exposes, and it is the one thing from this
document that is not done. With a signed `int`, `while n > 0: n -= 1` on
`n = -1` must return `-1` — the loop never runs. Two things still believe
otherwise, and both are the MODEL, not the machine:

1. `_gen_dec_while_block` (`formal/arm64_proof_gen.py`) emits `pred_iff` as the
   UNSIGNED `0 < UInt64.ofNat m`, and the model `countdown_go : Nat → UInt64`
   is `| 0 => 0 | k+1 => countdown_go k`, i.e. it returns 0 for every input. For
   `m >= 2^63` the loop test is false, so both statements are false, and
   `prog_correct`'s induction (which splits only on `m % 2^64 = 0` vs
   `0 < m % 2^64`) has no case for it. `wdiff` (`while n != 0`) is unaffected —
   equality is signedness-independent and the loop always reaches 0 — and still
   proves.
2. `sum_range`'s `loop_cond_flag` states the exit condition as the UNSIGNED
   `¬ (i < bound)`, so for a negative bound it is false and the leaf falls to
   the `sorry` (`rw [arm64_flag_ge_s]` rewrites the flag to a SIGNED `≥`, which
   is not what the statement says). Two holes there, up from zero.

Both are recorded rather than hidden: `countdown` and `wge` are in
`test_formal.py`'s `EXPECTED_FAILURES` with the reason, and `test_formal.py`
reports a stale entry as a failure if either starts passing. The fix is a model
change in two places, not a tactic:

- `pred_iff` becomes the signed test related to the Nat value with the
  `m < 2^63` conjunct the sign bit forces, proved from `UInt64.ofNat m`'s
  `m % 2^64`; the model becomes `if n < 2^63 then 0 else UInt64.ofNat (n % 2^64)`;
  and `prog_correct`'s step case splits on `m % 2^64 < 2^63` as well as on
  `eq_zero_or_pos`, with the new branch being one `runF_while_false` step.
- `sum_range_loop_cond_flag` is restated as `¬ (signed i < signed bound)` and
  `_gen_range_loop_model` is given the same `n < 2^63` split.

A signed `runF` arithmetic lemma pair (`sKey`-based order on `UInt64.ofNat`)
would be the reusable piece for both; ProofLib's `sKey` and its
`arm64_flag_*_s` lemmas are already the right shape, they just need the bridge
from `Nat` to the two's-complement word.
