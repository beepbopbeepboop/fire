# CODEGEN: `external_call["nanosleep", ...]` emits a prototype that conflicts with libc's

Status: open. Found 2026-11-15 while landing free-function overload emission
(`std/time/time.mojo`'s `sleep(Int)` overload became emitted for the first
time).

## What I ran

    python3 -c "import build_stdlib_dylib as b; ... compile_module_to_c('std/time/time.mojo')"
    gcc-mp-15 -fgimple -fsyntax-only -D__MOJO_STDLIB_MODE__ -Iruntime time.c

## What I saw

`std/time/time.mojo`'s `sleep(sec: Int)` body (line 366) calls

    _ = external_call["nanosleep", Int32](req, rem)

and the generated C contains

    extern int32_t nanosleep (_CTimeSpec *, int64_t);
    ...
    _t64 = nanosleep (req, rem);          /* rem is int64_t */

On macOS the platform header already declares
`int nanosleep(const struct timespec *, struct timespec *)`, so gcc reports

    error: conflicting types for 'nanosleep'; have 'int32_t(_CTimeSpec *, int64_t)'
    note: previous declaration ... with type 'int(const struct timespec *, struct timespec *)'

The second argument is an `int64_t` zero (`rem`), which is also not the pointer
the real signature wants. The module used to compile only because the whole
`exit`/`sleep` overload set was dropped by the duplicate-def pass before this
landing.

## What I expected

`external_call["name", Ret](args)` should not emit a prototype that disagrees
with a platform header the prelude already includes, and an argument whose
source value is `None`/a zero literal bound to a pointer parameter should be
emitted as a pointer (or the call should be rejected with a real diagnostic).

## Exact next step

Two independent pieces:

1. In `emit_resolve`/`emit_infra`'s `_external_protos` recording, skip a name
   that is declared by the prelude's headers (at minimum add `nanosleep` and
   the other `<time.h>`/`<unistd.h>` sleep-family names to the appropriate
   `_LIBC_DECLARED`/header set on platforms that include those headers), so the
   generated TU uses the platform prototype.
2. Type an `external_call` argument from the callee's known C signature when
   one exists (the `_CTimeSpec`/`int64_t` second slot above is really
   `struct timespec *`), so the call passes a pointer/null rather than a
   truncated word.

Until both land, the overload gate in `module_gen` keeps a plain overload set
with an `external_call` in any body unemitted (the pre-2026-11-15 behaviour).
