# FORMAL_subprocess_row_measured_b7: the `subprocess` host-import row, re-measured over all 143 importing files — and the correction it forces on the `-5` sweep's ranking

**Claim** `sweep12:hostmods-subprocess`. Written 2026-10-03 on
`work/formal12-hostmods-subprocess`, after the model landed its measured call
surface (commit `6189ec2f`). Every number below is measured on this tree; the
commands are in §6.

The short version: **the row is worth 0 files, and it was always going to be.
But not for the reason on record, and that difference matters** — the recorded
reason is a false statement about the compiler that would have sent the next
reader to the wrong file.

## 1. What the row is

143 files in the sweep's scope import `subprocess` (`tools/formal_sweep.py`'s
`find_source_files` over the repo plus `stdlib/std`, filtered by
`^\s*import\s+subprocess\b`). `subprocess` moved out of
`formal/imports.py`'s `HOST_UNREACHABLE` into `HOST_ADMITTED` on 2026-10-02,
so it no longer appears in the sweep's `not-answerable/host-import by module:`
line at all — the module is answered and a file that builds on it is counted as
`built-with-admitted-contracts`. What the row still is, is 143 files that import
it and do not build.

## 2. The measurement, before and after

The same 143 files, `-j 4 -t 60`, arm64, immediately before and after
`6189ec2f`:

| | files | pass | class CHANGED |
|---|---|---|---|
| before | 143 | **0** | — |
| after | 143 | **0** | **0 of the 103 both runs printed** |

**Zero.** And the terminal causes say why: **`subprocess` is not the terminal
cause for a single one of the 143.**

| n | terminal cause |
|---|---|
| 79 | `tempfile` — a host module with no Mojo source |
| 4 | `glob` |
| 3 | `gimple_codegen` (via `zlib`) |
| 2 | `datetime`, 2 `signal`, 2 `collections` |
| 1 each | `fire_compiler` (via `importlib`), `traceback`, `resource`, `copy`, `functools` |
| 3 | an `except` arm with a body (`test_cli_usage_text.py`, `test_native_dumpfull.py`, `tools/tu_grind.py`) — FORMAL.md phase 7, `bugs/FORMAL_except_arm_is_never_emitted` |
| 1 | `stat.S_IXUSR` read as a value — `bugs/FORMAL_module_state_no_storage.md` |
| 2 | a module whose API is its top-level statements (`module_loader.py`, `memslot.py`) — `FORMAL_dylib_module_body_has_no_load_time_entry_point` |

The order matters and is the whole finding: **`formal/imports.py` refuses an
unresolvable import before the build ever lowers a call**, so for 136 of the 143
the file stops at the import and `subprocess` is never reached. `tempfile` alone
is 79, and 103 of the 143 also import `tempfile`, which is why fixing
`subprocess` moved nothing: the build never got there.

## 3. The correction

The `-5` sweep's host-import ranking (the `formal8-7-r2` claim, whose doc was
deleted 2026-10-04 with its last module) gives this row a value of 0 and this
mechanism:

> **a keyword argument to a host module is REFUSED** … So **no `subprocess`
> module written in `formal/hostmods/` could be called by any of the 30 files**,
> however complete it was. The yield is 0 by a mechanism that no amount of
> implementation removes.

**The mechanism is false.** A keyword argument to a function in an imported
module binds as soon as the callee has a parameter of that name. Measured on
this tree, before any change:

```
$ cat .tmp/w/kw.mojo
from pathlib import match
def main() -> int:
    printf("b=%d\n", match(p="/x.py", pat="*.py"))
    return 0
Built: …/kw.out  [arm64/macho]          # builds and runs
```

and a parameter with a DEFAULT is filled across the dylib boundary the same way
(`nullcontext()` with `def nullcontext(v = 0)` prints `0`; `pack("i")` with five
defaults prints a packed integer). The doc's own probe
(`match(path="/x.py", pattern="*.py")`) used parameter names `pathlib.match` does
not have — its signature is `match(p, pat)` — so it measured a NAME MISMATCH and
read it as a refusal of keyword arguments.

