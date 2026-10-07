## Status 2026-10-05 (`work/formal42-5`): the multiply table is DONE and it found a MODEL defect on its first run — and the byte-wise ALU found a NEW host class

**The doc's "what is still open, and it is one thing" is closed, and closing it
was worth more than the doc predicted.** `formal/x86_64_model_coverage_test.py`
now carries `multiply_cases` beside `divide_cases` and `shift_cases`: **32 rows
over the three multiply forms at REAL ENCODINGS, against exact integer
arithmetic**, going through `x86_step` because all three products are spelled
out inline in the arms and there is no `x86_mul128` to ask. On the first run
**11 of 32 failed**, every one of them a CF/OF bit, every one of them `0F AF`.

### The model bug: `imul r64, r64`'s overflow flag was a statement about the low word

The arm computed

```
let lo := a * b
let ovf := lo != x86_sign_extend64 lo
```

which never looks at the high half and is wrong in **both** directions.
Measured on this host, `imulq %rcx, %rax` in a statically linked binary:

| a | b | low word | CF | OF | the model said |
|---|---|---|---|---|---|
| `0000000000000003` | `0000000000000005` | `…0f` | 0 | 0 | **overflow** |
| `ffffffffffffffff` | `ffffffffffffffff` | `…01` | 0 | 0 | **overflow** |
| `8000000000000000` | `0000000000000001` | `8…0` | 0 | 0 | **overflow** |
| `8000000000000000` | `0000000000000002` | `…00` | 1 | 1 | **fits** |
| `4000000000000000` | `0000000000000002` | `8…0` | 1 | 1 | **fits** |
| `deadbeefcafebabe` | `0000000000000003` | `9c…3a` | 0 | 0 | **overflow** |

A program testing `a * b` for overflow read CF set for `3 * 5`. The fix is two
named definitions, and `F7 /5` now reads the same one the `0F AF` arm does —
which is the deduplication that matters, because the two were written apart and
only one was ever checked:

```lean
def x86_imul_ovf (a b) := let (lo, hi) := x86_split128 (x86_signed a * x86_signed b)
                         hi != x86_sign_extend64 lo
def x86_mul_ovf  (a b) := let (_, hi)  := x86_split128 (Int.ofNat a.toNat * Int.ofNat b.toNat)
                         hi != 0
```

`x86_step_imul_r64`'s conclusion, `formal/x86_64_endtoend_test.py`'s
`_SUCCS["imul_r64_r64"]` row, its `_SIMP_FORMS` entry and `_abs_step`'s
`imul_r64_r64` arm all move with it — the last of those had carried the model's
own wrong version for one commit, transcribed as `_imul_ovf`.

**Why nothing saw it, which is the half worth keeping.** No `formal/examples`
program reads a flag after a multiply. And `formal/x86_64_model_fuzz.py --census
--per-form 3 --seed 11` reports **byte-identical output before and after this
fix** — same 1 FAULT, same HARNESS set, 0 WRONG, same exit code — because a
random 64-bit product does not overflow, so a model claiming an overflow for
every random product and one claiming the right thing agree on every random
product. **An arithmetic table was needed; more seeds cannot help**, and this
doc's own instrument (a random-program fuzzer) is structurally blind to it.

### The new host class: an RBP operand in a byte-wise ALU

Adding the byte-wise `and`/`or` found a disagreement this harness has and a
static binary does not, on an **RBP operand**, one instruction and one fixed
register file at a time (RAX = `0xefaeef4cddfebb42`, the source = `0xff`):

| encoding | this harness | exact | a static binary |
|---|---|---|---|
| `and RAX, RCX` — `20 c8` | `…42` | `…42` | correct |
| `and R8, R9` — `45 20 c8` | `…42` | `…42` | correct |
| `and RAX, RBP` — `20 e8` | `…00` | `…42` | correct |
| `and RCX, RBP` — `20 e9` | `…02` | `…42` | correct |

with RBP = `0xff` before and after in every row. `and bpl, al` (ModRM `cd`,
`rm` = rbp) behaves the same way, so it is not the `reg` field alone. This is
the same family as `HARNESS_SETCC_DESTS` below — an RBP operand misbehaving in a
region entered by `setcontext` into an `mmap`'d RWX page — with a different
byte, and **`HARNESS_MUL_FORMS`/the pool do not absorb it**: `and`/`or` are NOT
in `formal/x86_64_model_fuzz.py`'s pool, because a verdict class that cannot
attribute a difference is worse than not running the row, and the `HARNESS`
verdict is excluded from that script's exit status, so a class in it has to be
an attribution.

