# PARSE_FAIL: a subscript expression (`d[key]`) as a for-loop/with-statement target fails to parse

## Status
Fixed 2026-07-25.

### Fix summary
- `mojo_compiler.py`'s `_parse_unpack_target` (~line 1228) now also accepts
  a trailing subscript, `[...]` (possibly chained, `d[1][0]`), on a target
  element, after the existing dotted-attribute loop. A new helper,
  `_capture_bracketed_text()` (~line 1228, right before
  `_parse_unpack_target`), consumes a balanced `[...]` while tracking
  bracket depth (so a nested `[` inside the subscript doesn't end capture
  early) and reconstructs the contents as source text by joining each
  consumed token's raw `.value` (every token's value is the exact matched
  source substring, including quotes on STRING tokens, per `_TOKEN_RE`) —
  the bracket and its text are appended to the comma-joined target string
  literally (`"d[\"k\"]"`, `"targets[1][0]"`), the same "keep it as literal
  text" scheme the sibling attribute-target fix established for `.attr`.
- `myinterpreter.py`'s `_bind_single_target` (~line 3909) now detects a `.`
  OR `[` in the target-string element (previously only `.`) and, if either
  is present, routes through a new helper, `_parse_target_path` (~line
  3933), which walks the string left-to-right building the equivalent
  `IdentExpr`/`MemberExpr`/`SubscriptExpr` AST — attribute and subscript
  access can be freely mixed/chained in one target path. A subscript's
  `[...]` contents are re-tokenized/re-parsed as real Mojo source via
  `mojo_compiler.py`'s own `py_tokenize`/`Parser` (the same approach
  `_eval_fstring_expr` already uses for f-string field interpolation),
  since — unlike an attribute name — a subscript key is an arbitrary
  expression, not just a bare identifier. The resulting AST is handed to
  the existing `_assign_target`, which already has `SubscriptExpr` handling
  (`obj[idx] = value`) for ordinary subscript-assignment statements — no
  new subscript-set logic was written specific to `for`/`with`.
- Character-class scanning inside `_parse_target_path` deliberately avoids
  `ch.isalnum()` on a bare (dereferenced) single `char` — a real
  self-hosting gap this fix's first attempt hit: `gimple_codegen.py` only
  lowers string-predicate methods (`.isalnum()` etc.) for a `char *`
  receiver (`_lower_str_method`), never for a bare `char` one, AND
  `isalnum` is separately listed in `_C_RESERVED_FUNCS`, so a bare-char
  `.isalnum()` call silently mangles to an undefined-at-link-time symbol
  (`char_mojo_isalnum`) instead of raising a clear compile-time error —
  invisible until `make check-selfhost`'s link step. Fixed by adding a new
  `_is_ident_char` static helper using explicit range comparisons
  (`'a' <= ch <= 'z'`, etc.) instead, mirroring the single-char-comparison
  style `mojo_compiler.py`'s own multiline-string-prefix scanner already
  uses for the same reason.

### Scope: comma-containing subscript keys not supported
Per this doc's own original scope guidance: a subscript's `[...]` contents
are an arbitrary expression that could itself contain a top-level comma
(`d[a, b]`, a tuple key). The PARSER correctly handles this — bracket-depth
tracking in `_capture_bracketed_text` means a comma nested inside `[...]`
is consumed as part of the subscript text, not treated as the outer
target-list's separator. However, `myinterpreter.py`'s
`_bind_comprehension_target` later re-splits the whole joined target string
on `,` with a plain `str.split(',')` that is NOT bracket-depth-aware, to
separate elements of a MULTI-element target list (e.g. `for a, d[0] in
...:`). A comma-containing subscript key would only be ambiguous in that
specific combination — a subscript-with-comma-key as ONE element of a
multi-element comma-separated target list. This is deliberately left
unsupported/undetected (not scope for this fix); the real-world motivating
case (`targets[1][0]`) and this bug's own repro (`d["k"]`) both use
comma-free keys.

### Verification
- Both of this doc's repros work: `with 5 as d["k"]:` prints `5`;
  `for d["k"] in [1, 2]:` prints `1`, `2`.
- Real-world motivating case, a 2-level CHAINED subscript target
  (`with mock_ctx() as targets[0][0]:`), works — prints `42`.
- Mixed tuple target combining a plain name and a subscript element
  (`for a, d[0] in pairs:`) works — prints `1`, `a`, `2`, `b`.
- Regression-checked (all still work unchanged): plain tuple target
  (`for a, b in pairs:`), starred target (`for first, *rest in [lines]:`),
  attribute target (`for st.lineno, line in items:`), and `with EXPR as
  (a, b):` tuple target.
- `python3 test_gimple.py` — 161 passed, 0 failed (unchanged).
- `python3 test_module_cache.py` — 64 passed, 0 failed (unchanged).
- `make check-selfhost` — passes (mojo.py compiling its own source, 1
  passed, 0 failed). This caught the bare-`char`-method-call self-host
  regression described above on the first attempt (undefined symbol
  `_char_mojo_isalnum` at link time); fixed by switching to
  `_is_ident_char`'s range comparisons, then re-verified clean.
