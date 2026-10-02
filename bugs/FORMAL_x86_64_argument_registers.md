# FORMAL_x86_64_argument_registers: x86-64's six integer argument registers is the largest x86-64 parity gap, and lifting it is a real ABI change rather than a spill

**Area:** FORMAL (x86-64 codegen + the proof model). **Status: OPEN — measured,
not fixed, and the measurement is the point.** Found while working
`construct:x86-64-parity` on 2026-10-01, when the other x86-64 parity items had
closed and this was the largest thing left.

**Re-measured 2026-10-01, and the size of the job grew.** The codegen half is as
described below; the PROOF half was not in this document at all, and it is the
larger one: `lib/ProofLib.lean`'s `MojoFunc`/`evalFunc` bind one parameter, so a
two-parameter function — which BUILDS on both architectures today — produces a
proof file that does not elaborate. `bugs/FORMAL_ast_bridge_binds_only_the_first_parameter.md`
has the measurement and the order; "The exact next step" below carries the parts
that belong here (the stack-slot reservation and the disp32 gap in the x86-64
model).

## What it is

SysV AMD64 passes six integer arguments in registers; AAPCS64 passes eight. Both
emitters refuse a function or a call with more arguments than their register
file holds, rather than passing the rest on the stack:

| | arm64 | x86-64 |
|---|---|---|
| limit | 8 (`formal/arm64_codegen.py`'s `_ABI_ARG_REGS`) | 6 (`formal/x86_64.py`'s `ARG_REGS`) |
| callee end | `formal/arm64_codegen.py:997` | `formal/x86_64_codegen.py:862` |
| call end | `formal/arm64_codegen.py:5938` | `formal/x86_64_codegen.py:5659` |

So a program is a program on one architecture and a diagnostic on the other,
which is the shape this whole family of documents is about. Both ends refuse:
the callee half is what makes the call-site half honest, because a callee
reached with no call site at all — a dylib export, a reflection-resolved call —
would otherwise read a parameter past the register file.

## What it costs, measured rather than counted

**51 of the 623 files in `.tmp/sweep-x86-4.txt` carry this message** — more than
any other x86-64-specific cause in that log, and the whole of the x86-64/arm64
difference for `formal/hostmods/re.mojo` and `formal/hostmods/hashlib.mojo`.
Re-measured on this tree, both modules build on arm64 and are refused on x86-64
with exactly this message, and no other construct is involved:

```console
$ python3 fire.py build --formal --no-prove --backend=arm64 -o /tmp/re formal/hostmods/re.mojo
Built: /tmp/re  [arm64/macho]
$ python3 fire.py build --formal --no-prove --backend=x86_64 -o /tmp/re formal/hostmods/re.mojo
build: sub: 7 parameters exceeds the 6 the formal x86-64 ABI passes in registers
```

`FILES BLOCKED` is an upper bound and the task asked for the marginal effect to
be measured before investing, so: **of those 51, only 2 would become `pass`.**
Cross-referenced against `.tmp/sweep-arm-final.txt` (the arm64 run of the same
623 files):

| arm64's verdict for the file | how many of the 51 | what it means here |
|---|---|---|
| `not-answerable/host-import` | 39 | a CPython host module; unbuildable on x86-64 too, for a reason that has nothing to do with arity |
| `codegen` | 7 | the file's own refusal, which the arity fix merely exposes |
| **`pass`** | **2** | `formal/hostmods/re.mojo` and `formal/hostmods/hashlib.mojo` |

So the honest number is **2 files, not 51**, and the fix is worth stating that
way: the 49 others are a measurement artifact of a chained refusal, and no
change to this limit moves them into any rate. A sweep run that had lifted it
would report two new passes and forty-nine new next-findings — which is the
correct outcome and worth almost nothing in the headline.

`re.mojo`'s five wide functions and `hashlib.mojo`'s two, by parameter count:

```
formal/hostmods/re.mojo:      sub(7)  _subwalk(8)  _emit(7)  _gref(7)  _subfill(7)
formal/hostmods/hashlib.mojo: b2_g(7)  put6(8)
```

