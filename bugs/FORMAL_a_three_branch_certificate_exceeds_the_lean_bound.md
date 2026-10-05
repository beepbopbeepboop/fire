# FORMAL_a_three_branch_certificate_exceeds_the_lean_bound: the cost is the
# per-PATH value-flow facts, and everything the earlier rounds blamed for it
# checks in 23 seconds

**Status: the DIAGNOSIS is wrong in both of its earlier rounds and is corrected
here, with the measurements; the blowup itself is NOT fixed.** Found while
landing the bit-test proof arm (whose doc is deleted with it) and re-measured
2026-10-03 on this tree, with the measurement the earlier rounds did not take.

## 2026-10-05 (`work/formal31-2`): the boundary has MOVED to four branches, the
## concrete theorem is NOT the cost, and `hprior` is 4% of the walk theorem

**Three measurements, none of which re-verifies anything the sections below
say, and all three of which change what the next step should be.** Every number
below is on this tree; the program is §6's, generated with the proof check
stubbed out so no Lean run is involved in producing the `.lean`, and the Lean
runs are through `formal/lean.py::run_lean` under `tools/memslot.py --gb 8`.

**1. The failure is at FOUR branches now, not three.** The same §6 program that
§1 records as a kernel OOM at 6.1 GB in 202 s **checks at three branches**
(`rc=0`, 5.26 GB peak, ~110 s), and the 2-branch case is 3.09 GB. The
four-branch case **breaches an 8 GB ceiling and is killed by `memcap`** — which
is the `RESOURCE` verdict `CLAUDE.md` describes, i.e. NOT a verdict on the
proof: the process died for memory before it finished. So a reader who came
here to reproduce §1 finds a program that passes, and the thing that reproduces
is one branch further on. **That is worth knowing before anything else**, because
the whole of §4's argument ("a program that proves at two branches stops
building at three") is a statement about a threshold that moved.

| conditional branches | proof lines | `..._compiles_correctly_universal` | its `have` lines | `hprior` | `hsid`/`hcert`/`hrun_ex`/`hexit`/`h_adv` | `hpc*` | Lean |
|---:|---:|---:|---:|---:|---:|---:|---|
| 2 | 4 129 | 1 752 | 582 | 24 (**4.1 %**) | 230 (39.5 %) | 91 | **rc=0, 3.09 GB** |
| 3 | 6 452 | 3 616 | 1 198 | 48 (**4.0 %**) | 470 (39.2 %) | 187 | **rc=0, 5.26 GB** |
| 4 | 10 671 | 7 376 | 2 430 | 96 (**4.0 %**) | 950 (39.1 %) | 379 | **killed at the 8 GB ceiling** |

**2. The concrete theorem and its `native_decide` are NOT the cost.** §2's
table makes the theorem sound like the place, and the plausible reading of it is
that a 114 000-step `native_decide` is what fills the kernel. It is not:

| what | result |
|---|---|
| the whole file | rc=0, **5.26 GB** |
| the same file with the theorem's `114000` replaced by `11400` | rc=0, **5.21 GB** — a tenth of the fuel, the same memory |
| the same file with the theorem's `native_decide` replaced by `sorry` | rc=0, **5.27 GB** |
| everything up to `f_compiles_correctly_universal` | rc=0, **1.47 GB** |

So the cost is neither the step count nor the theorem: it is the walk theorem,
which is **3 616 of the file's 6 452 lines** and holds 1 198 of its 1 198
`have`s. `arm64_exec_go`'s fuel is a bound and the generator hands it a generous
one, which is why lowering it changes nothing — worth knowing, because
"the fuel is too big" is the next thing a reader would try.

**3. `hprior` is 4% here, not the ×3-per-branch family §3 measures, and the
five per-VISIT families are 39%.** The Status above already says the
duplicated-statement hypothesis is right and the scope is wrong; this is the
same conclusion from the other side, on a program whose `hprior` count DOUBLES
(24 → 48 → 96) where §3's table measured a tripling (48 → 144). **§3's "×3.0,
×2.67, ×2.5" is a property of that program's condition shape** (`not (n & 4)`
lowers to two instructions and two branches), not of the family. On this shape
every row doubles, `hprior` included, and the 4%-share is flat across all three
rows. So "hoist the `hprior` facts" removes 4% of the emission — §5 step 1's
own number, now reproduced — and the thing that would have to change is the
per-visit emission: `hsid`, `hcert`, `hrun_ex`, `hexit` and `h_adv` are 39% and
`hpc*` is another 16%, and all six exist once per (PATH, BLOCK) visit.

