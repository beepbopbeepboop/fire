# FORMAL_a_call_result_field_access_has_no_representation: every remaining host-import row is one capability, and it is not a module

**Area:** FORMAL (the value model — `formal/model.py`'s lowering of a field
through a value whose binding the image cannot see, `formal/build.py`'s export
rule, and `formal/imports.py`'s host-module tiers as the queue's input).
**Status: the ranking is DONE and it says the task's "next 4-6 modules by files
blocked" does not exist; three rows are CLOSED (17 sweep files); the capability
this file is about is NOT built and §5 says what building it takes.**

Written on `work/formal36-hostmods-wave5`, 2026-10-05, asked to rank the
remaining host-import files from `bugs/sweeps/sweep-arm-13.txt` and model the
next 4-6 of them. The ranking is the deliverable and it is negative; §4 is the
arithmetic and §5 is the next step.

## 0. What is here, in one table

`python3 tools/formal_host_import_shapes.py`, over
`bugs/sweeps/sweep-arm-13.txt` (220 host-import lines, 22 modules, every line
attributed). `files` is the sweep's count, `live` is how many of those files
**still spell the module in this tree**, `needs` is the shape of the use, and
the shapes are defined in the tool's docstring and pinned by
`test_formal_host_import_shapes.py` (`WORD` `FIELD` `SUBSCRIPT` `CONCAT`
`FSTRING` `BARE` `DECORATOR` `MODULE` `STAR` `DEAD`):

| module | tier | files | live | needs | what the files spell |
|---|---|---:|---:|---|---|
| `importlib` | unreachable | 94 | 5 | `WORD` | `import_module` |
| `collections` | modelled | 39 | 19 | `BARE` `FIELD` `WORD` `DEAD` | `Counter`, `defaultdict`, `OrderedDict`, `namedtuple` |
| `unittest` | unreachable | 18 | 18 | `BARE` `DECORATOR` `FIELD` `WORD` | `TestCase`, `main`, `SkipTest`, `skipUnless` |
| `itertools` | modelled | 14 | **0** | — | **CLOSED** |
| `copy` | modelled | 13 | 4 | `WORD` | `copy.copy`, `copy.deepcopy` |
| `random` | unclassified, model written | 8 | 8 | `WORD` | `Random`, `randrange`, `seed` |
| `types` | modelled | 6 | 5 | `BARE` `MODULE` `WORD` | `ModuleType`, `SimpleNamespace` |
| `importlib.util` | unreachable | 5 | 5 | `FIELD` `WORD` | `spec_from_file_location`, `module_from_spec` — load a module BY PATH |
| `inspect` | modelled | 5 | 5 | `FIELD` `WORD` | `getsource`, `getsourcelines`, `signature` |
| `builtins` | unreachable | 3 | 3 | `MODULE` | `dir(builtins)` — the module AS A VALUE |
| `datetime` | modelled | 2 | **0** | — | **CLOSED** |
| `socket` | unreachable | 2 | 2 | `BARE` `WORD` | `socket`, `socketpair`, `AF_UNIX` |
| `tokenize` | **unclassified** | 2 | 2 | `BARE` `WORD` | 7 kind codes, `TokenError`, `generate_tokens` |
| `asyncio`, `atexit`, `functools`, `plistlib`, `pwd`, `resource`, `sqlite3`, `unittest.mock`, `uuid` | mixed | 1 each | 0-1 | see the tool | one name each |
| `abc` `importlib` `types` `resource` `inspect` `pickle` `html.parser` `multiprocessing` `token` | — | closure only | 0 `alone` | — | nothing reachable |

