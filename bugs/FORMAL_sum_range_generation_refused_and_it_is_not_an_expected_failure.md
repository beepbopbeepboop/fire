# `formal/examples/sum_range.mojo` has no loop contract because its back edge is a CONDITIONAL branch — and no `EXPECTED_FAILURES` entry says so

**Status (2026-10-04, `work/formal21-6`): the GENERATION refusal is FIXED at the
root cause — the back edge is discharged by a bottom-tested loop contract, and
the doc's "next step" was right about what to ask and wrong about how many
things had to be asked. The proof now generates on arm64. It still does not
TYPECHECK, for a reason in the walk's SHARED conditional-branch machinery that
this branch did not take: see §0 and the second doc.**

**Area:** FORMAL (the arm64 proof generator's CFG walk). Found 2026-10-03 on
`work/formal18-6`; measured, not fixed. It belongs to whoever holds
`formal/arm64_proof_gen.py`'s walk, and it is **one arm away** from
`“`formal/examples/wdiff.mojo` has no loop contract on arm64”`, which this branch fixed and deleted.

**Status: still OPEN and still refused, and §"What the fix actually is" replaces
the next step above with a three-part change that is bigger than it looks — the
contract is not merely unapplied at the conditional edge, it is never BUILT for
this shape. Measured on this tree 2026-10-04 (`work/formal19-5`).**

## 0. What landed, and what is still open

**Fixed: `ValueError: unsupported cbz taken continuation to 0x100000330` is
gone, and it is gone at the cause.** The doc's §"The root cause" is confirmed
exactly — a `for`-range loop's back edge is a conditional branch, and the walk
asked "is this the loop top?" only in its `b` arm — and the discovery was the
half this doc did not name:

> `_gen_range_loop` was written for a shape the emitter **has not produced
> since the preheader landed**.

`arm64_codegen`'s `_emit_while` puts a `for`-range loop's emptiness test in a
PREHEADER, so the body, the counter increment, the comparison and the back edge
are ONE `cbz`-kinded block whose taken edge targets its OWN start, and the
generator's loop discovery — "a `b` block whose target is a `cbz` block" — has
no answer for it. Measured over every `.mojo` in `formal/examples/` and
`formal/hostmods/`: one self-looping `cbz` block for `sum_range`, and **no
top-tested range loop anywhere**, which is why the contract generator matched
nothing and the walk had nothing to apply. That is the whole of "the loop
contract is on ONE arm": the arm was right about the question and the loop was
not in the shape it was asking about.

The commit adds `while_lt_exit_contract_bottom` to `lib/ProofLib.lean`
(`while_lt_exit_contract` for a loop whose test is at the bottom: no condition
prefix, the branch's TAKEN edge is the loop again, and an entry obligation
that the counter is still below the bound), rewrites `_gen_range_loop` for the
shape the emitter produces — including composing the TWO-block exit path out of
each block's own certificate — and makes the `cbz` arm ask the question the
`b` arm already asks. The back edge's register chain and terminal value flow
moved out of the `b` arm into `_emit_range_back_edge_tail`, shared by both.

**Still open, and it is a different bug: the generated proof does not
typecheck.** One Lean error, in the walk's `hcond` obligation for the loop's
PREHEADER — the comparison's operand is read through a spill slot stored two
blocks earlier, the chain emits no flag lemma for a `B.cond`, and `bv_decide`
returns a "potentially spurious counterexample" over its own abstraction.
Filed, with the reproduction and the next step, as
`bugs/FORMAL_a_conditions_operand_read_through_an_earlier_stores_slot.md`. It
is not in the loop contract and it is not this branch's to take: `hcond` is
emitted for every conditional branch, so appending a `sorry` to that chain
would convert other programs' build failures into admitted obligations.

The generated proof also carries **four admitted `sorry`s** — the frame
obligations the loop's body run and exit path owe, stated where they are used
rather than discharged. That is this emitter's established shape
(`_COND_ARITH_DEFAULT`, the `-- TODO(range)` leaves) and the honest outcome
this doc's §"The next step" predicted: "a generated proof carrying that hole …
rather than a refusal". `test_formal.py`'s hole census reports all four, so
they are counted rather than hidden.

**Verified:** `python3 test_formal_call_proof_gen.py` — 61 passed, 0 failed,
including three new rows that pin that `sum_range` generates, that its proof
carries `while_lt_exit_contract_bottom`, and that the loop top on the IMAGE is
the self-looping block the contract is generated from. `python3 -c` over every
`formal/examples/*.mojo` with `prove=True, check=False`: **48 of 50 generate**,
and the two that do not are `subscript_var` (in `EXPECTED_FAILURES`) and
`wide_recv` (a semantic-model refusal in code-generation territory), both
unmoved by this change — it was 47 of 50 before it.

**`test_formal.py`'s `sum_range` row is still red**, for the `hcond` reason
above. So this document stays: the job it names is still not green.

**Not new, and the prior observation is recorded.** `bugs/FORMAL_proof_coverage_census_2026-10-03.md`
§0.3 already measured this exact refusal against this exact tree:

| item | the census's ledger | this tree, arm64 |
|---|---|---|
| `formal/examples/sum_range.mojo` | `admitted`, 2 holes | `ValueError: unsupported cbz taken continuation to 0x100000330` |

So the refusal is old — `git log -S` puts the `raise` at the 2026-09-23
restructure that created this backend — and what is new here is three things
that doc does not say: **the root cause**, **that the `formal` SUITE job is red
because of it and nothing in the tree records that**, and **that a second doc
still quotes the stale half of the table above**.

## What I ran

```console
$ python3 -c "…" probe_all.py arm64          # every formal/examples/*.mojo through
                                            # compile_formal(prove=True, check=False)
sum_range   FAIL  ValueError: unsupported cbz taken continuation to 0x100000330
```

Identical on **master's tip** (`6ccb36df`) and on this branch's base
(`86d60026`), so neither the last 25 merges nor this branch's commits did it. No
Lean: the refusal is at GENERATION time, so the whole census costs 2 s.

## The root cause, which is the part that is new

The built image, read off `formal/arm64_proof_gen.py`'s own decoder:

```
0x100000300  movz x0, #0 ; mov x20, x0 ; movz x0, #0 ; mov x21, x0    the prologue
0x100000324  cmp x0, x1
0x100000328  b.lt 0x100000330           <- into the body
0x10000032c  b    0x100000374           <- and past it (the loop never runs)
0x100000330  … total += i ; i += 1 ; cmp x0, x1 …
0x100000368  b.lt 0x100000330           <- THE BACK EDGE, and its target is the
                                           block's OWN start
0x10000036c  sub x21, x21, #1 ; b 0x100000374
0x100000374  … ret
```

`_cfg_blocks` therefore reports `0x100000330` as a `cbz`-kinded block whose TAKEN
target is itself, and the walk's conditional-branch arm raises:

```python
# formal/arm64_proof_gen.py:6019
tgt_bi = start_to_bi.get(taken)
if tgt_bi is None or tgt_bi in path:
    raise ValueError(f"unsupported cbz taken continuation to {hex(taken)}")
```

**That edge is the loop.** A `for` loop lowered with the test at the BOTTOM of
the body has a conditional back edge, so "the taken target is a block already on
the path" means *loop again*, not *impossible continuation*.

**The binary is right**, which is what makes this a proof-layer gap rather than a
codegen one:

```console
$ python3 fire.py build --formal --no-prove -o .tmp/sr.aout formal/examples/sum_range.mojo
$ .tmp/sr.aout ; echo $?
45            # 0+1+…+9, and it terminates
```

**And the walk's loop-contract handling is on ONE arm.** The unconditional
`b`-block arm consults `ctx["loop_contract"]` when its target is the loop top
(`formal/arm64_proof_gen.py:5382`); that is what makes `wdiff`, `countdown` and
`wge` generate contracts today — they lower with the test BEFORE the body, so
their back edge is an unconditional `b`. The conditional-branch arm's taken edge,
640 lines down, has no case at all. **`sum_range` and those three are the same
loop contract split across two arm shapes, and only one shape is implemented.**

## Why nothing in the tree records it

`test_formal.py`'s `EXPECTED_FAILURES` holds `fib`, `countdown`, `wge` and
`subscript_var` — **not `sum_range`** — and `tools/suite.py` registers

```python
test('formal', [PY, 'test_formal.py'], j=True, deps=['preflight', 'prooflib'], …)
```

with no `expect=`. So this is an UNEXPECTED failure of a job the registry says
must be green. The census doc saw the refusal and filed it against the CENSUS; the suite job is a different job, and nothing connects the two.

**Two numbers in the tree now disagree and both are quoted.** This doc's §0 table
above says the ledger recorded `admitted, 2 holes`, and
`bugs/FORMAL_arm64_known_proof_gaps.md` still quotes it — "sorries in passing
proofs | 2, both in `sum_range`", with `sum_range` absent from its own
known-gaps row. That doc is `formal18-2`'s claim, so this one does not edit it;
it is named here as the place where the stale half lives. Settling which number
is right is a `git log` on the walk, and it is the first step for whoever takes
this.

## The next step, and the shape of it

Give the conditional back edge the treatment the `b` arm already has. The
question to answer is the one that arm already asks:

* **is the taken target the loop top?** — `ctx["loop_contract"]["cbz_start"]`,
  the same value `:5382` matches on. If so, apply the contract there too.
* **if it is not**, it is a genuine re-entry and the refusal is right. That
  distinction is the whole of the patch; nothing below it needs new work.

Two measurements to take while in there, both cheap:

* `_gen_range_loop` already matches this file's shape (its loop-top block has the
  STP/LDP + CMP-register prefix it looks for), so check whether the contract it
  emits is what this edge needs or whether `while_lt_exit_contract`'s exit
  obligation has to be routed differently. The countdown arm's use site is the
  worked example of a contract being applied mid-walk.
