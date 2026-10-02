# `struct.pack` for a format naming 8 values is refused at the CALL SITE, so `struct.mojo`'s own "return an empty list" is unreachable

## Status

**The module's decline is reachable again and `formal-struct` is GREEN — its
`expect=` marker is gone (2026-10-02, `work/merge-bugs2`). What is left is the
ABI wall, and only that: a call with more arguments than the target's registers
is still refused, because that refusal is right.**

What moved, in two halves that had to land together:

1. **The test no longer manufactures a 9-argument call.** The `UNSERVABLE` group
   used to pad a format's real value list to five *while keeping every real
   value*, so a format naming 8 values produced `pack(fmt, v0..v7)` — 9
   arguments — and the call was refused where the doc below says. It now
   truncates the value list to five first and then pads to five, so the call
   carries exactly the five values the module has slots for. That is not a
   smaller `struct.pack` hiding the bug: `struct.mojo` answers the FORMAT it was
   given (`_nvalues(fmt)`), not how many arguments arrived, so "five supplied,
   more wanted" is precisely the state the module is supposed to decline, and
   the empty-list assertion below is now testing what it was written to test.
2. **A false refusal in `read_before_store` that made all five cases fail for an
   unrelated reason.** The `_build_cfg` entry block was given a second,
   fictitious edge to whatever block the body ended on, so the fixpoint
   intersected every join with the entry's OUT set (the parameter seed) and any
   name the body stored unconditionally read as unstored. Every one of these
   five programs ends in `print(n)`, not `return`, which is the shape that
   triggers it — so all five failed on `'n' is read at line 11 before anything in
   this function stores it`, a name stored three lines above the read. Fixed by
   discarding `run`'s return value at `formal/model.py`'s `_build_cfg` entry;
   pinned by five new rows in `test_formal_read_before_store.py`.

Measured, `/opt/homebrew/bin/python3 test_struct_formal.py`, three consecutive
runs after both: **154/154 checks passed, exit 0.**

The rest of this document is the record of what was found and why the call-site
refusal must stay.

## What is believed

`formal/hostmods/struct.mojo` declines a format it cannot serve by returning
an **empty list**, and its own docstring says so:

> FIVE value slots: the signature is six arguments wide because six is the
> smaller of the two ABIs' integer argument registers. A format naming more
> than five values cannot be packed here, and the three corpus formats that do
> — `<HHHHHH` (6), `<HHIQQQI` (7), `<IIQQQQQQ` (8) — return an empty list
> rather than a wrong answer.

`test_struct_formal.py`'s `UNSERVABLE` group asserts exactly that: build the
program, run it, and require the printed byte count to be **0** rather than the
format's real size. That is a good test — it is the difference between a byte
packer that declines and one that writes eight plausible bytes into a Mach-O
header.

The problem is that for the widest of those formats the call is refused before
the function is ever entered, so the module's decline cannot happen.

## What was run, and what it saw

    $ python3 tools/memslot.py --gb 8 -- python3 test_struct_formal.py
    FAIL  pack("<IIQQQQQQ") is refused, not wrong: build failed: build: call
          pack(): 9 arguments exceeds the 8 the formal arm64 ABI passes in
          registers
    FAIL  pack("<4sBBBBBBB5x") is refused, not wrong: (same)
    146/148 checks passed

    # and the two ABIs' limits, from the two emitters:
    $ grep -n '_ABI_ARG_REGS = ' formal/arm64_codegen.py
    60:_ABI_ARG_REGS = 8
    $ python3 -c "from formal.x86_64_codegen import ARG_REGS; print(len(ARG_REGS))"
    6

## The mechanism, exactly

A call is `1 + N` arguments, where `N` is the number of values:

| format | values | call arity | arm64 (limit 8) | x86-64 (limit 6) |
|---|---|---|---|---|
| `<HHHHHH` | 6 | 7 | enters, declines with `[]` | **refused at the call site** |
| `<HHIQQQI` | 7 | 8 | enters, declines with `[]` | **refused at the call site** |
| `<IIQQQQQQ` | 8 | **9** | **refused at the call site** | **refused at the call site** |
| `<4sBBBBBBB5x` | 8 | **9** | **refused at the call site** | **refused at the call site** |