That matters because the two readings point at different files. "A keyword
argument to a host module is refused" is a statement about the ABI with an owner
(`formal/build.py`, both emitters). "The model's parameter names do not match
CPython's" is a statement about one file, and it was true: `run(request: str)`
had no `capture_output` and all 547 call sites in this tree pass one. That is
what `6189ec2f` fixed, and the fix is now ratcheted —
`test_formal_admitted.py`'s `the modelled surface covers what the tree spells`
walks every `.py` with `ast` and fails when a called name is not declared with
matching parameters.

**The doc's CONCLUSION (0 files) was right, and this measurement says why**: the
row's yield is 0 because every one of the 143 files stops at a DIFFERENT
refusal first, not because no model could ever be called.

## 4. What the fix did buy, stated as a number and as a mechanism

`6189ec2f` moved **0 files** and it was not expected to. What it changed:

* **the module is now callable by the tree's own spelling.** Before it, every
  one of the 547 `subprocess.run` sites failed with `unexpected keyword
  argument`, and every `Popen` site (18) failed with `exports no Popen`, and
  every construction of `CompletedProcess`/`CalledProcessError`/`TimeoutExpired`
  (88) failed with `exports no …`. The module was modelled for nobody and was
  green in every differential test, because every differential test called a
  function that was already callable.
* **the admitted count went 7 → 12**, each new one a distinct host fact: the
  process id, `poll`'s `-1`, the two signals, `communicate`'s concatenated
  output. Each is a `sorry` in the generated Lean and a line on `fire.py`'s
  `trust:` output.
* **the wrappers' own `ValueError` rules are now computed** rather than left to
  the host, and `run`'s 12 parameters are the measured ones
  (`capture_output` 508, `text` 468, `timeout` 351, `cwd` 143, `check` 36,
  `env` 28, `errors` 4, `shell` 4, `input` 2, `stdout`/`stderr` 2, `stdin` 1).

## 5. The next row, sized

Ranked from `bugs/sweeps/sweep-arm-7.txt`'s `not-answerable/host-import by
module:` line, and re-measured here over the sweep's own scope:

| module | files in the row | what this tree actually calls | reachable half |
|---|---|---|---|
| **`tempfile`** | **111** | `TemporaryDirectory` 142, `mkdtemp` 92, `NamedTemporaryFile` 64, `TemporaryFile` 3, `mkstemp` 3, `gettempdir` 1 | **`mkdtemp` and `gettempdir` — `mkdtemp(3)` plus CPython's own candidate walk over `os.getenv` and `access(2)`, and NOTHING admitted.** `mkstemp` is reachable and is not written; see §7 |
| `importlib` | 48 | — | **0.** An embedded CPython; `HOST_UNREACHABLE` is right and there is nothing to write. |
| `glob` | 18 | — | the listing half is in the tree; `**` matching is not. Claimed by `formal10-3` (`FORMAL_glob_copy_collections_io_not_attempted`). |
| `zlib` | 15 | — | **0.** A library outside libSystem; the premise forbids linking it. |
| `collections` | 9 | `namedtuple` | the record half only. Claimed by `hostmods-platform`. |
| `signal` | 6 | — | **0.** |
| `types` | 6 | — | a type factory; `FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md`. |
| `copy` | 5 | — | **0.** One file imports it and never uses it; `copy.copy` is the identity, which is the shape of a wrong `time.time()`. |

**`tempfile` is the next row by a factor of 2.4, and it is worth 44 files.**
Measured over the 128 files in this repository that import it, **44 use ONLY
`mkdtemp`/`mkstemp`/`gettempdir`** and no unreachable name, so writing the
reachable half moves 44 files off `not-answerable/host-import` into the
answerable denominator, where they are counted as `codegen` findings rather than
as target facts. That is the `platform` row's arithmetic
(`bugs/FORMAL_platform_reachable_row_measured.md` §2) and the ceiling for a
`host-import` row to **PASS** is 0 either way: none of those 44 is a small
program.

`TemporaryDirectory` (142 uses) and `NamedTemporaryFile` (64) are 206 of the
305 attribute uses and are NOT reachable — a context manager and a file object
respectively, and `formal/hostmods/io.mojo` says at length why a stream is not a
value here. 84 of the 128 files use one or both, so the reachable half leaves
them exactly where they are.

`tempfile` is **no longer a recommendation**: `formal/hostmods/tempfile.mojo`
and `test_formal_tempfile.py` landed with it, `tempfile` left `HOST_UNREACHABLE`,
and `mkstemp` is absent with a measured reason. §7.

## 6. Reproducing §1-§5

The full commands are in §9; this is the short form.
python3 - <<'EOF' > .tmp/sp_list.txt
import sys, os, re
sys.path.insert(0, 'tools'); sys.path.insert(0, '.')
import formal_sweep as S
for f in S.find_source_files(list(S.default_roots()[0])):
    if re.search(r'^\s*import\s+subprocess\b',
                 open(f, encoding='utf-8', errors='replace').read()):
        print(f)
EOF
python3 tools/memslot.py --gb 8 --label spslice -- \
  python3 tools/formal_sweep.py -j 4 -t 60 --no-stdlib \
  $(cat .tmp/sp_list.txt | tr '\n' ' ') > .tmp/sp_slice.txt 2>&1

# The class comparison, three regexes and a dict (§2).
# The per-module ranking (§5's first column) is off the committed sweep log:
python3 tools/formal_sweep_causes.py bugs/sweeps/sweep-arm-7.txt
grep 'not-answerable/host-import by module' bugs/sweeps/sweep-arm-7.txt
```