* the ledger's two holes were in `loop_cond_flag`. If the range contract's
  `cond_flag` obligation is what fails to close, the honest outcome is a
  generated proof carrying that hole — which is what the ledger recorded — rather
  than a refusal.

## What the fix actually is, measured (2026-10-04) — three parts, and part 1 is
## the one this doc's next step missed

§"The next step" above says "give the conditional back edge the treatment the
`b` arm already has … is the taken target the loop top? `ctx["loop_contract"]
["cbz_start"]`, the same value `:5382` matches on. If so, apply the contract there
too." **Measured, that is necessary and not sufficient: for `sum_range` there is
no `loop_contract` in `ctx` to apply, because no loop contract is generated at
all.** Three things are missing, and in this order.

### 1. The loop test is never FOUND (the discovery, not the application)

`formal/arm64_proof_gen.py:5120` asks one question:

```python
for b in blocks:
    if b["kind"] == "b" and start_to_bi.get(b["targets"][0]) is not None:
        cbi = start_to_bi[b["targets"][0]]
        if blocks[cbi]["kind"] == "cbz":
            loop_check = (cbi, blocks[cbi]["start"])
```

— a **`b` block whose target is a `cbz` block**, i.e. an UNCONDITIONAL back
edge. `sum_range`'s blocks, read off `_cfg_blocks` (the generator's own
partitioner, so this is what the generator sees):

