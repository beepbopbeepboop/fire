# PARSE_FAIL: chained assignment fails when the first target is a tuple-unpack

## Status
Fixed (2026-07-20)

## Reproduction
```mojo
def f():
    var pair = [1, 2]
    a, b = x = pair
    print(a)
    print(b)
    print(x)
f()
```
Run: `python3 mojo.py run test.mojo`

## Previous (Buggy) Behavior
```
SyntaxError: test.mojo:3:9: Unexpected ASSIGN('=')
```

## Expected Behavior (now matches)
Like Python: `x` is bound to `pair` (the full list), then `a, b` unpacks
`x`'s (i.e. `pair`'s) elements — `a=1`, `b=2`, `x=[1, 2]`.

## Root Cause
`mojo_compiler.py`'s `_parse_stmt` had two separate, mutually-exclusive
passes for the tail end of an assignment statement:

1. A "tuple-target" branch (entered when the first parsed expression was
   followed by `COMMA`) that collected a comma-separated target list, then
   expected exactly ONE `=` followed by the real RHS — no further chaining.
2. A "chained assignment" branch (entered when the first parsed expression
   was directly followed by `=`, no comma) that looped to collect
   `target = target = ... = RHS`, but each target in that loop was parsed as
   a single expression, never a comma-separated tuple-unpack.

Since only one of the two branches could ever run for a given statement, a
tuple-unpacking target followed by ANOTHER `= target` link before the real
RHS (`a, b = x = pair`) fell into neither: branch 1 consumed `a, b`, then
consumed the first `=` and parsed `x` as `val`, then had no handling for
the second `=` that followed — leaving it unconsumed and producing
"Unexpected ASSIGN" back at the top-level statement loop.

## Fix
`mojo_compiler.py` (`_parse_stmt`, the assignment-handling tail after
`expr = self._parse_expr(0)`): replaced both branches with a single unified
algorithm. It parses a comma-separated "group" after each `=` (or the
initial expression), and as long as an `=` follows a group, that group is
treated as another target in the chain (a single-element group is a plain
target, a multi-element group is a tuple-unpacking target); the first group
NOT followed by `=` is the real RHS. This means ANY link in an assignment
chain — first, middle, or last position — can independently be a plain name
or a comma-separated tuple-unpack. A single target chain (`x = y = expr`)
still returns a plain `AssignStmt`/2-element `MultiAssignStmt` exactly as
before; a single tuple-unpack target (`a, b = expr`) still returns a plain
`AssignStmt` with a `TupleExpr` target exactly as before. The old dead
"Assignment / augmented assignment" ASSIGN-handling block (now unreachable,
superseded by the unified pass above) was removed, leaving only the
`AUGASSIGN` branch.

`myinterpreter.py`: no change needed on the actual merge target (`master`).
The worktree this fix was developed in was branched from a much older
commit that had no `execute_MultiAssignStmt` handler at all; `master`
already had one (added separately, see its own docstring: "was 'No handler
for MultiAssignStmt' — hit by ctypes/wintypes.py, tkinter/constants.py"),
and its existing `_assign_target`-based loop already handles a tuple-unpack
target generically — so the `mojo_compiler.py` parser fix alone was
sufficient once merged onto `master`.

## Verification
- Repro above: prints `1`, `2`, `[1, 2]` — correct.
- `i, j, k = x = g()` (3-way unpack, chain of 2, RHS a function call):
  correct (each of i/j/k gets its element, x gets the whole list).
- Regression: plain chained assignment `x = y = a[0]` (no tuple anywhere):
  still works (`x == y == a[0]`).
- Regression: plain single-target tuple unpack `a, b = expr`: still works.
- Regression: implicit-tuple RHS single target `args = usage, actions,
  groups, prefix`: still works.
- `python3 test_gimple.py`: 159 passed, 0 failed (this worktree's baseline
  before this change was also 159/0 — confirmed via `git stash` — so no
  regression; the 161/0 figure in project memory refers to a different
  checkout's state, not this worktree).
- `python3 test_module_cache.py`: 58 passed, 0 failed (baseline also 58/0
  via the same `git stash` check — no regression; again the 64/0 figure in
  project memory is a different checkout's baseline).
- `make check-selfhost`: passes (`self-host compiles + links clean`).
- From-scratch stdlib dylib build skip-count gate:
  ```bash
  rm -f build/libmojostdlib.dylib
  python3 -c "import build_stdlib_dylib as bsd; bsd.build_stdlib(jobs=8)" 2>&1 | grep -c '^  skip'
  ```
  prints `0` (both before and after the change) — no new skips introduced.

## Files Changed
- `mojo_compiler.py` — unified assignment/chained-assignment/tuple-unpack
  parsing in `_parse_stmt`.
- `myinterpreter.py` — added `execute_MultiAssignStmt` (delegates to
  `execute_AssignStmt`).
