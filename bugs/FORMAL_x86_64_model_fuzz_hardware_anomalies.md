# Two x86-64 rows the model-vs-hardware fuzzer cannot attribute to the model

**Status**: open. Reproducible, measured, and NOT a `lib/X86.lean` defect as far
as can be established here — which is the point of filing it, because the next
reader of `formal/x86_64_model_fuzz.py`'s output will otherwise go looking in the
model for a bug that is not there.

Found by `formal/x86_64_model_fuzz.py --census --seed 11`, on this host, with
the hardware half running natively under Rosetta 2 (`arch -x86_64`). Both classes
are counted as the `HARNESS` verdict and excluded from that script's exit
status; the reasoning is in the argument of `_impossible_on_hardware` and in the
module docstring.

## 1. `mul` / `imul` and nothing but the flags

```
  WRONG  (1 instruction)
    mul RAX
    bytes: 48f7e0
    sf hw=0x0 model=0x1
    init: rax=0xbf0cb98cd5588737 ... rflags=0x42
    hw:   rax=0xbd35d1c6c33b0dd1 rdx=0x8e93fd82120af3e4 flags=0x0a03
```

`RAX` and `RDX` — both compared by the fuzzer, and neither clobbered by the
terminator — **agree**. So the 128-bit product is right, and SF and ZF are by
definition `msb(RAX)` and `RAX == 0`. A difference in SF alone is therefore not
a disagreement about the product, and there is nothing in the model left to
change.

Measured directly, at five different initial flag values (`0x0002`, `0x0042`,
`0x0082`, `0x0003`, `0x0802`), all giving `flags=0x0a03` — SF clear, CF and OF
set (CF/OF correct: the product does not fit) — for RAX =
0xbf0cb98cd5588737, whose low word 0xbd35d1c6c33b0dd1 has bit 63 set.

Not `mul`/`imul`-specific in the harness: `neg`, `add`, `sub`, `xor`, `and` and
every shift set SF correctly on the same host, through the same stub, in the
same batches.

## 2. `setcc` into RBP, RSI or RDI

```
  WRONG  (1 instruction)
    setbe RDI
    bytes: 0f96c7
    rdi hw=0xb5beaf138f969d7e model=0xb5beaf138f969d01
```

`0f 96 c7` is `setbe dil` in long mode: one byte of RDI. The hardware left RDI
at `…d7e` and changed **one byte at offset 1 of RCX** — which is `sete ch`, the
**32-bit** decoding of `0f 94 c5`-shaped bytes. Three destinations misbehave
(`rbp`, `rsi`, `rdi`); the other thirteen agree, including `r8`..`r15`, which
need a REX byte and so cannot be read as 32-bit at all.

Not a dump problem: `mov rbp, 0x1122334455667788` in the same harness reads back
correctly in slot 5, and the entry stub's disassembly shows
`movq 0x30(%rbx), %rsi` / `movq 0x28(%rbx), %rbp` / `movq 0x38(%rbx), %rdi`
loading the block at the right offsets. Reproduces with a single-program
harness, so it is not a batch-indexing effect.

## Exact next step

Run the same programs **not under Rosetta** — natively on an x86-64 machine, or
in a Linux x86-64 VM — and record whether both classes disappear.

* If they do, the harness is fine and the answer is "Rosetta 2 mistranslates
  `mul`/`imul` flag-setting and the 32-bit-register destinations of `setcc` for
  code entered by `setcontext` into an `mmap`'d RWX page". That is worth knowing
  before anyone uses this fuzzer, or `formal/x86_64_model_test.py`, as an oracle
  on an Apple Silicon host.
* If they do not, the harness has a real bug and the next thing to instrument is
  the `setcontext` entry: dump the register file from the entry stub itself
  (before the first emulated instruction) and compare it against
  `init_block`, which is the one step of the path this file's evidence does not
  cover.

`formal/x86_64_model_test.py` is unaffected either way — it compares the low
byte of RAX after a whole `formal/examples` program, which neither class can
reach.