`test_struct_formal.py` pads a format's real value list up to five but keeps
every real value (`while len(values) < 5: values += [0]`), so a format naming 8
values produces a 9-argument call. `formal/arm64_codegen.py:5174` raises
`CodegenError` on it, and the build fails — so the group sees a build failure
where it expected a run that printed `0`.

Both failures are the two 8-value formats, which is the shape of the table
above and not a coincidence.

Note the scope honestly: `test_struct_formal.py` builds arm64 only
(`build_and_run` passes `--formal` with no `--backend`), so the x86-64 column
is read off `ARG_REGS`, not observed. On x86-64 the gap starts one format
earlier — a 6-value format is already over its limit of 6 arguments.

## Why the refusal is right and the test is not wrong to want the module

`formal/arm64_codegen.py:5163` explains the refusal, and the reason is a
measured silent miscompile:

> A ninth has no register, and this path has no stack-argument convention to
> fall back on, so the call is REFUSED here rather than truncated: the
> alternative — evaluate the extra arguments for their side effects, drop
> them, and branch — built an image that ran and read the ninth parameter as
> ZERO, which is a perfectly good answer to a great many questions (measured:
> `nine(1,...,9)` returned 1 where the source says 90001). A wrong value is
> strictly worse than a refusal here, because nothing downstream can tell a
> dropped argument from a caller who passed zero.

So the refusal must stay. What is broken is that it fires **above** the
module's own, gentler, in-band decline: the caller cannot reach the function
that knows how to say "I cannot serve this format".

## What is left, exactly

**Option 1 below is the only thing left, and it is unchanged:** the arm64
emitter still refuses a call with more arguments than its eight registers, so a
program that genuinely passes 9 arguments to a function still does not build.
That is the right answer (the measurement under "Why the refusal is right"
below), it is a property of the emitter rather than of `struct`, and nothing in
`test_struct_formal.py` depends on it any more — the suite now exercises the
module's own decline, which is the half that was unreachable.

1. **Give the arm64 emitter a stack-argument convention** for arguments 9 and
   up: store them to the stack in the callee's frame at entry (mirroring
   `formal/arm64_codegen.py:872`, which already has the callee-side refusal
   for a function *reached* without a call site) and push them at the call
   site in `_emit_call`. That is a real ABI feature and it unblocks every
   call over eight arguments in the tree, not just this one. It is also the
   change that makes the x86-64 gap worth closing at the same time, since
   x86-64 System V passes the first six integer arguments in registers and the
   rest on the stack for the same reason.
2. ~~**Or, if the emitter is not getting that soon**: change the `UNSERVABLE`
   group to assert the call-site refusal …~~ **Superseded.** This is close to
   what the test does now, and the reasoning behind it is sound rather than a
   documentation change dressed as a fix: the module answers the format it was
   given, so calling it with the five values it has slots for tests its decline
   instead of the ABI. The docstring correction it asked for turned out to be
   unnecessary — `struct.mojo` says five value slots because that is what it
   has, not because that is all the caller may pass.

## Related

- `formal/arm64_codegen.py:872` — the same limit on the callee side, refused
  for a function reached without a call site (a dylib export, a
  reflection-resolved call). Both sides of the same wall have to move
  together, or a function that can be entered but not called is a second,
  quieter hole.
- `bugs/FORMAL_known_limits.md` — the audit of which sweep refusals are true
  claims. This one is true, and it is not sweep residue, which is why it has
  its own doc.
- Registered as `formal-struct` in `tools/suite.py`, **with no `expect=`**
  since 2026-10-02: the marker was a declaration, not an excuse, and
  `test_suite.py` fails any `expect=`-marked test that starts passing, so this
  row retired itself the day the arity stopped being in its way.
