# FORMAL_time_struct_shaped_answers: five `time` names are absent because their answer is a struct

**Status: UPDATED 2026-10-03 (`work/formal16-8`). Item 1 is CLOSED and item 2 is
RESOLVED AS A LIMIT, so what is left here is a FACT rather than work: the five
names are absent because their answer is a STRUCT, a struct cannot cross a module
boundary on this path, and the API shape that would work around that would be an
API CPython's `time` does not have — which this module's own docstring rules
forbid inventing.** Both halves are measured below. Nothing is "fixed" in the
sense of five names answering, and nothing should be: see item 2.

**Status: OPEN, and a limit rather than a defect — but NOT the limit this doc
used to name.** It is the reason `localtime`, `gmtime`, `mktime`, `strftime` and
`get_clock_info` are ABSENT from `formal/hostmods/time.mojo` rather than
approximate. Found while writing `time` (2026-09-29, the `module:time` claim).
**Re-measured 2026-10-02: the struct LAYOUT is not what is missing — a module can
read a C library's struct field-wise today, and what it cannot do is STORE
through a pointer. That capability is filed as
`FORMAL_a_module_cannot_store_through_a_pointer_with_a_declared_pointee.md`, and
`test_formal_time.py`'s `structroute` group is the standing measurement behind
it. What remains here is that capability plus an API-shape judgement.** The
struct rule is the same on both backends, so no file is claimed here; the
container capacity rule is a separate, already-filed limit
(`FORMAL_listdir_no_run_time_sequence.md`).

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

## The exact next step, re-measured: the layout is NOT what is missing

The plan this doc used to end with was (1) give a struct an addressable field
layout across a dylib boundary, then (2) answer the three that RETURN one in the
scalar spelling, then (3) `mktime`/`strftime` last. **Step 1 turned out to be
already done, and the blocker is somewhere step 1's plan did not look.**

`test_formal_time.py`'s new `structroute` group is the measurement, on both
architectures:

| what a module tries | result |
|---|---|
| read a C library's struct byte-wise through `Pointer[UInt8]` | **works** — `(p + k).value()`, checked against the bytes of a value the test put in the environment |
| read it through a wider pointee | refused, naming the width rule |
| **write** through a pointee (`p.value() = 1`) | **refused** — "assignment target must be a plain name" / "only a plain name has a home" |

So the read half of the route exists, field by field, in four little-endian byte
loads each — which is exactly what a `struct tm`'s nine `int`s are. What a module
cannot do is WRITE, and that is what the five names are waiting on:

* `localtime`/`gmtime` take a `const time_t *`, and the eight bytes that pointer
  must address cannot be built on this path (no store, and a module has no state
  of its own — `bugs/FORMAL_module_state_no_storage.md`). Passing an integer
  instead passes a null pointer and the image segfaults inside libc: measured,
  exit -11, which is why this is a refusal here and not a plausible answer there;
* `mktime`/`strftime` take a `struct tm *`, i.e. 36 bytes to fill one field at a
  time — the same missing store;
* `get_clock_info` is a different absence (a host-object type) and is not
  waiting on this.

The capability is filed, with the exact next step and the reason the analysis
belongs in one place for both backends, as
`FORMAL_a_module_cannot_store_through_a_pointer_with_a_declared_pointee`.

That leaves two open items here, and neither is a defect in this tree:

1. **the store** (above) — the only thing between `localtime_year` and an
   answer. **CLOSED 2026-10-03, measured.** `p.value() = v` through a pointee
   with a DECLARED type is a store at that pointee's own width, and it builds and
   RUNS on both architectures: `test_formal_time.py`'s `structroute` group reads
   `read yes / store yes` on arm64 and on x86-64, 5/5 groups on each. The store is
   checked by running it and reading the bytes AT and AFTER each pointee, because
   a store at the wrong width writes the right answer and corrupts the bytes
   behind it — the one failure a build cannot see. Still refused on both machines
   by name: a store whose width would be a CHOICE rather than a fact (no recorded
   pointee, a float/blob/struct pointee, a `p + k` whose element width the
   declaration does not fix, a read-only page).
   `FORMAL_a_module_cannot_store_through_a_pointer_with_a_declared_pointee.md` is
   already gone from `bugs/`, so its capability landed and this group is its
   standing guard. One repair was needed to make the measurement readable: the
   `unscaled` row's needle was pinned to the refusal's old FRAMING while the
   refusal is intact on both machines, so `structroute` was red on master for a
   wording change. The needle is now the sentence's operative clause, with both
   current sentences quoted in the case's comment.
2. **the API shape**, still a judgement and still not mine to make: once the
   store lands, `localtime(t)` cannot return a `struct tm` on this path, so the
   choice is nine scalar functions against CPython's one struct, or one function
   taking a caller-owned buffer and an offset. `os`'s `stat` precedent answers
   with a scalar (`getsize`, via `lseek`) rather than a struct, which is a
   reason to prefer the first — but "a program that wants `tm_year` and `tm_mon`
   pays for two libc calls" is the cost, and it was already named here before
   the store question was answered. **RESOLVED AS A LIMIT 2026-10-03, and the
   resolution is that NEITHER candidate shape is available to THIS module.** The
   `os`/`stat` precedent does not carry, and the difference is the whole answer:
   `getsize` is a CPython name whose CPython answer IS a number, so answering it
   with `lseek` answers the same question, whereas `time.localtime_year` is not a
   CPython name at all — CPython has `localtime`, and its answer is a
   `struct_time` — so a scalar spelling would be inventing an API, which this
   module's own rules forbid ("each export is a CPython name with CPython's
   meaning", and the `now` section below, which declines to add a `now` for
   exactly this reason). A caller-owned buffer plus an offset is a second invented
   name for the same reason.

   **So the five names STAY absent**, and `test_formal_time.py`'s `limits` group
   is the standing statement of that ("5 absent names refused, each naming
   itself", on both architectures). What would actually answer them is a
   struct-RETURNING export — the same capability
   `FORMAL_returned_frame_caller_owned_block.md` gives a function inside one
   image, and which a dylib boundary does not have — and that is a project rather
   than a judgement call about five names.
