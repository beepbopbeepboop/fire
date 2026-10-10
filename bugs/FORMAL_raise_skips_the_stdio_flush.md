# FORMAL_raise_skips_the_stdio_flush: on arm64 a `raise` throws away everything the program had already printed

**Status:** open, arm64 only, and it is a **silent wrong output** — the image
runs, exits 1, and its stdout is *empty* when it should hold the lines printed
before the raise. Found 2026-09-30, while measuring
`bugs/FORMAL_no_exceptions.md`; that document records what a raise means for
control flow, this one records what it costs the output.

**Not fixed here.** The fix is in `formal/arm64_codegen.py`, which is not the
area of the work that found it, and it is a codegen change on a backend whose
gate is a full `make gate`. Filed with the repro and the next step instead.

## What I ran

Two builds of the *same source*, one per backend, plus a control. All under
`tools/memslot.py --gb 8`; sources in `.tmp`, so no repository file is involved.

```
def main() -> int:
    printf("before@@")
    raise 7
```

```
$ python3 fire.py build --formal --no-prove -o .tmp/exc/e .tmp/exc/e.mojo
Built: .tmp/exc/e  [arm64/macho]
$ ./.tmp/exc/e
$ echo $?
1

$ python3 fire.py build --formal --backend=x86_64 --no-prove -o .tmp/exc/e64 .tmp/exc/e.mojo
Built: .tmp/exc/e64  [x86_64/macho]
$ ./.tmp/exc/e64
before@@
$ echo $?
1
```

**arm64 prints nothing. x86-64 prints `before`.** Same source, same status.

The control, on arm64, to show the program really does reach the `printf`:

```
def main() -> int:
    printf("before@@")
    return 1
```

```
$ ./.tmp/exc/b
before@@
$ echo $?
1
```

So on arm64 a `return 1` from `main` flushes and a `raise` does not. The
difference is not the program's output path — it is which exit is taken.

## Root cause

**arm64** terminates a `raise` with the Darwin `exit` **syscall**, emitted
inline (`formal/arm64_codegen.py:1142`):

```python
        if isinstance(stmt, F.RaiseStmt):
            if stmt.value is not None:
                self._emit_expr(stmt.value)
            self._flush_pending_finally()
            self.asm.emit(encode_movz_xd_imm(0, 1))
            self.asm.emit(encode_movz_xd_imm(16, 1))     # X16 = 1 = exit
            self.asm.emit(encode_svc(0x80))
```

Syscall 1 enters the kernel. libc's `exit()` — the one that runs `atexit`
handlers and flushes `stdout` — is *user-space* code that runs *before* that
syscall, so making the syscall yourself skips all of it. `stdout` is fully
buffered when it is a pipe, so **every unflushed byte is discarded**.

The normal path is unaffected, and the reason is in the epilogue:
`_emit_epilogue` (`formal/arm64_codegen.py:904`) restores the frame and emits
`ret`. `main` therefore *returns* into libc's `__main`, which calls `exit()` and
flushes. A `raise` never returns.

**x86-64** does not have this bug: `formal/x86_64_codegen.py:997` lowers the
same statement through `_emit_call_exit(1)`, whose docstring at `:1392` reads
*"Call the C library's `exit(status)`"* — a `call`, so the flush happens.

## Why it sat unnoticed

The idiom is not one site. `encode_movz_xd_imm(16, 1)` immediately followed by
`encode_svc(0x80)` appears **16 times** in `formal/arm64_codegen.py` — it is
this module's universal "terminate with status 1", used for a bounds check, an
arity mismatch, a container-capacity overflow and a shape refusal as well as for
`raise`. **Every one of them discards buffered output.** The measured case is
`raise` because it is the only one a program can be *expected* to reach after
producing output; the others are refusals, where a bare status and no output is
arguably the right answer and nobody has measured otherwise.

And no test in the tree raises on this path: the two host-module waves
(`argparse` … `json`, `pathlib`) answer failure with return values *because*
`bugs/FORMAL_no_exceptions.md` says they must, so a raise is not exercised by
any of them.

## What I expected

`before@@` on both backends, exit 1 on both. The status is right on both; the
output is right on exactly one.

## The next step

1. **Route every one of the 16 through libc.** Replace the inline
   `movz x16, 1; svc` with a `bl` to the C library's `exit` — the encoding
   helper for a library call already exists, since `_emit_call_exit`'s x86-64
   twin and every other libc call on this backend use it. One helper, sixteen
   call sites, and the mechanical refactor is what keeps them from drifting back
   to the raw syscall.
2. **Then decide whether the refusals should keep exiting silently.** Once the
   flush is unconditional, a bounds-check refusal will also print whatever the
   program had buffered, which may be more than a caller wants. That is a
   judgement about each site, not one setting — so make it explicit rather than
   incidental, and record it at the helper.
3. **Pin it with three cases**, which would have caught this at the first
   hostmod wave: `printf` then `raise` (expect the line), `printf` then
   `return 1` (the control), and the same source on both backends so a
   re-divergence is a diff rather than a discovery. It belongs beside
   `test_formal_link_accounting.py`, the gate-resident file that owns this class
   of check — see the third item in `bugs/FORMAL_no_exceptions.md`.