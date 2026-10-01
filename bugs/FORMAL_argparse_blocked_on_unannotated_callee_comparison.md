# FORMAL_argparse_blocked_on_unannotated_callee_comparison: one comparison in a hostmod blocks 36 files, and two annotations clear it

**Status: found, measured, NOT fixed here.** Filed from the 2026-09-30 r2 sweep
re-measurement (`bugs/FORMAL_sweep_work_map_2026-09-30_r2.md`, row 3 of the
ranked terminal causes). The patch that clears it is two lines and is written out
below; it is not landed because its value is one file of coverage and it moves
the sweep's denominator by 34 (see §4), which is a decision about the sweep's
semantics rather than about this construct. Not claimed by any task at the time
of filing.

## What is wrong

`formal/hostmods/argparse.mojo` (2631 lines, the CPython-compatible `argparse`
for the formal backends, checked case-for-case against CPython by
`test_formal_argparse.py`) does not build. One comparison refuses it:

```mojo
def _lookup(spec, name, nlen):
    ...
        if _name_len(_rec(spec, i), k) == nlen and str_eq_n(
                _name_ptr(_rec(spec, i), k), name, nlen) == 1:
```

    build: `_name_len(...) == nlen` compares two values this path can only call
    numbers, and at least one of them arrived from a call that does not say what
    it returns. … The missing thing is the CALLEE's return type: annotate it
    `-> str` or `-> int`, which is what puts the answer in the dylib manifest's
    signature and lets this call site classify the result.

`_name_len` and `_fname_len` have no return annotation. `str_len`, on the other
side of the same comparison, **is** annotated (`formal/hostmods/os/_syscalls.mojo`
line 218: `def str_len(s) -> int`), so this is not "annotations do not cross a
module boundary" — measured, because that was the first hypothesis: a two-file
program whose imported `my_len(s) -> int` is compared against a local builds on
this path. It is two missing annotations in one module.

**Why it matters more than one file.** Every module a formal program imports
becomes a dylib on its link line, so a module that will not build takes **every
importer** with it. 36 files in the default arm64 sweep are blocked here, and
they are not a corner of the tree: `tools/memcap.py`, `tools/control.py`,
`tools/memslot.py`, `tools/suite.py`'s own helpers, `test_formal.py`,
`test_formal_run.py`, `test_formal_dylib.py`, `checked_run.py` — most of this
repo's own test suite and tooling. The refusal also **re-classifies**: a file
that imports `argparse` today is reported `codegen/dependency` (a gap in the
backend, in the denominator); once argparse builds, the same file is reported
`not-answerable/host-import` (a fact about the target, in no rate).

## The smallest reproducing program

Twelve lines, no imports, both architectures, no arguments:

```mojo
def nlen_of(rec, k):
    if rec == 0:
        return 0
    return 3


def lookup(spec, name, nlen):
    if nlen_of(spec, 0) == nlen:
        return 1
    return 0


def main(n):
    return lookup(n, "x", n)
```

```console
$ python3 fire.py build --formal --no-prove --backend=arm64 repro.mojo
build: `nlen_of(...) == nlen` compares two values this path can only call numbers, …

$ sed -i '' 's/^def nlen_of(rec, k):/def nlen_of(rec, k) -> int:/' repro.mojo
$ python3 fire.py build --formal --no-prove --backend=arm64 repro.mojo
Built: …/repro.aout  [arm64/macho]
```

The refusal needs three things and no more: a call to a function with **no
return annotation**, a **non-literal** on the other side (a literal is exempt —
`f(x) == 5` is a numeric comparison in every case the corpus has), and a
comparison operator. `print`, `len`, `while` and arithmetic are not involved.

## The fix, and what it buys — MEASURED

```mojo
-def _name_len(rec, k):
+def _name_len(rec, k) -> int:
...
-def _fname_len(p):
+def _fname_len(p) -> int:
```

Both return a length. Re-sweeping exactly the 37 files this cause blocks, with a
**cold CAS** (see `FORMAL_sweep_cache_ignores_imports.md` — the first attempt
served 35 of 37 verdicts from cache and measured nothing):

