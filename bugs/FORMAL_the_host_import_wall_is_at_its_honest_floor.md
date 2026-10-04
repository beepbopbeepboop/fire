# FORMAL_the_host_import_wall_is_at_its_honest_floor: what is left of the 203-file host-import row, and why each remaining name is out of reach

**Claim** `project26:hostmods-wave4` on `work/formal26-hostmods-wave4`. Measured
2026-10-04 against `master` at `faef18b3` on the corpus of
`bugs/sweeps/sweep-arm-11.txt`'s **203** `not-answerable/host-import` files.
This is the wave note for three modules written (`formal/hostmods/{traceback,
signal,operator}.mojo`) and it is the queue for everything the wave could not
write, which is most of what is left.

**The finding, in one sentence: after this wave, every remaining name on the row
needs an object a freestanding image that links libSystem and nothing else does
not have, so the row is not a queue of small modules any more — it is a queue of
six missing capabilities with 20 names on them.** The table in §3 says which is
which, per name, with the spelling census that decides it.

## 0. What landed afterwards (2026-10-05, `work/formal27-6`): the walk is a TOOL,
## and the `unittest` row is re-measured

**§6's third bullet is closed: the walk is `tools/formal_host_import_wall.py`,
not scratch, and its readers are pinned by `test_formal_host_import_wall.py`
(17 rows, 0.7 s, no build and no Lean).** §5 below is the promotion note and now
points at the tool rather than restating it; §3's numbers are the tool's, and
three of them are corrections rather than drift.

* **`sweep` was an UNDERCOUNT, by exactly the rows no tier classifies.**
  `formal/imports.py::unresolvable_import_error` has three arms and two of them
  name a host module, and the reader this doc's `sweep` column used knew only
  the first: "is a host module (CPython standard library)". The other — "is a
  CPython standard-library module, which has no Mojo source in this tree and no
  tier …" — is `FORMAL_stdlib_module_names_are_not_classified.md`'s own fix.
  Measured: **4 of the 203 lines, and all four are that arm**, so the table
  below said `tokenize` 0 / `plistlib` 0 / `sqlite3` 0 where the log says 2 / 1 /
  1. A column that drops the no-tier wording is silent about the rows
  classification is for, which is the one bias worth naming. The tool matches
  both and prints its own coverage (`203 of 203`).
* **The corpus grew, so `reach` is a different number and `alone` mostly is
  not.** 735 files walked against this doc's 203-file corpus, so `importlib`
  reads 236 where this table says 170 — the closure behind it grew. The `alone`
  column is the one that survives a corpus change, because it is a property of a
  file rather than of a total, and it barely moved: `unittest` 7, `builtins` 2,
  `random` 2, `datetime` 2.
* **Four rows are here that this table did not have**, all of them small and all
  of them from the corpus growing: `importlib.util` (10 reach / 1 alone,
  `test_arm64_encoders.py`), `pwd` (1 / 1, `test_formal_os.py`), `token` and
  `html.parser` (1 / 0 each). `pwd` and `tokenize` print as **`unclassified`** in
  the tool's `tier` column, which is §"the next step" of
  `FORMAL_stdlib_module_names_are_not_classified.md` arriving as a real row with
  a real file behind it: `pwd` is the password database, so it is
  `HOST_UNREACHABLE` by the rule this tree states, and `tokenize` is the one that
  §6 below left for a duplicate-table argument.

**And the re-measurement §6 asked for, on `unittest`, which it said was the
largest honestly-modellable-looking row: it is not one.** A spelling census over
all **18** files that reach it, on this tree:

| the spelling | files | what it is |
|---|---:|---|
| `unittest.TestCase` | **18 of 18** | a base class with ~15 assertion METHODS and no fields — inheritance across a dylib boundary, and the field half of that is fixed (`5cf72641`) |
| `unittest.main()` | **17 of 18** | enumerate every `test*` method of a class and call it: a run-time type walk |
| `unittest.SkipTest` | 4 | an exception the runner catches |
| `unittest.skipUnless` | 2 | a decorator whose predicate is evaluated at class-construction time |
| `unittest.mock` | 1 | a recorded object |

