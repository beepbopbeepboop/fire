# FORMAL_eleven_of_thirteen_host_import_rows_are_closure: what the host-import row looks like once `tempfile`, `textwrap`, `posixpath` and `html` have landed

**Measured 2026-10-03** while picking the next host modules from
`bugs/FORMAL_sweep_work_map_2026-10-02_b7.md`'s host-import row. Not a claim on
any of these modules — it is the measurement that says which of them is WORK and
which is a file waiting on something else, because the ranking that started this
(`tools/formal_sweep_causes.py --host`, and
`bugs/FORMAL_host_import_row_ranked_by_module_2026-10-03.md`) reads a sweep log
from **2026-10-02**, and `formal/hostmods/tempfile.mojo` landed on **2026-10-03**.

That date is the whole content of this doc. The b7 log's `--host` table does not
list `textwrap` at all — not because the row is small but because in that run all
three files wanting it were still stopped by `tempfile`. A module landing UNMASKS
the row behind it, and the ranking cannot see that until a sweep is re-run. So
every number below is measured NOW, by walking each file's import closure with
`formal/imports.py`'s own `resolve_module_path`, which is the resolver the build
itself uses.

## The measurement, and how to reproduce it

Two numbers per module, because they answer different questions:

  * **terminal** \u2014 `m` is the FIRST unresolvable module in the file's eager
    import walk. This is what `tools/formal_sweep.py` prints and what the b7 log
    ranked. It is the number that says "writing this module makes this file get
    further".
  * **closure** \u2014 `m` appears SOMEWHERE in the file's import closure. It is the
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
    walk, statically, and it is the `.tmp`-free version of what §4 of
    `FORMAL_host_import_row_ranked_by_module_2026-10-03.md` did by hand.

## The rows, ranked by terminal files

| terminal | closure | module | what it actually is |
|---:|---:|---|---|
| **7** | 217 | `glob` | WORK, and the largest reachable row left. See \u00a73 \u2014 **this doc does not claim it** |
| 4 | 93 | `collections` | NOT WORK: owned, and the answer is a message not a module |
| 2 | 3 | `datetime` | NOT WORK: the answer is a `struct`, and there is a doc for it |
| 1 | 205 | `copy` | NOT WORK: the same doc, and the same missing thing |
| 1 | 26 | `resource` | NOT WORK: `getrusage(2)` is libSystem but its ANSWER is `struct rusage` |
| 1 | 16 | `itertools` | NOT WORK: the one name this corpus uses answers a SEQUENCE |
| 1 | 3 | `random` | NOT WORK: the state is 624 words |
| 1 | 1 | `functools` | NOT WORK: every name is a decorator or a function value |
| 0 | 66 | `types` | NOT WORK: the one name is a TYPE FACTORY |
| 0 | 13 | `operator` | NOT WORK: every name is a FUNCTION VALUE |
| 0 | 204 | `abc` | NOT WORK: zero files, and the reason is in \u00a72 |
| 0 | 4 | `inspect` | NOT WORK: reads source off a live interpreter |
| 0 | 3 | `shlex` | NOT WORK **yet** \u2014 reachable, but the one file that wants it stops on `glob` first |

