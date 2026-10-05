# A dict READ never carries the slot's kind, so `d['k']` cannot say `None`, `True` or `1.5`

## Status 2026-10-04 (`work/bugs7-1`): the RENDER half is fixed, the READ half is not

Landed, and each item says which half of this doc it was:

* **`mojo_repr_slot_kind` is now the ONE renderer for "a slot of kind K holding
  this word".** There were three copies of the answer —
  `mojo_repr_list_kinds`'s own six-arm switch, the generated `_mojo_repr_dict`
  value chain, and the generated `_mojo_repr_pair` walker — and they had
  already drifted: `print({'mid': 0})` printed `0` (the dict chain's `val == 0`
  arm) while `sorted({'mid': 0}.items())` printed `[('mid', None)]` (the pair
  chain, which had no such arm). All three are now calls, so the next value kind
  is one arm in one function.
* **`mojo_dict_items` / `mojo_dict_items_int` record a per-slot kinds row on
  each pair they build**, off `_DictSlot.kind`, which is the bargain
  `mojo_list_set_kinds` and `MojoDict.val_repr` already make: a pair slot is a
  raw `int64_t`, so the value's kind is unrecoverable from the word. This closed
  a narrower doc that measured only this same defect through
  `sorted({'mid': 0}.items())`, and removed a SIGSEGV:
  `print(d.items())` on a dict holding a float handed 1.5's IEEE-754 bits to the
  runtime type-tag reader, which dereferences them.
* **`emit_dict_int_value_store` grew the `char *` setter arm** and the three
  sites that hand-rolled it stopped doing so. It used to be documented as "the
  one dict store of a NON-STRING VALUE", so a `d[k] = 'str'` reaching a dict
  through an OPAQUE int-typed receiver (a container global reads back as the
  boxed `int64_t`) had no arm at all and stored the pointer with `kind == 0`.
  `'%(s)s' % d` then printed the pointer decimal where CPython prints the string
  — and `print(d)` hid it, because a `kind == 0` word above 65536 goes to the
  generic reader, which renders a pointer-shaped word as a string.

**Still open, and it is the doc's own subject.** `d['k']` and
`read({'x': True})` still return the bare `int64_t` word: `d['n']` gives `0`
where CPython says `None`, `d['b']` gives `1` where CPython says `True`, and
`d['f']` gives `4609434218613702656`. Nothing below has changed. Two measured
confirmations that the fix above did not leak into the read side:

* `for k, v in sorted(d.items()): print(k, v)` over a HETEROGENEOUS dict reads
  every value with ONE accessor (`_dict_items_val_elems`, one value type per
  dict), so a container prints as a pointer decimal and a float as its bits. The
  kinds row fixes what a pair PRINTS with, not what a subscript loop READS with.
* `'%(f)s' % d` is right, because the keyed formatter already switched on
  `kind` (`_fmt_dict_val_str`) — which is why the `'%(s)s'` case above was a
  STORE-side gap rather than a read-side one, and why the two have to be
  diagnosed separately.

This doc also used to name a narrower twin of itself — the same defect
measured only as a `.items()` pair whose value was the integer 0 — which is
deleted with the fix above, because it was this bug at a narrower width.

Pinned on the render half by `test_gimple_runner.py`'s
`gimple_dict_items_pairs_keep_the_slot_kind` and
`test_runtime_diff.py`'s `dict_items_reads_each_slot_kind`; the read half has no
test, deliberately, because a test asserting `0` for `d['n']` is a bug waiting
to be written as a fix.

---

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