**The 7 `alone` files spell `TestCase` and `main` and nothing else** — named:
`test_formal_declared_param_census.py`, `test_formal_frame_field_census.py`,
`test_formal_frame_slot_subscript_census.py`, `test_formal_proof_breadth.py`,
`test_formal_returnless_census.py`, `test_formal_sweep.py`,
`test_llm/test_llm.py`. So the row this doc called "the largest
honestly-modellable-looking row" is **17 files wanting the interpreter's own
namespace walk** — `abc`'s missing capability and `builtins`' — and only 4 files
wanting anything past `TestCase` + `main`. That is not a module somebody can
write; it is `abc` (165 reach, 0 alone) wearing a different name, and the
"inheritance plus method dispatch" cause this table named was the wrong one for
the same reason the field bug was: it was the first thing that looked like a
blocker, and it was fixed, and the row did not move.

## 1. How the ranking was measured, and the correction it forced

Two instruments, and the first one was wrong in a way worth writing down.

**The sweep log is the ground truth for "what was this file blocked on".**
`bugs/sweeps/sweep-arm-11.txt` prints one `NOT-ANSWERABLE/HOST-IMPORT: <path>`
line per file with the chain that refused it, so ranking by the terminal host
module in that chain is a reading of the log and needs no tool. That is the
`sweep-terminal` column of §3.

**A file's own import closure is the ground truth for "what is still in its
way", and it has to be walked with the BACKEND'S readers** —
`formal.build.parse_module` + `formal.imports.imported_modules` +
`formal.imports.resolve_module_path`. Not Python's `ast`:

* `imported_modules` takes `fire_compiler`'s node classes, so handing it an
  `ast.parse(...).body` returns **nothing at all** and every row reads 0. The
  first version of the walk did that and its whole table was empty;
* it filters `FRONTEND_PROVIDED_MODULES`, so `dataclasses` — a front-end
  transform (`formal/dataclass_transform.py`), not a host module — is not a
  wall. Reading `ast` puts it on 176 files;
* it deliberately does **not** descend into `if` or `try` bodies, and that
  exclusion is the finding below.

**`traceback` was never a row.** An `ast`-based closure walk called it **38
files** and **26** of them "the only wall"; the backend's own walk says **0 and
0**. The 38 came from `import traceback` inside `if`/`try` blocks, which
`imported_modules` does not descend into because they are conditional and a
conditional import is not on the link line. No file in the corpus was blocked on
`traceback`. The module is still worth having — 30 bare
`traceback.print_exc()` call sites in this repository now resolve, and it is a
real capability this target did not have — but it moved **no sweep row**, and
the commit that landed it says so rather than claiming the 26.

## 2. What this wave moved, measured on the same tree both ways

`.tmp/before.py` (scratch, not committed — §5) run twice on the **same** tree,
the second time pretending the three new modules are absent, so the delta is not
a difference between two checkouts:

| | before | after |
|---|---|---|
| files with NO unmodelled host module left | **26** | **24** |
| `signal` | 32 reach, **3 alone** | **gone from the table** |
| `operator` | 10 reach, 0 alone | **gone from the table** |
| `traceback` | 0 reach | **0 reach** |
| `unittest` | 17 reach, 6 alone | 17 reach, **7 alone** |

Three files left the wall entirely, named: `test_memslot.py`, `tools/memcap.py`
and `tools/procrun.py` — each wanted `signal` and nothing else unmodelled.

**And one file appeared**, which is the effect
`bugs/FORMAL_eleven_of_thirteen_host_import_rows_are_closure.md` is about and
which is worth one sentence because it is the reason the table cannot be read as
"what is left, ranked": `test_formal_sweep.py` imports **both** `signal`
(line 22) and `unittest` (line 27), so it was never `signal`-alone and is now
`unittest`-alone. A module landing **unmasks the row behind it**, and the
unmasked row is larger than the one that was measured.

## 3. The 20 names that are left, and what each one needs

