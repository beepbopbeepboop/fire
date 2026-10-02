# CODEGEN: a generator that ITERATES a list/dict parameter still cannot type what it yields

**State: OPEN, reproduced 2026-09-29, all three silent-wrong-value shapes
measured against CPython. Not fixed.**

Found while closing item 8 of
`bugs/hard/CODEGEN_coro_yield_kind_unresolved_callsite.md`. That work typed
the loop target when a generator's list parameter has positive list evidence
(`_mojo_coro_param_elem_kinds` -> `_param_elem_types` -> `_elem_types` ->
`_boxed_list_ptr`). These three shapes are the ones that evidence does not
reach, and they are all the same underlying gap reached from different sides:
**a generator's `for <t> in <param>:` and its own value slot are decided by two
independent inferences that never see each other.**

All measured with the gimple backend (compile -> `gcc -fgimple` -> link
`fire_runtime.c` + the A3 coroutine objects -> run) against `exec`-ing the
identical text as Python. Every one of the three exits 0 with wrong output.

## 1. A tuple loop target is not in `_static_env` — the element truncates

```mojo
def rows(data):
    for i, r in enumerate(data):
        yield i
        yield r

def main():
    for v in rows([1.5, 2.5]):
        print(v)
```

    CPython:   0 1.5 1 2.5
    compiled:  0 1 1 2

The loop is now typed correctly — the generated body declares
`double r;` and reads `r = mojo_list_get_double (_t4, _t8)` (verified in the
emitted C) — and the value is then handed to an **`int64_t` value slot**,
because `_static_env`'s for-loop arm bails on a tuple target:

```python
tname = n.target.name if isinstance(n.target, N.IdentExpr) \
    else (n.target if isinstance(n.target, str) else None)
if tname is None or tname in env:
    continue
```

`ForStmt.target` for `for i, r in ...` is not an `IdentExpr`, so neither `i`
nor `r` ever enters the env, both `yield`s come back `None`, and the value
kind is the `int64_t` default.

Note this is NOT caught by the yield-site hole rule landed with item 8
(`_generator_value_kind`): that rule refuses a `None` beside a `char *` or
`double` kind, and here **every** kind is `None`, which is the ordinary
untyped generator and must keep compiling.

**Next step**: teach the same arm the tuple target, for the two shapes with a
known slot meaning — `enumerate(<x>)`, whose slot 0 is `i` and whose slot 1 is
`x`'s element kind. That alone turns this program's kinds into
`{'i', 'd'}`, which the *existing* mixed-float check already refuses, so the
wrong value becomes an honest refusal without touching the value-kind rules.

## 2. A dict argument's keys are read as the value slot

```mojo
def rows(data):
    for r in data:
        yield r

def main():
    d = {"k": 1.5}
    for v in rows(d):
        print(v)
```

    CPython:   k
    compiled:  4330428736        (the key's heap address)

A dict argument to an unannotated param is a hole for `_argkind`, so
`_CALLSITE_PARAM_KINDS['rows']` has no `data` entry and the value slot is
`int64_t`. The loop, meanwhile, takes the runtime dict-or-list dispatch (there
is no positive list evidence, correctly) and the dict arm binds the target `r`
to `char *` from `mojo_dict_iter_key`. The slot and the target then disagree
and the key is printed as a decimal.

**Next step**: this is the one-C-type-per-slot problem at a NEW site — the
value slot and the loop target, not the call sites and the yield. Either the
loop target's type has to become an input to the value-slot choice (the
generator yields exactly what it iterates, so `'p'` is forced), or a generator
whose value slot and loop target provably disagree has to be refused. The
refusal is the smaller change and is the honest direction.

## 3. A list of lists through a generator

```mojo
def rows(data):
    for row in data:
        for cell in row:
            yield cell

def main():
    for v in rows([[1, 2], [3, 4]]):
        print(v)
```

    CPython:   1 2 3 4
    compiled:  -104 25 -20 -40 25 -20      (garbage)

The generator-side twin of
`bugs/CODEGEN_nested_list_loop_target_loses_inner_elem_type.md`, and the same
fix: the outer loop's target is typed `MojoList *` but never inherits the
iterable's **nested** element ctype, so the inner loop reads the inner lists
through `mojo_list_get_int`. That doc's "next step" applies unchanged, with
`_mark_coro_param_elem_kinds` needing the same nested half (it currently skips
any param whose element kind is a container, on purpose: a container of
containers has no single C type without the nested slot).

## Not bugs — the two shapes here that are already right

- **Heterogeneous element types at different call sites** (`rows([1.5, 2.5])`
  and `rows([7, 8])` in one module): one call site's `int64_t` elements carry
  no information (that is what the `int64_t` default already assumes), so the
  slot resolves to `double` and the int call reads raw bits. This is the
  one-C-type-per-slot limitation, documented in
  `_record_param_elem`/`_informative_elem_ctype`; unresolvable without a
  tagged ABI, and not worth a refusal that would take the float call out too.
- **A loop-target name rebound to a different element domain inside a
  generator** (`for r in data: yield r` then `for r in ["z"]: yield r`): an
  honest `gcc -fgimple` refusal ("pointer value used where a floating-point
  was expected"), which is `_gen_for_list`'s own documented rebind hazard
  surfacing now that the first loop is typed. No code change wanted.

## Scope

`mojo/middle/coro.py` (`_static_env`) and the generator body emitter, plus the
same loop lowering as item 8 — so a full `make gate`, and the stdlib
unexpected-failure / skip counts have to be compared before and after.
