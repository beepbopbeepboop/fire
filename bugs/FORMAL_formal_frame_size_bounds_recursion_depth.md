# FORMAL_formal_frame_size_bounds_recursion_depth: neither formal backend guards the stack, so recursion past a fixed frame size is a SEGFAULT and not a refusal

**Status: OPEN, not fixed, and not mitigated at the backend. Re-measured
2026-10-01 and the fix is now DERIVED — see §0, which corrects two claims in
the "what the honest fix is" section below and names the two things that stand
between the guard and landing.** Measured on both architectures 2026-09-29,
while writing `formal/hostmods/re.mojo` (whose parser is recursive and
therefore has to carry a `MAXDEPTH` cap precisely because of this). The cap in
that module is a *workaround at the call site*; nothing in either backend stops
a program from recursing past the ceiling, and nothing diagnoses it when it
does.

## §0 Re-measured, and what the fix actually needs (2026-10-01)

Everything in the rest of this document still reproduces exactly, and the two
programs and the two exit-139s are re-measured below on this tree. What is new
is §0.1 (option 2 is not the cheap win this document thought) and §0.2 (the
guard's instruction sequence and its one real obstacle).

### The defect, re-measured

`deep` is the three-line source the rest of this document uses, on this tree:

```
arm64    N=59 0    N=61 0    N=62  SIGSEGV, exit 139
x86-64   N=400 0   N=450 0   N=500  SIGSEGV, exit 139
```

Unchanged, and unchanged in the way that matters: **the same source is a working
program at depth 100 on one backend and a segfault on the other.**

### 0.1 Option 2 is NOT a cheap win, and this document's account of it is wrong

The section below offers, as its second option, "size arm64's frame from need,
**the way x86-64 already does**". x86-64 does not. Its blob window is just as
fixed:

    formal/x86_64_codegen.py:64   _BLOB_BYTES = 16384
    formal/x86_64_codegen.py:916  self._frame_bytes = _align16(self._top_bytes + _BLOB_BYTES + _TEMP_SLACK)

so x86-64 sizes from need **plus** a fixed 16 KiB container window, while arm64
has a single fixed window that serves BOTH the container area and the spill
slots — `formal/arm64_codegen.py:894`:

    self._blob_cap = _SCRATCH - self._spill_bytes

That difference is the whole of the 8×, and it also means the obvious version
of option 2 — "shrink arm64's window to what the function uses" — is unsafe in
BOTH directions, which the section below does not consider:

* **Shrinking arm64's window** trades depth against capacity against a history
  that has already gone wrong twice. The constant's own comment
  (`formal/arm64_codegen.py:34-37`) records the first time: the window was 4032
  and grew to 131072 because "large functions exhausted mid-expression (list
  concat / comprehension reserves left 0 free)". A static bound has to mirror
  every blob-allocating site — list literals, dict literals, pushed tuples,
  string blobs, comprehension temporaries, the variadic area — and MISSING ONE
  is not a refusal, it is a frame that is too small and a program that writes
  through it. There is a per-function scan already (`_scan_list_caps`) but it
  answers the capacity of a list LITERAL, which is one of those sites and not
  the set.
* **Growing x86-64's window to match** moves the *ceiling* from ~450 to ~61 on
  the other backend, so `deep(100)` — a program that runs today — stops. The
  gap does not close; it moves.

So option 2 is not "worth having on its own" in any cheap form, and this document
should not be read as offering one. **The guard is the fix and there is no
cheaper substitute.**

### 0.2 The guard's shape, and the ONE thing that has to be decided first

The instruction sequence needs no new encoder and no new decision, and it is
worth writing down so nobody re-derives it:

    # prologue, immediately after `sub sp, sp, #frame`
    <load the floor word into a scratch>     # ADRP+ADD+LDR, the addressing
                                             # _emit_global_init already proves
    cmp sp, x16                              # encode_cmp_xn_xm(31, 16) — SP is
                                             # Rn, and encode_cmp_xn_xm's assert
                                             # is on Xm, so SP-in-Rn is legal
    b.lo  <trap>                             # below the floor
    b      <ok>                              # or fall through
    <trap>:                                  # the idiom ten sites already use:
                                             #   movz x0, <status>
                                             #   movz x16, 1
                                             #   svc #0x80

`encode_cmp_xn_imm(31, imm)` is NOT usable — SP is a 64-bit address and the
immediate is 12 bits — which is why the register form is the one that matters.

**THE OBSTACLE, and it is one thing, not two: where the floor word lives.** The
check needs a limit, and the limit is a property of the process, not of the
translation unit, which is why this document says the decision belongs to the
runtime-ABI owner. Every other answer has been measured against and loses:

* **A link-time constant** — sound only if it is below the real stack floor, and
  the main stack's address is not a link-time constant (ASLR), so a constant can
  be wrong in one direction or the other and there is no constant that is right.
* **A callee-saved register** — works, and costs: arm64's ten
  (`_CALLEE_SAVED = [19..28]`) are all allocatable locals, so one more reserved
  register is one fewer local per function in every function on the path.
* **A word in `__DATA`** — the natural home, and it is blocked by exactly the
  thing `formal/model.py`'s `initialization_is_lazy` already solved for the
  global-initialisation flag: **a dylib has no entry stub**
  (`emit_startup=False`), so there is nowhere to compute the floor once per
  process. The precedent for the answer is that function's — a lazy
  check-then-fill on a flag word — and it composes with this one, because the
  floor is a single word set from the first caller's own SP.

**And the second-order thing that has to happen with it:** the floor word only
gets a segment if `__DATA` is emitted, and `formal/macho_linker.py:297` makes
that conditional on the globals blob being non-empty —
`has_globals = bool(gblob)`, which also moves the entry offset. A program with
no module globals — **which is exactly the reproducer** — has no `__DATA` at
all, so making the word exist means making the segment unconditional, which
moves every image on the tree. `formal/elf.py` has the same pair.

### What is deliberately NOT done, and why

None of the above is landed, and the reason is worth stating rather than
leaving as an absence: the guard cannot be validated without a full formal sweep
and the dylib suites, and getting it wrong is not a refusal — an unset floor
makes `cmp sp, x16` compare against zero, which every prologue fails, so every
image that has one exits at its first call. That is a worse failure than the
segfault and it is silent. Whoever lands this should do it in this order:

1. the `__DATA` segment unconditional, with the floor word in it, and **no guard
   emitted yet** — that half is measurable on its own (every image still builds
   and runs, and the sweep's verdicts must not move), and it is the half with no
   way to produce the catastrophic failure above;
2. the floor STORE in the executable's entry stub;
3. the store in the dylib path, lazily, per `initialization_is_lazy`;
4. **then** the compare, in both backends.

Steps 1-3 are all observable as "the word is written and nothing else changed".
Step 4 is the one that can take an image down, and it is the one the sweep is
for.

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
   **SUPERSEDED — see §0.1. x86-64 does not size from need either** (its
   container window is a fixed 16 KiB too), and both directions of "make them
   agree" regress something: shrinking arm64's window is a static bound that has
   to mirror every blob-allocating site, and growing x86-64's moves the ceiling
   from ~450 to ~61. There is no cheap form of this option.
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
