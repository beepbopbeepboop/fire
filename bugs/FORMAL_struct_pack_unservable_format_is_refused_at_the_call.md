# FORMAL_struct_pack_unservable_format_is_refused_at_the_call: `struct.pack` never reaches the "return an empty list" contract it declares

**Status: OPEN, pre-existing on this branch's `HEAD` and measured against it
(2026-09-30) while running the regression floor for
`construct:method-param-field-access`. Not fixed here: `struct` is another
worker's module (`module:copy+collections+io+json+pathlib+typing+builtins` is
not this claim, and the arity ceiling is a backend-wide ABI fact).**

`test_struct_formal.py::test_unservable_formats_are_refused_not_wrong` is red on
two of its five formats, and it is red because the CALL is refused before the
module's own handling runs — so the contract `struct.mojo` declares for a
format it cannot serve is unreachable, and the test that exists to pin it can
only ever fail.

## What I ran

```
$ python3 test_struct_formal.py
...
FAIL  pack("<IIQQQQQQ") is refused, not wrong: build failed: build: call pack():
      9 arguments exceeds the 8 the formal arm64 ABI passes in registers
FAIL  pack("<4sBBBBBBB5x") is refused, not wrong: build failed: build: call
      pack(): 9 arguments exceeds the 8 the formal arm64 ABI passes in registers
146/148 checks passed
```

The generated program is the test's own, one value per format code:

```mojo
from struct import pack

def main():
    b = pack("<IIQQQQQQ", 1, 1, 1, 1, 1, 1, 1, 1)
    ...
```

The other three formats in `UNSERVABLE` pass because they need fewer than eight
values: the ceiling is on the CALL, not on the format's width, and only the two
eight-value formats plus the format string reach nine arguments.

**This is not my change.** Built with the tree's own `formal/build.py` at
`HEAD` (a scratch copy of the package with `git show HEAD:formal/build.py`
restored), the same source produces the same refusal:

```
REFUSED: call pack(): 9 arguments exceeds the 8 the formal arm64 ABI passes in registers
```

## Why it is a bug and not the test being stale

The refusal is TRUE as a statement about the ABI: arm64 passes eight integer
arguments in registers and a ninth goes on the stack, which this path does not
do for a C entry point (`formal/arm64_codegen.py`'s argument-count check).
What is not true is that it is the only answer available. `struct.mojo`
declares, and the test's own docstring states, that an unservable format
"returns an empty list rather than a wrong answer" — and that branch can never
be reached, because the program is refused at the call and the callee never
runs. So the module carries dead code and the test asserts a contract that
cannot be exercised.

The two halves have a real design question between them, which is why this is
filed rather than "fixed" by editing the test:

* either the CALL arity ceiling accounts for the arguments the callee is
  declared to accept (`pack(fmt, *values)` is variadic, so the ceiling applies
  to the ARGUMENTS the callee actually reads, and a callee that returns an
  empty list for a format it cannot serve is not reading them), or
* or `struct.mojo`'s unservable branch moves to the CALL SITE, where the
  backend can see the format string and the argument count at once.

## The exact next step

1. Read `formal/arm64_codegen.py`'s argument-count check and find what it
   counts: `len(args)` on the call, or the callee's declared parameter list.
   The message says "call pack(): 9 arguments exceeds the 8 the formal arm64
   ABI passes in registers", which reads like the former.
2. For a VARIADIC callee — `pack` is one, `printf` is the case the check
   exists for — decide whether the ceiling is on the callee's FIXED parameters
   plus the variadic area, or on every argument at the call. The answer decides
   whether this is a backend change or a module change, and it is the same
   question `bugs/FORMAL_frame_receiver_handoff.md`'s position family asks for a
   frame address.
3. Add the two formats back to a case that asserts the EMPTY LIST rather than a
   refusal, so the contract `struct.mojo` declares is actually pinned — the
   test's own wording ("A refused pack yields an empty list, and a list literal
   is the only shape this path can print a length for") is written for a build
   that happens, so it was written expecting the module's branch to win.