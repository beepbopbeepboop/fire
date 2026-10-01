# FORMAL_type_argument_read_as_a_container: a subscript's INDEX is not a container, and four stdlib files are refused for a store that never happens

**Status: not fixed, and not in this session's claim.** Filed 2026-09-30 while
fixing `origin_of` (map row 7); see
`bugs/FORMAL_frame_by_value_ceiling_zero.md` for the measurement that found it.
It is a REFUSAL, so nothing here builds and lies — the cost is four stdlib files
whose diagnosis is false, and one more step for whoever reads them.

## What is wrong

`formal/build.py`'s `_check_frame_escapes` has one branch for a frame address
inside a container literal:

```python
        elif isinstance(node, (F.ListExpr, F.TupleExpr, F.DictExpr)):
            for el in _container_values(node):
                _refuse_holder_use(fn, el, holders, by_name,
                                   "is stored in a container, which has no "
                                   "layout for a frame address")
```

and `model.iter_nodes` — the walker this and every other pass shares — yields a
node and then recurses into its fields. It does not yield the PARENT, so this
branch cannot tell two things apart that have the same node type:

* `x[0, 1]`, `[p, q]`, `{k: p}` — a runtime store, and refusing it is right;
* `Pointer[Deque[T], s]`, `UnsafePointer[_, s]` — a **type argument list**. A
  subscript over a type constructor's name is a type application, nothing is
  stored, and the frame address in it is not a store.

Both arrive as a `TupleExpr`, and both are refused with the same sentence, which
is false about the second.

## The reproducer, which has no `origin_of` in it

That is the part worth having: this is not an artefact of the `origin_of` work.

```python
# .tmp/p/tc2.mojo
struct S:
    a: Int
    b: Int

struct Box[T: AnyType, U: AnyType]:
    v: Int

def main(n: Int) -> Int:
    var s = S()
    s.a = 3
    s.b = 4
    var m = Box[Int, s]
    return m.v
```

```
$ python3 fire.py build --formal --no-prove -o tc2.out tc2.mojo
build: a S receiver is stored in a container, which has no layout for a frame
address on this path: the receiver of a multi-field struct is the ADDRESS of a
frame of 8-byte slots that belongs to the function which created it …
```

A trailing comma is not the discriminator — `Box[Int, s,]` (which the parser
turns into a `TupleExpr` index rather than a bare one) is refused identically.

## Why it is worth an hour

Four of the seven stdlib files that `origin_of`'s fix moved off map row 7 land
here, and they are the four largest of the stdlib's container-shaped structs:

| file | the subscript, as the source spells it |
|---|---|
| `std/builtin/tuple.mojo` | `UnsafePointer[_, origin_of(self)](_mlir_value=elt_kgen_ptr)[]` |
| `std/collections/deque.mojo` | `rebind[Pointer[Deque[downcast[Self.ElementType, …]], origin_of(self)]]` |
| `std/collections/linked_list.mojo` | the same, in `_build_iter` |
| `std/collections/set.mojo` | `rebind[Pointer[DictCopyable, origin_of(self)]](…)` |

Measured on current master with `origin_of` lowered, all four report
`a <X> receiver is stored in a container`. Before `origin_of` was lowered they
reported the `origin_of` sentence, which was false for a different reason. So
the honest reading of map row 7 after `14a2e42d` is: 7 files leave it, 4 of them
into this, and 0 reach `pass`.

## The exact next step

Two decisions, and the first is the one that has to be right.

**1. Is this subscript a type application or a container lookup?** Provable from
the base alone, and only for the names the model already classifies:

```python
def subscript_is_a_type_application(node, structs_by_name) -> bool:
    """`Foo[A, B]` is a TYPE application; `x[A, B]` is a lookup.

    Provable only for a base the model classifies: a type constructor
    (`type_constructor_kind` is not None — `Pointer`, `UnsafePointer`,
    `OpaquePointer`) or a struct this module declares. Anything else — an
    imported name, an unknown name, a local — is NOT decided, and the caller
    must fall through to today's behaviour, which is the refusal.
    """
```

`IteratorType[origin_of(self)]` is the case that cannot be decided this way: it
is a type application and `IteratorType` is a name this unit does not declare.
Deciding it needs the imported module's declarations, which is the cross-module
question `formal/imports.py` owns, so **it must not be guessed**. Leaving those
refused is the correct outcome for this change; a name that might be a local
dict is not a type application just because the index looks like types.

**2. Give the container branch the parents it needs.** `iter_nodes` is shared by
three passes that each need a different amount of context, so do not change it.
Collect the indexes to skip in a pre-pass over the same tree and key them by
`id`, which is what `model.struct_constructor_sites` already does for call
nodes:

```python
    type_index_ids = {
        id(node.index)
        for node in M.iter_nodes(fn.body)
        if isinstance(node, F.SubscriptExpr)
        and isinstance(node.index, (F.ListExpr, F.TupleExpr))
        and subscript_is_a_type_application(node, structs_by_name)
    }
    …
        elif isinstance(node, (F.ListExpr, F.TupleExpr, F.DictExpr)):
            if id(node) in type_index_ids:
                continue        # a type argument list, not a store
```

`_check_frame_escapes` (`formal/build.py:2830`) already takes
`structs_by_name` — it is the table the call half uses for `_names()` — and the
one caller passes the real one. So no signature change is needed, but the
decision still has to degrade to "not a type application" when the table is
absent or empty, which is what the dylib path passes and is the safe direction.

**The order matters and it is the same order as everywhere else in this file:**
the escape checks are raised from `_prepare_functions`, so this one pre-empts the
import diagnosis, and a narrowing of it is the safe direction precisely because
the wrong answer it used to give was a REFUSAL. There is no program that built
because of the branch being wider than it should be — so measure it by what
stops being refused, not by what starts.

## What to measure when it is done

The narrowing is on a check that is doing REAL work, and these are the shapes
that must keep being refused — each measured on current master, each refused by
the container branch, and each a genuine escape rather than a false positive:

| program | why the refusal is right |
|---|---|
| `d[s, 1] = 5` (a dict) | the frame address is part of the KEY, so it is parked in the dict's storage and outlives the frame |
| `var k = l[s, 1]` (a list) | the frame address is read as an INDEX; the word is compared against element values and answers from bytes it does not own |
| `d[0, 1] = s` (a dict) | already refused, and by a DIFFERENT branch — `_defer_subscript_escape` → `check_frame_subscript_escapes`, whose message names the spelling (`stored through 'd[0, 1]' in main()`). Worth knowing that the store case is covered twice and the index case once, because "narrow the container branch" must not be justified by the store case being safe to lose. |
| `s[0]` (a framed struct) | not this branch: `model`'s own message about a container reading of a frame address, and it is right there too much (offset 0 of a frame is the FIRST FIELD). |

And the one that must start building:

1. `Box[Int, s]` from the reproducer builds, and `m.v` reads slot 0 of the
   frame.
2. `IteratorType[origin_of(self)]`-shaped subscripts — a base this unit does
   NOT declare — must still be refused, and with a message that says the index
   is a type argument it could not place rather than one that says a store. That
   is the honest half of the limit: the decision is provable only for a base the
   model classifies, and the other half belongs to `formal/imports.py`.
