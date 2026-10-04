# `runs-cbz-condition`: the CBZ the `@require` guard emits tests a LITERAL POOL word, so the leaf admits an obligation the contract's hypotheses cannot decide

**Area:** FORMAL (the arm64 proof generator's CFG walk, `emit_runs`' `cbz`
arm). Claim `project22:arm64-cfg-leaves`.

**Status: OPEN, and the shape of it is measured.** The obligation left open is
quoted verbatim from a real Lean run, the structural reason it is not derivable
is named, and §"What is left to decide" is the one measurement that turns
"cannot be proved" into "is not true". Not fixed: closing it needs a relation
between the machine's `mem` and the image's literal pool, which is a model
change and not a tactic.

Found while replacing the CFG leaves' `sorry` fallbacks
(`formal/arm64_proof_gen.py`'s `CFG_LEAF_SITES`, added by the commit that
names them). Until they were named, this leaf was indistinguishable from the
other seven.

## The obligation, verbatim

`formal/examples/count.mojo`:

```python
@spec(count_spec; count_spec 0 = 0; count_spec (n+1) = count_spec n)
@require(n >= 0)
def count(n):
    if n == 0:
        return 0
    else:
        return count(n - 1)
```

Generated `count_proof.lean`, the CBZ at `0x1000002e4` inside the walk of the
base case (`count_contract`, second section), with the leaf's admission
replaced by `done` so that Lean names it:

```lean
have hs_0 : arm64_step (s_0) count_code = some ({ s_0 with pc := 4294968024 }) := by
  have hsr := count_sr_13 (s_0) hpc_0
  rw [hsr]
  ...
  all_goals (first | done)  -- arm64-cfg-leaf: runs-cbz-condition
```

```lean
count_proof.lean:5249:25: error: unsolved goals
⊢ some
      (if mem_read_u64 (mem_write_u64 (mem_write_u64 (mem_write_u64
                        (mem_write_u64 st.mem (st.sp - UInt64.ofNat 16).toNat st.x29)
                                       (st.sp - UInt64.ofNat 8).toNat  st.x30)
                        (st.sp - UInt64.ofNat 32).toNat st.x19)
                     (st.sp - UInt64.ofNat 24).toNat st.x20)
                 (UInt64.ofNat 4294968008 -
                     (UInt64.ofNat 4294968008 % 4096 -
                       ((if False then UInt64.ofNat 1024 - UInt64.ofNat (2 ^ 21)
                                 else UInt64.ofNat 1024) * 4096 + UInt64.ofNat 8))).toNat
       ≠ 0
      then { ... pc := (UInt64.ofNat s.pc + UInt64.ofNat 16).toNat ... }
      else { ... pc := s.pc + 4 ... })
    = some { ... pc := 4294968024 ... }
```

Two of `count`'s six `runs-cbz-condition` leaves are open this way (lines 5249
and 5284 of the same file); the other four close.

## Why it is not derivable, which is a fact and not an opinion

The branch is a `CBNZ` on x16, and x16's value at that point is

```lean
mem_read_u64 (frame stores over st.mem) <pool address>
```

where `<pool address>` is `4294968008 - (4294968008 % 4096 - 1024*4096 - 8)`,
the ADRP materialisation of a **literal-pool slot inside the image**. The
stores on the left are the four frame slots at `sp - 8/16/24/32`; the pool
address is none of them, so `mem_read_after_write_u64` — the lemma that is in
the emitted simp set and is the right one when a read hits a written slot — does
not apply, and nothing else in the file relates `mem` at that address to
anything.

The contract makes that unfixable within the walk.
`lib/Refine.lean:501`'s `Post` is claimed by `count_contract` for **every**
entry state:

```lean
theorem count_contract (fuel : Nat) (arg : UInt64) (st : Arm64State)
    (hfuel : 43 + 43 * arg.toNat ≤ fuel)
    (hpc : st.pc = 4294967988) (hx0 : st.x0 = arg) … :
    Post count_prog fuel mojo st arg
```

and `st.mem : Nat → UInt8` is unconstrained by `hpc`, `hx0`, `FrameBound` and
`hx30ret`. So both values of the pool word are live states of the theorem, and
the theorem can only be true if the two arms agree.

`formal/arm64_proof_gen.py` already knows how to retire the other half of this
and does: `_cbz_reg_const` scans a block's prefix for a register holding a
compile-time constant and, when that constant is non-zero, emits

```lean
have hne_{bi} : arm64_reg {r} {s_cur} ≠ 0 := …
exact absurd hc_{bi} hne_{bi}
```

