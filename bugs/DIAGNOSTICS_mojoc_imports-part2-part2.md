# DIAGNOSTICS mojoc imports, part 2 — part 2: synthetic signature rendering of implicit defaults

Part 2 of 3 of `bugs/hard/DIAGNOSTICS_mojoc_imports-part2.md`. Depends on
`DIAGNOSTICS_mojoc_imports-part2-part1.md` (the precompiled signature record).
Part 3 is `DIAGNOSTICS_mojoc_imports-part2-part3.md`.

## Class
mid. A bounded printer change plus its test. It must handle one tricky case
(an implicit conversion default whose `__init__` was never materialized from
the artifact), which is why it is not easy.

## Current state

The modular test expects the note for the imported struct to be rendered from a
synthesized signature, with the defaulted parameter printed as the call
expression, not the converted value:

    # CHECK: struct Container[T: Marked, W: Wrapper = __init__(Int(4))]
    # CHECK-SAME: # note - synthetic signature

The modular source comment states the constraint: the default is an implicit
conversion (`Wrapper` from `Int`) whose `__init__` is never materialized from
the bytecode, so the printer cannot confirm it is an implicit conversion. It
must print the default as written and must not crash (MOCO-4270). This repo has
no synthetic-signature printer for imported structs at all (see part 1).

## Goal

Add a printer that renders a signature record from part 1 as Mojo source text:

- bracket params first, then runtime params, each as `name: Type = default`
  with the default printed from its stored source text;
- when a default's head is an implicit conversion to the param's trait/type
  and the converted constructor is absent from the record, print the default
  text as written (`__init__(Int(4))`), never a guessed simplification and
  never an exception;
- the header line is prefixed with the marker `# note - synthetic signature`
  when the record came from the artifact rather than from source.

Put the printer next to the record reader from part 1 (one module, no second
renderer). Keep the function pure: record in, string out.

## Acceptance

For a record with `T: Marked` and `W: Wrapper = __init__(Int(4))` with no
`Wrapper.__init__` entry in the artifact, the printer returns
`struct Container[T: Marked, W: Wrapper = __init__(Int(4))]` followed by the
synthetic marker, and does not raise.

## Done when

File: `test_mojoc_synthetic_signature_default.py` (repo root; created by this
part). It builds the record in memory (no precompile needed) and asserts the
exact rendered header, plus a second record where the default is a plain
literal (`= 4`) to show the non-conversion path is unchanged.

Command: `python3 test_mojoc_synthetic_signature_default.py`

## Status

- **Open.** Blocked on part 1 landing the record shape. Nothing landed here yet.
