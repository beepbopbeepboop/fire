# PARSE_FAIL: a real struct definition named after a keyword (e.g. `struct super:`) is misparsed and cascades into a confusing, mislocated error

## Status
Fixed 2026-07-25

## Reproduction
```mojo
struct super:
    var msg: Int
```
Run: `python3 mojo.py run test.mojo`

## Actual Behavior (before fix)
```
SyntaxError: test.mojo:1:1: Expected NAME or KW got NEWLINE
```
reported at the START of the file with no relation to the real problem —
a classic cascaded-error signature.

## Root Cause
This is a subtle side effect of the earlier fix in this same session for
`bugs/PARSE_FAIL_struct_keyword_as_identifier.md` (commit `8bb942a`, "Fix
two more keyword-vs-identifier collisions: decorator names and `struct`").

`super` is a real Python builtin with no special keyword status in real
Python, but this dialect's lexer treats it as a keyword — it lexes as a
`KW`-kind token, not `NAME` (see `_KEYWORDS` in `mojo_compiler.py`, which
includes `'super'` alongside `struct`, `fn`, `ref`, etc.).

The `struct`-as-identifier fix added a lookahead in `_parse_stmt` (around
line 1423) that only treats a `NAME`-kind token immediately after `struct`
as "looks like a real struct definition":
```python
looks_like_structdef = nxt.kind == "NAME" and nxt2.kind in (
    "LBRACKET", "LPAREN", "COLON")
```
Since `super` lexes as `KW`, not `NAME`, `struct super:` — a REAL struct
definition whose name happens to be keyword-shaped — no longer even
attempted `_parse_struct()`, falling through to expression-statement
parsing instead (`struct` as a bare identifier, followed by another bare
identifier `super`, which is not valid as an expression continuation) and
cascading into the garbage, mislocated error above.

Even after fixing that lookahead, `_parse_struct()`'s own name-read
(`name = self._expect("NAME").value`) would still reject `super` — it
only accepted `NAME`-kind tokens, not the keyword-shaped `KW` token that
`super` (and any other keyword-as-struct-name) actually lexes as.

A third, runtime-level issue was uncovered during verification (out of the
originally scoped two `mojo_compiler.py` spots, but required for the fix
to be useful, not just parseable): `myinterpreter.py`'s `eval_IdentExpr`
unconditionally special-cased the identifier `super` to trigger this
dialect's `super()`/`super.method()` base-class-access magic
(`_eval_super`), with no check for whether `super` was actually shadowed
by a real binding in scope (e.g. a user's own `struct super:` definition).
This exactly mirrors the parser-level keyword-collision problem, but one
layer up, at name resolution instead of tokenization/grammar.

## Fix
Three changes, two in `mojo_compiler.py` (the originally-scoped parser
fix) and one in `myinterpreter.py` (required for the fix to actually be
usable at runtime, found during verification):

1. `mojo_compiler.py`, `_parse_stmt`'s `struct`/`class` dispatch (the
   `if t.value in ("struct", "class"):` branch, `looks_like_structdef`
   check around line 1423): widened the name-shape check to accept a
   `KW`-kind token or backtick-quoted `STRING`, not just `NAME` — mirrors
   the `name_like` check the `fn` fix already uses a few lines above in
   the same function.
   ```python
   name_like = nxt.kind in ("NAME", "KW") or (
       nxt.kind == "STRING" and nxt.value.startswith("`"))
   looks_like_structdef = name_like and nxt2.kind in (
       "LBRACKET", "LPAREN", "COLON")
   ```
2. `mojo_compiler.py`, `_parse_struct`'s name-read (was `name =
   self._expect("NAME").value`, around line 2156): changed to `name =
   self._ident()`, this file's established "read a name, accepting
   keyword-shaped tokens" helper (already used by the `ref`/decorator/`fn`
   fixes landed earlier the same session).
3. `myinterpreter.py`, `eval_IdentExpr` (around line 3205): `super` now
   first tries an ordinary scope lookup (`self.scope.get('super')`) and
   only falls back to the magic `_eval_super()` base-class behavior on
   `NameError` — i.e. a real binding (a user's own `struct super:` def,
   or theoretically `var super = ...`) shadows the magic, matching real
   Python's plain name-shadowing semantics for a name that has no actual
   keyword status there. Mirrors CPython's own `test_super.py`
   (`test_shadowed_global`/`test_shadowed_local`), which the real
   `super()` compiler magic behaves the same way for.

## Verification
All done against the merged-in state of `master`'s
`8bb942a`/`d86b78e`/`21ec536`/`de3fcd3` (this worktree was stale and
required `git merge master` first to pick up the `struct`-as-identifier
fix this bug is a follow-up to).

- (a) Exact repro, extended to construct and use an instance:
  ```mojo
  struct super:
      var msg: Int

  fn main():
      var s = super()
      s.msg = 42
      print(s.msg)
  ```
  Before all three fixes: cascaded `Expected NAME or KW got NEWLINE` at
  1:1. After the two `mojo_compiler.py` fixes alone: parses, but
  `var s = super()` crashed at runtime with `NameError: name 'self' is
  not defined` (from the unconditional `_eval_super` magic intercepting
  the constructor call). After all three fixes: prints `42`. PASS.
- (b) CPython `test_super.py`'s motivating shape (`test_shadowed_local`:
  a struct named `super` defined outside a class, used from inside
  another struct's method) — adapted to this dialect:
  ```mojo
  struct super:
      var msg: String
      fn __init__(inout self, msg: String):
          self.msg = msg

  struct C:
      fn method(self) -> String:
          var s = super("quite super")
          return s.msg

  fn main():
      var c = C()
      print(c.method())
  ```
  Parses with no `SyntaxError`, runs, prints `quite super` — sane,
  non-crashing behavior confirmed (full semantic parity with CPython's
  `__class__`-cell-based zero-arg `super()` magic is out of scope — this
  interpreter's `super`/`super.method()` sugar is a simpler,
  self/bases-based mechanism, not implemented via closure cells at all).
  PASS.
- (c) Ordinary struct/class definitions with normal (non-keyword) names,
  including a plain `struct Point:`, a plain `class Shape:`, and a struct
  with a real base class — completely unaffected. PASS.
- (d) The already-fixed `struct`-as-plain-identifier case from earlier
  the same session (`var struct = 5; struct = struct + 1; print(struct)`,
  interleaved with real `struct Foo:` / `struct Bar(Foo):` definitions) —
  still works identically. PASS.
- (e) A struct with both a base class and a keyword-shaped name
  (`struct super(Base):`) — parses and runs correctly, constructs an
  instance, reads back a field set via `__init__`. PASS.
- Regression check on the magic `super`/`super.method()` base-class
  sugar itself (no user struct shadowing it): a `Dog(Animal)` struct
  whose `speak()` calls `super.speak()` — still resolves to the base
  class method correctly (`Rex makes a sound (woof)`), confirming the
  `eval_IdentExpr` scope-lookup-first change doesn't regress the normal
  case (the scope lookup raises `NameError` as before when nothing
  shadows `super`, falling through to the same `_eval_super` path
  unchanged). Note: `super()` — with call parens and zero args, i.e. the
  full Python-style compiler-magic form — was already broken
  pre-existing before this bug's fix (`TypeError: '_MojoSuper' object is
  not callable`, confirmed via `git stash`); not a regression, out of
  scope for this bug.

## Full Test Suite Results
- `python3 test_gimple.py`: 161 passed, 0 failed.
- `python3 test_module_cache.py`: 64 passed, 0 failed.
- `make check-selfhost`: 1 passed, 0 failed. Especially relevant since
  this codebase's own source (`mojo_compiler.py`, `myinterpreter.py`,
  etc.) defines many real structs via the exact code paths touched here.
- From-scratch stdlib dylib build skip-count check:
  ```bash
  rm -f build/libmojostdlib.dylib
  python3 -c "import build_stdlib_dylib as bsd; bsd.build_stdlib(jobs=8)" 2>&1 | grep -c '^  skip'
  ```
  Result: `0` both before (baseline, confirmed via `git stash`) and after
  the change — no new skips introduced, every stdlib module still
  clean-compiles. Build completed cleanly with no errors either run.

## Files Changed
- `mojo_compiler.py` — `_parse_stmt`'s `struct`/`class` dispatch
  (`looks_like_structdef`, around line 1423) and `_parse_struct`'s name
  read (around line 2156, now `self._ident()`).
- `myinterpreter.py` — `eval_IdentExpr`'s `super` special-case (around
  line 3205), now scope-lookup-first with magic-`super` as the fallback.