None of the 51 is in the new-modular stdlib, so this limit costs the stdlib
nothing measurable today. It is a repo-and-hostmods problem, not a coverage-rate
problem, and that is worth knowing before anyone prices it as the latter.

## Why this is NOT a spill, and why the census doc's suggestion is not enough

The census that first measured this (one row per `formal/hostmods` module, per
backend) suggested either annotating an argument as spilled or restructuring the
two modules' wide functions. That census is now `test_formal_hostmods_census.py`
— the table is a test — and both of those modules have since had their wide
functions narrowed, so `fnmatch.mojo`'s `match_core(7)` is the only row left.
Both suggestions are real and both are worth saying precisely what they do:

* **Restructuring `re.mojo` and `hashlib.mojo`** fixes the 2 files and costs
  those modules their signatures. `_subwalk(8)` and `put6(8)` are internal, so
  the shape is the author's choice — but it makes a MODULE source narrower to
  suit a backend limit, and nothing in the language says these functions are
  over-wide.
* **Annotating a spill** is the wrong shape for a reason the tree already
  records twice: a spilled-argument convention is an ABI fact and belongs in
  the manifest signature next to the return type, and it has to be honoured by
  BOTH backends, with arm64 continuing to accept a call whose spilled argument
  the caller did not pass. `doc/ABI.md` is the contract, and it currently says
  nothing about arguments at all beyond "no hidden arguments".

**The real fix is the third option, and it is what both ABIs already do.** SysV
AMD64 puts arguments 7+ on the stack at `[rsp+0]`, `[rsp+8]`, … and AAPCS64 puts
arguments 9+ at `[sp+0]`, `[sp+8]`, … The emitters model an ABI smaller than
the real one on both machines; the refusal is a missing stack-argument
convention, not a property of either ABI. Implementing it is the same work
twice in the codegen **and a change to the proof model on top** — see "The exact
next step" above, which is where the size of that second half is measured — and
it changes an ABI contract, which is why it is filed rather than done here.

## The exact next step

**One correction first, measured 2026-10-01, because it changes the size of the
job and the doc's §5 sentence understates it: this is not "the same work twice"
in the emitters.** Lifting the limit makes a SEVEN-argument function legal, and
the proof side cannot state anything about seven arguments — or about two.
`lib/ProofLib.lean` has three one-parameter assumptions that are the same
assumption:

| where | shape |
|---|---|
| `lib/ProofLib.lean:745` | `inductive MojoFunc \| mk (name) (param : String) (body)` — one `param` |
| `lib/ProofLib.lean:882` | `evalFunc … (arg : UInt64)`, environment `fun name => if name == param then arg else 0` — every other parameter evaluates to **0** |
| `formal/arm64_proof_gen.py::_go_apply` | read `binders[0]`, applied one argument |

Measured on this tree, both generators, for `def f(a0, a1): return a0 + a1`:

```lean
def f_go (a0 : UInt64) (a1 : UInt64) : UInt64 := ...
def mojo (n : UInt64) : UInt64 :=
  f_go n                                  -- argument-count error
```

So a two-parameter entry point — a legal program, which **builds on both
architectures** (`def main(n: Int, m: Int) -> Int: return n + m`) — produces a
proof file that does not elaborate, with the error three definitions away from
the line that is wrong. **`bugs/FORMAL_ast_bridge_binds_only_the_first_parameter.md`**
is the measurement and the order; a generator guard landed with it so the
ill-typed file is no longer written, but the fix is `lib/ProofLib.lean`, and its
hardest step is that `test_input` (one `UInt64`, from `compile_formal`'s
`test_input=`) has to become a tuple, which is a `formal/build.py` change and not
a generator one. Read that doc before starting step 1 below: the codegen half and
the proof half are one change, not two, and the codegen half is the easy one.

The codegen steps, unchanged and still correct:

