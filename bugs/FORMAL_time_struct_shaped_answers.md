# FORMAL_time_struct_shaped_answers: five `time` names are absent because their answer is a struct

**Status: OPEN, and a limit rather than a defect. It is the reason `localtime`,
`gmtime`, `mktime`, `strftime` and `get_clock_info` are ABSENT from
`formal/hostmods/time.mojo` rather than approximate.** Found while writing
`time` (2026-09-29, the `module:time` claim). The struct rule is the same on
both backends, so no file is claimed here; the container capacity rule is a
separate, already-filed limit (`FORMAL_listdir_no_run_time_sequence.md`).

---

## What I ran

`formal/hostmods/time.mojo` is written and passes `test_formal_time.py` (4/4
groups). The five names below are the ones it does not define, and
`test_formal_time.py`'s `limits` group asserts that each one is REFUSED with a
message naming itself — so this is a measurement, not an omission:

```
$ python3 test_formal_time.py limits
PASS limits  5 absent names refused, each naming itself
```

The refusals, one of each:

```
$ cat > .tmp/lt.mojo
import time
def main() -> int:
  time.localtime(0)
  return 0
$ python3 fire.py build --formal --no-prove -o .tmp/lt .tmp/lt.mojo
build: time.localtime(): `time` is a linked module but it exports no
`localtime`, so the call has no symbol to bind. What it does export:
CLOCK_MONOTONIC, CLOCK_MONOTONIC_RAW, CLOCK_MONOTONIC_RAW_ALIAS,
CLOCK_PROCESS_CPUTIME_ID, CLOCK_REALTIME, CLOCK_THREAD_CPUTIME_ID,
clock_gettime_ns, monotonic, …. …
```

That is the export-map refusal naming the module and listing what it DOES
export, which is the diagnostic this situation deserves: a reader is told the
name is absent rather than being told an image would fail to load. The five
names produce the same message with their own name substituted, which is what
`test_formal_time.py`'s `limits` group asserts.

## What the five names need

| name | CPython's answer | why there is no representation |
|---|---|---|
| `localtime(secs)` | `time.struct_time` | a 9-field named tuple, and a namedtuple that cannot be constructed by a dylib export |
| `gmtime(secs)` | `time.struct_time` | as above |
| `mktime(tm)` | `float` | its ARGUMENT is a struct, so the input is the problem here, not the output |
| `strftime(fmt, tm)` | `str` | its ARGUMENT is a struct (`tm`), and CPython's default reads the local timezone |
| `get_clock_info(name)` | `types.SimpleNamespace` | a 9-attribute record; a struct with attributes, and `SimpleNamespace` is a host-object type |

So it is one capability with five callers: **a `struct tm` cannot cross a
module boundary, and cannot be constructed by one.** The three that only
RETURN one (`localtime`, `gmtime`, `get_clock_info`) fail on the way out; the
two that TAKE one (`mktime`, `strftime`) fail on the way in.

## Why

A formal value is one 64-bit word, and a struct is a frame blob
(`formal/model.py`, "no storage"). `formal/hostmods/os/_syscalls.mojo` already
records the same fact for `stat`, and the resolution there is the same one
taken here: `os` answers `getsize` with `lseek`, which returns the size as a
VALUE, and does not answer `st_mtime` at all.

The `os` case is instructive because `stat` is a libc function that does exist
on this target. The obstacle is not the call; it is the out-parameter struct
whose field offsets and padding the source never states. `localtime` is
worse: it writes a 9-field struct INTO a caller-supplied buffer, so even the
layout is the caller's to invent.

There is a second, independent obstacle on the argument side, and it is worth
naming separately because closing the struct problem would not close it: a
program would have to BUILD a `struct tm` to hand to `mktime` or `strftime`,
and `localtime`'s answer is a named tuple that cannot be read field-wise on
this path either. So even a perfect `struct tm` representation would give a
program that can obtain the nine numbers but not pass them back, which is why
this is filed as one capability rather than five names.

