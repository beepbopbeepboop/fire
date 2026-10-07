#!/usr/bin/env python3
"""Does `lib/X86.lean` agree with an x86-64 CPU, on RANDOM programs?

`formal/x86_64_model_test.py` compares the model against the hardware over 43
hand-written `formal/examples/*.mojo`, and it compares ONE number: the low byte
of RAX. That is a real check and it is not a weak one — it is the only thing
that can catch a model which typechecks and computes the wrong number — but it
has two properties that make it unable to see a whole class of defect:

  * **the programs are the compiler's programs.** Every example is straight-line
    arithmetic on `formal/examples/*.mojo`'s subject matter, so a register pair,
    an immediate and a memory displacement that no example happens to use are
    untested. A wrong decode of `REX.R` on a `mov` whose destination is `r12` is
    invisible until a program uses it.
  * **one number is compared.** A step that puts the wrong value in RDX, or the
    wrong value in CF, or the wrong value at `[r14+8]`, still produces the right
    RAX as long as nothing later reads it back. OF is the extreme case: nothing
    this backend emits reads OF except `setcc o`/`jcc o`, so a model that never
    set it at all would pass 43 examples.

This file closes both gaps. It builds random instruction sequences **out of the
encoders in `formal/x86_64.py`** — so every byte executed is a byte the backend
can emit — runs them natively on the CPU under Rosetta, dumps all 16 GPRs, the
four flags `X86State` actually has a field for, all 8 XMM registers and a
128-byte memory window, and runs the same bytes through `x86_exec_exit` with the
same initial state. Every one of those fields is compared.

## The two halves, and why they cannot be one program

The hardware half needs an address the model also knows, which means the
emulated code has to live at a FIXED address; the model half needs the harness's
dump-stub address, which is wherever the loader put it. So this runs in two
phases: the native harness first (it prints `STUB <addr>`, its own dump
routine's address), then one Lean file per batch with that address as the exit
pc. One `#eval!` per program, all of them in one `lean` process — see
`formal/lean.py::run_lean` for why that is the only launcher.

The harness is C, compiled `clang -arch x86_64` and run `arch -x86_64`, because
"run the bytes on a CPU" is the one thing a C compiler is a better tool for than
a Python one. It enters the emulated code with `setcontext` (so the initial
register file and EFLAGS are whatever the fuzz case asked for, not whatever the
previous program left) and leaves it through a dump stub that is part of the
HARNESS image, not the emulated region — see `HARNESS_C` for why copying the
stub into the region does not work.

## What is deliberately NOT in the instruction pool, and why

  * `ret`, `call`, `leave`, and any branch to a target that is not the next
    instruction. A program that branches anywhere but forward-to-the-stub leaves
    the model and the CPU in genuinely different places, which is a reportable
    divergence but not a LOCALISED one. `encode_jcc_rel8(cc, 0)` is in the pool
    and branches to itself's own next byte, so all fourteen modelled conditions
    are still evaluated against random flags at zero control-flow risk.
  * condition codes 10 and 11 (`p`/`np`). `X86State` has no `pf` field and
    `x86_cond` approximates both with ZF, which `lib/X86.lean` states where it is
    paid. No `encode_*` in `formal/x86_64.py` emits them, so there is no
    correctness obligation to compare, and including them would produce 2
    permanent "failures" per program that say nothing.
  * `cmov`. No `encode_*` emits it and `x86_step` does not decode it, so there
    is no model to disagree with.
  * rotates (`rol`/`ror`). `encode_shift_r64_imm8` maps `<<`, `>>` and
    `>>signed` onto digits 4, 5 and 7 only, so there is no encoder to fuzz.
  * `div`/`idiv` by a register whose value the program did not just set, because
    a zero divisor and a quotient that does not fit are both `#DE` on hardware
    and `none` (or a silently truncated answer) in the model. The pool sets the
    divisor from a nonzero immediate immediately before the divide, so the
    divisor is never zero; an overflow can still fault, and the harness's
    `SIGFPE` handler turns that into a `FAULT` row rather than a crash.

## There is no `HARNESS` verdict any more, and why there used to be

Until 2026-10-07 this file carried a third verdict, `HARNESS`, for a
disagreement "no x86-64 CPU can produce" — two classes, both measured on this
host under Rosetta 2. **Both were wrong, and the defect was in this tree rather
than in Rosetta**, which is why they are gone rather than kept:

  * **`setcc` into RBP, RSI or RDI.** The bytes this file executed were
    `0f 96 c5`/`c6`/`c7`, and the CPU is RIGHT about them: with no REX prefix
    those ModRM bytes name AH/CH/DH/BH — the HIGH bytes of RAX/RCX/RDX/RBX — so
    `0f 96 c5` is `setbe ch`, not `setbe bpl`. `formal/x86_64.py::_setcc` emitted
    the prefix for r8-r15 and omitted it for SPL/BPL/SIL/DIL (values 4-7), whose
    8-bit encodings exist only WITH a prefix present. The fix is
    `_byte_rex_required`, and `encode_and_r8_r8`/`encode_or_r8_r8` had the same
    omission for their 8-bit operands — which is why the byte-wise ALU rows were
    "deliberately not in the pool"; they are in it now.

  * **`mul`/`imul` flags.** `RAX`/`RDX` (the product) agree; only SF and ZF
    differed. Both are UNDEFINED by Intel SDM Vol. 2 after `MUL`/`IMUL` ("The
    SF, ZF, AF, and PF flags are undefined"), so the model's value and Rosetta's
    are both legitimate and comparing them was the bug. That is
    `undefined_flags`' job, not a verdict class: it now skips exactly SF and ZF
    when the program's last flag-writing instruction is a multiply, and keeps
    the CF/OF comparison the instruction DOES define.

Two further classes the doc named as hardware anomalies were measured and are
also absent: the "`imul` returns the wrong product" row does not reproduce (512
random two-operand `imul`s through this harness, 0 wrong products), and the
"`idiv` is not a 128-bit divide" row was INVERTED — the CPU and exact arithmetic
agree, and `lib/X86.lean`'s `x86_idiv128` was the wrong one, reconstructing the
dividend from a SIGNED low word. `formal/x86_64_model_coverage_test.py`'s divide
table is the regression for it.

The harness's own entry path is exonerated, by measurement rather than by
argument (`ENTRY_PROBE_WHY`, and `--entry-probe`): five runs of this module's
generators on this host (Apple silicon, `arch -x86_64`), 740 programs, 14
faulted, **0 disagreeing words**.

So a differing field is `WRONG` again, with one principled exception: a flag
`undefined_flags` names is not compared, because the architecture promises
nothing about it.

## Reading a run

    AGREE   every compared field matched
    WRONG   the model produced a state and a field differed — a model bug
    NORUN   `x86_step` returned `none` on a form `formal/x86_64.py` can emit —
            also a model bug, and a different one: it is a hole, not a lie
    FAULT   hardware took `#DE`; no comparison is possible and none is claimed

`--minimise` (on by default) shrinks each WRONG/NORUN row to a PREFIX of the
offending program: every prefix at once in one batch, which for a twelve-
instruction program is four runs collapsed into one. The reduced program is
printed with its bytes and its disassembly-by-encoder-name, and it is what
belongs in a regression test — **so it has to be a program that still fails,
and it was not one**: `Program.prefix` kept its parent's `index`, which is the
program's NAME in the generated Lean file (`code_N` / `init_N`) and the key
`run_model` answers under. Lean rejected the second `def code_N` and still
evaluated every `#eval!` against the first, so each prefix's hardware dump was
compared with the FULL program's model result and the "reduced" program agreed
when it was run on its own. `prefix` now gives a derived program its own index,
`lean_source` refuses two programs with one, and `run_model` treats a Lean error
as fatal rather than reading a partly-elaborated file's answers as verdicts.

Run: python3 formal/x86_64_model_fuzz.py [-n N] [--seed S] [--batch B] [-v]
Exit: 0 iff there is no WRONG and no NORUN.

**The arm64 sibling, and why this is a second file.**
`tools/formal_model_fuzz.py` asks the same question of `lib/ProofLib.lean`'s
`arm64_step`, and the two were measured rather than assumed to be one program
wearing two hats: of this file's 747 non-comment source lines, **8 are
byte-identical to a line in that one** (1.1%), and they are `memset`,
`printf` and two Lean `match` arms. Everything that decides a verdict is
different — the pool is `formal/x86_64.py`'s encoders rather than
`formal/arm64.py`'s, the address model is one `MAP_FIXED` region rather than a
translated window, the verdict set has `FAULT` and `NORUN` where that one has
`ENC-MISMATCH` and `NOSTEP`, and the two Lean halves are launched differently.
The shareable part is an argument parser and a reporting loop, and
`tools/tu_grind.py` is already that; neither harness carries its own copy of the
scratch-directory policy. `tools/formal_model_fuzz.py`'s docstring says the same
thing from its side, so neither file is the one you have to read to know there
are two.
"""

import argparse
import os
import random
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import formal.lean as L                                     # noqa: E402
import formal.x86_64 as X                                   # noqa: E402
import formal.x86_64_decode as D                            # noqa: E402

R = X.Reg

# ── the emulated machine's layout ───────────────────────────────────────
#
# Every address is FIXED, because the model addresses code absolutely and the
# comparison is only meaningful if both halves agree on where the bytes live.
# `MAP_FIXED` at 16 GB is above the arm64 low-mmap region (4 GB) and below the
# dyld shared cache (0x7fff_0000_0000), so nothing the loader placed is at
# risk; the harness aborts if the mapping did not land where it asked.

REGION_BASE = 0x0000000400000000
REGION_SIZE = 1 << 22
CODE_OFF = 0x000000
STACK_OFF = 0x001000
STACK_SIZE = 1 << 16
DATA_OFF = 0x020000
DATA_N = 128
"""The compared memory window, in bytes. Every memory operand the pool emits
addresses `[membase + disp]` with `|disp| <= DATA_N/2`, so every load and store
lands inside the window and inside it ALONE — a byte outside would be compared
against the model's `0` for an address the CPU never had."""

#: Region-RELATIVE. The absolute value (`REGION_BASE + STACK_TOP`) is what both
#: halves are given, and it has to be absolute in the harness too: a
#: region-relative RSP is an address near zero, which faults on the first
#: instruction that touches the stack and leaves the fuzzer with a program that
#: never ran.
STACK_TOP = STACK_OFF + STACK_SIZE - 16
STACK_TOP_ABS = REGION_BASE + STACK_TOP

MEMBASE = DATA_OFF + DATA_N // 2
"""Where both reserved memory-base registers point, RELATIVE to the region.
The window is centred on it so a displacement in `[-64, 64 - size]` keeps an
access of `size` bytes inside — `_disp` draws from exactly that range, and the
`size` half is load-bearing: a flat `[-64, 64)` let an 8-byte load at `disp = 57`
reach offset 128, one past the window, where the model reads 0 and the harness
reads a byte an earlier program in the batch left there.

The absolute value is `REGION_BASE + MEMBASE`, and both halves need that one:
the harness puts it in RDX's sibling registers and Lean puts it in `membase`.
Handing the harness the relative one is a `SIGSEGV` on the first memory
operand of the first program, which is why the two constants are named apart
rather than one being quietly assumed absolute."""
MEMBASE_ABS = REGION_BASE + MEMBASE

MAX_CODE = 4096

#: The registers the fuzz pool may use as a general operand.
#:
#:   * `RSP` is excluded because it is the emulated stack pointer, and the
#:     terminator's `mov [rsp], rbx` has to be able to write wherever the program
#:     left it.
#:   * `RBX` is excluded because the TERMINATOR CLOBBERS IT, and a register the
#:     harness overwrites is a register the comparison cannot use. It used to be
#:     `RAX` that the terminator clobbered, and the cost was that `imul`'s
#:     result -- which lands in RAX -- was invisible: `mul`/`imul` disagreed on
#:     SF with no visible difference in any register, and the two facts together
#:     are what a wrong `lo` looks like. Twelve of the sixteen remain, which still
#:     covers `REX.B` on both sides of every field it extends.
#:   * `R13`/`R14` are excluded because they are the two memory bases and must
#:     keep pointing into the compared window.
GENERAL = tuple(r for r in R if r not in (R.RSP, R.RBX, R.R13, R.R14))

#: Registers the harness's own code overwrites, so a difference in one of them
#: says nothing about the program. One, and it is named rather than inferred.
TERMINATOR_CLOBBERS = ("rbx",)
MEM_BASES = (R.R13, R.R14)
LOW8 = tuple(r for r in R if r.value < 8)

MASK64 = (1 << 64) - 1

#: EFLAGS bit positions for the four flags `X86State` carries a field for. PF
#: and AF are deliberately absent: `X86State` has no field for either, so a
#: comparison against them would be a comparison the model cannot pass.
EF_CF, EF_ZF, EF_SF, EF_OF = 0x001, 0x040, 0x080, 0x800

