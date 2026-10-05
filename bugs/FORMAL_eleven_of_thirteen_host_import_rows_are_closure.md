# FORMAL_eleven_of_thirteen_host_import_rows_are_closure: what the host-import row looks like once `tempfile`, `textwrap`, `posixpath` and `html` have landed

**Measured 2026-10-03** while picking the next host modules from
`bugs/FORMAL_sweep_work_map_2026-10-02_b7.md`'s host-import row. Not a claim on
any of these modules — it is the measurement that says which of them is WORK and
which is a file waiting on something else, because the ranking that started this
(`tools/formal_sweep_causes.py --host`, whose 2026-10-03 write-up is deleted
with its queue) reads a sweep log from **2026-10-02**, and `formal/hostmods/tempfile.mojo` landed on **2026-10-03**.

That date is the whole content of this doc. The b7 log's `--host` table does not
list `textwrap` at all — not because the row is small but because in that run all
three files wanting it were still stopped by `tempfile`. A module landing UNMASKS
the row behind it, and the ranking cannot see that until a sweep is re-run. So
every number below is measured NOW, by walking each file's import closure with
`formal/imports.py`'s own `resolve_module_path`, which is the resolver the build
itself uses.

**RE-MEASURED LATER THE SAME DAY (2026-10-03, second pass) and the conclusion
holds: eleven of thirteen are still closure, and `glob` is still the only real
row. §"Re-measured" has today's numbers, an order-independent definition of
"terminal" (the original one was a property of the traversal order), the FILES
each row is the only blocker for, and one new fact about `shlex`.**

## Re-measured 2026-10-03, second pass

Same walk, same corpus (350 `.py`/`.mojo` files in this tree, excluding
`bugs/`, `formal/` and the build directories), with two changes to the
measurement rather than to the conclusion:

* **`terminal` is now "this module is the ONLY thing standing between the file
  and a build"**, i.e. the file's set of unresolvable modules is exactly `{m}`.
  The original column was the FIRST unresolvable module of a depth-first walk,
  which makes the number a property of the traversal order: `fire_compiler.py`
  leaves five modules unresolved and which one is "first" is an artefact. The
  new definition is what "writing this module makes this file build" means, and
  it reproduces the original column closely enough (below) to show the original
  was measuring the same thing by accident.
* **A `shared` column**, the files where `m` is unresolvable *and something else
  is too*. That is the doc's own point as a number: `abc` is unresolvable in 200
  files and is the only blocker in **none** of them.

| alone | shared | closure | module | the doc's `terminal`, for comparison |
|---:|---:|---:|---|---|
| **7** | 205 | 212 | `glob` | 7 |
| 5 | 82 | 87 | `collections` | 4 |
| 2 | 2 | 4 | `random` | 1 |
| 2 | 1 | 3 | `datetime` | 2 |
| 1 | 200 | 201 | `copy` | 1 |
| 1 | 24 | 25 | `resource` | 1 |
| 1 | 17 | 18 | `itertools` | 1 |
| 1 | 0 | 1 | `functools` | 1 |
| 0 | 200 | 200 | `abc` | 0 |
| 0 | 68 | 68 | `types` | 0 |
| 0 | 14 | 14 | `operator` | 0 |
| 0 | 5 | 5 | `inspect` | 0 |
| 0 | 3 | 3 | `shlex` | 0 |

**Eleven of thirteen are still closure, and `glob` is still the only row with a
double-digit `alone` count.** The drift since the first pass is small and in the
direction the first pass predicted (a module landing unmasks the row behind it):
`collections` 4 → 5, `random` 1 → 2.

### The files each row is the ONLY blocker for

This is the actionable half the first pass did not have, and it is worth more
than the counts: it says which file a module would move, so a module worth one
file can be compared with a module worth seven on the same scale.