**What is left, and it is the characterisation of that class**: which ModRM
bytes carrying an RBP operand misbehave in this harness, whether it is the
`reg` field, the `rm` field or the `c5`/`c6`/`c7` byte shape this doc's
measurement already names, and whether the answer is one rule or two. The
instrument to make it is the one this doc already argues for — a
one-instruction census over all sixteen `rm` and all eight `reg` values. The
measurement above is in `formal/x86_64_model_fuzz.py`'s pool comment and in
`bugs/FORMAL_x86_64_instruction_coverage_backlog.md`.

### And `imul_r64_r64_imm` joins the multiply class

`HARNESS_MUL_FORMS` gains it: `imul RDX, R12, -1` in this harness leaves SF
clear where the product says set, the `imul_r64_r64` class one form over. A
form missing from that set is reported as a **model verdict**, so an incomplete
set is a wrong verdict rather than a missing row.

### Measured, this pass

| | before | after |
|---|---|---|
| `multiply_cases` | did not exist | **32 rows, 0 FAILED** (11 on the first run) |
| `--census --per-form 3 --seed 11` | 204 AGREE, 1 FAULT, 10 HARNESS, 0 WRONG | **206 AGREE, 1 FAULT, 11 HARNESS, 0 WRONG** |
| `-n 16 --ninstr 6 --seed 5` | 9 AGREE, 1 FAULT, 6 HARNESS | **11 AGREE, 5 HARNESS, 0 WRONG** |
| `x86_step_imul_r64` on a random product | CF/OF set for every product | set only when the 128-bit product misses 64 signed bits |

`python3 test_x86_64_model_fuzz.py` 12/12 and `python3 test_formal_sweep_truth.py`
136/136, both after.

**The doc stays**, for the class above and for the reason its last section gives:
the last word on the hardware still needs hardware this tree does not run on.

**Status 2026-10-05 (`work/formal40-7`): the harness is EXONERATED and so is the
REPORTER — four reporter defects, measured, and two of them the whole reason this
doc's classes were only ever visible in a one-instruction census. TWO MODEL
DEFECTS fell out of fixing the reporter, and TWO MORE hardware classes fell out
of fixing the model.** The census was always clean because it only ever asked the
question it could attribute.

| what | before | after |
|---|---|---|
| `-n 16 --ninstr 6 --seed 5` | 9 AGREE, 1 FAULT, **6 WRONG**, exit 1 | 9 AGREE, 1 FAULT, **6 HARNESS**, exit 0 |
| every minimised row reproduces | **no** — six two-instruction prefixes that AGREE | yes |
| `--census --per-form 3 --seed 11` | 1 FAULT, 9 HARNESS | unchanged (1 FAULT, 9 HARNESS, no WRONG) |
| `lib/X86.lean`'s 128-bit divide | wrote a quotient where the CPU raises `#DE` | refuses (`none`), which is what `#DE` means |
| `lib/X86.lean`'s `shl` OF by one | `MSB(result)` — the carry OUT | `MSB(src) XOR MSB(result)` — the carry IN |

**And the two classes this doc did not have, both measured in hand-written
assembly with no compiler in the register setup:**

* **`idiv` is not a 128-bit divide on this host.** 8 of 28 register triples
  disagree with exact integer arithmetic, every one of them with a negative RAX
  of large magnitude, and the disagreements include a remainder LARGER than the
  divisor. §"The fourth class".
* **`imul r64, r64` returns the wrong PRODUCT sometimes**, in the harness's
  `setcontext`-into-RWX context and not in a static image: `imul rcx, rax` with
  RCX = 0xdb93a3a76ecdd572 and RAX = 0xb8a942080f5409f0 leaves RCX =
  0xc2a21dc73ca65ce0 where exact arithmetic and the model both say
  0xed50ca78d4e11ce0. Intermittent — the census's four one-instruction
  `imul_r64_r64` cases agree on the product and differ only in SF.

**What is still open, and it is one thing.** The reporter now attributes five
classes per FIELD rather than per row, and the remaining `WRONG` rows are the
rows where no class explains some field: 5 of 48 at `--seed 3`, 3 at `--seed 7`,
2 at `--seed 5` and `--seed 11`, 0 at `--seed 1`. Each of the ones read says the
same thing — a documented host anomaly that has propagated further than the
rules follow, or a model bug the fuzzer has not yet separated from one. **The
next step is the same shape as the divide's and it is named here because it is
the only gap left**: the multiply has no arithmetic table, so a difference at a
three-operand `imul`'s destination is classified by resemblance rather than by
attribution. `formal/x86_64_model_coverage_test.py` now carries
`divide_cases` (16 rows, exact integer arithmetic, 7 of which fail on the
pre-change library) and `shift_cases` (21 rows, the definitions, 2 of which fail
on the pre-change library); a `multiply_cases` beside them is the same
construction over `0F AF /r` and `F7 /4`.

