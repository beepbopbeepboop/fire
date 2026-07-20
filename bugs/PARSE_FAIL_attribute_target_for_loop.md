# PARSE_FAIL: for-loop tuple-unpacking target with an attribute (member) element fails to parse

## Status
Fixed 2026-07-20.

### Fix summary
- `mojo_compiler.py`'s `_parse_for`'s nested `_parse_for_target()` (around
  line 1731) now accepts a dotted attribute-access expression as a
  target-list element: after consuming the leading NAME/KW token, it loops
  while the next token is `DOT`, consuming `.NAME` and appending it to the
  target string (`"st"` → `"st.lineno"`, chained `"a.b.c"` also works). This
  follows the exact same "keep it as literal text in the comma-joined
  string" pattern the same-day starred-target fix (`"*rest"`) already
  established, per the file's own docstring — no representational
  refactor needed.
- `myinterpreter.py`'s `_bind_comprehension_target` (~line 3718, used by
  both `execute_ForStmt` and `eval_Comprehension`) delegates every
  non-starred single-name bind to a new helper, `_bind_single_target(name,
  value)` (~line 3770): a plain name still does `scope.define()` as before;
  a dotted name is split on `.`, rebuilt as the equivalent
  `IdentExpr`/`MemberExpr` AST (nested `MemberExpr` for chained attributes),
  and passed to the existing `_assign_target()` — the same routine that
  handles ordinary `obj.attr = value` assignment statements. No new
  attribute-set logic was written specific to for-loops.
- Also verified for free (cheap extension, not scope creep): a for-loop
  whose *entire* target is a single attribute expression, e.g.
  `for st.lineno in [10, 20]:`, works correctly too, since it goes through
  the same non-comma `_bind_single_target` path.

### Verification
- Bug's exact repro (`st.lineno, line`) prints `1`, `a`, `2`, `b` as
  expected.
- Regression-checked plain tuple target (`for a, b in pairs:`) and the
  same-day starred target (`for first, *rest in lines:`) — both still work
  unchanged.
- Extra case `for st.lineno in [10, 20]:` (attribute-only target, no comma)
  prints `10`, `20` as expected.
- `python3 test_gimple.py` — 161 passed, 0 failed (unchanged).
- `python3 test_module_cache.py` — 64 passed, 0 failed (unchanged).
- `make check-selfhost` — passes (mojo.py compiling its own source, 1
  passed, 0 failed).
- From-scratch stdlib dylib build
  (`rm -f build/libmojostdlib.dylib && python3 -c "import build_stdlib_dylib
  as bsd; bsd.build_stdlib(jobs=8)"`): skip count is **0** both before and
  after the change (`grep -c '^  skip'` on the build output).

## Original Report (for history)

## Reproduction
```mojo
struct St:
    var lineno: Int
    def __init__(out self):
        self.lineno = 0
def f():
    var st = St()
    var items = [[1, "a"], [2, "b"]]
    for st.lineno, line in items:
        print(st.lineno)
        print(line)
f()
```
Run: `python3 mojo.py run test.mojo`

## Actual Behavior
```
SyntaxError: test.mojo:8:6: Expected KW got DOT('.')
```
The for-target parser apparently only accepts bare NAME tokens (optionally
comma-separated) as unpacking-target elements; `st.lineno` (an attribute/
member-access expression) as one element of the target list isn't
recognized at all — parsing fails immediately at the `.` after `st`.

## Expected Behavior
Each iteration should assign the first element of the current item to
`st.lineno` (i.e. `st.lineno = item[0]`, an attribute SET, not a variable
bind) and the second to the plain local `line`. First iteration:
`st.lineno = 1`, `line = "a"`; second: `st.lineno = 2`, `line = "b"`.

## Relationship to prior work
This session already fixed `for first, *rest in lines:` (starred for-target)
and confirmed plain `for a, b in pairs:` (bare-name tuple target) works.
This is a different, narrower gap: one element of the target list being an
**attribute expression** rather than a bare name. Real-world source example
(from the CPython 3.14 stdlib scan that populated this `bugs/` directory):
`Lib/configparser.py`'s `_read_inner`:
```python
for st.lineno, line in enumerate(map(self._comments.wrap, fp), start=1):
```
where `st` is a small state object and the loop directly mutates
`st.lineno` on each iteration instead of using a plain loop variable plus a
separate assignment.

## Files Likely Affected
- `mojo_compiler.py` — wherever for-loop targets are parsed (`_parse_for`/
  `_parse_for_target`, per this session's starred-target fix in the same
  area). Currently likely only accepts a NAME token (or `*NAME`, after
  today's fix) per target-list element; needs to also accept a general
  postfix/attribute expression (`NAME.NAME`, possibly chained
  `NAME.NAME.NAME`, and — check if worth supporting for symmetry —
  a subscript target like `NAME[expr]`, though the bug's own repro only
  needs the attribute case; don't scope-creep into subscript targets unless
  it's free).
- `myinterpreter.py` — wherever for-loop targets get bound each iteration.
  Binding a bare name uses `scope.define()`/similar; binding an attribute
  target needs to route through whatever mechanism plain attribute
  ASSIGNMENT already uses (`obj.attr = value`, i.e. `execute_AssignStmt`'s
  handling of a `MemberExpr` target) — reuse that rather than writing new
  attribute-set logic specific to for-loops.
