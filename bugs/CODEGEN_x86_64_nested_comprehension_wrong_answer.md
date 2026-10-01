# CODEGEN: an x86-64 nested comprehension returns the wrong number (and the two backends disagree)

**Found 2026-09-30 while fixing the 4095-word list-literal limit. NOT MINE and
NOT FIXED — the x86-64 container emitters are another worker's area
(`construct:x86-64-dylib`, `construct:arm64-silent-wrong-answers`). Filed
because `x86-containers` is a REGISTERED gate job with no `expect=` marker, so
this is a red test nothing points at, and a reader of the suite has no way to
tell it from a regression.**

## What I ran

`test_x86_64_containers.py`'s own case, `nested-comprehension`, standalone:

```python
def f(n):
    xs = [i + j for i in range(n) for j in range(n)]
    t = 0
    for x in xs:
        t += x
    return t

def main(n):
    return f(5)
```

| engine | answer | want |
|---|---|---|
| CPython | 100 | 100 |
| arm64 image (`--backend arm64`) | exit 100 | 100 |
| **x86-64 image (`--backend x86_64`)** | **exit 178** | 100 |
| x86-64 image, run directly (not through the suite) | **SIGBUS, exit 138** | 100 |

```console
$ python3 test_x86_64_containers.py
FAIL nested-comprehension       returned 178, want 100
[x86_64] PASS=44 FAIL=1 of 45
```

`178` is deterministic: two consecutive full-suite runs at HEAD and two with my
branch's changes all give exactly 178. Run *outside* the suite the same binary
dies with a bus error, so the program both computes a wrong number and, on a
different invocation, walks off the end of something — which is what a
comprehension that overruns its blob looks like from both sides.

## Why it is not a regression from the list-literal fix I was making

I touched `formal/x86_64_codegen.py` in that commit, so I checked rather than
argued. Measured by restoring `formal/{arm64,arm64_codegen,x86_64_codegen,model}.py`
from HEAD and running the suite twice, then putting my versions back and running
twice:

| tree | result |
|---|---|
| HEAD | `returned 178, want 100` (both runs) |
| with the list-literal fix | `returned 178, want 100` (both runs) |

Identical, so the byte-for-byte behaviour of this case is unchanged by that
work. Every edit I made to this file is arithmetically identical to what it
replaced — `_blob_available() - _blob_used()` is `_BLOB_BYTES - _frame_recv_bytes
- (_list_cursor - _blob_base - _frame_recv_bytes)`, and since `_blob_base =
-(_top_bytes + _BLOB_BYTES)` and `_blob_cap = -_top_bytes` that is exactly
`_blob_cap - _list_cursor`, which is what the old condition compared. The change
was the MESSAGE (it used to print two negative frame offsets as "bytes") and
nothing else.

## Why it matters more than one red row

It is the failure mode this backend is built to refuse rather than produce, and
it is producing it: the same source gives 100 on one architecture and 178 on the
other, with both builds succeeding. A single-generator comprehension is in the
same suite and passes, so the defect is specific to the NESTED form — the shape
`bugs/CODEGEN_nested_comprehension.md` is about, which is filed for the compiled
(gimple) path and has never been measured on the formal x86-64 emitter.

The bus error is the more serious half. A comprehension that overruns its blob
writes past the reservation, and the reservation is a frame area shared with
every other container in the function, so the damage lands on whatever is next
— a different program each time, which is the same class as
`bugs/FORMAL_wide_receiver_by_reference.md`'s use-after-free.

## The next step

1. Run the case with `--arch arm64` to confirm arm64 is the correct one of the
   two (already measured above: exit 100, matching CPython) — so the bug is
   localized to `formal/x86_64_codegen.py`'s comprehension path and not to
   `formal/model.py`'s `compr_cap` estimate, which both backends read.
2. Compare `_emit_compr_gen`'s cursor arithmetic against arm64's. The
   reservation is `8 + elem_size * cap` with `cap = min(cap, (avail - 8) //
   elem_size)`, and `_emit_compr_gen` is documented as a *recursive* walk with a
   depth counter (`d0`, `_compr_depth`) — a two-generator comprehension is the
   first case in the suite that recurses, and a cursor advanced per generator
   rather than per blob is exactly the arithmetic that yields a number nobody
   wrote.
3. Bisect by generator count: `[i + j for i in range(n) for j in range(n)]`
   against three generators, and against `[[i + j for j in range(n)] for i in
   range(n)]` (nested blob rather than nested generator). The last one
   distinguishes "the recursion is wrong" from "the flat two-generator chain is
   wrong", and those have different fixes.

Until then `x86-containers` stays red. It has no `expect=` marker, which is
correct — the marker is for a subject that is known broken and recorded, and this
is a subject that is known broken and, until now, unrecorded. This file is the
record; whoever fixes it should remove this file in the same commit and let
`x86-containers` go green on its own.
