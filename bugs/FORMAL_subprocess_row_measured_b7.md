# FORMAL_subprocess_row_measured_b7: the `subprocess` host-import row, re-measured over all 143 importing files — and the correction it forces on `FORMAL_host_import_row_5_measured.md`

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
| 2 | a module whose API is its top-level statements (`module_loader.py`, `memslot.py`) — `bugs/FORMAL_dylib_module_body_has_no_load_time_entry_point.md` |

The order matters and is the whole finding: **`formal/imports.py` refuses an
unresolvable import before the build ever lowers a call**, so for 136 of the 143
the file stops at the import and `subprocess` is never reached. `tempfile` alone
is 79, and 103 of the 143 also import `tempfile`, which is why fixing
`subprocess` moved nothing: the build never got there.

## 3. The correction

`bugs/FORMAL_host_import_row_5_measured.md` §`subprocess` gives this row a
value of 0 and this mechanism:

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
| **`tempfile`** | **111** | `TemporaryDirectory` 142, `mkdtemp` 96, `NamedTemporaryFile` 64, `TemporaryFile` 3, `mkstemp` 3, `gettempdir` 3 | **`mkdtemp` and `gettempdir` — `mkdtemp(3)` plus CPython's own candidate walk over `os.getenv` and `access(2)`, and NOTHING admitted.** `mkstemp` is reachable and is not written; see §7 |
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
311 attribute uses and are NOT reachable — a context manager and a file object
respectively, and `formal/hostmods/io.mojo` says at length why a stream is not a
value here. 84 of the 128 files use one or both, so the reachable half leaves
them exactly where they are.

`tempfile` is **no longer a recommendation**: `formal/hostmods/tempfile.mojo`
and `test_formal_tempfile.py` landed with it, `tempfile` left `HOST_UNREACHABLE`,
and `mkstemp` is absent with a measured reason. §7.

## 6. Reproducing this

```sh
export PATH=/opt/homebrew/bin:$PATH

# The row, before and after, over the importing files only.
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

Two things this row cost that are worth knowing before the next one:

  * **`mkstemp` is reachable and is NOT written**, because its only failure
    check cannot be trusted on this tree today.
    `bugs/FORMAL_a_bare_c_call_returning_a_32_bit_int_is_compared_as_a_zero_extended_word.md`
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

**-j 4 -t 60, not -j 6 -t 120**: this is 143 files of the 673-file scope and
every one of them is a REFUSAL, which is cheap — `~2.2 s of wall per build`
measured over 668 files in `FORMAL_sweep_work_map_2026-10-02_b7.md` §1.1. The
whole slice is 143 builds and finished in a few minutes on both sides of the
commit. A 60 s CPU bound was never the binding constraint: **no file in the
slice hit it**, and `-t 120` would change nothing except the time a hung file
takes to be reported.