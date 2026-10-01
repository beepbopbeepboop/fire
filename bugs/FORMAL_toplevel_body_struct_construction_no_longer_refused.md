# A struct construction with arguments in a module body now BUILDS, and `test_formal_toplevel.py` still asserts it is refused

## Status

OPEN — found 2026-09-30 while registering `test_formal_toplevel.py` (it was
named by no spec and in no bucket; it is now `formal-toplevel`, in `proofs`,
declared red with `expect=`). **2 of 70 checks fail, once per backend.**

## What is believed

`test_formal_toplevel.py` exists because a silent miscompile got through. A
file whose whole body was

```mojo
import sys
sys.exit(3)
```

built, linked, passed the symbol-bind audit and exited 0: every top-level
statement outside a `FunctionDef` was dropped without a diagnostic. That was
`bugs/FORMAL_toplevel_statements_dropped.md`, closed and **deleted** on
2026-09-29 (`6ad8efd5`) — so the durable artefact is the test file, whose
docstring carries the story, and not a doc. `bugs/FORMAL_module_state_no_storage.md`
still cites the deleted path for the `t1.mojo` row; that is a stale pointer to
fix, not a reason to go looking for the bug.

The file's discipline is therefore the right one for a case like this — build
the image, **execute** it, and compare stdout and exit status with CPython on
the same text — and it carries a family of `case_refused(...)` cases for
constructs the body reaches that the backend cannot lower.

One of those cases has outlived its fact.

## What was run, and what it saw

    $ python3 tools/memslot.py --gb 8 -- python3 test_formal_toplevel.py
    FAIL  body_construction_refusal [arm64] refused: it BUILT a construct with
          no representation; the binary is the real answer here
    FAIL  body_construction_refusal [x86_64] refused: (same)
    formal toplevel: PASS=68 FAIL=2 (70 checks)

The case, at `test_formal_toplevel.py:605`:

```python
return case_refused(
    "body_construction_refusal",
    "struct Point:\n    x: Int\n    y: Int\n    def __init__(self, x, y):\n"
    "        self.x = x\n        self.y = y\n\n"
    "p = Point(1, 2)\nprintf(\"%d\\n\", p.x)\n",
    "is a call to a user-defined `__init__`", tmpdir, verbose)
```

and `case_refused` (line 188) says, on a zero exit:

> it BUILT a construct with no representation; the binary is the real answer
> here

## The binary is right, so this is a stale expectation and not a miscompile

The helper refuses to certify a build it cannot check, which is the correct
instinct — but the thing it declined to check passes. Built by hand, both
backends, with a constructor that stores two distinct values:

    $ cat .tmp/probe/pt.mojo
    struct Point:
        x: Int
        y: Int
        def __init__(self, x, y):
            self.x = x
            self.y = y

    p = Point(11, 22)
    printf("x=%d y=%d", p.x, p.y)

    $ python3 fire.py build --formal --backend arm64  --no-prove -o pt.arm64 pt.mojo && ./pt.arm64
    x=11 y=22
    $ python3 fire.py build --formal --backend x86_64 --no-prove -o pt.x86_64 pt.mojo && ./pt.x86_64
    x=11 y=22
    $ python3 -c "print('x=%d y=%d' % (11,22))"
    x=11 y=22

Both fields are right, so the constructor is being inlined at the construction
site with the arguments the source passed, in the right order, and the frame
handoff works from a module body as well as from a function body.

One thing that looks wrong in that output and is **not**: the literal `\n` in
the case's own source. String escapes are not interpreted on this path, and
that is a pinned property, not a bug — `test_formal_sys.py:510`
(`test_string_escapes_are_not_interpreted`) asserts `"a\nb"` is five bytes and
says so in its own failure message ("string escapes are now interpreted on
this path"). Do not "fix" the case's `\n` while fixing this.

## What actually changed

Nothing in the tree records it, which is why this is worth a doc rather than a
one-line edit: a declared `__init__` used to be un-inlinable on this path, and
now is. `formal/model.py:8260` (`construction_init_body_refusal`) is the
refusal the case's needle came from — and it now only fires for an arity no
declared overload admits (`construction_init_arity_refusal`, line 8210) or an
`__init__` body the path still cannot inline. A 2-parameter `__init__` called
with 2 arguments is neither, so the call lowers.

The docstring of `test_a_module_body_can_still_be_refused_by_the_ordinary_codegen`
is the thing that is now wrong, and it is worth reading before editing
anything: it says the message is "the ordinary construction refusal, unchanged,
because the body is a function and the function pipeline is what answers it. A
second, body-specific refusal list would have made this a different message for
the same construct depending on where it was written." That argument still
holds — there is still no body-specific refusal list, and the remaining refusal
families (`body_next_finding` on a `printf` of a subscript) still come from
the ordinary pipeline. What changed is that this particular construct has an
ordinary answer now, which is a *success* the case was written to detect.

## The next step, exactly

1. Replace the one `case_refused` with a build-and-**run** comparison, which is
   the file's own discipline for a case in a module body: the program prints
   `p.x` and the case requires it to be `1`. That is a stronger assertion than
   the refusal it replaces — a refusal only says the backend declined, a run
   says the answer is right — and it is the assertion that would have caught a
   constructor inlined with the wrong argument order.
2. Leave the neighbouring cases alone. `test_a_module_body_reaches_its_next_real_finding`
   (a `printf` of a subscript) and `test_a_module_dylib_that_exports_no_exit_is_refused`
   are both still true refusals; run the file and confirm they still pass.
3. If the maintainers would rather the construct keep being refused — that is a
   policy question, not a bug report, and a defensible one — then the change is
   in the emitter, not in the test, and it should land with a doc saying which
   module-body constructs are in scope. Do not do that by editing the case: a
   test edited to match the code is the `coro` failure in
   `CLAUDE.md` wearing a smaller hat.

## Related

- The top-level-statements miscompile this file was written for is closed and
  its doc deleted; the file's own docstring is the record, and
  `bugs/FORMAL_read_before_store_returns_a_register.md` is the gap that
  lowering exposed next door. What is left open about a module body is in
  `bugs/FORMAL_module_state_no_storage.md`.
- Registered as `formal-toplevel` in `tools/suite.py` with
  `expect='bugs/FORMAL_toplevel_body_struct_construction_no_longer_refused.md …'`.
  The `expect=` is a declaration, not an excuse: `test_suite.py` fails any
  `expect=`-marked test that starts passing, so this row retires itself when
  the case is corrected.