## 7. `tempfile`, landed

`formal/hostmods/tempfile.mojo`, `test_formal_tempfile.py`,
`formal/hostmods/os/_syscalls.mojo::fs_mkdtemp`, and `tempfile` out of
`HOST_UNREACHABLE`. `gettempdir` is CPython's own candidate walk and is checked
against CPython's own answer on both backends, including with `$TMPDIR` pointed
at a directory of the test's own — which is the row that separates "first
candidate" from "first ENVIRONMENT candidate", and the reason this host would
not have caught a `/tmp`-first walk. `mkdtemp` is the real `mkdtemp(3)` and is
checked against CPython's own six invariants rather than a table, because six
random characters cannot be compared between two processes.

**Zero admitted contracts**, which is why `tempfile` is in no tier at all rather
than in `HOST_ADMITTED`: it is `fcntl`'s situation, not `subprocess`'s.

### What it moved, measured

Over the 128 files in this repository that import `tempfile`, `-j 4 -t 60`,
arm64:

| | before | after |
|---|---|---|
| refused for `tempfile` | **128** | **0** |
| `codegen` (a finding in the file) | 0 | **6** |
| `codegen/dependency` (a finding one level down) | 0 | **15** |
| `not-answerable/system-module-call` | 0 | **9** |
| `not-answerable/host-import` | 128 | 95 |
| `pass` | 0 | **0** |

**0 passes, as every host-import row in this project predicts** — none of those
128 files is a small program. What moved is that 21 of them are now in the
ANSWERABLE denominator and counted as findings, instead of being reported as a
fact about the target. The new top blocker for that row is `glob` x28,
`zlib` x12, `itertools` x8, `unittest` x7.

And the knock-on, over the 143 files that import `subprocess`, the same way:

| | before `tempfile` | after |
|---|---|---|
| `not-answerable/host-import` | 136 | **106** |
| `codegen/dependency` | 2 | **17** |
| `codegen` | 3 | **8** |
| **files that changed class** | | **29** |