## What was wrong with the REPORTER, and it is the whole of why this doc said
## "the census is clean"

Four defects, all silent, all in the reporting path rather than in the harness,
and the two that decided every other number here come first.

**1. `minimise` compared every prefix against the FULL program's model result.**
`Program.prefix` kept its parent's `index`, and that index is the program's
NAME in both directions: `lean_source` declares `code_<index>` /
`mem_<index>` / `init_<index>` and `run_model` keys its table by it. So a
minimisation batch was N programs claiming one name. Lean rejects the second
`def code_N` — **and still evaluates every `#eval!` against the first**, so the
file printed N copies of ONE program's answer and `evaluate` paired each
prefix's hardware dump with it. Measured on the pre-fix tree,
`-n 16 --ninstr 6 --seed 5`:

```
x86-64 model fuzz: 16 programs, ninstr=6 seed=5
  AGREE 9   FAULT 1   WRONG 6
minimising 6 discrepancies ...
  AGREE  (2 instructions)
    add RDI, R8; setae R8
```

**Six `WRONG` rows minimised to six two-instruction programs that AGREE**, and
the printed verdict contradicted the reported one in every case — so the
"reduced program … is what belongs in a regression test" was a program that does
not fail. The fix is three lines and two guards: `prefix` gives a derived
program its own index (`_FRESH_INDEX_BASE`, because a minimisation batch must
not collide with a corpus of any size), `lean_source` **raises** on two programs
with one index, and `run_model` treats a Lean `: error:` as fatal rather than
reading a partly-elaborated file's answers as verdicts — a missing `#eval!` and
a computed one look alike otherwise, which is B22's shape.

**2. The `setcc` class only fired when EVERY instruction was a `setcc`, and its
byte test could not see a REX prefix.** The
rule read `texts[-1]` for the destination and required
`all(t.startswith("set") for t in texts)`. That is true of the census's
one-instruction cases and false of every random program, so any random program
containing one anomalous `setcc` was reported `WRONG` — six of sixteen at seed 5
— with the module docstring's promise ("counted separately, named, and excluded
from the exit status") false and the tool exiting 1. The rule now reads the
BYTES (`0f 9x c5`/`c6`/`c7`, which is what §2 below measured) and asks whether
the disagreement is **exactly what that instruction's misbehaviour explains**:
every differing field is a general register, each differing in exactly one of its
eight bytes, and every register among them is either the destination or the
collateral byte the doc's table records (`c5` → byte 1 of `rcx`, `c6` → byte 1
of `rdx`, `c7` → nothing). That is an attribution, not a resemblance: a 32-bit
operation differs in four bytes, a memory store is a `mem[...]` field, flags are
named fields, and a `setcc` into a destination that behaves (`0f 9x c4`, `rm` =
`rsp`) is not this class. All four are pinned as counter-cases in
`test_x86_64_model_fuzz.py::TestTheVerdictIsAboutTheModel`.

**The `mul`/`imul` rule is now attributed rather than widened, and it is
attributed to the program's LAST FLAG-WRITING INSTRUCTION** (decoded with the
project's own decoder, from the FORM names, so a form the decoder renames cannot
leave it stale). The flags a run ends with are the flags its last flag-writing
instruction set; a `movabs` between the multiply and the end of the program moves
no flag, so "the last instruction" would miss the very rows this exists for, and
"one of them" would attribute flags to a multiply that something overwrote. The
rule it replaced — every instruction of the program must be a `mul`/`imul` — is
true of a one-instruction census case and false of every random program, which is
the whole of the bug.

**And the rules are applied PER FIELD, because a program can contain two of these
at once** (a `cqo`/`idiv` pair writing RAX/RDX beside a `setcc` into `rsi`
writing RSI is two anomalies, and a whole-row rule could answer neither). A field
is explained when it is:

* a flag and the last flag-writer is a multiply or a divide;
* RAX or RDX and the program contains a register-form `div`/`idiv`;
* a one-byte difference in a `setcc` destination the doc's measurement names, or
  in the collateral byte that encoding writes instead;
* a one-byte 0/1 difference in ANY `setcc` destination when a flag differs in the
  same row — a `setg r8` after this host's mislabelled ZF is the same defect one
  step later;
