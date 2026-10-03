# FORMAL_tempfile_context_manager_needs_a_way_out_of_a_with: the 73 files `tempfile` cannot honestly reach

**Claim** `sweep12:hostmods-rank` on `work/formal12-hostmods-rank`. Companion to
`bugs/FORMAL_host_import_row_ranked_by_module_2026-10-03.md` §4, which is where
the ranking and the per-module verdicts live.

## What I ran

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/formal_sweep_causes.py --host bugs/sweeps/sweep-arm-7.txt
python3 test_formal_tempfile.py -v                     # 7/7, arm64 and x86-64
python3 test_formal_hostmods_census.py tempfile.mojo   # BUILD on both
```

and, for the four builds in the companion's §4, one `memslot`-wrapped
`python3 fire.py build --formal --no-prove --backend=arm64 -o … <file>` per file.

## What I saw

`tempfile` is the largest host-import row in the sweep: **111 files, 109 of
which bind a name the module publishes** (`TemporaryDirectory` x64, `mkdtemp`
x51, `NamedTemporaryFile` x9, `mkstemp` x2), so the row is work and not closure.
`formal/hostmods/tempfile.mojo` answers `gettempdir`, `gettempprefix`,
`TMP_MAX` and `mkdtemp(prefix)`, differential-tested against this interpreter's
own `tempfile` on both backends.

**It moves 0 of the 111 files to `pass`, and 73 of them cannot be reached by any
honest `tempfile` on this target.** The remaining 38 now stop somewhere real —
four of them were built by hand and none of the four mentions `tempfile` any
more — and that is the whole of what the module bought. The 73 break down as:

| name | files | why it is absent |
|---|---:|---|
| `TemporaryDirectory` | 64 | **its contract is the removal on the way OUT of a `with`** |
| `NamedTemporaryFile` | 9 | a FILE OBJECT — a `FILE *`, a cursor and a buffer — is more than one 64-bit word |
| `mkstemp` | 2 | its answer is `(fd, name)`, a two-element tuple, and a tuple is a frame blob |

## Why `TemporaryDirectory` is the one that matters, and why it is not shipped

`formal/hostmods/contextlib.mojo` measured the shape, arm64 and x86-64:

```
def nullcontext(v): return v
with nullcontext(11) as x: ...        # x binds to 11 on BOTH backends
```

`with EXPR as TARGET` evaluates `EXPR`, evaluates the body, and binds `TARGET` to
the expression. **There is no dispatch through an `__exit__` to hook**, and
nothing in the module or the backend changes that.

So a `TemporaryDirectory` modelled as "make the directory, hand back its path"
would build, run, print the right answers, and **leave the tree behind** — and
`contextlib.mojo`'s own rule is the reason it is not shipped:

> A name that answers the easy half of its contract and drops the half that
> matters is the one thing a mirror of CPython must not export.

It is worth being concrete about why the easy half is *tempting* here, because
the 64 call sites in this repository use the bound name as a path and nothing
else, so `with tempfile.TemporaryDirectory() as d:` would typecheck, run, and
leave the tree in `$TMPDIR` — a disk-usage wart rather than a wrong answer for
these 64 callers. That is exactly the judgement the rule forbids: the module
would be correct for every caller in this corpus and wrong for the module's
contract, which is the arrangement that costs the most later, because the next
64 files that use it are not this repository's.

`NamedTemporaryFile` and `mkstemp` are shorter arguments and are written out in
full at the bottom of `formal/hostmods/tempfile.mojo`'s docstring: a FILE
OBJECT is not one word (`formal/hostmods/io.mojo` says the same about
`sys.stdout`), and a `(fd, name)` tuple is a frame blob
(`bugs/FORMAL_time_struct_shaped_answers.md`, the same limit that keeps
`shutil.disk_usage` and `os.path.split` from returning their own answers).

## The exact next step

**A `with` statement that runs something on the way out.** In CPython's terms, a
context manager here has to be able to be one of two things, and today it can
only be the second:

1. an OBJECT with `__enter__`/`__exit__` — impossible while a value is one
   64-bit word, because an object that holds a path and a cleanup flag is two
   words; **or**
2. the KEYWORD ITSELF carrying the cleanup — `with EXPR as TARGET` already binds
   the target, and what is missing is that the block's exit has no way to call
   anything.

Option 2 is the smaller change and it is the one that would pay across this row
and two others. A `with` that also lowered an optional cleanup FUNCTION —
`with EXPR as TARGET:` where `EXPR`'s module can name one — would give
`TemporaryDirectory` a body, `contextlib.closing` the call it silently skips
today (measured in that module's docstring: `with closing(7) as v:` builds,
runs, prints `v=7`, and CPython raises `AttributeError`), and `shutil`'s
`chdir` its restore. It is a change to how a `with` is lowered in **both**
backends, which is why it is filed here and not attempted.

The value model question underneath it is the same one
`bugs/FORMAL_module_state_no_storage.md` owns, and it is worth saying which half
is which: the CLEANUP FUNCTION would be a name and a call, both of which a
module can have. Nothing about the cleanup needs storage that a `__mod_init_func`
slot does not already need.

## The second-order item, which is a compiler change and not a module

`mkdtemp(prefix=…)` works and 50 of the 51 corpus call sites spell exactly that.
The one that does not (`prefix="eqtest-", dir=HERE`, three sites) is refused
with `unexpected keyword argument 'dir'`, and **CPython's own signature is
`mkdtemp(suffix=None, prefix=None, dir=None)`** — so a faithful three-parameter
mirror is a function no caller in this corpus can call, because **a call across a
dylib boundary cannot fill a default**: the argument register is not written for
a value this image cannot see, and the backend refuses it by name rather than
passing a stack address (`bugs/FORMAL_default_argument_not_applied_across_a_dylib.md`;
`os.mkdir(path, mode)` and `shutil.rmtree(path, maxdepth)` are spelled with every
argument for the same reason).

Measured while writing this, and worth recording because it is the fact that
decides the shape: **a keyword argument at such a call DOES arrive.**
`os.makedirs(path="kwdir", mode=511)` builds and creates the directory, and a
one-parameter function called as `one(prefix="P")` builds and answers. So the
capability needed is narrow — *fill the callee's defaults from the callee's own
declaration* — and `bugs/FORMAL_host_import_row_5_measured.md` §"The one line to
take from this document" already argues it is worth more than every host module
in the row put together. This document does not re-open that argument; it is the
second time the same capability has been measured, from the other direction.

## What was verified, and what was not

`test_formal_tempfile.py` (7 groups, both architectures), the hostmods census row
for `tempfile.mojo`, `test_formal_imports.py`, `test_formal_admitted.py`,
`test_formal_sweep_truth.py` and `test_refusal_taxonomy.py` all pass. **No
`make gate` and no sweep**: this is a `formal/hostmods/` module plus a test file,
and the integrator runs the gate once over everyone's work.