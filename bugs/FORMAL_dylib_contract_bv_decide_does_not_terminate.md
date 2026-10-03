# `bv_decide` on a composed per-export state does not terminate (dylib `hreg`)

**What I ran.** `formal/build.py::compile_formal_dylib(..., prove=True)` on
`def triple(n): return n * 3`, generated the proof, and ran it through
`formal/lean.py::run_lean` at a modest bound.

**What I saw.** The 210,844-byte generated proof does not finish. Measured at a
180 s CPU bound: **177.1 s CPU in 79.9 s of wall** (2.2 cores, so it saturates
and the wall bound alone would never have caught it), then `RLIMIT_CPU` →
SIGXCPU. Before this tree had a launcher the same file was measured at "did not
finish in 30 minutes" (`FORMAL_OPUS_dylib_termination_handoff.md` §1), and the
2026-10-02 processes the user killed by hand were `lean` running this shape of
obligation.

**What I expected.** `triple` is `n * 3`: three instructions of effect. The
`Total` theorem for it is already proved by the CFG walk, and the spec comes
from the source, so the only work left is one register's value over 15 steps.

**Which tactic.** `bv_decide`, and specifically in the two theorems
`dylib_export_0_triple_contract.hreg` / `.hx30`:

```lean
theorem hreg : ∀ n : UInt64,
    arm64_reg 0 (S14 (start n)) = (fun n => (n * (3 : UInt64))) n := by
  intro n
  simp only [S15, …, S1, st0, …, st14, start, body, arm64_reg, arm64_set_reg, …]
  bv_decide
```

`S14 (start n)` is a **14-fold nested** `Arm64State`: each level is an
`arm64_set_reg` plus a `mem_write_u64 (mem_write_u64 …)` memory pair plus an
`sp` update. `bv_decide` has to normalise that goal before it can decide it, and
the normalisation does not terminate.

**How it was narrowed** (every variant is a prefix/suffix edit of the ONE
generated file, run at a 60–90 s bound, all on an otherwise idle box):

| variant | result |
|---|---|
| the generated file as emitted | spins (killed at the bound) |
| the file's own `set_option maxHeartbeats 20000000` removed, launcher `-T 200000` | **spins, 0 errors** — heartbeats do not meter it |
| everything before `namespace dylib_export_0_triple_contract` (lines 1–1825: the whole trace walk, all 15 `dylib_step_ok_*`, all 15 `walk_b0_self*`, `runs`, `mid`) | **checks clean, 18.4 s wall / 9.4 s CPU, 0 errors** |
| the contract namespace up to (not including) `hreg` — `start`, `st0…st14`, `S0…S15`, `body` | **checks clean, 8.0 s / 8.7 s, 0 errors** |
| …plus `hreg`/`hx30` with their closing `simp only […]` replaced by `skip`, `bv_decide` kept | **spins** |
| …plus `hreg`/`hx30` with `bv_decide` replaced by `sorry`, closing `simp only` kept | **checks clean, 40.0 s / 42.0 s, 0 errors** |

Those last two are the whole finding: the closing `simp only` and `bv_decide`
are each individually fine, and **it is `bv_decide` that does not return**.

**Why no budget catches it.** `simp` congruence recursion, measured three ways,
each of which left the run spinning with **0 errors**:

* `set_option maxHeartbeats` at 200000 (the file's own 20,000,000 removed) — no
  "timeout at whnf";
* `simp (maxSteps := 100000)` on the 14 pc lemmas — nothing;
* `simp (maxRecDepth := 10000)` on all 32 `simp` calls in the contract region —
  nothing.

`/usr/bin/sample <pid> 5` on a live run names the mechanism: a worker thread
**32,332 stack frames deep** in
`Lean.Meta.Simp.simpAppUsingCongr_visit → simpAppUsingCongr →
Lean.Meta.Simp.simpLoop → visitPreContinue → congrDefault → simpAppUsingCongr …`,
i.e. `simp` re-simplifying congruence arguments without end, from inside
`bv_decide`'s own normalisation — which the generated file has no way to
configure. This is why `OPUS-1`'s "40× `maxHeartbeats`, did not help" was a true
measurement of the wrong instrument.

**Minimal repro.** `python3 .tmp/dylib_repro.py` in the worktree that measured
it (regenerate with the steps in §How it was narrowed); standalone, it is lines
**1826–1959** of the generated proof — 34 declarations, `start`, `st0…st14`,
`S0…S15`, `body`, `hreg`, `hx30` — with the four `import`s at the top. It checks
in 40 s with `bv_decide` → `sorry` and does not finish with it.

**Exact next step** (for whoever holds `formal/arm64_proof_gen.py`; this is
`generate_dylib_proof` → `_dylib_contract_proof`, and `OPUS-1…OPUS-3` are the
same ground):

1. **Do not raise a budget.** Three separate meters were measured failing to
   fire; a fourth will too. The goal has to get smaller.
2. **Decide one step at a time, not the composed effect.** The walk region
   already proves `arm64_step (qS_k st) dylib_code = some (qT_k st)` for each
   `k` (`dylib_sr_k`) and `arm64_runs dylib_code K st = some (qS_K st)`
   (`walk_b0_selfK`) — 18 s, and it closes. `hreg` re-derives the same register
   value from the 14-deep term in one shot. Thread the value through the
   existing per-step equalities (or state `hreg` over `qS_k` for the last `k`
   that touches x0) so `bv_decide` sees one `arm64_set_reg`, not fourteen.
3. If that cannot be made to work, the honest fallback under
   `formal/admitted.py`'s convention is to emit the contract as a NAMED
   obligation with the `sorry` counted in the census — **not** to leave a
   non-terminating proof in a `--formal` path. A dylib build that spins is worse
   than a dylib build that reports an unproved contract.
4. Whatever is done, `bv_decide` on a composed state should be wrapped so a
   future regression is a Lean error rather than a process: there is no config
   for its internal `simp`, so the honest instrument is
   `formal/lean.py`'s launcher, which now kills this exact file at
   `PROOF_CPU_S` and says so.

**Status: root cause found, fix not attempted here.** The launcher bounds it;
the generator that emits it is not this change's area (`lean:launcher`), and
`FORMAL_OPUS_dylib_termination_handoff.md` is another worker's live handoff on
the same code.
