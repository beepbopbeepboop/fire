SPLIT: FORMAL_x86_endtoend_memory_ceiling-part1, FORMAL_x86_endtoend_memory_ceiling-part3. Part 2 (the peak-measurement harness `tools/measure_proof_peaks.py` and its schema test) has landed; its doc is deleted.

# FORMAL: three generated proofs exceed the per-process `-M 6144` memory ceiling

## Symptom, measured

    python3 -m formal.x86_64_endtoend_test   (full run, measured 2026-11-19)
      wide_expr         terminates: FAIL lean exited -6: libc++abi: terminating due to uncaught excep…
      wide_recv         terminates: FAIL lean exited -6: libc++abi: terminating due to uncaught excep…
      list_literal_index  terminates: FAIL lean exited 1: error: (kernel) excessive memory consumption

Three of the thirteen full-run failures (`PASS=68 FAIL=13 of 68`). The first
two die in the interpreter (`lean::memory_exception`, rc -6); the third is the
kernel's own ceiling (`excessive memory consumption`, rc 1). All three are the
same limit: `formal/lean.py` runs every generated proof with
`-M LEAN_MEMORY_MB`, and `LEAN_MEMORY_MB = 6144` (line 291; `-M` applied at
line 315). `list_literal_index`'s run peaked at 6.6 GB — just over.

## Why this is a file property, not machine pressure

The ceiling is per-process and deterministic: two independent full runs of the
same tree produced byte-identical results (the same three failures, the same
counts 53/2/13), and a quiet machine does not change a `-M` rejection. These
are the generated files' proof COST, not the machine's state. The
`formal-x86-endtoend` marker's 2026-10-05 prose already named `wide_recv` as
the known case of this class; the other two are the same class arriving at the
same wall from different proofs.

`list_literal_index` is the newest of the three and got HERE because of the
general step lemma landing (commit `90797f88e`): the old rax-pinned walk used
to take its guard's TRAP arm (JZ → exit(2)) with a wrong ZF, so its success
path was never proved and its cost never paid. With the general
`x86_step_mov_rm64_imm32` the success path now elaborates (the
`x86_set_flag4` simp-set correction in the shift rows, commit `69bcf55b0`,
was the last elaboration blocker), and its per-step `hval` chain — the
47-successor, 26-lemma scale the coverage run reports — peaks above the
6144 MB the runner gives it.

## What the class means for the suite

Until the proofs cost less, these three can be neither `PROVED` nor a counted
hole: the file does not finish elaborating, so no `sorry` is ever counted.
They count in `FAIL=M` (the checked marker number) and nowhere else. Raising
`-M` for the three files is a measurable next data point (`list_literal_index`
needs just ~1 GB more than the current ceiling; `wide_recv`'s earlier
measurement hit the wall at the same 6144 with a longer proof), but the
structural fix is the proof cost: the per-step `hval` facts exist because one
`simp` over the whole chain did not finish in 1500 s on `wide_recv`
(`emit_value_facts`'s docstring records the measurement), so the cost moved
from wall-time to memory, and the three files above are where the memory form
bites.

## Next step

1. Measure each file's peak with a raised `-M` (e.g. `mem_mb=8192` through
   `formal.lean`'s existing parameter) to pin the number each needs.
2. Attack the cost where it is: the `hval` chain's simp set re-normalizes the
   nested `mem_write_bytes` `ite` at every step on the long paths — the same
   term the single-`simp` strategy died on; the per-step facts would be cheaper
   if the addresses they peel were reduced once and named.
3. Re-run the full suite and move the three toward `PROVED` or a counted hole
   as the cost drops; the marker's `FAIL=M` follows the run either way.

## Done when

`wide_expr`, `wide_recv`, and `list_literal_index` elaborate to completion
(`PROVED`, or `PROVED` with a counted hole named), and no generated proof in
the corpus is rejected by the `-M` ceiling.
