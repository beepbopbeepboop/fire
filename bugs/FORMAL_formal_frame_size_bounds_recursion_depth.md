# FORMAL_formal_frame_size_bounds_recursion_depth: neither formal backend guards the stack, so recursion past a fixed frame size is a SEGFAULT and not a refusal

**Status: OPEN, not fixed, and not mitigated at the backend.** Measured on both
architectures 2026-09-29, while writing `formal/hostmods/re.mojo` (whose parser
is recursive and therefore has to carry a `MAXDEPTH` cap precisely because of
this). The cap in that module is a *workaround at the call site*; nothing in
either backend stops a program from recursing past the ceiling, and nothing
diagnoses it when it does.

## The defect

Every function on the formal path subtracts a **fixed** frame size from the
stack pointer in its prologue and restores it in its epilogue, and neither
backend compares the result against a floor:

- **arm64** — `formal/arm64_codegen.py:37`: `_SCRATCH = 131072` (128 KiB),
  emitted as `_emit_sub_imm(self.asm, 31, 31, _SCRATCH)` at
  `formal/arm64_codegen.py:895`. It is fixed because the register allocator
  reserves its scratch as a fixed window rather than sizing it.
- **x86-64** — `formal/x86_64_codegen.py:64`: `_BLOB_BYTES = 16384` (16 KiB)
  plus the computed locals, emitted as
  `encode_sub_r64_imm32(Reg.RSP, self._frame_bytes)` at
  `formal/x86_64_codegen.py:756`.

There is no depth counter, no `SP` floor test, and no compile-time bound. The
main thread's stack is 8 MiB on this host (`ulimit -s` = 8176 KiB,
`RLIMIT_STACK` = 8372224), so the reachable recursion depth is simply
`8 MiB / frame size`, and crossing it is a **SIGSEGV with exit status 139** — no
output, no message, no status a caller could read.

## Measured, both backends, same 3-line source

```python
def deep(n: Int) -> Int:
    if n <= 0:
        return 0
    return deep(n - 1) + 1

def main(n: Int) -> Int:
    printf("%d\n", deep(N))
    return 0
```

| N | arm64 | x86-64 |
|---|---|---|
| 59 | 59 | — |
| 60 | 60 | — |
| 61 | **61** | — |
| 62 | **SIGSEGV, exit 139** | — |
| 200 | — | 200 |
| 400 | — | 400 |
| 450 | — | **450** |
| 500 | — | **SIGSEGV, exit 139** |

`62 × 128 KiB = 7.6 MiB` and `~450 × 16 KiB = 7.2 MiB`, both inside the same
8 MiB, which is the arithmetic the numbers predict. The encoder table confirms
arm64's 61: `1 << 20 = 1048576`, and `61 × 1048576 = 63,963,136` bytes of
scratch, leaving ~4.4 MiB — the ceiling is the scratch, not the saved registers.

## Why this is a compiler bug and not a program that is asking for too much

Three things, and any one of them would be enough:

1. **The source is not deep.** `deep` is tail-shaped and has two locals. There
   is nothing about it that a compiler is entitled to refuse, and it is the
   shape a hand-written recursive walk over a list or a tree takes.
2. **The two backends disagree by 8× on the same program.** 61 versus 450 for
   one source file is the definition of two implementations of one language not
   answering the same question. Whatever the right answer is, `deep(100)` is
   currently a working program on one backend and a segfault on the other.
3. **A crash is not a refusal, and this backend's stated rule is that an honest
   refusal beats a wrong answer.** The whole formal path is built on returning
   a status or declining to build; a SIGSEGV is a third thing, and it is the
   one outcome a caller cannot distinguish from the hardware failing. The
   codegen already has the idiom for the honest version — the division-by-zero
   guard at `formal/arm64_codegen.py:5490-5493` loads a code into `X0`/`X1` and
   emits `svc(0x80)`, and a stack-overflow guard is the same three
   instructions with a different comparison.

## Why it sat here

Nothing generated a program that recursed deeply until something needed a
recursive PARSER. The formal host modules are the only code on this path with
deep recursion, and they are new. There is no test that walks a call graph to
depth, and no test that asserts a *refusal* at a depth, because until now
there was no depth to refuse at — the number was an accident of
`_SCRATCH / 128 KiB` and the 8 MiB main stack, neither of which is written down
anywhere except here.

## What the honest fix is, and what is not

Three options, and the first is the one that belongs:

1. **A stack-floor guard in the prologue.** Both prologues already know the
   frame size, so the check is `SP < limit` after the subtraction, and the
   failure arm is `movz x0, <code>; svc(0x80)`. This converts a crash into a
   status at the exact point where the fact is known, and it is the only option
   that keeps the backend's own rule. The limit has to be a value the runtime
   supplies (the main stack is a property of the process, not of the
   translation unit), so it is either a link-time constant or a word read from
   a known address — a decision that belongs with whoever owns the runtime
   ABI, not with this fix.
2. **Size arm64's frame from need, the way x86-64 already does.** This raises
   61 to roughly 450 and makes the two backends agree, which is worth having on
   its own. It does **not** remove the ceiling and it is not a fix on its own;
   it is the same bug with a bigger number.
3. **A compile-time bound on the call graph's depth.** Not available: the depth
   is not knowable for a mutually-recursive graph, and refusing those would
   refuse ordinary code. Listed only so that it is not proposed again.

## Next step

Option 1, in both backends, with the limit threaded in from the runtime rather
than hard-coded. The two sites are the two `sub` instructions named above. A
test that recurses to `deep(1000)` and requires a *status* rather than a signal
belongs beside it — and it belongs in the suite, not in a host module, because
the host module that found this worked around it rather than reporting it.

**Do not "fix" this by raising `_SCRATCH`.** That is option 2 wearing option 1's
name, and it makes the arm64/x86-64 disagreement worse rather than better.
