# FORMAL_platform_reachable_row_measured: the `platform` row closed, and what the 30 files landed on

**Status: CLOSED for `platform`, and CLOSED for `platform()` as of 2026-10-02
(§1 has the update and the measurement that changed the recommendation); OPEN
for the two rows measured alongside it (`glob`, `collections`) and for
`fnmatch`, which are recorded here because the numbers are the answer and the
older docs' numbers are stale.**

Written 2026-10-01 on the `module:platform+fnmatch+collections-rest` claim.
What landed: `formal/hostmods/platform.mojo` (checked by
`test_formal_platform.py`), `uname(3)` / `sysctlbyname(3)` / `strcmp` in
`formal/hostmods/os/_syscalls.mojo`, and the removal of `platform` from
`HOST_MODELLED`.

This doc exists because `formal/imports.py`'s `HOST_MODELLED` comment promises
"the accounting is in `bugs/FORMAL_platform_reachable_row_measured.md`", and
because the two host-import rows this claim also owns — `glob` and
`collections` — were last measured on a tree where `os.listdir` and `re` had
not landed. Both of those measurements were wrong in a way that changed the
recommendation, and they are replaced below.

---

## 1. What `platform` is now, and the one absence that is NOT a host object

**Superseded 2026-10-02 for `platform()` itself, which is now here.** §1's
closing claim — "**`platform()` itself is not written, and it is one call
away**" — was true when this section was written and is not true now. What
landed, and what it cost:

* `platform(exe, aliased, terse)` in `formal/hostmods/platform.mojo`, plus
  `platform_string(p0…p5)` for CPython's `platform._platform`. Checked by
  `test_formal_platform.py`'s new `platform` group: 11 values and 11 join
  corners against CPython's own `_platform`, on this host.
* `str_strip`, `str_find`, `str_count` and `str_replace_all` in
  `formal/hostmods/os/_syscalls.mojo`. `str_replace_all` is the helper §5 below
  asked `fnmatch`'s `translate` to share, so that half of §5's next step is
  done and the rest (`fnmatch.mojo` itself, and the `pathlib.mojo` refactor)
  is not.
* §1's "one `read` in `_syscalls.mojo` plus a `filetype` reader" — **already
  landed before this update**, by the `construct:x86-byte-read-and-platform`
  claim: `fs_read` and `fs_macho_field` are both in `_syscalls.mojo`, and
  `architecture_bits`/`architecture_linkage` are the reader. §1 below was
  written as if they were still missing.

**The decision §1 got wrong is the one that matters, and it is a measurement
rather than a preference.** §1 proposed wrapping libSystem's
`_NSGetExecutablePath` and called it "the honest one and it is small". It is
not available: **that function FAULTS on this host.** Four ways, one of them
not this compiler at all:

    cc -O0 -o e  e.c  && ./e      # SIGSEGV  (extern int _NSGetExecutablePath(..))
    cc -O1 -o e1 e.c  && ./e1     # SIGSEGV
    cc -O1 -o e2 e.c  && ./e2     # SIGSEGV, 64 KiB static buffer
    python3 -c "… ctypes … _NSGetExecutablePath(buf, 65536)"   # SIGSEGV, from CPython

and `getprogname()` — which does work — returns a bare basename
(`./.tmp/plat/e3` → `e3`), not a path. So §1's *other* option is the one that
happened: the executable path is a **PARAMETER**, which is already how
`architecture_bits(exe)` and `architecture_linkage(exe)` are spelled in this
module, so `platform(exe, aliased, terse)` is consistent with them rather than a
new shape. The two flags have no defaults because a default argument is not
applied across a dylib boundary, so a caller writes `platform(exe, 0, 0)`.

**What is still absent, and none of it is a missing line of code:**

