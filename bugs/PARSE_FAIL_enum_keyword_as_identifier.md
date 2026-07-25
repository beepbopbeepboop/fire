# PARSE_FAIL: `enum` used as a plain variable/parameter name is misparsed as the `enum` definition keyword

## Status
Fixed 2026-07-25

This is the fourth instance of the same keyword-vs-identifier collision
pattern already fixed in this codebase for `fn` (`bugs/PARSE_FAIL_fn_keyword_as_identifier.md`)
and `struct` (`bugs/PARSE_FAIL_struct_keyword_as_identifier.md`,
`bugs/PARSE_FAIL_struct_named_keyword.md`).

## Reproduction
```mojo
def f():
    enum = 5
    print(enum)
f()
```
and
```mojo
def f():
    var enum = 5
    enum.something(1, 2)
f()
```
Run: `python3 mojo.py run test.mojo`

## Actual Behavior (before fix)
```
SyntaxError: test.mojo:2:8: Expected NAME got ASSIGN('=')
```
and
```
SyntaxError: test.mojo:3:8: Expected NAME got DOT('.')
```
`_parse_stmt`'s `enum` dispatch (`if t.value == "enum": return
self._parse_enum()`, around line 1490) unconditionally committed to
enum-definition parsing whenever a statement started with the token
`enum`, with no lookahead to check whether the following tokens could
actually form an enum definition. Real Python has no `enum` keyword — it's
a common plain identifier (e.g. a local var named `enum`, independent of
the stdlib `enum` module import) — so this collision is real, exactly like
the `fn`/`struct` collisions fixed earlier.

## Expected Behavior
`enum` should be usable as an ordinary variable/parameter/attribute name
when not immediately followed by the shape of a real enum definition
(name-like token then `(` or `:`), while still parsing as an enum
definition when it is.

## Fix
`mojo_compiler.py`'s `_parse_stmt`, `enum` dispatch (previously an
unconditional `return self._parse_enum()` around line 1490): added the
same positive-lookahead disambiguation used for `fn`/`struct` — only
commit to `_parse_enum()` when `enum` is followed by a name-like token
(NAME/KW/backtick-STRING) and then one of `(` (optional base-class list)
or `:` (straight into the body); otherwise fall through to ordinary
expression/assignment-statement parsing (which already accepts KW tokens
as identifiers via `_parse_primary`).

Also widened `_parse_enum`'s own name-read from `self._expect("NAME")` to
`self._ident()` (NAME/KW/backtick), matching the `struct super:` fix for
`_parse_struct`'s name read, so an enum can itself be named after another
keyword (e.g. `enum struct:`).

## Verification
- Exact bug repro now parses and runs successfully: `enum = 5; print(enum)`
  prints `5`. `var enum = 5; enum.something(1, 2)` correctly reaches
  runtime and fails there with `AttributeError: 'int' object has no
  attribute 'something'` (out of scope — there's no `.something()` method
  on `int`; the fix is about parsing, not runtime semantics), same as the
  analogous `struct.pack_into(...)` case in the `struct` fix.
- A real enum definition (`enum Color:\n    RED\n    GREEN\n    BLUE`)
  immediately adjacent to enum-as-identifier code (a function using `enum`
  as a local variable) still parses and executes correctly —
  `Color.RED`/`Color.BLUE` resolve to `0`/`2` as expected, and the
  enum-as-identifier function still prints `8` for `enum=7; enum+1`.
- `enum` as a bare read/attribute-base/call-argument in the middle of an
  expression (e.g. a function parameter named `enum`, or a local `enum`
  passed into another function) works correctly, confirming
  `_parse_primary`'s existing KW-as-identifier handling needed no change —
  same finding as the `fn`/`struct` fixes.
- `python3 test_gimple.py`: 161 passed, 0 failed.
- `python3 test_module_cache.py`: 64 passed, 0 failed.
- `make check-selfhost`: passes — 1 passed, 0 failed.
- From-scratch stdlib dylib build skip-count check:
  ```bash
  rm -f build/libmojostdlib.dylib
  python3 -c "import build_stdlib_dylib as bsd; bsd.build_stdlib(jobs=8)" 2>&1 | grep -c '^  skip'
  ```
  Result: `0` both before (baseline, confirmed via `git stash`) and after
  the change — no new skips introduced, every stdlib module still
  clean-compiles.

## Files Changed
- `mojo_compiler.py` — `_parse_stmt`'s `enum` dispatch (the `if t.value ==
  "enum":` branch, previously an unconditional `return
  self._parse_enum()` around line 1490), plus `_parse_enum`'s name read
  (`self._expect("NAME")` → `self._ident()`). `_parse_primary` required no
  change.
