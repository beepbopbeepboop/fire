# FORMAL_container_returning_export_whose_body_calls_helpers_breaks_the_CALLERS_image

**Area:** the formal backends' cross-module call path — the callee's frame/reserve
computation and the caller's frame layout. Found 2026-10-03 on
`work/formal8-7-r2` while writing `formal/hostmods/glob.mojo`, which this bug
blocks (see "What it blocks").

**Status: the CAUSE IS LOCATED (2026-10-03), and it is not in the caller's
frame at all: it is `subscript_base_lowering`'s two index conventions, which
make the callee's helper write eight bytes from where the callee reads. Filed
as its own doc because the decision belongs to another claim — see §What the
cause is. Both architectures. The symptom is a silent image — exit 1, no output
at all — and §Why the output is missing is the half that made it look like a
frame bug.**

## What the cause is

`model.subscript_base_lowering` decides, per subscript, between a raw POINTER
index (`base + i*width`) and a BLOB walk (`base + 8 + i*width`, bounds-checked
against word 0). It decides from the base's DECLARED type, and a parameter has
one only if the declaration gives it one. So in `glob`:

```mojo
def glob(root, pattern, recursive) -> List[String]:
    var segs: Pointer[Int64] = malloc(8 * (n + 2))     # ANNOTATED: segs + 8k
    var ns = _split(pattern, segs)                      # writes segs + 8 + 8k
    ...

def _split(pattern, segs) -> int:                       # UNTYPED: segs + 8 + 8k
    ...
```

the write and the read of "element 0" are eight bytes apart, and the bounds
check on the callee's side is comparing an index against a count that has not
been written yet. Measured on both architectures:

| shape | before | after |
|---|---|---|
| `_fill(p: Pointer[Int64])`: `p[1] = 42` | `b[1] == 42` | `b[1] == 42` |
| `_fill_u(p)`: `p[1] = 43`, same pointer | `b[2] == 43`, `b[1]` unchanged | unchanged |

and CPython says `b[1] == 43` for both spellings. The full reproducer, both
architectures, is in
`bugs/FORMAL_a_subscript_through_an_untyped_PARAMETER_is_a_blob_element_and_through_an_annotated_pointer_is_a_word.md`.

**This is that doc's bug and not this one**, and the reason this doc's §The
bisect below stops where it does: the fix is `subscript_base_lowering`'s, and
`formal13-1` holds `bug:FORMAL_a_blob_is_two_conventions` — the same decision,
whose cross-image half landed on master as `d9874a93`. Narrowing it to refuse
the ambiguous spelling is a change to what every host module may write, so it
is not a call this claim gets to make.

## Why the output is missing, which is what made this look like a frame bug

The callee's store traps, and the trap is a raw syscall:

```
movz x0, #1 ; movz x16, #1 ; svc #0x80        # exit(1), by syscall
```

A raw `exit` syscall terminates the process **without flushing stdio**, so every
line the caller printed before the call is lost when stdout is a pipe — which is
how every harness runs it. The caller is fine; the callee traps inside its own
first helper; and "not even the first `printf` in `main` runs" is a property of
the exit, not of the caller's frame. This is why §What is RULED OUT below could
not find it: the evidence that pointed at the caller was an artefact of buffering.

## The symptom

An exported function whose declared return type is a CONTAINER, whose body calls
other functions in its own module, produces a CALLER's image that starts, prints
nothing, and exits 1. **Not even the first `printf` in `main` runs**, so it is the
caller's frame layout and not the callee's arithmetic — the callee's own first
statement never runs either.

## The reproducer

`formal/hostmods/glob.mojo` — 300 lines, and only its four public functions
matter. This is the whole of what the caller needs:

```python
# <repo>/formal/hostmods/glob.mojo
from os import listdir, listdir_len, listdir_get, listdir_free
from os.path import isdir, exists
from os._syscalls import str_alloc, str_put, str_len, str_build, fs_free
from fnmatch import match_any, byte_or

def glob(root, pattern, recursive) -> List[String]:
    var n = strlen(pattern)
    var trailing = 0
    if n > 0 and byte_or(pattern, n - 1) == 47:
        trailing = 1
        pattern = _slice(pattern, 0, n - 1)
    var segs: Pointer[Int64] = malloc(8 * (n + 2))
    var ns = _split(pattern, segs)
    var count = 0
    if ns > 0:
        count = _walk(root, segs, ns, 0, recursive, trailing, 0, 0)
    var b: Pointer[Int64] = malloc(8 * (count + 1))
    memset(b, 0, 8 * (count + 1))
    if count > 0:
        _walk(root, segs, ns, 0, recursive, trailing, b, 1)
    b[0] = count
    _free_segments(segs, ns)
    fs_free(segs)
    return b
```

with `_slice`, `_split`, `_walk`, `_walk_magic`, `_walk_literal`,
`_walk_recursive`, `_emit` and `_free_segments` private to the module, and the
caller:

```mojo
from glob import glob

def main(n):
    printf("start\n")
    var paths = glob("<any existing directory>", "*.py", 0)
    printf("got n=%d\n", len(paths))
    return 0
```

```
$ python3 tools/memslot.py --gb 8 --label t -- \
    python3 fire.py build --formal --no-prove --backend=arm64 -o /tmp/p p.mojo
Built: /tmp/p  [arm64/macho]
$ /tmp/p ; echo "exit=$?"
exit=1                 # and NO output — not even "start"
```

Identical on `--backend=x86_64`, and the two builds report the same thing, so it
is not an architecture drift.

## What is RULED OUT, measured

Each of these was tried and **works**, so none of them is the trigger:

