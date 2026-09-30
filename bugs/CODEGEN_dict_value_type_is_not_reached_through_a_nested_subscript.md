# CODEGEN: a dict's known value type is not reached through a NESTED subscript, so `d[k][j]` reads a pointer's bits as a double

**Area:** CODEGEN / return-type and expression typing — `mojo/middle/resolve_shared.py`
(`_quick_type`'s `SubscriptExpr` arm), with `mojo/middle/infra_infer.py`'s
`_dict_value_locals` as the table it fails to reach.

**Found while:** merging `master` into
`work/fix-merge-fix-merge-fix-merge-fix-merge-formal-cross-module`
(the `construct:cross-module-link` claim), 2026-09-30 — while consolidating
the two hand-copied body walkers that merge left forty lines apart. Not a
regression from that merge; the gap is at the merge base.

**Status: OPEN, cause located, not fixed.** Filed rather than fixed because the
`_quick_type` arm is shared with the self-hosted compiled path and the fix
needs the `elifs`/element-type evidence question answered once, deliberately,
rather than guessed at inside a merge.

## What I ran

```console
$ python3 .tmp/gp_sub2.py            # each under tools/memslot.py --gb 8
FAIL dict of lists, subscript the list: got='4612811918334230528'  want='2.5'
PASS dict of lists, subscript the DICT (works today): got='2'       want='2'
FAIL nested dict, subscript twice:      got='4347714304'           want='v'
```

Both failing cases are four-line functions; CPython on the same text gives
`2.5` and `v`. `4612811918334230528` and `4347714304` are the low 32 bits of
the `char *` that was really there, read as a `double` and as an `int64_t`.

## The two shapes

```python
def f():
    d = {}
    d["k"] = [1.5, 2.5]
    return d["k"][1]        # 4612811918334230528   -- CPython: 2.5

def g():
    d = {}
    d["k"] = "vv"
    return d["k"][0]        # 4347714304            -- CPython: v
```

The first line of each is exactly what `_dict_value_locals`
(`mojo/middle/infra_infer.py`) was written to see: it records
`{'d': 'MojoList *'}` / `{'d': 'char *'}` and overlays it on
`gen._dict_val_types` inside `_infer_return_type_with_locals`'s save/restore
window. **The evidence is found and put in the table.** Nothing reads it,
because the expression that needs it is not shaped like the one the reader
recognises.

## Cause

`mojo/middle/resolve_shared.py`, `_quick_type`'s dict-subscript arm:

```python
if (isinstance(node, gimple_ctypes.SubscriptExpr)
        and isinstance(node.obj, gimple_ctypes.IdentExpr)):
    _dvt = (getattr(gen, '_dict_val_types', None) or {}).get(node.obj.name)
    if _dvt:
        return _as_str(_dvt)
```

`node.obj` must be an `IdentExpr`. In `d["k"][1]` the outer subscript's `obj`
is the inner `d["k"]` — itself a `SubscriptExpr` — so the guard is false, the
arm is skipped, and the expression falls through to the `int64_t` default. The
container is laundered through a scalar slot, which is the precise failure the
arm directly above it was written to prevent for the one-level case.

Measured, not assumed — the table really is populated for the failing case:

```console
$ python3 .tmp/probe_sub.py       # prints what _dict_value_locals returns
DICT_VALUE_LOCALS -> {'d': 'MojoList *'}      (x4, one per inference pass)
```

and the emitted signature is `int64_t build (void)` where the answer is
`double`.

## Why the fix is not one line

The arm's own comment rules out the tempting shortcut, and the rule is right:

> A LIST subscript is deliberately not handled: `lst[i]`'s element type is a
> different table with different evidence, and guessing would launder a
> container through a scalar slot.

So `d["k"][1]` needs `d`'s value type (`MojoList *`, known) AND that list's
ELEMENT type (`double`, known only from the literal that was stored). The
element type lives in `_elem_types`, keyed by the lowered value rather than by
the dict's name, which is why the two tables cannot simply be chained at this
site. The honest fix records the element type of a dict's values alongside the
value type — i.e. `_dict_value_locals` grows a second output, and the nested
arm consults both — rather than teaching `_quick_type` to guess `double`
because the outer subscript's obj happened to be a subscript.

That is a real design change to a shared estimator, which is why it does not
belong in a merge commit.

## The exact next step

1. Give `_dict_value_locals` a second return value: the element type of the
   values it records (the same `gen._quick_type(n.value)` answer already
   computed, passed through `_infer_list_elem_type` when the value is a
   `ListExpr`). Overlay it in the same save/restore window the value type
   already uses, so the two cannot disagree about which `d` they describe.
2. Relax the guard to `isinstance(node.obj, gimple_ctypes.SubscriptExpr)` and
   answer from that pair. Keep the `IdentExpr` arm exactly as it is — it is
   correct and it is the one the existing tests pin.
3. Regression tests beside the existing ones in `test_gimple_runner.py`:
   both shapes above, each diffed against CPython on the same text, plus the
   `d["k"]` one-level case as the control that must not move.

Step 1 is where the judgement is; steps 2 and 3 follow from it. Note that
`bugs/hard/CODEGEN_cross_function_container_element_type.md` is the same
underlying family (a container's compile-time knowledge lost across a
boundary) and may already have opinions worth reusing.