| CPython | here | why |
|---|---|---|
| `uname().processor` | `uname_processor()` → `""` | `uname -p`, a subprocess. CPython's own "cannot be determined" |
| `libc_ver()` | — | needs to read a file and shell out |
| `platform.processor()` | — | `sysctl kern.proc_translated` under Rosetta is not `uname -p` |

`platform()`'s answer is CPython's **minus the one word `uname -p` produces**,
and that is measured rather than argued: on this host CPython's
`platform()` is `macOS-26.6.2-arm64-arm-64bit-Mach-O` and this is
`macOS-26.6.2-arm64-64bit-Mach-O`.

Two things the old text also had right and are kept: `platform._platform`'s
cleanup cannot be exercised by `platform()` itself on this host (none of the six
parts contains a space, a slash, a colon or the word `unknown`), so the join's
eleven steps are pinned by a corpus of their own rather than by the composition;
and the oracle for `platform()` is CPython's `_platform` over this module's
pieces, **not** `platform.platform()`.

§2, §3, §4 and §5 below are unaffected by this and still stand.

## 2. The marginal effect of the module, measured: 30 files, 0 PASS, and 0 that could

`tools/formal_sweep.py` over exactly the thirty files that
`.tmp/sweep-x86-4.txt` classified `not-answerable/host-import` with `'platform'`
in the chain, `-j 6 -t 600`, on this tree (`.tmp/sweep-platform-30.txt`):

    [arm64] 30 files: PASS=0 not-pass=30
       not-answerable/host-import     30
      not-answerable/host-import by module: subprocess x28, shutil x2
      0 of the 30 mention 'platform' at all

