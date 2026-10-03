# FORMAL_a_call_through_a_one_words_field_calls_the_receiver: `c.f(5)` on a ONE-FIELD struct is rewritten to `c(5)`

**Area:** FORMAL (`formal/build.py`'s `_rewrite_self_fields`, and the refusal
that now catches the result: `formal/model.py`'s `callee_value_refusal`).

**Status: OPEN, not fixed. The verdict is now right and the MESSAGE mis-spells
the source — which is the part that still sends a reader to the wrong line.**

Found 2026-10-03 on `work/formal12-backend-crash` while answering the sweep's
`not-answerable/unresolved-extern` rows, on both architectures.

## What I ran

```sh
$ cat .tmp/m/p4.mojo
struct Cb:
    var f: Int

def main(n: Int) -> Int:
    var c = Cb()
    var v = c.f(5)
    return v

$ python3 tools/memslot.py --gb 8 --label t -- \
    python3 fire.py build --formal --no-prove -o .tmp/m/p4 .tmp/m/p4.mojo
```

## What I saw

**Before** (pristine `git archive HEAD` into a scratch tree, `c5ab524d`):

```
build: p4.mojo: the image would bind 1 symbol(s) that nothing provides, so it
could not be loaded: c.
```

`f` is the ONLY field of `Cb`, and a one-field struct's receiver **is** its
field (`formal/model.py`'s `struct_fits_one_word`, and the whole claim of
`_rewrite_self_fields`). So the rewrite that keeps `self.f` and `self` the same
storage rewrites the CALLEE `c.f` to `c`, and the call becomes `c(5)` — a call
of the receiver. The emitter then did what it does with any name this unit does
not compile: a branch against a symbol spelled `c`, which nothing provides.

**After** (`404de02b`, which refuses a call whose callee is a name the calling
function binds):

```
build: `c` is a call through a VALUE rather than through a function of this
unit — `c` is a name main binds, a parameter or a local of it, and this path
has no representation for a function value.
```

## What I expect

`c.f(5)` in CPython is `TypeError: 'int' object is not callable`, so a refusal
is right. Two things are still wrong:

1. **the message names `c`, and the source says `c.f`.** The emitter passes
   `model.member_chain_text(e.func)` so a two-name spelling can be printed when
   `_callee_symbol` flattens a receiver-qualified callee — and for THIS shape
   `e.func` is already `IdentExpr('c')`, because the rewrite ran in
   `_prepare_functions`, before codegen. A refusal that names a name the reader
   did not write is the `bugs/FORMAL_known_limits.md` failure mode (a
   diagnostic that mis-describes the construct sends the next reader looking for
   the wrong thing), and here it costs a second build to discover that `f` is
   the field.
2. **the rewrite cannot tell a field read from a method call.** `c.f(5)` and
   `c.f` reach `_rewrite_self_fields` as the same node shape, and only one of
   them is a field read. A `c.g()` where `g` is a one-field struct's METHOD is
   lifted by the receiver-lift pass (`build.py`'s `n.func = lifted`) and is
   unaffected, which is why the two spellings disagree.

## The exact next step

Make the rewrite callee-aware, in one of two places:

* **`_rewrite_self_fields`' visitor** (smallest): skip a node that is the
  `func` of a `CallExpr`. `M.rewrite_tree` hands the visitor a node and no
  parent, so this needs the parent — either a pre-pass that records the callee
  node identities before the walk (a set of `id()`, the same shape
  `arm64_codegen`'s `_ret_frame_sites` already uses), or a `visit` that is
  given the parent.
* **the visitor's caller**, if it already walks statements: refuse the shape by
  name here, which is what the emitter's refusal now does one stage later and
  with a spelling the rewrite has already lost.

Either way the refusal belongs NEXT TO the rewrite rather than in the emitter:
the emitter cannot recover the spelling, and the rewrite is the thing that lost
it. A test belongs beside `_rewrite_self_fields`' own cases with the field/method
pair side by side (`c.f` builds, `c.f(5)` is refused naming `c.f`).

**Not measured, and it should be before the fix lands:** whether the rewrite
also eats a CALL RESULT (`c.f.g()`, `c.f(1).x`) — the same visitor, the same
blindness, and no measurement of it exists. `bound_names_in_order`'s walk and
this rewrite were compared for this reason in
`formal/build.py::_names_bound_in`'s docstring; that comparison says the walk
over-collects and this rewrite under-collects in opposite directions, so a
second opinion is worth having.

## Related, and already closed

`404de02b` — the same emitter line now refuses the general shape ("a callee
this function binds is a value, not a symbol"), which is what turned this from
`not-answerable/unresolved-extern` into a codegen finding at all.
`bugs/FORMAL_bare_receiver_with_an_ambiguous_method_name_is_refused.md` is the
neighbouring receiver-shape question and is not this one.