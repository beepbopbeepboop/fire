# FORMAL_a_subscript_of_an_unannotated_pointer_parameter_reads_the_next_word

**Found 2026-10-03** while writing `os.environ_update` for
`formal/hostmods/os/__init__.mojo` (`bugs/FORMAL_os_environ_is_a_view_and_the_
sweep_row_behind_it.md` §4). It is a **silent wrong answer**, not a refusal, on
**both architectures**, and it is in the shared model rather than in either
emitter.

## The smallest source that shows it, and what it says

Twelve lines, and the two parameters differ only in whether they are ANNOTATED:

```mojo
def blob_count(e: Pointer[Int64]) -> int:      # annotated
    return e[0]

def read_annotated(e: Pointer[Int64]) -> int:  # annotated
    return e[0]

def read_bare(e) -> int:                       # NOT annotated
    return e[0]

def main(n):
    var b: Pointer[Int64] = malloc(16)
    memset(b, 0, 16)
    b[0] = 53
    b[1] = 7
    printf("annotated=%d\n", read_annotated(b))   # 53   CPython: 53
    printf("bare=%d\n", read_bare(b))             #  7   CPython: 53
    printf("callee=%d\n", blob_count(b))          # 53
    return 0
```

```
$ python3 fire.py build --formal --no-prove -o img .tmp/probe/min1.mojo && ./img
annotated=53
bare=7
callee=53
```

**`read_bare(b)` answers `b[1]`, not `b[0]`** — and `blob_count(b)`, which reads
the same word with the same subscript, answers 53. Both images, byte-identical:

| | arm64 | x86-64 |
|---|---|---|
| `read_annotated(b)` — `e: Pointer[Int64]`, `e[0]` | 53 | 53 |
| `read_bare(b)` — `e` unannotated, `e[0]` | **7** | **7** |
| `blob_count(b)` — `e: Pointer[Int64]`, `e[0]` | 53 | 53 |

**The offset is a WHOLE ELEMENT, not a scale error**, which is what makes it
read like a plausible answer rather than like a wild one. With
`b = [53, 7, 9, 11]`:

```
$ ./img                       # arm64 and x86-64, identical
e0=7 e1=9 em1=0
```

so `e[0]` reads the word at `+8`, `e[1]` the word at `+16`, and `e[-1]` reads
neither word 0 nor anything else in the blob (0, where the blob holds 53). It
is a fixed bias of one element for a non-negative index and something else again
for a negative one, and the honest statement is the observable one: **an
unannotated parameter that receives a pointer does not subscript where the
source says.**

## Why it is worth a document rather than a patch from the session that found it

The shape is COMMON in this repository's host modules, and every one of those
functions is a public export of a module dylib, so the wrong answer is
reachable from any importer. `formal/hostmods/os/__init__.mojo`'s own
`environ_*` family is the case in point: `environ_update(e, other)` written the
way every other function there is written —

```mojo
def environ_update(e: Pointer[Int64], other) -> Pointer[Int64]:
    var n = other[0]          # 7209024, not 52
```

— looped over garbage and never terminated. Annotating the parameter
(`other: Pointer[Int64]`) is the whole fix and the module now does that, so the
rows this document is about are **not** a known failure: they are a rule about
how a parameter has to be written. What is left open is that nothing REQUIRES
the annotation, nothing refuses its absence, and the answer without it is wrong
rather than refused — which is the one combination this backend is written to
never produce (`bugs/FORMAL_pointer_value_model.md`'s subject, and the reason
every reader in `formal/model.py` refuses rather than guesses).

## What I know and what I do not

**Measured:** the table above, both architectures, byte-identical; the
four-element mapping; the caller-side fact that `blob_count(b)` in the same
program answers 53, so the POINTER is intact and only the subscript is wrong;
and that annotating the parameter fixes it, on both backends, with no other
change (the `environ_update` case in `test_formal_os_backing.py` is 77 answers
against CPython on arm64 and on x86-64 with the annotation in place).

**Not measured, and it is where the next session starts.** I did not find the
subscript's element-width reader. The shape of the bug says it is a WIDTH
question and not an address one — the address is right, because the same
pointer read through an annotated parameter is right — so the reader to look at
is whichever one answers "how wide is the element of this subscript's base" for a
base whose type the source never states, and the answer it must be returning is
`DEFAULT_INT_TYPE`'s width applied to a base it should have refused. Two
candidates, both in `formal/`, and both named here rather than guessed at:

  * `formal/model.py`'s subscript element-kind reader — the one
    `subscript_element_kind` and `_note_binding` use, whose answer for a `char *`
    is "a byte" and whose answer for a name with no stated type is "nothing"
    (`docs` on `len()` of an unclassified value refuse for exactly that reason:
    `len(items) is len() of a value classified as 'int'`).
  * the `_offset_scale` guard `bugs/FORMAL_os_environ_is_a_view_and_the_sweep_row_
    behind_it.md` §3 records, which is about a DECLARED pointee and deliberately
    does not fire at a subscript whose base has no declared pointee at all.

The first thing to write down is a refusal that is TRUE, because a refusal is
the correct answer for `e[0]` where `e` has no stated type: the module would
then have to annotate, which is what the fix here did by hand. Whether the
refusal or a width answer is better is a value-model decision and belongs to
`FORMAL_pointer_value_model.md`'s owner; the shape of the hole is measured here
and the decision is not.

## Reproducing

Write the twelve-line source above to `.tmp/min1.mojo` and:

```console
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 fire.py build --formal --no-prove -o .tmp/min1 .tmp/min1.mojo
$ python3 .tmp/ptyrun.py .tmp/min1 3            # a pty, or stdout buffering
                                            # hides the answer: the program
                                            # prints its lines and exits, so a
                                            # pipe loses them if it dies
```

The pty note is not a detail: the first symptom I saw was an image that printed
NOTHING and exited 1, because the loop in the caller was walking a garbage count
and the buffered lines went with it. `setvbuf`/`stdbuf` do not reach a Mach-O
that calls `printf` directly; a pty does, and `script -q /dev/null <image>` is
the same thing without the helper.