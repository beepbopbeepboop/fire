# `runs-cbz-condition`: the CBZ that tests the STACK-FLOOR word, so the leaf admits an obligation no tactic can reach

**Area:** FORMAL (the arm64 proof generator's CFG walk, `emit_runs`' `cbz`
arm). Claim `project22:arm64-cfg-leaves`.

**Status: OPEN, PARTIAL LANDED (2026-10-04, `work/formal23-2`), and the
SUBJECT of this document is misidentified — which is the finding.** The
register this leaf tests is **not** a literal-pool word and the `@require` guard
emits no code at all: it is `_emit_stack_floor_guard`'s own
`ADRP+ADD X17, &floor ; LDR X16, [X17] ; CBNZ X16, done`, reading the floor
word in `__DATA`, and the address in the quoted goal is exactly
`model.stack_floor_address(0x100400000)`:

    >>> hex(model.stack_floor_address(0x100400000))
    '0x100400008'          # 4299161608, the literal in the residual goal

So §"What is left to decide" below — the `native_decide` experiment, and the
lemma it would produce, "the value at a pool address is a function of `code`" —
**cannot work and should not be run**: the address is in `__DATA`, it is read
through `st.mem` and not through `code`, and the word there is one the PROGRAM
writes (the first caller stores `SP - BUDGET`), so relating it to the image
would be false. §"What was measured, and where" is still right about the census.

**What landed.** `emit_runs`' `cbz` arm now peels the frame stores off the
tested register's load before the leaf
(`mem_read_after_write_u64` / `mem_read_after_write_u64_ne`, `decide` as the
discharge), which reduces the obligation to its minimal form and makes the
diagnosis legible — the ADRP expression is gone and the goal is one
`mem_read_u64` at a literal address. Pinned by
`test_formal_call_proof_gen.py::TestCfgLeafCensus::test_the_cbz_leaf_peels_the_frame_reads_before_it_admits`,
which pins the REDUCTION and not a pass.

**What the reduction settles, and it is stronger than "unproved".** The residual
is

    ⊢ mem_read_u64
          (mem_write_u64 (mem_write_u64 (mem_write_u64
              (mem_write_u64 st.mem (st.sp - 16).toNat st.x29)
              (st.sp - 8).toNat st.x30)
              (st.sp - 32).toNat st.x19)
              (st.sp - 24).toNat st.x20)
          4299161608
        = 0

**which is FALSE for an arbitrary `st.mem`, so this is not a true claim the
model cannot decide — it is a false obligation, because the theorem's `st` has
unconstrained memory.** `Arm64State.init` is the only place that says memory is
zero (`mem := fun _ => 0`), and the universal theorem quantifies over every
`Arm64State`. The doc's own reading of the situation — "both values of the pool
word are live states of the theorem, and the theorem can only be true if the two
arms agree" — is therefore not a question about this example at all: with
`mem` free the branch is undecided in BOTH directions, so "do the two arms agree"
is not well posed in the theorem as stated. What is left is a `lib/Refine.lean`
hypothesis, and §"The next step" says which.

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
the ADRP materialisation of a word in `__DATA`. **That word is the stack-floor
word, not a literal-pool slot** (the Status section has the arithmetic), so the
name in the rest of this document is wrong and the conclusion drawn from it is
wrong with it. The stores on the left are the four frame slots at
`sp - 8/16/24/32`; the floor address is none of them, so the frame writes cannot
decide the read, and nothing else in the file relates `mem` at that address to
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
cannot see: the value is behind an `LDR`, so the scan clears x16 on the load and
returns `None`. **But that mechanism must NOT be extended to cover it**, which
the original reading of this document asked for and which would be wrong: the
image's own floor word is non-zero from the second call onwards, so "statically
non-zero" is true of the MACHINE and false of the MODEL (`st.mem` is zero there
until the walk's own store), and `hne_{bi} : arm64_reg 16 s_cur ≠ 0` would be
unprovable — and asserting it would be asserting something false about the
model. What is needed is not a constant but a MEMORY fact; see the next
section.

## What is left to decide — SUPERSEDED, and the answer is in the Status

The section this replaces proposed one `native_decide` experiment: run the
compiled `count` with `mem` overwritten at the loaded word, and see whether the
two arms of the `CBNZ` leave the same value in x0. **Do not run it.** It asks
whether the leaf admits a false claim or a true-but-unprovable one, and that
question is not well posed: with `st.mem` free the branch is undecided in both
directions, so there is no pair of arms to compare. It also assumed the loaded
word is a function of `code`, which is false for the stack-floor word — the
program writes it.