```
  4 start=0x100000300 kind=cbz  targets=['0x100000324', '0x100000328']
  5 start=0x100000324 kind=b    targets=['0x100000374']
  6 start=0x100000328 kind=seq
  7 start=0x100000330 kind=cbz  targets=['0x10000036c', '0x100000330']   <- the back edge
  8 start=0x10000036c kind=b    targets=['0x100000374']
  9 start=0x100000374 kind=ret
```

Blocks 5 and 8 branch to the RET block, so `loop_check` stays `None` and the
whole `if loop_check is not None` at `:7020` — every `_gen_range_loop` and
`_gen_countdown_loop` call, and the `_init_ctx` that carries the contract to the
walk — is skipped. `wdiff`, `countdown` and `wge` are found precisely because
their block 5 is `b 0x1000002fc`. **So the first change is in the discovery: a
`cbz` block whose TAKEN target is its own start is the same answer, and the scan
has to ask for it.** That is the `formal16-2` doc's "`csel`/bit-test" territory
only in the sense that both are about which branch is a loop's test; the change
itself is one clause.

### 2. `_gen_range_loop` reads the two targets in the wrong order for this shape

`_gen_range_loop` does `cbz_fall, cbz_taken = cbz_block["targets"]` and then
`body_pc = cbz_fall; exit_pc_val = cbz_taken`. For a loop whose test comes FIRST
that is right. For `sum_range` the taken target is `0x100000330` — the block's
OWN start — and the fall target is the exit path, so the two are swapped:

