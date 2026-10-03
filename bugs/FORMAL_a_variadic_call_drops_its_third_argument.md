# FORMAL_a_variadic_call_drops_its_third_argument: `fcntl(fd, F_SETFD, flags)` succeeds and does nothing

**Status: OPEN. NOT fixed. Found while writing `formal/hostmods/fcntl.mojo`
and its test, 2026-10-02. Not anybody else's claim: the area is how the two
formal backends pass a NON-`printf` variadic argument, and the `sweep5:hostmods-more`
claim covers the host modules, not the emitter.**

## What I ran and what I saw

A formal image that opens a descriptor and calls `fcntl(2)` on it, next to
CPython doing the same thing to the same file:

```python
# .tmp/w/fc2.mojo
from fcntl import getfd, setfd, getfl
from os._syscalls import fs_open_ro, fs_close, fs_fcntl

def main() -> int:
    var fd = fs_open_ro(".tmp/w/lockfile")
    printf("before=%lld\n", getfd(fd))            # F_GETFD
    printf("set_lit=%lld\n", fs_fcntl(fd, 2, 1))  # F_SETFD, literal argument
    printf("after_lit=%lld\n", getfd(fd))
    printf("set_var=%lld\n", setfd(fd, 1))
    printf("after_var=%lld\n", getfd(fd))
    printf("fl_before=%lld\n", getfl(fd))         # F_GETFL
    printf("fl_set=%lld\n", fs_fcntl(fd, 4, 4))    # F_SETFL, O_NONBLOCK
    printf("fl_after=%lld\n", getfl(fd))
    fs_close(fd)
    return 0
```

arm64 — every line identical on x86-64:

```
before=0          set_lit=0   after_lit=0
set_var=0         after_var=0
fl_before=0       fl_set=0    fl_after=192
```

CPython, on the same file, same commands:

```
before=1          set=0       after=1
fl_before=0       fl_set=0    fl_after=4
```

**`F_SETFD` reports success and changes nothing.** `fl_after=192` where CPython
says `4`: not the requested `O_NONBLOCK`, and not the value from before either.
`192` is `0xC0`.

Two things in that table are NOT the bug and are recorded so nobody re-chases
them:

  * `before=0` against CPython's `before=1` is a difference in the **OPEN**, not
    in the read. CPython's `os.open` sets `FD_CLOEXEC` by default; this path's
    `open(p, "r")` does not, and cannot — there is no `fcntl` to set it with,
    which is the loop this bug is in.
  * `fl_before=0` is the same story for `O_LARGEFILE`, which Darwin's `open`
    would have set and this path's lowered `open` apparently does not.

## Why it happens

`fcntl(2)` is `int fcntl(int fd, int cmd, ...)`. The third parameter is
**variadic**, and a variadic argument is passed in the same register as any
other argument of the same class — so `fcntl(fd, 2, 1)` should put `fd` in `x0`,
`2` in `x1` and `1` in `x2` (arm64) or `rdi`, `rsi`, `rdx` (SysV x86-64).

`printf` is **not** evidence that variadic integers arrive: `printf` is lowered
by a path that knows it is variadic and builds a real C format string and a real
argument list, and every host module in the tree relies on it working. A call to
an unbound extern that merely HAPPENS to be variadic is a different path, and
this measurement says the third argument does not survive it — `fl_after=192`
is consistent with the call receiving a value that was never 4 and never 0.

## What it costs, and who it touches

  * **`formal/hostmods/fcntl.mojo` has `getfd`/`setfd`/`getfl`/`setfl` ABSENT**
    because of this, and `lockf` absent for the adjacent reason that
    `F_SETLK`'s argument is a POINTER through the same variadic tail. Both are
    documented at the place in the module where they would have been, with the
    measurement quoted, and `test_formal_fcntl.py`'s `absent` group pins all six
    refusals by name. `flock(2)` is not variadic and works, which is why the
    module is worth having at all.

  * **The tree's other variadic-extern calls are unexamined by this.** The
    candidates are `printf`-family (excluded, handled), `syslog(3)`, `openlog`,
    `pselect`/`poll` (their timeout is a pointer — same failure), and anything
    in `formal/hostmods/` that calls an extern with more parameters than the
    fixed-arity part of that function's prototype declares. I have NOT audited
    those; the next step below is how to.

## The next step, exactly

In `formal/arm64_codegen.py` and `formal/x86_64_codegen.py`, find where an
unbound-extern call's arguments are emitted and compare it with the `printf`
path. Concretely:

1. Emit a probe program that calls one non-`printf` variadic extern with three
   distinct integer arguments and a fourth that must be ignored, where the
   callee reports what it received. `fcntl(fd, F_GETPATH, buf)` is a good
   candidate and a bad first choice; a simpler one is `syslog(3, 3, "%s", s)`,
   whose fourth argument the callee ignores — but a second process's stderr is
   awkward to read back, so `fcntl(fd, F_SETFL, 4)` followed by `F_GETFL` is the
   cheapest observable pair and is what this doc already uses.
2. The question to answer is whether the emitter emits arguments positionally
   for an unbound extern, or only for calls it has classified. If it is the
   latter, then an extern whose prototype this tree does not know is called with
   fewer arguments than the C ABI passes, and **every** such call in the tree is
   suspect — which is a much bigger finding than this one and worth knowing.
3. The test that would close it is `test_formal_fcntl.py`: delete `getfd`,
   `setfd`, `getfl` and `setfl` from the module's `absent` list, delete
   `lockf`, and add them. Until the emitter is fixed, adding them would make
   `setfd` a function that lies.

**A note on why this is filed rather than fixed here.** The fix is in the two
codegen backends, which is the `CODEGEN_*`/`FORMAL_*` codegen surface rather
than the host-module surface this task claimed, and neither backend is small
enough to change safely from a light worker whose own change must stay
narrow. The measurement is the contribution.
