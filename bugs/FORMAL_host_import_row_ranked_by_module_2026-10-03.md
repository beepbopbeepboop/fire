# FORMAL_host_import_row_ranked_by_module_2026-10-03: the 241-file host-import row, ranked, and what each module is actually worth

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
| 15 | ? | unreachable | `zlib` | not measurable (built into the interpreter, no stdlib source) | the three biggest codegen rows are all behind a module nobody has written; a project, §5 |
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
| 1 | 1 | modelled | `posixpath` | eight names | **THE MODEL IS WRITTEN**: `formal/hostmods/os/path/__init__.mojo` IS CPython's `posixpath`. What is missing is the SPELLING — a `formal/hostmods/posixpath.mojo` re-exporting `os.path`, as `os/__init__.mojo` already does for its own five names. One file (`test_formal_os.py`), and that file spells `os.path` everywhere else |
| 2 | 2 | modelled | `datetime` | `datetime` x2 | a clock this tree reads plus arithmetic; the ANSWER is the shaped record `bugs/FORMAL_time_struct_shaped_answers.md` |
| 2 | 0 | modelled | `resource` | — | `getrusage(2)` is libSystem and `struct rusage` is a fixed layout; 2 files, and both spell `getrusage(RUSAGE_CHILDREN)` |
| 3 | ? | unreachable | `builtins` | — | all three spell `set(dir(builtins))`: the interpreter enumerating itself |
| 1 | 0 | unreachable | `sysconfig` | — | `fire.py` imports it and never uses it, so fixing it would move nothing |

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
and not one of the four sampled stops on `tempfile` any more. The other 73 are
stopped by names the module deliberately does not export, and the reasons are
in the module's own docstring and in
`bugs/FORMAL_tempfile_context_manager_needs_a_way_out_of_a_with.md`:
`TemporaryDirectory` (64 files — its contract is the removal on the way OUT of a
`with`, and there is no `__exit__` to hook), `NamedTemporaryFile` (9 — a FILE
OBJECT is more than one 64-bit word) and `mkstemp` (2 — a two-word tuple).

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
2. **`html.escape`, 1 file.** The cheapest honest module left in the row: five
   character replacements over `str_replace_all`, `test_formal_html.py` as seven
   lines of comparison against CPython over a corpus with `&<>"'` in it. Listed
   here rather than done because a work map that quietly does its own item 2 is
   not a work map.
3. **`formal/hostmods/posixpath.mojo`, 1 file.** A re-export of `os.path`, which
   `os/__init__.mojo` already does for five of its names. One file that spells
   `os.path` everywhere else is thin evidence, which is the honest reason it is
   item 3 and not item 1.
4. **`glob`, 18 files** — `formal10-3`'s, not this row's.
5. **The six pure-closure modules** — nothing to do. Whoever picks them up should
   read the module that really stops those files out of §4's table, which is the
   finding the `uses` column exists to deliver.

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