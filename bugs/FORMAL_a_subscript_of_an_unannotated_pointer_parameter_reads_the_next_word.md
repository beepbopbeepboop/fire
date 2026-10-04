# FORMAL_a_subscript_of_an_unannotated_pointer_parameter_reads_the_next_word

**Found 2026-10-03** while writing `os.environ_update` for
`formal/hostmods/os/__init__.mojo` (`bugs/FORMAL_os_environ_is_a_view_and_the_
sweep_row_behind_it.md` §4). It is a **silent wrong answer**, not a refusal, on
**both architectures**, and it is in the shared model rather than in either
emitter. **The trigger is not the missing annotation but the ABSENT POINTER
TYPE**: a parameter annotated `Int` does it too, and an unannotated one that
receives a `char *` reads text-section bytes rather than the caller's string.

**The corpus case is FIXED by hand and pinned** — `environ_update`'s parameter
is annotated, and `test_formal_os_backing.py`'s `environ_view` is 77 answers
against CPython on both architectures with it. What is open is that nothing
REQUIRES the annotation, nothing refuses its absence, and the answer without one
is wrong rather than refused, which is the one combination this backend is
written to never produce. §"The exposure" measures what a fix would cost.

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

## It is not "unannotated" — it is "not established to be a POINTER", and an
## `Int`-annotated parameter does it too

| shape | arm64 | x86-64 | CPython |
|---|---|---|---|
| `def f(e: Pointer[Int64]): return e[0]`, called with a blob | 53 | 53 | 53 |
| `def f(e): return e[0]`, called with a blob | **7** | **7** | 53 |
| **`def f(e: Int): return e[0]`, called with a blob** | **7** | **7** | `TypeError` |
| `def f(s: Pointer[UInt8]): return s[0]`, called with `"AB"` | 65 | 65 | 65 |
| `def f(s): return s[0]`, called with `"AB"` | **1953459822** | **1953459822** | 65 |

The third row is the one that makes this a value-model question and not a
missing annotation: the parameter says `Int` **out loud**, so no annotation
fixes it, and the answer is the blob header's neighbour rather than a refusal.
The last row is worse than a wrong number in the sense that matters — those four
bytes are not the caller's string at all, they are text-section bytes read at
`base + 8` from an address whose first word happened to be small.

## Why it happens: it is the residual `subscript_base_lowering` NAMES and does
## not measure

`formal/model.py`'s `subscript_base_lowering` routes `obj[i]` three ways: a
`load` at the pointee's width when the base is established to be a pointer, a
refusal when it is a pointer whose pointee has no width, and — for **every base
whose kind nothing establishes** — the container reading, where element `i` is at
`base + 8 + 8*count`. That third answer is right for a list and **wrong by one
whole element** for a word holding an address: a blob's first word is its count
and an address has no count there. Both emitters ask the same function, which is
why the two machines agree to the byte.

Its own docstring states the trade, declines it, and then says where the number
is:

> What is deliberately NOT refused: a base whose kind nothing establishes. […]
> "refuse every unestablished base" would refuse every `p[i]` where `p` came
> from a caller. Measured over the 395 `.mojo` files of the sweep corpus that is
> ~2 200 sites whose base is a word […] The remaining wrong-number case — a base
> that IS an address and says nothing — is recorded, with the number, in that
> bug doc.

**The bug doc it names is DELETED** (`bugs/FORMAL_subscript_of_a_pointer_reads_
a_blob_count.md`, fixed when `p[i]` was routed to the pointer path for a base
that says it is one) and five files still cite it, so the residual it recorded
had nowhere left to live. This document is that residual, and the measurement
below is the number its author did not take.

## The exposure, measured: a blanket refusal is NOT the fix

`tools/formal_unstated_base_subscript_census.py` (new, and a parse plus one
walk — no build, no Lean, no sweep, for the reason
`tools/formal_frame_field_census.py` gives) asks the real
`subscript_base_lowering` and the real `model.ValueKinds` over the corpus:

```
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 tools/formal_unstated_base_subscript_census.py
scanned 377 .mojo files
subscripts that take the BLOB reading: 5510 sites in 174 files
…whose base is a LIST, so the reading is RIGHT: 43
…whose base is NOT a list — THE EXPOSURE, an upper bound: 5467 sites in 170 files

the exposure, by what the base's kind is:
  NOTHING                  4017
  int                      1015
  type                      418
  str                        17

the exposure, by how the base is spelled:
  a name                   3781
  a field read             1389
  a call result             273
  a subscript                24
```

**Read it as an UPPER BOUND and it is still too big to refuse.** The 418 `type`
sites are the type-parameter subscripts (`List[Int]`) that are refused further
down the same path, which is the "most of them" the docstring predicted — but
4017 bases are `NOTHING`, i.e. nothing in the image says what they are, and many
of those really are containers this instrument cannot see (a local bound from a
callee that returns a blob). So the number settles ONE question — "is refusing
the unestablished base cheap?" — and the answer is **no**, which is why the
existing design is right and why the fix has to be narrower than a refusal.

## What the next step is, precisely

Two candidate rules, and which one is correct is a decision rather than a
derivation:

  * **Refuse a subscript whose base's kind the image states as a NUMBER.**
    That is the 1015 `int` row plus the third row of the table above, it is the
    one shape where the blob reading is certainly wrong (an integer has no
    elements) and where the source itself is nonsense, and it costs nothing
    outside itself. The reader is `subscript_element_kind` /
    `subscript_base_lowering`'s own `("blob", 8, False, None)` arm: it already
    has the kind in hand when it answers `blob`, and `int` is not a list kind.
  * **Refuse it for a base that IS a parameter with no annotation**, which is
    the shape found here and is narrower still — but it is a SPELLING rule
    dressed as a type rule, and `FORMAL_a_local_read_before_its_first_
    assignment.md`'s instrument exists because spelling rules are how this corpus
    gets its false positives.

Either way the change is in `formal/model.py` and both emitters inherit it, so
the measurement to make afterwards is the sweep's own refusal count — the
integrator's — and the pin is a `test_formal_run.py` row per shape in the table
above. I did not choose between them: the choice is between two wrong answers for
a base nothing types, and `FORMAL_pointer_value_model.md`'s owner is the one who
should make it.

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