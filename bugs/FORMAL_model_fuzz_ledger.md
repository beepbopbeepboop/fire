# FORMAL_model_fuzz_ledger: what `tools/formal_model_fuzz.py` has measured

**This is the ledger for the arm64 MODEL-vs-HARDWARE differential harness.** One
row per sweep, and then one entry per finding with what it turned out to be.
It exists because the tool's own output is a tally on stdout and a set of
generated files in a temp directory, neither of which anybody reads next week:
`bugs/FORMAL_fuzz_ledger.md` is the same document for `tools/formal_fuzz.py`
(the program-level differential) and this one is its arm64-model counterpart.

A row here is a MEASUREMENT of a run, never a target. What makes a row worth
reading is the mix beside it: `shifts` 60/60 with nothing in it says the six
shift instructions agree with the CPU over the corpus, and `memreg` 0/60 with
99 refusals says nothing at all about the register-offset load and store — it
says the model cannot step them.

## 1. What the tool is, and what a number in this file means

`python3 tools/formal_model_fuzz.py` builds one generated Mach-O function per
case, runs the case's instructions on the CPU, runs the same BYTES through
`arm64_step` in Lean, and compares X0-X30, SP, NZCV, the pc and every byte of
the comparison window. Six verdicts, and the distinction between them is the
point:

| verdict | meaning | is it a model bug? |
|---|---|---|
| `AGREE` | both engines ran to the end and the state is identical | no |
| `WRONG` | both ran to the end and the state DIFFERS | **yes** |
| `NOSTEP` | `arm64_step` answered `none` for an instruction the backend emits | **yes** — a refusal, and a proof that cannot step an instruction is a proof about nothing |
| `FAULT` | the CPU took a signal | no — the pool asked for an address outside the window, or for an instruction the architecture traps on |
| `ENC-MISMATCH` | `formal/arm64.py` and `as -arch arm64` disagree about the instruction | no — an encoder-table finding |
| `ENC-FAIL` | `as` refused the pool's own text | no — a pool bug |

Machine: 18-core arm64 macOS 25.6, clang 21, Python 3.14.7. Every run under
`python3 tools/memslot.py --gb 4`, peak **2.3 GB** across all of the runs
recorded here (`MEMLIMIT` well inside the 3-4 GB line in `BLOW.md`).

## 2. Sweeps

| date | mixes | seed | cases | tally | what came of it |
|---|---|---|---|---|---|
| 2026-10-04 | all 10 | `model-fuzz` | 60 | AGREE 26, WRONG 9, NOSTEP 13, FAULT 10, ENC-MISMATCH 8 | the harness itself; every non-`AGREE` class below was a defect in the POOL or in the harness, and each is listed in §3 |
| 2026-10-04 | all 10 | `sweepB` | 297 | AGREE 152, WRONG 45, NOSTEP 99, FAULT 0, ENC-MISMATCH 0 | the first clean sweep: every remaining finding is a fact about `arm64_step` |
| 2026-10-04 | per-mix, 60 each | `ledgerA` | 596 | AGREE 238, WRONG 70, NOSTEP 172 | the coverage table in §2.1 |

### 2.1 Per-mix coverage (60 cases per mix, seed `ledgerA`)

| mix | AGREE | WRONG | NOSTEP | what the NOSTEPs are |
|---|---|---|---|---|
| `shifts` | 60 | 0 | 0 | — the six shift instructions agree over the whole corpus |
| `alu` | 50 | 10 | 0 | |
| `ext` | 39 | 21 | 0 | |
| `muldiv` | 47 | 13 | 0 | |
| `flags` | 21 | 14 | 25 | `cmn` |
| `select` | 10 | 8 | 42 | `csel`, `cmn` |
| `mem` | 11 | 4 | 45 | `strh`, `ldrsw`, `ldrb`, `ldrh`, `ldrsh`, `ldr w`, `str w`, `ldur`, `stur` |
| `memreg` | 0 | 0 | 60 | `ldr x, [xn, xm]` and `str x, [xn, xm]` |

`shifts` agreeing is worth a row of its own: `bugs/FORMAL_arm64_right_shift_
is_always_arithmetic.md` is the history this tool would otherwise have
reproduced, and over 60 cases of `lsl`/`lsr`/`asr` immediate and register forms
with the boundary-valued operands §4 describes, the model's shifts match the
CPU on every one. That is a measurement, not a proof.

## 3. Defects in the HARNESS, found by the harness

Kept here rather than in a bug doc because each is fixed and each cost more
than the model bugs did. All of them are the same class: **a disagreement that
was about the harness and would have been filed as a model bug.**

1. **The flag probe measured from a code address.** The epilogue recorded SP
   and the pc into X16 before the four conditional branches that read NZCV,
   so the probe's baseline was the pc rather than the case's X16, and the
   reconstructed flags were a function of where the harness was loaded. The
   probe now runs first and X16's dumped slot is its baseline.
2. **One `9:` for three branches.** A numeric local label is reused by
   definition, so `b.mi 9f` / `b.eq 9f` / `b.cs 9f` with a single `9:` at the
   end skip ALL THREE `add`s. The reconstructed flags came out with N=1 and Z=1,
   a combination no subtraction can produce. There is now a `9:` after every
   `add`.
