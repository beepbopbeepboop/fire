# CODEGEN: a list literal longer than 4095 words dies on a bare AssertionError

## Status (2026-09-30 — FIXED. The 4095-word limit is gone; the real limit is now stated in a message both backends share)

A blob element is at byte `8*(i+1)` from the blob's base, and the arm64
STR-immediate offset field is 12 bits SCALED by the access size, so element 4095
is the first one the instruction cannot name. The store now puts the offset in a
REGISTER past that reach, so the limit that remains is the frame's — and it is
stated, on both backends, in one message.

Measured on this tree, `fire.py build --formal --no-prove`:

| elements | before | after (arm64) | after (x86-64) |
|---|---|---|---|
| 4094 | builds | builds | builds |
| 4095 | builds | builds, `len` = 4095 | **refused**: 32768 bytes needed, 16384 available |
| 4096 | `AssertionError` | builds, `len` = 4096 | refused |
| 5000 | `AssertionError` | builds, `len` = 5000 | refused |
| 16000 | `AssertionError` | builds, every element reads back | refused |
| 16383 | `AssertionError` | builds, `len` = 16383 | refused |
| 16384 | `AssertionError` | **refused**: 131080 bytes needed, 131072 available | refused |
| 20000 | `AssertionError` | refused | refused |

So arm64's list-literal ceiling is now **16383 words** (a 128 KB frame budget
divided by 8, less the count word) and x86-64's is **2047** (a 16 KB blob
region). The two ceilings differ because the two frames differ; they are now
refused by the same sentence with the same shape, which is what a reader
comparing the architectures needs.

## The fix

**`formal/arm64.py`** — two encoders, each verified against
`clang --target=aarch64-apple-darwin` + `otool -s __TEXT __text`:

| encoder | `str x0,[x9,x10]` | `str x0,[x9,x15]` | base |
|---|---|---|---|
| `encode_str_xt_xn_xm` | `f82a6920` | `f82f6920` | `0xF8206800` |
| `encode_ldr_xt_xn_xm` | `f86a6920` | `f86f6920` | `0xF8606800` |

**`formal/arm64_codegen.py`** — `_emit_blob_store(base, byte_off, val)` and
`_emit_blob_load(base, byte_off, val)`, which use the immediate form below
`_BLOB_IMM_MAX` (32760) and the register form above it, with the offset
materialized by the existing `_emit_mov_imm` (MOVZ/MOVK, so any 64-bit
constant). X15 is the offset register: locals are X19..X28 and the temps this
emitter uses are X0..X14 and X16..X18.

Five call sites moved onto them, and the reason it is five and not one is the
point of the helper: **four of them had the identical `8 * (i + 1)` shape and
the identical latent assert**, and the bug doc this file replaces only ever saw
the list-literal one.

| site | shape | reachable by |
|---|---|---|
| `_emit_list` | `STR` | a list literal — the reported case |
| `_emit_range_list` static path | `STR` | `range(0, 6000)`, i.e. **the realistic way to hit this at all** |
| tuple unpack, literal RHS | `LDR` | a 4095-target tuple assignment |
| nested tuple unpack | `LDR` | a nested one |
| the third `LDR` site | `LDR` | the same walk, one branch over |

Below the threshold the immediate form is still used, because it is one
instruction instead of three and every list anyone writes is below it.

## The message, which was the other half of this bug

The doc said "the *documented* limit has to be stated somewhere a caller reads
it, which today it is not". It still was not, on the backend that did *not*
crash: x86-64's check compared two negative FRAME OFFSETS and printed them as
byte counts, so a 4095-element list literal read

```text
build: list literals exceed the formal frame (16368 > -16 bytes)
```

— a true statement about two numbers and no help at all. There were five such
messages in `formal/arm64_codegen.py` and four in `formal/x86_64_codegen.py`,
each formatting its own two sides. That is nine copies of one decision, which is
how the two architectures came to describe the same limit in different shapes
with different vocabularies.

`formal/model.py`'s `frame_blob_refusal(what, wanted, available)` is now the one
message, and both backends pass it SIZES. The same word fixes the vocabularies
(`"list literals"` → `"a list literal"`, `"slice views"` → `"a slice view"`),
and the number a caller can act on — how many elements would fit — is derived
from the budget the way the emitters derive the blob size:

```text
build: a list literal does not fit in the frame: it needs 160008 bytes and this
function has 131072 left for containers. A blob of 8-byte elements is
[count][element...], so at most 16383 element(s) fit in what is left here — and
the budget is shared with every other list, dict, string and receiver frame in
the same body. Build the container at run time (append into a list literal sized
for what the program needs), or split it across two functions so each gets its
own budget.
```

x86-64 gained `_blob_available()` and `_blob_used()` for this, because its
`_blob_cap` is a frame offset and its `_list_cursor` is an offset too; both are
now converted to sizes at the point of comparison. The arithmetic is
**identical** to what it replaced — `_blob_available() - _blob_used()` reduces to
`_blob_cap - _list_cursor` — and that was verified by measurement, not by
reading: `test_x86_64_containers.py`'s one failing case returns the identical
wrong number (178) with and without the change, see
`bugs/CODEGEN_x86_64_nested_comprehension_wrong_answer.md`.