- From-scratch stdlib dylib build
  (`rm -f build/libmojostdlib.dylib && python3 -c "import build_stdlib_dylib
  as bsd; bsd.build_stdlib(jobs=8)"`): skip count is **0** both before and
  after the change (`grep -c '^  skip'` on the build output); dylib built
  successfully.

## Original Report (for history)

## Status
Open (found 2026-07-25, re-testing the backlog for still-live parser bugs)

## Reproduction (two manifestations — same shared parser code)

**1. `with` statement:**
```mojo
def f():
    var d = {}
    with 5 as d["k"]:
        print(d["k"])
f()
```
```
SyntaxError: test.mojo:3:11: Expected COLON got LBRACKET('[')
```

**2. `for` loop:**
```mojo
def f():
    var d = {}
    for d["k"] in [1, 2]:
        print(d["k"])
f()
```
```
SyntaxError: test.mojo:3:5: Expected KW got LBRACKET('[')
```

Both fail in the same shared target-parsing code — `_parse_unpack_target`
(`mojo_compiler.py`), the helper this session already extended twice today
for `for`/`with` targets: once for a starred name (`for first, *rest in
...:`) and once for an attribute-access element (`for st.lineno, line in
...:`, and by extension today's `with EXPR as (a, b):` tuple-target fix,
which reused the same helper for `with`). It currently has no case for a
SUBSCRIPT expression (`NAME[expr]`, or a chain like `NAME[expr][expr2]`) as
a target element.

## Expected Behavior
`with EXPR as d["k"]:` should perform a subscript ASSIGNMENT
(`d["k"] = EXPR`, or whatever this codebase's `with` semantics actually
bind to) on each entry, and `for d["k"] in items:` should assign each
iteration's value into `d["k"]` via subscript-set — matching how the
already-fixed attribute-target case (`for st.lineno, line in ...:`) routes
through `_assign_target`'s existing `MemberExpr`-target handling; a
subscript target should route through whatever `_assign_target` already
does for a plain `d["k"] = value` assignment statement (`IndexExpr`/
`SubscriptExpr`-shaped target — check the exact AST node name this codebase
uses).

## Real-world impact
Confirmed via real CPython 3.14 stdlib source: `Lib/test/test_with.py:669`:
```python
targets = {1: [0, 1, 2]}
with mock_contextmanager_generator() as targets[1][0]:
```
(a `with`-target that's a CHAINED subscript, `targets[1][0]` — two levels
deep, so if you special-case just one level of `[...]`, make sure a second
consecutive `[...]` after the first also composes, the same way the
already-fixed attribute-target case had to consider chained `a.b.c`).

## Suggested approach
This is directly analogous to today's already-fixed attribute-target case
— read that fix's diff/bug doc first (`bugs/PARSE_FAIL_attribute_target_for_loop.md`,
"Fixed 2026-07-25" in this same directory) for the exact established
pattern: it represents a target as a plain string (comma-joined, with `*`/
dotted-attribute markers embedded as literal text), and
`myinterpreter.py`'s `_bind_comprehension_target`/`_bind_single_target`
splits on `.` to detect and rebuild an attribute target into a real
`MemberExpr` AST for `_assign_target` to handle. A subscript target will
need the analogous thing: extend `_parse_unpack_target` to also consume a
trailing `[...]` (possibly chained) after a leading name, keeping the `[`
and its contents as literal text in the target string (matching the `.attr`
precedent), and extend `myinterpreter.py`'s target-binding helper to detect
a `[`-containing name and reconstruct/evaluate it as a real
subscript-assignment AST node instead of a plain variable bind — reusing
`_assign_target`'s existing subscript-target handling (used for a plain
`d["k"] = value` statement) rather than writing new subscript-set logic
specific to `for`/`with`.

Note: unlike the attribute case (where the "attribute name" part is always
a simple trailing identifier), a subscript's `[...]` contains an arbitrary
EXPRESSION (the key/index), which is harder to safely embed as literal
text in a comma-joined string target representation (a key expression could
itself contain a comma, e.g. `d[a, b]` for a tuple key, which would be
ambiguous with the outer comma-separated target-list). Use judgment on how
to handle this correctly — e.g. only support a single subscript with a
comma-free key expression for now (covering the real-world motivating case,
which uses plain integer-literal keys) and document any deliberately
unsupported edge case (like a comma-containing subscript key) rather than
silently mishandling it.

## Files Likely Affected
- `mojo_compiler.py` — `_parse_unpack_target` (shared by `_parse_for` and
  `_parse_with`, per today's earlier fixes in this same area).
- `myinterpreter.py` — `_bind_comprehension_target`/`_bind_single_target`
  (same shared helper today's attribute-target fix extended).
