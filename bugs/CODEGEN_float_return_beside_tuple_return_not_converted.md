# CODEGEN: a function returning a float on one path and a tuple on another fails `gcc -fgimple` ("cannot convert to a pointer type"), which breaks the self-host build

Status: OPEN. Filed 2026-11-12 from a failing `make` of `fire.o`. Class: easy (one narrow codegen case, a small standalone repro below).

## Symptom

Building the self-hosted compiler stops at `fire.o`:

```
python3 fire.py fire.py --dump-full          # ✓ Generated fire.ci
sed -i '' 's/^int main/int mojo_main/' fire.ci
gcc-mp-15 -Os -g -fgimple -ftrivial-auto-var-init=zero -I runtime -c -x c fire.ci -o fire.o
mojo/middle/comptime.py: In function 'mojo_middle_comptime_eval_const_3837fb':
mojo/middle/comptime.py:470:3: error: cannot convert to a pointer type
  470 |     if isinstance(node, FloatLiteral): return node.value
make: *** [fire.o] Error 1
```

`fire.ci` is generated without complaint; it is the C compiler that rejects it. So the self-hosted binary (stage1 and everything after it: `make bootstrap`, `mojoc`) cannot be built from current master.

## Cause of the regression (known)

Line 470 of `mojo/middle/comptime.py` was added on 2026-11-12 by `13b16397d` ("decide float comparisons in comptime conditions"): `eval_const` gained `if isinstance(node, FloatLiteral): return node.value`. That function already returns booleans, ints, strings, `('.', name)` tuples, built tuples, built lists and `None`. The new branch is the first one that returns a `float` beside the pointer-valued (tuple/list) returns.

## Minimal repro (no compiler closure needed)

`mixed_ret.py`:

```python
from dataclasses import dataclass

@dataclass
class FloatLit:
    value: float

@dataclass
class TupleE:
    elements: list

def eval_const(node):
    if isinstance(node, FloatLit): return node.value
    if isinstance(node, TupleE):
        res = []
        for e in node.elements:
            res.append(eval_const(e))
        return tuple(res)
    return None

def main():
    print(eval_const(FloatLit(1.5)))
```

```
python3 fire.py mixed_ret.py --dump-full
gcc-mp-15 -Og -fgimple -I runtime -c -x c mixed_ret.ci -o mixed_ret.o
# mixed_ret.py:12:3: error: cannot convert to a pointer type
#    12 |     if isinstance(node, FloatLit): return node.value
```

Measured 2026-11-12 on master, same compiler, one variable changed per row (return branches of `eval_const`):

| returns | `gcc -fgimple` |
|---|---|
| float, str, None | OK |
| bool, int, float, str, None | OK |
| int, float, None | OK |
| **float, tuple, None** | **FAIL: cannot convert to a pointer type** |
| **float, str, tuple, None** | **FAIL: cannot convert to a pointer type** |

So the failing ingredient is a `tuple` (a pointer-valued) return beside a `float` return. Scalars beside each other, and a float beside a string, are handled.

## What is not yet known

- Which representation the function's return slot gets in the failing case. The error says the float branch is being converted *to a pointer type*, which suggests the return type was inferred as a pointer (from the tuple branch) and the `double` is returned without being boxed into it. Look at how `int` and `bool` returns beside a tuple are boxed and why `float` is not (the `int+float+None` row passes, so the scalar case is fine; the tuple case is the one to read in the generated `fire.ci`).
- Whether a `list` return behaves like a `tuple` (the real `eval_const` returns both).

## Scope and rule

Fix the codegen, not the call site: a function that returns a float on one path and a tuple on another is ordinary Python and must compile. Do not paper over it by rewriting `eval_const` (CLAUDE.md: no quick fix; consolidate, do not work around). If the proper fix is large, land the part that makes this repro compile and say what remains.

## Acceptance

- `mixed_ret.py` above compiles through `fire.py --dump-full` and `gcc -fgimple -c` with no error, and `eval_const(FloatLit(1.5))` prints `1.5` when run.
- The other rows of the table still compile.
- A regression test, `test_float_return_beside_tuple_return.py`, runs that repro (compile and run, compare with CPython's output) and passes.

## Done when

`python3 test_float_return_beside_tuple_return.py` passes. Then, as the integrator's concern and not a worker's: the `fire.o` step of the self-host build (the command in the Symptom section) gets past `mojo/middle/comptime.py`. A worker does not run the whole-closure build; report that step as not run.
