# PARSE_FAIL: `struct` used as a plain variable/module name is misparsed as a struct-definition keyword

## Status
Fixed 2026-07-25

## Reproduction
```mojo
def f():
    var struct = 5
    struct.pack_into("q", 1, 2)
f()
```
Run: `python3 mojo.py run test.mojo`

## Actual Behavior (before fix)
```
SyntaxError: test.mojo:3:6: Expected NAME got DOT('.')
```
`_parse_stmt` sees the statement start with the token `struct` and
unconditionally calls `_parse_struct()` (`if t.value in ("struct",
"class"): return self._parse_struct()`), which then expects a struct NAME
immediately after — choking on the `.` that follows instead, since this
statement is really `struct.pack_into(...)`, an ordinary method call on a
variable named `struct`, not a struct definition at all.

## Expected Behavior
`struct` should be usable as an ordinary identifier in any position where a
real `struct Name:` definition couldn't syntactically start — matching how
this exact class of bug was already fixed for the `fn` keyword earlier this
session (see `bugs/PARSE_FAIL_fn_keyword_as_identifier.md`).

## Real-world impact
Confirmed via real CPython 3.14 stdlib source:
`Lib/multiprocessing/shared_memory.py:345`:
```python
struct.pack_into(
    "q" + self._format_size_metainfo,
    self.shm.buf,
    ...)
```
where `struct` is the real Python standard library module (imported earlier
in the file as `import struct`), used completely ordinarily.

## Root Cause
`mojo_compiler.py`'s `_parse_stmt` dispatch had an unconditional carve-out:
```python
if t.value in ("struct", "class"): return self._parse_struct()
```
with no lookahead at all — any statement starting with the token `struct`
(or `class`) was committed to `_parse_struct()`, which then does
`self._expect("NAME")` for the struct's name and fails on anything else,
including `.` (attribute access), `(` (a call), `=` (assignment), etc.

## Fix
`mojo_compiler.py`, in `_parse_stmt`'s struct/class dispatch (the `if
t.value in ("struct", "class"):` branch, around line 1396). Applied the
same positive-lookahead disambiguation strategy already established by the
`fn` fix: only commit to `_parse_struct()` for the `struct` keyword when the
token shape that follows could actually BE a struct definition — `struct`
immediately followed by a `NAME` token (per `_parse_struct`'s own
`self._expect("NAME")`, struct names are NAME-only, unlike function names
which also accept KW/backtick-string) and then one of `[` (struct param
block, e.g. `struct Baz[T: AnyType]:`), `(` (base-class list, e.g. `struct
Bar(Foo):`), or `:` (straight into the body, e.g. `struct Foo:`). Anything
else — `struct.attr`, `struct(...)` as a call, `struct =`, bare `struct`,
etc. — falls through to ordinary expression/assignment-statement parsing,
where `struct` is already accepted as a plain identifier via
`_parse_primary`'s existing KW-token-as-NAME handling (verified — no change
needed there).

`class` is left unconditionally routed to `_parse_struct()`, unchanged: a
variable literally named `class` is invalid in real Python too (`class` IS
a hard keyword there), so there is no realistic identifier-collision risk
for it, unlike `struct` which has no keyword status in real Python at all.

## Verification
- Exact bug repro now parses successfully; `struct.pack_into("q", 1, 2)`
  on an `Int`-valued `struct` variable correctly reaches runtime and fails
  there with `AttributeError: 'int' object has no attribute 'pack_into'`
  (out of scope — there's no real `struct`-module implementation in this
  interpreter; the fix is about parsing, not stdlib `struct` semantics).
- `var struct = 5; print(struct)` — pass.
- Real struct definitions immediately adjacent to struct-as-identifier
  code, including a plain struct (`struct Foo:`), a struct with a base
  class (`struct Bar(Foo):`), and a generic struct param block (`struct
  Baz[T: AnyType]:`), interleaved with functions that use `struct` as a
  local variable (assigned, reassigned, compared with `==`, read as a
  bare name, used as an attribute base after being assigned a real struct
  instance, and read from a wider scope) and a module-level `var struct =
  10` — all parse and execute correctly, output as expected.
- `struct` as a bare read (`print(struct)`), read into another variable,
  and as a base for `.x` attribute access on a real struct instance — all
  pass, confirming `_parse_primary`'s existing KW-as-identifier handling
  needed no change, same finding as the `fn` fix.
- `python3 test_gimple.py`: 161 passed, 0 failed.
- `python3 test_module_cache.py`: 64 passed, 0 failed.
- `make check-selfhost`: passes — 1 passed, 0 failed. Especially relevant
  here since this codebase's own source uses `struct` extensively for real
  definitions.
- From-scratch stdlib dylib build skip-count check:
  ```bash
  rm -f build/libmojostdlib.dylib
  python3 -c "import build_stdlib_dylib as bsd; bsd.build_stdlib(jobs=8)" 2>&1 | grep -c '^  skip'
  ```
  Result: `0` both before (baseline, confirmed via `git stash`) and after
  the change — no new skips introduced, every stdlib module still
  clean-compiles.

## Files Changed
- `mojo_compiler.py` — `_parse_stmt`'s `struct`/`class` dispatch (the `if
  t.value in ("struct", "class"):` branch, previously an unconditional
  `return self._parse_struct()` around line 1396). `_parse_struct` and
  `_parse_primary` required no change.
