# FORMAL: `svc` exit handling — part 1: census every emitted `svc`'s x16 and x0 use

Part 1 of 5 of `bugs/hard/FORMAL_svc_exit_handling_incomplete.md`. This is the
parent's design step 1: measure before assuming. It changes no generator code;
it lands the measurement as a test.

## Goal

Land a fast census over the arm64 images of `formal/examples` that answers, for
every `svc` word in the corpus, the parent's three questions:

1. Is x16 statically `1` (exit), statically another value such as `4` (write),
   or dynamic?
2. For every write `svc`, does the fall-through rewrite `x0` before anything
   reads the byte count the model does not model?
3. Is a dynamic x16 present anywhere in emitted code? The parent says a
   dynamic one is a finding, not a default; the test must make one a visible
   failure naming its program and pc, not a refusal a reader has to infer.

The detector must also be shown live against a hand-built image, so the test
cannot pass by scanning nothing.

## Current state (measured 2026-11-13 by a scratch script)

Over the 94 `formal/examples/*.mojo` arm64 images: **439** `svc` words, of
which **220** are static exit (`x16 = 1`) and **219** are static write
(`x16 = 4`); **0** are dynamic, and **0** write sites read `x0` before it is
rewritten. The corpus is clean today.

The readers already exist and are the ones to use, not re-derive:

* `formal/arm64_proof_gen.py::_is_svc` — the encoding test;
* `formal/arm64_proof_gen.py::_svc_static_x16(words, pc, leaders)` — x16 from
  the `movz` directly before the `svc`, or `None` when dynamic;
* `formal/arm64_proof_gen.py::_is_svc_exit(words, pc, leaders)` — static
  `x16 = 1`;
* `formal/arm64_proof_gen.py::_x0_reassigned_after_write(words, pc)` — the
  fall-through rule for a write `svc`.

What is missing is a test: nothing measures this corpus, so the next change to
the emitter or the readers can turn a static site dynamic without any gate
job noticing.

## Acceptance

* A new `TestSvcProvenanceCensus` in `test_formal_call_proof_gen.py` builds the
  arm64 image of every `formal/examples/*.mojo` with
  `formal.build.compile_formal(..., arch="arm64", prove=False, check=False)`
  and walks every word with `_is_svc`.
* For each `svc` it records `(program, pc, x16)`, and for every `x16 != 1` it
  records `_x0_reassigned_after_write` as well. The test prints a summary line
  with the total, exit, write, dynamic and unrewritten-`x0` counts.
* The corpus assertions are **dynamic count == 0** and **write-with-`x0`-read
  count == 0**. A failure names the program, the pc and the offending word.
* A hand-built fixture (`svc` at the entry with no preceding `movz`, then
  `movz x0, #0`, then `ret`) is classified `dynamic` by the same census
  helper, and a fixture with a write `svc` followed by an `add x1, x0, x2`
  before any x0 rewrite is reported as an unrewritten write. Both prove the
  census can fail.
* No generator behaviour changes. `_is_svc`, `_svc_static_x16`,
  `_is_svc_exit`, `_x0_reassigned_after_write` are called, not copied.

## Done when

```
python3 test_formal_call_proof_gen.py TestSvcProvenanceCensus
```

exits 0. It is text-only: no Lean, no `prooflib`, no proof generation. Expected
cost: codegen-only builds of 94 small examples, about 20-30 s and under 1 GB.

## Approach

1. Add the class to `test_formal_call_proof_gen.py`, next to
   `TestTheStackFloorTrapIsAProofObligation` / `TestTheRefusalNamesTheSvcItRefuses`
   (the classes that already own the `svc` predicates).
2. One helper, e.g. `_svc_census(words, base, code)`, returns one record per
   `svc`; build `leaders` from `_cfg_blocks(words, base, base +
   _exec_code_limit(code))` exactly as `_cfg_decomposition_refusal` does.
3. Compile with `prove=False`; a compile refusal is a test failure naming the
   example, not a skipped example. Do not grow a skip list to make the census
   pass.
4. Keep the corpus list derived from `glob.glob(os.path.join(HERE, "formal",
   "examples", "*.mojo"))`, so a new example is measured automatically.

## Out of scope

* Admitting the dynamic case (parts 2-4) and the dylib termination theorem
  (part 5). This part only makes the current state observable.
* The x86-64 corpus.
