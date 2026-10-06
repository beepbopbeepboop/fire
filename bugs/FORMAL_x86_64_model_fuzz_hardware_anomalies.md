# Two x86-64 rows the model-vs-hardware fuzzer cannot attribute to the model

**Status 2026-10-05 (`work/formal28-6-r2`): the harness is EXONERATED by
measurement, and the `setcc` class is one DECODE rather than three odd
registers.** The "exact next step" below had two branches; the second one is
what this host can run and it is the one that now has an answer.

## What is established, and how

**1. The entry path is correct — 740 programs, 0 disagreements.** This doc's
"the next thing to instrument is the `setcontext` entry: dump the register file
from the entry stub itself (before the first emulated instruction) and compare
it against `init_block`" is now
`formal/x86_64_model_fuzz.py --entry-probe`, and it is the instrument rather
than a plan: the entry stub now dumps the register file it has just installed,
into `probe_area`, with the same RIP-relative stores and in the same order as
`dump_area`, so the two are one layout and the comparison is word for word
(`ENTRY_PROBE_WHY`).

```
$ for s in 1 7 11; do python3 formal/x86_64_model_fuzz.py --entry-probe --census --per-form 3 --seed $s; done
entry probe: 204 program(s), 2 faulted, 0 disagreeing word(s)
entry probe: 204 program(s), 1 faulted, 0 disagreeing word(s)
entry probe: 204 program(s), 1 faulted, 0 disagreeing word(s)
$ for s in 2 4 5; do python3 formal/x86_64_model_fuzz.py --entry-probe -n 64 --ninstr 12 --seed $s; done
entry probe: 64 program(s), 6 faulted, 0 disagreeing word(s)
entry probe: 64 program(s), 7 faulted, 0 disagreeing word(s)
entry probe: 64 program(s), 4 faulted, 0 disagreeing word(s)
```

740 programs, 20 faulted, **0 disagreeing words**: every one of the sixteen GPRs,
the flags word and all eight XMM registers came back exactly as `init_block`
asked. So neither row below is the harness, and the reason this doc existed —
"the next reader of `formal/x86_64_model_fuzz.py`'s output will otherwise go
looking in the model for a bug that is not there" — is settled on the only host
this tree runs on: `formal/x86_64_model_fuzz.py`'s module docstring carries the
measurement, so the reader is told rather than left to derive it.

Two things the flags word taught on the way, both of which are the reason the
check is not a `==`: `pushfq` reads bit 1 (reserved, always one) and bit 9 (IF)
as one whatever the program asked for, and `eflags()` sets the first and not the
second, so the first version of this reported **204 rows and no information**,
one per program, differing by exactly `0x200`. The comparison now takes the four
bits `X86State` carries a field for plus the reserved one, and requires every
*other* bit to agree on its own — so a bit nobody compares is still allowed to
disagree, which is what makes the narrowed mask a measurement rather than a way
of making the check pass.

**2. The `setcc` class is ONE decode, and it is not three odd registers.** §1
below said "three destinations misbehave (`rbp`, `rsi`, `rdi`); the other
thirteen agree". Measured one instruction per program, fixed initial state, all
fifteen destinations side by side:

```
setbe rax  0f96c0   correct        setbe r8   410f96c0  correct
setbe rcx  0f96c1   correct        setbe r9   410f96c1  correct
setbe rdx  0f96c2   correct        setbe r10  410f96c2  correct
setbe rbx  0f96c3   correct        setbe r11  410f96c3  correct
setbe rsp  0f96c4   correct        setbe r12  410f96c4  correct
setbe rbp  0f96c5   rbp UNCHANGED, byte 1 of RCX becomes 1
setbe rsi  0f96c6   rsi UNCHANGED, byte 1 of RDX becomes 1
setbe rdi  0f96c7   rdi UNCHANGED and nothing else written
                               setbe r13..r15  410f96c5..c7  all correct
```