29 of the 103 files both runs classified moved — 15 to `codegen/dependency`, 5 to
`codegen`, 9 to `system-module-call`. **`tempfile` was the top blocker for 79 of
the 143, and 6189ec2f made `subprocess` bindable; neither could show up in a
count until both had landed**, which is the strongest argument this map has for
the order the two fixes went in.

### What is next, re-ranked

The rows below `tempfile`, from the two slices above (128 + 143 files, the union
of everything `subprocess` and `tempfile` used to block). The b7 log's own order
is the same one; these two are what it looks like from here.

| module | tempfile slice | subprocess slice | reachable? | owner |
|---|---|---|---|---|
| **`glob`** | **28** | **31** | the listing half is in the tree (`os.walk`), `**` segment matching is not; `recursive=True` is a KEYWORD and binds now | `FORMAL_glob_copy_collections_io_not_attempted` (`formal10-3`) |
| `zlib` | 12 | 15 | **0** — a library outside libSystem, and the premise forbids linking it | — |
| `itertools` | 8 | 8 | generators over lists, and a list is a frame blob (`FORMAL_listdir_no_run_time_sequence`) | — |
| `copy` | 5 | 6 | **0** — `copy.copy` would be the identity | `FORMAL_glob_copy_collections_io_not_attempted` |
| `collections` | 3 | 5 | `namedtuple` only; the record wants a `struct` | `FORMAL_glob_copy_collections_io_not_attempted`, `module:…collections-rest` (`hostmods-platform`) |
| `importlib` | 5 | 5 | **0** — an embedded CPython | — |
| `signal` | 3 | 5 | **0** — a process-wide host object | — |
| `types` | 3 | 4 | **0** — a type factory (`FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time`) | `formal8-1` |
| `textwrap` | 4 | 3 | **WAS — and it LANDED on 2026-10-03**; §8 | landed |
| `random` | 3 | 3 | `arc4random_buf` is in libSystem | — |
| `inspect` | 2 | 2 | flagged as considered, not missed | — |
| `socket` | 2 | 2 | **0** | — |
| `unittest`, `functools`, `shlex`, `traceback`, `uuid`, `warnings`, `unittest.mock` | 1-7 | 1-2 | see `HOST_MODELLED` | `formal10-3` for `functools` |

**`glob` is next by 4x and it is already someone's** —
`“FORMAL_glob_copy_collections_io_not_attempted: `glob`”` is claimed by
`formal10-3`, whose claim names glob, copy, collections and io together. It is
also the row the recorded recommendation points at, and that recommendation is
now one step further along than when it was written: the keyword capability it
was waiting on landed in 6189ec2f and `glob.recursive=True` binds now, so what
is left is the `**` segment walk and nothing else.

**`textwrap` was the next row that is unclaimed and reachable**, and it landed
(§8). Its ceiling to PASS was 0 for the reason every row here is: the 5 files
that want it are test drivers.

**So `glob` is what is left**, and it is `formal10-3`'s: see §8.

Two things this row cost that are worth knowing before the next one:

  * **`mkstemp` is reachable and is NOT written**, because its only failure
    check cannot be trusted on this tree today.
    `FORMAL_a_bare_c_call_returning_a_32_bit_int_is_compared_as_a_zero_extended_word`
    has the measurement: a bare C call whose C return type is `int` arrives with
    the high 32 bits of the register unspecified, and this backend models every
    bare call's return as a full word, so `mkstemps(...) < 0` is FALSE for the
    `-1` the host returned. `mkdtemp(3)` returns `char *` and is unaffected,
    which is why one of the two shipped.
  * **`mkdtemp(suffix=…)` is correct only for an EMPTY suffix**, and that is
    pinned by a test rather than left for a caller to discover: `mkdtemp(3)`
    substitutes the last six bytes, so `.txt` after them is part of the name.
    The entry point that takes a suffix is `mkstemps(3)`, which is the callee
    the bug above is about.

## 8. `textwrap`, landed

