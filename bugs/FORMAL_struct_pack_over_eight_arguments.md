# `struct.pack` for a format naming 8 values is refused at the CALL SITE, so `struct.mojo`'s own "return an empty list" is unreachable

## Status

OPEN — found 2026-09-30 while registering `test_struct_formal.py` (it was
named by no spec and in no bucket; it is now `formal-struct`, in `proofs`,
declared red with `expect=`). **2 of 154 checks fail, on arm64** — 148 cases
plus the six the harness self-test added, so the count is a function of the
CASES rather than of the verdicts (see
`bugs/CODEGEN_test_struct_formal_is_flaky.md`, which is why).

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

## The next step, exactly

Two shapes, and the first is the real one:

1. **Give the arm64 emitter a stack-argument convention** for arguments 9 and
   up: store them to the stack in the callee's frame at entry (mirroring
   `formal/arm64_codegen.py:872`, which already has the callee-side refusal
   for a function *reached* without a call site) and push them at the call
   site in `_emit_call`. That is a real ABI feature and it unblocks every
   call over eight arguments in the tree, not just this one. It is also the
   change that makes the x86-64 gap worth closing at the same time, since
   x86-64 System V passes the first six integer arguments in registers and the
   rest on the stack for the same reason.
2. **Or, if the emitter is not getting that soon**: change the `UNSERVABLE`
   group to assert the *call-site* refusal for the formats whose arity exceeds
   the ABI — i.e. require the build to fail with `exceeds the 8 … passes in
   registers` — and keep the empty-list assertion for the formats that do fit
   (6 and 7 values on arm64). That is a smaller `struct.pack` than the module
   documents, so `formal/hostmods/struct.mojo`'s docstring has to be corrected
   with it, and `test_struct_formal.py:451`'s `check(sorted(wide) ==
   sorted(UNSERVABLE))` needs to know which half it is asserting.

Option 2 is a documentation change dressed as a fix; option 1 is the fix.
Do not take option 2 and call the module's contract intact.

## Related

- `formal/arm64_codegen.py:872` — the same limit on the callee side, refused
  for a function reached without a call site (a dylib export, a
  reflection-resolved call). Both sides of the same wall have to move
  together, or a function that can be entered but not called is a second,
  quieter hole.
- `bugs/FORMAL_known_limits.md` — the audit of which sweep refusals are true
  claims. This one is true, and it is not sweep residue, which is why it has
  its own doc.
- Registered as `formal-struct` in `tools/suite.py` with
  `expect='bugs/FORMAL_struct_pack_over_eight_arguments.md …'`. The `expect=`
  is a declaration, not an excuse: `test_suite.py` fails any `expect=`-marked
  test that starts passing, so this row retires itself the day the arity
  works.