* the destination of a three-operand `imul r64, r64` (the class in the head's
  table); or
* **derived from one of those**, by the program's own instructions: `mov`,
  `movq xmm, r64`, a store into the compared window, and the ALU and shift forms
  whose result is a function of one operand alone. That last list deliberately
  EXCLUDES the multiply and the divide — a product is not a function of its
  factors in the sense that propagates a difference — and the propagation is read
  off the decoder's operands rather than guessed from the field names, so an
  unrelated difference in `mem[…]` has nothing to match and stays a model verdict.
  The memory half needs the window's own arithmetic: both reserved bases point at
  `MEMBASE`, which is `DATA_N // 2` bytes INTO the window, so a store at
  `[r13 + d]` is the `mem[…]` field holding window offset `DATA_N // 2 + d`.

**The REX prefix is the fourth reporter defect and it is in the same rule.** The
anomaly is three ModRM bytes — `0f 9x c5`-`c7`, `rm` = `rbp`/`rsi`/`rdi` with no
extension — and `41 0f 94 c7` is `sete r15`: the same three bytes with `REX.B`
extending `rm` from 7 to 15. A byte scan that cannot see the prefix calls that
one the anomaly and absorbs a real model bug behind it, which is the one thing a
verdict class must not do. The scanner is the decoder now.

**Measured after all four, the same commands the doc already names:**

```
$ python3 formal/x86_64_model_fuzz.py -n 16 --ninstr 6 --seed 5
  AGREE 9   FAULT 1   HARNESS 6      (was WRONG 6)                       exit 0
$ python3 formal/x86_64_model_fuzz.py --census --per-form 3 --seed 11
  FAULT 1   HARNESS 9, no WRONG, no NORUN                                  exit 0
$ python3 formal/x86_64_model_fuzz.py -n 48 --seed 1
  AGREE 28  FAULT 3  HARNESS 16  NORUN 1      (was HARNESS 12  WRONG 5)
```

and every minimised row now reproduces: the verdict printed beside a reduced
program is the verdict that program gets on its own, which is the property the
file's own docstring says the reduction exists for.

**3. `run_model` read a partly-elaborated Lean file as answers.** Its parser
takes every line that starts with a digit, and Lean prints the `#eval!` results
it could compute whether or not the rest of the file elaborated — so a rejected
declaration produced answers that belonged to a different program, and a program
whose own `#eval!` had failed was simply absent, which reads as `NORUN-MISSING`
rather than as a file that would not build. `: error:` now raises, with the
first diagnostic in the message. That is three lines and it is the guard that
makes fix 1 visible: the duplicate `code_N` errors were in the output the whole
time.

## The `#DE` this harness never raises, and the model gap behind it

**Found while reading what fix 1 unmasked, and it is the same shape as the two
above: a disagreement no x86-64 CPU can produce, this time in the trap rather
than in a value.** All five `WRONG` rows of `-n 48 --seed 1` reduce to a `cqo` /
`idiv r64` pair whose 128-bit quotient does not fit in 64 bits. Measured, one
instruction at a time, on the 10-instruction reduction (the model's answer and
the hardware's, at each prefix):

| prefix | last instruction | RAX hw → mdl | RDX hw → mdl |
|---|---|---|---|
| 8 | `mov rcx, 0x1` | `f2a74de452e6b438` → same | `0c5c7fd0a6a3a450` → same |
| 9 | `cqo` | unchanged | **`ffffffffffffffff` → same** |
| 10 | `idiv rcx` | **`f2a74de452e6b438` → `0000000000000000`** | `ffffffffffffffff` → `0` |

So `cqo` agrees exactly, and at the `idiv` the hardware leaves RAX alone and
writes RDX = 0 — which is what a 64-bit dividend would give. The 128-bit value
is `−2^64 − 0x0d5b21bad29b47c8`, the divisor is 1, and the quotient does not fit
in `Int64`, so **`IDIV` must raise `#DE` and write nothing**. Two independent
confirmations that it must:

* the same three bytes in a **static** image, hand-written assembly, divisor in a
  register `cltq` does not touch: `Floating point exception`, exit 136;
* the x86-64 manual's rule, which is a range check on the quotient.

And in the harness's own context — `setcontext` into an `mmap`'d RWX page, the
context this doc's other two classes are already about — **no trap is raised and
no `#DE` reaches the harness's `SIGFPE` handler** (there is no `F` line for the
program; it reaches the dump stub). That is the third instruction whose result
differs in this context, and the doc's own closing question ("the last word needs
hardware this tree does not run on") has the same answer for it as for the other
two: it is the host, not `lib/X86.lean`.

