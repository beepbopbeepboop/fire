# INTERP: list slice step is silently ignored — wrong results, no error

## Status
**Fixed 2026-07-20.**

## Reproduction
```mojo
def f():
    var lst = [1, 2, 3, 4, 5, 6]
    print(lst[::2])
    print(lst[1:5:2])
f()
```
Run: `python3 mojo.py run test.mojo`

## Actual Behavior (before fix)
```
[1, 2, 3, 4, 5, 6]
[2, 3, 4, 5]
```

## Expected Behavior (matches real Python/Mojo slicing semantics)
```
[1, 3, 5]
[2, 4]
```

## Root Cause (confirmed)
The parser (`mojo_compiler.py`'s `_parse_subscript_item`) was already parsing
the 3-part slice correctly — `SliceExpr.step` was populated fine. The bug was
purely in the interpreter's evaluator: `myinterpreter.py`'s
`Interpreter.eval_SliceExpr` read `expr.start`/`expr.stop` but never read
`expr.step` at all, and applied the slice as plain `obj[start:stop]`
(Python 2-part slicing), silently dropping the step component entirely.
Since `obj` for both `List` and `String`/`str` values is a native Python
`list`/`str`, both list slicing and string slicing shared this single
code path and therefore shared the exact same bug.

## Fix
`myinterpreter.py`, `Interpreter.eval_SliceExpr` (~line 3371): now also
evaluates `expr.step` and builds a proper 3-arg slice:

```python
def eval_SliceExpr(self, expr: N.SliceExpr):
    """Evaluate slice expression."""
    obj = self.eval_expr(expr.obj)
    start = self.eval_expr(expr.start) if expr.start else None
    stop = self.eval_expr(expr.stop) if expr.stop else None
    step = self.eval_expr(expr.step) if expr.step else None
    return obj[start:stop:step]
```

Since `obj` is a plain Python `list`/`str` at runtime, `obj[start:stop:step]`
gets correct native Python slicing semantics for free, including negative
steps.

## Verification
All via `python3 mojo.py run`, on the interpreter path:
- `lst[::2]` → `[1, 3, 5]` (matches expected)
- `lst[1:5:2]` → `[2, 4]` (matches expected)
- `lst[::-1]` → `[6, 5, 4, 3, 2, 1]` (negative-step reversal, correct)
- `lst[::3]` → `[1, 4]` (step-only, no start/stop, correct)
- `lst[5:2:1]` → `[]` (empty-result slice, correct — matches Python)
- `lst[1:4]` → `[2, 3, 4]` (ordinary 2-part slice, unaffected/still correct)
- `"abcdefgh"[::2]` → `"aceg"` (string slicing, same code path, correct)
- `"abcdefgh"[::-1]` → `"hgfedcba"` (string reversal, correct)

## Test suites
- `python3 test_gimple.py`: 159 passed, 0 failed (unaffected — fix is
  interpreter-only, this file wasn't touched).
- `test_myinterpreter.py`, `test_myinterpreter_simple.py`,
  `test_myinterpreter_validation.py`: all three fail to even start, both
  before and after this fix (`ModuleNotFoundError: No module named 'parser'`
  and `FileNotFoundError: mojo/ast_nodes.mojo`) — confirmed pre-existing and
  unrelated to this change (reproduced identically with the fix stashed
  out).

## Out-of-scope sibling finding (compiled path)
`gimple_codegen.py`'s `_lower_slice` (~line 8979) has the identical bug: it
reads `node.start`/`node.stop` and lowers to `mojo_str_slice`/
`mojo_list_slice`/`mojo_cstr_slice`/pointer-arithmetic calls that only ever
take start/stop — `node.step` is never read anywhere in that function. This
report is explicitly interpreter-scoped, so the compiled path was left
unfixed; a real end-to-end compiled-binary repro under `mojo.py build` was
not reachable to confirm at runtime because the current build has an
unrelated pre-existing linker failure (`symbol not found in flat namespace
'_CUDA_0c85c9'`) on this machine, but the static-code read leaves no
ambiguity that the same gap exists there. Should be filed/fixed as its own
follow-up.