**Thirty of thirty moved off `platform`, and thirty of thirty landed on a
PERMANENT fact about the target.** `subprocess` is a second process and
`shutil` is a writable filesystem, both `HOST_UNREACHABLE`
(`formal/imports.py`'s `HOST_UNREACHABLE`), and 29 of the 30 are test drivers
that exist to run `fire.py` as a child process. `formal/imports.py` is the
30th, one level down: it imports `cas`, and `cas.py` imports `subprocess`.

So the pass rate did not move and could not have: **the ceiling for this row is
0**, and that is a property of what those files ARE, not of what they import.
Stating it as "30 files unblocked" would be the "Files blocked is an upper
bound" mistake in the other direction — the row closed because every file in it
turned out to be permanently out of reach for a reason the module did not
cause, and the number that got better is the amount of **remaining work**, which
went from "30 files are waiting for `platform`" to zero.

That is the honest reading and it is worth one more sentence: a host-import row
whose files all turn out to need a second process is a row that was never a
coverage number at all, which is exactly what `tools/formal_sweep.py`'s own
`not-answerable/host-import` blurb says and why the class is kept out of every
rate.

## 3. `glob` re-measured: still 9 files, and the reason has moved

`.tmp/sweep-x86-4.txt` lists `glob x9`, and the older record
(`bugs/FORMAL_glob_copy_collections_io_not_attempted.md` §`glob`) said the
blocker was `os.listdir` and that "glob landed earlier" meant
`formal/hostmods/pathlib.mojo`'s `pathlib.match`. **Both halves of that are now
stale, and the useful question is what a `glob` would be worth TODAY.**

Why the 9 files still stop: `formal/hostmods/glob.mojo` does not exist. There
is no `glob` in the new-modular stdlib (`../new-modular/Mojo/stdlib/std`) and
none in this tree, and the refusal
`imports 'glob', which is a host module (CPython standard library), which has no
Mojo source for this backend to compile` is exact and current. What landed
earlier was the MATCHER (`pathlib.match`), not the module.

Measured with a one-function stub `formal/hostmods/glob.mojo` on the search
root (`def glob(p) -> int: return 0`), all nine:

| lands on | files | class after |
|---|---|---|
| `subprocess` | `checked_run.py`, `formal/x86_64_model_test.py`, `scripts/check_resolved_bugs.py`, `tools/fix_genexpr_anyall.py` | permanent |
| `importlib` via `fire_compiler` | `test_examples_parse.py` | permanent |
| a real codegen refusal IN THE FILE | `bootstrap-validate.mojo` (`print()` cannot tell whether `BinaryOp` is a string or a number), `test_relaxed_imports.mojo` (`+` on two strings), `tools/audit_selfhost_ast.py` (`sys` is a module-level name of another module) | **`codegen`** |
| misclassified | `test_no_new_container_casts.py` — classified `host-import`, but the message is a codegen refusal about `tokenize` having no home | see below |

**So a real `glob` moves 9 files off the reachable row: 5 onto permanent facts
and 4 into real findings — and 0 to PASS, for the same reason the `platform`
row had a ceiling of 0: they are test drivers.** Four files entering `codegen`
is worth having (they become findings in the denominator, which is what a
refusal in the file is supposed to be), but it is not a rate improvement.

The stale recommendation in the old doc ("`glob`'s pattern half —
`has_magic`, `escape` … a day's worth") is **superseded**: `os.listdir` and
`os.walk` have landed since, as exact run-time blobs
(`formal/hostmods/os/__init__.mojo`, `listdir_len`/`listdir_get`/
`listdir_free`), so the LISTING is no longer what blocks `glob`. What is left
is a pattern walk and a result blob, and `**` is the hard part of it — CPython's
`**` matches zero or more path segments recursively and this target has no
recursion to offer except `os.walk`, which is already written. Do the pattern
half alone and 9 files convert from "out of reach, with an owner" into
"refused by the export map", which is a WORGER label: it is a fact about the
target dressed as a gap in the backend. That is why no partial `glob` was
shipped.

One measurement worth keeping that is not about `glob`: with the stub,
`test_no_new_container_casts.py` was classified `not-answerable/host-import`
while its message names a codegen refusal (`'tokenize' has no home`). That is a
CLASSIFIER bug in `tools/formal_sweep.py` — a file whose refusal sentence is
about an unresolved name is being counted as a fact about the target — and it
means the sweep's host-import count is an over-count. Not this claim's file to
fix; recorded here so whoever owns `tools/formal_sweep.py` can find it.

## 4. `collections` re-measured: 0 files, and the "waiting on `re`" note is stale

Same stub method (`namedtuple` + `Counter` on the search root), the five files
`.tmp/sweep-x86-4.txt` classifies on `collections`:

| file | lands on |
|---|---|
| `formal/lean.py` | `shutil` (permanent) |
| `tools/arm64_insn_audit.py` | `subprocess` (permanent) |
| `tools/formal_sweep.py` | `concurrent.futures` (permanent) |
| `tools/formal_sweep_causes.py` | `importlib.util` (permanent) |
| `tools/heapprof_report.py` | `subprocess` (permanent) |

**Five of five onto permanent facts; a real `collections` would move zero
files.** The old doc's "three of the four are waiting on `re`, which is a real
module and is being written" is now false — `re` landed, and these five walked
past it to a second process and a loader. `collections.namedtuple` still cannot
be answered (it CONSTRUCTS a type, and a type is not a value on this path) and
`Counter` still is a dict, so the module remains a real gap; it is simply worth
zero files, which is why it is still unwritten.

## 5. `fnmatch`: reachable, worth zero files, and NOT written here on purpose

`fnmatch` is in this claim and is genuinely reachable — it is pure string
matching, and nothing about it needs a host object. It is worth **zero files**:
no file in the sweep imports `fnmatch`, so nothing would move.

It is also **not** `formal/hostmods/pathlib.mojo`'s `match`, and that file says
so at `match`'s own definition: `PurePath.match` is right-aligned and
non-recursive and `fnmatch.fnmatch` has neither. The difference that matters
most is that `fnmatch`'s `*` crosses `/` (`fnmatch.fnmatch("a/b.py", "*.py")`
is 1 in CPython, and `pathlib.match("a/b.py", "*.py")` is 0). Everything else —
the `[seq]`/`[!seq]` bracket rule, including `^` and `[` being literal in the
first position, and `?` — is the SAME code, and `pathlib.mojo` already has it
in `match_seg`/`match_bracket`.

So writing `formal/hostmods/fnmatch.mojo` without touching `pathlib.mojo` would
be the second implementation of one bracket matcher, which `CLAUDE.md` calls
out by name; and refactoring `pathlib.mojo` onto a `fnmatch.mojo` is a
cross-module change to a file another claim landed, which is outside this one.
**The next step, exactly:** put the bracket/`?`/`*` core in
`formal/hostmods/fnmatch.mojo` with a "does `*` cross `/`" flag, export
`fnmatch`, `fnmatchcase` and `translate` (all three pure, all three exactly
comparable against CPython), and make `pathlib.mojo`'s `match_seg` call it with
the flag off. `fnmatch.filter` needs a run-time-length sequence and `iglob`/
`fnmatch`'s laziness is a generator, so those two are absent on this path the
way every other collection here is. That is a half-day for one module plus a
refactor, for zero files — which is why it is written down rather than done.

**One third of that next step landed with `platform()` (2026-10-02): the
`str_replace_all(s, from, to)` helper is now in
`formal/hostmods/os/_syscalls.mojo`,** beside `str_find`, `str_count` and
`str_strip`, because CPython's `platform._platform` is eleven string cleanups
and `translate` is one. So the shared-machinery argument this section makes is
settled and only the module and the `pathlib.mojo` refactor remain.

`fnmatch.translate`'s one CPython subtlety, so the next person does not have to
rediscover it, is that it is a FUNCTION-BUILDING function: CPython's
`translate` returns a new function object, which is a construction of a type on
a path where a type is not a value — so `translate` is absent for the same
reason `collections.namedtuple` is, and `fnmatch.fnmatch`/`fnmatchcase` (which
are pure) are the reachable two.

## 6. What was verified, and how

The block below is the ORIGINAL author's measurements and is kept as the record
of what the row said at the time. The 2026-10-02 re-run, after `platform()`
landed, is in `git log` on the branch that landed it (`formal8-9`) and the
numbers that moved are the two that name this module: `test_formal_platform.py`
is 11/11 groups (was 8/8, and the three new ones are `platform` plus the
`exports`/`absent` rows the new public names changed), `test_formal_imports.py`
is PASS=52 (was 41, and the difference is other claims' host modules rather than
this one), `test_formal_link_accounting.py` is 211 checks (was 170, same reason).

    python3 test_formal_platform.py -v        # 8/8 groups
    python3 test_formal_imports.py             # PASS=41 FAIL=0
    python3 test_formal_link_accounting.py     # 170 checks, 0 failed
    python3 -m unittest test_formal_sweep_truth # 31 tests, OK
    python3 test_formal_os.py                  # 4/4 groups
    python3 test_formal_os_backing.py          # 39/39
    python3 test_formal_pathlib.py             # 7/7 groups
    python3 test_formal_small_hosts.py         # 4/4 groups

`test_formal_run.py` reports `PASS=472 FAIL=5` on this tree — and reports the
**identical five** on `HEAD~1` extracted to a scratch directory and run there, so
they are pre-existing on master and not caused by this change. They are
`empty_list_constructor_len_is_zero`,
`every_empty_container_ctor_is_zero_length`,
`empty_container_ctor_beside_a_literal`,
`blob_constructor_with_operands_is_refused_by_its_own_reason` and
`a_mutated_module_global_is_refused`, i.e. the zero-operand container
constructor and a mutated module global. No doc in `bugs/` covers them; that is
a gap in the queue rather than a finding of this change, and it belongs to
whoever owns `formal/model.py`'s empty-blob constructor.
`test_formal_dylib.py` likewise reports `PASS=11 FAIL=1`
(`default path emits a checked proof`) identically at `HEAD~1`.