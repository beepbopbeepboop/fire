# FORMAL_host_import_row_ranked_by_module_2026-10-03: the 241-file host-import row, ranked, and what each module is actually worth

**Status 2026-10-04 (`work/formal21-5`): §5's queue is CLOSED — and its biggest
item, `zlib`, was never a project. It was three DEAD `import zlib` lines, and
the row's 29 files read nothing from the module.** The measurement is in §A
below; the three imports are gone and so are the `resource`, `sysconfig` and
`traceback` rows, which were the same shape. **§3's false diagnostic is fixed**
— the ranking's `UNTIERED` note quoted a sentence the build stopped emitting two
refactors ago — and so is the hole in §1's own instrument that let a row of dead
imports read `uses: ?` for five sweeps: a module with no readable names now has
a FALLBACK that asks whether any blocked file uses it at all, and zero is a
sound answer to that. The other three items landed before this round and the
text below still describes two of them as undone.

**Claim** `sweep12:hostmods-rank` on `work/formal12-hostmods-rank`. Every number
below is read off `bugs/sweeps/sweep-arm-7.txt` (the 2026-10-02 arm64 sweep,
complete over all 668 files) with

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/formal_sweep_causes.py --host bugs/sweeps/sweep-arm-7.txt
```

which is a mode that landed with this work. It is the successor to
`bugs/FORMAL_host_import_row_5_measured.md` (the `-5` sweep's ranking, and
`formal8-7-r2`'s claim — **not edited here**) and to §4 of
`bugs/FORMAL_sweep_work_map_2026-10-02_b7.md`, whose `by module: tempfile x111,
importlib x48, glob x18 …` line was written by hand off the log and is now a
tool's output.

## 1. Why the row needed its own ranking

The class is **241 files, the biggest in the sweep** (against 285 codegen /
codegen-dependency lines), and the instrument that ranks the codegen half
(`tools/formal_sweep_causes.py`) **could not rank it at all**: a host-import line
is not a refusal about a construct, it is a refusal about a MODULE, so the
question a person asks of the row is "which module", and there was no answer
that tool could give. `--host` is that answer, and it carries the same two
properties the cause table has earned the right to claim:

* **`FILES BLOCKED IS AN UPPER BOUND**, for the same reason and with the same
  force: the formal backend builds a dylib for every module in a file's eager
  import closure, so `gimple_codegen.py imports 'zlib'` blocks every file that
  imports `gimple_codegen` whether or not any of them says `zlib`. The `uses`
  column is the one that decides WORK from WAITING.
* **`uses` counts a SPELLING, not a word.** The codegen column can search for a
  whole word because the names it looks for are `BinaryHeap` and `slice`. The
  names here are `copy`, `types`, `signal`, `html` and `datetime`, which are
  ordinary English words that appear in prose, in comments and in the bodies of
  functions that have nothing to do with the module — a word search would report
  `copy` as used by five files when it is used by none. A file counts as using a
  module when it contains `mod.NAME` with `NAME` one the module declares, or a
  `from mod[.sub] import …` line binding one.

The names come from **CPython's own stdlib source, parsed**, with `__all__`
winning where CPython defines it. `tier` is read through
`formal/imports.py::host_module_tier` and `model` from `formal/hostmods/`;
neither is copied, because a copy is a list that rots the day a module is
written — which is the ordinary way this row gets smaller.

## 2. The ranking

`files` counts a file once per module it is blocked by. 241 lines, 241 files,
24 modules — no file is in two rows in this sweep.

