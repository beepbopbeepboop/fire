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

## Measured with the real compiler (`tools/mojo build`, 2026-11-11)

Corrects the first draft of this report, which said our diagnostic was a second defect. It is not.

| case | real Mojo, in order | ours |
|---|---|---|
| `def ten(out self) -> Int:` in a struct | `functions must not declare both an 'out' argument and a return type` at 5:26 (the `Int`); then `self argument must be present in instance method` (at `self`) | same primary message, at 5:21 (the close paren): position gap |
| `def __init__(out self) -> A:` | `functions must not declare both an 'out' argument and a return type` at 3:31 (the `A`) | same primary message, at 3:26: position gap |
| `def set(out self, v: Int):` (no return type) | `'self' argument must have type 'Self'; use a 'where' clause to constrain the 'Self' type instead` | accepted: gap |
| `def f(out x: Int) -> Int:` | `functions must not declare both an 'out' argument and a return type` at 1:22 (the `Int`); then `'out' argument cannot be returned by name; ...` | same primary message, at 1:21: position gap |
| `def f(out x: Int)` called as `f(y)` | `invalid call to 'f': unexpected argument` | accepted: gap |
| `def ten(mut self) -> Int:` | accepted | accepted |
| `def __init__(out self, v: Int):` | accepted | accepted |
| `fn f(...)` | `'fn' has been removed; use 'def' instead` | accepted: gap |

The primary message is the same. Real Mojo adds a second error on the same declaration.

Scope limits, measured on the 49 fixtures that use `out self` on a non-constructor or an `out` parameter with a return
type (`fix/selected.json` in the measurement scratchpad):

- Real Mojo flags the declaration line itself in 46 of 49 fixtures. The other three are in `test_formal_run.py`
  (lines 7873, 22504, 5150) and are not yet explained.
- Most of the other errors in those fixtures come from the rest of the fixture (`'main()' does not return a value`,
  missing `move` for a struct with no `__init__`, `int` for `Int`, unknown modules). Those are not the `out` bug.
- Real Mojo does not support all of Python, so it is not a valid oracle for whole fixtures. The validity check must be
  per declaration: does real Mojo flag this `out` declaration?

## Decisions and what is still open

- Real Mojo is the reference for the `out`-declaration constructs only, not for whole fixtures.
- The expected behaviour of our compiler for each row of the table above is the real compiler's primary message at the
  same `file:line:col`. `test_out_param_return_type_diagnostic.py` pins every row: matched rows as plain assertions,
  position and accept gaps as `expectedFailure`, each naming this doc. Fixing a gap means removing its marker in the same
  commit.
- Whether a fixture that uses Mojo-only syntax belongs in a Python-only suite is not decided here. The project target is
  100% Python, so the fixture set needs its own review.

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

## Explained: the three unflagged fixtures in `test_formal_run.py` (lines 7873, 22504, 5150)

Measured with the real compiler on self-contained variants (`out self` shapes, 2026-11-11):

| shape | real Mojo | ours |
|---|---|---|
| `def copy_from(out self, other: Self)`, declaration only | accepted | accepted |
| same, called as `r.copy_from(q)` | `invalid call to 'copy_from': unexpected argument` at `q` | accepted: gap |
| `def set(out self, v: Int)` | `'self' argument must have type 'Self'`, at `v` | accepted: gap |
| `def fill(out self, r: S)` (S a struct in the same file) | `'self' argument must have type 'Self'`, at `r` | accepted: gap |
| `def reset(out self)` (no other parameters) | `self argument must be present in instance method`, at `self` | accepted: gap |

- Fixtures 7873 and 22504 (`copy_from`, `take`) are valid declarations but invalid call sites. Real Mojo's first error
  for them is in `main`, not in the declaration.
- Fixture 5150 (`fill(out self, r: S)`) is refused at its declaration. Real Mojo never reached that check because its
  `from byref_xmod import` does not resolve.

Decided behaviour, from these measurements: an `out self` method that is not a constructor is refused by the real
compiler in every shape measured, either at the declaration or at the call. Our compiler must refuse it too, at the real
location, with the real message. These are pinned as `expectedFailure` cases in
`test_out_param_return_type_diagnostic.py`. Fixing one means removing its marker in the same commit.

What is not decided: the exact general rule behind the messages. The real messages depend on the parameter list, so the
fixer should take the rule from the table, not from a summary. A full measurement of every fixture is still the first
step of the fixture gate.
