# CODEGEN: one function's return ELEMENT type is inferred once for the whole
# program, and every other call site of it inherits that one answer

Found 2026-10-01 while fixing `bugs/CODEGEN_list_of_pairs_iterated_as_dict.md`.
It is the reason `bugs/CODEGEN_list_element_read_defaults_to_str_across_a_call.md`
cannot be closed with a two-line fixture: a fixture that exercises both the
fixed shape and a second container shape at the same call site is itself this
bug. Not mine — filed here with the measurement, because a reader of the two
docs above will otherwise "simplify" a fixture into it.

## Status: OPEN, pre-existing, NOT introduced or worsened by any of the
## 2026-10-01 kinds work. A/B-verified on this tree.**

## What it does

```python
def ident(x):
    return x
def main():
    print(list(ident([1, 2, 3])))
    print(list(ident("abc")))
main()
```

CPython: `[1, 2, 3]` then `['a', 'b', 'c']`.
Compiled (both pipelines, exit 0):

```
['\x18', '\x1a', '\ufffd', '\x02', '\x01']
```

Five elements read out of a three-element list. `ident`'s return ELEMENT type
is one program-wide answer, the string call site's `char *` wins, and every
int-list call site then reads its slots with `mojo_list_get_str` — on a list
whose slots hold small integers, which `strlen` walks off the end of.

The same unification with `','.join` instead of `list` stops compiling:

```
error: passing argument 1 of 'mojo_list_get_str' makes pointer from integer
       without a cast
```

The shapes that make it visible, all measured on this tree:

| one function, two call sites | compiled |
|---|---|
| `list(ident([1,2,3]))` + `list(ident("abc"))` | five garbage "elements" from a 3-element list |
| `list(ident([1,2,3]))` + `",".join(ident(["a","b"]))` | gcc `-Wint-conversion` error |
| `sum(ident([1,2,3]))` + `",".join(ident(["a","b"]))` | correct (nothing reads a slot wrongly) |
| `",".join(ident(["a","b"]))` alone | correct |

So the damage needs a second call site whose element type differs AND a reader
that consults the inferred element type.

## What was run

```
python3 .tmp/probe2.py <fixture>       # compile_to_gimple, do_imports=True and
                                       # link_mode=True, gcc -fgimple + fire_runtime.c,
                                       # stdout+exit diffed against CPython
```

A/B against the tree with the whole 2026-10-01 kinds change reverted:
`list(ident([1,2,3]))` + `",".join(ident(["a","b"]))` MATCHES without it and
FAILS to compile with it — i.e. the unified element type was previously
*masked* on that path by `list()` re-lowering its argument inside
`_lower_comprehension`, which carries the element-type record onto a fresh
temp. It is exposed, not introduced; the exposure is fixed at the call site
(`_lower_ctor_from_iterable`'s docstring in `mojo/backend_gimple/emit_calls.py`
records why that path hands a resolved `MojoList *` back to the comprehension
instead of substituting the boxed name).

## Next step

The return element type has to be a property of the CALL, not of the callee.
`_return_elem_types` (`gen._return_elem_types`, filled by
`_infer_return_elem_type` in Pass 2c) is keyed by callee name and is consulted
at the call site — so the call site has a per-callee answer available and is
choosing not to use it, or the answer it has is itself the join of every call
site's.

Two steps, in this order, and the first is a measurement:

1. Dump what `gen._return_elem_types['ident']` is for the fixture above. If it
   is `char *`, the pass already joins across call sites and the fix is to make
   it a per-(callee, argument) answer, keyed by argument position, with the
   callee's own body as the fallback for a call site that supplies no
   evidence. If it is `int64_t` and the *call site* is overriding it with
   `_elem_types[t]`, the fix is to stop that override.
2. Whatever the answer, `_elem_types` must not be a property of the callee: it
   is keyed by a lowered NAME, and two call sites of one function produce two
   names, so only the pass that unions them is putting one value under both.
   `gimple_codegen.py`'s `_actual_types` has the same shape and the same
   hazard; check both in the same pass.

A regression row belongs in `test_gimple.py` beside
`test_a_returned_heterogeneous_list_keeps_its_slot_kinds`, because that is the
row whose docstring already says why its own fixture cannot carry a second
container shape.