**And one structural reason the hoist cannot be a rename, which the code
already records and §5 step 1 does not.** `s_{bi}` is introduced by
`rcases hrun_ex_{bi} with ⟨s_{bi}, hrun_{bi}⟩` **inside each path's own tactic
branch**, so the proposition `(s_4).x5 = n` on one path and on another are two
different statements about two different bindings of the same name —
`formal/arm64_proof_gen.py`'s `hprior_memo` comment says so ("a fact proved in
ONE branch of the walk is not in scope in a sibling, because `s_{pb}` is
REBOUND per path … that is the most that is sound without changing what
`s_{pb}` is"). `tools/formal_hprior_census.py`'s duplicate column counts
identical STATEMENT TEXT, so the 42-61% it reports is not shareable text: it is
the same sentence about different locals. **Hoisting therefore needs `s_{bi}` to
mean one thing per block rather than per visit**, and that is a change to what
the walk emits, not to where it emits it.

**What this does NOT change:** the blowup is still real, it is still
exponential in the number of conditional branches, and §5's ordering still holds
with `hprior` replaced by "the per-visit facts" as the subject. Nothing here is a
fix.

**The Lean harness that works, because §6's warning is right and the numbers
differ.** §6 says `ensure_library` peaks at 7.82 GB and to build private oleans
instead; measured here, that build peaks at **1.4 GB** (six `lean -o` calls,
`LEAN_PATH` pointed at a scratch directory, ~40 s for `ProofLib.olean`'s 31 MB
and the rest), and a proof run against those private oleans peaks at 3.1 GB
(two branches) and 5.3 GB (three). `lean_flags(mb, heartbeats, threads)`'
`mem_mb` is left unset, so Lean's own `maxMemory` is whatever the toolchain
defaults to; the 8 GB ceiling is `tools/memslot.py --gb 8`, not Lean.

    # private oleans, then a run — everything through run_lean, never `lean` direct
    export PATH=/opt/homebrew/bin:$PATH
    LEAN=$(python3 -c 'import sys;sys.path.insert(0,".");import formal.lean as L;print(L.find_lean())')
    mkdir -p .tmp/lib
    for m in ProofLib X86 work Refine Contracts IEEE754; do
      python3 tools/memslot.py --gb 8 --label lib -- \
        env LEAN_PATH=$PWD/.tmp/lib $LEAN -o .tmp/lib/$m.olean lib/$m.lean
    done
    python3 tools/memslot.py --gb 8 --label lean -- python3 .tmp/checklean.py \
      .tmp/tb/b3_proof.lean .tmp/lib        # rc=, exceeded=, peak, output

`checklean.py` is `formal/lean.py::run_lean` with `LEAN_PATH` =
(`dirname(proof)`, the private lib dir), `cwd` = the proof's directory,
`wall_s=1500 cpu_s=5400`; eleven lines, and scratch rather than committed for
§6's reason. **One trap this pass cost an hour on**: `LeanRun`'s memory field
is `peak_rss`, not `peak`, and the generated proof `import`s `work`, so a
library build that skips `work.lean` fails with `unknown module prefix 'work'`
rather than with anything about the proof.

**Update 2026-10-04 (formal21-2): the DUPLICATE measurement §5 step 1 asked for
is taken, with a committed instrument, and it CORRECTS the diagnosis above: the
exponential is not one family's, so hoisting `hprior` alone would not have
fixed the blowup. `tools/formal_hprior_census.py` walks an emitted `.lean` and
reports each family's count and how many of its facts carry a statement another
one also carries. Nothing here runs Lean.**

| conditional branches | proof lines | `have` lines | **duplicated statements** | `hprior` | `hsid` / `hcert` / `hrun_ex` / `hexit` / `h_adv` |
|---:|---:|---:|---:|---:|---:|
| 2 | 4 934 | 1 946 | — | 12 | 12 each |
| 3 | 6 942 | 3 939 | **1 643 (42%)** | 48 | 46 each |
| 4 | 10 130 | 5 924 | — | 144 | 96 each |
| 5 | 15 814 | 7 329 | **4 505 (61%)** | 384 | 190 each |

Two things fall out of that table, and the second is the one that changes the
next step.

1. **The `hprior` facts are 88-97% duplicates** (384 facts, 315 duplicated
   statements at five branches; 48 and 31 at three). §5 step 1's hypothesis is
   right about them.
