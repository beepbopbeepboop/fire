# FORMAL_a_var_self_receiver_on_a_one_field_struct_drops_its_store

**Area:** FORMAL, both backends — `formal/model.py`'s
`MUTATING_RECEIVER_CONVENTIONS` and `receiver_writeback_name`, and the parser's
folding of a `var self` receiver into the `owned` convention.
**Status: the plain-`self` spelling is FIXED (it is refused now, by
`model.one_field_dropped_receiver_stores`); the `var self` spelling is refused
by the same rule, and whether it SHOULD be is the open question here.**

Found 2026-10-03 on `work/formal14-fuzz-arm64` by `tools/formal_fuzz.py`, whose
one-field class generator (`self.a = self.a + k` through a plain `self`) finds
this family. The fix for the plain spelling is in `formal/build.py`,
`formal/model.py` and four rows of `test_formal_run.py`; this doc is about the
one corpus site the same fix newly refuses, and about why that site is a question
about the language rather than a defect to paper over.

## The measurement

Over **373 `.mojo` files** (this repository and the stdlib, the same scope
`tools/formal_receiver_rebind_census.py` uses), with
`model.one_field_dropped_receiver_stores` as the recogniser rather than a second
reading of it:

| | methods | files |
|---|---|---|
| a one-field struct's method that stores its own field | **110** | 50 |
| …with a receiver in `MUTATING_RECEIVER_CONVENTIONS` (`out`/`inout`/`mut`) | **109** | 50 |
| …with any other convention | **1** | 1 |

So the corpus convention is already the right one: 109 of 110 write the receiver
convention that makes `receiver_writeback_name` hand the receiver back. The one
that does not is:

```
std/python/python_object.mojo:1411
    def steal_data(var self) -> PyObjectPtr:
        var ptr = self._obj_ptr
        self._obj_ptr = {}
        return ptr
```

`PythonObject` is a one-field struct, `var self` is the receiver, and the body
stores `self._obj_ptr`. Before the fix that built, ran and dropped the store; the
caller's object kept the old pointer. After the fix it is refused by name.

**The coverage cost is zero**, and not by luck: `python_object.mojo` is
`not-answerable/host-import` in the sweep (it imports `cpython`, which has no
Mojo source for this backend), so it was never a pass.

## Why it is a question and not a one-line fix

`var self` and `owned self` both reach `fn.param_convs` as the string **`owned`**:

| source spelling | `param_convs['self']` | in `MUTATING_RECEIVER_CONVENTIONS`? |
|---|---|---|
| `self` | *(absent)* | no |
| `mut self` | `mut` | yes |
| `inout self` | `mut` | yes — the parser folds `inout` into `mut` |
| `out self` | `out` | yes |
| `var self` | `owned` | **no** |
| `borrowed self` / `read self` | `read` | no |
| `ref self` | `ref` | no |

Two things fall out of that table, and they are separate findings:

1. **`"inout"` in `MUTATING_RECEIVER_CONVENTIONS` is dead.** The parser folds
   `inout self` to `mut`, so no `FunctionDef` ever carries the string `inout` in
   `param_convs` and that tuple entry can never match. It is harmless and it is
   also a lie about the parser's vocabulary — the kind of thing that makes a
   future reader add `"inout"` a second time somewhere else.
2. **Whether `owned` belongs in the list is a question about the LANGUAGE.** 195
   of the 196 methods with a non-mutating receiver convention are readers
   (`__iter__`, `__getitem__`, `ref self`, `unsafe_ptr`), where `owned`/`ref`/
   `read` is exactly right and adding `owned` to the list would be harmless. One
   is a writer, and it is the one above. In Mojo's argument model `inout` is the
   convention that says "this method may change the object its receiver names",
   and `owned` says the method takes ownership of it — a different promise, which
   may or may not imply mutation. This path has no representation for ownership
   transfer either way, so guessing would be worse than asking.

## The next step

One of two changes, and the decision between them is the language's, not the
backend's:

* **`owned` joins `MUTATING_RECEIVER_CONVENTIONS`** (and `"inout"` comes out, and
  `var self`/`owned self` should stop being folded together if they are not the
  same convention). Then `steal_data` builds and its store reaches the caller, and
  the refusal stops firing on it. Cost: every `owned self` method becomes a
  write-back candidate, which for a one-field struct means the method returns the
  receiver — so the 195 readers would have to be re-checked for whether they
  already return something (`mutating_receiver_return_refusal` would start
  firing on them). **Measure that before doing it**: it is a bigger change than it
  looks, and the census to measure it with is the one above.
* **Leave the list alone** and treat `owned self` as "not a mutating receiver",
  which is what the refusal now says. Then `python_object.mojo`'s
  `steal_data(var self)` should be written `steal_data(mut self)`, and the
  refusal's message is the whole of the change needed — which is why it names the
  convention it read rather than only saying "not handed back".

Either way the parser's `inout` → `mut` folding should be recorded on the tuple,
so the next reader is not misled about which strings can reach it.

## Reproducing

```console
$ python3 tools/memslot.py --gb 8 --label probe -- \
      python3 fire.py build --formal --no-prove -o .tmp/x .tmp/probe/var_self.mojo
build: PythonObject.steal_data() stores `_obj_ptr`, the one field its receiver
IS, and `var self` is not a receiver this path hands back, so the store cannot
reach the caller: …
$ python3 tools/formal_receiver_rebind_census.py     # the 51-site census beside it
$ python3 test_formal_run.py refuse_a_one_field_store_through_a_plain_receiver \
      refuse_a_one_field_augmented_store_through_a_plain_receiver \
      both_arch_two_field_store_through_a_plain_receiver_still_reaches_it \
      both_arch_one_field_init_stores_its_parameter_through_a_plain_receiver
```