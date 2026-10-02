# A dict parameter that is only FORWARDED is declared `MojoList *`, so the forward hands the callee a list pointer as its dict

Found 2026-10-02 while fixing
`bugs/CODEGEN_unannotated_dict_param_value_type_not_propagated.md` (doc
deleted with that fix, same commit). NOT caused by it and not in its area: that
fix types the dict's VALUE type at the callee's read site, and this is about
the parameter's own C type at the DECLARATION — one layer up, and the fix
cannot see it.

## What I ran

`gimple_codegen.compile_to_gimple` + `gcc -fgimple` +
`runtime/fire_runtime.c`, against CPython on the same text.

```python
def leaf(d):
    print(d["x"])

def middle(d):
    return leaf(d)

def main():
    middle({"x": "1"})
```

| | output |
|---|---|
| CPython | `1` |
| compiled | `None` |

exit 0, no diagnostic.

## What I see

The generated signature:

```c
void middle_815e8f (MojoList * d)
```

`d` is declared a **list** pointer. `leaf` then receives it as its dict:

```c
  _t3 = mojo_dict_get_str (_t1, _t2);   /* _t1 came from a MojoList * */
```

`mojo_dict_get_str` reads a `DictSlot` out of a `MojoList`'s header, finds
nothing, and hands back NULL — which the printer renders as `None`, not as an
address, so this one at least fails loudly enough to be recognisable.

Pre-fix tree, same program: a decimal address. So the dict-value contract fix
turned an address into `None`; both are wrong and the cause is upstream of
both.

## The mechanism, and why the shape matters

`middle`'s body contains NO use of `d` other than the forward, so every
use-based inference has nothing to say about it. `_infer_param_types` then
falls to its name-based container guess, and — the same class of defect
`bugs/hard/CODEGEN_param_used_only_as_method_receiver.md` was filed for and
fixed on the METHOD-RECEIVER direction — it guessed the wrong KIND:
`MojoList *` for a name it has no evidence about.

Two things make this worth a doc rather than a shrug:

1. **It is order-dependent, which is why it is easy to miss.** With
   `middle` defined BEFORE `leaf`, the same program prints `1` — correctly,
   and for no reason anyone designed. `_caller_bodies` is walked in source
   order and `middle`'s guessed parameter type is refined by whatever was
   known at the moment its own inference ran. A regression test written in one
   order passes and the other order fails.
2. **It is a hard wrong-pointer coercion, not a missing type.** `MojoList *`
   where `MojoDict *` is meant survives the C compiler silently; the callee
   reads whatever is at that offset.

## Adjacent, and NOT the same bug

- `def middle(d): leaf(d)` (forward as a statement, no `return`) fails the
  same way. So it is not return-type inference — it is the parameter's own
  type.
- A two-hop chain (`mid1` -> `mid2` -> `leaf`) prints `0`, not `None`.
- `bugs4-5` holds `bug:CODEGEN_string_arg_type_lost_across_forwarding_hop`
  and `bugs4-10` holds `bug:CODEGEN_param_used_only_as_method_receiver`; both
  are the same family (a parameter with no local use gets a name-based guess)
  on the SCALAR and METHOD-RECEIVER axes. This is the CONTAINER axis, and it
  is unclaimed.

## Exact next step

The container-kind answer for a parameter whose only use is to be forwarded to
a callee whose corresponding parameter's kind IS known. `_container_param_kinds`
(`mojo/backend_gimple/emit_infra.py`, already keyed by `current_func_name` for
the same reason) is the table that carries the conclusion per function, and
the forward is an ordinary call the existing `_calls_in_stmts` walk already
sees — so the evidence exists at the same place the scalar and struct-pointer
observers read it in `module_gen.py`'s Pass-1.3d, and this is a third observer
there rather than a new pass.

The bar for landing it: a test that pins BOTH definition orders, since the
current one-sided behaviour is exactly what makes the bug survivable.