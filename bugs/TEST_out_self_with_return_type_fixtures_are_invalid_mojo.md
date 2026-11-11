# TEST: fixtures declare `out self` and a return type, which is invalid Mojo, and nothing checks them

Status: OPEN (HARD). Filed 2026-11-11. Area: TEST (fixture validity), with a diagnostic-wording mismatch.

## Symptom

`test_formal_x86_64_parity.py` reported `FAIL=3` of 90 on master. Each failure is a fixture, not a backend:

    FAIL  method_call_on_a_nested_frame_receiver: --backend=arm64 did not build:
          ...error: functions must not declare both an 'out' argument and a return type

The three fixtures all declare `def put(out self, v: Int) -> Int:`. Changing `out self` to `mut self` made the
suite PASS=90 FAIL=0 (commit `e26a073ed` on master, and its archive twin).

## Cause

`out self` is the receiver convention of a constructor (`def __init__(out self, ...)`). On an ordinary method it is
not valid, and real Mojo says so. Measured with the real compiler (`tools/mojo build`) on a struct with
`def ten(out self) -> Int:`:

    error: self argument must be present in instance method

Our front end refuses the same source with a different sentence:

    error: functions must not declare both an 'out' argument and a return type

Both refuse. The fixture was never valid, so the parity run had nothing to compare against.

## Why it went unnoticed

1. The parity harness treats a build failure on an arm64 backend as a backend failure. It never asks whether the
   source is valid Mojo first.
2. The same fixtures run through CPython, which accepts `out self` as an ordinary parameter. A CPython oracle
   therefore cannot tell a valid program from an invalid one.
3. No test checks the fixtures themselves against the real compiler.

## Scope (measured with `grep -rn "(out self[^)]*)[^:]*->"` over `*.py`)

| file | invalid fixtures |
|---|---|
| `test_formal_run.py` | 12 |
| `test_formal_method_param_field.py` | 12 |
| `test_formal_bracketed_method_field_set.py` | 4 (`def bump[T: Int](out self, k: Int) -> Int`) |
| `test_formal_frame_slot_subscript_census.py` | 3 |
| `test_formal_debug_assert.py` | 1 |
| `test_x86_64_parity` (parity, the three above) | 3 (already fixed on master by `e26a073ed`; not in the 32 below) |

That is 32 fixtures still invalid, in five files. Not measured: whether each one currently passes or refuses in its
own test. Some may pass only because their test never builds the arm64 path. `test_out_param_return_type_diagnostic.py`
is the one intentional case: it pins our diagnostic text and must stay.

`formal/build.py`'s two matches are docstring prose, not code.

## Second defect: the diagnostic does not match the real compiler

Our wording ("functions must not declare both an 'out' argument and a return type") describes the wrong rule for a
method. The real rule is that `out self` is a constructor receiver. A user who writes the mistake is told about a
conflict between two arguments that is not the actual problem.

## Design

- **A validity gate on fixtures.** Every fixture that claims to be valid Mojo is compiled by the real compiler
  (`tools/mojo build`) once, and the result is recorded. A fixture that real Mojo refuses is an error in the test, not a
  backend red. The gate runs in the parity and formal-run tests, so a bad fixture fails before it reaches the backends.
- **Fixtures use the right receiver.** An ordinary method is `mut self` (or `self`); `out self` is only for
  `__init__`. Where a test needs a constructor, it writes `__init__`.
- **Diagnostic wording follows the real compiler.** `out self` on a non-constructor is refused with the real
  compiler's meaning, stated in our words, and `test_out_param_return_type_diagnostic.py` is updated to pin it.

## Fix order

1. Measure: compile each of the 32 fixtures with `tools/mojo build` and record accept or refuse. Put the table in this
   doc. Any fixture real Mojo accepts is not in scope here.
2. Add the validity gate (a helper that runs `tools/mojo build` once per fixture and caches the verdict under
   `build/`), and wire it into the parity and formal-run tests.
3. Convert the refused fixtures to `mut self`, or to `__init__`, and re-run each test. Expected: no change in
   results, since only the receiver spelling changes.
4. Align the diagnostic message with the real compiler's meaning, and update the one pinning test.
5. Delete this doc in the same commit as step 3.

## Related

- `e26a073ed` (master): the three parity fixtures, `out self` to `mut self`.
- `test_out_param_return_type_diagnostic.py`: pins the current wording; updated in step 4.
