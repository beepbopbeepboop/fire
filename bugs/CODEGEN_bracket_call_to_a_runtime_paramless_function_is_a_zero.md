# A bracket-parametrised call (`f[T=7]`) compiles to a literal `0` unless link mode specialises it AND the callee has a runtime parameter

**Found 2026-10-02 on `work/bugs4-3`** while fixing
`bugs/CODEGEN_interpreter_evaluates_a_keyword_bracket_call_as_a_subscript.md`
(deleted with that fix). That doc treated the compiled path as the
reference for what a bracketed call means; it is not one. The interpreter
answers `7`; the compiled path answers `0`, silently, exit 0, on every
pipeline, for two independent reasons.

## What I ran

Two harnesses, both three lines, both in `.tmp/kb/probe1.py` (single
translation unit: `gimple_codegen.compile_to_gimple` + `gcc -fgimple` +
`runtime/fire_runtime.c`) and `.tmp/kb/probe_link.py` (the real program
path: `driver.compile_program`, i.e. `do_imports=True` +
`link_imports=True`, then run the binary).

```mojo
def b[T: Int](n: Int) -> Int:
    return T + n

def a[T: Int]():
    return T

def main():
    print(b[7](10))
    print(a[7]())
```

| program | expected | link mode (`driver.compile_program`) | single TU (`compile_to_gimple`) |
|---|---|---|---|
| `b[7](10)` | `17` | **`17`** | `0` |
| `a[7]()` | `7` | `0` | `0` |

And the tree's own existing case, which is why this went unnoticed:

```
$ python3 .tmp/kb/probe1.py 'def add_const[lhs: Int](rhs: Int) -> Int:
    return lhs + rhs

def main():
    print(add_const[1](10))'
STDOUT: '0\n'
```

`test_comptime_bracket_params.py::test_free_function_int_comptime_param`
asserts `add_const[1](10)` → `11`, and it passes — because that suite
builds through `driver.compile_program` (its own docstring says so). Every
other consumer of the single-TU path gets `0`.

## The two defects, in the emitted C

**1. The single-TU path never specialises at all.** Every bracket call site
lowers to a dropped call, whatever the callee looks like:

```c
int64_t _gimple_main (void)
{
  ...
  _t1 = (int64_t)0;  /* indirect call via SubscriptExpr */
  ... sprintf (_t2, _t4, _t1); ...   /* prints "0" */
```

This is not a missing specialisation for one shape: it is what every
`f[...]()` call in a non-link-mode build becomes. The machinery that
answers it (`_elaborate_generic_call` plus the per-call-site
instantiation objects) lives in the link-mode configuration only — which
is consistent with `bugs/CODEGEN_comptime_bracket_parametrized_function_
calls_silently_wrong.md`'s own framing (that fix was link-mode-only too,
and the same file's note that "the plain `compile_to_gimple_cached` +
single-`.o` build `mojo build` uses has no notion of extra elaboration
objects at all"). What is missing is any REFUSAL in the single-TU path: a
shape whose only answer is a specialisation should be refused by name
there, not answered `0`.

**2. In link mode, a callee with no runtime parameter is not specialised.**
`b` (one runtime parameter) works; `a` (none) does not, and inside `a` the
comptime parameter is an undeclared name:

```c
int64_t a (void)
{
  int64_t _t1;
  _t1 = (int64_t)0;  /* ct param or undeclared: T */
  return _t1;
}
```

That comment is the whole defect: `T` is a declared parameter of `a`, and
the parameter was never bound from the bracket. The elaborated
instantiation for a zero-runtime-argument callee is presumably never
recorded (nothing to thread the extra argument through), so the call site
falls back to the same `/* indirect call via SubscriptExpr */` zero as
defect 1.

## Why it matters, and what it is NOT

It is a **silent wrong answer**, not a crash and not a refusal, on the
path `mojo build` takes by default (`driver.compile_program`) for the
zero-runtime-parameter shape. `std/sys/info.mojo`'s `platform_map` and
every other bracketed helper in the stdlib is a comptime-only function, so
this is the shape that reaches real code.

It is **not** the keyword-bracket spelling: `a[T=7]()` and `a[7]()` both
answer `0` here, so the parser's keyword/positional distinction — the
subject of the interpreter bug just fixed — is not involved on this side.

## Next step

Two questions, in this order, and the first one may make the second
moot:

1. **Should the single-TU path refuse a bracketed call it cannot
   specialise?** `_lower_call`'s final catch-all
   (`if not isinstance(node.func, IdentExpr): return 'int', self._new_val('int', '0')`)
   is where `/* indirect call via SubscriptExpr */` comes from, and it is a
   wrong answer for this shape on every path — link mode included for the
   zero-runtime-parameter case. Making it name the shape
   (`a bracketed call f[...]() needs link-mode specialisation, which this
   build does not do`) would convert a silent `0` into an honest refusal,
   which is this codebase's rule for an uncertain shape, and would cover
   both defects at once.
2. If a real answer is wanted instead: the link-mode elaborator must
   record an instantiation for a callee whose parameter list is empty, and
   bind its comptime parameters into the elaborated body. That is the
   `b`-with-`n`-removed case of whatever threads `T` for `b`, and it is
   where the fix belongs if the single-TU path is not going to refuse.

## Evidence

- The two probe scripts are three-line harnesses; both outputs above are
  measured, not inferred, and the C excerpts are quoted from
  `compile_to_gimple`'s output.
- `test_comptime_bracket_params.py`'s own `_build_and_run` docstring
  records that it goes through `driver.compile_program`, which is why its
  `add_const[1](10)` → `11` assertion and the single-TU `0` above are not
  in conflict.