1. **x86-64 call site** (`formal/x86_64_codegen.py:5939`): replace the
   `len(args) > len(ARG_REGS)` refusal with a push of the surplus. The
   evaluation discipline already exists and is correct — arguments are evaluated
   left to right onto 16-byte slots and popped in reverse into the argument
   registers precisely so that evaluating argument *i+1* cannot clobber
   argument *i*'s register — so the surplus is pushed BEFORE the register pops
   and lands at `[rsp+0]`, `[rsp+8]`, … The 16-byte slot size is a problem and
   is also the solution: SysV requires 8-byte spacing, and `_SLOT` is 16, so the
   surplus needs its own push rather than a slot.
   **The one detail the step below does not fix, added by measurement:** the
   surplus area has to be reserved BEFORE the argument slots are pushed, because
   the register pops restore RSP and a value written at `[rsp+0]` during the pop
   loop would be overwritten by the next pop. So: `sub rsp, 8*surplus` (rounded
   UP to a multiple of 16, with the padding placed at the HIGHER addresses so
   argument 6 still lands at `[rsp+0]` — see step 2), then evaluate and pop, and
   write each surplus argument at `[rsp + pad + 8*(i-6)]`. SysV requires RSP to be
   16-byte aligned at the `call`, and `8*surplus` is not a multiple of 16 for an
   odd `surplus`, which is what the rounding is for. `formal/x86_64.py`'s
   `_rm_disp` already emits a **disp32** for `|disp| > 127`, so the encoder needs
   no change — but `lib/X86.lean` has **zero** disp32 forms (five `mov … mem` step
   theorems, all disp8), so the *model* returns `none` for a stack read beyond
   offset 127 and that has to be added alongside.
2. **x86-64 callee prologue** (`:993`): read parameter *i* for *i* >= 6 from
   `[rbp + 16 + 8*(i-6)]` — 16 because the return address is at `[rbp+8]` and
   the saved RBP at `[rbp+0]`. The `_emit_extend` normalization the register
   path applies applies unchanged, since a stack argument arrives in exactly
   the same condition.
3. **The returned-frame hidden word** is one more argument and moves with them:
   `model.RETURNED_FRAME_MAX_ARGS` is 6 and `test_returned_frame_layout.py`
   pins it (`the_budget_matches_x86_64_argument_registers`), so raising the
   plain limit without deciding what the budget becomes leaves a documented
   number false about the file it is reported against. **Decide the budget
   first.**
4. **Then arm64**, identically, and the shared budget becomes `min(6, 8)` = 6
   for the frame convention and 6 for the plain arity limit — which is the
   number every message already quotes, so nothing user-visible changes except
   that 7- and 8-argument programs build on both. **This step's proof half is
   the same one**: `lib/ProofLib.lean`'s `Arm64State`/`X86State` are separate
   models but the `MojoFunc`/`evalFunc` arity is shared, so it is done once.
5. `test_formal_run.py`'s `nine_arguments_refused` and
   `nine_parameters_refused_without_a_call_site` pin the refusal at NINE and
   pass with the needle `"9 arguments exceeds the"`. They stay green while the
   limit is 8 and go red at 9, so they are the anti-rot for step 1 — but a fix
   that lifts past 9 must convert them to positive cases rather than loosen the
   needle.

## What is NOT the next step, and was measured

Widening the check without implementing the spill does not even produce a wrong
image; it produces an `IndexError` out of the emitter, which the sweep
classifies as `backend-crash` — a verdict for a compiler bug, and the worst
class to have a coverage report full of:

```console
$ # `len(params) > 99` substituted for the x86-64 callee check
$ python3 fire.py build --formal --no-prove --backend=x86_64 -o /tmp/re formal/hostmods/re.mojo
build: tuple index out of range
  File "formal/x86_64_codegen.py", line 877, in _emit_function
    self.asm.emit(encode_mov_r64_r64(Reg.R11, ARG_REGS[i]))
IndexError: tuple index out of range
```

Worth recording because the obvious first experiment is exactly this, and the
resulting `IndexError` says nothing about the real work — it is a stack trace
from a table lookup, not a measurement of the fix's size.

## What this would buy, stated honestly

Two files pass on x86-64. `formal/hostmods/re.mojo` and
`formal/hostmods/hashlib.mojo` become usable on that target, which unblocks
`test_re_formal.py` and `test_formal_hashlib.py` from being x86-64-skipped —
those are two real test suites that currently run on one architecture because of
a message about six registers. That is the whole of the measurable benefit today,
and it is not nothing: a backend whose own host library is arm64-only is a
backend with no second opinion on itself.