## Not this document: the `now` in `runtime/stdlib_wrapper.mojo`

Writing this module moved that file off `time`, and it now fails on a
different and much more specific thing, which is worth stating here because
the next reader will hit it and it is NOT one of the five names above:

```
$ python3 tools/formal_sweep.py --no-stdlib runtime/stdlib_wrapper.mojo
NOT-ANSWERABLE/UNRESOLVED-EXTERN: runtime/stdlib_wrapper.mojo  (build: … the
image would bind 1 symbol(s) that nothing provides, so it could not be loaded:
now. …)
```

`runtime/stdlib_wrapper.mojo` is three lines and opens
`from time import now, sleep`. **`now` is not a CPython `time` name** —
CPython has `time()`, and `dir(time)` contains no name with `now` in it
(checked). It is a Mojo-side spelling, and this file is written in Mojo
(`fn main()`), so it was written against the Mojo stdlib's idea of `time`
rather than CPython's.

This module deliberately does NOT export a `now`. Adding one would mean
inventing an API that the module it is named after does not have, and the
whole point of the docstring rules above is that each export is a CPython
name with CPython's meaning. So the correct fix belongs in that fixture, not
in `time.mojo`: `from time import time, sleep` is the CPython spelling, and
`time()` on this target is `time_seconds()` (whole seconds) or
`time_seconds_bits()` (the fractional form). A one-line change to a runtime
test fixture, deliberately not made here — that file is not this claim's, and
changing a test fixture to make a sweep number move is exactly the shortcut
this work is supposed to avoid.

## What I expect

`localtime(t)` to be answerable as the nine integers it contains, and
`mktime`/`strftime` to be answerable given them. The spelling that would
follow the `os` precedent is scalar functions — `localtime_year(t)`,
`localtime_mon(t)`, … — one per field, rather than a struct; that is a
judgement about the API shape and it is the integrator's or the next worker's
to make, not something to guess at from here.

## The exact next step

The struct read is the same problem `bugs/FORMAL_stat_out_parameter_is_unreadable.md`
and `bugs/FORMAL_subscript_of_a_pointer_reads_a_blob_count.md` record, so
there is one fix for all of them rather than five:

1. **Give a struct an addressable field layout across a dylib boundary.**
   `doc/ABI.md`'s "Aggregates" section already says the right thing —
   *"Structs are passed and returned by pointer … Field layout (name → C type,
   in declaration order) is recorded in the reflection table and must match on
   both sides"* — and the block that follows says the `Span` row is a hardcoded
   model rather than a declared struct. So the contract is written and the
   implementation is a special case. Routing `_emit_subscript_addr`'s
   pointer-with-declared-pointee rule (the one
   `FORMAL_subscript_of_a_pointer_reads_a_blob_count.md` §"exact next step"
   asks for) to a struct whose fields the reflection table knows would give
   `tm.tm_year` as a load at a stated offset.

2. **Then answer the three that return one, in the scalar spelling**, and
   check each field against CPython's own `time.localtime(t)` in a new group
   of `test_formal_time.py`. That group should compare fields, not the tuple:
   the tuple is the thing with no representation, and comparing it would
   reintroduce the obstacle the fix removes.

3. **`mktime` and `strftime` last**, and each needs its timezone answered
   separately — `strftime("%Z")` reads the process's `TZ`, which is a `char *`
   in the C library's data, and `localtime` reads it too. That is a reachable
   facility (`getenv` already is, in the `os` module) but it is a second
   capability, and neither of these two names is correct without it.

**Not attempted here, and why.** Answering `localtime` with nine separate
functions that each re-derive the broken-down time from the timestamp is
possible — the arithmetic is pure — but it would be nine libc calls per field
and a program that wanted `tm_year` and `tm_mon` would pay for all eighteen.
That is a worse API than CPython's for a saving that is not the one the module
is for, so the honest state is the refusal above.