| module | alone for |
|---|---|
| `glob` (7) | `bootstrap-validate.mojo`, `cas.py`, `fault_tolerance.py`, `py314_cache.py`, `test_relaxed_imports.mojo`, `tools/audit_selfhost_ast.py`, `tools/fix_genexpr_anyall.py` |
| `collections` (5) | `consolidate_string_pool.py`, `tools/analyze_stdlib_errors.py`, `tools/arm64_insn_audit.py`, `tools/formal_chain_probe.py`, `tools/heapprof_report.py` |
| `random` (2) | `test_formal_hashlib.py`, `tools/formal_fuzz.py` |
| `datetime` (2) | `run_stdlib_tests.py`, `scripts/bootstrap_full_test.py` |
| `copy` (1) | `tools/apply_extraction.py` |
| `resource` (1) | `test_selfhost_memory.py` |
| `itertools` (1) | `test_formal_run.py` |
| `functools` (1) | `version.py` |

**Four of `glob`'s seven are not the files the b7 log listed**, which is the same
date problem this doc is about: `checked_run.py`, `test_no_new_container_casts.py`
and `tools/suite.py` were in the sweep's row and are not in this one, and
`cas.py`, `fault_tolerance.py` and `py314_cache.py` are in this one and were not
in it. The row MOVES as the tree moves, which is why §below measures rather than
ranks.

### `shlex` is still not alone anywhere, and there is a second thing in the way

All three files that want it, with their whole unresolvable set:

```
test_suite.py        -> abc, copy, glob, importlib, importlib.util, memslot,
                        shlex, signal, suite, types, zlib
tools/ab_run_one.py  -> glob, shlex, signal
tools/suite.py       -> glob, shlex, signal
```

So §next-step item 2 below ("blocked behind `glob`") holds and **understates it**:
`signal` is in all three, and `signal` is not a module anyone has sized — it is
libSystem's signal handling, which is a capability question of its own rather
than a row in this list. (`memslot`, `suite` and `importlib.util` in the first
line are REPOSITORY siblings that this static walk cannot resolve and a real run
resolves through `sys.path`; they are artefacts of the walk, and the doc's method
has always had them.)

**So `shlex` is a three-deep sequencing answer, not a two-deep one**, and writing
it moves nothing on its own even after `glob` lands.

## The measurement, and how to reproduce it

Two numbers per module, because they answer different questions:

  * **terminal** — `m` is the FIRST unresolvable module in the file's eager
    import walk. This is what `tools/formal_sweep.py` prints and what the b7 log
    ranked. It is the number that says "writing this module makes this file get
    further".
  * **closure** — `m` appears SOMEWHERE in the file's import closure. It is the
    CEILING on what modelling `m` could ever move, because a file can only build
    once its whole closure resolves.

    `abc` is why the distinction is not pedantry: it is in the closure of **204**
    files and is TERMINAL for **none** of them.

    ```python
    # per file, the walk the build itself does
    seen, stack, out = set(), [path], set()
    while stack:
        p = stack.pop()
        if os.path.realpath(p) in seen: continue
        seen.add(os.path.realpath(p))
        for m in I.imported_modules(I.module_statements(p)):
            d = I.resolve_module_path(m, relative_to=p, project_root=REPO)
            (out.add(m) if d is None else stack.append(d))
    ```

    This is NOT a sweep and it needs no `formal_sweep.py` run: it is the same
    walk, statically, and it is the `.tmp`-free version of what §4 of the
    2026-10-03 host-import ranking did by hand.

## The rows, ranked by terminal files

