# FORMAL_link_dylib_imported_struct_field: an executable cannot bind a field of a struct it links

**Status:** found, not fixed, and deliberately not fixed here: it is the
`--link-dylib` boundary, which is a different area from the construct this
session was on. Written down because the refusal's stated repair is impossible
to apply, and that is the defect class worth handing over.

## What is wrong

A dylib built by `fire.py dylib --formal` advertises its structs' METHODS
(`_formal_exports` emits a `kind: "method"` entry, and a `__len__` is one — the
manifest for a two-field struct with a `__len__` and an `add` carries
`heaplib_Bag___len__` and `heaplib_Bag_add`). What it does not carry, and what
the importing executable has no way to recover, is the struct's FIELD LIST. So a
program that links the library and touches a field is refused at the first field
access, naming a repair that cannot be followed:

```
$ fire.py dylib --formal --no-prove -o heaplib.dylib heaplib.mojo
Built: heaplib.dylib
$ cat prog.mojo
def main(k: Int) -> Int:
    var b = Bag()
    b.n = 4
    b.tag = 1
    printf("%d", b.n)
    return 0
$ fire.py build --formal --no-prove -o prog.aout --link-dylib heaplib.dylib prog.mojo
build: main: 'b.n' is a field access through 'b', and this path has no way to
say what 'b' holds. … 'b' is bound here as a parameter, so none of the three is
established … Bind the base from a constructor THIS MODULE declares (`x = S()`),
or declare the field's type so the base is not typeless
```

"Bind the base from a constructor this module declares" is the right advice and
is impossible here: `Bag` is declared in `heaplib.mojo`, not in `prog.mojo`, and
the whole point of the dylib is that the program does not have that source. The
same program with the struct declared locally builds and runs, which is the
control that says the refusal is about the boundary and not about the program.

Two things are true at once and the message asserts only the first: the field
access is a REFUSAL (nothing is silently wrong today), and the reason it gives
is a fact about the TARGET rather than about the program — the very distinction
`formal/imports.py` draws for host modules and that this path does not draw for
an imported struct.

## Why it is not reachable from the `len()` work, and how that was checked

The single-translation-unit path — a sibling `.mojo` next to the program, which
is what `test_formal_run.py`'s module cases and the stdlib sweep both use — has
no such gap: the module is inlined, its `struct_is_framed` answer is recomputed
from its own parse, and `len(b)` across the boundary computes the right answer on
both architectures. Only the `--link-dylib` image boundary has it. So:

* the `__len__` REWRITE is sound across a dylib (the callee is a method of the
  receiver's own struct, the field list comes from the same source file the
  library was compiled from, and a frame address is absolute);
* what is missing is the RECEIVER'S DECLARATION reaching the executable, which
  every field access needs and which the manifest does not carry.

## The exact next step

One field list per exported struct in the dylib MANIFEST, the same way the
manifest already carries each export's arity and signature: `structs: [{"module":
…, "name": "Bag", "fields": ["n", "tag"]}]` beside `exports`. Then
`formal/imports.py`'s imported-struct collection reads it and `struct_is_framed`
answers the same way it does for an inlined module, and the executable's frame
slot table has a field list to compute `base + 8k` from.

The alternative, if a manifest is not wanted, is for the importing build to be
given the module's SOURCE PATH — it is already recorded as the dylib's
`load_path`'s sibling in every case the sweep exercises — and to parse it, which
is what the single-TU path does today. The manifest is the better of the two
because the two sides then cannot disagree about a field list, which is the same
agreement argument `bugs/FORMAL_frame_receiver_handoff.md` §1 makes for the
method hand-off.

A narrower, honest interim is to make the message say which of the two facts is
operating — that the struct is in a LINKED LIBRARY and this image has no
declaration of it — rather than telling the reader to bind the base from a
constructor this module does not declare.

## Verification

* `fire.py dylib --formal --no-prove` on a two-field struct with a `__len__`
  and an `add`: the manifest exports `Bag___len__` and `Bag_add`, so the method
  side works.
* `fire.py build --formal --no-prove --link-dylib` on a program that writes
  `b.n` and reads it back: refused as quoted above, on arm64.
* The same program with the struct declared locally, no `--link-dylib`: builds,
  runs, prints 4.
* The single-TU sibling-import equivalent of the same program, including
  `len(b)` and a method call on the imported struct: builds and runs on BOTH
  architectures, `7 14`.
