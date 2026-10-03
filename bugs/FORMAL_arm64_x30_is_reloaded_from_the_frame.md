# FORMAL_arm64_x30_is_reloaded_from_the_frame: the dec1 recursion family cannot be proved because the generator asserts x30 is unchanged and the code generator now RELOADS it

**Area:** FORMAL (the arm64 proof generator's per-instruction value flow).
**Status: OPEN, measured, with the exact next step.** Found 2026-10-03 by
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

## What is NOT the cause, so nobody re-derives it

* **Not the library.** `arm64_reg 30` is `s.x30` and the model's SP change
  (`528981bb`, register 31) does not touch register 30. The obligation's LHS is
  a plain record projection once the block function is unfolded; what is not
  plain is the VALUE the projection holds.
* **Not the proof's honesty.** The emitted theorem is TRUE — `(st).x30` is what
  the slot holds. This is incompleteness, not unsoundness, which is why the
  fix is a peel chain and not a change of the model.
* **Not `count`'s other three error sites.** Those were the emitter naming a
  hypothesis it never emitted and unfolding with a one-block-deep simp set;
  they are fixed in `formal/arm64_proof_gen.py` on this branch and described in
  the census §5.1. Do not re-open them looking for this.