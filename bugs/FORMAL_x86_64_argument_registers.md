# FORMAL_x86_64_argument_registers: x86-64's six integer argument registers is the largest x86-64 parity gap, and lifting it is a real ABI change rather than a spill

**Area:** FORMAL (x86-64 codegen). **Status: OPEN — measured, not fixed, and
the measurement is the point.** Found while working `construct:x86-64-parity`
on 2026-10-01, when the other x86-64 parity items had closed and this was the
largest thing left.

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

`bugs/FORMAL_x86_64_hostmods_that_do_not_build.md` §Failure 2 suggests either
annotating an argument as spilled or restructuring the two modules' wide
functions. Both are real and both are worth saying precisely what they do:

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
convention, not a property of either ABI. Implementing it is the same work twice
and it changes an ABI contract, which is why it is filed rather than done here.

## The exact next step

1. **x86-64 call site** (`formal/x86_64_codegen.py:5659`): replace the
   `len(args) > len(ARG_REGS)` refusal with a push of the surplus. The
   evaluation discipline already exists and is correct — arguments are evaluated
   left to right onto 16-byte slots and popped in reverse into the argument
   registers precisely so that evaluating argument *i+1* cannot clobber
   argument *i*'s register — so the surplus is pushed BEFORE the register pops
   and lands at `[rsp+0]`, `[rsp+8]`, … The 16-byte slot size is a problem and
   is also the solution: SysV requires 8-byte spacing, and `_SLOT` is 16, so the
   surplus needs its own push rather than a slot.
2. **x86-64 callee prologue** (`:862`): read parameter *i* for *i* >= 6 from
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
   that 7- and 8-argument programs build on both.
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