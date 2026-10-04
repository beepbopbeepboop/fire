# CODEGEN: a generator that ITERATES a list/dict parameter still cannot type what it yields

**State: OPEN, reproduced 2026-09-29, all three silent-wrong-value shapes
measured against CPython. Not fixed.**

Found while closing item 8 of
`CODEGEN_coro_yield_kind_unresolved_callsite`. That work typed
the loop target when a generator's list parameter has positive list evidence
(`_mojo_coro_param_elem_kinds` -> `_param_elem_types` -> `_elem_types` ->
`_boxed_list_ptr`). These three shapes are the ones that evidence does not
reach, and they are all the same underlying gap reached from different sides:
**a generator's `for <t> in <param>:` and its own value slot are decided by two
independent inferences that never see each other.**

All measured with the gimple backend (compile -> `gcc -fgimple` -> link
`fire_runtime.c` + the A3 coroutine objects -> run) against `exec`-ing the
identical text as Python. Every one of the three exits 0 with wrong output.

## Status (2026-10-02, `work/bugs4-2`) — item 1's proposed next step is INSUFFICIENT, and the reason is now located: the two passes that answer "what does this generator yield" never see each other, and only ONE of them has a refusal

Re-measured on this tree; all three shapes reproduce exactly as below (item 1
compiled `0 1 1 2` where CPython prints `0 1.5 1 2.5`; item 2 printed the key's
heap address where CPython prints `k`).

The doc's own framing — "a generator's `for <t> in <param>:` and its own value
slot are decided by two independent inferences that never see each other" — is
right, and item 1 names one of the two. What is newly established is **which**
two, and that the fix item 1 proposes lands the value slot's KIND on the
A3 side only, which makes the compiled answer WORSE rather than honest.

### Item 1's next step was tried, and it is not enough

`_static_env`'s for-loop arm now handles the two-slot `enumerate(<x>)` target
(slot 0 is the index, slot 1 is `<x>`'s element kind — both statically known,
so there is no reason to skip the pair). Measured, that arm alone gives:

```
env(_static_env(rows)) = {'data': ('list', 'd'), 'i': 'i', 'r': 'd'}   ✓
_generator_value_kind(rows) = (None, 'mixed float / non-float yields (v0)')   ✓ refusal
```

The refusal is real, and on the A3 path a refusal is what the doc predicted.
**But `rows` is compiled through the C++20 emitter, not the A3 pass**, and that
emitter does not consult `_generator_value_kind` at all. It asks
`mojo/middle/exprtypes.py::_generator_yield_ctype`, which resolves each
`yield <expr>` with `_infer_simple_expr_ctype(n.value, known, ...)` — and
`known` is the generator's PARAMETER map (`_gen_cpp_generator_unit`'s
`self._cpp_list_local_elem_types` lineage), which contains no loop targets.
So `yield r` resolves `r` to nothing, becomes `int64_t`, `yield i` is
`int64_t`, the two agree, and the value slot is `int64_t`:

```
before the arm:  0 1 1 2
after  the arm:  0 <raw IEEE-754 bits> 1 <raw IEEE-754 bits>       WORSE
```

Reverted. The change is not in the tree, and this is the write-up of why: the
A3 pass's answer and the C++20 emitter's answer to the SAME question are two
separate inference passes, and only one of them can refuse.

### So the fix has two halves, in this order

1. **`_generator_yield_ctype`'s `known` map has to carry the loop targets the
   emitter itself types.** The emitter ALREADY types them — `_cpp_for_stmt`
   declares `double r;` and emits `r = mojo_list_get_double(...)` (this is in
   the doc's own analysis) — so the information exists at the point of use and
   is simply not published to the yield-kind inference. That is a much smaller
   change than the refusal route and it is strictly better: it makes item 1
   CORRECT (`0 1.5 1 2.5`) instead of refused, and it is the same fix as item
   3's "the outer loop's target is typed `MojoList *` but never inherits the
   iterable's NESTED element ctype".
2. **Item 2 then needs no refusal at all.** Its doc says "either the loop
   target's type has to become an input to the value-slot choice, or a
   generator whose value slot and loop target provably disagree has to be
   refused. The refusal is the smaller change and is the honest direction" —
   but that reasoning was written while only one pass could refuse, and (1)
   makes the first option available: a dict-typed parameter's loop target is
   `char *` from `mojo_dict_iter_key`, so the value slot follows from the
   target instead of being decided beside it. The remaining risk is a dict/list
   parameter whose target kind is NOT statically known (the same one-C-type-per-
   -slot limitation the doc already records for item 3), and THAT is where a
   refusal belongs — not here.

Nothing else in this doc is addressed: the heterogeneous-call-site limitation
and the loop-target-rebind refusal are both already-correct behaviour and stay
as they are.

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
`CODEGEN_nested_list_loop_target_loses_inner_elem_type`, and the same
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
