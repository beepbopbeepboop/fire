# `struct.pack` for a format naming 8 values was refused at the CALL SITE, so `struct.mojo`'s own "return an empty list" was unreachable

## Status

**arm64 is FIXED and the module's decline is reachable; x86-64 is a separate
wall that still refuses, and it is stated below with its own next step.
`formal-struct` is GREEN and its `expect=` marker is gone (2026-10-02,
`work/merge-bugs2`). What is left is the ABI, and only the x86-64 half of it.**

Three things moved, on two branches that did not see each other — and the
composition matters, because the second of them was written for a tree on which
the first had not landed:

1. **arm64 got AAPCS's stack-argument convention** (`d6b5dbb3`), which is the
   fix this document asked for and the one its "What landed" section describes:
   a call with a ninth argument builds on arm64, the argument arrives, and a
   caller that passes more than eight arguments is no longer refused. Measured
   on that branch with the base's 148-check suite: 148/148.
2. **The test no longer manufactures a 9-argument call** (`work/merge-bugs2`).
   The `UNSERVABLE` group used to pad a format's real value list to five *while
   keeping every real value*, so a format naming 8 values produced
   `pack(fmt, v0..v7)` — 9 arguments — and on the tree that commit was written
   on, the call was refused where this document says. It now truncates the value
   list to five first and then pads to five, so the call carries exactly the
   five values the module has slots for. That is not a smaller `struct.pack`
   hiding the bug: `struct.mojo` answers the FORMAT it was given
   (`_nvalues(fmt)`), not how many arguments arrived, so "five supplied, more
   wanted" is precisely the state the module is supposed to decline, and the
   empty-list assertion is now testing what it was written to test. It also
   makes the suite ARM64-INDEPENDENT, which matters now that the two backends
   answer a nine-argument call differently.
3. **A false refusal in `read_before_store` that made all five cases fail for an
   unrelated reason** (also `work/merge-bugs2`). The `_build_cfg` entry block
   was given a second, fictitious edge to whatever block the body ended on, so
   the fixpoint intersected every join with the entry's OUT set (the parameter
   seed) and any name the body stored unconditionally read as unstored. Every
   one of these five programs ends in `print(n)`, not `return`, which is the
   shape that triggers it — so all five failed on `'n' is read at line 11 before
   anything in this function stores it`, a name stored three lines above the
   read. Fixed by discarding `run`'s return value at `formal/model.py`'s
   `_build_cfg` entry; pinned by five new rows in
   `test_formal_read_before_store.py`.

Measured, `/opt/homebrew/bin/python3 test_struct_formal.py`, after 2 and 3 and
before arm64's convention landed: **154/154 checks passed, exit 0**, three
consecutive runs. On the composed tree it is 154/154 again — see the merge
commit's report; the denominator moved only because the suite grew by its own
harness self-test, never because a verdict moved.

The rest of this document is the record of what was found, what the convention
fixed, and why the remaining refusal is right.

## What was true, and what was wrong about it

`formal/hostmods/struct.mojo` declines a format it cannot serve by returning an
**empty list**, and its own docstring says so:

> A format naming more than five values cannot be packed here, and the three
> corpus formats that do — `<HHHHHH` (6), `<HHIQQQI` (7), `<IIQQQQQQ` (8) —
> return an empty list rather than a wrong answer.

`test_struct_formal.py`'s `UNSERVABLE` group pins exactly that, and pinning it
is the difference between a byte packer that declines and one that writes eight
plausible bytes into a Mach-O header.

The refusal that stood above it was **true about the register count and wrong
about the consequence**. arm64 passes eight integer arguments in X0..X7; the
ninth goes on the stack; and this path had no stack-argument convention, so the
call was REFUSED:

```
$ python3 test_struct_formal.py
FAIL  pack("<IIQQQQQQ") is refused, not wrong: build failed: build: call pack():
      9 arguments exceeds the 8 the formal arm64 ABI passes in registers
146/148 checks passed
```

The module carried a branch that could not be reached, and the test that exists
to pin it could only ever fail.

## What landed

AAPCS's stack-argument convention, both ends, on arm64
(`formal/arm64_codegen.py`). The design and the two places a mistake shows up
are in the commit (`d6b5dbb3`); the parts worth carrying here are the ones a
reader of this file would otherwise have to re-derive:

| | |
|---|---|
| **caller** | `_emit_call` `SUB SP` by a multiple of 16 for the outgoing area, store the STACK arguments into it, and only then spill and pop the register arguments into X0..X7 |
| **callee** | the prologue reads argument `8+k` from `[X29 + 16 + 8k]` — X29 plus the sixteen bytes of saved FP/LR, which is where the callee's SP was before the prologue moved it |
| **bound** | `_MAX_INCOMING_ARGS` = 24, a FRAME bound (every parameter past the eighth needs a home) and not an ABI one |
| **still refused** | a VARIADIC callee with arguments past the registers, because `_emit_variadic_area` lays the `...` tail out at the slots the stack arguments now occupy and nothing states an order between the two |

**The caller's ordering is the measurement worth keeping.** Storing the stack
arguments after the register spills looks equivalent and is not: the eight
`STP [SP, #-16]!` have already moved SP 128 bytes down, so every `[SP + 8k]`
lands in the register spill area. Measured, with the offsets correct for the SP
at the time:

```
nine(1,…,9)    ->  37      where the source says 45
ten(1,…,10)    ->  0       where it says 1000000010
```

The ninth argument read as ZERO — the exact wrong answer the original refusal
existed to prevent, arriving by a different road. A callee cannot tell a
dropped argument from a caller who passed zero, so this is the one answer that
must never appear.

`nine_t` (`return h`) is the row that pins the callee half, and it exists
because a stack slot holding a `char *` is the case a wrong offset is least
likely to be caught by: `[NINE][EIGHT][ONE]` reads all three of the first,
last and an in-between argument of a nine-`String` parameter function.

## What did NOT land, and why

**x86-64 still refuses a ninth argument.** Its System V convention passes six
integer arguments in RDI/RSI/RDX/RCX/R8/R9 and the rest on the stack, and that
stack area is a second, separate piece of work in
`formal/x86_64_codegen.py`. The two differ in their limit because the ABIs do,
not in what they do about it — which is what the pre-fix comment on arm64's
check already said.

This is pinned as a STATED limit rather than left to be discovered:
`test_formal_x86_64_parity.py`'s `X86_ONLY_REFUSALS` group builds x86-64 only,
requires the refusal, and deliberately does NOT require arm64 to refuse. If a
later change implements the SysV stack area, that case starts failing and says
why.

The reason the x86-64 half is left is arithmetic, not priority: a module both
backends compile has to fit the SMALLER convention (that is
`test_struct_formal.py`'s `test_the_module_builds_on_both_backends`, written
when `struct.mojo`'s signatures were first written to arm64's ceiling of eight
and the x86-64 build was refused outright). So widening `pack` past six
parameters requires the SysV stack area first, and the measurement above is
what the x86-64 half is worth.

## What is left, exactly

**arm64's half of the "give the emitter a stack-argument convention" step this
document asked for is DONE** — it is the "What landed" section above, `d6b5dbb3`
— so that step is off the list for arm64 and what remains is the same
convention against the OTHER register file, plus the widening it unblocks:

1. x86-64's stack area, in `formal/x86_64_codegen.py`'s `_emit_call` and its
   prologue — the same four corners as arm64's, against
   `formal/x86_64.py`'s `ARG_REGS` (six). The offsets are `[RBP + 16 + 8k]` for
   the same reason arm64's are `[X29 + 16 + 8k]`, provided x86-64's spills are
   also RBP-relative; **verify that before writing it**, it is the one
   assumption the port rests on.
2. THEN widen `formal/hostmods/struct.mojo`'s `pack` from five value slots to
   eight, with the slots DEFAULTED (a slot past `_nvalues(fmt)` is never read,
   so a caller packing a short format has nothing to say about it) and with
   `_nvalues(fmt) > 5` becoming `> 8`. This is no longer needed to make the
   module's decline REACHABLE — `work/merge-bugs2` made it reachable by calling
   `pack` with the five values the module has slots for, which is the state
   `test_struct_formal.py` now pins — so what widening changes is what the
   module can ANSWER. It CHANGES `UNSERVABLE`: `<HHHHHH` (6 bytes) and
   `<4sBBBBBBB5x` (16 bytes) are both in the module's buffer-size ladder and
   would become PACKED rather than declined, while `<IIQQQQQQ` (56 bytes) has no
   ladder entry and would still decline. The group would need re-deriving, not
   deleting.
3. Do steps 1 and 2 together or not at all: widening `pack` without the SysV
   area breaks `test_the_module_builds_on_both_backends`, which is a
   registered check of the module rather than of the ABI — and for the same
   reason it is still refused on x86-64 today, where a nine-argument
   `pack(fmt, v0..v7)` has no home in six registers.

**The smaller shape this document offered as the alternative was not taken, and
the reasoning for skipping it survives the composition.** It was: assert the
call-site *refusal* for the formats whose arity exceeds the ABI. The module's
in-band decline is reachable once the call carries the five values it has slots
for, so pinning the ABI instead would have frozen the emitter's ceiling as the
module's contract — a documentation change dressed as a fix. `struct.mojo`'s
docstring therefore needed no correction: it says five value slots because that
is what it has, not because that is all a caller may pass.

## Related

- `formal/arm64_codegen.py`'s `_load_home_from_stack` / `_emit_call`'s outgoing
  area — the two ends of the one convention, kept together in the commit.
- `bugs/FORMAL_known_limits.md` — the audit of which sweep refusals are true
  claims. This one was true, and it is not sweep residue, which is why it has
  its own doc.
- Registered as `formal-struct` in `tools/suite.py`, **with no `expect=`**
  since 2026-10-02: the marker was a declaration, not an excuse, and
  `test_suite.py` fails any `expect=`-marked test that starts passing, so this
  row retired itself the day the arity stopped being in its way. (The
  arm64-side half said the marker had to come off *with* the ABI change and
  that the registry was "not this change's to edit"; it came off on
  `work/merge-bugs2` instead, and the composed tree has the row the registry
  wants — no marker, suite green.)
- `bugs/FORMAL_struct_pack_unservable_format_is_refused_at_the_call.md` was the
  same finding filed from another branch, with the design question behind it
  spelled out. It is deleted, so this is the one document for this defect.