| shape | result |
|---|---|
| `def g0(root, pattern, recursive) -> List[String]` with ONE `malloc` and no helper call | works |
| the same with TWO `malloc`s and no helper call | works |
| the same with one `malloc` + one private helper call + storing the call's result | works |
| the same with TWO `malloc`s + one private helper call | works |
| the same with a `_slice` call **and** `pattern = _slice(...)` rebinding a parameter | works |
| the same with a call to an 8-parameter private helper (`_walk`) | works |
| `-> str` and `-> int` exports that return a private call's result | works |
| ONE parameter instead of three, `-> List[String]`, inline blob | works |
| `has_magic(pattern) -> int` and `escape(pattern) -> str` from the SAME module, called from a program | work |
| `glob_free(paths) -> int` from the same module, called from a program | works |
| `os.listdir(path) -> List[String]` and `os.walk(root, maxdepth) -> List[String]` from a program | work |
| a call to `glob` inside a function that `main` NEVER calls | works — the image runs and prints |

That last row is the load-bearing one, and **it reads the other way now**: the
same call site is harmless when nothing calls it, because nothing CALLS the
callee, so the callee's first helper never runs and never traps. It was read as
"the caller's frame is laid out around this callee"; it is "the callee's own
first statement traps, and the trace looks like nothing ran".

## The bisect, and where it stands

Truncating `glob`'s body from the end, in the same module with the helpers still
present, each variant exported and called the same way:

| variant | body | result |
|---|---|---|
| `g0` | one `malloc`, no helper call | **works** |
| `g1` | `+ _split`, `+ _free_segments`, `+ fs_free(segs)` | **fails, silent** |
| `g2` | `g1` + the trailing-slash branch and `pattern = _slice(...)` | fails |
| `g3` | `g2` + the counting `_walk` | fails |
| `g4` | `g3` + the filling `_walk` (i.e. `glob` itself) | fails |

So the FIRST step that turns a working export into a failing one is **`_split`
plus `_free_segments` plus `fs_free`** — three private calls, two of them on the
segment array, and a `malloc`/`fs_free` pair around it. `g5`/`g7` above show that
two `mallocs` plus one helper call is fine, so it is not the allocation count and
not the number of calls; it is something about calling THREE functions, or about
the `malloc`/`free` PAIR, that the caller's frame computation mis-reads.

**And the failure MODE is not stable**, which is itself a datum: with the
`g6`-shaped body (`one malloc + one helper call + store the call's result`) the
image was **KILLED by signal 9** rather than exiting 1; with `g1` and `glob` it
exits 1 silently. Different shapes, different symptoms, one area.

## The bisect, re-run on 2026-10-03, and what it actually discriminates

The harness above was rebuilt (`.tmp/cx/bisect_r3.py` in the tree that measured
this; a two-file module plus one caller per variant, built and RUN, so the
verdict is the image's exit code and output). It reproduces the symptom on the
first shape that stores into a blob it has not counted yet, and **that shape is
the harness's own bug, not the compiler's** — which is worth stating because it
is the same mistake this doc's original bisect made:

| variant | body | result |
|---|---|---|
| count first, then a helper that writes element 1, one `malloc` | `b[0] = 3; b[1] = _split(pattern, b)` | **works** |
| the same with the helper taking only the string | `b[0] = 3; b[1] = _split(pattern)` | works |
| the same with the helper's result discarded | `b[0] = 3; _split(pattern, b)` | works |
| **count NOT yet set**, helper writes element 1 | `b[0] = _split(pattern, b)` | **fails, silent** |
| count not yet set, the store in the CALLER instead | `b[0] = _split(pattern)` | prints a count, exits 0 |

The last two rows are the discriminator, and they are not about the container
return, the number of calls, or the malloc/free pair: **the same store is
checked in the callee and not in the caller**, because the callee's `segs` is
UNTYPED (so it takes the blob walk, count and all) and the caller's `b` is
annotated `Pointer[Int64]` (so it is a raw pointer index). With the count
declared first, every variant passes on both architectures. That is
`bugs/FORMAL_a_subscript_through_an_untyped_PARAMETER_is_a_blob_element_and_through_an_annotated_pointer_is_a_word.md`,
and it is the whole of what this doc was chasing.

## What it blocks, and why it is not worked around

`bugs/FORMAL_host_import_row_5_measured.md`'s remaining item is
`formal/hostmods/glob.mojo`, and that module is written and correct on the
semantics — checked against CPython's own `glob` for the shapes in the design
comment there — but its caller-side image does not run. **It is not committed**,
because a module whose callers get a silent exit-1 image is worse than no module:
the export map would bind and the program would run and compute nothing. A
`CONTROL-STATUS: PARTIAL` is the honest report.

## Exact next step

Steps 1 and 2 are DONE and are superseded by §What the cause is above: the
statement is named, and it is not in the caller's frame computation at all. What
is left:

1. **`subscript_base_lowering`'s two conventions, which is the other claim's.**
   The census that decides it — how many subscripts in `formal/hostmods/` go
   through an unannotated parameter, and how many of those callers pass a blob —
   is in that doc's §The next step, and it is the gate on whether the repair is
   an annotation, a manifest-carried parameter kind, or a refusal of the
   ambiguous spelling.
2. **`glob.mojo` itself is then unblocked, and it is worth re-checking its
   `_split`/`_walk` signatures against whichever answer lands**: if an
   unannotated parameter keeps meaning "blob", every one of its parameters that
   receives a `Pointer[Int64]` needs the annotation, which is a mechanical edit
   to a module that does not exist in this tree yet (it is on
   `work/formal8-7-r2`'s working tree, uncommitted).
3. **Until then, the cheapest thing that would have found this in an afternoon**
   is in that other doc's §next step 3: one helper with an annotated parameter
   and one without, called on the same pointer, both storing, both read back. It
   fails on the current tree, so it is a regression test that pays for itself.
