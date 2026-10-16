# FORMAL_a_tuple_for_target_leaf_is_classified_as_the_element_container: `printf("%d", a)` is refused as "a is a CONTAINER" for `for a, b in [(1, 2)]`

**Area:** FORMAL, both backends, in the shared value model —
`formal/model.py::ValueKinds._scan`'s `ForStmt` arm (`_bind_target(s.target,
self._iterable_kind(s.iterable), …)`), against `_unpacked_element_kind`, which
is what the ASSIGNMENT spelling of the same target already uses. **Filed, NOT
fixed** (found 2026-10-12 on `work/formal275-docs` while fixing the starred
for-target, which is why the doc's own repro is unreachable).

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ cat .tmp/t1.mojo
def main():
    for a, b in [(1, 2)]:
        printf("a=%d b=%d\n", a, b)
    return 0

$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 fire.py build --formal --no-prove --backend=arm64 \
      -o .tmp/t1.arm64 .tmp/t1.mojo
build: the `%d` conversion in printf's format string reads `a` as a NUMBER…
  reads `a` as a number, and `a` is a CONTAINER — its one word is the address
  of its blob …
```

The interpreter answers it (`1 2`); the refusal is FALSE about the source. The
same happens on x86-64, and for the starred and nested spellings:

```
for a, b in [(1, 2)]:          printf("%d", a)   -> refused, "a is a CONTAINER"
for a, *rest in [(1, 2, 3)]:   printf("%d", a)   -> refused, "a is a CONTAINER"
for a, (b, c) in [(1, (2, 3))]: printf("%d", b)  -> refused, "b is a CONTAINER"
```

## The cause

`_scan`'s `ForStmt` arm binds **every leaf** of the target to the ITERABLE's
one-element kind:

```python
elif isinstance(s, F.ForStmt):
    self._bind_target(s.target, self._iterable_kind(s.iterable),
                      own=self._iterable_own_shape(s.iterable))
```

`_iterable_kind([(1, 2)])` is the kind of ONE element of the outer list, and
that element is the TUPLE `(1, 2)`, which `_pair_value_kind` classifies as the
container `list:int`. So `a` — which the source says holds `1` — is classified
`list:int`, and the newer `%d`-of-a-container refusal
(`515fe237`, "a NUMBER `printf` conversion of a CONTAINER is refused") turns
that misclassification into a build refusal.

The ASSIGNMENT spelling does not have this: `a, b = (1, 2)` goes through
`_unpacked_element_kind`, which narrows a tuple target's names to the tuple's
ELEMENT kind (`int`), and `print(a)` works there. The two spellings of the same
target shape disagree, and the `for` arm is the one that is wrong.

## Why the runtime answers are still right

The misclassification is invisible to arithmetic because the WORD `a` holds is
the integer the tuple element was: `s = s + a` adds the right number whatever
kind the reader believes. It is visible only to a reader that must classify the
value — `printf`/`print`, `len`, a subscript, truthiness — which is why the
starred for-target's own reproducer
(`for a, *rest in [(1,)]: printf("a=%d\n", a)`) reaches this instead of the
exit-1 the starred doc describes, and why nothing in the narrow for-target rows
saw it (they all sum with `+`).

## The exact next step

Give a TUPLE for-target the per-position element kind the assignment spelling
already gets, in `_scan`'s `ForStmt` arm: for a target that is a tuple/list
(`model.for_target_tree`), bind each leaf to `subscript_element_kind` of the
iterable's element kind — and the trailing `*name` leaf to a list of that same
element kind — rather than binding every leaf to the element kind itself.
`_unpacked_element_kind` is the reader to share; the one thing it does not do
today is answer for a STAR leaf, which is a REST list rather than an element.

The conservative direction is the one to keep: a leaf whose per-position element
kind cannot be stated should keep the current element kind (or fall to the word
default) rather than be refused, because `for a, b in <a name>` is ordinary and
its element kind is often only "a word".

**This is a corpus-wide kind change and needs a full `make gate`** — the for
target's kind is read by the subscript, `len`, truthiness and `print`
lowerings, so a suite run is the evidence that it moves only the false refusals.
It is filed rather than fixed here because `work/formal275-docs` is a light
worker and this is not its claimed bug.