* `body_pc` would be `0x10000036c`, which is `sub x21, x21, #1 ; b exit` — the
  exit, not a body;
* `exit_pc_val` would be the loop top itself.

With `body_pc` pointing at the exit, the body-block walk finds no `b` block
targeting `cbz_start` and `_gen_range_loop` returns `None` — and the caller's
`else` then tries `_gen_countdown_loop`, which requires the same `b`-to-`cbz`
back edge and also returns `None`, and the refusal becomes "no loop contract
matches". **Measured, the rest of the signature DOES match this file**, which is
the encouraging half and the reason §"The next step" above believed it:
block 7's prefix carries step-branch indices `[10, 21, 10, 10, 22, 2, 10, 10, 10,
21, 10, 10, 22, 6]` — STP-pre (21), LDP-post (22), CMP-register (6) — and its
terminator is a `B.cond` (51), which is exactly the predicate
`if not (21 in idxs and 22 in idxs and 6 in idxs and _has_cond): return None`
tests. So the shape is recognised and the ROLE of the two targets is the only
thing wrong.

### 3. The contract for this shape is a DIFFERENT induction, and the library does
### not have it

`while_lt_exit_contract` cannot express a test at the bottom, and this is
structural rather than a missing hypothesis. It asks for a BODY RUN that starts
at `bodyPc` and comes back to `checkPc`:

```
(hbodyRun : ∀ st, st.pc = bodyPc → arm64_runs code mb st = some (body st))
(hbodyPc  : ∀ st, st.pc = bodyPc → (body st).pc = checkPc)
```

For `sum_range` the loop's body IS the loop top: the run from `0x100000330`
reaches the test at `0x100000368`, whose successor is either the loop top again
or the exit — it never returns to `checkPc`, because `checkPc` is where it
started and `arm64_runs` is a straight-line run. `bodyPc = checkPc` would make
`hbodyRun` demand `arm64_runs code 0 st = some st` with `body = id` AND
`hbodyR : arm64_reg r (body st) = arm64_reg r st + 1`, which is `r = r + 1`.

**So the Lean half is a new theorem, and its statement is short.** `checkPc` is
the loop top, `cbzPc` the test instruction INSIDE that block, the iteration is
the block's own straight-line prefix, and the induction is on
`(b - r).toNat` exactly as before:

```lean
theorem while_do_exit_contract
    (code : Nat → UInt8) (exit checkPc cbzPc exitBpc : Nat)
    (q : Arm64State → Bool) (r b : Nat) (model : Arm64State → UInt64)
    (cond ex : Arm64State → Arm64State) (mc me : Nat)
    (P : Arm64State → Prop)
    (hP_pc   : ∀ (st : Arm64State) (pc : Nat), P st → P { st with pc := pc })
    (hP_cond : ∀ st, st.pc = checkPc → P st → P (cond st))
    (hstep   : ∀ st, st.pc = cbzPc →
      arm64_step st code = some (if q st then
        ({ st with pc := exitBpc } : Arm64State) else ({ st with pc := checkPc } : Arm64State)))
    (hcondRun  : ∀ st, st.pc = checkPc → arm64_runs code mc st = some (cond st))
    (hcondMid  : …) (hcondPc : ∀ st, st.pc = checkPc → (cond st).pc = cbzPc)
    (hcondFlag : ∀ st, st.pc = checkPc →
      (q (cond st) = true ↔ ¬ (arm64_reg r st < arm64_reg b st)))   -- q = LEAVE, as in while_lt
    (hcondRB : ∀ st, st.pc = checkPc →
      arm64_reg b (cond st) = arm64_reg b st)
    (hcondR  : ∀ st, st.pc = checkPc →
      (arm64_reg r (cond st)).toNat = (arm64_reg r st).toNat + 1)     -- see the wrap note
    (hcondModel : ∀ st, st.pc = checkPc → arm64_reg r st < arm64_reg b st →
      model (cond st) = model st)
    (hexRun) (hexMid) (hexPc) (hexX0) (hmodelPc) (hcbzExit) (hExitBpc) (hCheckCbz) :
    ∀ (st : Arm64State) (fuel : Nat),
      (mc + 2) * ((arm64_reg b st).toNat - (arm64_reg r st).toNat) + (mc + me + 2) ≤ fuel →
      st.pc = checkPc → P st →
      ∃ s, arm64_go_exit st code exit fuel = some s ∧ s.x0 = model st
