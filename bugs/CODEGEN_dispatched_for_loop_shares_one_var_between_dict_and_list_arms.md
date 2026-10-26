# CODEGEN: the dict/list runtime dispatch in `_gen_for_iter` shares ONE C variable between two arms, so the dict arm's `char *` wins a list-of-ints loop and `print(i)` SIGSEGVs

## Status (2026-10-02 — measured, root-caused to three lines, NOT fixed: the fix has to choose a representation and that is not this doc's author's call alone)

Found while re-measuring `bugs/PARTIAL_WORK_HANDOFF.md` §2.1, whose own claim
("`len`/`[i]` work and `for x in b.items` segfaults") is still exactly true and
whose recorded cause is only half of it.

## The repro, both spellings

```python
class Reader:
    def __init__(self, items):
        self.items = items          # <- field ends up int64_t, see "Why"

class Owner:
    def __init__(self, items):
        self._items = items

    def read(self):
        return Reader(self._items).items

def main():
    o = Owner([10, 20])
    for i in o.read():
        print(i)
main()
```

and the same thing through a local (`r = Reader(o._items); for i in r.items:
print(i)`), which is `PARTIAL_WORK_HANDOFF.md` §2.1's own `Reader(self._items)`
shape. Identical verdict for both:

| | CPython 3.14.7 | compiled (`compile_to_gimple` + `gcc -fgimple` + run) |
|---|---|---|
| `print(r.items[0])` | `10` | `10` — correct |
| `for i in r.items: print(i)` | `10` / `20` | nothing, **SIGSEGV (exit -11)**, reproduced with `MallocScribble=1` |

Subscripting the field is right; iterating it crashes. That asymmetry is the
whole clue.

## What the generated C does

`Reader.items` is declared `int64_t` while `Owner._items` is `MojoList *`:

```c
typedef struct Owner  { MojoList * _items; } Owner;
typedef struct Reader { int64_t items;    } Reader;
```

so `for i in r.items` cannot take the static list path and goes through
`_gen_for_iter`'s dual runtime dispatch (`emit_loops.py:1066`):

```c
  _t13 = r->items;
  _t14 = mojo_is_registered_dict (_t13);   /* false at run time */
  ...
bb_4:                                          /* the LIST arm */
  _t24 = (MojoList *) _t13;
  _t26 = mojo_list_len (_t24);
bb_13:
  _t30 = mojo_list_get_int (_t24, _t28);
  i = (char *) _t31;          <-- THE CRASH: the loop target is a char *
  mojo_print (i);             <-- mojo_print((char *)10)
```

`mojo_print` on the integer 10 read as a string is the segfault, and it is not
a bad guess made in the loop body: `i`'s C type was fixed BEFORE the body ran.

## Why: one variable, two arms, two element types

`_gen_for_iter`'s dispatch arm calls `_gen_for_dict(var, dp, ...)` and
`_gen_for_list(var, lp, ..., share_var_with_sibling_arm=True)`. The list arm
passes `share_var_with_sibling_arm=True` on purpose (the comment above
`_fl_retype` explains why: both arms must declare the *identical* C variable,
because only one arm ever executes and renaming the list arm's copy would leave
the already-lowered body reading the original bare name — measured, and it
produces a hard `-fgimple` type error). So the DICT arm's element type wins the
shared declaration, and a dict KEY is a `char *`. `_fl_ctype = _as_str(elem) if
elem is not None else elem` leaves the type unset when the element type is
unknown, and `_declare_var`'s default then keeps whatever the dict arm wrote.

So neither default is right for both arms, which is why this is not a one-line
fix:

* `char *` (today) is right for a string-keyed dict, and **crashes** on a list
  of ints or doubles, and prints a pointer decimal for a list of strings that
  arrived without an element type.
* `int64_t` would be right for a list of ints and for an int-keyed dict, and
  would print a pointer decimal for a string-keyed dict — a silent wrong value
  where today there is a correct one, i.e. a regression traded for the crash.

The runtime already has the answer the codegen is missing: `mojo_list_get_kinds`
is what `_mojo_repr_list` asks to describe a value it cannot type statically
(see that function's own comment), so a dispatch arm CAN ask the value what its
elements are and declare the shared variable from THAT — one registration per
loop body, before the arms, instead of a guess from whichever arm is lowered
first. That is the change worth making, and it is in `emit_loops.py` plus the
element-type bookkeeping, which is another claim's write set.

## Why the field is `int64_t` at all (the upstream half, still open)

`self.items = items` with an unannotated `__init__` parameter. The field's C
type comes from `param_types.get('items')` in
`mojo/middle/module_shared.py`'s field pre-pass, which has no call-site evidence
to consult, so it defaults to `int64_t`; and the element type is never threaded
at all (`_field_elem_types['Reader']` is empty). This is `PARTIAL_WORK_HANDOFF`
§2.1's residue, re-measured today and still true — see that doc's updated entry.
Fixing the field type removes THIS repro (the loop would take the static list
path) without fixing the dispatch arm, which is why both are named here: the
first is an inference gap and the second is a codegen gap, and either one alone
leaves a SIGSEGV reachable.

## Also measured, because it is the same bug and it is NOT the same repro

* `Box(x)` where `x` is a local bound to a list literal: **correct** now
  (`1 2 3` on both paths), so `PARTIAL_WORK_HANDOFF` §2.1's "still leaves the
  field `int64_t`" is stale for the literal route.
* `self.<field>` / local-field route: still loses the element type, as above.

## Not attempted, and why

The two candidate resolutions each have a measured downside (a regression for
the other arm), and the third (asking the runtime) touches the element-type
bookkeeping in `mojo/backend_gimple/emit_loops.py` and the runtime helper
contract — both in other claims' write sets, mid-merge. A wrong choice here is a
silent wrong value in a stdlib module, which is the outcome this tree keeps
paying for.