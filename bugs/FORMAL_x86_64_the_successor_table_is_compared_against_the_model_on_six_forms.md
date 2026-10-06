# `formal/x86_64_model_coverage_test.py` compares the emitter's SUCCESSOR against the model on 6 of the 43 forms, and the two that were stale were both among the other 37

**Area:** FORMAL (the x86-64 emitter/model agreement check). Found 2026-10-05 on
`work/formal69-docs`, while fixing the two stale successor rows that made
`formal-x86-endtoend` fail 26 of 26 (`bugs/FORMAL_x86_64_end_to_end_proof.md`'s
B32/B33, filed 2026-10-05).

**Status: the two rows are fixed and the check now covers them; the other 37 are
not, and the general fix is named below.**

## What the check is, and why it is the right home for this

`formal/x86_64_model_coverage_test.py::SUCCESSOR_FORMS` compares the successor
`formal/x86_64_endtoend_test.py::_resolve` WRITES for an instruction against the
successor `lib/X86.lean`'s `x86_step` COMPUTES for it, by `native_decide`. It is
a semantic check rather than a textual one, which is the whole point: `_SUCCS` is
a copy of the model, and B1/B2/B21/B29 are all the same lesson — a copy that
drifts is a proof of a different instruction, and a textual check cannot see the
drift. The `cqo` row (B29) is why the file exists.

## What is missing, measured

```console
$ python3 -c "import formal.x86_64_endtoend_test as E, formal.x86_64_model_coverage_test as M; print(len(M.SUCCESSOR_FORMS), len(E._FORMS))"
6 43
```

so 37 forms have a `_SUCCS` row and no row in `SUCCESSOR_FORMS`. The two that had
drifted (`setcc`, `imul_r64_r64`) were both in those 37, and both were found by
`formal-x86-endtoend`'s `Type mismatch` instead — which is the direction the
project has been arguing against for three docs now: **the end-to-end prover is
the only thing that compares the table with the model, it costs 30-200 s per
example, and it only reaches a form when an example happens to contain it.**

`formal/examples/` is 93 programs and its instructions cover 43 forms, so the
corpus does reach them — but one `Type mismatch` per example, printed as
`lean exited 1: error: Type mismatch | x86_step_setcc_r8 s24` with the
`:60` truncation `_run_lean` applies, which names a LEMMA rather than a row. Both
rows could have stayed wrong for months on that route.

## The next step

**Add the other 37 rows.** Each is `(form, encoding, probe)` plus an optional
initial state, and the two halves have real constraints that the existing six
show:

* **the encoding** comes from `formal/x86_64.py`'s `encode_*` (never hand-written
  bytes — a row whose bytes the backend does not emit is a row about an encoding
  nothing produces), and the form name must be the DECODER's form, i.e. the key
  in `_FORMS`;
* **the probe** must read a field whose value DIFFERS between the correct
  successor and the plausible wrong ones, and `X86State.init 10 m` leaves every
  register but `rdi` at 0 — so a row whose output is a single register needs a
  FOURTH field giving that register a non-zero initial value, exactly as `setcc`'s
  does now, or the row passes on a row that states the wrong instruction. Measured
  and visible: `lib/X86.lean`'s own `x86_step_setne_al` sat on a zero RAX for the
  same reason and had the whole-register bug in its STATEMENT until the fuzzer's
  census found it;
* **the memory forms** cannot be probed through `mem` at all (it is a
  `Nat → UInt8`, so record equality is not decidable — B29's reason for the
  probe), so they need `mem_read_bytes` through a probe, e.g.
  `fun t => (t.rip, mem_read_bytes t.mem ADDR 8)`, with the address a literal
  the `_Abs` machine supplies. That is the one part of this that needs a new
  mechanism rather than a new row, and it is the rows that have not been written
  yet.

`SUCCESSOR_FORMS` is a tuple of tuples and `successor_lean_source` already
accepts the optional fourth element, so a row costs three lines and no change to
the emitter. The coverage count is printed by the registered job
(`formal-x86-model`) as `emitted successor vs the model: N form(s)`.

## Reproducing

```console
$ python3 formal/x86_64_model_coverage_test.py | grep 'successor vs the model'
emitted successor vs the model: 6 form(s) — each successor is the model's
```

The same command with `_SUCCS["setcc"]` put back to
`{ x86_set_reg … }` reports two failures and exits 1 — measured, not argued.