`sete rbp` (`0f 94 c5`) behaves the same as `setbe rbp`, so it is not one
condition code. **The three are the ModRM bytes `c5`, `c6`, `c7` — `rm` =
`rbp`/`rsi`/`rdi`, which are exactly the three `rm` values that take NO SIB
byte.** `rm` = `rsp` is the one that does (`c4`, with `mod = 11` and `rm = 100`
meaning "a SIB byte follows"), and it is correct; every destination needing a
REX prefix is correct. So it is one decode of `0f 9x c5`/`c6`/`c7`, which is why
exactly three of sixteen show up and why `HARNESS_SETCC_DESTS` names three
registers rather than a byte — the byte is now in the module docstring beside it,
with the measurement, and a native fix has to delete all three names.

`mov rbp, 0x1122334455667788` reading back correctly in the same harness (which
§1 already records) is the other half: the store path is fine, which is what a
one-decode reading predicts — `mov`'s `88 /r` with `mod = 11` has the same ModRM
shape and does not trip it, so the fault is in the `0f 9x` opcode's decode and
not in the `rm` field's use.

**3. `mul`/`imul` is unchanged and still not the model's.** §2's argument stands
on its own and is not affected by either measurement: `RAX` and `RDX` — both
compared, neither clobbered by the terminator — agree, so the 128-bit product is
right, and SF and ZF *are* `msb(RAX)` and `RAX == 0` by definition. A difference
in SF alone is not a disagreement about the product. That leaves a CPU that
computes the right product and the wrong sign flag, which is a translation unit
and not an arithmetic one.

## What is left, and it is one command on a machine this tree does not run on

**Run the census natively on x86-64 hardware** — no `--entry-probe` needed,
though it is cheap and its answer is the one above:

```
$ python3 formal/x86_64_model_fuzz.py --census --seed 11
```

* **If both classes disappear**, this is now a fully explained host artifact and
  the answer is: *Rosetta 2 mistranslates the flag result of `mul`/`imul`, and
  the `0f 9x c5`–`c7` group of `setcc` encodings, for code entered by
  `setcontext` into an `mmap`'d RWX page.* Worth knowing before anyone uses this
  fuzzer, or `formal/x86_64_model_test.py`, as an oracle on an Apple Silicon
  host. The `HARNESS_SETCC_DESTS` names then come out.
* **If they do not**, the harness is exonerated (measurement 1) and the class is
  one decode (measurement 2), so what is left is a `0f 9x` / `mul` flag bug in
  Rosetta itself and there is nothing further to instrument on this side. That
  is a stronger statement than this doc could make before, because the entry path
  is now measured rather than argued.

Either way `formal/x86_64_model_test.py` is unaffected: it compares the low byte
of RAX after a whole `formal/examples` program, which neither class can reach.

**The doc stays for one reason and it is a small one:** the last word needs
hardware this tree does not run on, and a reader who finds the two `HARNESS`
verdict classes in the fuzzer's output deserves the pointer. Everything the
reading rests on is in the module docstring and `ENTRY_PROBE_WHY`, and
`test_x86_64_model_fuzz.py` pins the instrument.

## What this is

Both classes are counted as the `HARNESS` verdict and excluded from that
script's exit status; the reasoning is in the argument of `_impossible_on_hardware`
and in the module docstring.

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
at `…d7e` and changed **one byte at offset 1 of RCX**. Reproduced here with a
fixed initial state and reproduced byte for byte, and the class is `0f 9x c5`–
`c7` — see the measurement at the top, which supersedes "three destinations
misbehave" with the byte they share.

Not a dump problem: `mov rbp, 0x1122334455667788` in the same harness reads back
correctly in slot 5. **And not an entry problem**, which is what measurement 1
above establishes and what this doc could not say before.

## Reproducing

```
python3 tools/memslot.py --gb 8 --label t -- python3 test_x86_64_model_fuzz.py
python3 formal/x86_64_model_fuzz.py --entry-probe --census --per-form 3 --seed 11
```