```console
$ python3 tools/memslot.py --gb 16 --label sweep37nc -- env \
      GMOJO_HOME=$PWD/.tmp/gmojo_nc python3 tools/formal_sweep.py -j 4 -t 60 \
      `cat .tmp/argparse37.txt`
[arm64] 37 files: PASS=1 not-pass=36
  pass                            1
  codegen                         2     module-global name has no storage x1,
                                         a TYPE name placed as a value x1
  not-answerable/host-import     34     platform x6, subprocess x6, json x5,
                                         concurrent.futures x4, collections x3,
                                         fcntl x3, ast x1, ctypes x1, html x1,
                                         math x1, posixpath x1, shutil x1, signal x1
```

**Ceiling: 1 of 37.** So:

* `formal/hostmods/argparse.mojo` itself reaches `pass` (it is the only file
  whose own body is the blocker).
* 34 files **leave the codegen denominator** — they import a host module with no
  Mojo source, which is a fact about the target.
* 2 files stay in it behind a different construct (`STAGES` has no
  module-global storage; `'int'` as a return annotation read as a value).

**"FILES BLOCKED" is an upper bound, and here the bound is 1/37.**

## Why it is not landed

1. **It buys one file of coverage.** 37 blocked, 1 passes. Every other one of
   those 36 files is blocked by something else, and for 34 of them what it is
   blocked by is not a backend gap at all.
2. **It changes the headline rate for a reason that is not coverage.**
   `112/481 = 23.3%` becomes `113/447 = 25.3%`: +1 in the numerator, −34 in the
   denominator. That is a real improvement in what the sweep can say and no
   improvement in what the backend can lower, and the two should not be confused
   in a planning document. Whoever owns the sweep's class semantics should say
   which of the two they want to be quoted.
3. The construct itself is not the backend's problem. `model.py`'s refusal is
   **right**: a `char *` is compared by address, `c = mk("abc")` and
   `d = mk("abc")` are unequal pointers, and a program that took the other
   branch would be silently wrong on both architectures. The gap is that a
   module of 2631 lines written against CPython's own source carries two
   unannotated helpers, and nothing in `test_formal_argparse.py` caught it
   because that suite tests the BEHAVIOUR of programs that import argparse, not
   whether argparse itself builds.

## The exact next step

1. Land the two annotations **with a test that asserts the module builds**, not
   only that programs importing it behave. The natural home is
   `test_formal_argparse.py`; the cheapest honest form is one case that runs
   `build --formal` on `formal/hostmods/argparse.mojo` itself and requires exit
   0, because that is the assertion whose absence let 36 files be blocked by a
   module nobody built.
2. Grep the other hostmods for the same shape — `formal/hostmods/{os,sys,struct,
   time,hashlib,re}.mojo` — and annotate. `str_len`/`str_eq_n`/`str_alloc` in
   `os/_syscalls.mojo` are annotated; `_syscalls.py`'s neighbours are the
   question. A refusal-free build of each hostmod is the measurement, and it is
   one command per module.
3. If the sweep's denominator is going to keep moving like this, the rate needs
   a second number next to it ("files whose only blocker is a construct, not a
   host import"), because a fix that reclassifies 34 files out of the
   denominator will otherwise look like the biggest win on the tree.

## Files

* `formal/hostmods/argparse.mojo:540` `_name_len`, `:954` `_fname_len`
* the refusal: `formal/model.py:2203` `string_compare_word_refusal` — the
  `compares two values this path can only call numbers` message
* the sweep log and the 37-file list: `.tmp/sweep_20260930_r2.log`,
  `.tmp/argparse37.txt` in the worktree that produced
  `bugs/FORMAL_sweep_work_map_2026-09-30_r2.md`
* the ranking: `tools/formal_sweep_causes.py`, row 3; the coverage test for it:
  `test_refusal_taxonomy.py` (`CAUSE_SAMPLES`)