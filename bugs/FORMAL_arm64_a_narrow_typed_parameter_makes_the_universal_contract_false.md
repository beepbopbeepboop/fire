# a TYPED narrow parameter makes the universal contract false: `⊢ t32s (t8s n) = n` is not true of an arbitrary `n`

**Area:** FORMAL (the arm64 proof generator's CFG walk, `emit_block`'s
branch handler). Found 2026-10-04 while measuring which CFG leaves admit.

**Status: OPEN, MEASURED, and it is red today.** `formal/examples/sgt8.mojo`
and `sle8.mojo` do not typecheck on this tree, they are not in
`test_formal.py`'s `EXPECTED_FAILURES`, and no `sorry` admits them: Lean
*rejects* the proof. So `test_formal.py` should be reporting two unexpected
FAILs and — with `count`, `fact`, `pow2`, `sqsum` and `sum` from
`bugs/FORMAL_arm64_x30_is_reloaded_from_the_frame.md` — seven.

Not fixed: closing it is a decision about what a typed parameter's range
hypothesis is, and both available answers change a theorem's statement rather
than its proof.

## What is there

```python
# formal/examples/sgt8.mojo
def sgt8(n: Int8) -> Int8:
    if n > 3:
        return 1
    else:
        return 0
```

The codegen narrows the incoming word to the declared type, faithfully, and the
generated block definition says so (`output/sgt8_proof.lean:3553`):

```lean
def sgt8_b0_qT4 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 19 (sgt8_b0_qS4 st) (t8s (arm64_reg 19 (sgt8_b0_qS4 st))))
def sgt8_b0_qT5 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 19 (sgt8_b0_qS5 st) (t32s (arm64_reg 19 (sgt8_b0_qS5 st))))
```

`sxtb` then `sxtw`. Nothing here is wrong.

What is wrong is the obligation the walk then derives from it. `emit_block`'s
branch handler pins each source variable's register in each PRIOR block, to
carry the condition's value into this one
(`formal/arm64_proof_gen.py:6597`, `have hprior_{bi}_{pb}_{v} : (s_{pb}).x{reg} = {v}`),
and for `sgt8` the variable is the parameter `n`:

```lean
have hprior_4_0_n : (s_0).x19 = n := by
  rw [hsid_0]
  simp only [sgt8_b0_qS0, …, sgt8_b0_qT5, arm64_reg, arm64_set_reg, …]
```

with the residual goal Lean reports, verbatim:

```
sgt8_proof.lean:4745:43: error: unsolved goals
⊢ t32s (t8s n) = n
```

**That is false.** The theorem's `n` is a `UInt64` with no range hypothesis —
`count`'s contract shape is the same, `hpc : st.pc = …`, `hx0 : st.x0 = arg`,
`FrameBound`, `hx30ret`, nothing about the argument's magnitude — and
`t32s (t8s n)` is `n` only for `n < 2^31`. So the walk is asking Lean to prove
the identity function on a word that the machine has just truncated.

Twelve diagnostics, all the same two shapes: four `unsolved goals` on
`hprior_4_0_n` (lines 4745, 4910, 5110, 5280 — the four blocks of the walk that
need the fact) and eight `The prover found a potentially spurious
counterexample` from the `grind` at lines 4760/4930/5130/5305, which is the same
obligation seen from `hcond_4`.

## Why it is not a CFG leaf, and why it was invisible

No `sorry` is involved: the obligation is a `have … := by` with a failing proof,
so Lean refuses the file and the hole census reads **0**. That is the whole
reason this sat unnoticed while
`bugs/FORMAL_trust_audit_2026-10-04.md` went through the generator's admissions
and found nothing wrong with them — the audit read the `sorry`s, and this is not
one.

It surfaced while replacing the CFG leaves' fallbacks, because stripping them
turns "the proof elaborates" into "the proof says which line failed", and the
first non-leaf line that failed was this one.

## The two ways to close it, and which is honest

1. **Give the contract the range hypothesis.** `Post`/`contract_sound` would
   carry `n < 2^(8k-1)` (or the two-sided version) alongside `hx0`, and every
   caller already knows the bound it passed. This makes the statement TRUE and
   the existing `hprior` obligation provable by `simp` — `t32s_t8s` is already
   in `tw_extra` and is exactly this lemma with the hypothesis. It also widens
   `lib/Refine.lean`'s `Post` and `contract_sound`, which every recursive
   example depends on, so it is not a one-file change.
2. **Do not narrow at the entry.** If the codegen did not `sxtb` the incoming
   argument, `t32s (t8s n) = n` would never arise — but then the machine would
   disagree with the source on every `Int8`/`Int16` parameter whose value is out
   of range, which is the narrower bug and the wrong place to fix it.

(1) is the real fix and (2) is the tempting one. The reusable piece is
`t32s_t8s` with its side condition stated rather than assumed.

## Reproduce

```console
$ python3 -c "import sys; sys.path.insert(0,'.'); import formal.build as fb; \
    r = fb.compile_formal('formal/examples/sgt8.mojo', arch='arm64', \
                          output='.tmp/sgt8.aout', prove=True, check=False); \
    from formal.lean import check_proof_cached; \
    print(check_proof_cached(r['proof_path'], repo_root='.')[:1])"
False
```

Generation is ~1 s; the Lean run is ~3 min and 2.7 GB.
