# FORMAL_x86_64_formal_backend_gaps: two ways the x86-64 formal backend was not yet a backend

Split out of the old root `BUG.md`. Two small, unrelated gaps in
`formal/x86_64_codegen.py` as a *backend* — neither is a machine-model or
proof problem, which is the common thread worth keeping: in both cases the
model was right and the code around it was not.

## `X86_64Codegen.compile` did not accept `structs` — every build failed

`formal/build.py`'s shared `_codegen_and_link` passes `structs=structs` into
`codegen.compile(...)`, but `X86_64Codegen.compile` did not take it:

```
X86_64Codegen.compile() got an unexpected keyword argument 'structs'
```

Every x86-64 build failed, so `formal/x86_64_model_test.py` and the x86-64
proof path could not run at all. Fixed on the x86-64 side by accepting and
ignoring the argument (`formal/x86_64_codegen.py:412`) — one interface, two
backends, and no dependency on the arm64 struct work landing first. If the
x86-64 backend later needs the map, it is already threaded through.

## `len(x)` was not implemented — it linked to a libc symbol that does not exist

**Status:** FIXED on both backends (arm64 then x86-64; the x86-64 half waited
only because `formal/x86_64_codegen.py` was another agent's active file, and
landed once that agent was stopped). `len(range(10))` now returns 10 on
arm64 and on x86-64 under `arch -x86_64`. Five cases in
`test_formal_run.py` pin it (list, range, empty, nested, and two lens added).

**A string argument is no longer refused, and this section's reason for
refusing it was wrong.** The text below says "A string argument is refused by
name on both backends — a string is a bare `char *` with no length prefix, so
there is no count at offset 0 to read". The first half of that is still true;
the second half was the wrong reason, and it hid a worse bug. There is no
*count field* at offset 0, but a NUL-terminated `char *`'s length is a
*computation* — `strlen` is the definition of it — so `len` of a string needs no
field and no second word. It is now lowered as `strlen` on both backends, and
`bugs/FORMAL_string_value_model.md` has the decision, the cost and the
measurement.

The refusal was also narrower than the bug it was standing in for, which is
worth recording because the shape recurs: it fired on a **syntactic**
`StringLiteral` and on an identity type-constructor and nothing else, so
`len(m)` for a local fell through to the count-field load and read the first
eight bytes of the *character data*. Measured on both architectures,
`len(m)` where `m = "hello"` returned **1819043176** — 0x6C6C6568, the bytes
`hell` read little-endian — and `len("  hi".lstrip())` returned **536897896**,
0x20006869, `hi` followed by the two spaces that had just been trimmed. Both
built, both ran, both were wrong, and the wrong number was indistinguishable
from a right one. It is now 5 and 2. The third case — an operand the source
does not type — is refused rather than read, which is the half of the old
refusal that was right.

Found while gating the x86-64 machine model. `formal/x86_64_model_test.py` is
green, but the container suite has one failure
(`test_x86_64_containers.py`: 44/45), and the same input is wrong on arm64 too.

```python
def f(n):
    return len(range(n))     # f(10) should return 10
```

| backend | expected | actual |
|---|---|---|
| arm64    | 10 | -6 |
| x86_64   | 10 | -6 |

Root cause, confirmed from the emitted image rather than inferred: `len` is
not a builtin the codegen knows. `_emit_call` (`formal/x86_64_codegen.py:2683`)
special-cases `range` and then treats every other callee as either a known
function or an extern, and `len` matches neither, so it becomes an extern call:

```
$ python3 -c "...compile and print info['extern_calls']..."
extern call: {'sym': 'len', 'addr': 4294968347, 'kind': 'call'}
```

There is no `len` in libSystem, so the call binds to nothing meaningful and
returns whatever was in RAX — hence the same `-6` on both architectures rather
than two independent wrong answers. `len` is listed in
`formal/comptime_runner.py:116`'s `_KEYWORDS`, so the comptime path knows about
it; the compiled path does not.

Fix: lower `len` the way `range` is lowered — read the blob's count field (the
first 8 bytes) into RAX. It is one case in `_emit_call` plus the same in
`formal/arm64_codegen.py`.

Originally left alone deliberately: both files were open with another agent
doing the arm64 formal sweep, and a one-case builtin is not worth a collision.
Not an x86-64 regression and not a machine-model problem —
`formal/x86_64_decode.py` decodes the image correctly and the model agrees
with the hardware on all 43 examples (`test_x86_64_examples.py`: 43/43).
