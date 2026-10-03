# The formal Lean proof checks in the gate have no time bound, so they are switched off

**Status: OPEN. The eight gate tests that typecheck generated Lean are `disabled=` (registered, not run) until Lean runs
under a wall-clock AND CPU bound and the looping obligations are found.**

2026-10-02: the user killed ten `lean` processes by hand, some with hundreds of CPU-hours. A valid inductive proof
checks in seconds to minutes; those were non-terminating elaborations (a `simp` / `decide` / `omega` / kernel
reduction that `maxHeartbeats` does not meter). `formal/lean.py` had a 1200 s wall timeout on some paths and no CPU
bound; `formal/x86_64_model_test.py` and others launch `lean` with no timeout at all. A gate that can run forever is not a
gate, so these are off and this doc is the switch (CLAUDE.md "Known failures": deleting this doc re-enables them, and
`tools/suite.py` refuses to load while a disabled test's doc is gone).

Disabled in `tools/suite.py`: `formal`, `formal-call-proofgen`, `formal-dylib`, `formal-imports`, `formal-sweep`,
`formal-x86`, `formal-x86-endtoend`, `formal-x86-model` (every test that `deps` on `prooflib`; `prooflib` itself stays,
a dependency with no live dependent costs nothing).

Safety net already in place: `tools/control.py guard` kills a `lean` in our trees past 45 min wall / 90 min CPU.

## What closes it (worker `formal7-lean-bound` owns it)

1. ONE launcher in `formal/lean.py` that every call site uses, enforcing wall time and total CPU time (all threads),
   killing the process group, passing Lean's own bounds, and reporting a kill as a loud distinct failure.
2. Defaults sized from MEASURED proof times (5-10x the slowest legitimate file).
3. A test that a looping Lean file is killed and never reads as success; an estate check that no `lean` launch exists
   outside the launcher.
4. The root cause: which generated obligations spin (formal/arm64_proof_gen.py, x86_64_proof_gen.py, build.py), fixed or
   minimised into a repro.

Then delete this doc and the eight tests come back (check the per-test time first: put the measured times in the
registry, `tiny`/`small` class as appropriate).