— "the taken arm is statically dead". This leaf is the case `_cbz_reg_const`
cannot see: the constant is behind an `LDR` from the pool, so the scan clears
x16 on the load and returns `None`. The generator's existing mechanism is right
and its blind spot is exactly a literal-pool load.

## What is left to decide, and it is one `native_decide`

Whether the leaf is admitting a **false** claim or a true-but-unprovable one
turns on a single question: do the two arms of that `CBNZ` leave the same value
in x0? Do not assume either answer.

```
$ python3 - <<'PY'
import sys, os; sys.path.insert(0, os.getcwd())
import formal.build as fb
r = fb.compile_formal('formal/examples/count.mojo', arch='arm64',
                      output='.tmp/count_decide.aout', prove=True, check=False)
print(r['proof_path'])
PY
```

then, in a scratch file importing that proof's own `count_code` /
`count_prog`, evaluate

```lean
example : (match arm64_exec_go_exit { (Arm64State.init 10 4294967968)
                                      with x30 := UInt64.ofNat 4294968164 }
            count_code 200000 with
          | some s => s.x0 | none => 0) = mojo 10 := by native_decide
```

and the same with `mem` overwritten at the pool word
(`mem_write_u64`-style, or `Arm64State.init`'s `mem` composed with a function
that is non-zero at that address only). Two answers:

* **they differ** — `count_contract` is FALSE as stated, which is the sharpest
  entry in `FORMAL.md` §7 and needs its own row there, and the fix is to
  constrain the contract's `st` (or to make `mem` the image's memory, which is
  the honest reading of a freestanding image and a much larger change);
* **they agree** — the claim is true and unproved, and the fix is a lemma: the
  value at a pool address is a function of `code`, so `code`-relative facts
  about literal slots are the reusable piece (one `native_decide` per slot, and
  `_cbz_reg_const` grows an `LDR`-from-pool case).

Either way the first change is the same and it is small: teach
`_cbz_reg_const` to read the constant an `ADR`/`ADRP`+`LDR` pair materialises,
so the leaf emits a fact instead of a question.

## What is already measured, and where

`runs-cbz-condition` is the only site of the fifteen that admits in the corpus
measured so far. Over the 47 examples of `formal/examples` that generate an
arm64 proof:

| | leaves reached | admits (Lean, fallbacks stripped) |
|---|---|---|
| `frame-contract-terminal` | 324 | 0 — `identity` (4 leaves) and `wdiff` (4) |
| `runs-cbz-condition` | 36 | **2 of 6 in `count`** |
| `runs-ret-x0` / `-x30` / `-frame-ok-window` | 12 each | 0 in `count` (which is red for another reason — below) |
| `runs-bl-step` | 7 | 0 in `count` |
| `dec-while-back-edge-decrement` / `-frame-slot` | 12 each | 0 in `wdiff` |
| `loop-cond-flag` / `loop-cond-step` | 3 each | 0 in `wdiff` |
| the five `range-loop-*` sites | 0 | unreachable in this corpus |

**`count` is red today for an unrelated and already-documented reason**, so its
two admissions are not currently visible in any suite: its `hx30fr` fact fails
at proof line 5330 and the `FrameOk` window's `intro j hj` fails at 5364, which
is `bugs/FORMAL_arm64_x30_is_reloaded_from_the_frame.md` (claimed by
`work/formal21-3`). `count` is NOT in `test_formal.py`'s `EXPECTED_FAILURES`, so
`test_formal.py` should be reporting it as a FAIL on this tree; nobody has
looked because the leaf it also admits was invisible.

Reproduce the second half with no Lean at all (the first is generation, ~1 s per
example; the census over all 47 is ~2 s):

```python
import sys, glob, os; sys.path.insert(0, ".")
import formal.arm64_proof_gen as G
for f in sorted(glob.glob("output/*_proof.lean")):
    print(os.path.basename(f), G.cfg_leaf_census(open(f).read()))
```

and to see WHICH leaf admits, strip the fallbacks and read Lean's own
diagnostics — every tagged line that reports `unsolved goals` is a leaf that
admitted:

```python
import formal.build as fb, formal.arm64_proof_gen as G
from formal.lean import check_proof_cached
r = fb.compile_formal("formal/examples/count.mojo", arch="arm64",
                      output="output/count.aout", prove=True, check=False)
text = G.no_admission_fallback(open(r["proof_path"]).read())
open("output/count_nohole.lean", "w").write(text)
ok, detail, cached, n = check_proof_cached(
    "output/count_nohole.lean", repo_root=".")
print(detail.splitlines()[4])        # the leaf, by name
```

Both functions and the whole registry are pinned by
`test_formal_call_proof_gen.py::TestCfgLeafCensus`, which is why the corpus
figures in the table above are reproducible and not a reading of line numbers.