| files | uses | tier | module | what the blocked files bind | verdict |
|---:|---:|---|---|---|---|
| **111** | **109** | written | **`tempfile`** | `TemporaryDirectory` x64, `mkdtemp` x51, `NamedTemporaryFile` x9, `mkstemp` x2 | **MODELLED 2026-10-03**, §4 below |
| 48 | 1 | unreachable | `importlib` | `import_module` x1 | nothing to do: 47 of 48 are closure behind `fire_compiler`, and the one that uses it needs an embedded CPython |
| 18 | 9 | modelled | `glob` | `glob` x9 | **OWNED** — `formal10-3` holds `FORMAL_glob_copy_collections_io_not_attempted.md`, which has the analysis |
| 15 | ? | unreachable | `zlib` | not measurable (built into the interpreter, no stdlib source) — **and MEASURED since, by another question: 0. §A. The three `import zlib` lines this row rested on read nothing from the module, so it was never a project** | ~~a project, §5~~ — **CLOSED, §A** |
| 9 | 9 | modelled | `collections` | `Counter` x4, `namedtuple` x3, `defaultdict` x3, `OrderedDict` x1 | the ANSWER already exists and is a message, not a module: `HOST_MODULE_ADVICE` tells those callers to declare a `struct`. `formal8-1` owns the capability (`FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md`) |
| 6 | **0** | modelled | `types` | — | **nothing to model**: every blocked file names nothing `types` declares. This is the finding, not an omission |
| 6 | 1 | unreachable | `signal` | `signal` x1 | 5 of 6 closure; a signal handler is a host object |
| 5 | 4 | modelled | `copy` | `deepcopy` x3, `copy` x2 | **OWNED** — `formal8-1`, same doc as `collections`: the two are one missing thing |
| 3 | 3 | unreachable | `unittest` | `TestCase` x3, `main` x2 | process-wide reporting machinery; `HOST_UNREACHABLE` says why |
| 2 | 2 | modelled | `atexit`→unreachable | — | 2 files, an interpreter shutdown path |
| 1 | 1 | written | `functools` | `lru_cache` x1 | one file, and a decorator is silently DROPPED (`FORMAL_functools_is_unbuildable_as_a_host_module.md`) |
| 1 | 1 | modelled | `inspect` | `getsource` x1 | one file; `getsource` reads source off a live interpreter |
| 1 | 1 | modelled | `shlex` | `quote` x1 | one file, and it is the shape `fnmatch`/`re` already have |
| 1 | ? | modelled | `itertools` | — | one file; generators are a documented limit |
| 1 | ? | unreachable | `asyncio`, `socket`, `traceback` | — | one file each, and all three are named in the tier rule itself |
| 1 | 1 | modelled | `html` | `escape` x1 | **REACHABLE AND SMALL**: `escape`/`unescape` are five character replacements over `os/_syscalls.mojo`'s `str_replace_all`, the `shlex` shape. One file (`tools/md2html.py`) is the whole prize |
| 1 | 1 | **WRITTEN 2026-10-03** | `posixpath` | eight names | **DONE — §5 item 3.** `formal/hostmods/posixpath.mojo` re-exports every public name of `os/path/__init__.mojo`, which IS CPython's `posixpath`, and `test_formal_os.py`'s new `posixpath` group runs the whole path corpus through that spelling against the same CPython oracle. It left `HOST_MODELLED`, which is what a written module does |
| 2 | 2 | modelled | `datetime` | `datetime` x2 | a clock this tree reads plus arithmetic; the ANSWER is the shaped record `bugs/FORMAL_time_struct_shaped_answers.md` |
| 2 | 0 | modelled | `resource` | — | `getrusage(2)` is libSystem and `struct rusage` is a fixed layout. **CORRECTED 2026-10-04, §A: the 2 files spell `resource.getrusage(resource.RUSAGE_CHILDREN)` inside the STRING of a child program they write out, never in code, and both imports were dead** |
| 3 | ? | unreachable | `builtins` | — | all three spell `set(dir(builtins))`: the interpreter enumerating itself |
| 1 | 0 | unreachable | `sysconfig` | — | `fire.py` imports it and never uses it, so fixing it would move nothing. **DONE 2026-10-04, §A: the import is gone** |

**THE COLUMN THAT DECIDES THE QUEUE IS `uses`, and it is 109/111 for exactly
one row.** Four modules in this table are pure closure (`types` 0, `resource` 0,
`sysconfig` 0, `asyncio`/`socket`/`traceback`/`itertools` unmeasurable or 0), and
for those the honest next step is not "write the module" — it is "find the
module that really stops those files", which is what §3 measured.

## 3. The six names that were in NEITHER tier — a diagnostic that was false