What replaces it is a measurement of the reduced goal, which the landed peel
makes possible, and it is the whole of what is now known:

```
$ python3 tools/memslot.py --gb 8 --label lean-count -- python3 .tmp/lean_count.py output/count_nohole.lean
OK False cached False sorries 0
errors: 9
   count_nohole.lean:5249:32: error: unsolved goals      ← this leaf, before
   count_nohole.lean:5284:32: error: unsolved goals      ← this leaf, before
   count_nohole.lean:5330:16: error: Tactic `rfl` failed        (formal21-3)
   count_nohole.lean:5364:22: error: Tactic `introN` failed  ×4 (formal21-3)
   count_nohole.lean:5406:32: error: unsolved goals      ← a recursion branch
   count_nohole.lean:5434:32: error: unsolved goals      ← a recursion branch
memcap: done, peak 4.2 GB across up to 2 procs (ceiling 8.0 GB)
```

(the harness is the doc's own "Reproduce" below with `repo_root=os.getcwd()` —
`repo_root='.'` makes `lean.py` build a RELATIVE `LEAN_PATH` and Lean answers
`unknown module prefix 'ProofLib'`, and the CAS then caches that verdict under
the proof's bytes, so a re-run needs a one-byte change to the file to be
re-measured at all. Both are recorded because both cost an hour.)

## The next step: a MEMORY hypothesis, not a constant

The theorem quantifies over every `Arm64State`, and `st.mem` is one of its
fields, so nothing in it says the machine's memory outside its own frame is
zero. `Arm64State.init`'s `mem := fun _ => 0` says it for the CONCRETE run and
for nothing else. The missing statement is the same shape as `FrameBound`, and
`FrameBound` is where to put it — `lib/Refine.lean:512`, next to it, as its
sibling:

```lean
abbrev FrameBound (stride : Nat) (st : Arm64State) (arg : UInt64) : Prop :=
  stride * (arg.toNat + 1) ≤ st.sp.toNat
```

Something of the shape "this frame's stores are the only ones below `sp`, so
`st.sp - K ≤ a → st.mem a = 0` for every `K` the emitter can have written" —
which is precisely what makes `mem_read_u64 (four frame stores) 4299161608 = 0`
follow by `mem_read_after_write_u64_ne`, since `FrameBound` already puts
`st.sp` near 2^64 and the floor address is at `0x100400008`.

What it costs, and it is a project rather than a patch:

* the hypothesis has to be **discharged for the initial state** (where it is
  `rfl`/`decide`, because `init`'s `mem` is the constant-zero function) and
  **carried through the frame contract** — `frameBound_succ` and its siblings
  are the pattern, and each needs the memory fact to survive a `BL`;
* every arm64 proof that reaches a memory load from outside its own frame is
  regenerated and re-checked, which is a full Lean sweep, not a single example
  — `count` alone cannot show the change is sound;
* and the shape of the hypothesis is a value-model decision, not a tactic: a
  program that legitimately maps memory low (a `malloc`'d buffer below 2^32, an
  `mmap`) would falsify it, and this path's allocator has to be checked for that
  before the hypothesis is stated as universal. `bugs/PERF_memory_over_4gb_is_a_bug.md`'s
  standard applies to the decision, not to the code.

Until that lands the leaf admits, and it is the only one of the fifteen that
does.

## What is already measured, and where

`runs-cbz-condition` is the only site of the fifteen that admits in the corpus
measured so far. Over the 47 examples of `formal/examples` that generate an
arm64 proof:

| | leaves reached | admits (Lean, fallbacks stripped) |
|---|---|---|
| `walk-terminal` | 324 | 0 — `identity` (4 leaves) and `wdiff` (4) |
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
looked because the leaf it also admits was invisible. **Re-measured
2026-10-04** on this tree's tip and unchanged in every figure: 9 diagnostics, of
which 5 are `formal21-3`'s and **4** are this leaf — the two floor-guard CBZs
above plus two RECURSION branches (`count_proof.lean:5406`, `:5434`), which the
table's "2 of 6" did not separate out. The recursion branches carry
`have hne_6 : arg ≠ 0` and are a different subject (`∀ n, n ≠ 0 → count n = …`
against a branch the walk forces), so they are left here rather than merged into
this document's claim; a reader counting this leaf should count four, not two.

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
    "output/count_nohole.lean", repo_root=os.getcwd())   # ABSOLUTE: see above
print(detail.splitlines()[4])        # the leaf, by name
```

Both functions and the whole registry are pinned by
`test_formal_call_proof_gen.py::TestCfgLeafCensus`, which is why the corpus
figures in the table above are reproducible and not a reading of line numbers.
