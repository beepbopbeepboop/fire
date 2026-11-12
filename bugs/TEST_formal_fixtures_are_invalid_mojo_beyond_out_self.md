# TEST: fixtures are invalid Mojo beyond the `out` declarations

Status: OPEN. This is the remainder carried out of the deleted
`TEST_out_self_with_return_type_fixtures_are_invalid_mojo` doc, whose subject
(the `out` declaration shapes) is fixed and now swept by
`test_out_param_return_type_diagnostic.py`'s `FixtureCorpusValidity`. Area:
TEST (fixture validity).

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

## Measured scope limits (carried over, 2026-11-11)

- The real compiler is the reference per DECLARATION, not per whole fixture:
  it does not support all of Python, so a whole-fixture compile is not a valid
  oracle. Of the 49 fixtures using an `out` shape, it flagged the declaration
  line in 46; the other three were invalid at a call site or had an unresolved
  import.
- The fixture set is Python-only by project target, so whether a fixture using
  Mojo-only syntax belongs in it needs its own review; this doc does not
  decide that.

## Next step

1. Pick ONE error class from the list above (start with lowercase `int`, the
   cheapest to measure and convert) and measure it with `tools/mojo build`
   over the fixture corpus. Record the table here.
2. Extend `test_out_param_return_type_diagnostic.py`'s
   `FixtureCorpusValidity` from its `out`-specific sweep to the measured class
   (a new refusal tuple and a positive/negative gate case beside the existing
   ones), or add a sibling class in the same file. The sweep compiles every
   fixture string, so it costs ~4 s for ~190 strings; keep it in that
   registered job rather than adding an unregistered test file.
3. Convert the fixtures, one class per commit, with the corpus gate green
   before the commit.
4. Delete this doc in the commit that lands the last class, after
   `python3 tools/dangling_doc_refs.py --ratchet`.

## Done when

`python3 test_out_param_return_type_diagnostic.py FixtureCorpusValidity`
rejects every measured invalid-Mojo class over the fixture corpus, and no
fixture in the suite provokes one.