`reach` = files whose closure names it. `alone` = files for which it is the
**only** name in that set, i.e. the files "writing this module makes this file
build" is a true statement about — the `alone` column of
`bugs/FORMAL_eleven_of_thirteen_host_import_rows_are_closure.md`, which this
table is the same measurement of four waves later.
`sweep` = files the 2026-10-04 sweep reported **on this name specifically**.

**The three numeric columns are RE-MEASURED (2026-10-05, `work/formal27-6`) by
`tools/formal_host_import_wall.py`, which is §5's promotion, so they are a
reading rather than a re-derivation. `reach` is over the tool's own corpus — the
735 files the sweep walks, this repository and the stdlib — where this table's
were over the 203 host-import files, so a bigger `reach` is a bigger corpus and
not a bigger wall; `alone` and `sweep` are the two that are corpus-independent
and both are within ±1 of what this table said, except where §0 says otherwise.**

| name | reach | alone | sweep | what it needs, and who has it |
|---|---:|---:|---:|---|
| `importlib` | 236 | 0 | 90 | **a host process.** `importlib.metadata` reads a distribution's metadata by running that distribution; `import_module` executes a module. The 90 is almost all closure — the swept files spell `importlib.metadata` **once** and `importlib.import_module` **once** between them, and reach it through `fire_compiler.py`. |
| `copy` | 237 | 1 | 13 | **a cloneable value.** `copy`/`deepcopy` of a container, which is a blob in the frame that built it. Owned and documented: `bugs/FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md` (`formal8-1`). |
| `abc` | 236 | 0 | 0 | **an interpreter.** `abc` is a metaclass and a registry; nothing here builds a type at run time. |
| `collections` | 129 | 10 | 29 | **CLAIMED** — `hostmods-platform`, `module:platform+fnmatch+collections-rest`. Not touched here. |
| `types` | 83 | 0 | 6 | **a namespace object.** `SimpleNamespace` (20 spellings) and `ModuleType` (3) are both run-time-constructed records, same missing thing as `copy` above. |
| `resource` | 34 | 0 | 0 | `getrlimit` answers a **pair**, and `setrlimit` wants a pair to hand back — `bugs/FORMAL_time_struct_shaped_answers.md`'s shape. The `RLIMIT_*` constants alone would be a module with no consumer. |
| `itertools` | 21 | 1 | 14 | **a lazy sequence.** `combinations` (the only name the swept files spell) is a generator of tuples; neither half is representable. |
| `unittest` | 18 | 7 | 16 | **RE-MEASURED in §0, and this row's cause was the wrong one.** `TestCase` in 18 of 18 and `main()` in 17 of 18; the 7 `alone` files spell those two and nothing else. `main()` is a run-time type walk, so this is `abc`'s capability, not a module. |
| `builtins` | 18 | 2 | 2 | **the interpreter's own namespace.** `set(dir(builtins))` — measured in `formal/imports.py`'s own comment, which is why `builtins` is a `HOST_UNREACHABLE` entry. |
| `inspect` | 8 | 0 | 4 | **the source text.** `getsource` reads a file and returns its text; `signature` reads a frame's code object. `HOST_UNREACHABLE`'s own comment says the subset that reads attributes off live values is reachable and the frame-walking half is not. |
| `random` | 8 | 2 | 5 | **module state.** `Random`/`seed`/`randrange`: a generator's whole meaning is that successive calls differ, and a value here is one word with no storage between calls. `HOST_MODELLED`, correctly. |
| `datetime` | 4 | 2 | 2 | **a `struct tm`.** Every swept file spells `datetime.now().isoformat()` — a returned struct with a method chain on it. `formal/hostmods/time.mojo` already says why its own `localtime`/`strftime` are absent. |
| `socket` | 2 | 1 | 2 | **a host object.** `socketpair()` returns a pair of descriptors that are also objects; `socket()` is one. |
| `tokenize` / `token` | 3 | 1 | 3 | **a generator of named tuples.** `generate_tokens` yields `(type, string, start, end, line)`. The **constants** are answerable (`COMMENT`, `OP`, `FSTRING_START`, `FSTRING_END`, `TSTRING_START`, `TSTRING_END`) and `formal/hostmods/ast.mojo` already numbers them internally — but shipping them as a second table would be the duplicate `CLAUDE.md` warns about, and the two files that want them also want `generate_tokens`, so the constants alone move **0** files. |
| `atexit` | 2 | 0 | 1 | **a callback.** `register(f)` stores a callable to run at exit. |
| `uuid` | 2 | 0 | 1 | `uuid4()` is 122 bits of randomness with no state to draw from. `HOST_UNREACHABLE`, correctly. |
| `asyncio` | 1 | 0 | 1 | **an event loop and a thread.** `run`/`sleep`/`gather`. |
| `functools` | 1 | 1 | 1 | **CLAIMED** — `formal25-3`, `bug:FORMAL_functools_is_unbuildable_as_a_host_module`. Not touched here. |
| `importlib.util` | 10 | 1 | 4 | `spec_from_file_location`/`find_spec` are the same host-process capability as `importlib` above, under a name the corpus grew into since this table was written; `test_arm64_encoders.py` is the one file it is alone for.
| `pwd` | 1 | 1 | 0 | **the password database.** `test_formal_os.py` is alone for it. It is `HOST_UNREACHABLE` by the rule this tree states — the file is not something a freestanding image has — and it is in NO tier today, so the tool prints it as `unclassified`.
| `tokenize` / `token` again, separately | 2 / 1 | 1 / 0 | 2 / 0 | §"What is cheap and NOT in the table" below, which says why the constants alone move 0 files; `token`'s own row is its `INFO`/`ENDMARKER` vocabulary and nothing reaches it alone.
| `html.parser` | 1 | 0 | 0 | a parsed file, like `plistlib`.
| `plistlib`, `sqlite3`, `fractions` | 1 each | 0 | 1 / 1 / 0 | a parsed file, a database handle, a rational — all run-time-constructed records. The two `1`s are the no-tier wording §0 is about: the b11 log reported them on that sentence and this table's reader did not see it. |

