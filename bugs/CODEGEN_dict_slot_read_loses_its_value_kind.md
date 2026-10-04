# A dict READ never carries the slot's kind, so `d['k']` cannot say `None`, `True` or `1.5`

Found 2026-10-02 while fixing the dict store path (the six
`emit_dict_int_value_store` call sites and the value-kind arms of the
generated `_mojo_repr_dict`). **Not a key bug, and not a store bug**: the
store now tags every slot correctly (kind 0 int, 1 double, 2 `char *`,
3 bool, 4 `None`), and the dict's own repr reads those tags. The READ side is
what throws the tag away.

## What I ran

`gimple_codegen.compile_to_gimple` + `gcc -fgimple` +
`runtime/fire_runtime.c` through `test_gimple_runner.py`'s own
`compile_mojo_to_gimple_exe`, against CPython on the same text:

```python
d = {}
d['n'] = None
d['z'] = 0
d['b'] = False
d['f'] = 1.5
print(d)
print(d['n'], d['z'], d['b'], d['f'])
```

## What I saw

```
CPython  : {'n': None, 'z': 0, 'b': False, 'f': 1.5}
           None 0 False 1.5
compiled : {'n': None, 'z': 0, 'b': False, 'f': 1.5}      <- the repr is right
           0 0 0 0                                        <- every read is int64_t
```

Exit 0, no diagnostic, and the two halves of one program disagree with each
other: `print(d)` says `None` and `print(d['n'])` says `0`.

## It reaches a dict PARAMETER too, and the two halves of that are already separated

Measured on the same tree, through the same harness:

```
def read(d):
    return d['x']

print(read({'x': 'a'}))     -> 'a'      both agree
print(read({'x': 1.5}))     -> '1.5'    both agree
print(read({'x': True}))    -> True     compiled: 1
print(read({'x': 2})); print(read({'x': 'a'}))   # two DISAGREEING call sites
                              -> 'a' is CPython's answer, compiled prints a pointer decimal
```

So the cross-call dict-value contract (`_param_dict_val_types`, added
2026-10-02) does its documented job: a unanimous `char *` or `double` at the
call sites types the parameter and the read picks `mojo_dict_get_str` /
`mojo_dict_get_double`. Two shapes are left, and neither is that contract's
fault:

* a `bool` value, which is the slot-kind gap this doc is about (the codegen
  knows the value is a bool at the call site — `is_python_bool_expr` says so —
  and the store tags it, and then the READ throws the tag away);
* DISAGREEING call sites, where the documented answer is "unknown" and the
  consequence is exactly the same read-side gap: the slot's kind is on the
  slot and nothing asks for it.

Both are fixed by the accessor this doc's "Exact next step" describes. Worth
saying plainly, because it bounds the work: the store side already tags every
value kind correctly, and nothing above it consumes the tag.

## The mechanism

`_lower_subscript`'s `ot == 'MojoDict *'` arm
(`mojo/backend_gimple/emit_calls.py`) picks its accessor from
`gen._dict_val_of(ov)` — the codegen's record of what the dict's values are,
which is the same "one type for the whole dict" assumption every
value-type consumer here makes. When the codegen does not know, it emits
`mojo_dict_get_int`, and the runtime's `mojo_dict_get_int` is

```c
int64_t mojo_dict_get_int(MojoDict *d, char *key)
{
    _DictSlot *sl = _dict_lookup(d, key);
    return sl ? sl->val : 0;
}
```

— it returns `val` and never looks at `sl->kind`. So the tag exists, is
written by the store, is read by the repr, and is invisible to the one
consumer that hands the value to a program.

That is why this is only visible for values whose tag is not also their
representation: a bool is 0/1 (so `d['b']` gives `1` where CPython says
`True`), a `None` is 0 (so `d['n']` gives `0`), and a float's bits are an
`int64_t` that is not the float (so `d['f']` gives `4609434218613702656`).
An int or a `char *` value happens to survive, which is why this sat
unnoticed next to the bugs the store side already had.

`d.get(k)`, `d.pop(k)`, `d.values()`, `k in d.values()` and the
`%(k)s`-style formatting have the same shape (`_fmt_dict_val_str` DOES
switch on `kind`, which is why `'%s' % d` is right and `d['n']` is not).
`for v in d.values(): print(v)` goes through `mojo_dict_values` ->
`mojo_list_get_int`, so it has the same gap one level out.

## Exact next step

A kind-aware accessor pair in the runtime, beside `mojo_dict_get_int`:

```c
char *mojo_dict_repr_slot(MojoDict *d, char *key);   /* the slot's value repr */
int64_t mojo_dict_slot_kind(MojoDict *d, char *key); /* 0..4, or -1 if absent */
```

`mojo_dict_repr_slot` is a switch on `kind` with the same arms
`_mojo_repr_dict` uses (`mojo_repr_str` for 2, `mojo_repr_float(
mojo_double_from_bits(v))` for 1, `"True"/"False"` for 3, `"None"` for 4,
`mojo_str_from_int` for 0) — and `_mojo_repr_dict`'s value arm should call
it, so there is ONE implementation of "what a dict slot looks like" rather
than the walker and the accessor each having their own.

The codegen half is the part with a decision in it, and the project has
already solved the analogous problem for lists: `mojo_list_set_elem_repr` /
`mojo_list_repr_elem` record a repr FUNCTION on the value itself where the
element's type is known and unrecoverable later. A dict's equivalent is to
record, on the temp that `d[k]` produced, the `(dict, key)` pair it came
from, and have `_repr_value` / `_stringify_value` — the two chokepoints the
bool fix already had to touch — ask `mojo_dict_repr_slot` for a value with
no better static type. That keeps `print(d['n'])` right without teaching
every consumer a new branch, and it is the same bargain as the list one:
known where the read happens, unrecoverable afterwards.

Two things to decide before attempting it, both measured here:

1. **A temp is not a slot.** The same `int64_t` temp can be assigned from
   several reads (`x = d['a'] if c else d['b']`), so the record has to be
   cleared when a temp is re-assigned, or the repr will ask about the wrong
   key. `_actual_types` (the same shape of map) is the precedent for where
   that invalidation lives.
2. **A MISSING key must still print nothing useful rather than something
   wrong.** `d['absent']` is 0 today and CPython raises `KeyError`; the
   new accessor has to decide whether to keep answering 0 (a divergence
   that predates this doc) or refuse, and either answer is a behaviour
   change that wants its own evidence.

## Blast radius

Every read of a dict value whose C representation differs from its Python
one: `None`, `bool`, and `float` — three of the five value kinds, and the
three that a dict of parsed JSON or config data is mostly made of. Silent:
exit 0, a plausible integer, and a program that prints `0` where it means
"absent".