| terminal | closure | module | what it actually is |
|---:|---:|---|---|
| **7** | 217 | `glob` | WORK, and the largest reachable row left. See §3 — **this doc does not claim it** |
| 4 | 93 | `collections` | NOT WORK: owned, and the answer is a message not a module |
| 2 | 3 | `datetime` | NOT WORK: the answer is a `struct`, and there is a doc for it |
| 1 | 205 | `copy` | NOT WORK: the same doc, and the same missing thing |
| 1 | 26 | `resource` | NOT WORK: `getrusage(2)` is libSystem but its ANSWER is `struct rusage` |
| 1 | 16 | `itertools` | NOT WORK: the one name this corpus uses answers a SEQUENCE |
| 1 | 3 | `random` | NOT WORK: the state is 624 words |
| 1 | 1 | `functools` | NOT WORK: every name is a decorator or a function value |
| 0 | 66 | `types` | NOT WORK: the one name is a TYPE FACTORY |
| 0 | 13 | `operator` | NOT WORK: every name is a FUNCTION VALUE |
| 0 | 204 | `abc` | NOT WORK: zero files, and the reason is in §2 |
| 0 | 4 | `inspect` | NOT WORK: reads source off a live interpreter |
| 0 | 3 | `shlex` | NOT WORK **yet** — reachable, but the one file that wants it stops on `glob` first |