**Six capabilities, twenty names.** A run-time-length container that outlives the
frame that made it (`collections`, `copy`, `types`, `itertools`, `fractions`,
`plistlib`, `sqlite3`); a host process (`importlib`, `sqlite3`, `unittest.mock`);
an interpreter's own namespace (`builtins`, `abc`, `inspect`); module state
(`random`, `tokenize`); a first-class callable (`atexit`, `functools`,
`itertools`' helpers); and inheritance plus method dispatch (`unittest`). Every
one of the six is a **project**, not a module, and each already has a doc or a
claim — which is why this wave modelled three modules and stopped rather than
modelling a fourth that would have been a fourth copy of the same refusal.

## 4. What is cheap and NOT in the table

Two things this wave found that are not walls and are worth having:

* **`signal`'s constants cross a dylib boundary as module-level LITERALS.**
  `formal/build.py::_publish_imported_constants` folds a linked module's
  published constants into the importer's use site, so `signal.SIGTERM` reads as
  the number `15` with no call and no symbol. All nine files that want this
  module spell it that way and would otherwise all have to be edited.
  `formal/hostmods/ast.mojo` says the opposite about its own literals — that they
  "are NOT importable from it" — and that is still true of a module that declares
  **no public function**, because a dylib of nothing but constants cannot be
  linked at all (`bugs/FORMAL_a_module_that_exports_nothing_cannot_be_a_dylib.md`).
  So the vocabulary and the two functions are not two features; the second is
  what makes the first linkable.
* **A module-level literal constant is the cheapest capability in this tree and
  nothing in the sweep's instruments can see it.** `tools/formal_sweep.py`
  classifies a file by the refusal it prints, and a file whose only remaining
  wall is a constant vocabulary prints nothing at all.

## 5. Reproducing this — it is a TOOL now, and it keeps the one thing scratch had

```console
$ python3 tools/formal_host_import_wall.py                       # the table above
$ python3 tools/formal_host_import_wall.py --json                # machine-readable
$ python3 tools/formal_host_import_wall.py --unmodelled glob     # "before this module landed"
$ python3 test_formal_host_import_wall.py                        # 17 rows, 0.7 s
```

`tools/formal_host_import_wall.py` is the walk, promoted, and it reads with the
BACKEND's readers for the reason §1 gives — `formal.build.parse_module`,
`formal.imports.imported_modules`, `formal.imports.resolve_module_path` — and
with `formal.imports.host_module_tier` / `is_cpython_stdlib` / `INERT_MODULES` /
`is_frontend_provided` to decide what a WALL is. It reuses `tools/formal_sweep.py`
for the corpus (`find_source_files`, `default_roots`), for the class prefix and
for `_split_chain`, rather than owning a second copy of any of them.

**The ability §5 used to ask for is the tool's `--unmodelled`, and it is the
reason a delta is measurable on ONE tree**: a module landing unmasks the row
behind it and never grows one, so a before/after across two checkouts measures
the merge. `test_formal_host_import_wall.py` pins it on a real file —
`tools/suite.py` imports `glob`, `formal/hostmods/glob.mojo` answers it, so
`tools/suite.py` has no wall today and exactly one (`glob`) with the flag.

Three things the promotion changed about the measurement, each of them a
correction rather than a refactor:

* **the `sweep` column lost a blind spot** (§0): both wordings of
  `unresolvable_import_error`'s host-module arm are matched, and the header
  prints how many of the log's host-import lines were attributed at all
  (`203 of 203`);
* **"the backend cannot read this file" stopped meaning "this file imports
  nothing"**: one file in the corpus is unreadable — `test_formal_libc_symbol.py`,
  whose own source this tokenizer refuses, because an f-string replacement field
  with a newline in it is PEP 701 and `fire_compiler.py`'s tokenizer predates it.
  The tool prints that count rather than folding it into the corpus;
* **a name CPython ships that no tier classifies is a row with its own label**
  (`unclassified`) rather than a row the table left out, which is what put `pwd`
  and `tokenize` on it.

§3's spelling census is a regular expression count of `module.name` and
`from module import name` over each row's own files; §0's `unittest` census is
the same count over the 18 files the tool says reach it.

## 6. Not done, and why

* **`token`/`tokenize`'s constants** are answerable and were left, because
  `ast.mojo` already holds the numbers and a second table would be a duplicate,
  and because the two files that want them also want `generate_tokens`, which
  moves 0 either way. It is the one piece of §3 this wave could have written and
  chose not to. **STILL TRUE, and now measured rather than argued:** the tool
  says `tokenize` reaches 2 files with 1 `alone` and `token` reaches 1 with 0
  `alone`, so the constants still move 0 files and the duplicate table would
  still be a duplicate.
* **`unittest`** — **the re-measurement is DONE (§0) and the answer is that this
  row is not modellable at all**: 17 of its 18 files spell `unittest.main()`,
  which is a run-time type walk, so the row is `abc`'s and `builtins`'
  capability under a second name. Nothing further to pick up here, and the
  "inheritance plus method dispatch" cause this doc carried is withdrawn.
* **The walk** — DONE. §5's promotion note is now a tool, a test and a usage
  line, and this document no longer describes a walk.

## What is left that is genuinely next, and it is not a module

The six capabilities in §3's closing paragraph are the whole remaining queue, and
after §0's re-measurement one of them has lost its own row and folded into
another:

1. **a run-time-length container that outlives the frame that made it** —
   `collections` (129 reach / 10 alone, and CLAIMED by `hostmods-platform`),
   `copy`, `types`, `itertools`. This is the largest *honest* row left and the
   one `FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md` (`formal8-1`)
   owns.
2. **an interpreter's own namespace** — `abc` (236 reach), `builtins` (18 / 2),
   `inspect` (8), and now `unittest`'s 17. The biggest row by `reach` and
   **0 files** by `alone` before `unittest`, which is the shape that says "no
   module will ever move these".
3. module state (`random`, 8 / 2); a host process (`importlib`, 236 / 0);
   a first-class callable (`atexit`, `functools`, `itertools`' helpers); a
   `struct tm` (`datetime`, 4 / 2).
