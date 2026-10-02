# `struct.pack` for a format naming 8 values was refused at the CALL SITE, so `struct.mojo`'s own "return an empty list" was unreachable

## Status

**FIXED on arm64, measured before and after on this tree, and `test_struct_formal.py` is
148/148.** x86-64 is a separate wall and still refuses; it is stated below with
its own next step. The `expect=` marker on `formal-struct` in `tools/suite.py`
is the kind that retires itself — `test_suite.py` fails any `expect=`-marked
test that starts passing — so that row has to come off with this, and the
registry is not this change's to edit.

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

## The next step, exactly

1. x86-64's stack area, in `formal/x86_64_codegen.py`'s `_emit_call` and its
   prologue — the same four corners as arm64's, against
   `formal/x86_64.py`'s `ARG_REGS` (six). The offsets are `[RBP + 16 + 8k]` for
   the same reason arm64's are `[X29 + 16 + 8k]`, provided x86-64's spills are
   also RBP-relative; **verify that before writing it**, it is the one
   assumption the port rests on.
2. THEN widen `formal/hostmods/struct.mojo`'s `pack` from five value slots to
   eight, with the slots DEFAULTED (a slot past `_nvalues(fmt)` is never read,
   so a caller packing a short format has nothing to say about it) and with
   `_nvalues(fmt) > 5` becoming `> 8`. That makes the module's decline
   reachable for the first time, and it CHANGES what `test_struct_formal.py`'s
   `UNSERVABLE` group is asserting: `<HHHHHH` (6 bytes) and `<4sBBBBBBB5x`
   (16 bytes) are both in the module's buffer-size ladder and would become
   PACKED rather than declined, while `<IIQQQQQQ` (56 bytes) has no ladder
   entry and would still decline. The group would need re-deriving, not
   deleting.
3. Do steps 1 and 2 together or not at all: widening `pack` without the SysV
   area breaks `test_the_module_builds_on_both_backends`, which is a
   registered check of the module rather than of the ABI.

## Related

- `formal/arm64_codegen.py`'s `_load_home_from_stack` / `_emit_call`'s outgoing
  area — the two ends of the one convention, kept together in the commit.
- `bugs/FORMAL_known_limits.md` — the audit of which sweep refusals are true
  claims. This one was true, and it is not sweep residue, which is why it has
  its own doc.
- `tools/suite.py`'s `formal-struct` row carries `expect=` naming this file.
  That row must lose its marker with this change or the suite reports a
  green test as a failure.
- `bugs/FORMAL_struct_pack_unservable_format_is_refused_at_the_call.md` is the
  same finding filed from another branch, with the design question behind it
  spelled out. It is deleted with this change.
