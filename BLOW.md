# BLOW.md — the memory blowup: a never-frees accumulator (CORRECTED)

Branch `crash`. **This document previously carried a wrong headline. It
was wrong, it misled a session, and the correction is the most important
thing here — read §1 before anything else.**

`bugs/CODEGEN_bootstrap_resource_blowup.md` is the long history (incl.
the ~192 GB `fire.py` run and the useful "a SIGKILL here is evidence of
nothing" rule). This document supersedes its framing, not its history.

---

## 0. NOT closed

**Status: localised, not fixed.** Three gate steps are red *because* of
this, and all three `expect=` markers cite this section:

| step | what is actually wrong now |
|---|---|
| `ab-native` | RESOURCE-capped. Peak has drifted **9.4 -> 8.6 -> 10.0 GB** across three runs against a `small` 8 GB ceiling. Not a correctness verdict — killed for memory before finishing. |
| `native-dumpfull` | Runs 126 s, then fails. Its cost is the self-hosting bootstrap pre-pass this corpus triggers: **~15-30 GB, ~15-25 s per call**. |
| `bootstrap-stage2-dumps` | No longer segfaults, but does not reproduce the reference dumps. Sub-jobs return `mojo_unsupported_iter` no-ops or a wrong dump — a **silent-wrong-answer** class that no exit code reports. |

None of the three is the original SIGSEGV; that is fixed. All three sit
downstream of the same unbounded accumulation documented in §2, so none
can be closed by correcting a marker — the pre-pass cost has to come
down for them to go green.

**Measured repro for the per-call pre-pass cost**: §2. **Root-cause
status**: localised to a never-frees accumulator, not yet fixed; the
untried structural lever is per-module AST lifetime (§4).

---

## 1. RETRACTION: the "~15.8 GB constant" was a false positive

The previous version of this file measured a flat **15.84 GB / ~180 G
instructions** on *every* `--dump-full` invocation regardless of input
size, and concluded the blowup was a fixed cost of entering the compile
path rather than growth.

**That was an artifact of a bug, not a property of the compiler.** The
crash fix in `e7fc3ec` had made `mojo_boxed_is_str` alias
`_mojo_tagged_addr_ok` wholesale. That predicate answers *"can I read an
8-byte type tag here"*, so it requires 8-byte alignment **and**
`malloc_usable_size >= 8` — and a `.rodata` string literal satisfies
**neither** (measured: `"bb"/"a"/"ccc"` at low-3-bits 4/7/1, with
`malloc_size() == 0`). So every string literal in every program stopped
classifying as a string, and the compiler fell into formatting addresses
as decimal strings and doing string work over them — on every input,
which is exactly why the footprint looked like a flat constant.

The fix extracts the genuinely shared half into `_mojo_ptr_shaped` (the
2 GiB floor plus the 2^47 bound) and keeps alignment and
`malloc_usable_size` inside `_mojo_tagged_addr_ok` alone.

**Same probe, before and after** (`/usr/bin/time -l`, 133-byte program):

| | peak RSS | instructions |
|---|---:|---:|
| under the `e7fc3ec` regression | 15.84 GB | 180.0 G |
| **on the fixed tree** | **0.01 GB** | **0.1 G** |

A 1584x reduction from a one-line change to a predicate. **The flat
"constant" was the string-literal bug's own memory profile.**

Consequences for what this file previously claimed, all now void:

- ❌ "The blowup is a fixed startup cost, not growth." **False.** It is
  growth, and it is a leak.
- ❌ "`--help` being free means it is not startup / dynamic linking /
  a static initialiser." The inference was sound; the premise it was
  applied to was not.
- ❌ "Do not go looking for the per-module leak first — it is not where
  15.8 GB is." **Exactly backwards.** The per-module leak is where it is.
- ❌ "`ab-native` cannot pass because the compiler's fixed cost is
  15.84 GB against an 8 GB ceiling." Wrong reason. `ab-native` is still
  RESOURCE-capped (8.6 GB vs 8 GB) — but because of real growth, not a
  phantom constant.
- ❌ "`fire.py` at ~192 GB is ~12x an unexplained constant." There is no
  constant. See §2.

## 2. What the blowup actually is (measured 2026-09-27)

`vmmap` probe of the malloc zone during a real self-hosted compile:

| measurement | value |
|---|---:|
| `./mojoc --dump-full fire.py` peak RSS | **47.7 GB** (then SIGSEGV 139) |
| instructions retired | **0.76 T** |
| `./mojoc --dump-full fire_compiler.py` peak | **58.6 GB**, then SIGTRAP 133 |
| instructions retired | **1.24 T** |
| malloc zone at t=12 s | **11.4 GB across 130,462,322 live blocks** |
| mappings / fragmentation | 953 mappings, **1% frag** |
| growth | linear |

`sample` during the run is **flat** — regex 5%, sets 3%, malloc 2%. There
is no hot loop. 180 G instructions doing nothing in particular *is* the
signature: the work is not slow, it is unbounded in **volume**.

**It is a never-frees accumulator.** That is now established rather than
suspected.

### What this rules out

- **A miscomputed arena/table bound.** Ruled out as a *step*; what
  remains is accumulation.
- **Quadratic over a fixed universe** (types x methods). Would show a
  different profile than linear-in-time block growth.
- **Fragmentation.** 1% at 11.4 GB.
- **The tokenizer as the volume source.** 14.8 MB of source against
  670M blocks.
- **A single hot loop.** The flat profile excludes it.

## 3. Status of the crash, for the same reason

The segfault is **not** fully fixed, and this file previously implied it
was. `bootstrap-stage2-dumps` went 45/45 segfaulting -> **4/45**; the
survivors are the largest inputs, and `./mojoc --dump-full fire.py` still
exits **139** on this tree, at 47.7 GB. `mojoc --help` and a 133-byte
program both run clean. So: the small-input crash is fixed, the
large-input one is not, and both the residual crash and the blowup sit
downstream of the same unbounded accumulation.

## 4. Next lever

**Per-module AST lifetime** — the untried structural fix, and the one the
evidence points at. Two confirmed-cheap wins are documented and still
undone:

1. The three `_selfhost_*` passes tokenize the same file list **3x**,
   under three separate cache keys — so the cache cannot help, and the
   work is done three times.
2. `_set_grow`'s replay probes each key **twice**.

Both are repeated-work, not growth, so both are cheap wins rather than
the fix. The fix is not releasing anything.

## 5. Rules for measuring this, learned the hard way

- **Establish that the compiler is CORRECT before measuring its
  resource use.** A wrong answer can cost 1584x the memory of a right
  one, and it will look like a structural property of the system. Every
  number in §1 was a true measurement of a broken compiler.
- **`/usr/bin/time -l` in the foreground, always.** A SIGKILL is evidence
  of nothing (manual kill and OS kill are the same signal) and
  `( ... &)` hides the true exit status — that mistake already cost one
  session a bogus OOM diagnosis in this same area.
- **Measure the *shape*, not just the peak.** A flat footprint across a
  25x input range looked conclusive and was the tell that the number was
  not about the input. §1 had that signal available and read it backwards.
- Per-process `time -l` numbers are for `mojoc` alone; the runner's
  `memcap` numbers are **tree** totals ("across up to 3 procs") and
  include `gcc`. Never compare the two sets directly.