`formal/hostmods/textwrap.mojo`, `test_formal_textwrap.py`, and `textwrap` out
of `HOST_MODELLED`. `dedent` and `indent`, over the `str_len`/`str_lead`/
`str_find`/`str_cmp` that `formal/hostmods/os/_syscalls.mojo` already has.
**Zero admitted contracts** for the third time, and the reason is the same one
each time: a string is a `char *` this path already carries, so there is nothing
to trust.

The cheapest row in the census, and that is what made it the right one to do
next rather than a small one: five files in this repository import `textwrap`
and spell `dedent` 78 times and `indent` twice, with no keyword argument
between them. `wrap`, `fill` and `shorten` are absent because a rendering WIDTH
is their subject and no file here asks for one.

Its own rule is the thing worth reading the docstring for, because the obvious
implementation is wrong: CPython's margin is the ` `/`	` prefix the
lexicographic MINIMUM and MAXIMUM of the non-blank lines agree on, not the
minimum of their leading-run lengths, and the two differ on `dedent("  a\n \tb")`
(0 against 1). `test_formal_textwrap.py`'s corpus group names the rows the
design rests on, requires them present, and asserts that the discriminating row
still discriminates against CPython on the host running it — so the docstring
and the corpus cannot drift apart without one of them failing.

Measured, `-j 4 -t 60`, arm64, over the 128 files that import `tempfile` (a
slice containing all five): `not-answerable/host-import` 95 → 92,
`not-answerable/system-module-call` 9 → 11, answerable denominator 21 → 22.

**What is left on this row is `glob`, and it is not mine to take**:
`“FORMAL_glob_copy_collections_io_not_attempted: `glob`”` is claimed by
`formal10-3`, whose claim covers glob, copy, collections and io together, and
its recorded recommendation is now one step further along than when it was
written — the keyword capability it was waiting on landed in `6189ec2f`, so
`glob.glob(pat, recursive=True)` binds and what remains is the `**` segment walk
and nothing else.

---

## 9. Reproducing everything above

```sh
export PATH=/opt/homebrew/bin:$PATH

# The file list each slice is over: the repo half of the sweep's scope, minus
# the stdlib tree (which has no `import subprocess`/`import tempfile` in it, and
# whose presence would only change the denominators).
python3 - <<'EOF' > .tmp/sub_list.txt
import sys, os, re
sys.path.insert(0, 'tools'); sys.path.insert(0, '.')
import formal_sweep as S
for f in S.find_source_files([os.getcwd()]):
    if re.search(r'^\s*import\s+subprocess\b',
                 open(f, encoding='utf-8', errors='replace').read()):
        print(f)
EOF
sed 's/subprocess/tempfile/' .tmp/sub_list.txt > /dev/null   # §7's slice

# A slice sweep, before and after.
python3 tools/memslot.py --gb 8 --label spslice -- \
  python3 tools/formal_sweep.py -j 4 -t 60 --no-stdlib \
  $(cat .tmp/sub_list.txt | tr '\n' ' ') > .tmp/sp_slice.txt 2>&1

# The per-file class delta between two runs (§2, §7), which is three regexes
# and a Counter and is what every "N files changed class" number here is.
python3 tools/formal_sweep_causes.py bugs/sweeps/sweep-arm-7.txt   # §3, §5

# The three test files, which are the durable half of all of it.
python3 test_formal_admitted.py            # the ratchet + subprocess surface
python3 test_formal_tempfile.py            # tempfile
python3 test_formal_textwrap.py            # textwrap
```

**-j 4 -t 60, not -j 6 -t 120**: this is 143 files of the 673-file scope and
every one of them is a REFUSAL, which is cheap — `~2.2 s of wall per build`
measured over 668 files in `FORMAL_sweep_work_map_2026-10-02_b7.md` §1.1. The
whole slice is 143 builds and finished in a few minutes on both sides of the
commit. A 60 s CPU bound was never the binding constraint: **no file in the
slice hit it**, and `-t 120` would change nothing except the time a hung file
takes to be reported.