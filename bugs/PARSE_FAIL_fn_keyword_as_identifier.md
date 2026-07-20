# PARSE_FAIL: `fn` used as a plain variable/parameter name is misparsed as the `fn` function-definition keyword

## Status
Fixed 2026-07-20

## Reproduction
```mojo
def g():
    return 1, 2, 3, 4
def f():
    fn, lno, func, sinfo = g()
    print(fn)
    print(sinfo)
f()
```
Run: `python3 mojo.py run test.mojo`

## Actual Behavior (before fix)
```
SyntaxError: test.mojo:4:2: Expected NAME or KW got COMMA(',')
```
The statement `fn, lno, func, sinfo = g()` is being parsed as an attempted
*function definition* (`_parse_funcdef`), because the statement starts with
the token `fn`, which this Mojo dialect reserves as the `fn`-style function
declaration keyword. The parser never gets a chance to recognize this as a
plain tuple-unpacking assignment where `fn` happens to be used as an
ordinary identifier.

## Expected Behavior
`fn` should be usable as an ordinary variable/parameter/attribute name in
any position where a real function definition couldn't syntactically start
— i.e. Python code (which has no `fn` keyword at all) using `fn` as a local
variable name should work exactly like any other identifier. Real-world
example (from the CPython 3.14 stdlib scan that populated this `bugs/`
directory): `Lib/logging/__init__.py`:
```python
fn, lno, func, sinfo = self.findCaller(stack_info, stacklevel)
```

## Root Cause
`mojo_compiler.py`'s `_parse_stmt` dispatch already had a narrow,
incomplete carve-out for `fn`-as-identifier at statement start:
```python
if t.value in ("def", "fn"):
    # fn(  →  variable named "fn" being called; treat as expression
    # fn =  →  variable named "fn" being assigned; treat as expression
    if t.value == "fn" and self._peek(1).kind in ("LPAREN", "ASSIGN", "AUGASSIGN", "DOT"):
        pass  # fall through to expression statement
    else:
        self._advance(); return self._parse_funcdef([])
```
This enumerated only 4 "not a funcdef" shapes (`fn(`, `fn=`, `fn+=`, `fn.`)
and treated everything else — including `fn,` (a tuple-unpacking target),
`fn ==`, `fn is`, `fn[0]`, bare `fn`, etc. — as the start of a function
definition, so it fell into `_parse_funcdef`, which then choked on the
first non-NAME/KW token it found where it expected the function's name.

## Fix
`mojo_compiler.py`, in `_parse_stmt`'s `KW` dispatch (the `if t.value in
("def", "fn"):` branch). Replaced the enumerate-what's-NOT-a-funcdef
approach with a positive shape check for what a real function definition
actually looks like: `fn` immediately followed by a name-like token (NAME,
KW, or a backtick-identifier STRING — matching what `_parse_funcdef` itself
accepts as a function name) and then either `(` (plain signature) or `[`
(generic params before the parameter list). Only when both conditions hold
does the parser commit to `_parse_funcdef`; otherwise it falls through to
ordinary expression/assignment-statement parsing, where `fn` is accepted as
a plain identifier via `_parse_primary`'s existing `t.kind in ("NAME",
"KW")` → `IdentExpr` handling (already correct, no change needed there —
`print(fn)`, `obj.fn`, `somefunc(fn)` already worked mid-expression before
this fix; only the statement-start dispatch was wrong).

This is strictly more permissive than the old carve-out (it also lets `fn,`,
`fn ==`, `fn is`, `fn[0]`, bare `fn`, etc. fall through) while still being
strictly conservative about what counts as a real function definition, since
`_parse_funcdef` itself requires exactly "name-like token, then optional
`[...]`, then `(`" to parse a signature at all.

`def` is unaffected — it was already unconditionally routed to
`_parse_funcdef`, and `def` has no realistic identifier-collision risk
since it's already a hard keyword in real Python too.

## Verification
- Exact bug repro: prints `1` then `4` — pass.
- Real `fn` definitions immediately followed by more `fn`-adjacent code,
  including generics and `mut`/`out self` struct-method conventions
  (`fn foo(x: Int) -> Int:`, `fn bar():`, `fn __init__(out self, x: Int):`,
  `fn __copyinit__(out self, other: Self):`, `fn get(mut self) -> Int:`,
  `fn add[T: Intable](self, y: T) -> Int:`, plus a *following* statement
  that itself starts with `fn` used as an identifier) — all parse and
  execute correctly, no lookahead state leaked across statements.
- `fn` as a bare read (`print(fn)`), as a struct field / attribute name
  (`self.fn`, `o.fn`), and as a call argument (`somefunc(fn)`) — all pass.
- Tricky "looks funcdef-ish but isn't" cases: `fn = d["key"](x=5)` (RHS
  looks call-shaped but `fn` itself is followed by `=`, not `(`/`[`);
  `fn is not None` (`fn` followed by KW `is`, which is name-like, but the
  token after `is` is `not`, not `(`/`[`) — both correctly fall through to
  expression/assignment parsing instead of misfiring into `_parse_funcdef`.
- `python3 test_gimple.py`: 159 passed, 0 failed (confirmed via `git stash`
  that 159/0 is this branch's pre-existing baseline, not a regression from
  the stale "161" figure in older notes).
- `python3 test_module_cache.py`: 58 passed, 0 failed (likewise confirmed
  as the pre-existing baseline via `git stash`, not a regression from a
  stale "64" figure).
- `make check-selfhost`: passes — `mojo.py` self-hosted compiling `mojo.py`
  produces byte-identical/clean output, 1 passed, 0 failed. This is the
  most important check for this bug since this codebase's own source (and
  its self-hosted build path) makes extensive real use of `fn` definitions.
- From-scratch stdlib dylib build skip-count check:
  ```bash
  rm -f build/libmojostdlib.dylib
  python3 -c "import build_stdlib_dylib as bsd; bsd.build_stdlib(jobs=8)" 2>&1 | grep -c '^  skip'
  ```
  Result: `0` (every stdlib module still compiles, no new skips introduced).

## Files Changed
- `mojo_compiler.py` — `_parse_stmt`'s `fn`/function-definition dispatch
  (the `if t.value in ("def", "fn"):` branch, previously around line 1146
  in this checkout). `_parse_primary` required no change — it already
  accepted KW-kind tokens as plain identifiers mid-expression.