**Eleven of the thirteen are closure, not work, and that is the finding.** The
ranked doc reached the same conclusion for six of them from a different direction
(§2 of that doc: "the honest next step is not 'write the module' — it is 'find the
module that really stops those files'"); this measures the whole row rather than
six names in it.

## §2 The three 0-terminal rows, measured name by name

Each of these has a specific reason it is not a module, and each is checkable in
one grep — which is the level at which "not reachable" should be argued, because
"not reachable" is a claim about a capability and these are claims about SPELLINGS.

  * **`types`, 0 terminal / 66 closure.** Every `types.X` in this repository that
    is the standard library is `types.ModuleType` (x10). The other ~200 `types.*`
    hits are `formal/types.py`'s own members reached through a local named
    `types` — `types.IdentExpr`, `types._safe_name`, and so on — and
    `formal/types.py` resolves as a REPOSITORY SIBLING, one pass further down
    `resolve_module_path`. So the stdlib `types` is reachable for exactly one
    reason and it is the wrong one: `ModuleType(name)` is a **TYPE FACTORY**,
    and a type is not a value on this path (`formal/model.py`;
    `bugs/FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md` is the
    measurement, and it owns this name too). The 66 are behind
    `fire_compiler.py`, which is behind `importlib`.
  * **`operator`, 0 terminal / 13 closure.** Every use is a **FUNCTION VALUE**
    passed as an argument, and all of them are in `myinterpreter.py`:

        def __add__(self, other): return self._binary(other, operator.add)

    `operator.add` is a first-class function object, and one cannot cross a dylib
    boundary here for the same reason `functools.lru_cache` cannot
    (`bugs/FORMAL_functools_is_unbuildable_as_a_host_module.md`). `myinterpreter.py`
    already documents the substitution it made — `operator.index` has a
    hand-written stand-in at its line 2076, and the file says why.
  * **`abc`, 0 terminal / 204 closure, and this is the interesting one.** The
    import is in `fire_compiler.py` and the imported NAME IS NEVER USED AS A
    VALUE:

        from abc import abstractmethod          # line 62
        ...
        body.append(f"{pad}    @abstractmethod")   # line 7592 — a STRING

    So `abc` is the `typing` shape exactly: the import resolves as soon as the
    module EXISTS, `abstractmethod` need not be in any export table, and nothing
    ever reads the name (`formal/hostmods/typing.mojo`'s docstring measures that
    for `Optional`). A module would therefore buy **zero files**, because
    `fire_compiler.py` — the only file that imports `abc` — is blocked by five
    modules at once, measured:

        fire_compiler.py unresolved: ['abc', 'copy', 'glob', 'importlib', 'zlib']

    and four of the five are owned elsewhere. **The 204 is a closure number and
    it is a trap**: it is the second-largest in the table and it is worth exactly
    nothing, which is the argument for having a `terminal` column at all.

## §3 `glob` is the only real row left, and this doc does not claim it

**7 terminal / 217 closure**, and it is the largest thing in the reachable part
of the host-import row. The 2026-10-03 host-import ranking records it as
**OWNED — `formal10-3`**, holding
`FORMAL_glob_copy_collections_io_not_attempted.md`. That document is NOT in this
tree and `formal/hostmods/glob.mojo` does not exist, and `formal10-3` is not in
`tools/control.py claims` on 2026-10-03 — so the claim is ambiguous: either that
work did not land or it landed and its doc was deleted with it (which is the rule
for a FIXED bug).

**So it is reported here and not taken**, because §5 of that same doc is right
that it is a project rather than a patch and the person who picks it up needs to
know the shape before starting:

  * `glob.glob(pattern)` answers a **run-time-length LIST**, which is the
    `bugs/FORMAL_listdir_no_run_time_sequence.md` limit. `os.listdir` answers
    because it may `malloc` a blob; `glob.glob` would have to as well, and the
    callers iterate it, so the blob has to be ITERABLE, which no blob here is.
    That is the whole difficulty and it is a real one.
  * `fnmatch`'s matcher is `formal/hostmods/fnmatch.mojo`'s `match_core` and
    `pathlib.mojo` already calls it across a dylib boundary, so the PATTERN half
    is done and is one import.
  * The `**` recursive form needs a directory walk whose DEPTH is not known at
    build time — `os.walk` answers with a blob plus `walk_free`, so the shape
    exists, but the recursion over it does not.
  * `importlib.util.spec_from_file_location` (1 file) and `importlib`
    (48 files) are unreachable and are NOT this row's problem; 47 of the 48 are
    closure behind `fire_compiler.py`.

## §4 What landed today, and what it moved

Three modules and the files each one unblocked, all measured by building the file
with the sweep's own argv:

| module | what it is | files that moved off it, and onto what |
|---|---|---|
| `textwrap` | `dedent`, `indent` | `test_runtime_diff.py` → `subprocess.TimeoutExpired` handler arm; `test_interp_oracle.py` → the same; `test_comptime_parity.py` → `sys.executable` |
| `posixpath` | 30 forwards to `os.path` | `test_formal_os.py` → `Exception as e` handler arm |
| `html` | `escape` | `tools/md2html.py` → `OSError` handler arm |

Plus `os.path.realpath`'s own divergence, found on the way and filed as
`FORMAL_os_path_realpath_keeps_a_double_slash_root`.

Every one of them moved onto a refusal about the FILE'S OWN SOURCE, which is the
whole value of a module in that directory: the verdict does not change, the
SUBJECT of the refusal does, and a subject about the file is one a person can act
on where a subject about a module is not.

## The next step, in the order the ranking gives

(Re-measured 2026-10-03; item 1's blocker is now FIXED and item 2's is deeper
than this list said. Everything else stands.)

1. **`glob` — 7 files, and the only real row.** §3 says why it is not taken
   here; whoever takes it needs §3's four bullets and the two ownership
   questions answered first. **Both ownership questions are answered**: no
   claim in `tools/control.py claims` names `glob`, and
   `formal/hostmods/glob.mojo` is still not in this tree (it lives uncommitted on
   `work/formal8-7-r2`'s working tree). **And the blocker is GONE — fixed at the
   root 2026-10-03**, in `model.subscript_base_lowering`, the one decision both
   emitters read: a subscript through an unannotated parameter now takes the
   convention its CALL SITES use on that argument, so one value has one
   convention wherever the name is written, and call sites that disagree are
   refused by name rather than silently mismatched. Measured inert on this corpus
   (3 713 unannotated-parameter subscripts over 459 `.mojo` files, none of them
   changes answer) and pinned by `test_formal_run.py`'s
   `both_arch_an_untyped_parameter_indexes_the_same_pointer_as_an_annotated_one`
   and `test_formal_cross_module.py`'s
   `a_container_returning_export_whose_helpers_take_the_buffer` — which is
   `glob`'s own shape in miniature, a `-> List[Int]` export whose private helper
   takes the buffer it is handed through an untyped parameter. So **`glob`'s next
   step is no longer "wait for `subscript_base_lowering`, then annotate the blob
   parameters"**: the annotation is no longer what chooses, so those parameters do
   not need it. What is left is §3's real difficulty, which nothing in that round
   touched — the run-time-length LIST, and a blob the CALLERS can iterate.
2. **`shlex` — reachable, and blocked behind `glob` AND `signal`.** `quote`,
   `split` and `join` are pure computation over bytes a value already is
   (`formal/imports.py` says so). The three files that want it stop on `glob`
   first — and on `signal` too, in all three (§Re-measured). So it is a
   **sequencing** answer, not a capability one, and it is THREE deep rather than
   two: write `glob` and `shlex` is still not the next wall, because `signal` is
   beside it in every file that wants it.
3. **`shlex` has an open QUESTION of its own**, and it is not a module:
   `FORMAL_link_accounting_shlex_entered_the_host_set_with_no_source`
   records that `shlex` was added to `HOST_MODULES` with no source, which fails
   `formal-link-accounting` in the everyday gate, and the doc asks which of two
   rules governs a sourceless standard-library name. Writing
   `formal/hostmods/shlex.mojo` takes the doc's option 1 (the `fcntl` route —
   `formal/hostmods/fcntl.mojo` is in the tree) and settles it — so **item 2 and
   item 3 are the same piece of work** and whoever takes it should read that doc
   first.
4. **`inspect`, `resource`, `datetime`, `collections`, `copy`, `random`,
   `functools`, `itertools`, `types`, `operator`, `abc` — all closure.** §2
   gives the name-level reason for each and §1 gives the row. None of them is
   next, and writing this down is the point: the ranking made eleven of them look
   like work and the measurement says otherwise. **The one caveat the second
   measurement adds** is that three of them are the ONLY blocker for a single
   file each — `itertools` for `test_formal_run.py`, `functools` for
   `version.py`, `copy` for `tools/apply_extraction.py` — so "worth 0 or 1" is a
   real number to weigh against a module's cost, and `itertools` is worth
   noticing: the corpus's own run suite is one `itertools` call away, and §2's
   reason for it ("the one name this corpus uses answers a SEQUENCE") has not
   changed.

## Status, 2026-10-05 (`formal31-3`): three of the rows have LANDED, the fourth
## (`itertools`) is closed by the corpus rather than by a module, and the table
## above is stale in a way that matters

The measurement this document is has moved. It is kept above rather than
rewritten because the table's numbers are what a reader has to check the new
ones against, and because the reasoning about which rows are WORK and which are
CLOSURE is the part that has held up across every re-run.

### The rows that closed, by other branches, and what each was

| module | the doc's row | what is in the tree now |
|---|---|---|
| `glob` | **7 terminal / 217 closure**, "WORK, and the largest reachable row left", §3 said it was not being taken here | `formal/hostmods/glob.mojo`, 816 lines, 24 functions; `test_formal_glob.py` 6/6. §3's four bullets were answered rather than skipped: `glob.glob` returns a run-time-length list as a **blob** (`_iglob` became a count/fill pair, because "a producer has to allocate where it can be SEEN to"), the `fnmatch` pattern half was already done and cost one import, and the `**` recursive form is `os.walk` plus a depth the caller passes |
| `shlex` | item 2: reachable, blocked behind `glob` AND `signal`; item 3: entered `HOST_MODULES` with no source, failing `formal-link-accounting` | `formal/hostmods/shlex.mojo` exists, so item 3 took the doc's own option 1 (the `fcntl` route) and both `signal` and `shlex` are modelled |
| `signal` | "not a module anyone has sized" — a capability question of its own | `formal/hostmods/signal.mojo` |

`glob` was the doc's only "real row" and it is gone, which means the honest
answer to "what is next" is no longer on this list at all.

### The rows that are still closure, and the one that is still NOT WORK

Re-measured 2026-10-05 with `formal/imports.py`'s own `resolve_module_path` —
the same walk, the same definition of `terminal` ("this module is the ONLY thing
standing between the file and a build"), and the same corpus rule (this
repository's own files, `bugs/`, `formal/` and the build directories excluded):

| file | unresolvable set, 2026-10-05 |
|---|---|
| **`test_formal_run.py`** | **{}** — see below |
| `tools/suite.py` | {} |
| `test_selfhost_memory.py` | {} |
| `version.py` | `{'functools'}` — `functools` alone, as at `-11` |
| `tools/apply_extraction.py` | `{'copy'}` — `copy` alone, as at `-11` |
| `test_suite.py` | `abc, copy, importlib, importlib.util, memslot, suite, types` |

`test_suite.py`'s line is the doc's own caveat about `memslot`, `suite` and
`importlib.util` being repository siblings a static walk cannot resolve, and
`abc`/`types`/`copy` are §2's three 0-terminal rows — so `test_suite.py` is a
closure number and not a row, exactly as §"The rows, ranked by terminal files"
said.

### `itertools` — closed by the corpus, and the reasoning is worth keeping

§4's caveat named `itertools` as the row worth noticing, because it was the
ONLY blocker for one file and the file was "the corpus's own run suite".
`itertools` is still not a host module and §2's reason is still true — the one
name this corpus uses "answers a SEQUENCE", and a run-time-length sequence is
`FORMAL_listdir_no_run_time_sequence.md`'s subject, which is a project.

**But `test_formal_run.py` did not need a sequence, and that is the whole of
what changed.** Its one use is `itertools.combinations(part, 2)` over a 26-element
slice inside a Python function that GENERATES Mojo source. `part` is a slice of
a list whose length the generator already knows, so every pair is an index pair
in a double loop, and the comprehension that consumed a generator takes that
without one. The generated Mojo is unchanged; the file loses a dependency.

Measured, and it is the claim the doc's own §4 makes about a module — *"the
verdict does not change, the SUBJECT of the refusal does, and a subject about the
file is one a person can act on"*:

```console
$ python3 -c '… formal.build.compile_formal("test_formal_run.py", arch="arm64", prove=False, check=False)'
REFUSED in 12.1s:
an f-string literal on line 146 is refused on this path: its value is its INTERPOLATED text…
```

and `tools/formal_sweep.py::classify` on that message, with the file's own
source and path, gives **`codegen`** — `ANSWERABLE`, `DIRTY` — where it was
`not-answerable/host-import`, which is excluded from the coverage denominator
entirely. So the 1043 build-and-run rows this suite holds are now under a class
that counts them, and the next construct in front of them is named (an f-string
literal, which is `FORMAL_string_composition_has_no_buffer.md`, claimed) rather
than a module nobody has written.

The rows are in `test_formal_run.py::check_type_value_tag_generator`, both of
them no-compiler so they cost a second rather than a minute of images:

  * **every pair, exactly once.** The `if X == Y` lines are read back out of
    the GENERATED Mojo — not out of the loop that wrote them, which is what
    makes it a property of the program the backend will compile — and asked to
    cover every unordered pair of every 26-name chunk once and no pair twice.
    786 pairs over 3 chunks. The ORDER is deliberately not asserted, and the
    docstring says so: two orderings are two images and the same answer, so
    pinning one would be pinning a detail under a coverage claim.
  * **this file's own import closure**, walked with the resolver the BUILD uses
    (not an `ast` approximation, which would pass on a file the sweep still files
    as host-import). 12 modules, `{}` unresolvable.

### What is left on the row

`functools` for `version.py` and `copy` for `tools/apply_extraction.py`, one
file each, and both are still §2's shapes: `lru_cache` is a decorator over a
function value (`bugs/FORMAL_functools_is_unbuildable_as_a_host_module.md`, and
`version.py`'s one use is `@functools.lru_cache(maxsize=1)` on a function this
repository could spell as a plain cached call), and `copy`'s is `deepcopy` over
objects this path has no heap for. Neither is a module worth writing; the honest
statement is that two files in this repository are one stdlib call away from
being swept and each call is a capability question rather than a missing file.
