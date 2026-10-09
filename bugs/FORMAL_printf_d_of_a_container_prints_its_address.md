# `printf("%d", <a list>)` prints the blob's heap ADDRESS on both backends

**Area:** FORMAL, both backends — the `printf` vararg placement. **Status: NOT
FIXED.** Found 2026-10-05 on `work/formal35-4` while landing the list-of-lists
element kind, which is what made the shape reachable in a program with a NAME in
it; the shape itself predates that and is not caused by it.

## What I ran, what I saw, what I expected

```console
$ cat .tmp/printfl.mojo
def main() -> Int32:
    var xs = [1, 2, 3]
    printf("v=%d\n", xs)
    return 0

$ python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/pl .tmp/printfl.mojo
Built: .tmp/pl  [arm64/macho]
$ .tmp/pl
v=1809329920
$ python3 fire.py build --formal --no-prove --backend=x86_64 -o .tmp/pl .tmp/printfl.mojo
$ .tmp/pl
v=1870638832
```

Exit 0, nothing on stderr, and a heap address where CPython raises:

```
TypeError: %d format: a list is required, not int
```

Measured on `master` as well as on the tree that change landed on, and for a
local AND for a list PARAMETER (so it is not about how the name got its kind):

| source | arm64 | x86-64 | CPython |
|---|---|---|---|
| `var xs = [1, 2, 3]; printf("v=%d", xs)` | 1809329920 | 1870638832 | `TypeError` |
| `def show(xs): printf("v=%d", xs)` called `show([1, 2, 3])` | 1841065712 | 1870638832 | `TypeError` |

**This is the mirror of the refusal that exists.** `printf("%s", 42)` is
refused by name — `formal/model.py::printf_arg_text_evidence`'s step 3 reads a
NAME's own-shape evidence and refuses when it says integer, precisely because
"%s walks bytes looking for a NUL". `%d` of a container is the other direction
of the same table and there is no row for it: both backends place a vararg from
the FORMAT (`%d` → `SITE l`), and neither asks what the operand's kind says
before printing eight bytes of it.

## The exact next step

**One row in `formal/model.py`, asked by both emitters beside
`printf_kind_conversion_refusal`.** The evidence already exists and is already
positive: `ValueKinds.kind_of` answers `list:…` for a container and the emitters
already call it for this operand (it is what `_print_call`'s `%s`/`%lld` switch
and `printf_arg_float_evidence` read). So the refusal is "the operand's kind is
a container and the conversion is a NUMBER", with the operand's own kind as the
evidence rather than a name's `own_shape` — `printf_arg_text_evidence`'s step 5
is the same argument for `%s` and is the shape to copy.

Two things to decide, and the doc should say so rather than have the next reader
find them:

1. **`printf("%d", xs)` is a program whose own source is wrong**, so this is the
   refusal direction — but `printf("%d", b)` for a `bytearray` and
   `printf("%d", d)` for a `Dict` are the same shape and the same answer, so the
   row must be asked of the KIND (`is_list_kind`) rather than of the
   constructor's name, or the three disagree.
2. **What the reader should be told instead.** The useful sentence names the
   conversion and the operand's kind — CPython's own `TypeError: %d format: a
   list is required, not int` is the model to mirror, and it is checkable: this
   repository's oracle (`fire.py run`) raises on the same text, so the message
   can be pinned to the shape CPython reports.

The test belongs in `test_formal_run.py`'s `REFUSAL_CASES`, one row per
backend through the existing `refuse:` runner, which already requires both
architectures to produce the SAME words.