## Tests

Four cases in `test_formal_run.py`, and the split between them is the point:

* `list_literal_past_the_immediate_offset` — 5000 elements, reads `a[0]` and
  `a[4999]`. Two ends of one blob through one function, so a fix that moved the
  far STORES but not the far LOADS would build this, run it, and read the wrong
  word back.
* `every_element_of_a_16000_element_list_reads_back` — all 16000 elements summed
  through a subscript, which is the only way to tell "the far stores landed in
  the right places" from "the ends are right". 16000 is 87% of arm64's budget,
  so it also pins that the frame reservation and the element loop agree.
* `range_literal_past_the_immediate_offset` — `range(0, 6000)`, the static
  `range()` path, which had the same assert at the same element and is how a
  real program reaches this limit.
* `refuse_list_literal_over_the_frame_budget` — 20000 words, and the `refuse:`
  machinery checks **both** backends produce the same sentence, because the two
  budgets differ and a reader comparing the architectures needs to see that the
  difference is the budget and not the message.

## A limit worth knowing about, found on the way

`len(range(0, n))` is refused with a *different* message — "`len(a)` is
`len()` of a value classified as `'int'`" — on both backends, for every `n`.
The `range()` result is not classified as a list for `len`, so the `range()` rows
above index it rather than measuring it. That is a pre-existing gap in the
`range()` result's classification, independent of this limit, and it is not
fixed here. Filed as the second half of
`bugs/CODEGEN_x86_64_nested_comprehension_wrong_answer.md`'s neighbourhood: the
next person to look at `range()` should start with `_expr_str_kind`'s list
answer for a `range()` call rather than with the emitter.

---

## Original report (2026-09-29), kept as written

A list literal of more than 4095 elements does not build, and it does not build
with a message: the build dies inside the encoder with

```text
  File "formal/arm64_codegen.py", line 4006, in _emit_list
    self.asm.emit(encode_str_xt_xn_imm(0, 9, 8 * (i + 1)))
  File "formal/arm64.py", line 345, in encode_str_xt_xn_imm
    assert 0 <= imm12 < 0x1000
AssertionError
```

4095 is exactly where the limit is, and it is a real architectural limit rather
than an arbitrary one: `encode_str_xt_xn_imm` encodes a STR (immediate,
unsigned offset) whose offset field is 12 bits, and `_emit_list` walks the
elements storing each at `8 * (i + 1)` bytes into the frame blob, so element
4095 lands at byte 32768 — one past what the instruction can express.

## Reproducer

```python
def main():
    var a = [1, 1, … 4096 elements total …]
    print(a[0])
```

| elements | result |
|---|---|
| 4094 | builds |
| 4095 | builds |
| 4096 | `AssertionError` |
| 4100 | `AssertionError` |

## Why it is filed rather than fixed here

The fix is not the assert — the assert is correct, and loosening it would emit a
truncated store. It is one of two things, and which one is right depends on a
decision that is not this module's to make:

1. **Emit the blob in pieces.** Fill 4095 words with STR-immediate stores, then
   store the pointer with a register-offset STR (or a MOVZ/MOVK pair plus STR
   with a register offset) and continue. This raises the limit to whatever the
   frame allows — and the frame limit is the other half of this: a formal frame
   list is capped at 131072 bytes, so a 16384-element list of words is the real
   ceiling, not infinity.
2. **Refuse it with a message that says so.** A `CodegenError` naming the
   element count and the 4095 limit is what a caller can act on; a bare
   `AssertionError` from an encoder three frames deep is not.

(1) is strictly better and is what should happen; (2) is the minimum that makes
the existing behaviour honest. Either way the *documented* limit has to be
stated somewhere a caller reads it, which today it is not.

**Both landed**, and the numbers above confirm the prediction in (1) exactly: a
16384-element list of words is the ceiling, because `8 * (1 + 16384) = 131080`
against 131072 bytes of frame.

## Measured impact on this repository

`formal/hostmods/ast.mojo` takes a caller-owned token buffer as a list
parameter and `tokenize_from` is called with a window, because a whole file's
token stream at three words per token is far past this limit: the 1200-token
window the test uses is 3608 words, which is 88% of the 4095 available, and a
larger window does not build. That is the reason the module's windowing API
exists in the shape it does, and it is why `token_bound` is an upper bound a
caller sizes a *window* from rather than a buffer for the whole file.

**The windowing is no longer forced by this limit on arm64** — 3608 words is 22%
of 16383, and a whole file's token stream for a 1200-line source would fit. It
is still the right API (the x86-64 ceiling is 2047 words, so a 3608-word buffer
does not fit there), and the module's own comment now names a stale reason, which
is worth a note for whoever reads it next rather than a change here: this is a
host module exercised through `test_ast_formal.py`, not by a build.
