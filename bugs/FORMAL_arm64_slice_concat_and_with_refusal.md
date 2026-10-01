# FORMAL/arm64: `with x as y:` is refused, and slices and list `+` compute the wrong thing

## Status: OPEN — three arm64 gaps, one of which blocks a whole statement

Found 2026-09-30 while working the nested-comprehension cluster
(`bugs/CODEGEN_nested_comprehension.md`, now deleted); none of these is fixed.
All three are arm64-only: x86-64 agrees with CPython on every case below.

## What I ran

`test_x86_64_containers.py --arch arm64` (the container/surface corpus) and the
same cases built by hand through `formal.build.compile_formal(..., arch=...)`,
run directly (no Rosetta involved on arm64), each compared with CPython on the
same source. Baseline: **arm64 45/60, x86-64 59/60** after the comprehension work;
the eight arm64 failures are the three below.

---

## 1. `with 7 as y:` is refused, so the whole statement is unusable

```
def main():
    x = 0
    with 7 as y:
        x = y
    return x
```

| | CPython | x86-64 | arm64 |
|---|---|---|---|
| builds, returns | `7` | `7` | **refused at build** |

```
FormalBuildError: f: 'y' is read at line 4 before anything in this function
stores it, and CPython raises UnboundLocalError for that program (NameError at
module level). This path cannot raise it: the register allocator gives 'y' a
home because the function assigns it somewhere, and the emitted image has no way
to mean "unbound" — so the read would return whatever the CALLER left in that
register, a word that changes with the build and differs between the two
backends. Store 'y' before reading it, or declare it where it is written.
```

The refusal is the read-before-store analysis, and its premise is false for
`with`: the `with` TARGET is a store (it binds `y`), it is just not one the
analysis counts. So the message tells the user to write code that is different
from what CPython accepts, and the x86-64 backend — which counts the target
store — builds the same program.

Note the message's second sentence is about `UnboundLocalError`, which this
program does not raise; the refusal is being made for the right reason
(don't read an uninitialised register) against the wrong fact (this is not an
unbound read).

**Next step:** find where a `WithStmt` target's binding is recorded in the
x86-64 path and record it in the arm64 one — most likely the same
frame-holder/definite-assignment pass, or `_collect_var_names`' `walk`'s
`F.WithStmt` branch (`formal/x86_64_codegen.py:207` has one; the arm64
allocator's equivalent needs the same). The x86-64 backend is the reference for
what "counted as a store" means here.

---

## 2. A slice of a list computes something else

All five slice cases return `1`:

| case | CPython | arm64 |
|---|---|---|
| `xs = [1,2,3,4,5,6]; return xs[1:3]` summed | `13` | **1** |
| `xs[2:]` summed | `34` | **1** |
| `xs[::2]` summed | `24` | **1** |
| `xs[:-2]` summed | `45` | **1** |
| `xs[2:1]` summed (empty) | `0` | **1** |

`1` for all of them, including the empty slice, is the shape of "the slice
materialised a blob with a count the source never wrote, or with the count read
from the wrong end". x86-64 is right on all five.

**Next step:** `_emit_slice_parts` in `formal/arm64_codegen.py` (the arm64
counterpart of the x86-64 `_emit_slice`) — the materialised view's count is
what every one of these reads, so that one word is the place to look. Compare
the two emitters' blob layout for the view (`[count][element …]`, per the shared
comment in `_emit_list`) before assuming the count is the bug: an empty slice
returning 1 also fits "the count field is the STEP".

---

## 3. `list + list` and the sum over the result

| case | CPython | arm64 |
|---|---|---|
| `xs = [1,2]; xs = xs + [3]; return len(xs)` | `3` | **a different number every build** (measured 158, 21, 214, 221, 196 across five builds of the same source) |
| `xs = [1] + [2]; t = 0; for x in xs: t += x; return t` | `3` | **SIGBUS (-10)** |

Non-determinism across builds of byte-identical source is the signature this
project's own notes call out: an uninitialised or out-of-range read. The
concat path reserves both operands and copies (`_emit_list_concat` in the
x86-64 backend is the reference), so the cursor arithmetic in the arm64 twin is
where to start.

**Next step:** `formal/arm64_codegen.py`'s list-concat emitter; compare its blob
reservation order against x86-64's `_emit_list_concat` (which computes all of
these correctly), since a reservation that lands inside a receiver frame or an
operand blob produces exactly this signature.

---

## Not fixed here, and why

All three are arm64-backend work outside the comprehension cluster I was working,
and none is a one-line fix that could be landed and verified inside that scope:
each needs the arm64 allocator/emitter compared line by line against its x86-64
twin, and the container corpus has to stay green for both arches while it
happens. Filed rather than half-done.

**Blast radius for whoever takes these:** `tools/formal_sweep.py` measures which
files BUILD per backend, so a change here is one of the "type-resolution change
that quietly regresses modules" shape CLAUDE.md warns about — compare its
before/after counts, and the `x86-examples` differential (which runs the 45
`formal/examples` through BOTH backends and compares) is the cheapest
regression signal for all three.