**Eleven of the thirteen are closure, not work, and that is the finding.** The
ranked doc reached the same conclusion for six of them from a different direction
(\u00a72 of that doc: "the honest next step is not 'write the module' \u2014 it is 'find the
module that really stops those files'"); this measures the whole row rather than
six names in it.

## \u00a72 The three 0-terminal rows, measured name by name

Each of these has a specific reason it is not a module, and each is checkable in
one grep \u2014 which is the level at which "not reachable" should be argued, because
"not reachable" is a claim about a capability and these are claims about SPELLINGS.

  * **`types`, 0 terminal / 66 closure.** Every `types.X` in this repository that
    is the standard library is `types.ModuleType` (x10). The other ~200 `types.*`
    hits are `formal/types.py`'s own members reached through a local named
    `types` \u2014 `types.IdentExpr`, `types._safe_name`, and so on \u2014 and
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
    already documents the substitution it made \u2014 `operator.index` has a
    hand-written stand-in at its line 2076, and the file says why.
  * **`abc`, 0 terminal / 204 closure, and this is the interesting one.** The
    import is in `fire_compiler.py` and the imported NAME IS NEVER USED AS A
    VALUE:

        from abc import abstractmethod          # line 62
        ...
        body.append(f"{pad}    @abstractmethod")   # line 7592 \u2014 a STRING

    So `abc` is the `typing` shape exactly: the import resolves as soon as the
    module EXISTS, `abstractmethod` need not be in any export table, and nothing
    ever reads the name (`formal/hostmods/typing.mojo`'s docstring measures that
    for `Optional`). A module would therefore buy **zero files**, because
    `fire_compiler.py` \u2014 the only file that imports `abc` \u2014 is blocked by five
    modules at once, measured:

        fire_compiler.py unresolved: ['abc', 'copy', 'glob', 'importlib', 'zlib']

    and four of the five are owned elsewhere. **The 204 is a closure number and
    it is a trap**: it is the second-largest in the table and it is worth exactly
    nothing, which is the argument for having a `terminal` column at all.

## \u00a73 `glob` is the only real row left, and this doc does not claim it

**7 terminal / 217 closure**, and it is the largest thing in the reachable part
of the host-import row. `bugs/FORMAL_host_import_row_ranked_by_module_2026-10-03.md`
records it as **OWNED \u2014 `formal10-3`**, holding
`FORMAL_glob_copy_collections_io_not_attempted.md`. That document is NOT in this
tree and `formal/hostmods/glob.mojo` does not exist, and `formal10-3` is not in
`tools/control.py claims` on 2026-10-03 \u2014 so the claim is ambiguous: either that
work did not land or it landed and its doc was deleted with it (which is the rule
for a FIXED bug).

**So it is reported here and not taken**, because \u00a75 of that same doc is right
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
    build time \u2014 `os.walk` answers with a blob plus `walk_free`, so the shape
    exists, but the recursion over it does not.
  * `importlib.util.spec_from_file_location` (1 file) and `importlib`
    (48 files) are unreachable and are NOT this row's problem; 47 of the 48 are
    closure behind `fire_compiler.py`.

## \u00a74 What landed today, and what it moved

Three modules and the files each one unblocked, all measured by building the file
with the sweep's own argv:

| module | what it is | files that moved off it, and onto what |
|---|---|---|
| `textwrap` | `dedent`, `indent` | `test_runtime_diff.py` \u2192 `subprocess.TimeoutExpired` handler arm; `test_interp_oracle.py` \u2192 the same; `test_comptime_parity.py` \u2192 `sys.executable` |
| `posixpath` | 30 forwards to `os.path` | `test_formal_os.py` \u2192 `Exception as e` handler arm |
| `html` | `escape` | `tools/md2html.py` \u2192 `OSError` handler arm |

Plus `os.path.realpath`'s own divergence, found on the way and filed as
`bugs/FORMAL_os_path_realpath_keeps_a_double_slash_root.md`.

Every one of them moved onto a refusal about the FILE'S OWN SOURCE, which is the
whole value of a module in that directory: the verdict does not change, the
SUBJECT of the refusal does, and a subject about the file is one a person can act
on where a subject about a module is not.

## The next step, in the order the ranking gives

1. **`glob` \u2014 7 files, and the only real row.** \u00a73 says why it is not taken
   here; whoever takes it needs \u00a73's four bullets and the two ownership
   questions answered first.
2. **`shlex` \u2014 reachable, and blocked behind `glob`.** `quote`, `split` and
   `join` are pure computation over bytes a value already is (`formal/imports.py`
   says so), and the one file that wants it (`test_suite.py`, three
   `shlex.quote` calls) stops on `glob` before it reaches `shlex`. So it is a
   **sequencing** answer, not a capability one: write `glob` and `shlex` becomes
   the next wall for `test_suite.py` and `tools/suite.py`.
3. **`shlex` has an open QUESTION of its own**, and it is not a module:
   `bugs/FORMAL_link_accounting_shlex_entered_the_host_set_with_no_source.md`
   records that `shlex` was added to `HOST_MODULES` with no source, which fails
   `formal-link-accounting` in the everyday gate, and the doc asks which of two
   rules governs a sourceless standard-library name. Writing
   `formal/hostmods/shlex.mojo` takes the doc's option 1 (the `fcntl` route) and
   settles it \u2014 so **item 2 and item 3 are the same piece of work** and whoever
   takes it should read that doc first.
4. **`inspect`, `resource`, `datetime`, `collections`, `copy`, `random`,
   `functools`, `itertools`, `types`, `operator`, `abc` \u2014 all closure.** \u00a72
   gives the name-level reason for each and \u00a71 gives the row. None of them is
   next, and writing this down is the point: the ranking made eleven of them look
   like work and the measurement says otherwise.