# TEST: fixtures are invalid Mojo beyond the `out` declarations

Status: PARTLY FIXED on master (2026-11-12). The `out` declaration family was
already fixed and swept by `test_out_param_return_type_diagnostic.py`'s
`FixtureCorpusValidity` (commit `34fca92c3`). This round measured the rest of
the same 42 fixtures and fixed the half of the bug that is a harness defect:
a source the front end refuses is no longer reported as a backend red.
Area: TEST (fixture validity).

## Symptom

Many fixture strings in the suite are Mojo source that the real compiler
refuses for reasons other than `out`. The real compiler was measured
(2026-11-11) on the 42 fixtures that the `out` campaign converted; after the
conversion the remaining errors in those same fixtures were:

- `printf` (not a name in real Mojo without the module),
- lowercase `int` for `Int`,
- `main` declared to return a value (real Mojo: `'main()' does not return a value`),
- a struct that is constructed but has no `__init__` (real Mojo wants `move`,
  or a declared constructor),
- implicit copies.

## Why it matters

`test_formal_x86_64_parity.py` calls a failed build on one backend a backend
failure. A fixture that is not valid Mojo therefore reports as a red in the
wrong layer, and the CPython oracle cannot catch it: CPython accepts the
Python spellings that real Mojo refuses. The `out` fixtures were exactly this
shape, and the `out` sweep now catches only that one declaration family.

## Measured (2026-11-12, all 42 converted fixtures, `tools/mojo build`)

The fixtures were re-extracted from the conversion commit `73eb00d4b` (42
strings in five files) and each one was given to the real compiler
(`Mojo 1.3.0.dev2026110405`). All 42 are refused; the real compiler's FIRST
error in each:

| class | fixtures | real compiler's first error |
|---|---|---|
| `main` declared to return a value | 21 | `'main()' does not return a value; remove the return type` |
| lowercase `int` | 6 | `use of unknown declaration 'int'; did you mean 'Int'?` |
| struct constructed without `__init__` / move | 6 | `invalid initialization: missing required argument: 'move'` |
| parameter without a type | 5 | `argument type must be specified` |
| `printf` | 1 | `use of unknown declaration 'printf'` |
| mutating method on a temporary | 1 | `invalid call to 'bump': invalid use of mutating method on rvalue of type 'Cell'` |
| no `main` | 1 | `module does not contain a 'main' function` |
| unresolved import | 1 | `unable to locate module 'byref_xmod'` |

Two classes the original list did not name are in the measurement: a
parameter with no type (5) and a mutating method called on a temporary (1).
Both are accepted by this tree's front end, like the five original classes.

## Why these classes are not a corpus-wide real-Mojo gate

`printf`, `int` and `main() -> Int` are this tree's own dialect, not mistakes
in the fixtures:

- `main() -> Int` returning the process status is the documented input shape
  (`doc/GNU-EXTENSIONS.md` shows `def main() -> Int:` as Mojo input), and the
  formal fixtures use it to assert an exit status.
- `printf` is in `gimple_codegen.py`'s known-symbol table
  (`gimple_codegen.py:3958`, `:4117`); it is a builtin here.
- lowercase `int` is Python's spelling, and the project's target is Python;
  the same fixture set is also run through CPython, which is the oracle these
  tests compare against.
- `move`/implicit copies are real Mojo's ownership rules; the formal fixtures
  deliberately exercise this tree's by-reference receiver and field-copy
  behaviour, which is what `mut self` fixtures test.

So "the fixture corpus is valid real Mojo" is not this tree's contract; it is
"valid for this tree's compiler", which is what the harnesses actually need.
Converting the 42 would change what the tests assert (an exit status, a
`printf` format, a copy shape), not just the spelling. This matches the
measurement limit carried into this doc: the fixture set is Python-only by
project target, and whether a Mojo-only corpus should exist is a separate
decision.

## Fixed this round: the wrong-layer report (the actual defect left)

The reported failure mode is not that the fixtures use Python spellings; it is
that a fixture the front end refuses was reported as a backend red. That is
now classified in `test_formal_x86_64_parity.py::build_failure_detail`: when a
build fails, the other backend is built too (only on failure), and

- the same `error:` sentence on both backends is reported as a **SOURCE
  error**, not a backend red (the shared front end is the only thing that can
  produce one), and
- different sentences are reported as both backends refusing, naming each
  diagnostic, because neither is the other's oracle.

`REFUSALS` is unchanged: `run_refusal` still requires both backends to refuse
with the SAME words, which is the stronger assertion for a construct that is
known to have no representation.

Pinned in `test_out_param_return_type_diagnostic.py`'s
`ParityBuildFailureIsClassifiedByLayer` (two cases: a refused fixture is a
SOURCE error on both backends; a failure the other backend does not reproduce
keeps the `--backend=... did not build` message).

## Next step

1. Decide the fixture corpus's contract, which decides whether any further
   work exists here:
   - **this tree's dialect** (the current behaviour): the gate is "the front
     end accepts it", and the harness classification above is its enforcement.
     No fixture conversion; close this campaign.
   - **a separate real-Mojo corpus**: add one and point a sweep at it, starting
     with lowercase `int` (6 fixtures here) and `main` returning a value (21).
     Converting the current 42 is NOT that corpus, because it would delete the
     exit-status and `printf` assertions.
2. If the first answer: delete this doc in that commit and let
   `FixtureCorpusValidity` keep the `out` family. If the second: extend it with
   the new corpus and the measured class, one class per commit.

## Done when

The wrong-layer defect is closed (2026-11-12): the harness asks the other
backend before it blames one, and
`python3 test_out_param_return_type_diagnostic.py ParityBuildFailureIsClassifiedByLayer`
passes. The corpus question is the decision above; until it is made this doc
is the record of why no further conversion is warranted on the current corpus.