#: Bounds for the ONE Lean run per batch. Bigger than a proof check because it
#: is: `n` `#eval!` goals each executing a whole instruction sequence through
#: `x86_exec_exit`, in one process. Sized against `formal/lean.py`'s recorded
#: measurements rather than guessed.
FUZZ_WALL_S = 1800.0
FUZZ_CPU_S = 1800.0

#: `movabs rbx, stub` ; `mov [rsp], rbx` ; `ret` — the harness dump stub's
#: address planted at whatever RSP the fuzzed program left behind, then `ret`
#: through it, so the CPU lands in the stub and `x86_exec_exit` (whose `exit` pc
#: IS the stub address) stops on the same step. All three are forms
#: `formal/x86_64.py` emits and `x86_step` decodes, which is the property that
#: makes this work; see `TERMINATOR_WHY` below.
TERMINATOR_TEXT = "movabs rbx, <stub> ; mov [rsp], rbx ; ret"
TERMINATOR_LEN = len(X.encode_mov_r64_imm64(R.RBX, 0)) \
    + len(X.encode_mov_rm64_r64(R.RSP, 0, R.RBX)) + len(X.encode_ret())
TERMINATOR_IMM_OFF = 2
"""Where the stub address sits inside the terminator: two bytes into the
`REX.W B8+r` encoding, which is a `mov r64, imm64` and therefore carries all
eight bytes. The harness patches here at run time, because the stub's address is
wherever the loader put it and the byte table is built before the loader runs."""


def terminator_bytes(stub):
    return (X.encode_mov_r64_imm64(R.RBX, stub)
            + X.encode_mov_rm64_r64(R.RSP, 0, R.RBX) + X.encode_ret())


#: The seventeen stores, in `dump_area`'s offsets and order so the two dumps are
#: one layout and can be compared word for word. `%rax` is stored BEFORE the
#: `pushfq`/`popq` pair, because that pair clobbers it — and at this point in
#: the stub `%rax` already holds register 0, loaded by `movq 0(%rbx), %rax`.
#: `%rbx` is register 3 by now (`movq 24(%rbx), %rbx`), which is why every store
#: is RIP-relative and no base register is named.
def _asm_line(text):
    """One `__asm__` string line, in the form `HARNESS_C` writes its own.

    The probe goes INSIDE that string literal — it is assembler, spliced between
    two of the stub's instructions — so it has to arrive escaped, and getting
    that wrong is a `missing terminating '"' character` from clang rather than
    anything to do with the probe.
    """
    return '"%s\\n"' % text


_ENTRY_PROBE_ASM = "".join(
    _asm_line("  movq %%%s, _probe_area+%d(%%rip)" % (r, off))
    for r, off in (("rax", 0), ("rcx", 8), ("rdx", 16), ("rbx", 24),
                   ("rsp", 32), ("rbp", 40), ("rsi", 48), ("rdi", 56),
                   ("r8", 64), ("r9", 72), ("r10", 80), ("r11", 88),
                   ("r12", 96), ("r13", 104), ("r14", 112), ("r15", 120))
) + (_asm_line("  pushfq")
     + _asm_line("  popq %rax")
     + _asm_line("  movq %rax, _probe_area+128(%rip)")) + "".join(
    _asm_line("  movq %%xmm%d, _probe_area+%d(%%rip)" % (i, 136 + 8 * i))
    for i in range(8))


ENTRY_PROBE_WHY = """\
The entry stub is the ONE step of the harness nothing has ever read back, and it
is the step any "the CPU disagrees on every field" reading would have to be
explained through: the stub
loads the register file out of `init_block` with real `mov` instructions (note 1
at the top of this file), so if those loads did not land, every register would
be wrong and the model would disagree with the hardware on every field of every
program -- which is not what a two-row census shows.

So the probe is the register file as the CPU has it AT THE MOMENT the entry
stub jumps, dumped by the stub itself into `probe_area` with the same
RIP-relative stores and in the same order as `dump_area`, so the two are one
layout. It is compiled in only when asked for (`probe=True`, `--entry-probe`):
seventeen stores on a path that runs once per program is not a cost worth paying
for a measurement nobody reads, and the default harness text has to stay what it
was.

What it settled, and the reason it is worth keeping: the `setcc` class this
file used to call a hardware anomaly was the CPU being RIGHT about `0f 96 c5`
(`setbe ch`, not `setbe bpl`, because the encoder omitted the REX prefix). The
probe is what ruled the entry file out as the cause, and it is the instrument to
reach for first whenever a field-level disagreement looks like it might be the
harness rather than the model.
"""


TERMINATOR_WHY = """\
Three terminators were wrong before this one, and the two that failed are the
instructive ones.

A `jmp rel32` into the stub cannot work at all: the harness's own image loads at
0x100000000+ on this platform, the emulated region is mmap'd wherever the fuzzer
asked for it, and the displacement between them does not fit in 32 bits, so
`(int32_t)(stub - code_end)` truncates and the program jumps to an address
derived from the truncated value -- a fault on the first instruction, RSP still
untouched, which reads as "setcontext into mapped code does not work under
Rosetta" rather than as an arithmetic slip.

A `ret` through a slot already holding the stub (the convention
`formal/x86_64_model_test.py` uses, with the slot at the initial RSP) works right
up until a fuzzed program does `pop` then `push`: the pop RAISES RSP by eight,
so the following push writes the return slot, and the final `ret` pops the
program's own value. Restoring RSP first, with `mov rsp, rax` before the `ret`,
fixes that and breaks something else -- `resume` is then entered through the
stub with RSP inside the emulated stack, and a program that popped more than it
pushed puts it low enough that `printf` walks off the region.

So the terminator writes the return address where it wants it, AT the RSP the
program left: `mov [rsp], rax` is `REX.W 89 /r` with mod=0 and rm=4, i.e. a SIB
byte, which `x86_mem_addr` reads and `x86_step_rex` advances past -- the same
shape as the spilled-argument stores the backend emits. Nothing about it depends
on where the program left RSP, and the model writes the same eight bytes at the
same address, so the `ret` reads the same value on both sides.
"""




# ── the instruction pool ────────────────────────────────────────────────
#
# Each entry is (name, weight, builder). The builder takes the rng and returns
# the encoder's bytes, so every byte this file can execute came out of
# `formal/x86_64.py` — the property that makes a disagreement a MODEL bug rather
# than a question about whether the harness invented an encoding.

def _imm32(r):
    return r.choice([0, 1, -1, 2, -2, 255, 256, -256, 0x7FFFFFFF,
                     -0x80000000, 0x55555555, -0x55555555, 0x0F0F0F0F,
                     r.randrange(-2**31, 2**31)])


def _imm8(r):
    return r.choice([0, 1, -1, 2, -2, 7, 31, 32, 33, 63, 64, 65, -128, 127,
                     r.randrange(-128, 128)])


def _shift_count(r):
    """A shift count, as the UNSIGNED byte `encode_shift_r64_imm8` asserts on.

    0 and 64..255 are in the pool deliberately. A count of 0 leaves every flag
    UNTOUCHED on hardware, which is not the same as computing a shift by zero
    and setting flags from the result; and a count at or above the operand width
    is a different case again (the count is masked to six bits, so 64 and 0
    agree). Both are the "undefined flag" shapes a straight-line fuzzer has to
    be told about explicitly, because a random count in 1..63 never reaches
    them."""
    return r.choice([0, 1, 2, 7, 31, 32, 33, 63, 64, 65, 127, 128, 200, 255,
                     r.randrange(0, 256)])


def _imm64(r):
    return r.choice([0, 1, MASK64, 1 << 63, (1 << 63) - 1, (1 << 31) - 1,
                     0x5555555555555555, 0xAAAAAAAAAAAAAAAA,
                     0x8080808080808080, r.getrandbits(64)])