```

The proof is `while_lt_exit_contract`'s with the body group deleted: `zero` is
that lemma's base case verbatim, and `succ k` applies `ih` to
`{cond st with pc := checkPc}` after `rec1_glue_gen` for `mc` and one
`go_exit_cbz_fall` — no second `rec1_glue_gen`, because there is no second run.

**One design decision inside it, and it is the one to be careful about: the
counter's advance is stated in NATS** (`(arm64_reg r (cond st)).toNat =
(arm64_reg r st).toNat + 1`), not as `arm64_reg r (cond st) = arm64_reg r st + 1`.
`while_lt_exit_contract` states the `UInt64` equation and derives the Nat one
inside the induction, using `r < b` to get the no-wrap. A test at the BOTTOM
cannot: the increment has already happened when the loop decides to exit, and the
base case only knows `b ≤ r`. With the `UInt64` spelling the base case needs
`¬ (r + 1 < b)` from `b ≤ r`, which is FALSE when `r = 2^64 - 1` and `b > 0` — the
counter wraps and the machine genuinely loops again. Stating it in Nats makes the
no-wrap an explicit OBLIGATION, which the generator discharges where it can
(inside the body, from `i < bound`) and ADMITS where it cannot (on the exit
path), and that admission is the honest account: it is the same unsigned
exit-side obligation `countdown`/`wge` are already marked for
(`bugs/CODEGEN_arm64_cmp_flags_and_loop_signedness.md`), and it is what the
census recorded as `sum_range`'s `loop_cond_flag` hole before the refusal.

### 4. And the walk's conditional arm, which is where §"The next step" was right

`formal/arm64_proof_gen.py:6307`:

```python
tgt_bi = start_to_bi.get(taken)
if tgt_bi is None or tgt_bi in path:
    raise ValueError(f"unsupported cbz taken continuation to {hex(taken)}")
```

The question to ask is the one the `b` arm asks at `:5647` — is `taken` the
`cbz_start`? — and when it is, the ~130 lines the `b` arm emits for the contract
have to be emitted here too, against `taken` rather than `tgt`. **They must be
EXTRACTED, not copied**: CLAUDE.md's "no duplicated implementations" applies with
force here, because the block encodes one fact about one example twice — the
`h{i}x19`/`x20`/`x21` chain and the `h{i}x20 = s_{i-1}.x20 + s_{i-1}.x21`
"the last block incremented the counter" step are numbered off the block indices
of a two-block loop, and the doc's own history is the argument:
`bugs/FORMAL_arm64_known_proof_gaps.md`'s comment in that arm records that a
previous version named `hsrc_1`/`hsid_1` and `{name}_b2_qT6`, which are one
example's numbering, and that Lean reported them as `Unknown identifier` hundreds
of lines later. One helper, two call sites.

### What this doc does NOT claim

* That the four parts land, or in this order — 1 and 2 are mechanical and 3 and 4
  are where the work is.
* That the generated proof will be CLOSED. Per the author's own note, the
  exit-side unsigned comparison may still be admitted; the outcome to aim for is
  a generated proof with that hole, which is what the ledger recorded, rather than
  a refusal.
* `sum_range`'s **value** theorem. The `range` model (`_gen_range_loop_model`'s
  `loop_go`) is only reached through the contract, and the walk's post-processing
  assumes the accumulator is updated in a block AFTER the test — which in this
  shape is the same block as the test. That is a second, separate obligation and
  this doc does not claim it is free.

## Reproducing

```console
$ cd "$(git rev-parse --show-toplevel)"
$ python3 -c "
import sys, os; sys.path.insert(0, os.getcwd())
import formal.build as B
try:
    B.compile_formal('formal/examples/sum_range.mojo', output='.tmp/sr.aout',
                     prove=True, check=False)
except Exception as e:
    print(type(e).__name__, e)"
ValueError unsupported cbz taken continuation to 0x100000330
```