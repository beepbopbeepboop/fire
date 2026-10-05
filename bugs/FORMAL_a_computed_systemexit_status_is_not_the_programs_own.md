# `raise SystemExit(n)` for a computed `n` leaves status 1, which is not the
# program's own status

**Area:** FORMAL, exceptions. Claim `project33:exceptions`, measured 2026-10-05
on `work/formal33-exceptions`. **OPEN, and deliberately so** — it is the one
case in the `raise SystemExit` rule where the backend's answer is a NUMBER it
cannot see, and a refusal was available and was not taken. Read
`bugs/FORMAL_a_try_handler_arm_is_still_never_emitted.md` §1 for the table this
row belongs to.

## What was run

```console
$ cat se.mojo
def code() -> Int:
    return 3

def main(n):
    print("before")
    raise SystemExit(code())
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove -o .tmp/se .tmp/se.mojo && ./.tmp/se ; echo "exit=$?"
before
exit=1
$ python3 -c "import sys
def code(): return 3
def main(n):
    print('before'); raise SystemExit(code())
sys.exit(main(3))" ; echo "exit=$?"
before
exit=3
```

Both backends answer 1; CPython answers 3. Same source with a literal in place
of `code()` gives 3 on both backends, and all five literal forms are correct
(`test_formal_exceptions.py`'s five `systemexit_*` rows, 198/198).

## What is right about the current answer, and what is not

`formal/model.py::raise_exit_status` reads an **integer literal** — including a
negated one, which is why `raise SystemExit(-1)` is 255 and not 1 — and
leaves everything else at 1. The literal case is exact. This doc is about the
other case.

Two defensible answers, and the tree currently takes neither cleanly:

* **Refuse.** `raise SystemExit(code())` becomes a build error naming the
  argument. Sound in the way this compiler is usually sound: the program stops
  building rather than running with a status nobody chose. Costly: `sys.exit(n)`
  is the ordinary spelling and it would refuse every call site of it.
* **Compute it.** Emit the argument, put it in the exit-status register and
  leave. Both backends can do this today and neither needs a new mechanism:
  x86-64's `_emit_call_exit` already takes a status and `_emit_mov_r64_r64`
  would put a computed word in RDI instead of an immediate; arm64's `_emit_exit`
  emits `movz x0, #status; movz x16, #1; svc` and the immediate is the only part
  that has to become a register — but the value has to survive the `fflush`
  call `_emit_exit` makes first, so it must be pushed across that, which is the
  one instruction the change actually adds.

**Why 1 was chosen anyway.** The status is the one thing a CALLER observes, so a
wrong one is the failure this compiler cannot detect on its own: a script whose
`sys.exit(3)` becomes `sys.exit(1)` looks like a passing test. Exiting 1 is the
same number as the overwhelming majority of real failures, which means a
caller checking `!= 0` is right and a caller checking `== 3` is wrong — and
that asymmetry is the reason the computed form is a bug rather than a rounding.

**The recommendation is the second option** — emit the computed value — because
it is a handful of instructions on a path that already exists, and because
refusing it would refuse a spelling that CPython's own `sys.exit` produces. The
reason it is not done in the same commit as the literal case is that it is a
separate mechanism (a register-valued exit against an immediate-valued one)
and bundling the two would have put an unmeasured instruction sequence in the
same commit as the one that needed measuring.

## The exact next step

1. In `formal/arm64_codegen.py::_emit_raise`, when
   `M.raise_exit_status` says "computed" rather than returning an int, emit the
   argument expression, push it, flush the pending finallys and the streams,
   pop it into X0 and take the raw `svc` exit — the shape `_emit_exit` already
   has, with `encode_movz_xd_imm(0, status)` replaced by a `mov` from the
   scratch register. A `status` of `None` from `raise_exit_status` is what says
   "computed", and it is the only signal that distinguishes the two paths.
2. In `formal/x86_64_codegen.py::_emit_raise`, the same, with RDI: `_emit_call_exit`
   currently takes an `int` and emits `_emit_mov_imm(Reg.RDI, status)`, so it
   wants a sibling that takes a register. No stack is needed — SysV's first
   integer argument register is written last.
3. `raise_exit_status` should stop returning 1 for the computed case and start
   returning `None`, and its two callers must branch on that rather than on the
   number. That is the API change, and doing it FIRST is what stops the two
   backends from quietly disagreeing about what `None` means.
4. Mask to a byte at the point the status is delivered, not in
   `raise_exit_status`: `exit(3)` truncates, and a computed `n` can be out of
   range where a literal one usually is not (`raise SystemExit(-1)` is the
   current row for that). `os._exit` and a raw `svc` do not truncate the same
   way on both platforms, so this needs measuring rather than assuming.
5. Rows for `test_formal_exceptions.py`: the literal control (already there,
   must stay green), a computed `n` at 3, a computed `n` at 0, and a computed
   `n` that is negative — the last two are what would catch a mask that is only
   applied on one backend.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_exceptions.py \
      systemexit_with_a_literal_status
```