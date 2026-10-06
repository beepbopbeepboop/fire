# FORMAL_arm64_x30_is_reloaded_from_the_frame: the dec1 recursion family cannot be proved because the generator asserts x30 is unchanged and the code generator now RELOADS it

**Area:** FORMAL (the arm64 proof generator's per-instruction value flow).
**Status: OPEN. Re-measured 2026-10-03 on this tree, and the DIAGNOSIS IS
CORRECTED: the obligation is not merely unproved, it is FALSE as the theorem is
stated, so "peel the chain" is not the whole fix and step 1 below is necessary
but not sufficient.** The reduced goal is quoted verbatim from a real run, the
`st.sp` that makes it false is computed, and §"What this costs the fix" says
what has to be added first. Everything else in this file — the two error sites,
the measurement table, the five affected examples, the peel machinery that
exists — was re-confirmed on this tree and still stands.
Found 2026-10-03 by
`tools/formal_proof_breadth.py`'s proof-breadth census
(`bugs/FORMAL_proof_coverage_census_2026-10-03.md`), which is the first thing
ever to run this repository's OWN functions through `build --formal` with
proofs on. Nothing in `formal/examples`' existing coverage sees it, because every
dec1 program in the corpus is the same two-line shape and the one that
typechecks (`wdiff`) has no call in it.

## What is broken

`formal/arm64_proof_gen.py::_gen_universal_e2e_cfg` emits, for each block that
ends a run, a fact that the link register survived the block:

```lean
have hx30fr_5 : (count_b5_qS4 (({ s_4 with pc := 4294968088 }))).x30 = (st).x30 := by
  have h8 : (8 : UInt64) = UInt64.ofNat 8 := rfl
  simp +decide only [h8, hsid_0, …, mem_read_after_write_u64, …]
  all_goals rfl
```

and `all_goals rfl` fails, with both sides reduced (`count`, proof line 5220):

```
⊢ mem_read_u64
     (mem_write_u64 (mem_write_u64 (mem_write_u64 (mem_write_u64
        (mem_write_u64 (mem_write_u64 st.mem (st.sp - 16).toNat st.x29)
                                (st.sp - 8).toNat  st.x30)
                                (st.sp - 32).toNat st.x19)
                                (st.sp - 24).toNat st.x20)
        ((0x1000001c8 - (0x1000001c8 % 4096 - 1024 * 4096 + 8)).toNat)
        (st.sp - 1984))
     (st.sp - 8).toNat
   = st.x30
```

**The right-hand side is the entry state's x30; the left is a read of a slot
five writes deep, and the address it reads (`st.sp - 1984`) is not any of the
addresses written.** So `mem_read_after_write_u64` — which is in the emitted
simp set and is the right lemma when the read hits a written slot — does not
apply, and the obligation is not closed.

## Why it is true, and what it now takes

It is true, and the reason is that **the code generator reloads x30 from the
frame instead of leaving it in the register**. The block's step function is of
the shape

```lean
def count_b5_qT4 (st : Arm64State) : Arm64State :=
  { x0 := …, x30 := mem_read_u64 <the caller's stores> ((st.sp - 1984).toNat), … }
```

so `x30` is no longer `st.x30` definitionally; it is a load from the callee
frame's x30 slot, whose offset is set by the callee's own prologue. The
generator's `hx30fr_N` was written for a codegen that kept x30 in the register,
and it is now a statement about the callee's frame layout — which is exactly
what `FrameOk`'s memory clause and the `mem_read_write_below` /
`mem_read_write_pair_below` peels exist for.

So this is the hazard `CLAUDE.md` names, in its exact form: `gimple_codegen.py`-
style independence between the code generator and the proof generator. Nothing in
the generator is wrong about the MACHINE; the obligation it states is
unproved, and it is the only thing standing between the corpus and a proof.

## What it costs, measured

`formal/examples/count.mojo` and `pow2.mojo` on arm64, at HEAD after this
branch's other fix (`bugs/FORMAL_proof_coverage_census_2026-10-03.md` §5.1,
which removed three of count's five error sites):

| program | before that fix | after |
|---|---|---|
| `count` | 5 error sites (`hsrc_0` unknown identifier, an unsolved `hargeq`, `hspd`'s "Expected type must not contain free variables" ×3, and this `rfl`) | **1** — `hx30fr_5`'s `rfl` |
| `pow2` | (a 180 s wall breach in the census, so no verdict) | **1** — `hx30fr_5`'s `rfl`, at 167 s |
| `sqsum` | (a 180 s wall breach in the census, so no verdict) | **1** — `hx30fr_5`'s `rfl`, at 188 s |
| `fact` | not measured before | **1** — the same `rfl`, same reduced sides |
| `sum` | not measured before | **1** — the same `rfl`, same reduced sides |

(`python3 fire.py build --formal -o .tmp/f.aout formal/examples/<stem>.mojo`, one
at a time: each of these is a 150-300 s Lean run, and two concurrent runs at
Lean's own 6 GB ceiling is what breached an 8 GB reservation during the census
that found them. Every one reports the identical reduced obligation — the read at
`st.sp - 1984` against `st.x30` — which is what makes this one fact and not five.)

**None of the five is a regression from this branch, and that is measurable
without Lean at all.** At `master` every one of the five emits **4 references to
`hsrc_0` and defines exactly 1 `hsrc_N`** — the citation of a hypothesis nothing
binds, which is a hard Lean error wherever it appears. Generating the five proofs
on each side and counting the tokens (`formal.build.compile_formal`,
`prove=True, check=False`, no Lean):

| | `count` | `fact` | `pow2` | `sqsum` | `sum` |
|---|---|---|---|---|---|
| `master` — `hsrc_0` citations | 4 | 4 | 4 | 4 | 4 |
| this branch — `hsrc_0` citations | **0** | **0** | **0** | **0** | **0** |

So the five were red before this branch and are red after it with three fewer
error sites each; what is left is this one.

and the same `hx30fr_N` shape is what the `FrameOk` conjuncts hit in the same
walk, which is the second error site in `count`:

```
prog_proof.lean:5254:22: error: Tactic `introN` failed: There are no additional
binders or `let` bindings in the goal to introduce
case refine_1.refine_5.refine_1 …
⊢ mem_read_u64 (mem_write_u64 …) = st.x30
```

`refine_1.refine_5` is the **x30 conjunct of `FrameOk`** — `FrameOk` is a
15-conjunct `∧` (`lib/Refine.lean:171`: x19…x30, `sp`, and one `∀ j` window
clause), and the emitter opens all 15 holes and then emits `all_goals intro j hj`,
which only the window clause has binders for. The x30 hole is left open by the
preceding `simp … <;> all_goals try rfl` for the reason above, and then the
`intro` fails on it. So the two error sites are one bug: **the x30 conjunct is
not closed by `rfl`, and the emitter assumes every conjunct is.**

**The whole dec1 family is behind this one fact, and all five are MEASURED** —
`count`, `fact`, `pow2`, `sqsum`, `sum` are the five arm64 examples with a
recursive call in the corpus's `_dec1_pattern` shape, they all take the same
emitter path, and all five now fail with the identical obligation and nothing
else. `test_formal.py` lists none of them in `EXPECTED_FAILURES`, so on this tree
it reports **five** unexpected failures where it reported none on 2026-10-03
(`8d05d94e` verified `count` green at 43.8 s; `wdiff`, which has no call, still
passes). That is the size of this one fact: **12 % of the arm64 corpus.**

## The exact next step

0. **Add the `sp` premise** — §"What this costs the fix" above, which is the
   correction to this list and comes before it. Everything below is unreachable
   until the statement is true.
1. **`hx30fr_N` needs the callee's frame invariant, not `rfl`.** Concretely:
   find where `hx30fr` is emitted (`formal/arm64_proof_gen.py`, the `_halts`
   branch of `emit_block`, next to `hj_{bi}`/`hjump_{bi}`) and discharge it
   with the same chain the memory clause uses — `mem_read_write_below` /
   `mem_read_write_pair_below` at the offsets the callee's prologue actually
   wrote, with the read's own slot peeled last. `hj_{bi}` already exists in
   that block and cites `hx30fr_{bi}`, so the dependency direction is right;
   what is missing is the proof of `hx30fr` itself, and it must come BEFORE
   `hj`. The `hf` fact the FrameOk branch already builds
   (`131152 ≤ st.sp.toNat`, from `hbnd`) is the `sp` fact that chain needs.
   The generator's own comment at the emission site says the obligation is
   "value flow", which is what it has always been and is now load-bearing.
2. **The `FrameOk` conjuncts need per-conjunct tactics, not one `all_goals`.**
   The `refine ⟨?_,…⟩ <;> simp …` shape assumes all 15 holes close the same
   way. Since `FrameOk`'s shape is the library's (`lib/Refine.lean`), the
   honest fix is to name the 15 components and give the register conjuncts the
   `mem_read_write_below` chain while the window clause keeps `intro j hj` —
   one `all_goals` per conjunct kind. Doing this with `first | intro j hj |
   skip` instead would be worse than the error it removes: an unclosed conjunct
   would fall through to the emitter's `all_goals (first | done | sorry)` and
   become a silent hole, and a hole in a `FrameOk` conjunct is a false claim
   about the caller's frame.
3. **Then re-run the five.** Each is a 140-300 s Lean run (`wdiff` measured
   282 s on 2026-10-03), so budget `-j 1`; two concurrent runs at Lean's own
   6 GB ceiling is what breached an 8 GB reservation during this census.

## The correction: the emitted theorem is FALSE for an arbitrary `st.sp`

`hx30fr_5`'s reduced goal, verbatim from
`python3 fire.py build --formal -o .tmp/dump/count.aout formal/examples/count.mojo`
on this tree (`count_proof.lean:5330`, the `rfl` after the `simp +decide`):

```
⊢ mem_read_u64
     (mem_write_u64
       (mem_write_u64
         (mem_write_u64
           (mem_write_u64 (mem_write_u64 st.mem (st.sp - UInt64.ofNat 16).toNat st.x29) (st.sp - UInt64.ofNat 8).toNat
             st.x30)
           (st.sp - UInt64.ofNat 32).toNat st.x19)
         (st.sp - UInt64.ofNat 24).toNat st.x20)
       (UInt64.ofNat 4294968008 -
           (UInt64.ofNat 4294968008 % 4096 -
             ((if False then UInt64.ofNat 1024 - UInt64.ofNat (2 ^ 21) else UInt64.ofNat 1024) * 4096 +
               UInt64.ofNat 8))).toNat
       (st.sp - UInt64.ofNat 1984))
     (st.sp - UInt64.ofNat 8).toNat
   = st.x30
```

Read the nesting from the inside out — five stores, in the order they were
performed, and then one read:

| # | address | value |
|---|---|---|
| 1 | `st.sp - 16` | `st.x29` |
| 2 | `st.sp - 8` | `st.x30` |
| 3 | `st.sp - 32` | `st.x19` |
| 4 | `st.sp - 24` | `st.x20` |
| 5 | `PAGE` | `st.sp - 1984` |
| read | `st.sp - 8` | |

`PAGE` is `formal/model.py::stack_floor_address` — the stack-floor WORD, at an
ABSOLUTE address, which is why the read is five writes deep: stores 3, 4 and 5
sit between it and store 2. Stores 1-4 are the frame prologue, `sp`-relative,
and those are what `ctx["stores"]` and the peel machinery in
`_gen_universal_e2e_cfg` know about. **Store 5 is not `sp`-relative, so it is
in the model's chain and not in the generator's store list** — which is the
generator-side half of this.

And the theorem cannot be closed as stated, because `st.sp` is a free variable
and the fifth store can land on the read:

```
PAGE        = 4294968008 - (4294968008 % 4096 - (1024*4096) + 8) = 4299161592
st.sp       = PAGE + 8 = 4299161600          -- then (st.sp - 8).toNat = PAGE
hbnd        : FrameBound 131152 st 0   is   131152 * (0 + 1) <= 4299161600   TRUE
```

`FrameBound` (`lib/Refine.lean:293`) is `stride * (arg.toNat + 1) <= st.sp.toNat`
and nothing more, so `hbnd` holds for that `st`. The read then returns store
5's value, `st.sp - 1984`, and the goal asks Lean to prove
`st.sp - 1984 = st.x30`. **`count_compiles_correctly_universal` is therefore
false for a `st` it quantifies over**, and so is the `FrameOk` conjunct whose
goal is the same chain — the two error sites are two statements of one false
thing, which is why fixing the tactic without fixing the statement would have
made the build green and the theorem wrong.

This corrects §"What is NOT the cause" below, which said "this is incompleteness,
not unsoundness". That was right about the emitted theorem being *true in the
intended situation* and wrong about the statement, which quantifies over every
`Arm64State`.

## What this costs the fix

A premise. Nothing else in the file's step 1 can be reached before it, and the
premise has to be one the concrete entry state satisfies, or the concrete run
tests stop being about the binary.

The honest shape is a `sp` bound, and the generator has everything it needs:
the store address is `model.stack_floor_address(globals_base(fmt))` and
`formal/build.py::globals_base(fmt)` is the one computation of it for both
backends. So the universal theorem's binder list — which today is the frame
binder plus `hn : stride * (n.toNat + 1) + stride <= 2^64...`
(`formal/arm64_proof_gen.py`, `if fuel is None:` in `_gen_universal_e2e_cfg`) —
gains one more, of the form

```
(hspg : <stack_floor_address> + 8 + 8 + <the frame's deepest slot> <= st.sp.toNat)
```

which for `count` is `4299161592 + 24 <= st.sp.toNat`. That is what
`mem_read_after_write_u64_ne` then needs for store 5, and `omega` closes it
against `hbnd`'s `2^64 - …` shape; stores 1, 3 and 4 are the
`mem_read_after_write_u64_slot'` peels (`k + 8 <= j` with `k = 8`, so `j >= 16`
— every one of them), and store 2 is `mem_read_after_write_u64`.

Three things to decide, and the doc's own step list does not mention any of them:

1. **Is the premise `hbnd` or a sibling?** `FrameBound` is library-shared
   (`frameBound_succ` is how the recursion induction step works), so putting it
   there is a `lib/Refine.lean` change with a blast radius; a sibling binder on
   the theorem is a generator change with none. The sibling is the smaller and
   more honest one: the frame-vs-data-page separation is a property of THIS
   theorem's entry state, not of every frame claim in the library.
2. **The `tree_init` / `runProg` pair at the other two `Arm64State.init n …`
   sites** (`tree_init`, `init`) need the same premise, and `runProg`'s state
   (`lib/Refine.lean:112`) is the one `n` alone cannot describe — see
   `formal/arm64_proof_gen.py`'s `_via_prog`, which already routes a wider ENTRY
   around `runProg` for exactly this class of reason.
3. **What discharges it.** Nothing references
   `count_compiles_correctly_universal` today, so a premise is free — which is
   also why it is the dangerous shape: a premise nobody discharges is a weaker
   theorem that reads as a stronger one. `test_formal.py`'s dec1 examples and
   the run tests are what would have to say so.

## What is NOT the cause, so nobody re-derives it

* **Not the library.** `arm64_reg 30` is `s.x30` and the model's SP change
  (`528981bb`, register 31) does not touch register 30. The obligation's LHS is
  a plain record projection once the block function is unfolded; what is not
  plain is the VALUE the projection holds.
* **Not the model.** `arm64_step`'s store arm and the emitter's `STR` to the
  stack-floor word agree — the chain above is what the machine does. See
  §"The correction" above for what IS wrong, which is the theorem's `st`, not
  the model's step.
* **Not `count`'s other three error sites.** Those were the emitter naming a
  hypothesis it never emitted and unfolding with a one-block-deep simp set;
  they are fixed in `formal/arm64_proof_gen.py` on this branch and described in
  the census §5.1. Do not re-open them looking for this.