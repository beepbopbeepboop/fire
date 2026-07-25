# PARSE_FAIL: `with expr as (a, b):` (parenthesized tuple-unpacking target) unsupported

## Status
Fixed (2026-07-25)

## Fix
- `mojo_compiler.py`: extracted the for-loop target parser (formerly a
  nested closure `_parse_for_target` local to `_parse_for`) into a proper
  method `_parse_unpack_target` (defined right after `_ident`, ~line 1191).
  Pure refactor — no behavior change for `for`-loop targets; `_parse_for`
  now calls `self._parse_unpack_target()` instead of the local closure.
- `_parse_with` (~line 2260): both `as`-target parse sites (the first
  with-item, and each subsequent comma-separated with-item) now call
  `self._parse_unpack_target()` instead of `self._ident()`. Because
  `_parse_unpack_target()` only treats a *parenthesized* group as a tuple
  target (a bare NAME/KW is returned as a plain string, and the method
  never itself consumes a top-level comma), this correctly accepts
  `with EXPR as (a, b):`, `as (a, b, c):`, and nested `as (a, (b, c)):`
  while leaving `with a() as x, b() as y:` (multiple context managers, each
  its own comma-separated with-item) untouched — the outer `while COMMA`
  loop in `_parse_with` still owns that comma; `_parse_unpack_target` never
  sees it.
- `myinterpreter.py`'s `execute_WithStmt` (~line 3003): binding
  `item.alias` now goes through `self._bind_comprehension_target(item.alias,
  entered)` instead of a bare `self.scope.define(item.alias, entered)`.
  `_bind_comprehension_target` already knows how to unpack a comma-joined
  string target ("a", "(a, b)", "(a, b, c)", nested, starred, or dotted)
  since for-loop targets use the exact same string representation — no new
  with-specific unpacking logic was written.

## Verification
- Repro from this file: prints `1` then `2`.
- `with EXPR as (a, b, c):` (3-way tuple): prints `1`/`2`/`3`.
- `with open(...) as fh:` (plain single-name target, the overwhelmingly
  common case): unaffected, still binds `fh` directly.
- `with a() as x, b() as y:` (multiple context managers): unaffected —
  confirmed byte-identical output before/after this change (both bind the
  raw instance, a pre-existing unrelated gap where `__enter__` isn't
  actually invoked via `hasattr`/MojoInstance; not touched by this fix).
- `with x():` (no `as` clause at all): unaffected, still runs the body
  with no binding.
- `python3 test_gimple.py`: 161 passed, 0 failed (unchanged).
- `python3 test_module_cache.py`: 64 passed, 0 failed (unchanged).
- `make check-selfhost`: passes (1 passed, 0 failed — mojo.py compiling
  its own source clean).
- From-scratch stdlib dylib build (`rm -f build/libmojostdlib.dylib` +
  `build_stdlib_dylib.build_stdlib(jobs=8)`): skip count is **0** both
  before and after this change (no regression from the documented 595/0
  clean-compile baseline).

## Reproduction
```mojo
def get_pair():
    return 1, 2
def f():
    with get_pair() as (a, b):
        print(a)
        print(b)
f()
```
Run: `python3 mojo.py run test.mojo`

## Actual Behavior
```
SyntaxError: test.mojo:4:19: Expected NAME or KW got LPAREN('(')
```
`_parse_with` (`mojo_compiler.py:2263`) calls `self._ident()` directly after
`as`, which only accepts a single bare NAME/KW token — it has no handling
for a parenthesized (or bare comma-separated) tuple-unpacking target the
way `for`/plain-assignment targets already do (this session already fixed
similar tuple-unpacking-target gaps in `for`-loop targets and chained
assignment).

## Expected Behavior
`with EXPR as (a, b):` should bind `a`/`b` by unpacking whatever `EXPR`'s
context-manager `__enter__` (or, in this codebase's simplified `with`
semantics if it doesn't do real context-manager protocol, whatever the
`with` value evaluates to) returns, exactly like a plain assignment
`a, b = EXPR` would.

## Real-world impact
Confirmed via real CPython 3.14 stdlib source:
`Lib/xml/etree/ElementTree.py:737`:
```python
with _get_writer(file_or_filename, encoding) as (write, declared_encoding):
```

## Files Likely Affected
- `mojo_compiler.py` — `_parse_with` (line ~2263). Currently calls
  `self._ident()` unconditionally after `as`; needs to also accept a
  parenthesized (and/or bare, if this codebase's grammar allows an
  unparenthesized comma-list here — check real Python's grammar, which
  requires parens for a with-target tuple unlike a for-target) comma-separated
  target list, producing whatever target representation this codebase's
  other tuple-unpacking sites already use (check what `_parse_for_target`
  or the assignment-statement tuple-target parsing produces, and reuse the
  same shape/mechanism rather than inventing a new one, per this project's
  consolidation convention).
- `myinterpreter.py` — wherever `with` statement execution binds its `as`
  target (verify it already knows how to bind a tuple/multi-name target via
  whatever shared unpacking-binding helper this session's earlier fixes
  established, e.g. `_assign_target`/`_bind_comprehension_target`/similar —
  reuse it, don't write new unpacking logic for `with`).
