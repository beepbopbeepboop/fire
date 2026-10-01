# CODEGEN: a list literal longer than 4095 words dies on a bare AssertionError

## Status (2026-09-29 — OPEN, measured; a stated limit reported as a crash)

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

## Measured impact on this repository

`formal/hostmods/ast.mojo` takes a caller-owned token buffer as a list
parameter and `tokenize_from` is called with a window, because a whole file's
token stream at three words per token is far past this limit: the 1200-token
window the test uses is 3608 words, which is 88% of the 4095 available, and a
larger window does not build. That is the reason the module's windowing API
exists in the shape it does, and it is why `token_bound` is an upper bound a
caller sizes a *window* from rather than a buffer for the whole file.
