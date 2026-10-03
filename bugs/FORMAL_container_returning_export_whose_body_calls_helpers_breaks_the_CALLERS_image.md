# FORMAL_container_returning_export_whose_body_calls_helpers_breaks_the_CALLERS_image

**Area:** the formal backends' cross-module call path — the callee's frame/reserve
computation and the caller's frame layout. Found 2026-10-03 on
`work/formal8-7-r2` while writing `formal/hostmods/glob.mojo`, which this bug
blocks (see "What it blocks").

**Status: reproducer pinned and bisected to a statement-level difference; the
cause is NOT located. Both architectures. The failure is a silent image — exit 1,
no output at all.**

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

That last row is the load-bearing one: **the same call site is harmless when
nothing calls it.** So the bug is in how the CALLER's frame is laid out around a
call to this particular callee, decided at build time from something about the
callee, and the callee's own behaviour is not involved.

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
two `malloc`s plus one helper call is fine, so it is not the allocation count and
not the number of calls; it is something about calling THREE functions, or about
the `malloc`/`free` PAIR, that the caller's frame computation mis-reads.

**And the failure MODE is not stable**, which is itself a datum: with the
`g6`-shaped body (`one malloc + one helper call + store the call's result`) the
image was **KILLED by signal 9** rather than exiting 1; with `g1` and `glob` it
exits 1 silently. Different shapes, different symptoms, one area.

## What it blocks, and why it is not worked around

`bugs/FORMAL_host_import_row_5_measured.md`'s remaining item is
`formal/hostmods/glob.mojo`, and that module is written and correct on the
semantics — checked against CPython's own `glob` for the shapes in the design
comment there — but its caller-side image does not run. **It is not committed**,
because a module whose callers get a silent exit-1 image is worse than no module:
the export map would bind and the program would run and compute nothing. A
`CONTROL-STATUS: PARTIAL` is the honest report.

## Exact next step

1. Build the bisect harness from this doc's `g0`/`g1` pair — two exports in one
   host module, one caller each — and grow `g1` one statement at a time until it
   stops working. That is four or five builds and it names the statement.
2. When it is named, look at what the CALLER emits for the call: the callee's
   `frame_params` contract is `[None, None, None]` for `glob` and the same for
   every working variant above, so the contract is NOT the discriminator. The
   next thing to compare is the frame RESERVE the caller computes for the
   container-typed return, and whether anything in the callee makes the model
   believe the callee writes through one of its parameters (which would switch
   the parameter to by-reference and change the caller's frame). `pattern` IS
   assigned in `glob` — and a by-reference `char *` is exactly the shape whose
   wrong handling corrupts a frame silently. **This is the most promising lead
   and it is a lead, not a diagnosis**: `g2` assigns `pattern` too and the
   one-parameter `pattern = _slice(...)` variant works, so the evidence so far
   is consistent with "assigned parameter AND a container-typed return AND more
   than one helper call" and nothing finer.
3. Whatever it is, it belongs in `formal/model.py` (the frame/reserve decision,
   shared) rather than in either emitter, because it reproduces on both.