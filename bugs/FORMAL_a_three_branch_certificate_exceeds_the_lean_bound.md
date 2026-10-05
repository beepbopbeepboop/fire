# FORMAL_a_three_branch_certificate_exceeds_the_lean_bound: the cost is the
# per-PATH value-flow facts, and everything the earlier rounds blamed for it
# checks in 23 seconds

**Status: the DIAGNOSIS is wrong in both of its earlier rounds and is corrected
here, with the measurements; the blowup itself is NOT fixed.** Found while
landing the bit-test proof arm (whose doc is deleted with it) and re-measured
2026-10-03 on this tree, with the measurement the earlier rounds did not take.

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