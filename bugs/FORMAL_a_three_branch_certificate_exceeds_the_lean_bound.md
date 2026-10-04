# FORMAL_a_three_branch_certificate_exceeds_the_lean_bound: the cost is the
# per-PATH value-flow facts, and everything the earlier rounds blamed for it
# checks in 23 seconds

**Status: the DIAGNOSIS is wrong in both of its earlier rounds and is corrected
here, with the measurements; the blowup itself is NOT fixed.** Found while
landing the bit-test proof arm (whose doc is deleted with it) and re-measured
2026-10-03 on this tree, with the measurement the earlier rounds did not take.

**The one-line version:** the whole-program certificate for a function with
THREE conditional branches does not finish on this tree, and it is neither
`_gen_run_cert`'s composed-state walk nor `runProg` nor the `hx30` goal that all
three of the docs this spawned name. It is `formal/arm64_proof_gen.py:6143`'s
`for _pb in _prior_blocks:` — the `hprior_*` value-flow facts — which are
re-emitted once per PATH through the CFG, so their number is exponential in the
number of conditional branches, and their proofs each re-unfold a block's whole
composed state.

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

1. **Share the `hprior` facts across paths.** The fact is `(s_{pb}).x{reg} = v`
   where `s_{pb}` is the state after block `pb` on the current path. When two
   paths reach the same `pb` with the same register value — which is the case for
   every program whose branches test DISJOINT variables, including this one — the
   facts are identical and one copy serves both. The generator can decide this
   syntactically (same prior-block set, same `_var_regs` assignment) and emit the
   fact once per block with a name that does not carry `bi`. **Measure it first**:
   count the duplicate `(pb, reg, rhs)` triples across paths in the four proofs
   above, which is a walk over an emitted `.lean` and costs nothing.
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