def _disp(r, size):
    """A displacement that keeps an access of `size` bytes inside the window.

    The window is centred on `MEMBASE` (`DATA_N // 2` bytes in), so an operand
    at `[base + disp]` covers window offsets `DATA_N//2 + disp .. + size`.  A
    displacement drawn WITHOUT regard to the size can reach past the window:
    `disp = 57` with an 8-byte load covers offsets 121..128, and offset 128 is
    outside a 128-byte window.  The model reads 0 there — its `mem_N` returns 0
    for every address past `dataN` — while the harness reads whatever the region
    holds, which for a program after the first in a batch is a byte an earlier
    program's out-of-window STORE left behind (the per-program `memcpy` resets
    only `DATA_N` bytes).  That is a disagreement about an address neither half
    should have touched, and it made a verdict depend on BATCH ORDER: measured
    on seed 3, `mov RSI, [R13+57]` reported `rsi hw=0xf6d0…02 model=0xd0…02`
    in a batch and AGREED when the same program ran alone.  The bound is
    therefore size-aware.
    """
    return r.randrange(-DATA_N // 2, DATA_N // 2 - size + 1)


def _reg(r, pool):
    return r.choice(pool)


def _mem(r, size):
    return _reg(r, MEM_BASES), _disp(r, size)


_ALU_RR = (("add", X.encode_add_r64_r64, 4), ("or", X.encode_or_r64_r64, 2),
           ("and", X.encode_and_r64_r64, 2), ("sub", X.encode_sub_r64_r64, 4),
           ("xor", X.encode_xor_r64_r64, 3), ("cmp", X.encode_cmp_r64_r64, 5),
           ("test", X.encode_test_r64_r64, 3))
_ALU_RI32 = (("add", X.encode_add_r64_imm32), ("or", X.encode_or_r64_imm32),
             ("and", X.encode_and_r64_imm32), ("sub", X.encode_sub_r64_imm32),
             ("xor", X.encode_xor_r64_imm32), ("cmp", X.encode_cmp_r64_imm32))
_ALU_RI8 = (("add", X.encode_add_r64_imm8), ("and", X.encode_and_r64_imm8),
            ("sub", X.encode_sub_r64_imm8), ("cmp", X.encode_cmp_r64_imm8))
_SHIFTS = ("<<", ">>", ">>signed")
_SETCC = tuple((nm, getattr(X, "encode_set" + nm))
               for nm in ("e", "ne", "l", "le", "g", "ge",
                          "b", "be", "a", "ae"))
#: The condition-code nibbles the model evaluates exactly. 10 (`p`) and 11
#: (`np`) are excluded: see the module docstring.
_JCC_CC = tuple(cc for cc in range(16) if cc not in (10, 11))


def pool():
    """[(name, weight, builder)] — the instruction pool, with each builder
    returning `(instruction text, bytes)` so a report can name the instruction
    rather than hex."""
    out = []

    def add(weight, name):
        def deco(fn):
            out.append((name, weight, fn))
            return fn
        return deco

    # mov, register and immediate
    @add(6, "mov_r64_imm64")
    def _(r):
        reg = _reg(r, GENERAL)
        v = _imm64(r)
        return "movabs %s, 0x%x" % (reg.name, v), X.encode_mov_r64_imm64(reg, v)

    @add(6, "mov_r64_imm32")
    def _(r):
        reg = _reg(r, GENERAL)
        v = _imm32(r)
        return "mov %s, %d" % (reg.name, v), X.encode_mov_r64_imm32(reg, v)

    @add(6, "mov_r64_r64")
    def _(r):
        d, s = _reg(r, GENERAL), _reg(r, GENERAL)
        return "mov %s, %s" % (d.name, s.name), X.encode_mov_r64_r64(d, s)

    @add(4, "mov_r32_r32")
    def _(r):
        d, s = _reg(r, GENERAL), _reg(r, GENERAL)
        return "mov %s, %s" % (d.name, s.name), X.encode_mov_r32_r32(d, s)

    # mov, memory. The byte and halfword STORES are in the pool on purpose: they
    # are the partial-register writes, and they are the two forms `x86_step` has
    # no opcode byte for at all (0x88 and 66-prefixed 0x89).
    @add(5, "mov_r64_rm64")
    def _(r):
        d, (b, off) = _reg(r, GENERAL), _mem(r, 8)
        return "mov %s, [%s%+d]" % (d.name, b.name, off), \
            X.encode_mov_r64_rm64(d, b, off)

    @add(4, "mov_r32_rm32")
    def _(r):
        d, (b, off) = _reg(r, GENERAL), _mem(r, 4)
        return "mov %s, [%s%+d]" % (d.name, b.name, off), \
            X.encode_mov_r32_rm32(d, b, off)

    @add(4, "mov_rm64_r64")
    def _(r):
        (b, off), s = _mem(r, 8), _reg(r, GENERAL)
        return "mov [%s%+d], %s" % (b.name, off, s.name), \
            X.encode_mov_rm64_r64(b, off, s)

    @add(3, "mov_rm32_r32")
    def _(r):
        (b, off), s = _mem(r, 4), _reg(r, GENERAL)
        return "mov [%s%+d], %s" % (b.name, off, s.name), \
            X.encode_mov_rm32_r32(b, off, s)

    @add(3, "mov_rm8_r8")
    def _(r):
        (b, off), s = _mem(r, 1), _reg(r, GENERAL)
        return "mov [%s%+d], %s" % (b.name, off, s.name), \
            X.encode_mov_rm8_r8(b, off, s)

    @add(3, "mov_rm16_r16")
    def _(r):
        (b, off), s = _mem(r, 2), _reg(r, GENERAL)
        return "mov [%s%+d], %s" % (b.name, off, s.name), \
            X.encode_mov_rm16_r16(b, off, s)

    # widen/narrow. The LOW-8 register shapes are in the pool deliberately:
    # `movzx rax, dl` carries NO REX byte at all, so it is the one form that
    # takes the model's no-REX decoder rather than the REX one.
    @add(4, "movzx_r64_r8")
    def _(r):
        d, s = _reg(r, GENERAL), (r.choice(LOW8) if r.random() < 0.5
                                  else _reg(r, GENERAL))
        return "movzx %s, %s" % (d.name, s.name), X.encode_movzx_r64_r8(d, s)

    @add(4, "movsx_r64_r8")
    def _(r):
        d, s = _reg(r, GENERAL), (r.choice(LOW8) if r.random() < 0.5
                                  else _reg(r, GENERAL))
        return "movsx %s, %s" % (d.name, s.name), X.encode_movsx_r64_r8(d, s)

    @add(3, "movzx_r64_r16")
    def _(r):
        d, s = _reg(r, GENERAL), _reg(r, GENERAL)
        return "movzx %s, %s" % (d.name, s.name), X.encode_movzx_r64_r16(d, s)

    @add(3, "movsx_r64_r16")
    def _(r):
        d, s = _reg(r, GENERAL), _reg(r, GENERAL)
        return "movsx %s, %s" % (d.name, s.name), X.encode_movsx_r64_r16(d, s)

    @add(3, "movsxd_r64_r32")
    def _(r):
        d, s = _reg(r, GENERAL), _reg(r, GENERAL)
        return "movsxd %s, %s" % (d.name, s.name), X.encode_movsx_r64_r32(d, s)

    @add(3, "movzx_r64_rm8")
    def _(r):
        d, (b, off) = _reg(r, GENERAL), _mem(r, 1)
        return "movzx %s, [%s%+d]" % (d.name, b.name, off), \
            X.encode_movzx_r64_rm8(d, b, off)

    @add(3, "movsx_r64_rm8")
    def _(r):
        d, (b, off) = _reg(r, GENERAL), _mem(r, 1)
        return "movsx %s, [%s%+d]" % (d.name, b.name, off), \
            X.encode_movsx_r64_rm8(d, b, off)

    @add(2, "movzx_r64_rm16")
    def _(r):
        d, (b, off) = _reg(r, GENERAL), _mem(r, 2)
        return "movzx %s, [%s%+d]" % (d.name, b.name, off), \
            X.encode_movzx_r64_rm16(d, b, off)

    @add(2, "movsx_r64_rm16")
    def _(r):
        d, (b, off) = _reg(r, GENERAL), _mem(r, 2)
        return "movsx %s, [%s%+d]" % (d.name, b.name, off), \
            X.encode_movsx_r64_rm16(d, b, off)

    @add(2, "movsx_r64_rm32")
    def _(r):
        d, (b, off) = _reg(r, GENERAL), _mem(r, 4)
        return "movsxd %s, [%s%+d]" % (d.name, b.name, off), \
            X.encode_movsx_r64_rm32(d, b, off)

    @add(2, "lea_r64_rm64")
    def _(r):
        d, (b, off) = _reg(r, GENERAL), _mem(r, 0)
        return "lea %s, [%s%+d]" % (d.name, b.name, off), \
            X.encode_lea_r64_rm64(d, b, off)

    # ALU, register/register and register/immediate
    for nm, enc, w in _ALU_RR:
        def make(enc=enc, nm=nm):
            def _(r):
                d, s = _reg(r, GENERAL), _reg(r, GENERAL)
                return "%s %s, %s" % (nm, d.name, s.name), enc(d, s)
            return _
        add(w, "alu_rr:%s" % nm)(make())

    for nm, enc in _ALU_RI32:
        def make(enc=enc, nm=nm):
            def _(r):
                d, v = _reg(r, GENERAL), _imm32(r)
                return "%s %s, %d" % (nm, d.name, v), enc(d, v)
            return _
        add(3, "alu_ri32:%s" % nm)(make())

    for nm, enc in _ALU_RI8:
        def make(enc=enc, nm=nm):
            def _(r):
                d, v = _reg(r, GENERAL), _imm8(r)
                return "%s %s, %d" % (nm, d.name, v), enc(d, v)
            return _
        add(3, "alu_ri8:%s" % nm)(make())

    @add(3, "xor_edx_edx")
    def _(r):
        return "xor edx, edx", X.encode_xor_edx_edx()

    @add(3, "imul_r64_r64")
    def _(r):
        d, s = _reg(r, GENERAL), _reg(r, GENERAL)
        return "imul %s, %s" % (d.name, s.name), X.encode_imul_r64_r64(d, s)

    # group 3. `not` leaves the flags alone on hardware and so must in the
    # model; `neg` sets all four.
    @add(2, "not_r64")
    def _(r):
        g = _reg(r, GENERAL)
        return "not %s" % g.name, X.encode_not_r64(g)

    @add(2, "neg_r64")
    def _(r):
        g = _reg(r, GENERAL)
        return "neg %s" % g.name, X.encode_neg_r64(g)

    @add(2, "mul_r64")
    def _(r):
        g = _reg(r, GENERAL)
        return "mul %s" % g.name, X.encode_mul_r64(g)

    @add(2, "imul1_r64")
    def _(r):
        g = _reg(r, GENERAL)
        return "imul %s" % g.name, X.encode_imul_r64_1op(g)

    # `div`/`idiv` get their divisor from RCX, loaded from a nonzero immediate
    # immediately before, so the `#DE`-on-zero case is not what is being tested
    # here (see the module docstring). RDX is cleared for `div` and sign-extended
    # for `idiv`, which is what the backend itself emits.
    @add(2, "div_r64")
    def _(r):
        v = _imm64(r) or 1
        d = _imm64(r)
        return ("mov rcx, 0x%x" % v, X.encode_mov_r64_imm64(R.RCX, v)), \
               ("xor edx, edx", X.encode_xor_edx_edx()), \
               ("mov rdx, 0x%x" % d, X.encode_mov_r64_imm64(R.RDX, d)), \
               ("div rcx", X.encode_div_r64(R.RCX))

    @add(2, "idiv_r64")
    def _(r):
        v = _imm64(r) or 1
        return ("mov rcx, 0x%x" % v, X.encode_mov_r64_imm64(R.RCX, v)), \
               ("cqo", X.encode_cqo()), \
               ("idiv rcx", X.encode_idiv_r64(R.RCX))

    @add(1, "cqo")
    def _(r):
        return "cqo", X.encode_cqo()

    # shifts, by immediate and by CL. Count 0 and count >= 64 are both in the
    # immediate pool on purpose: hardware treats a count of 0 as "no flags
    # touched" and a 64-bit count as "flags cleared, OF undefined".
    for op in _SHIFTS:
        def make(op=op):
            def _(r):
                g, v = _reg(r, GENERAL), _shift_count(r)
                return "%s %s, %d" % (op, g.name, v), \
                    X.encode_shift_r64_imm8(op, g, v)
            return _
        add(4, "shift_imm8:%s" % op)(make())

    for op in _SHIFTS:
        def make(op=op):
            def _(r):
                g = _reg(r, GENERAL)
                return "%s %s, cl" % (op, g.name), X.encode_shift_r64_cl(op, g)
            return _
        add(3, "shift_cl:%s" % op)(make())

    # setcc over every register, not just the low eight: a setcc into `r12`
    # exercises the REX.B path through `x86_rm_write`'s `sz = 1` register case.
    for nm, enc in _SETCC:
        def make(enc=enc, nm=nm):
            def _(r):
                g = _reg(r, GENERAL)
                return "set%s %s" % (nm, g.name), enc(g)
            return _
        add(3, "setcc:%s" % nm)(make())

    # all fourteen modelled conditions, as a branch to the NEXT instruction:
    # the condition is evaluated against whatever random flags are live, and
    # control flow cannot diverge.
    @add(3, "jcc_rel8:0")
    def _(r):
        cc = r.choice(_JCC_CC)
        return "jcc rel8 cc=%d (to next)" % cc, X.encode_jcc_rel8(cc, 0)

    @add(1, "jmp_rel8:0")
    def _(r):
        return "jmp rel8 (to next)", X.encode_jmp_rel8(0)

    # The rel32 SPELLINGS of the same three control-flow forms, each a branch to
    # the next instruction, and the reason they were missing is worth recording:
    # `formal/x86_64_codegen.py` emits them past a 128-byte reach and the pool
    # drew only the rel8, so two emitted forms and a third (`call`) had no
    # model-vs-hardware case at all. `tools/formal_isa_census.py` carried all
    # three in its BACKLOG with the reason "a call cannot run in the harness's
    # straight-line stub without leaving it" -- and the harness does NOT leave:
    # the emulated region is one `MAP_FIXED` mapping and the terminator falls
    # through into the dump stub at its end, so a branch to the NEXT instruction
    # stays inside whatever the program has already put there. `call rel32 0` is
    # the interesting one: it pushes the return address and jumps five bytes on,
    # which both halves do, and the pushed word lands on the emulated stack --
    # outside the compared memory window (`DATA_OFF`, not `STACK_OFF`), so it is
    # not compared and cannot be a false disagreement.
    @add(3, "jcc_rel32:0")
    def _(r):
        cc = r.choice(_JCC_CC)
        return "jcc rel32 cc=%d (to next)" % cc, X.encode_jcc_rel32(cc, 0)

    @add(1, "jmp_rel32:0")
    def _(r):
        return "jmp rel32 (to next)", X.encode_jmp_rel32(0)

    @add(2, "call_rel32:0")
    def _(r):
        return "call rel32 (to next)", X.encode_call_rel32(0)

    # `lea dst, [rip + disp]` -- RIP-relative, and therefore the one form the
    # census put in BACKLOG "because the two engines' RIPs differ by the load
    # slide".  They do not, HERE: the harness maps its region at a FIXED address
    # with `MAP_FIXED` and the model is handed the same base, so a pc-relative
    # RESULT is the same number in both halves.  (arm64's `adrp` is the case that
    # reason fits, and it is in `HARNESS_LIMITS` for it.)
    @add(2, "lea_r64_rip")
    def _(r):
        d, disp = _reg(r, GENERAL), r.randrange(-16, 16) * 4
        return "lea %s, [rip%+d]" % (d.name, disp), X.encode_lea_r64_rip(d, disp)

    @add(2, "push_pop")
    def _(r):
        n = r.randrange(1, 5)
        text, code = [], b""
        for i in range(n):
            g = _reg(r, GENERAL)
            if r.random() < 0.5:
                text.append("push %s" % g.name)
                code += X.encode_push_r64(g)
            else:
                text.append("pop %s" % g.name)
                code += X.encode_pop_r64(g)
        return "; ".join(text), code

    @add(1, "movq_xmm")
    def _(r):
        k, g = r.randrange(8), _reg(r, GENERAL)
        return "movq xmm%d, %s" % (k, g.name), X.encode_movq_xmm_rm64(k, g)

    # ── the SSE2 scalar binary64 forms, and the hardware differential they get
    #
    # All nine are emitted by `formal/x86_64_codegen.py` and none was in this
    # pool, so `tools/formal_isa_census.py`'s FUZZ column read `no` for each and
    # the model's SSE arms (added with the decoder and the samples in the same
    # change) had no CPU to be compared against.  See
    # `bugs/FORMAL_x86_64_instruction_coverage_backlog.md`, shape 1.
    #
    # The XMM FILE is compared word for word by this harness (the entry stub
    # loads it, the dump stub stores it), and the initial values are RANDOM
    # 64-bit patterns, so the arithmetic rows exercise NaN, infinity and
    # denormal operands as well as ordinary ones.  **A NaN PAYLOAD is the one
    # place the two engines are allowed to differ**: Lean's `Float.ofBits`/
    # `toBits` normalises a signalling NaN to the canonical quiet NaN
    # (`lib/IEEE754.lean`'s `ofBits_toBits_normalises_a_nan_payload`), while the
    # CPU propagates the first operand's payload.  A row whose only difference
    # is a quiet NaN's payload bits is the model being faithful to IEEE's VALUE
    # and not to the payload, which is stated there and is not a model bug.
    _SSE_FP = {"addsd": X.encode_addsd_xmm, "subsd": X.encode_subsd_xmm,
               "mulsd": X.encode_mulsd_xmm, "divsd": X.encode_divsd_xmm}

    @add(3, "sse_fp")
    def _(r):
        op = r.choice(("addsd", "subsd", "mulsd", "divsd"))
        dst, src = r.randrange(8), r.randrange(8)
        return ("%s xmm%d, xmm%d" % (op, dst, src),
                _SSE_FP[op](dst, src))

    @add(2, "ucomisd")
    def _(r):
        dst, src = r.randrange(8), r.randrange(8)
        return ("ucomisd xmm%d, xmm%d" % (dst, src),
                X.encode_ucomisd_xmm(dst, src))

    @add(1, "xorpd")
    def _(r):
        dst, src = r.randrange(8), r.randrange(8)
        return ("xorpd xmm%d, xmm%d" % (dst, src),
                X.encode_xorpd_xmm(dst, src))

    @add(1, "movq_r64_xmm")
    def _(r):
        xmm, g = r.randrange(8), _reg(r, GENERAL)
        return ("movq %s, xmm%d" % (g.name, xmm),
                X.encode_movq_r64_xmm(g, xmm))

    @add(1, "cvtsi2sd")
    def _(r):
        xmm, g = r.randrange(8), _reg(r, GENERAL)
        return ("cvtsi2sd xmm%d, %s" % (xmm, g.name),
                X.encode_cvtsi2sd_xmm_r64(xmm, g))

    # `cvttsd2si` is the one SSE row a RANDOM XMM mostly drives OUT OF RANGE:
    # a random 64-bit pattern is a magnitude near 2^1000, and the hardware
    # answers the integer indefinite `0x8000000000000000` with the invalid flag
    # set.  `x86_cvttsd` models that, so the row is a real comparison of the
    # indefinite answer rather than a row that only ever sees ordinary values.
    @add(1, "cvttsd2si")
    def _(r):
        xmm, g = r.randrange(8), _reg(r, GENERAL)
        return ("cvttsd2si %s, xmm%d" % (g.name, xmm),
                X.encode_cvttsd2si_r64_xmm(g, xmm))

    @add(1, "nop")
    def _(r):
        return "nop", X.encode_nop()

    # The three forms that were emittable, undecodable and unmodelled until
    # 2026-10-05 and are in the pool for the same reason every other row here
    # is: a form the fuzzer never runs has no model-vs-hardware case at all.
    # None of the three branches, so each runs to the terminator like the rest.
    #
    # The scale is drawn from BOTH signs on purpose: the immediate is signed, and
    # a positive-only pool would leave the negative half of the row untested —
    # which is the half a C subscript uses.
    @add(2, "imul_imm")
    def _(r):
        dst, src = _reg(r, GENERAL), _reg(r, GENERAL)
        imm = r.choice([1, 2, 4, 8, -1, -4, -8])
        return ("imul %s, %s, %d" % (dst.name, src.name, imm),
                X.encode_imul_r64_r64_imm(dst, src, imm))

    # The BYTE-WISE `and`/`or` (`20 /r` / `08 /r`), which exist so a floating
    # `==` can read the conjunction of ZF and PF without reading the seven bytes
    # a `SETcc` left in the register.  They were undecodable and unmodelled until
    # 2026-10-05 and unFUZZABLE until 2026-10-07, because this harness disagreed
    # about an RBP operand and the disagreement was mis-attributed to the host:
    # `encode_and_r8_r8(RAX, RBP)` emitted `20 e8` with no REX prefix, which is
    # `andb %ch, %al` — the high byte of RCX, not BPL.  With `_byte_rex_required`
    # in `formal/x86_64.py` the encoder emits `40 20 e8`, a 512-case census over
    # all sixteen `rm` and all sixteen `reg` values agrees with exact arithmetic,
    # and the rows are in the pool.
    @add(3, "and_r8")
    def _(r):
        d, s = _reg(r, GENERAL), _reg(r, GENERAL)
        return "and %s, %s" % (d.name, s.name), X.encode_and_r8_r8(d, s)

    @add(3, "or_r8")
    def _(r):
        d, s = _reg(r, GENERAL), _reg(r, GENERAL)
        return "or %s, %s" % (d.name, s.name), X.encode_or_r8_r8(d, s)

    # **`call r64` is deliberately NOT here, and this is a HARNESS property
    # rather than a model gap.**  It jumps to a register's contents, and a
    # random 64-bit value is outside the one `MAP_FIXED` region the harness
    # maps, so every case would fault at the jump and the comparison would never
    # happen — the same reason arm64's `encode_br_xn` is in
    # `tools/formal_isa_census.py`'s `HARNESS_LIMITS`.  The alternative — a call
    # to a known address inside the region — is a different instruction from the
    # one a function-value call emits, so it would be testing the pool rather
    # than the encoder.
    #
    # The form is not therefore untested: `samples()` asks `x86_step` about it
    # and `x86_step_call_r64` is a theorem about it, so the model side has a
    # check and only the hardware differential is missing.

    return out


POOL = pool()
_POOL_WEIGHTS = [w for _n, w, _f in POOL]


def census_cases(rng, per_form=3):
    """One-instruction programs, `per_form` of them per pool entry.

    Random programs find bugs; this finds them PER FORM, which is what says
    which encoder is unmodelled. A NORUN minimised out of a random program names
    one offending byte sequence, and a dozen of those is a dozen unrelated
    stories; the same question asked once per pool entry is a table, and the
    table is the argument that a model change fixed a FORM rather than one
    program.

    `per_form` > 1 because a form's agreement can depend on its operands: a
    `setcc` into a register whose upper bits are set agrees with a model that
    zeroes the whole register and disagrees with one that preserves them, and a
    single random initial state would make that look like luck.
    """
    cases = []
    idx = 0
    for name, _w, fn in POOL:
        for _ in range(per_form):
            item = fn(rng)
            items = list(item) if isinstance(item[0], tuple) else [item]
            _t, _b, regs, xmm, flags, mem = _init_state(rng)
            cases.append((name, "%s#%d" % (name, len(cases)),
                          Program(idx, items, regs, xmm, flags, mem)))
            idx += 1
    return cases


def _init_state(rng):
    """The initial machine state one fuzz case starts from."""
    regs = [rng.getrandbits(64) for _ in range(16)]
    regs[R.RSP.value] = STACK_TOP_ABS
    regs[R.R13.value] = MEMBASE_ABS
    regs[R.R14.value] = MEMBASE_ABS
    xmm = [rng.getrandbits(64) for _ in range(8)]
    flags = {name: bool(rng.getrandbits(1))
             for name in ("cf", "zf", "sf", "of_")}
    mem = [rng.getrandbits(8) for _ in range(DATA_N)]
    return None, None, regs, xmm, flags, mem


def gen_program(rng, ninstr):
    """One random program: the instruction list, the initial register file, the
    initial XMM file, the initial flags and the initial memory window.

    The instruction list is a list of `(text, bytes)` PAIRS rather than a text
    list plus one concatenated byte string, because the prefix search below cuts
    a program at an instruction boundary and nothing in the tree records an
    encoder's length — so a split has to come from the generator, not from a
    second guess at where one instruction ends."""
    items = []
    for _ in range(ninstr):
        _n, _w, fn = rng.choices(POOL, weights=_POOL_WEIGHTS, k=1)[0]
        item = fn(rng)
        if isinstance(item[0], tuple):
            items.extend(item)
        else:
            items.append(item)
    _t, _b, regs, xmm, flags, mem = _init_state(rng)
    return items, regs, xmm, flags, mem


# ── the native half ─────────────────────────────────────────────────────

HARNESS_C = r"""/* GENERATED by formal/x86_64_model_fuzz.py -- do not edit.
 *
 * Five things here are load-bearing, and each has a reason that cost a run to
 * find.
 *
 * 1. THE ENTRY STUB LOADS THE REGISTER FILE WITH INSTRUCTIONS. `setcontext`
 *    restores RIP and RSP and the CALLEE-SAVED registers on this platform and
 *    silently leaves the caller-saved ones (RAX, RCX, RDX, RSI, RDI, R8-R11)
 *    holding whatever the C code that called it had. Measured: with a program
 *    of one `nop`, the CPU's R8 came back as a libsystem address, RDX and R9 and
 *    R11 as zero, RCX and R10 as the address of the dump array, and only RBX,
 *    RBP and R12-R15 as the values the fuzzer asked for. So `setcontext` alone
 *    cannot express "start with these sixteen registers", and a fuzzer that
 *    believes it can reports every register as a disagreement -- which is what
 *    it did, on a model that was in fact agreeing on the one instruction the
 *    program contained. The stub therefore reads all seventeen words (sixteen
 *    GPRs plus EFLAGS) out of a block the C code points at, with real `mov`
 *    instructions, and only RIP comes from `setcontext`.
 *
 * 2. The two stubs stay in the HARNESS image and are never copied into the
 *    emulated region. Every store and every reference in them is RIP-relative
 *    or register-relative, and a RIP-relative displacement is resolved against
 *    the CURRENT instruction pointer: copied to the region's address the same
 *    bytes compute `dump_area` minus the harness's slide plus the region's, so
 *    every store lands in unmapped memory and the first program segfaults before
 *    executing one byte. Measured, not reasoned: that was the first version.
 *
 * 3. NEITHER STUB RETURNS WITH A CALL. `leaq _resume(%rip), %rsp; ret` puts RSP
 *    at the ADDRESS OF `_resume` and then pops a "return address" out of the
 *    first eight bytes of that function -- its own machine code. It faults
 *    immediately, and reads as "entering mapped code does not work", which is
 *    not what is true. It is `push`+`ret` off whatever stack the program left,
 *    which is the `TERMINATOR_WHY` contract on the other side.
 *
 * 4. The dump stub saves RSP BEFORE anything can change it, and RFLAGS by
 *    `pushfq`/`popq %rax` (which is the only way to read the flags without
 *    destroying them). `popfq` would work too and does not: it discards the
 *    reserved bit's contribution and the model has no AF to compare.
 *
 * 5. The driver is a LOOP over programs. The first version had `run_one` call
 *    `advance` which called `run_one`, so a program that faulted recursed until
 *    the C stack ran out and took the process with it -- and because
 *    `siglongjmp` restores RSP into a frame whose C stack had already been
 *    reused, WHICH programs faulted changed from run to run. A fuzzer whose
 *    verdicts move between runs cannot be used to decide whether a fix worked.
 */
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
#include <signal.h>
#include <sys/mman.h>
#include <ucontext.h>

#define REGION_BASE REGION_BASE_L
#define REGION_SIZE REGION_SIZE_L
#define CODE_OFF    CODE_OFF_L
#define STACK_OFF   STACK_OFF_L
#define STACK_SIZE  STACK_SIZE_L
#define STACK_TOP   STACK_TOP_L
#define DATA_OFF    DATA_OFF_L
#define DATA_N      DATA_N_L
#define TERMINATOR_LEN TERMINATOR_LEN_L
#define TERMINATOR_IMM_OFF TERMINATOR_IMM_OFF_L

unsigned long long dump_area[64];
#ifdef PROBE_ON
/* `probe_area` is the ENTRY side of the same layout, and it exists only
 * when the harness is built with `probe=True`: the entry stub fills it
 * from the registers it has just loaded and the driver prints it beside
 * the dump. Guarded with the stores and the print, so a default build is
 * the harness it was -- see `ENTRY_PROBE_WHY`.
 */
unsigned long long probe_area[64];
#endif
/* The address the entry stub jumps to, read RIP-relative so the stub needs no
 * scratch register to reach it -- every GPR is holding a value the fuzzer chose
 * by the time that jump happens. */
unsigned long long enter_target = REGION_BASE + CODE_OFF;

void resume(void);

__asm__(
".text\n"
".globl _enter_stub\n"
"_enter_stub:\n"
"  movq (%rsp), %rbx\n"
/* XMM first, through RAX as the scratch: `setcontext` cannot set an XMM
 * register at all (there is no field for one in `__darwin_x86_thread_state64`),
 * so without this every XMM comparison is against whatever the C library left
 * there -- and the model, whose `X86State.xmm0..7` all start at 0, disagrees on
 * all eight of them on every program including a bare `nop`. */
"  movq 136(%rbx), %rax\n"
"  movq %rax, %xmm0\n"
"  movq 144(%rbx), %rax\n"
"  movq %rax, %xmm1\n"
"  movq 152(%rbx), %rax\n"
"  movq %rax, %xmm2\n"
"  movq 160(%rbx), %rax\n"
"  movq %rax, %xmm3\n"
"  movq 168(%rbx), %rax\n"
"  movq %rax, %xmm4\n"
"  movq 176(%rbx), %rax\n"
"  movq %rax, %xmm5\n"
"  movq 184(%rbx), %rax\n"
"  movq %rax, %xmm6\n"
"  movq 192(%rbx), %rax\n"
"  movq %rax, %xmm7\n"
"  movq 0(%rbx), %rax\n"
"  movq 8(%rbx), %rcx\n"
"  movq 16(%rbx), %rdx\n"
"  pushq 128(%rbx)\n"
"  popfq\n"
"  movq 32(%rbx), %rsp\n"
"  movq 40(%rbx), %rbp\n"
"  movq 48(%rbx), %rsi\n"
"  movq 56(%rbx), %rdi\n"
"  movq 64(%rbx), %r8\n"
"  movq 72(%rbx), %r9\n"
"  movq 80(%rbx), %r10\n"
"  movq 88(%rbx), %r11\n"
"  movq 96(%rbx), %r12\n"
"  movq 104(%rbx), %r13\n"
"  movq 112(%rbx), %r14\n"
"  movq 120(%rbx), %r15\n"
"  movq 24(%rbx), %rbx\n"
"__PROBE_ASM__"
"  jmp *_enter_target(%rip)\n"
".globl _dump_stub\n"
".globl _dump_stub_start\n"
".globl _dump_stub_end\n"
"_dump_stub:\n"
"_dump_stub_start:\n"
"  movq %rax, _dump_area+0(%rip)\n"
"  movq %rcx, _dump_area+8(%rip)\n"
"  movq %rdx, _dump_area+16(%rip)\n"
"  movq %rbx, _dump_area+24(%rip)\n"
"  movq %rsp, _dump_area+32(%rip)\n"
"  movq %rbp, _dump_area+40(%rip)\n"
"  movq %rsi, _dump_area+48(%rip)\n"
"  movq %rdi, _dump_area+56(%rip)\n"
"  movq %r8,  _dump_area+64(%rip)\n"
"  movq %r9,  _dump_area+72(%rip)\n"
"  movq %r10, _dump_area+80(%rip)\n"
"  movq %r11, _dump_area+88(%rip)\n"
"  movq %r12, _dump_area+96(%rip)\n"
"  movq %r13, _dump_area+104(%rip)\n"
"  movq %r14, _dump_area+112(%rip)\n"
"  movq %r15, _dump_area+120(%rip)\n"
"  pushfq\n"
"  popq %rax\n"
"  movq %rax, _dump_area+128(%rip)\n"
"  movq %xmm0, _dump_area+136(%rip)\n"
"  movq %xmm1, _dump_area+144(%rip)\n"
"  movq %xmm2, _dump_area+152(%rip)\n"
"  movq %xmm3, _dump_area+160(%rip)\n"
"  movq %xmm4, _dump_area+168(%rip)\n"
"  movq %xmm5, _dump_area+176(%rip)\n"
"  movq %xmm6, _dump_area+184(%rip)\n"
"  movq %xmm7, _dump_area+192(%rip)\n"
"  leaq _resume(%rip), %rax\n"
"  pushq %rax\n"
"  ret\n"
"_dump_stub_end:\n"
);

extern char dump_stub_start[], dump_stub_end[];
/* `char[]`, NOT `void *`: a `void *` declaration of a symbol the assembler
 * block also DEFINES is a common symbol to the linker, and the C side then
 * reads a pointer to wherever the common was allocated instead of the stub's
 * address -- `enter_stub` came back as 0x4800001d61258948 and the process hung
 * in the first instruction. */
extern char enter_stub[];

static unsigned char *region;
static unsigned int npgm;
static unsigned int pgm;
static int outcome;              /* 0 = faulted, 1 = reached the dump stub */
static volatile int fault_sig;
static volatile uint64_t fault_rip;
static sigjmp_buf back_env;

/* 16-byte aligned because the entry stub pushes a qword and pops the flags
 * through it before it installs the emulated RSP. */
static uint64_t enter_stack[64] __attribute__((aligned(16)));

static void on_fault(int sig, siginfo_t *si, void *uctx)
{
    ucontext_t *u = (ucontext_t *)uctx;
    (void)si;
    fault_sig = sig;
    fault_rip = u->uc_mcontext->__ss.__rip;
    siglongjmp(back_env, 1);
}

/* `progs` is a flat byte array (fuzzed bytes PLUS the terminator), `prog_off`/
 * `prog_len` its extent table, and `init_block` the 25 words per program the
 * entry stub loads: the sixteen GPRs in `x86_get_reg` order, then EFLAGS, then
 * XMM0..XMM7 -- which is the order the stub reads them in, so the offsets in the
 * asm above and the row built here are one table and not two. */
__PROGS__

/* Enter the emulated code. Does not return: `setcontext` puts the CPU in the
 * entry stub, and the only ways out are the dump stub and a signal, both of
 * which `siglongjmp` back to the driver loop. */
static void enter(unsigned int i)
{
    unsigned int len = prog_len[i];
    unsigned char *code = region + CODE_OFF;

    /* The emulated stack is zeroed for EVERY program, not just the first: a
     * `pop` reads a slot nothing wrote, the model reads 0 there, and a stale
     * stack byte would make every popped register a false disagreement. */
    memset(region + STACK_OFF, 0, STACK_SIZE);
    memcpy(region + DATA_OFF, init_mem + i * DATA_N, DATA_N);
    memcpy(code, progs + prog_off[i], len);
    /* Patch the terminator's `movabs rax, imm64` with the stub's address; see
     * TERMINATOR_WHY. A slot planted at the initial RSP instead does not
     * survive a `pop` followed by a `push`. */
    memcpy(code + len - TERMINATOR_LEN + TERMINATOR_IMM_OFF,
           &(uint64_t){(uint64_t)dump_stub_start}, 8);

    /* Slot 8, not slot 0: `__rsp` points AT the slot the entry stub reads,
     * and the stub's `pushq`/`popfq` pair for EFLAGS needs the eight bytes
     * below it -- which is why the array is 64 words and not 2. */
    enter_stack[8] = (uint64_t)&init_block[i][0];

    fault_sig = 0;
    fault_rip = 0;
    ucontext_t uc;
    getcontext(&uc);
    /* Only RIP and RSP: see note 1 at the top of this file. */
    uc.uc_mcontext->__ss.__rip = (uint64_t)(uintptr_t)enter_stub;
    uc.uc_mcontext->__ss.__rsp = (uint64_t)&enter_stack[8];
    setcontext(&uc);
    fprintf(stderr, "harness: setcontext returned for program %u\n", i);
    exit(4);
}

void resume(void)
{
    unsigned int k;
    printf("P %u", pgm);
    for (k = 0; k < 16; k++) printf(" %016llx", dump_area[k]);
    printf(" %016llx", dump_area[16]);
    for (k = 0; k < 8; k++) printf(" %016llx", dump_area[17 + k]);
    for (k = 0; k < DATA_N / 8; k++) {
        unsigned long long v = 0;
        unsigned int j;
        for (j = 0; j < 8; j++)
            v |= (unsigned long long)region[DATA_OFF + 8 * k + j] << (8 * j);
        printf(" %016llx", v);
    }
    printf("\n");
#ifdef PROBE_ON
    /* The ENTRY register file, dumped by the stub that loaded it, one line
     * per program beside the dump. Off unless the harness was built with
     * `probe=True`, so a default run's output is byte for byte what it
     * was; see `ENTRY_PROBE_WHY`. */
    printf("E %u", pgm);
    for (k = 0; k < 25; k++) printf(" %016llx", probe_area[k]);
    printf("\n");
#endif
    outcome = 1;
    siglongjmp(back_env, 1);
}

int main(void)
{
    struct sigaction sa;
    unsigned int i;

    memset(&sa, 0, sizeof sa);
    sa.sa_sigaction = on_fault;
    sa.sa_flags = SA_NODEFER | SA_RESTART | SA_SIGINFO;
    sigemptyset(&sa.sa_mask);
    for (i = 0; i < sizeof fault_handled / sizeof fault_handled[0]; i++)
        sigaction(fault_handled[i], &sa, NULL);

    region = mmap((void *)(uintptr_t)REGION_BASE, REGION_SIZE,
                  PROT_READ | PROT_WRITE | PROT_EXEC,
                  MAP_ANON | MAP_PRIVATE | MAP_FIXED, -1, 0);
    if (region == MAP_FAILED || (unsigned long)region != REGION_BASE) {
        fprintf(stderr, "harness: mmap MAP_FIXED at 0x%lx failed (%p)\n",
                (unsigned long)REGION_BASE, region);
        return 1;
    }
    printf("STUB %lx\n", (unsigned long)dump_stub_start);
    fflush(stdout);
    npgm = NPROG;

    for (pgm = 0; pgm < npgm; pgm++) {
        outcome = 0;
        if (sigsetjmp(back_env, 1) == 0)
            enter(pgm);                  /* does not return */
        if (!outcome)
            printf("F %u %d %llx\n", pgm, fault_sig,
                   (unsigned long long)fault_rip);
        fflush(stdout);
    }
    printf("DONE\n");
    fflush(stdout);
    return 0;
}
"""


def _cwords(row):
    """One C initialiser row of 64-bit words.

    The `ULL` suffix is not decoration: a 64-bit pattern with bit 63 set is not
    representable as a C signed literal, and clang's default is to accept it as
    unsigned with a warning -- a warning in generated code nobody reads."""
    return ",".join("%dULL" % (v & MASK64) for v in row)


def _c_array64(name, rows):
    """A `NPROG x 16` table of 64-bit words.

    The `ULL` suffix is not decoration: a 64-bit pattern with bit 63 set is not
    representable as a C signed literal, and clang's default is to accept it as
    unsigned with a warning -- a warning in generated code nobody reads."""
    out = ["static const unsigned long long %s[][16] = {" % name]
    for row in rows:
        out.append("  {" + _cwords(row) + "},")
    out.append("};")
    return "\n".join(out)


def harness_source(programs, probe=False):
    """The generated C for one batch of programs.

    `probe` adds the entry register file's dump — `ENTRY_PROBE_WHY`.
    """
    # `full_code()`, NOT `p.code`: the harness has to execute the terminator
    # too, and copying only the fuzzed bytes leaves the CPU running off the end
    # of them into the previous program's tail — which is a SIGSEGV on most
    # programs and, worse, an ACCIDENTALLY CORRECT run on one of them, because
    # that tail sometimes decodes as the terminator. This was measured: five
    # programs faulting with `rsp` untouched and one that quietly agreed, with
    # the model never having been asked.
    # The terminator's immediate is a PLACEHOLDER here (all zero bytes): the
    # stub's address is wherever the loader puts it, and this byte table is
    # built before the harness exists to be loaded. `enter` patches it.
    code = b"".join(p.code + terminator_bytes(0) for p in programs)
    decls = ["static const unsigned char progs[] = {"]
    decls.append("  " + ",".join(str(b) for b in (code or b"\x90")))
    decls.append("};")
    decls.append("static const unsigned int prog_off[] = {"
                 + ",".join(str(off) for off, _l in
                            _extents(programs)) + "};")
    decls.append("static const unsigned int prog_len[] = {"
                 + ",".join(str(l) for _o, l in _extents(programs)) + "};")
    decls.append("#define NPROG %d" % len(programs))
    decls.append("static unsigned long long init_block[][25] = {")
    for p in programs:
        row = ([p.regs[i] for i in range(16)] + [eflags(p.flags)]
               + list(p.xmm))
        decls.append("  {" + _cwords(row) + "},")
    decls.append("};")
    flat_mem = [b for p in programs for b in p.mem]
    decls.append("static const unsigned char init_mem[] = {"
                 + ",".join(str(b) for b in (flat_mem or [0])) + "};")
    decls.append("static const int fault_handled[] = {SIGFPE, SIGSEGV, SIGBUS,"
                 " SIGILL, SIGTRAP};")
    # `PROBE_ON` goes FIRST, before the harness text, because the two guarded
    # regions — the `probe_area` declaration and `resume`'s print — are both
    # ABOVE the generated tables, and a `#define` below them is a macro the
    # preprocessor has already passed. Measured: `use of undeclared identifier
    # 'probe_area'`, which is what a `#define` in the wrong place looks like.
    return (("#define PROBE_ON 1\n" if probe else "")
            + HARNESS_C
            .replace("REGION_BASE_L", "0x%016xUL" % REGION_BASE)
            .replace("REGION_SIZE_L", "%dUL" % REGION_SIZE)
            .replace("CODE_OFF_L", "0x%06xUL" % CODE_OFF)
            .replace("STACK_OFF_L", "0x%06xUL" % STACK_OFF)
            .replace("STACK_SIZE_L", "0x%06xUL" % STACK_SIZE)
            .replace("DATA_OFF_L", "0x%06xUL" % DATA_OFF)
            .replace("DATA_N_L", "%d" % DATA_N)
            .replace("TERMINATOR_LEN_L", "%d" % TERMINATOR_LEN)
            .replace("TERMINATOR_IMM_OFF_L", "%d" % TERMINATOR_IMM_OFF)
            .replace("STACK_TOP_L", "0x%012xUL" % STACK_TOP_ABS)
            # The WHOLE literal, quotes included, is what is replaced: the
            # placeholder sits inside `__asm__("...")` as a string of its own,
            # so a replacement carrying its own quotes would concatenate with
            # the placeholder's and produce `""  movq …`. With `probe=False` the
            # replacement is `""`, which is why a default run's harness is the
            # same text it was.
            .replace('"__PROBE_ASM__"',
                     _ENTRY_PROBE_ASM + "\n" if probe else '""')
            .replace("__PROGS__", "\n".join(decls)))


def _extents(programs):
    out, off = [], 0
    for p in programs:
        n = len(p.code) + TERMINATOR_LEN
        out.append((off, n))
        off += n
    return out


def eflags(flags):
    v = 0x002                      # the reserved bit, always 1 on hardware
    if flags["cf"]:
        v |= EF_CF
    if flags["zf"]:
        v |= EF_ZF
    if flags["sf"]:
        v |= EF_SF
    if flags["of_"]:
        v |= EF_OF
    return v


#: Where a DERIVED program's index starts.  The generated corpus numbers its
#: programs from 0, and a minimisation batch of a twelve-instruction program
#: wants twelve names that cannot collide with a corpus of any size — a name is a
#: Lean identifier and a table key, so "the same name twice" is not a cosmetic
#: duplicate.  See `Program.prefix`.
_FRESH_INDEX_BASE = 1000000
_fresh_counter = [0]


def _fresh_index():
    _fresh_counter[0] += 1
    return _FRESH_INDEX_BASE + _fresh_counter[0]


class Program(object):
    """One fuzz case, and the two byte strings both halves have to agree on.

    `code` is the FUZZED part; `full_code(stub)` appends `terminator_bytes`, the
    three instructions that leave the program into the harness's dump stub. The
    model gets the same bytes and the same exit pc, so the terminator is decoded
    by the model exactly as the CPU decodes it.

    `items` is the `(text, bytes)` list, kept because a prefix of a program is a
    prefix of that list; see `gen_program`."""

    __slots__ = ("index", "items", "code", "regs", "xmm", "flags", "mem")

    def __init__(self, index, items, regs, xmm, flags, mem):
        self.index = index
        self.items = list(items)
        self.code = b"".join(b for _t, b in self.items)
        self.regs = regs
        self.xmm = xmm
        self.flags = flags
        self.mem = mem

    @property
    def text(self):
        return [t for t, _b in self.items]

    def full_code(self, stub):
        return self.code + terminator_bytes(stub)

    def prefix(self, n, index=None):
        """The first `n` instructions, same initial state.

        Exact rather than approximate, because these programs are straight-line:
        a prefix is itself a valid program, so a disagreement it still shows is
        one it causes.

        **`index` is not the parent's by default, and that is the fix rather than
        a convenience.**  `index` is the program's NAME in both directions: the
        Lean file declares `code_<index>` / `init_<index>` and prints the result
        under it, and `run_model` keys its table by it. So N prefixes of one
        program with one index produce N programs that all claim the same name,
        and Lean rejects the file — while still evaluating every `#eval!`
        against the FIRST declaration, so `run_model` gets N copies of ONE
        program's answer and `evaluate` pairs each prefix's hardware dump with
        the FULL program's model result.  Measured before this line existed:
        `-n 16 --ninstr 6 --seed 5` reported six `WRONG` rows and minimised
        every one of them to a two-instruction prefix that agrees when it is run
        on its own.  So the index is fresh unless a caller genuinely means the
        same program, and `lean_source` refuses duplicates rather than
        generating a file that half elaborates.
        """
        if index is None:
            index = _fresh_index()
        return Program(index, self.items[:n], self.regs, self.xmm,
                       self.flags, self.mem)


def build_harness(programs, workdir, probe=False):
    """Compile the native harness and return its path, or raise.

    `probe` is `--entry-probe`: the entry stub also dumps the register file it
    loaded, which is the one step of this path nothing else reads back.
    """
    src = os.path.join(workdir, "fuzz_harness.c")
    exe = os.path.join(workdir, "fuzz_harness")
    with open(src, "w") as f:
        f.write(harness_source(programs, probe=probe))
    cmd = ["clang", "-arch", "x86_64", "-O1", "-D_XOPEN_SOURCE",
           "-Wno-deprecated-declarations", "-o", exe, src]
    proc = subprocess.run(_memslot(cmd), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("clang failed:\n"
                           + (proc.stdout + proc.stderr)[:4000])
    if shutil.which("codesign"):
        subprocess.run(["codesign", "-s", "-", exe], capture_output=True,
                       text=True)
    return exe


def _memslot(argv):
    """Every subprocess this file spawns goes through the machine-wide memory
    reservation (see `CLAUDE.md`): `clang` is a compiler and the harness is a
    native process, and neither is small enough to leave unaccounted for."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    slot = os.path.join(root, "tools", "memslot.py")
    if not os.path.exists(slot):
        return argv
    return ["python3", slot, "--gb", "8", "--label", "x86fuzz"] + argv


def run_native(programs, workdir, verbose=False, probe=False):
    """`([(status, fields)] per program, stub_address)`, where `status` is
    `'ran'` (and `fields` is what the CPU left behind) or `'fault'` (hardware
    took `#DE`, so there is nothing to compare and nothing is claimed).

    With `probe=True` a third value comes back — `{pos: [25 words]}` — the
    register file the entry stub had installed, for the programs that ran. See
    `ENTRY_PROBE_WHY`.
    """
    if not programs:
        return [], 0, {}
    exe = build_harness(programs, workdir, probe=probe)
    proc = subprocess.run(_memslot(["arch", "-x86_64", exe]),
                          capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError("harness exited %d:\n%s%s"
                           % (proc.returncode, proc.stdout[-2000:],
                              proc.stderr[-2000:]))
    stub = None
    got = {}
    faults = {}
    probes = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "STUB":
            stub = int(parts[1], 16)
            continue
        if parts[0] == "F":
            faults[int(parts[1])] = (int(parts[2]), int(parts[3], 16))
            continue
        if parts[0] == "E":
            probes[int(parts[1])] = [int(x, 16) for x in parts[2:]]
            continue
        if parts[0] == "P":
            i = int(parts[1])
            v = [int(x, 16) for x in parts[2:]]
            got[i] = v
    if stub is None:
        raise RuntimeError("harness printed no STUB line:\n"
                           + proc.stdout[:2000])
    out = []
    # POSITIONAL, not `p.index`: the harness numbers programs 0..n-1 within its
    # own table, and a batch's `Program.index` is its index in the WHOLE run, so
    # the second batch onwards looks up keys the harness never wrote and every
    # program in it is reported as a fault with signal 0.
    for pos, p in enumerate(programs):
        v = got.get(pos)
        if v is None:
            out.append(("fault", faults.get(pos, (0, 0))))
            continue
        regs = v[0:16]
        fl = v[16]
        xmm = v[17:25]
        memq = v[25:25 + DATA_N // 8]
        out.append(("ran", {
            "regs": regs,
            "flags": {"cf": bool(fl & EF_CF), "zf": bool(fl & EF_ZF),
                      "sf": bool(fl & EF_SF), "of_": bool(fl & EF_OF)},
            "xmm": xmm,
            "memq": memq,
        }))
    if verbose:
        sys.stderr.write("  native: stub=0x%x ran=%d fault=%d\n"
                         % (stub, sum(1 for s, _ in out if s == "ran"),
                            sum(1 for s, _ in out if s == "fault")))
    return out, stub, probes


# ── the model half ──────────────────────────────────────────────────────

LEAN_PRELUDE = """\
import X86

set_option maxRecDepth 100000

def dataLo : Nat := %(dataLo)d
def dataN : Nat := %(dataN)d
/-- `rsp` is a `UInt64`, so the constant the initial state needs is in that
    type. `Nat` and `UInt64` are separate declarations rather than a coercion
    because the model reads a literal `UInt64` at that field and a `Nat` is a
    type error there. -/
def stackTopU : UInt64 := %(stackTop)d

/-- Every field `X86State` has that a program can be compared on: the 16 GPRs
    in `x86_get_reg` order (which is NOT the encoding order), the 8 XMM
    registers, the memory window as 8-byte reads, and the four flags as one
    letter each so a disagreement reads as a word rather than as four numbers. -/
def showState : Option X86State → String
  | none => "NORUN"
  | some s =>
      let regs := (List.range 16).map (fun i => toString (x86_get_reg s i))
      let xmm := (List.range 8).map (fun k => toString (x86_get_xmm s k))
      let mem := (List.range (dataN / 8)).map
        (fun i => toString (mem_read_bytes s.mem (dataLo + 8 * i) 8))
      let fl := [if s.zf then "Z" else "z", if s.sf then "S" else "s",
                 if s.cf then "C" else "c", if s.of_ then "O" else "o"]
      String.intercalate " " (regs ++ xmm ++ mem ++ fl)

"""


def _print_census(rows, forms):
    """One line per pool entry: which verdicts its samples got.

    A form whose verdict MIXES is reported as MIX rather than silently averaged:
    agreement that depends on the operands is exactly what `per_form > 1` exists
    to expose, and collapsing it to a majority hides the operands."""
    by_form = {}
    detail = {}
    for p, status, why in rows:
        by_form.setdefault(forms[p.index], []).append(status)
        detail.setdefault(forms[p.index], []).append(
            (status, "; ".join(p.text), p.code.hex(), why))
    print("\nper-form census (%d forms):" % len(by_form))
    for form in sorted(by_form):
        seen = sorted(set(by_form[form]))
        verdict = seen[0] if len(seen) == 1 else "MIX:" + "/".join(seen)
        print("  %-28s %-22s %s" % (form, verdict,
                                    " ".join(by_form[form])))
        if len(seen) > 1 or seen[0] != "AGREE":
            for status, text, hexb, why in detail[form]:
                print("      %-8s %-44s %s" % (status, text[:44], why))


def _byte_list(items):
    return "[" + ", ".join(str(b) for b in items) + "]"



def lean_source(programs, stub):
    """The Lean file that asks the model to run each program, or raise.

    **The names are the programs' `index`, so two programs with one index are a
    caller bug and this refuses them rather than emitting a file that half
    elaborates.** Lean rejects `code_N` / `mem_N` / `init_N` declared twice, and
    — measured, and the reason a refusal is better than a warning — it still
    evaluates every `#eval!` against the FIRST declaration, so the file prints
    N copies of one program's answer under one key and every caller reading it
    sees a model result that belongs to a different program. `run_model` treats
    a Lean error as fatal too, so a file that fails for any other reason cannot
    be read as a set of verdicts either.
    """
    seen = {}
    for p in programs:
        if p.index in seen:
            raise ValueError(
                "two programs share index %d — %r and %r. The Lean file "
                "declares code_%d / init_%d once and would answer both from "
                "the first. `Program.prefix` gives a derived program its own "
                "index for this reason."
                % (p.index, seen[p.index], p.items[0][0] if p.items else "",
                   p.index, p.index))
        seen[p.index] = p.items[0][0] if p.items else ""
    out = [LEAN_PRELUDE % {"dataLo": REGION_BASE + DATA_OFF,
                           "dataN": DATA_N,
                           "stackTop": STACK_TOP_ABS}]
    base = REGION_BASE + CODE_OFF
    for p in programs:
        full = p.full_code(stub)
        out.append("def code_%d (a : Nat) : UInt8 :=" % p.index)
        out.append("  if a < %d then 0 else (%s).getD (a - %d) 0"
                   % (base, _byte_list(full), base))
        # ONLY the data window. The model's initial memory is zero everywhere
        # else, and so is the harness's emulated stack (zeroed per program) --
        # but when the terminator planted its own return address at the initial
        # RSP, the model was given that slot as a NON-ZERO initial byte and the
        # harness was not, so every program that ended with a `pop` disagreed
        # about one register. The terminator writes the return address itself
        # now (`mov [rsp], rax`), so nothing is planted and nothing may be.
        out.append("def mem_%d (a : Nat) : UInt8 :=" % p.index)
        out.append("  if a < dataLo then 0 else")
        out.append("  if a - dataLo >= dataN then 0 else"
                   " (%s).getD (a - dataLo) 0" % _byte_list(p.mem))
        fields = ["rax := %d" % p.regs[0], "rcx := %d" % p.regs[1],
                  "rdx := %d" % p.regs[2], "rbx := %d" % p.regs[3],
                  "rsp := stackTopU", "rbp := %d" % p.regs[5],
                  "rsi := %d" % p.regs[6], "rdi := %d" % p.regs[7]]
        # `rbx` is named because the terminator overwrites it, so the two halves
        # deliberately disagree there; see GENERAL.
        for k in range(8, 16):
            fields.append("r%d := %d" % (k, p.regs[k]))
        for k in range(8):
            fields.append("xmm%d := %d" % (k, p.xmm[k]))
        fields.append("zf := %s" % ("true" if p.flags["zf"] else "false"))
        fields.append("sf := %s" % ("true" if p.flags["sf"] else "false"))
        fields.append("cf := %s" % ("true" if p.flags["cf"] else "false"))
        fields.append("of_ := %s" % ("true" if p.flags["of_"] else "false"))
        fields.append("mem := mem_%d" % p.index)
        out.append("def init_%d : X86State :=" % p.index)
        out.append("  { X86State.init 0 %d with" % base)
        out.append("    " + ",\n    ".join(fields) + " }")
        out.append('#eval! "%d " ++ showState'
                   ' (x86_exec_exit init_%d code_%d %d)'
                   % (p.index, p.index, p.index, stub))
    return "\n".join(out) + "\n"


def run_model(lean, programs, stub, lib_dir, workdir, verbose=False):
    """`{index: fields or None}` from the Lean model, or raise.

    `None` is the model's `NORUN` (`x86_exec_exit` returned `none`), which is a
    DIFFERENT failure from an absent key — see `evaluate`.

    **A Lean error is fatal, and that is the other half of what this reads.** The
    answer is a set of `#eval!` lines, and Lean prints the ones it could compute
    whether or not the rest of the file elaborated: a file with a rejected
    declaration still answers, for the declarations Lean accepted. So a silent
    parse of this output turns "the model refused to elaborate this program"
    into a verdict about the machine — the B22 shape, where an absent answer and
    a computed one look alike. Measured on the pre-fix tree, where every prefix
    of a minimisation batch shared one index: the file carried six
    `already been declared` errors and six IDENTICAL results.
    """
    if not programs:
        return {}
    src = os.path.join(workdir, "FuzzCheck.lean")
    with open(src, "w") as f:
        f.write(lean_source(programs, stub))
    env = dict(os.environ,
               LEAN_PATH=os.pathsep.join((workdir, lib_dir)))
    run = L.run_lean(lean, [src], cwd=workdir, env=env,
                     wall_s=FUZZ_WALL_S, cpu_s=FUZZ_CPU_S)
    if run.exceeded:
        raise RuntimeError(run.exceeded)
    errors = [ln for ln in (run.stdout + run.stderr).splitlines()
              if ": error:" in ln]
    if errors:
        raise RuntimeError(
            "the model's Lean file did not elaborate (%d error(s)); its answers "
            "would be partial, and a partial answer is read as a verdict "
            "about the machine. First: %s"
            % (len(errors), errors[0].strip()))
    got = {}
    for line in (run.stdout + run.stderr).splitlines():
        line = line.strip().strip('"')
        if not line or not line[0].isdigit():
            continue
        head, _, rest = line.partition(" ")
        if rest == "NORUN":
            got[int(head)] = None
            continue
        vals = rest.split()
        if len(vals) != 16 + 8 + DATA_N // 8 + 4:
            continue
        nums = [int(v) for v in vals[:-4]]
        got[int(head)] = {
            "regs": nums[0:16],
            "xmm": nums[16:24],
            "memq": nums[24:24 + DATA_N // 8],
            "flags": {"zf": vals[-4] == "Z", "sf": vals[-3] == "S",
                      "cf": vals[-2] == "C", "of_": vals[-1] == "O"},
        }
    if verbose:
        sys.stderr.write("  lean: %d/%d programs reported (rc=%d)\n"
                         % (len(got), len(programs), run.returncode))
    return got


# ── comparison ──────────────────────────────────────────────────────────

REGNAME = ("rax", "rcx", "rdx", "rbx", "rsp", "rbp", "rsi", "rdi",
           "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15")


#: The flags each condition code READS, from the model's `x86_cond`.  Only the
#: ten conditions the `setcc` pool draws need an entry; the two parity codes are
#: absent from the pool because `X86State` has no `pf` (see the module
#: docstring), so nothing here can name a flag the model does not have.
_CC_FLAGS = {
    0x0: ("of_",), 0x1: ("of_",), 0x2: ("cf",), 0x3: ("cf",),
    0x4: ("zf",), 0x5: ("zf",), 0x6: ("cf", "zf"), 0x7: ("cf", "zf"),
    0x8: ("sf",), 0x9: ("sf",), 0xc: ("sf", "of_"), 0xd: ("sf", "of_"),
    0xe: ("zf", "sf", "of_"), 0xf: ("zf", "sf", "of_"),
}
_FLAGS4 = ("zf", "sf", "cf", "of_")
#: Form-name prefixes and names, from `formal/x86_64_decode.py`'s own naming.
_ALU_FORMS = ("alu_rr:", "alu_ri32:", "alu_ri8:", "alu_rr8:", "alu_rr32:")
_MUL_FORMS = ("group3:mul", "group3:imul1", "imul_r64_r64",
              "imul_r64_r64_imm")
_DIV_FORMS = ("group3:div", "group3:idiv")
_SHIFT_FORMS = ("shift_imm8:", "shift_cl:")
#: `form -> bytes touched`, for the pool's memory loads and stores.
_LOAD_MEM = {"mov_r64_rm64": 8, "mov_r32_rm32": 4, "movzx_r64_rm8": 1,
             "movsx_r64_rm8": 1, "movzx_r64_rm16": 2, "movsx_r64_rm16": 2,
             "movsx_r64_rm32": 4}
_STORE_MEM = {"mov_rm64_r64": 8, "mov_rm32_r32_mem": 4, "mov_rm8_r8": 1,
              "mov_rm16_r16": 2}
#: Register-only copies `form -> (dst field, src field)`, including the
#: widening forms whose `reg` is the destination and `rm` the source.
_REG_COPIES = {"mov_rm64_r64": ("rm", "reg"), "mov_rm32_r32": ("rm", "reg"),
               "movzx_r64_r8": ("reg", "rm"), "movsx_r64_r8": ("reg", "rm"),
               "movzx_r64_r16": ("reg", "rm"), "movsx_r64_r16": ("reg", "rm"),
               "movsxd_r64_r32": ("reg", "rm")}


def _decode(code):
    """`decode_all(code)`, or `[]` for a stream this project's decoder refuses.

    The empty list is the safe direction for the taint pass: a stream it cannot
    name has no undefined value it can PROVE, so the row is compared in full --
    and if the decoder refuses it, `x86_step` almost certainly refuses it too,
    which is a `NORUN` and not a comparison at all.
    """
    try:
        return D.decode_all(bytes(code))
    except (D.DecodeError, IndexError, ValueError):
        return []


def _taint(program):
    """A forward pass over `program`'s decoded instructions, carrying the value
    UNDEFINEDNESS the architecture introduces.

    Intel SDM Vol. 2 leaves flags undefined after some instructions -- `MUL`/
    `IMUL` leave SF, ZF, AF and PF undefined ("The SF, ZF, AF, and PF flags are
    undefined"); `DIV`/`IDIV` leave all six; a shift by a count other than one
    leaves OF undefined -- and the model has to give SOME value for each.
    Comparing them is comparing a promise the architecture did not make, which
    is the whole of what the old `HARNESS` verdict was about.

    **It is not only the flags, and that is why this is a dataflow pass rather
    than a set of names.**  A `setcc` turns a flag into a register byte, so an
    undefined flag becomes an undefined VALUE, and every field computed from it
    -- a register the value is copied into, an XMM register, a byte of the
    compared window -- is undefined too.  Measured through this harness:
    `imul R10, RBP, 4 ; setge R11` differs in R11 alone (the model's SF is the
    low word's, Rosetta leaves it clear) and `... ; imul R10, R9, 2 ; mov RSI,
    R12 ; setl RBP` differs in RBP.  Both are architecturally undefined and
    neither is a model bug, and the old per-row rule could only absorb the
    second because it happened to compare the flag too.

    Returns `(flags, regs, xmm, mem)` -- the flag names, GPR indices, XMM
    indices and window BYTE offsets that are undefined at the END of the
    program, which is the only state the fuzzer compares.
    """
    flags = set()
    regs = set()
    xmm = set()
    mem = set()
    stack_tainted = [False]

    def undef_reg(i):
        return i in regs

    def window(disp, size):
        return range(DATA_N // 2 + disp, DATA_N // 2 + disp + size)

    def read_mem(insn, size):
        return any(o in mem for o in window(insn.mem_disp, size))

    def write_mem(insn, size):
        mem.update(window(insn.mem_disp, size))

    def put(is_undef, i):
        (regs.add if is_undef else regs.discard)(i)

    for insn in _decode(program.code):
        form, mod = insn.form, insn.mod
        if form == "setcc":
            if any(f in flags for f in _CC_FLAGS.get(insn.cc, ())):
                regs.add(insn.rm)
        elif form in _LOAD_MEM:
            put(read_mem(insn, _LOAD_MEM[form]), insn.reg)
        elif form in _STORE_MEM and mod != 3:
            # `mov_rm64_r64` is the decoder's name for BOTH the register move
            # and the memory store, so the `mod` test is what keeps a register
            # move from being read as a store into the window.
            if undef_reg(insn.reg):
                write_mem(insn, _STORE_MEM[form])
        elif form == "movq_xmm_rm64":
            if undef_reg(insn.rm):
                xmm.add(insn.xmm)
        elif form in ("mov_r64_imm32", "mov_r64_imm64"):
            regs.discard(insn.rm)                       # a constant
        elif form in ("lea_r64_rm64", "lea_r64_rip"):
            put(insn.mem_base is not None and undef_reg(insn.mem_base),
                insn.reg)
        elif form in _REG_COPIES:
            dst, src = _REG_COPIES[form]
            put(undef_reg(getattr(insn, src)), getattr(insn, dst))
        elif form == "cqo":
            put(undef_reg(0), 2)
        elif form == "alu_rr32:xor" and insn.reg == insn.rm:
            regs.discard(insn.rm)                       # `xor r, r` is zero
            flags = set()
        elif form in _DIV_FORMS:
            src = undef_reg(insn.rm) or undef_reg(0) or undef_reg(2)
            if src:
                regs.update((0, 2))
            flags = set(_FLAGS4)                        # all six undefined
        elif form in _MUL_FORMS:
            if form == "imul_r64_r64":
                src = undef_reg(insn.reg) or undef_reg(insn.rm)
                put(src, insn.reg)
            elif form == "imul_r64_r64_imm":
                src = undef_reg(insn.rm)
                put(src, insn.reg)
            else:                                       # group3:mul / imul1
                src = undef_reg(insn.rm) or undef_reg(0)
                if src:
                    regs.update((0, 2))
            flags = set(_FLAGS4) if src else {"sf", "zf"}
        elif form.startswith(_ALU_FORMS):
            reads = (insn.reg, insn.rm) if form.startswith(
                ("alu_rr:", "alu_rr8:", "alu_rr32:")) else (insn.rm,)
            src = any(undef_reg(i) for i in reads)
            if form not in ("alu_rr:cmp", "alu_rr:test"):
                put(src, insn.rm)
            flags = set(_FLAGS4) if src else set()
        elif form in ("group3:not", "group3:neg"):
            if form == "group3:neg":
                flags = set(_FLAGS4) if undef_reg(insn.rm) else set()
            if undef_reg(insn.rm):
                regs.add(insn.rm)
        elif form.startswith(_SHIFT_FORMS):
            src = undef_reg(insn.rm) or (form.startswith("shift_cl:")
                                         and undef_reg(1))
            put(src, insn.rm)
            # **A count of 0 moves NO flag at all** (the module docstring's
            # `_shift_count` note), so an earlier instruction's undefined flags
            # survive it: `... ; idiv rcx ; >>signed R9, 0` ends with the
            # divide's undefined CF/SF/ZF, and the old code here reset them
            # because it treated every shift as a flag-writer.  A `cl` count is
            # unknown, so it is conservative in the safe direction: the earlier
            # undefined flags are kept AND OF may be.
            count = insn.imm if form.startswith("shift_imm8:") else None
            if count == 0:
                pass                                  # flags unchanged
            elif src:
                flags = set(_FLAGS4)
            elif count is None:                       # `cl`: 0 is possible
                flags = flags | {"of_"}
            elif count == 1:
                flags = set()
            else:
                flags = {"of_"}
        elif form == "push_r64":
            if undef_reg(insn.rm):
                stack_tainted[0] = True
        elif form == "pop_r64":
            put(stack_tainted[0], insn.rm)
        # jcc/jmp/call/nop/ret/leave write no compared field.
    return flags, regs, xmm, mem


def undefined_flags(program):
    """The flags the hardware leaves undefined at the END of `program`.

    `_taint` is the whole of the undefined-value analysis; this is its flag
    half, and it is what the old `HARNESS` "mul/imul flags" and "div" rows
    became once the flag names were read from the SDM instead of the host.
    """
    return _taint(program)[0]


def diff(hw, model, skip=()):
    """[(field, hardware value, model value)] — every compared field that
    differs, in a fixed order so a report is diffable against itself.

    `skip` is a set of FIELD names (`undefined_fields`' vocabulary: a flag, a
    GPR, `xmm<k>` or `mem[<off>]`), and every one of them is a value the
    architecture leaves undefined for this program. Skipping them is the whole
    of what the old `HARNESS` verdict did, now said per field instead of per row
    and with the flag's own undefinedness propagated to what it reaches.
    """
    skip = set(skip)
    out = []
    for i, name in enumerate(REGNAME):
        if name in TERMINATOR_CLOBBERS or name in skip:
            continue
        if hw["regs"][i] != model["regs"][i]:
            out.append((name, hw["regs"][i], model["regs"][i]))
    for k in range(8):
        if "xmm%d" % k in skip:
            continue
        if hw["xmm"][k] != model["xmm"][k]:
            out.append(("xmm%d" % k, hw["xmm"][k], model["xmm"][k]))
    for i, (a, b) in enumerate(zip(hw["memq"], model["memq"])):
        if "mem[%d]" % (8 * i) in skip:
            continue
        if a != b:
            out.append(("mem[%d]" % (8 * i), a, b))
    for name in ("zf", "sf", "cf", "of_"):
        if name in skip:
            continue
        if hw["flags"][name] != model["flags"][name]:
            out.append((name, int(hw["flags"][name]),
                        int(model["flags"][name])))
    return out


def undefined_fields(program):
    """Every compared field `_taint` proves the hardware leaves undefined in
    `program`: the undefined flags plus each register, XMM register and window
    byte derived from one, in `diff`'s own field vocabulary."""
    flags, regs, xmm, mem = _taint(program)
    out = set(flags)
    out.update(REGNAME[i] for i in regs)
    out.update("xmm%d" % k for k in xmm)
    out.update("mem[%d]" % (8 * (o // 8)) for o in mem)
    return out


def summarise(v):
    return ", ".join("%s hw=0x%x model=0x%x" % (f, a, b)
                     for f, a, b in v[:6]) \
        + ("" if len(v) <= 6 else " (+%d more)" % (len(v) - 6))


def evaluate(lean, batch, lib_dir, workdir, verbose=False):
    """Run both halves over one batch and return `([(Program, status, detail)],
    stub_address)`."""
    native, stub, _probes = run_native(batch, workdir, verbose)
    model = run_model(lean, batch, stub, lib_dir, workdir, verbose)
    out = []
    for p, (nstat, hw) in zip(batch, native):
        if nstat == "fault":
            sig, rip = hw
            out.append((p, "FAULT",
                        "hardware took signal %d at rip=0x%x (no comparison "
                        "possible)" % (sig, rip)))
            continue
        if p.index not in model:
            out.append((p, "NORUN-MISSING",
                        "the model reported nothing for this program"))
            continue
        mdl = model[p.index]
        if mdl is None:
            out.append((p, "NORUN", "x86_step returned none"))
            continue
        d = diff(hw, mdl, undefined_fields(p))
        if d:
            out.append((p, "WRONG", summarise(d)))
        else:
            out.append((p, "AGREE", ""))
    return out, stub


def minimise(lean, p, verdict, lib_dir, workdir, verbose=False):
    """The shortest PREFIX of `p` with the same verdict, or `None`.

    ALL prefixes at once, in ONE batch: a binary search would be `log2(n)` Lean
    runs per program, each one a fresh process paying for the whole `#eval!`
    batch, and the fuzzer's own budget is the thing being spent. Linear is `n`
    programs in one run, which for the twelve-instruction programs this file
    generates is four runs collapsed into one.

    A prefix that stops disagreeing and then starts again is possible in
    principle (a wrong store the model never reads, followed by one it does),
    and this reports the SHORTEST offending prefix rather than pretending the
    disagreement is monotone — so what it hands back is a program that genuinely
    fails, not merely the boundary of one.
    """
    if verdict not in ("WRONG", "NORUN"):
        return None
    n = len(p.items)
    if n <= 1:
        return p
    cands = [p.prefix(k) for k in range(1, n + 1)]
    res, _stub = evaluate(lean, cands, lib_dir, workdir, verbose)
    for cand, (_cp, status, _d) in zip(cands, res):
        if status == verdict:
            return cand
    return p


def entry_probe_report(programs, workdir):
    """`([(pos, register_index, wanted, got)], n_faulted)` — where the ENTRY
    register file is not what `init_block` said it should be, one row per
    disagreeing word, and how many programs never ran at all.

    **`init_block`'s order IS the comparison, and that is the point**: the row is
    built as `[p.regs[0..15]] + [eflags(p.flags)] + list(p.xmm)` and the entry
    stub reads the same twenty-five words in that order (note 1 at the top of
    this file), so "the CPU's register file at entry" and "the row the fuzzer
    asked for" are two readings of one table rather than two conventions that
    could drift.

    **The flags word is compared bit by bit, and the two bits that cannot agree
    are named rather than masked away.** `pushfq` returns bit 1 (reserved,
    always one) and bit 9 (IF, the interrupt-enable flag) as one whatever the
    program asked for, and `eflags()` sets the first and not the second, so a
    plain `==` differs by exactly `0x200` on every program and says nothing.
    Comparing the four bits `X86State` carries a field for — `EF_CF`, `EF_ZF`,
    `EF_SF`, `EF_OF` — plus bit 1, and requiring every OTHER bit to be equal
    too, is both correct and stricter: a bit nobody compares is still allowed to
    disagree, and `TERMINATOR_WHY` note 4's `popfq` problem (which discards the
    reserved bit's contribution and the model has no AF) is the same fact seen
    from the other side. Measured: with the four bits masked, 0 of 180 census
    programs disagree on anything.

    A `FAULT` program has no entry dump — the program faulted, so nothing about
    the stub is in question — and is not a row. A missing `E` line for a program
    that ran IS a row, and it is the interesting one: it means the entry stub
    did not reach its own dump.
    """
    rows, _stub, probes = run_native(programs, workdir, probe=True)
    bad = []
    for pos, p in enumerate(programs):
        want = [p.regs[i] for i in range(16)] + [eflags(p.flags)] + list(p.xmm)
        got = probes.get(pos)
        if rows[pos][0] != "ran":
            # A faulted program never reached the dump, so there is nothing to
            # compare and the entry stub is not what stopped it. Reported in the
            # summary line, not as a row: a `#DE` is the program's own doing.
            continue
        if got is None:
            bad.append((pos, -1, "an entry dump", None))
            continue
        for k, w in enumerate(want):
            g = got[k] if k < len(got) else None
            if k == 16:
                if g is None:
                    bad.append((pos, k, w, None))
                    continue
                # See the docstring: the model's four bits plus the reserved
                # one, exactly; every other bit must agree on its own.
                mask = EF_CF | EF_ZF | EF_SF | EF_OF | 0x002
                if (w & mask) != (g & mask) or (w & ~mask) != (g & ~mask & ~0x200):
                    bad.append((pos, k, w, g))
                continue
            if g != w:
                bad.append((pos, k, w, g))
    return bad, sum(1 for r in rows if r[0] != "ran")


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-n", "--n", type=int, default=64,
                    help="programs to generate (default 64)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--ninstr", type=int, default=12,
                    help="instructions per program (default 12)")
    ap.add_argument("--batch", type=int, default=32,
                    help="programs per Lean run (default 32)")
    ap.add_argument("--no-minimise", action="store_true")
    ap.add_argument("--census", action="store_true",
                    help="one-instruction programs, per-form per pool "
                         "entry, reported as a per-form table")
    ap.add_argument("--per-form", type=int, default=3,
                    help="initial states per form in --census (default 3)")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--entry-probe", action="store_true",
                    help="check the register file the ENTRY stub installed and "
                         "exit: no lean, no model, no batch loop. The one step "
                         "of the harness nothing else reads back, and the only "
                         "evidence available on a host that is not x86-64")
    args = ap.parse_args(argv)

    rng = random.Random(args.seed)
    forms = {}
    if args.census:
        cases = census_cases(rng, args.per_form)
        programs = [p for _form, _label, p in cases]
        forms = {p.index: form for form, _label, p in cases}
    else:
        programs = []
        for i in range(args.n):
            items, regs, xmm, flags, mem = gen_program(rng, args.ninstr)
            programs.append(Program(i, items, regs, xmm, flags, mem))

    if args.entry_probe:
        # BEFORE the lean lookup on purpose. This asks a question about the
        # NATIVE half, so making it wait on a toolchain and a library build
        # would be a dependency in the wrong direction: it is the instrument for
        # exactly the situation where the model half cannot be trusted to tell
        # you anything.
        with L.scratch_dir("x86_entry_probe") as workdir:
            bad, n_fault = entry_probe_report(programs, workdir)
        print("entry probe: %d program(s), %d faulted, %d disagreeing word(s)"
              % (len(programs),
                 n_fault, len(bad)))
        for pos, k, want, got in bad[:40]:
            which = ("entry dump" if k < 0
                     else ("flags" if k == 16
                           else "xmm%d" % (k - 17) if k >= 17
                           else "reg%d" % k))
            print("  program %d  %-9s init_block=%s cpu=%s"
                  % (pos, which,
                     want if isinstance(want, str) else "0x%016x" % want,
                     "no dump" if got is None else "0x%016x" % got))
        if bad:
            print("  …the entry stub did not install the register file the "
                  "fuzzer asked for; every field of every program would then be "
                  "a false disagreement and no disagreement would be the CPU's "
                  "fault. See ENTRY_PROBE_WHY.")
            return 1
        print("  every word of every entry register file matches init_block")
        return 0

    root = L._default_root()
    lean = L.find_lean(root)
    if not lean:
        print("lean not found (see ./lean-toolchain)")
        return 1
    L.ensure_library(lean, os.path.join(root, "lib"))
    lib_dir = os.path.join(root, "lib")

    rows = []
    with L.scratch_dir("x86_model_fuzz") as workdir:
        for start in range(0, len(programs), args.batch):
            chunk = programs[start:start + args.batch]
            res, _stub = evaluate(lean, chunk, lib_dir, workdir,
                                  args.verbose)
            rows.extend(res)
            if args.verbose:
                counts = {}
                for _p, s, _d in res:
                    counts[s] = counts.get(s, 0) + 1
                print("  batch %d..%d: %s"
                      % (start, start + len(chunk),
                         " ".join("%s=%d" % kv for kv in sorted(counts.items()))))

    tally = {}
    for _p, s, _d in rows:
        tally[s] = tally.get(s, 0) + 1
    bad = [(p, s, d) for p, s, d in rows if s in ("WRONG", "NORUN",
                                                  "NORUN-MISSING")]
    print("x86-64 model fuzz: %d programs, ninstr=%d seed=%d"
          % (len(programs), args.ninstr, args.seed))
    for k in sorted(tally):
        print("  %-14s %d" % (k, tally[k]))
    if forms:
        _print_census(rows, forms)

    if bad and not args.no_minimise:
        print("minimising %d discrepanc%s ..."
              % (len(bad), "y" if len(bad) == 1 else "ies"))
        with L.scratch_dir("x86_model_fuzz_min") as workdir:
            seen = set()
            for p, s, d in bad[:16]:
                small = minimise(lean, p, s, lib_dir, workdir, args.verbose)
                if small is None:
                    continue
                key = (tuple(small.code), s)
                if key in seen:
                    continue
                seen.add(key)
                res, _stub = evaluate(lean, [small], lib_dir, workdir,
                                      args.verbose)
                _p, got_status, detail = res[0]
                print("  %s  (%d instruction%s)"
                      % (got_status, len(small.items),
                         "" if len(small.items) == 1 else "s"))
                print("    %s" % ("; ".join(small.text)))
                print("    bytes: %s" % small.code.hex())
                print("    %s" % (detail or ""))
                if len(small.items) <= 6:
                    print("    init: rax=0x%x rbx=0x%x rcx=0x%x rdx=0x%x "
                          "rflags=0x%x" % (small.regs[0], small.regs[3],
                                            small.regs[1], small.regs[2],
                                            eflags(small.flags)))

    return 1 if tally.get("WRONG") or tally.get("NORUN") \
        or tally.get("NORUN-MISSING") else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