**What this is NOT, and the two things it does decide.** It is not a licence to
absorb the row: the model's own answer is wrong too, and in the OTHER direction.
`x86_idiv128` returned the quotient of an arbitrary-precision `Int` with no range
check, so the model wrote a value where the instruction faults. **That half is
FIXED (2026-10-05, `work/formal40-7`)** — `x86_div128`/`x86_idiv128` return `none`
for a quotient outside 64 bits, which is the meaning `none` already had for a
zero divisor and is what `#DE` means — and it is checked against exact integer
arithmetic in `formal/x86_64_model_coverage_test.py`'s new divide table (16
cases, 7 of which fail on the pre-change library). What is left here is not the
model.

## The fourth class: `idiv` is not a 128-bit divide on this host, and it is not
## the harness's context

**Measured with hand-written assembly, no compiler in the register setup, in an
ordinary statically linked binary — not in the fuzzer's `mmap`'d RWX page:**

```asm
    movabsq $0xe149a83728fa361a, %rax
    movabsq $0xffffffffffffffff, %rdx     # what `cqo` writes for a negative RAX
    movabsq $0xb9559250d09dfa6c, %r9      # the divisor
    idivq %r9
```

| where | quotient | remainder |
|---|---|---|
| **exact integer arithmetic** | `0000000000000004` | `fbf35ef3e6824c6a` |
| **`lib/X86.lean`'s `x86_idiv128`** | `0000000000000004` | `fbf35ef3e6824c6a` |
| this host, `arch -x86_64` | `0000000000000000` | `e149a83728fa361a` |

The host's remainder is the dividend's own low word and its quotient is 0 —
which is the answer for a **64-bit** division of RAX by the divisor, so the
upper half of the dividend is not reaching the divide. (`|remainder| <
|divisor|` holds for the host's answer, 1.6e19 < 5.1e18 does **not**, so it is
not a division of anything.)

**How wide it is: 8 of 28 register triples disagree with exact arithmetic**, and
every one of the 8 has a negative RAX of large magnitude — which is the shape a
random dividend has and the shape `udivmod`'s and `floordiv`'s do not, which is
why `formal/x86_64_model_test.py` agrees on all 52 examples and cannot be used
as the oracle for this class:

```
rax=0000000000000001 rdx=0000000000000000 d=0000000000000007   OK
rax=0000000000000001 rdx=ffffffffffffffff d=0000000000000007   OK
rax=000000000000000a rdx=0000000000000000 d=0000000000000007   OK   (1 rem 3)
rax=000000000000000a rdx=ffffffffffffffff d=0000000000000007   OK
rax=0000000100000000 rdx=0000000000000000 d=0000000000000007   OK
rax=7fffffffffffffff rdx=0000000000000000 d=0000000000000007   OK
rax=e149a83728fa361a rdx=0000000000000000 d=0000000000000007   WRONG
rax=e149a83728fa361a rdx=ffffffffffffffff d=0000000000000007   WRONG
rax=ffffffffffffffff rdx=0000000000000000 d=0000000000000007   WRONG
rax=ffffffffffffffff rdx=ffffffffffffffff d=0000000000000007   WRONG
… and the same pattern for the second divisor
```

**What follows for this file, and it is a limit rather than a fix.** Two
consequences, and the second is the one that costs:

1. **A `WRONG` row whose only difference is an `idiv`/`div` register pair is not
   a model verdict on this host**, and the fuzzer says so rather than reporting
   it: `_impossible_on_hardware` gains this class with the shape "every
   differing field is RAX or RDX and the program's bytes contain a group-3
   `F7 /6` or `F7 /7`". It is an attribution rather than a resemblance in the
   same sense the `setcc` rule is — the two registers a divide writes are named
   by the instruction — and it is still a rule that can absorb a real `idiv`
   model bug, so **the arithmetic check is the one that has to carry that
   coverage**, and it now does (`divide_cases` in the coverage test, which is
   why that table's docstring says the CPU is not an available oracle).
2. **`formal/x86_64_model_test.py` cannot see an `idiv`/`div` model bug whose
   dividend has a large negative low half.** That is a real hole in the only
   hardware differential this model has, and it is not closed by anything here:
   closing it needs either native x86-64 hardware or a second arithmetic oracle.
   The arithmetic table is that oracle for the divide itself, and it is not one
   for `x86_step`'s decode of the instruction around it.

## Status 2026-10-05 (`work/formal28-6-r2`): the harness is EXONERATED by
## measurement, and the `setcc` class is one DECODE rather than three odd
## registers

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
