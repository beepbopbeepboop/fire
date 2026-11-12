# COMPILE_FAIL_Tools_cases_generator_analyzer-part3: the str()/repr() None guard must not be a parenthesized ternary in a `__GIMPLE` body

Part 3 of 4 of `bugs/hard/COMPILE_FAIL_Tools_cases_generator_analyzer.md`.

## Goal

Remove the last analyzer-owned gcc error,
`analyzer.py:194:10: error: expected expression before '(' token`. It is not a
comprehension bug: the `str(<struct>)` lowering emits the None guard as a
parenthesized C conditional expression, and `gcc -fgimple` rejects `(...)` in
operand position inside a `__GIMPLE` body.

## Current state (measured 2026-11-11, HEAD `d210765a2`)

The analyzer build (part2's command) reports the error twice, both at
`analyzer.py:194:10`, both on the `", ".join([str(c) for c in self.caches])`
line. `Uop.dump` is a struct method, so its body is `__GIMPLE`-tagged. The
generated C at that point is:

```c
  _t21 = mojo_list_get_int (_t17, _t19);
  _t22 = (int64_t)_t21;
  c = (CacheEntry *)_t22;
  _t23 = c;
  _t24 = CacheEntry___str__ (_t23);
  _t25 = (_t23 ? _t24 : _slit_10243);       /* <-- reported as 194:10 */
  mojo_list_append_str (_t16, _t25);
  ...
  _t29 = StackEffect___str__ (_t14);
  _t30 = (_t14 ? _t29 : _slit_10243);       /* <-- the second one */
```

Column 10 is the `(` of the parenthesized conditional. Two independent gcc
probes on this machine (`/opt/local/bin/gcc-mp-15`, the tree's `find_gcc()`)
confirm the rule:

```c
void __GIMPLE f (long long c, long long a, long long b)
{ long long t; t = (c ? a : b); }        /* error: expected expression before '(' token */

void __GIMPLE g (long long c, long long a, long long b)
{ long long t; t = c ? a : b; }          /* OK */

char *h (long long *p);
void __GIMPLE k (long long c, long long *p, char *s)
{ char *t; t = c ? h (p) : s; }          /* error: invalid operands in ternary operation */
```

So simply dropping the parentheses is not enough: one arm is a function call,
and a call is not a legal ternary operand in GIMPLE either. The select has to
be lowered as real control flow.

The emitting site is one line,
`mojo/middle/calls_shared.py:890`, in `user_dunder_repr_call`:

```python
return gen._new_val('char *', f'({_local} ? {_call} : {_none})')
```

`_new_val` emits `t = rhs` (`mojo/backend_gimple/emit_resolve.py:2130`), so the
rhs must be a legal GIMPLE r-value. `user_dunder_repr_call` is the single shared
dunder lookup for both `_repr_value` (`repr(x)`, `%r`) and `_stringify_value`
(`str(x)`, `%s`, f-strings), so the same defect covers `repr()` of a struct
with a user `__repr__`. A grep of `? ... : ...` emissions inside `_new_val`
calls finds this as the only parenthesized one; the others pass plain variable
operands and are legal.

## Plan

1. **Lower the guard as a branch, not as a C `?:`.** Add one small shared helper
   next to `_new_val` (e.g. `_select_val(gen, ctype, cond_ctype, cond_val,
   then_val, else_val)` in `mojo/backend_gimple/emit_resolve.py`), which:
   allocates the result temp with `_new_temp`, normalizes the condition with
   `_ensure_bool_cond`, emits `if (cond) goto bb_then; else goto bb_else;`,
   assigns the then value in its block, the else value in its block, and returns
   the temp. This is the same three-block shape as
   `_lower_TernaryExpr` (`mojo/backend_gimple/emit_exprs.py:1435`); do not
   hand-write a second `? :` expression string at this call site.
   Call it from `user_dunder_repr_call` with `then = _call` and
   `else = _none`.
2. **Keep the call lazy.** It must run only when `_local` is non-NULL, exactly
   as CPython's `str(x)` semantics and the current C ternary intend. A
   branch-based select preserves that; an eager both-arms version would call a
   user `__str__` on NULL.
3. **Do not touch the other `? :` sites.** `emit_loops.py`, `emit_calls.py` and
   `emit_exprs.py` emit bare `cond ? a : b` with simple variable operands, which
   gcc accepts. Changing them is unrelated churn.
4. **Test** as below. The fixture must put the call in a struct method (a
   `__GIMPLE` body); a top-level function is not tagged and would not reproduce.

## Acceptance

* The fixture below compiles with `gcc -fgimple` and the binary prints
  `I1, I2` (CPython's answer). Today gcc rejects the generated C with
  `error: expected expression before '(' token`.
* The analyzer build no longer reports `analyzer.py:194`. (It may still stop on
  part2's sibling-layout errors until part2 lands; this part removes its own
  two diagnostics.)
* The same fixture with `repr(...)` instead of `str(...)` and a user
  `__repr__` behaves the same, since both go through
  `user_dunder_repr_call`.

## Done when

`python3 test_paren_ternary_gimple_operand.py` (new file) exits 0.

The fixture:

```python
class Item:
    def __init__(self, n: int):
        self.n = n
    def __str__(self) -> str:
        return "I" + str(self.n)

class Holder:
    def __init__(self):
        self.items = [Item(1), Item(2)]
    def dump(self) -> None:
        print(", ".join([str(c) for c in self.items]))

Holder().dump()
```

The test calls `gimple_codegen.compile_to_gimple(src)` (a struct method is
enough to tag the body `__GIMPLE`), compiles the result with
`find_gcc() -fgimple -I runtime`, runs the binary and compares stdout to
`python3` on the same source. `python3` prints `I1, I2`; the current tree fails
before the binary exists with `expected expression before '(' token` at the
`", ".join(...)` line (measured 2026-11-11).

Do **not** use `python3 fire.py run` as the oracle for this fixture: the
interpreter currently ignores a user `__str__` and prints `<Item instance>`
(separate bug, `bugs/INTERP_python_str_dunder_ignored.md`).

## Out of scope

* The interpreter's missing user-`__str__` dispatch (separate bug doc).
* The sibling-layout collision (part2) and class-pattern binding (part1).