The tool printed `UNTIERED` for six modules, and that label turned "a name in
neither tier is a possibility" into a list. A name in neither tier is refused
with **"not a stdlib or sibling module, and no such file exists"**, which is
false of a CPython standard-library module — and it is the sentence that says
the reader has a TYPO, which is the wrong thing to tell someone whose import is
correct. Ten of the 241 files were reading it.

All six are classified as of this commit, each by the tier RULE rather than by
reading (`formal/imports.py`, and `test_formal_imports.py`'s new case):

| module | tier | why, in one line | files |
|---|---|---|---:|
| `builtins` | unreachable | `set(dir(builtins))` asks the interpreter to enumerate itself | 3 |
| `sysconfig` | unreachable | where an embedded CPython would be installed | 1 |
| `html` | modelled | five character replacements over a string | 1 |
| `datetime` | modelled | a clock `time.mojo` already reads, plus calendar arithmetic | 2 |
| `resource` | modelled | `getrusage(2)` is libSystem; `struct rusage` is `fs_stat_fill`'s exercise | 2 |
| `posixpath` | modelled | **the model is already written** — `os/path/__init__.mojo` IS CPython's `posixpath` | 1 |

Two consequences beyond the wording. `builtins` and `sysconfig` were being counted
by `tools/formal_sweep.py`'s **reach line** as REACHABLE — `host_module_tier`
answers `""` for a name in no tier and the reach line counts that as in-reach —
so ten files were on the wrong side of the only number that separates "a gap
with an owner" from "a fact about the target". And a name in a HOST tier now
outranks a same-named sibling file, which is what
`test_host_module_still_refused_despite_same_named_sibling` has always claimed:
the new test's first version put `builtins.mojo` next to the program importing
`builtins`, watched it resolve to itself, and reported a false pass.

**135 other CPython standard-library modules are still in neither tier**
(`bz2`, `curses`, `email`, `gettext`, …). They are not this row's problem — no
file in this sweep imports one — but the same false sentence is waiting for the
first one that does, and `tools/formal_sweep_causes.py --host` names them on
demand now.

## 4. What landed for `tempfile`, and the 73 files it did not reach

`formal/hostmods/tempfile.mojo` answers `gettempdir`, `gettempprefix`,
`TMP_MAX` and `mkdtemp(prefix)` — a real directory at mode 448 with eight
characters of CPython's own alphabet from `arc4random_buf` and CPython's
retry-on-collision loop. `test_formal_tempfile.py` is 7 differential groups
against this interpreter's own `tempfile` on **both** backends. `tempfile` left
`HOST_UNREACHABLE`, where it had been filed under "a terminal": the terminal
half of that claim still holds (nothing in the module asks for one) and the
`TMPDIR` half never did.

**It moves ZERO files to `pass`, and the measurement of what it DOES move is
four files, built by hand** (`python3 fire.py build --formal --no-prove
--backend=arm64 -o … <file>`, the sweep's own argv):

| file | stops on, after `tempfile` stopped being the answer |
|---|---|
| `test_container_membership.py` | `build_config` → `module_loader.py`: "this module's API is its top-level statements" — the **16-file** row of `FORMAL_sweep_work_map_2026-10-02_b7.md` §6 |
| `test_dict_tuple_key.py` | the same `build_config` → `module_loader.py` row |
| `comptime.py` | `cas.py` → **`glob`** — the 18-file row, owned by `formal10-3` |
| `test_coro_scoreboard.py` | `gimple_codegen.py` → **`zlib`** — the 15-file row |

So **38 files now stop somewhere real instead of on a module that had one**,
and not one of the four sampled stops on `tempfile` any more. The other 73 were
stopped by names the module deliberately did not export: `TemporaryDirectory`
(64 files — its contract is the removal on the way OUT of a `with`, and there was
no `__exit__` to hook), `NamedTemporaryFile` (9 — a FILE OBJECT is more than one
64-bit word) and `mkstemp` (2 — a two-word tuple).

**Updated 2026-10-03: `TemporaryDirectory` is ANSWERED** — the 64, which is
three quarters of this row. A `with` now lowers to the context-manager protocol
(`formal/build.py`'s `_rewrite_with_statements`, with `formal/model.py`'s
`struct_is_context_manager` for the rule), so `TemporaryDirectory` is a struct
with `__enter__`/`__exit__` and its removal on the way out is real:
`formal/hostmods/tempfile.mojo`'s `TemporaryDirectory` and `test_formal_
tempfile.py`'s `temporary-directory` group, on both architectures. **Measured
coverage effect: the sweep's verdicts barely move** — of the 241 repository
files that contain a `with`, 12 pass before and 12 pass after, and exactly one
file changes class — because those 64 files are mostly stopped by ANOTHER host
import first (`os`, `subprocess`, `argparse`), and the sweep reports the first
failing import. The other 11 (`NamedTemporaryFile`, `mkstemp`) are still absent
for the representation reasons in the module's docstring.

## 5. What is left to do, in the order the ranking gives

1. **`zlib`, 15 files.** Not a module to write but a project to argue about, and
   the argument is worth having once: DEFLATE is arithmetic over bytes, so a
   `formal/hostmods/zlib.mojo` could compute inflate/deflate itself the way
   `re.mojo` computes a match — nothing in that contradicts "a formal image links
   libSystem and nothing else", so the `HOST_UNREACHABLE` entry's premise (a
   library outside libSystem) is the thing to re-examine rather than inherit.
   Correct DEFLATE in this value model is a large piece of work; it is not a
   patch, and `gimple_codegen.py` (the one file that wants it) is also behind
   `binary_heap.mojo`.
2. ~~**`html.escape`, 1 file.** The cheapest honest module left in the row: five
   character replacements over `str_replace_all`, `test_formal_html.py` as seven
   lines of comparison against CPython over a corpus with `&<>"'` in it. Listed
   here rather than done because a work map that quietly does its own item 2 is
   not a work map.
3. ~~**`formal/hostmods/posixpath.mojo`, 1 file.**~~ **LANDED 2026-10-03
   (`work/formal13-4`).** A re-export of `os.path`, which `os/__init__.mojo`
   already does for five of its names, plus the test that makes it a measurement
   rather than a transcription: `test_formal_os.py`'s `posixpath` group runs the
   `strings` group's whole corpus — 34 path shapes, seven one-argument functions,
   three two-argument ones over a cross product and a pair list, and the one
   documented deviation — through `from posixpath import …` and compares every
   answer against this process's own `posixpath`. Same corpus, same oracle, other
   spelling: which is the only assertion a re-export can be wrong about, since a
   name bound to the wrong function still builds.

   What it cost, so the next writer is not surprised: **three tables had to learn
   about it**, and one of them is a new shape the account had never had.
   `test_formal_link_accounting.py`'s `HOST_SET_ADDED_TIERS` loses its
   `posixpath` row (a name with source does not belong in a claim tier);
   `test_formal_imports.py`'s placement table loses it too, which is the test
   that used to assert a `posixpath` import is refused as a host module; and
   `test_formal_admitted.py`'s `ADMITTED_COUNTS` gains `"posixpath": 0`, because
   a module with a model that is not in that table is a claim of trust nobody
   counted. The new one is `HOST_SET_ADDED_THEN_WRITTEN`, because `posixpath` is
   the first name that was ADDED to a tier after the split and then WRITTEN: it
   is in neither `PRE_SPLIT_HOST_MODULES` nor any tier, so the "what left the host
   set" account could not see it move — and a name that cannot be seen to move is a
   name whose tier entry can rot, which is how `tempfile` sat in
   `HOST_UNREACHABLE` with an `mkdir` behind it for a day.

   **And the honest measure of the win, which is what §2 already said:** one file
   moves, and `test_formal_os.py`'s `posixpath.` names are its CPython ORACLE
   rather than a program to compile, so the sweep row it unblocks is a test
   harness asking this backend to compile itself. The capability was never
   missing; the NAME was, and a caller that spells `import posixpath` now reaches
   the model.
4. ~~**`glob`, 18 files** — `formal10-3`'s, not this row's.~~ **LANDED 2026-10-04** (`formal20-hostmods-wave3`); 51 files on the `-10` log, and `bugs/FORMAL_the_host_import_rows_after_glob_ranked_by_what_they_actually_spell.md` is the successor ranking.
5. **The six pure-closure modules** — nothing to do. Whoever picks them up should
   read the module that really stops those files out of §4's table, which is the
   finding the `uses` column exists to deliver. **DONE 2026-10-04, §A: three
   of the six were DEAD IMPORTS, and the other three are closure behind rows
   that have owners.**

## 6. Reproducing this

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/formal_sweep_causes.py --host bugs/sweeps/sweep-arm-7.txt
python3 tools/formal_sweep_causes.py --host --json bugs/sweeps/sweep-arm-7.txt
python3 tools/formal_sweep_causes.py --host --min 14 bugs/sweeps/sweep-arm-7.txt
```

No lean, no proof, no gate: the ranking reads a log and parses CPython's stdlib.
The four builds in §4 are `memslot`-wrapped single-file builds; a full re-sweep
is not a light worker's to run, and the CAS means a re-run with nothing changed
reads a file per file.

---

## A. 2026-10-04: the `zlib` row was three dead imports, and the queue is closed

**§5 item 1 called `zlib` "not a module to write but a project to argue about"
and asked for the argument to be had once. The argument is that nobody uses it.**
Three files in this repository import it:

    $ grep -n "zlib" gimple_codegen.py mojo/middle/types.py mojo/middle/coro.py
    gimple_codegen.py:12:import zlib
    gimple_codegen.py:3089:        # zlib binding (mojo_zlib.h)      <- a COMMENT
    gimple_codegen.py:3090:        'mojo_zlib_compress':  (...)      <- RUNTIME symbols
    mojo/middle/coro.py:2954:import zlib as _zlib
    mojo/middle/coro.py:2958:    # `_crc32_str`, NOT `zlib.crc32`     <- a COMMENT
    mojo/middle/types.py:24:import zlib
    mojo/middle/types.py:1096:    string's bytes — IDENTICAL to `zlib.crc32(s.encode())`.

**Every other mention is prose.** `gimple_codegen.py` names `mojo_zlib_*`, which
is this project's own C runtime binding (`runtime/fire_zlib.h`), not CPython's
module; `mojo/middle/coro.py` says in a comment that it deliberately does NOT call
`zlib.crc32`; `mojo/middle/types.py`'s two mentions are a docstring. So the 29
files the `-10` sweep files under `zlib` are import CLOSURE behind three lines
that read nothing, and **a `formal/hostmods/zlib.mojo` — DEFLATE and inflate
computed the way `re.mojo` computes a match — would have moved 0 of them.**

That is why nobody looked: §1's `uses` column prints `?` for `zlib`, because
`zlib` is built into CPython's interpreter and has no stdlib source here to parse,
and a `?` is the honest answer to "which of its names does this file bind". It
is not the answer to the question the row is actually asking. **So the
instrument now asks the question it can answer**, which is what §B is.

### The four rows that were dead imports, and what each file stops on now

One row each, and every file in each row blocked on an import nothing read. The
`after` column is `python3 fire.py build --formal --no-prove -o … <file>`, the
sweep's own argv, on this tree:

| row | files | the dead import | what the file stops on now |
|---|---:|---|---|
| `zlib` | 29 | `gimple_codegen.py:12`, `mojo/middle/types.py:24`, `mojo/middle/coro.py:2954` | `fire_compiler.py imports 'importlib'` (`build_module.py`, `test_coro_bugs.py`) |
| `resource` | 2 | `tools/mem_slope.py:33`, `test_selfhost_memory.py:32` — both spell `resource.getrusage(resource.RUSAGE_CHILDREN)` inside the STRING of a child program they write out | `build_config` → `module_loader.py`: `os.path reads 'path'`, which is `FORMAL_module_state_no_storage` |
| `sysconfig` | 2 | `fire.py:23` — §2's own row already said "imports it and never uses it, so fixing it would move nothing" | `importlib` |
| `traceback` | 1 | `test_coro_bugs.py:21` | `gimple_codegen` → `fire_compiler` → `importlib` |

**34 files' rows are gone and 0 reach `pass`**, which is the prediction every
host-import row in this project has made (`…_b10.md` §1.3 says the same of
`glob`: 50 files, 42 changed class, 0 passes). The reason is the same in all four
cases and it is not a disappointment: the files behind these rows are the
compiler's own front end, and what they stop on next is a real refusal —
`importlib` (54 files, `uses: 0`, closure behind `fire_compiler`) and the
module-state row (30 files).

**`resource`'s row is the one the doc got wrong in its own table, and the
correction is worth stating.** §2 says of it: "2 files, and both spell
`getrusage(RUSAGE_CHILDREN)`". They do — in the source text of a child program
they write out with `subprocess`, which is a Python program this backend never
compiles. The parent process calls nothing. A reader who took the row at face
value would have gone looking for a `getrusage` binding.

### The queue, item by item, after this round

| §5 item | state |
|---|---|
| 1. `zlib` | **CLOSED — it was never a project. §A.** |
| 2. `html.escape` | **LANDED 2026-10-03, in another branch**: `formal/hostmods/html.mojo` (`escape`, five ordered replacements over `_syscalls.mojo`'s `str_replace_all`) with `test_formal_html.py` as the differential. The text below still calls it "the cheapest honest module left in the row" — it is written. |
| 3. `formal/hostmods/posixpath.mojo` | **LANDED 2026-10-03** (`work/formal13-4`), and `test_formal_posixpath.py` alongside it. |
| 4. `glob` | **LANDED 2026-10-04** (`formal20-hostmods-wave3`): `formal/hostmods/glob.mojo`, and `bugs/FORMAL_the_host_import_rows_after_glob_ranked_by_what_they_actually_spell.md` is the successor ranking — 51 files on the `-10` log, 16 of them users, the rest closure. |
| 5. the six pure-closure modules | **DONE, and it was the finding rather than the chore.** `resource`, `sysconfig` and `traceback` were dead imports (§A). `types` (10 files, 10 users), `itertools` (11, `>=3`), `builtins` (2, `>=2`), `asyncio`/`socket` (closure, 0) are closure behind other rows, and the three rows with real users are asserted to keep having users by `test_formal_sweep_truth.py`'s `test_the_other_rows_still_have_users`. |

**The ranking as it stands**, re-based on `bugs/sweeps/sweep-arm-10.txt` (the
2026-10-04 arm64 run, 710 files) with the tool as it is now:

    $ python3 tools/formal_sweep_causes.py --host bugs/sweeps/sweep-arm-10.txt
    files  uses  tier        module
       54     0  unreachable  importlib          (uses: 0 — closure)
       51    16  written      glob                formal/hostmods/glob.mojo
       29     0  unreachable  zlib                <- DEAD IMPORTS, §A
       24    11  modelled     collections         (claimed: hostmods-platform)
       13    13  unreachable  unittest            (process-wide reporting)
       11     3  modelled     copy                (formal8-1: a type factory)
       11   >=2  modelled     itertools           (generators, a documented limit)
       10    10  modelled     types               (formal8-1: a type factory)
    244 blocked file x module pairs over 244 files, in 27 modules

against the 241 files / 24 modules of §2. Every row with a user in it either has
an owner or names a limit; the three that do not (`importlib`, `zlib`, and the
`types`/`collections` type factories) are what §A and the owners' docs say they
are.

### What is deliberately NOT done

* **`collections` and `copy` have dead imports too**, measured:
  `consolidate_string_pool.py:15`, `tools/formal_chain_probe.py:91` and
  `tools/formal_field_walk_differential.py:32` all import `collections` and read
  nothing from it, and `tools/apply_extraction.py:14` imports `copy` likewise —
  and `fire_compiler.py:62`'s `from abc import abstractmethod` is unread. **Left
  alone**, because each of those rows has files that really do use the module
  (`collections` 11 of 24, `copy` 3 of 11, `abc` is the parser's own closure), so
  a dead import in one file costs nothing and the rows are another worker's to
  measure. The census is `test_formal_sweep_truth.py`'s `_imports_of` plus
  `tools/formal_sweep_causes.py::_host_mentions_module`, both of which are
  importable, so the list is a `python3 -c` away rather than an afternoon.
* **`atexit`, `builtins` and `itertools` are left as they are**, each with users
  (`test_ab_native.py`'s `atexit.register`, `set(dir(builtins))`, and three
  files that spell `itertools`), and each pinned as having users so that a future
  reader cannot widen §A to "every module with no readable names" by accident.

## B. 2026-10-04: two defects in the instrument this document is about

### B1. The `UNTIERED` note quoted a sentence the build stopped emitting

`tools/formal_sweep_causes.py` printed, for a module in neither tier and with no
model:

> `UNTIERED: tokenize is in NEITHER formal/imports.py tier, so its refusal
> reads "not a stdlib or sibling module, and no such file exists" — a statement
> about module RESOLUTION that is false of a CPython standard-library module`

That sentence stopped being what the build says when
`formal/imports.py::unresolvable_import_error` grew its THIRD wording
(`bugs/FORMAL_stdlib_module_names_are_not_classified.md` §0, a claim that is not
this document's): a name CPython ships and no tier names is now refused as "a
CPython standard-library module, which has no Mojo source in this tree and no
tier …". **So the ranking was quoting a sentence the compiler cannot emit, on
every untiered row it printed** — three modules and four files on the `-10` log
(`tokenize` x2, `plistlib` x1, `sqlite3` x1) — and none of the counts around it
was wrong, which is what made it invisible.

The note now asks `formal/imports.py::unresolvable_import_error` for the clause
and prints that, against one of the files the row actually blocked, because the
build owns the wording and a copy is right until the wording moves. This is the
same defect `tools/formal_sweep.py::_is_cpython_stdlib` had before it became a
delegation, and §3 of this document is the one that found that one.

### B2. `uses: ?` for a module with no readable names, which is how §A stayed invisible

§1's column is right to print `?` when it cannot read the module's declared names
— `zlib` is built into CPython's interpreter, so there is no source here to
parse, and a count from a list written in the tool would be a number nobody could
check. **But that is the answer to "which of its names does this file bind", and
the row's question is "does any file use it at all".** The second question has a
sound answer at zero: a file that never mentions the module cannot be using
whatever it exports.

`_host_mentions_module` is that reader, and it answers **by AST** rather than by
word, which is the whole of the discipline: the corpus says `zlib` and `resource`
in PROSE (the two comments quoted in §A) and inside STRINGS (`mem_slope.py`'s
child-program source), and a regex over raw source would have reported all three
of the files that import `zlib` as users of it — which is the direction this
column must never be wrong in. All four spellings are handled: `mod.NAME`,
`from mod import NAME` (which never spells `mod` at all), `import mod as alias`,
and an import whose bound name is only re-exported.

The printed row now reads:

    29     0  unreachable  zlib
        uses:  0 — no blocked file READS zlib: not one imports it and binds
               something it then uses in code (a comment or a string is not a
               use), so the row is import CLOSURE whatever zlib exports

and for a module with users whose names still cannot be read it says `>=N — a
LOWER BOUND`, and for one with a `.mojo` file in the row it says NOT MEASURED,
because Python's parser is not a Mojo parser and a zero from one would be a
guess. **The other `?` rows on the `-10` log are decided by the same question**:
`itertools` `>=2` and `builtins` `>=2` are LOWER BOUNDS and are real users;
`resource` 0 (dead imports, §A) and `atexit` 0 — whose one blocked file is
`_ab.py`, which imports `test_ab_native.py` and never spells `atexit`, while
`test_ab_native.py` itself really does call `atexit.register`. `uuid`, `functools`
and `shlex` have readable names and are counted the ordinary way.

**Tests**: `test_refusal_taxonomy.py` 237/237 (was 228 on this tree before this
round, +9: the `UNTIERED` clause is asked for rather than quoted, and seven
spellings of the `uses` fallback including the comment-only and string-only ones
plus the `.mojo` refusal), and `test_formal_sweep_truth.py` 104/104 with a new
`TestHostImportRowsAreNotDeadImports` — the premise that the four names are
unbuildable is asked of the build's own wording, the dead-import census is the
assertion, and the three rows WITH users are asserted to keep having them.

```console
$ python3 test_refusal_taxonomy.py
refusal taxonomy: PASS (237/237 checks, 38 families, 61 causes)
$ python3 test_formal_sweep_truth.py
Ran 104 tests in 25s — OK
$ for f in build_module.py fire.py tools/mem_slope.py test_coro_bugs.py; do
      python3 fire.py build --formal --no-prove -o .tmp/z/x "$f"; done
```