2. **They are 5% of the emission.** `hsid`, `hcert`, `hrun_ex`, `hexit` and
   `h_adv` each grow 46 → 190 from three branches to five, i.e. 2x per branch —
   because each is emitted once per PATH that reaches its block, which is the
   same structural cause `hprior` has. `hprior` grows fastest (48 → 384, 8x)
   only because it is 2x per branch TIMES the prior blocks on the path. So the
   growth is a property of emitting per-path block facts at all, and `hprior`
   is the largest single consumer rather than the cause.

**Consequence for §5, stated so nobody re-derives it: step 1 as written ("share
the `hprior` facts across paths") removes 5% of the emission and cannot have
fixed a 202 s / 6.1 GB kernel OOM.** It is also not implementable as written, and
that is the second measurement: `hprior_{bi}_{pb}_{v}` is emitted inside
`emit_block`'s per-path term, and `hsid_{pb}` beside it — so the fact is not in
scope for a later path and renaming it to drop `bi` is necessary and not
sufficient. The counts of `hsid` per block say the same thing from the other
side: 1, 1, 2, 4, 8, 16, 32, 64 occurrences at increasing indentation, i.e. the
block locals are emitted per path as well.

**So the next step is the HOIST, and it is one mechanism rather than nineteen
families: emit each block's facts ONCE, at the shallowest indentation that can
see them, and reference them by name.** That is what the duplicate column
measures — 61% of the emission at five branches is a fact another one already
states. §5 step 2 ("emit that composition ONCE per block as a named local, the
shape `hsid_{pb}` already has") is the same move one level down and is the right
place to start, because `hsid_{pb}` is the fact every other per-path fact is
stated in terms of.

**What was NOT attempted here, and why, stated so nobody re-derives it.** This
change is in `formal/arm64_proof_gen.py`, whose output can only be checked BY
LEAN, and a light worker's ceiling is 8 GB (`tools/memslot.py`) while the proof
needs more than that to get past its own midpoint — the 2M-heartbeat run peaks
at 4.2 GB and the full run at 6.4. So the fix can be *written* under the ceiling
and not *verified* under it, and every measurement above was made at or under
the ceiling by NOT running Lean at all.

**The one-line version:** the whole-program certificate for a function with
THREE conditional branches does not finish on this tree, and it is neither
`_gen_run_cert`'s composed-state walk nor `runProg` nor the `hx30` goal that all
three of the docs this spawned name. It is `formal/arm64_proof_gen.py:6143`'s
`for _pb in _prior_blocks:` — the `hprior_*` value-flow facts — which are
re-emitted once per PATH through the CFG, so their number is exponential in the
number of conditional branches, and their proofs each re-unfold a block's whole
composed state. (The 2026-10-04 measurement below says that family is the largest
consumer of a growth that is structural, and that the hoist is the fix.)

## 1. The failure, as it is now (2026-10-03, this tree)

**SUPERSEDED by the 2026-10-05 Status above, which moves this boundary to FOUR
branches: the three-branch program below now checks at 5.26 GB.** What is kept
is the failure MODE — a kernel OOM rather than a wall-clock bound — because the
four-branch case now dies the same way and at a higher ceiling.

```console
$ python3 tools/memslot.py --gb 8 --label lean -- python3 .tmp/f19/leanrun.py 420 \
      python3 fire.py build --formal -o .tmp/three.out --backend=arm64 .tmp/three.mojo
exit=1 wall=201.9s
build: proof check failed: three_proof.lean:6035:8: error: (kernel) excessive
memory consumption detected
memcap: peak 6.1 GB across up to 3 procs
```

**The failure MODE has changed and the old record is wrong about it.** This doc
used to report `lean exceeded 1500s wall`. On this tree the same program dies of
a kernel OOM at **6.1 GB in 202 s** — inside the bound, with a different error.
A reader who came here to raise the bound would find nothing to raise.

## 2. Where the time goes, measured (this is the part the earlier rounds missed)

Three runs of the SAME generated proof through `formal/lean.py::run_lean`,
under the same 8 GB ceiling, with the program spliced at three points. No
generator was changed for any of them.

| what is in the file | result |
|---|---|
| everything up to the final theorem (10 129 lines: every block cert, every `qS`/`qT` chain, **all 32 `hx30` goals**, all 144 `hprior` goals' statements) | **rc=0, 23.1 s, 2.5 GB** |
| the above plus the theorem's STATEMENT alone — `(match runProg f_prog n with …) := by sorry` | **rc=0, 22.1 s, 2.5 GB** — the statement is free |
| the whole file | kernel OOM at 6.1–6.4 GB, 202–299 s |

So: **`hx30` is not the expensive thing.** All 32 of those goals — the whole
chain `simp only […qS0, …qT23, arm64_reg, arm64_set_reg, Arm64State.init]`
that `FORMAL_csel_in_the_model_costs_a_ternary_export_its_whole_proof.md`
prescribes rewriting as per-step lemmas — are inside the 23 seconds. And
`runProg`'s reduction, which the error POSITION (`6035:8`, the theorem's own
header) points at, is inside the 22.

Localising further, by lowering `maxHeartbeats` so the error names a tactic
instead of the kernel:

| `maxHeartbeats` | where it stops | wall | peak |
|---|---|---|---|
| 400 000 | `three_proof.lean:8156` — the first `hsrc_4 := hcond_4.mp hc_4` | — | 2.8 GB |
| 2 000 000 | `:8270` — the `hcond_8` goal's `by_cases h : … <;> simp [h, Arm64State.init] <;> bv_decide`, plus a `simp` failure at the same line | 103 s | 4.2 GB |
| 5 000 000 / 10 000 000 | kernel OOM at `6036:0` | 212 s / 299 s | 6.4 GB |

**Heartbeats accumulate over the whole declaration, not per tactic**, so the
middle row is a position on a path and not a single hot tactic. What it does
establish is that the walk gets about 56 % of the way through the theorem before
the kernel gives up, and that the `hcond_*` goals are in the expensive
neighbourhood.

## 3. The growth, and it is not the thing the docs name

Four programs that differ only in how many `if`s they have, generated with the
proof check stubbed out (`formal.lean.check_proof_cached` replaced by a no-op —
the emission is what is being counted, so no Lean run is involved):

| conditional branches | proof lines | **`hprior_*`** | `hx30_*` | `hcond_*` | `hcbz_*` | basic blocks |
|---:|---:|---:|---:|---:|---:|---:|
| 2 | 6 941 | **48** | 16 | 12 | 15 | 8 |
| 3 | 10 129 | **144** | 32 | 28 | 31 | 10 |
| 4 | 16 360 | **384** | 64 | 60 | 63 | 12 |
| 5 | 27 887 | **960** | 128 | 124 | 127 | 14 |

**`hprior` is the only row that grows faster than 2x per branch** (×3.0, ×2.67,
×2.5) and it is 7.5x the count of `hx30` at three branches. `hx30` merely
DOUBLES, which is consistent with it being one per path-end rather than one per
(path, prior block, variable). The docs' shared theory — "`_gen_run_cert`'s
composed-state walk over one more pair of blocks", and "the `hx30` goal is the
last place in this walk that still re-unfolds the whole chain" — describes the
row that doubles.

**The ×3 figures are this PROGRAM's, not the family's** — measured 2026-10-05:
on §6's program with three `if`s whose conditions are all single comparisons,
`hprior` is 24 / 48 / 96 at two / three / four branches, i.e. ×2, and its share
of the walk theorem is a flat 4.0-4.1%. The difference is `not (n & 4)` above,
which lowers to two instructions and therefore two branch blocks. The
conclusion the Status draws from the flat share does not depend on which it is.

The generating code is `formal/arm64_proof_gen.py:6143`:

```python
for _pb in _prior_blocks:
    for _v in _vars:
        _hp = f"hprior_{bi}_{_pb}_{_v}"
        A(f"{IND}have {_hp} : (s_{_pb}).x{_var_regs[_v]} = {_v} := by")
        A(f"{IND}  rw [hsid_{_pb}]")
        A(f"{IND}  simp only [{', '.join(_pb_defs + list(_hpriors) + ['arm64_reg', 'arm64_set_reg', 'Arm64State.init'])}]")
```

Two facts per (prior block, variable), **emitted inside the per-branch walk**,
each proved by unfolding that prior block's whole `qS`/`qT` chain and then
discharging memory side conditions with `simp (disch := decide)`. The nest is
`branches × prior-blocks-on-the-path × variables-in-the-condition`, and the
outer factor is applied once per PATH, so the emission is exponential in the
number of conditional branches and the per-block chain is unfolded once per
(path, prior block) rather than once per block.

The comment above that loop already records WHY the facts exist — "for a nested
condition, unfolding every prior block in this one proof term exceeds the
kernel's recursion limit" — so the per-block split is a fix for a real limit.
The cost is that the split is redone per path.

## 4. Why it is not a bound, and what it is instead

The earlier version of this doc argued the wall was where the cost was. It is:
the growth is in the EMISSION, it is measurable with no Lean run at all (§3), and
it is 2^n in a construct (`if`) the corpus is full of. The honest alternative to
proving the shape is refusing it, and today a program that proves at two
branches stops building at three with a message about the KERNEL's memory.

## 5. The exact next step

**Read the 2026-10-05 Status before starting.** It does not reorder this list,
and steps 1 and 2 are still not implementable as written — but it says which
MEASUREMENT is the thing to beat (the per-visit facts in
`..._compiles_correctly_universal`, `hprior` among them at 4%), that step 1's
duplicate column counts identical statement text about DIFFERENT per-visit
bindings of `s_{pb}` and so is not shareable, and that the boundary has moved to
four branches.

Not a bigger bound, and **not the `hx30` rewrite** — §2 measures that goal at
inside 23 seconds, so landing it would be real work for no measurable change.
In this order, because each is cheaper than the one after it:

1. ~~**Share the `hprior` facts across paths.**~~ **MEASURED 2026-10-04 and
   found to be 5% of the emission** — the duplicate hypothesis is right (315 of
   384 at five branches) and the scope is wrong, because the fact is emitted
   inside a per-path term and a later path cannot see it. The full measurement,
   the scope argument and the `hsid` per-block counts are in the Status at the
   top; read them before starting, because they say the next step is the HOIST
   rather than this. The one number to beat is 384 `hprior` goals at five
   branches, and the wall to beat is the 202 s / 6.1 GB kernel OOM.
2. **If they cannot be shared, hoist the chain instead of the fact.** Each
   `hprior`'s proof is `simp only [_pb_defs …]` over block `pb`'s composed state.
   Emitting that composition ONCE per block as a named local — the shape
   `hsid_{pb}` already has — turns each `hprior` into `rfl`/`omega` off it, and
   it is the same move §1 of `bugs/FORMAL_dylib_export_loops_and_frame_bounds.md`
   records for `hreg`.
3. **Then, and only then, re-measure the table.** The number to beat is 144
   `hprior` goals at three branches; the wall to beat is the 202 s / 6.1 GB
   kernel OOM.

**What was NOT attempted here, and why, stated so nobody re-derives it:** a light
worker's ceiling is 8 GB (`tools/memslot.py --gb 8`), and this proof needs more
than that to get past its own midpoint — the 2M-heartbeat run already peaks at
4.2 GB and the full run at 6.4. Every measurement above was made at or under that
ceiling and none of them needed more; a fix for this can be *written* under it but
cannot be *verified* under it, so the verification is owed to a run with
`MEMLIMIT_GB` above 8.

## 6. Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ printf 'def f(n):\n    x = 0\n    if n & 8:\n        x = x + 1\n    if not (n & 4):\n        x = x + 2\n    if 16 & n:\n        x = x + 4\n    return x\n' > .tmp/three.mojo

# the failure (§1), bounded so a known-slow case costs minutes not PROOF_WALL_S
$ python3 tools/memslot.py --gb 8 --label lean -- python3 .tmp/leanrun.py 420 \
      python3 fire.py build --formal -o .tmp/three.out --backend=arm64 .tmp/three.mojo

# the controls and the growth table (§2, §3): stub the ONE check, so the .lean
# is written and never handed to Lean
$ python3 - <<'PY'
import formal.lean as L; L.check_proof_cached = lambda *a, **k: (True, "gen only", False, 0)
import fire; fire.main()
PY   # …with argv `build --formal -o .tmp/nb3.out --backend=arm64 .tmp/nb3.mojo`

# the 23-second control: the same proof with the final theorem removed
$ head -6034 three_proof.lean > .tmp/three_notheorem.lean
$ python3 .tmp/check_lean.py .tmp/three_notheorem.lean 420      # rc=0, 23.1s, 2.5GB
```

`check_lean.py` is `formal/lean.py::run_lean` with `LEAN_PATH` pointed at this
worktree's `lib/` — **not** `ensure_library`, whose currency check wants a
`ProofLib.olean` rebuild that peaks at 7.82 GB, i.e. over an 8 GB ceiling. That
is the one trap in reproducing any of this, and it cost this pass a killed run.
Both harnesses are scratch (`.tmp/leanrun.py` is a `subprocess` with a timeout, so
a known-slow case costs minutes rather than `PROOF_WALL_S`; `check_lean.py` is
five lines) and are spelled out above rather than committed — §2's whole claim is
that these measurements are cheap, and a committed script would suggest otherwise.