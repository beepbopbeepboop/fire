# FORMAL: a name bound by a multi-name `for` target is classified as the ITERABLE's kind, so a scalar element is refused as a CONTAINER

**Area:** FORMAL, both backends — the shared value model
(`formal/model.py`'s `_bind_target` / `_kind_of_nested_elements`, read by
`formal/arm64_codegen.py` and `formal/x86_64_codegen.py`). **Status: OPEN.**
Found 2026-10-13 on `work/formal338-docs` while pinning the starred-for-target
fix; PRE-EXISTING and not that fix's doing (the star target binds a rest blob
now, but the same classification is behind it).

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ cat .tmp/ns2.mojo
def main():
    for a, b in [(1, 2)]:
        printf("a=%d\n", a)
    return 0
$ for A in arm64 x86_64; do python3 tools/memslot.py --gb 8 --label t -- \
      python3 fire.py build --formal --no-prove --backend=$A -o .tmp/ns2.$A \
      .tmp/ns2.mojo && ./.tmp/ns2.$A; echo "  exit=$?"; done
```

and, identically on both backends:

```
build: the `%d` conversion in printf's format string reads `a` as a number, and
`a` is a CONTAINER — its one word is the address of its blob, so the C library
renders the heap address rather than a value. ...
```

The interpreter and CPython both answer the program:

```console
$ python3 fire.py run .tmp/ns2.mojo
a=1
$ python3 -c 'for a, b in [(1, 2)]: print(a)'
1
```

## Why it is a bug rather than a gap

The element `(1, 2)` is a tuple blob, so the for-target unpacks it and `a` holds
the INTEGER `1`. The model instead gives `a` the element kind of the ITERABLE
(`[(1, 2)]`'s element is a tuple, i.e. a container), which is one level too
coarse: `_comprehension_target_names`'s docstring and
`_kind_of_nested_elements` both say so in as many words ("a tuple target's names
all get the ITERABLE's element kind, which is one level too coarse for
`[[1, 2], [3, 4]]` unpacked into `a, b`"). The refusal is therefore of the
SAFE direction (it refuses rather than printing an address), but it refuses a
program the interpreter and CPython both accept, and it fires on the commonest
scalar spelling there is.

The class is exactly the one the `printf`-container guard exists to catch, one
level of nesting away: the guard sees a name whose kind is a container and
refuses the `%d`. It is also why the deleted
`FORMAL_a_starred_for_target_is_broken_on_both_backends.md`'s own reproducer
(`for a, *rest in [(1,)]: printf("%d", a)`) still refuses at generation — its
star half is fixed, and this half is not.

## The boundary of it

* A single-name target is fine: `for a in [1, 2, 3]: printf("%d", a)` prints
  `1 2 3` on both backends (there is no second name to give a coarse kind).
* It is the multi-name target that trips it, and it does so whatever the inner
  element is: `for a, b in [(1, 2)]` (ints), `for k, v in [(10, 20)]`,
  `for a, *rest in [(1, 2, 3)]` all refuse the `%d` on the scalar name.
* Both backends refuse with the SAME words, which is why this is one shared
  model bug and not a backend divergence.

## Exact next step

`formal/model.py::ValueKinds._bind_target` binds EVERY name of a tuple target to
the SAME `kind` — the iterable's element kind:

```python
    elif isinstance(target, (F.TupleExpr, F.ListExpr)):
        for el in target.elements:
            self._bind_target(el, kind, own=own)
```

so `for a, b in [(1, 2)]` binds both `a` and `b` to the tuple blob's kind.  The
second-level kind is the one `_kind_of_nested_elements` already computes for an
element word (it is `_pair_value_kind`'s sibling and exists for exactly this
"element of an element" question), so the fix is to hand `_bind_target` the
per-name kind of the ELEMENT rather than of the iterable.  The two readers that
share the coarse answer — `_bind_target` for the `for` statement and
`_comprehension_target_names` for a comprehension target — want to move
together, or one spelling is fixed and the other is not.  The docstring's "one
imprecision rather than two" is the reason this is a scoped change and not a
new kind table.

## Reproducing every number here

```console
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 fire.py build --formal --no-prove .tmp/ns2.mojo     # refused
$ python3 fire.py run .tmp/ns2.mojo                               # a=1
```