3. **`MSR`/`MRS NZCV` do nothing in EL0 here** (macOS 25.6, measured for all
   sixteen values and every source register). The harness cannot set the
   initial flags and cannot read the final ones that way, so the initial flags
   are established by a `cmp` both engines execute and the final ones are read
   back with conditional branches. This is also better evidence than an `msr`
   would have been.
4. **The memory window was anchored at SP, so an SP write-back moved it** —
   28 SIGBUS/SIGSEGV in the `model-fuzz` sweep, every one of them this file's
   fault. The write-back forms are out of the pool and the gap is written down
   (§4).
5. **`x31` is not a base register in assembly text.** `[x31, #8]` is rejected
   by `as` ("invalid operand for instruction"), which took the whole 297-case
   batch down with it. The pool now spells the base `sp`.
6. **Two `movz` encoders with the same idea and different widths.**
   `encode_movz_xd_imm` emits the 32-bit word (`0x52800000`) and
   `encode_movz_xn_imm` the 64-bit one (`0xd2800000`); the pool had paired the
   32-bit encoder with the text `movz xN`. See
   `bugs/FORMAL_arm64_movz_encoder_is_named_xd_and_encodes_wd.md`.
7. **`and xN, xM, #W` where `W` is a MASK WIDTH.** `encode_and_xd_xn_imm`'s
   third argument is the mask width (8/16/32 → `#0xff`/`#0xffff`/
   `#0xffffffff`), not an immediate, and the pool printed the width.
8. **`LDP` with `Rt == Rt2` is UNPREDICTABLE**, and `encode_ldp_xn_xt_sp`'s
   argument order and scale are both the other way round from its name — see
   §4 and its bug doc.
9. **`MOV Xd, Xn` has two encodings.** `encode_mov_zr_xn` emits `ADD Xd, Xn,
   #0` where the assembler emits `ORR Xd, XZR, Xn`; 60 of 297 cases in one run
   were that single fact reported as an encoder defect. The encoder cross-check
   compares DISASSEMBLY, through a small table of A64 aliases.
10. **A byte comparison is not an instruction comparison.** The cross-check now
    disassembles both words with `otool -tv` and compares the mnemonics, so
    `movz w0, #1` vs `movz x0, #1` — a real finding — is still caught.

## 4. What is NOT covered, and why

Written down because a tally that reads as coverage is worse than a gap that
names itself:

* **The SP write-back pairs** (`STP Xt1, Xt2, [SP, #-imm]!`, `LDP Xt1, Xt2,
  [SP], #imm`). `arm64_step` has arms for both (`0xa9800000`, `0xa8c00000`);
  this harness cannot compare them because SP is where its window is anchored.
* **`LDP Xd1, Xd2, [SP, #imm]`** (`0xa9400000`), which the model DOES step. No
  wired encoder emits it, so a pool built from the wired encoders cannot produce
  it — see §3.8 and the LDP bug doc.
* **Every branch and call**: `B`, `BL`, `CBZ`, `CBNZ`, `TBZ`, `TBNZ`, `B.cond`,
  `BR`, `BLR`, `RET`. A case is straight-line, so the pc check is `+4n` on both
  sides and a branch would take the two engines to different places. The
  conditions themselves are covered indirectly, through NZCV and through
  `csel`/`cset`.
* **`MSR`/`MRS`, `SVC`, `ADRP`, `ADR`** — none is emitted by a lowering, and
  `MSR`/`MRS` do not work in EL0 on this platform anyway.
* **Anything at a non-zero pc base.** The model's SP and pc are compile-time
  constants and the harness's are runtime addresses, so the memory window and
  the pc delta are compared in OFFSETS. Every address a case touches is inside
  the window by construction, which is a property of the generator and is
  stated in `gen_mem`'s docstring.

## 5. The findings, minimised

Each row is a one-instruction counterexample produced by `--minimise`, which
keeps the case's flag seed (§ the minimiser's docstring) and requires the
reduced case to fail the SAME WAY as the original — without both of those it
will happily delete the guilty instruction and report a different bug.

| instruction | model | hardware | what it is |
|---|---|---|---|
| `movk x23, #54219, lsl #0` | `ffffffffffffffff` | `ffffffffffffd3cb` | MOVK modelled as an OR, so it cannot insert a halfword into an already-set field |
| `sxtb w0, w3` | `ffffffffffffffa5` | `00000000ffffffa5` | the W-destination sign-extension is not truncated to 32 bits |
| `sxth w5, w6` | `ffffffffffffc834` | `00000000ffffc834` | the same, 16-bit |
| `cmn x0, x3` | — | — | no arm: `arm64_step` returns `none` |
| `csel x1, x5, x1, lt` | — | — | no arm |
| `ldrb w27, [sp, #27]` | — | — | no arm |
| `ldrsb x29, [x9, #11]` | — | — | no arm |
| `ldrsw x25, [x9, #24]` | — | — | no arm |
| `ldrsh x0, [x17, #28]` | — | — | no arm |
| `str x29, [x9, x17]` | — | — | no arm (register-offset store) |

The full set of refusals is §2.1's table; `bugs/FORMAL_arm64_step_cannot_step_
nine_wired_encodings.md` carries the count and the encoders.