Two shapes in that table are the ones the older ranking cannot express at all.
**`MODULE` is the module OBJECT used as a value** — `dir(builtins)` — and it is
its own refusal ("a module is not a value this path can place: there is no
register, frame slot or `__DATA` word for it"), not a dead import and not a
word. **`BARE` is a module-level name with no call on its chain**, which is a
fact about the CALLER rather than about the module, because a constant in a host
module is a zero-argument function for exactly this reason
(`formal/hostmods/os/__init__.mojo`; `test_formal_stat.py::group_absent` says the
same about why its refusals are calls).

`tokenize`'s seven kind codes are `BARE` — a module-level name with no call on
its chain — which is a fact about the CALLER, not about the module: a constant
in a host module is a zero-argument function for exactly this reason
(`formal/hostmods/os/__init__.mojo`, and `test_formal_stat.py::group_absent`
says the same thing about why its refusals are calls). So even the one row whose
names are all plain integers would move its caller rather than its module.

## 1. Why the existing ranking could not answer this, and what it took

`tools/formal_sweep_causes.py --host` ranks the same rows and adds a `uses:`
column. Two limits, both measured:

* **For a module with no `.py` source in this interpreter's stdlib the column
  is a LOWER BOUND and says so.** `itertools`, `builtins`, `resource` and `pwd`
  are frozen or builtin, so the tool cannot enumerate their declarations by
  parsing a source file and prints `>=2` / `>=3` / `>=1`. §0's `itertools` row
  has exactly **one** use in the whole repository and that number is not
  derivable from the tool. The count is answerable from the other end — the
  swept file's own AST says what it spells — and that is what
  `tools/formal_host_import_shapes.py` reads.
* **"the file names it" is not "a `.mojo` module can answer it".** A value on
  this path is one 64-bit word (`doc/ABI.md`), and a module dylib publishes
  functions. So the SHAPE of a use decides the question before the module's
  semantics do, and 17 of the 22 rows in §0 have at least one use that is not
  the shape a module can publish.

`tools/formal_host_import_shapes.py` is a NEW FILE rather than a column on that
tool, for the reason that tool and `tools/formal_host_import_wall.py` are both
edited by five live branches (`git branch --no-merged master`) and a wave that
adds a column to a contested file merges as a conflict. It imports that tool's
`_newest_sweep` rather than reimplementing the rule, because the naive version
is wrong in a way this would have shipped: a name sort over
`sweep-<arch>-<n>.txt` ends on `sweep-x86-9.txt`, round nine.

## 2. What a `.mojo` module cannot publish, measured on this tree

Four refusals, each produced by `python3 fire.py build --formal --no-prove` on a
two-line program, each quoted from what it printed:

    os.getenv("HOME").size
    → 'os.getenv(...).size' is a field access through 'os.getenv(...)', and
      this path has no way to say what 'os.getenv(...)' holds. A field is
      lowered three ways and which one applies is decided by the BINDING of
      the base, not by a type …

    os.sep
    → os.sep reads 'sep' out of the imported module `os`, and a module is not a
      value this path can place: there is no register, frame slot or `__DATA`
      word for it …

    platform.machine().upper()
    → the image would bind 1 symbol(s) that nothing provides … upper.
      (A green build and an unbound symbol: the worst of the two, and it is why
      a method call on a value receiver is refused BY NAME rather than lowered.)

    len(os.getenv("HOME"))
    → len() of bytes the KERNEL supplied … a `strlen` counts BYTES and CPython
      counts CHARACTERS … Refused rather than emitted.

The first three are the three shapes `FIELD`, `BARE` and a method call, and the
fourth is the general statement: **the answer has to be one word, and the thing
CPython answers with here is not.** A dict (`collections.Counter`) is a frame
blob; a `struct rusage` (`resource.getrusage`) is a frame blob; a `struct
passwd` (`pwd.getpwuid`) is a frame blob; a `datetime` is six fields
(`FORMAL_time_struct_shaped_answers.md`); a `UUID` is 128 bits plus a `.hex`
method (`uuid.uuid4().hex[:8]`); a plist is a dict
(`plistlib.load(f)["ProductVersion"]`).

## 3. What DID move, and it was not a module

Three rows closed with no `formal/hostmods/` file at all, because in each case
the use was either a dead import or a spelling the module could never have
answered:

| row | files | what it was | the fix |
|---|---:|---|---|
| `itertools` | 14 (19 of closure) | **two** import statements in the whole repository: `test_formal_dylib.py:434` `itertools.combinations(sorted(segs), 2)` and a function-local `import itertools as _it` in `test_module_cache.py` | two index loops, verified `==` to `itertools` including the order |
| `datetime` | 2 | `datetime.now().isoformat()` in two report headers | `time.time()`, which `fault_tolerance.py:254` has always used for a field with the same name |
| `copy` | 1 of 13 (`alone`) | `tools/apply_extraction.py` imported `copy` and read nothing through it | deleted the import |
| `collections` | 4 of 39, **2 of them `alone`** | four files imported it and read nothing through it: `consolidate_string_pool.py` (`from collections import OrderedDict`), `formal/admitted.py`, `tools/formal_chain_probe.py`, `tools/formal_field_walk_differential.py` | deleted the imports; `collections`'s `alone` count went **10 → 8** |

The `collections` half is the same shape of finding as the `copy` half and was
found by the same instrument: **`DEAD` is a column, not an absence.** Neither
`formal_sweep_causes.py` nor the wall tool prints it, because both ask whether a
file NAMES a module and a dead import does name one. Four of the row's 39 files
answered "yes" and meant nothing by it, and two of them were the row's
`alone` files — a file for which `collections` is the ONLY wall, so the delete
moves it rather than merely reclassifying it.

`test_formal_dylib.py` and `test_module_cache.py` were both on the row for
`itertools`, and `test_formal_dylib.py` is imported by a dozen other formal test
files, so **one line of one file held a fourteenth of the sweep's coverage
denominator outside it.** The equivalence is not a resemblance:
`itertools.combinations(seq, 2)` is defined over INDEX pairs of its input
(`seq[i]` with `j > i`) and `itertools.product(alpha, repeat=n)` yields with the
LAST position varying fastest, which is a nest with the last index innermost, so
both substitutions yield the same SEQUENCE. Both files now pin the property
their own replacement relies on — every unordered pair visited exactly once, and
820 corpus values with the level boundaries named — because a dependency removed
for a reason is a dependency that can come back unnoticed, the case it feeds
still runs either way.

## 4. The arithmetic: zero rows are left that a module can move

Twenty-two rows. Against them:

* **8 are a fact about the target**, correctly tiered `unreachable` and with the
  object named: `importlib` and `importlib.util` (an embedded CPython — the five
  files load a module BY PATH with `spec_from_file_location` +
  `module_from_spec`), `builtins` (the module as a VALUE: `dir(builtins)` asks
  the interpreter to enumerate its own namespace, which is the one question on
  that page with no answer here), `socket` (a socket), `unittest` and
  `unittest.mock` (process-wide reporting machinery), `asyncio` (a thread),
  `atexit` (a shutdown path).
* **1 is closure and written**: `random`, 8 files of which 5 spell
  `random.Random(seed)` — an object with 624 words of state behind a pointer.
* **5 need a type**: `collections.namedtuple`, `collections.Counter`,
  `types.SimpleNamespace`, `types.ModuleType`, `copy.deepcopy`. The capability
  and its owner are `bugs/FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md`.
* **4 need a live interpreter's frames or objects**: `inspect.getsource` /
  `signature` (a function object and its `co_firstlineno`), `sqlite3.connect`,
  `plistlib.load` (a stream object and a dict), `tokenize.generate_tokens` (a
  generator of 5-tuples, and a `TokenError` exception).
* **2 need a shaped record**: `resource.getrusage` and `datetime` — both filed
  at `FORMAL_time_struct_shaped_answers.md`.
* **2 are decorators and are refused on purpose**: `functools.lru_cache` on
  `version()`, and `unittest.skipUnless`. A decorator on a function OR a class is
  DROPPED, silently, by both backends
  (`bugs/COMPILE_FAIL_decorator_application_dropped.md`), so exporting the name
  would make the program build and enforce nothing. `version.py`'s is cited by
  name in `mojo/backend_gimple/device_select.py::_decorator_names`'s docstring as
  the worked example that function's `CallExpr` branch exists for, so removing
  the import would trade one file of this wall for a hole in a compiled-path
  test. **Left, deliberately.**
* **3 are UNCLASSIFIED** — `tokenize`, `pwd`, `plistlib`, `sqlite3` are in
  neither tier, so their refusal says "nothing here can say whether it is
  reachable". `bugs/FORMAL_stdlib_module_names_are_not_classified.md` is
  CLAIMED (`formal28-5`) and owns the classification; §0 gives the per-name
  readings by measurement rather than by editing that tier set.

**Nothing is left in the "write a `.mojo` module" column.** The task's "next
4-6 modules by files blocked" does not exist as stated, and this is the second
wave to measure that
(`bugs/FORMAL_the_host_import_rows_after_glob_ranked_by_what_they_actually_spell.md`
§2 said it and had no column to say it with; §0 is the column).

### 4.1 Nine of those files want CPython ON PURPOSE, and that is a third answer

Nine sweep files across four rows use their host module as an **oracle** rather
than as a capability — they are differential tests whose whole job is to compare
a compiled image against this process's CPython, so a program that builds without
CPython is a program that has stopped testing anything:

| file | the oracle |
|---|---|
| `test_formal_link_accounting.py`, `test_formal_monomorph.py`, `test_formal_receiver_position.py`, `test_formal_type_application.py`, `test_runtime_dylib.py` | `inspect.getsource(fn)` / `signature(fn)`, then `src.count(…)` — the source TEXT is the assertion |
| `test_ast_formal.py`, `test_no_new_container_casts.py` | `tokenize.generate_tokens(readline)`, the token stream CPython's tokenizer produces |
| `test_formal_time.py` | `fractions.Fraction` with the IEEE-754 rounding rule written out; the file's own docstring says asserting against `ns / 1e9` would fail a CORRECT module |
| `test_formal_os.py` | `pwd.getpwnam('root').pw_dir`, to build the expected value for `posixpath.expanduser("~name")` |

So these nine are not "a module to write" and not "a caller to re-spell": they
are programs that must keep importing CPython to be worth running, and the sweep
files them under `not-answerable/host-import` because it asks "can this file
become a formal image", which is the wrong question for a differential test.
**That is a property of the sweep's SCOPE, not a defect in the backend**, and
the fix is in the report rather than in a `.mojo` file: a file whose only use of
a host module is to be compared against it belongs in neither the numerator nor
the denominator of a codegen-coverage rate, for the same reason a test's
fixture does not count as untested code.

`tools/formal_host_import_shapes.py` does not have an oracle column and cannot
grow one honestly — "this use is the file's oracle" is not a syntactic fact, it
is a fact about why the file exists, and the four rows above were read by hand.
It is recorded here so the next reader does not re-derive it, and so that a
future wave measuring "how many files moved" does not count these nine as
outstanding.

## 5. The next step, and it is a value-model question

The 13 rows that are not facts about the target are all waiting on ONE thing,
and it is not a module: **a representation for a value that is more than one
64-bit word, reachable from a `WORD` the caller already has.** Every one of them
needs it in one of three forms, and they are separable:

1. **A field read through a call's result** — `os.stat(p).st_mode`,
   `resource.getrusage(w).ru_maxrss`, `pwd.getpwnam(n).pw_dir`,
   `uuid.uuid4().hex`, `datetime.now().isoformat()`. Measured: refused, by name,
   with the reason that the BINDING of the base decides the layout. The cheapest
   honest form is not a struct at all — it is the shape
   `formal/hostmods/os/_syscalls.mojo` already uses for `stat`, where the reader
   is `fs_stat_mode(p, follow)` and the caller re-spells. That moves `resource`,
   `pwd` and `datetime` with three caller edits and no backend change, and it is
   worth measuring before anything in `formal/model.py` is touched.
2. **A container behind a `WORD`** — `plistlib.load(f)[k]`,
   `collections.Counter`/`defaultdict`. `os.listdir` and `os.environ` already
   answer this with a `malloc`'d blob and a count/fill/accessor pair, so the
   capability exists; what does not is a spelling a caller can write without
   changing every use, and `formal/imports.py`'s own entry for `collections`
   declines the blob under the name `Counter` for three measured reasons.
3. **A type at run time** — `namedtuple`, `SimpleNamespace`, `ModuleType`,
   `deepcopy`, `Random(seed)`, `Signature`. Owned by
   `bugs/FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md`.

**1 is the cheapest and it is three files, so it is the first thing to try.** The
measurement that says so is §0's `FIELD` column: six rows carry one, and no row
in §0 carries a `FIELD` without also carrying a `WORD`, which is what "the call
lowers and the read does not" looks like from the outside.

**What this doc is NOT claiming.** It does not claim the remaining rows are
permanent facts about the target — most of them are not, and §4 says which are.
It claims they are not reachable by writing a `formal/hostmods/` module, which
is a much narrower claim and the one that decides what to work on next.