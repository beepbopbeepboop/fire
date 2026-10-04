# FORMAL_a_subscript_through_an_untyped_PARAMETER_is_a_blob_element_and_through_an_annotated_pointer_is_a_word

**Class:** a silent wrong answer — the same spelling indexes two different
addresses, and both backends agree on the wrong one.
**Area:** `formal/model.py`'s `subscript_base_lowering` (the decision both
emitters read), and therefore `formal/arm64_codegen.py`'s
`_emit_subscript_addr` and `formal/x86_64_codegen.py`'s twin. Found 2026-10-03
while bisecting `FORMAL_container_returning_export_whose_body_calls_helpers_breaks_the_CALLERS_image`,
whose `glob` reproducer is one instance of it.

**Status: MEASURED and reduced to one shape. NOT fixed — the neighbouring claim
`bug:FORMAL_a_blob_is_two_conventions` is in the same decision, and read
"Fixed" below for why that is not a reason to sit on it.**

## What is wrong

A pointer subscript has TWO conventions on this path, and which one a name gets
is decided by the name's declared type:

| the base | spelling | address |
|---|---|---|
| `Pointer[Int64]` (annotated) | `p[1]` | `p + 1*8` — a raw C pointer index |
| an UNTYPED name | `p[1]` | `p + 8 + 1*8` — element 1 of a `[count][e…]` blob |

The second is the blob walk in `_emit_subscript_addr`, which skips word 0 (the
count) and bounds-checks against it. The first is `shape == "load"` in
`model.subscript_base_lowering`, which is a plain scaled add. The annotation is
the only thing that chooses, and a PARAMETER has one only if the declaration
gives it one.

So the same callee, handed the same pointer, stores somewhere else depending on
how it spelled its parameter — and nothing says so.

## The reproducer

```mojo
def _fill_u(p) -> int:
    p[1] = 43
    return 0


def main(n):
    var b: Pointer[Int64] = malloc(8 * 4)
    memset(b, 0, 32)
    b[0] = 3
    printf("words before: %d %d %d\n", b[0], b[1], b[2])
    _fill_u(b)
    printf("words after:  %d %d %d\n", b[0], b[1], b[2])
    return 0
```

```
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove [--backend=x86_64] -o .tmp/x .tmp/prog.mojo && .tmp/x
words before: 3 0 0
words after:  3 0 43          # b[2], not b[1] — 8 bytes further on
```

**Identical on arm64 and x86_64**, and CPython's answer for the same text is
`b[1] == 43`. With the parameter annotated (`def _fill_u(p: Pointer[Int64])`) the
store lands on `b[1]` and both backends agree with CPython — so the annotation,
and nothing else, is the whole difference.

**A READ has the same defect**, and it is worse, because a read of the wrong
address is not a wrong answer to the question asked:

```mojo
def _peek(p) -> int:
    return p[0]          # reads p + 8, which is element 0 of a blob
```

`segs[0]` inside a helper is `segs + 8` and `segs[0]` in the caller is `segs`,
which is the mismatch that makes
`bugs/FORMAL_container_returning_export_whose_body_calls_helpers_breaks_the_CALLERS_image.md`'s
`glob` fail (its `_split(pattern, segs)` writes element 0 at `segs + 8` while
`glob` reads element 0 at `segs`).

**The bounds check fires on the wrong side of it.** The blob walk also emits the
count check, so storing into a blob whose count is not yet set traps:

```
movz x0, #1 ; movz x16, #1 ; svc #0x80        # a raw exit(1) syscall
```

and **a raw exit syscall does not flush stdio**, so a program that printed
before the call loses every buffered line. That is the whole of that other
doc's "starts, prints nothing, and exits 1", and it is why the symptom looked
like a CALLER-side frame bug: the caller is fine, and the callee's own first
statement never ran either because the callee trapped inside its FIRST helper.

## What is ruled out

* The call ABI. The argument moves correctly: the call is `mov x0, x20 ; push ;
  mov x0, x22 ; push ; pop ; mov x1, x0 ; pop ; bl` — traced from the emitted
  encoders, and `_split`'s prologue reads its two parameters into `x19`/`x20`
  from `x0`/`x1` as it should.
* The container RETURN. `-> List[String]` and a `malloc`'d blob both work with an
  annotated parameter (`test_formal_run.py`'s `blob` group pins the annotated
  form on both architectures).
* A one-image program. This is not cross-module at all: the reproducer above is
  a single `.mojo` file with no imports, so `formal/imports.py`'s cross-image
  rules — including `check_subscript_through_an_unclassified_import`, which is
  where `FORMAL_a_blob_is_two_conventions` landed — are not in the path.

## Why this is filed rather than fixed, honestly

The decision is `model.subscript_base_lowering`, and `formal13-1`'s claim
includes `bug:FORMAL_a_blob_is_two_conventions`, whose doc was deleted with its
fix (`d9874a93`, on master). That fix is about a cross-IMAGE pointer and this
is about a PARAMETER in one image, so they are different instances of one
family — but they are the same decision, and a narrowing of it that made
unannotated-parameter subscripts REFUSE would take out every host module that
reads a blob through an untyped parameter, which is a change to the host-module
surface rather than to one construct. That is a bigger decision than a light
worker should make against someone else's live claim.

## The next step, in the order the measurements give

1. **Decide what an unannotated parameter means**, and write it down in
   `subscript_base_lowering`'s docstring, because today it means "blob" by
   default and the alternative is "raw pointer". The measurement that decides
   it is a census: how many subscripts in `formal/hostmods/**/*.mojo` go through
   an unannotated parameter, and how many of those callers pass a blob and how
   many pass a `Pointer[Int64]`. The answer is a call-site fact the callee
   cannot see, which is why the honest fix may be to REFUSE the ambiguous
   spelling and name the annotation, the way
   `check_subscript_through_an_unclassified_import` already does across an
   image boundary.
2. **Whatever the answer, give the raw-pointer convention a spelling that does
   not depend on an annotation being present at the callee.** A parameter's
   kind could travel in the dylib manifest beside `frame_params`, which is
   where a cross-image parameter's shape already travels; within one image the
   call site is in the same function tree and the emitter could read it.
3. **Pin the mismatch itself meanwhile.** The cheapest possible regression is
   the pair above — one helper with an annotated parameter and one without,
   called on the same pointer, both storing, both read back — because it fails
   on the CURRENT tree and passes only when the two conventions agree.
   `test_formal_run.py`'s `blob` group is where it belongs.

## Reproducing

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove -o .tmp/x .tmp/prog.mojo
Built: .tmp/x  [arm64/macho]
$ .tmp/x
words before: 3 0 0
words after:  3 0 43
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove --backend=x86_64 -o .tmp/y .tmp/prog.mojo && .tmp/y
words before: 3 0 0
words after:  3 0 43
```
