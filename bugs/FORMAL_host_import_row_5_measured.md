# FORMAL_host_import_row_5_measured: what is left of the `not-answerable/host-import` row after `stat`, `math`, `shutil` and `fcntl`, and what each remaining module is worth

**Status: the row is CLOSED for four modules and DECIDED for the other five.
The one premise the five rest on was MEASURED FALSE on 2026-10-02 and is
corrected below: a keyword argument to a host module is NOT refused, and four of
the five numbers change with it. Written 2026-10-02 on the
`sweep5:hostmods-more` claim, which covered the whole
`.tmp/sweep-arm-5.txt` row. Everything below is measured on this tree or is a
reference to a measurement that already exists; the "worth" column is the number
that decides each one and it is stated before the reasoning, because the
reasoning is easier to argue with than the number is.**

## §CORRECTION (2026-10-02): the keyword-argument blocker is not a blocker

**"A keyword argument to a host module is REFUSED" is false on this tree, and
four of the five "worth" numbers below were derived from it.** The capability
exists and is complete, on both architectures:

    # a cross-module callee, keywords in declaration order, REVERSED, mixed
    # with a positional, and with an omitted parameter's default filled
    printf("%d %d %d %d %d\n", need_two(a=1, b=77), need_two(b=77, a=1),
           need_two(a=1), need_two(1, b=77), need_one(a=5))
    ->  77  77  511  77  5              CPython: the same

    # a HOST module, keywords written in reverse declaration order
    printf("%d %d %d\n", match_path(bn=4, b="*.py", an=4, a="x.py"),
           match_path(bn=1, b="*", an=4, a="x.py"),
           match_path(bn=4, b="*.md", an=4, a="x.py"))
    ->  1 1 0        identical on arm64 and x86-64, and identical to the
                     POSITIONAL spelling of the same three calls

    # a callee whose SOURCE is unreadable — the manifest alone
    two(b=2, a=1)  ->  12          two(nope=2) -> refused by name

**Why the original measurement found a refusal.** The program it measured was
`match(path="/x.py", pattern="*.py")`, and `formal/hostmods/pathlib.mojo`'s
`match` declares `(p, pat)` — so `path` and `pattern` name no parameter, and
`model.bind_call_arguments` correctly applied the language's rule. That call is
also not a CPython spelling: `pathlib.match` exists in CPython as the METHOD
`PurePosixPath.match(pattern)`, not as a module-level function taking two
named parameters. **The refusal was true, the conclusion drawn from it was not.**

**The mechanism, so nobody re-derives it.** `bind_call_arguments`
(`formal/model.py`) is the ONE implementation of "which argument lands on which
parameter" and both backends call it. For a callee in another image the
declaration comes from `_extern_decls`, keyed by the SYMBOL the call binds, and
the manifest's `call.positional` carries the parameter NAMES — which is why the
last measurement above works with the source gone and why the second row of the
table's own "what this costs" argument does not survive contact with it.

**What the numbers become.** `subprocess` and `glob` were the two verdicts
argued from the keyword refusal, and each keeps a reason of its own that was
never about keywords — `TimeoutExpired` being an exception, and `**` needing a
recursive walk — so both are unchanged in verdict and changed in reason. The
other three (`copy`, `ctypes`, `concurrent.futures`) never depended on it.
**The row's file counts and the census are the original document's, and are not
re-measured here.**

**Pinned by** four rows in `test_formal_cross_module.py`, all compared against
CPython on the same text where CPython has the spelling at all: the keyword
binding itself, the unknown-name refusal, the positional-and-keyword double
binding refusal, the host-module reverse-order call, and the manifest-only
binding. 30/30.

**`glob` IS WRITTEN, AND IT IS BLOCKED BY A CODERGEN BUG RATHER THAN BY `**`
(2026-10-03, `work/formal8-7-r2`).** `formal/hostmods/glob.mojo` exists on that
branch's working tree and is not committed. `has_magic` and `escape` answer
CPython's byte for byte on both architectures; the rest of the semantics were
designed against CPython's own `glob` over 23 patterns (`*.py`, `*`, `**/*.py`,
`a/**`, `**`, `?`, `[af]*`, `*/`, `a/`, `*/*/`, …) with the rules written down in
the module: the hidden-name rule, `**` as zero-or-more-segments under
`recursive`, the trailing `/` as a directory FILTER (not a decoration), and
CPython's `**`-last spelling as `D + "/"`. **A caller of it gets an image that
prints nothing and exits 1**, and a module whose callers bind and then compute
nothing is worse than no module at all.

**So the row's `glob` number changes shape, and the change is worth more than
the module would have been.** This document sized `glob` as "0 to PASS and about
4 files into `codegen`", with `**` as the hard part and everything else
mechanical. The measurement is that `**` was not the hard part: the two halves
this document already called mechanical (the listing, the matcher) really are
mechanical, and what stands in the way is neither of them. Filed with a
statement-level bisect and the list of shapes that are NOT the trigger as a
dedicated doc, since deleted with its fix. **That blocker is FIXED (2026-10-03),
at the root and not in the caller:** the
cause was `model.subscript_base_lowering` choosing between a pointer index and a
blob walk from the CALLEE's annotation, and it now derives the convention from
the call sites, so one value has one convention wherever it is named — pinned by
`test_formal_run.py`'s `both_arch_an_untyped_parameter_indexes_the_same_pointer_
as_an_annotated_one` and `test_formal_cross_module.py`'s
`a_container_returning_export_whose_helpers_take_the_buffer`, which is `glob`'s
shape in miniature. So the blocker doc is deleted and this row's number becomes
the one written here. What is left for `glob` is the run-time-length LIST and a
blob the callers can iterate, which this document's `**` bullet already names.

## What landed from this claim

| module | file | test | files moved to PASS |
|---|---|---|---|
| `stat` | `formal/hostmods/stat.mojo` | `test_formal_stat.py` | 0 |
| `math` | `formal/hostmods/math.mojo` | `test_formal_math.py` | 0 |
| `shutil` | `formal/hostmods/shutil.mojo` | `test_formal_shutil.py` | 0 |
| `fcntl` | `formal/hostmods/fcntl.mojo` | `test_formal_fcntl.py` | 0 |

**ZERO files moved to PASS, in all four cases, and that is the row's actual
shape.** A `not-answerable/host-import` row is a set of files that each want one
CPython module, and the sweep's own blurb is explicit that the class is kept out
of every rate for exactly this reason: it says a file is a fact about the target,
not a gap in the backend. What writing a module does to such a row is change
WHICH FACT it is:

  * from "blocked on a module that does not exist" (no owner) to "blocked on the
    thing that module cannot do" (an owner, and usually a bug doc), or
  * from a fact about the target to a REFUSAL in the file itself, which puts the
    file in the sweep's `codegen` denominator where its own problems count.

That second one is worth a number. `shutil` is a REVERSAL of a
`HOST_UNREACHABLE` entry, i.e. the sweep had called those three files
permanently out of reach and they are not; `fcntl` was in NO tier at all, so its
three files were not even classified with a reason; `stat` and `math` each move
one file off a row whose reason was a module that now exists. **None of that is
a coverage improvement and none of it should be reported as one** — the same
arithmetic `bugs/FORMAL_platform_reachable_row_measured.md` §2 performs on the
`platform` row, which moved thirty files and says "the ceiling for this row is
0".

## The five that are NOT written, and each one's number

| module | files | what it is worth | why |
|---|---|---|---|
| `subprocess` | 30 | **0** | measured below: every caller spells `capture_output=True`, and `TimeoutExpired` is an EXCEPTION this path has no answer for |
| `glob` | 7 | **0 to PASS, 4 into `codegen`** | the listing exists, the blob API would work, and the callers iterate the result as a list |
| `copy` | 1 | **0** | the one file imports `copy` and never uses it |
| `ctypes` | 1 | **0** | a dynamic loader for foreign code |
| `concurrent.futures` | 4 | **0** | threads |

(The `subprocess` row's reason is the one the §CORRECTION replaces: it read
"and a keyword argument to a host module is REFUSED", which is false. The
verdict is unchanged and the sentence now names the reason that survives.)

---

## `subprocess` — the decisive measurement, and it is not about `posix_spawn`

**The capability is there.** `posix_spawn(3)`, `pipe(2)`, `fork`/`execve` and
`waitpid(2)` are all in libSystem, and `formal/hostmods/os/_syscalls.mojo` is
where a Mojo module's C calls live. So the usual reason — "this image links
libSystem and nothing else, and there is no child to spawn" — is **false**, and
a reader who stopped there would conclude the module is unwritable when it is
merely unwritten.

**The blocker was the CALLERS, and half of that measurement was wrong.**
All 30 files use `subprocess.run`, and every one of them passes at least one
KEYWORD argument — `capture_output` in **29 of the 30**, `text=True` in 27,
`timeout=` in 27, `cwd=` in 25, `env=` in 6, plus
`stdout=subprocess.PIPE` (`tools/tu_grind.py:41`) and
`input=source_code` (`tools/analyze_stdlib_errors.py:31`). Those keyword
arguments are NOT a blocker: §CORRECTION measures them binding into a host
module's callee out of declaration order, on both architectures, and a module
author chooses the declaration. The measurement this section used to quote —

```
$ cat .tmp/w/kw.mojo
from pathlib import match
def main() -> int:
    printf("b=%lld\n", match(path="/x.py", pattern="*.py"))
    return 0
$ python3 fire.py build --formal --no-prove -o .tmp/w/kw2 .tmp/w/kw2.mojo
build: call match(): unexpected keyword argument 'path'
```

— refused `pathlib.match(path=…, pattern=…)` because `match` declares `(p,
pat)`, and that call is not a CPython spelling either.

**What survives is one item of the sized list: `TimeoutExpired`.** It is an
EXCEPTION and `tools/tu_grind.py:43` catches it, so a `timeout=` needs a
deadline poll and a second failure answer, and this path has neither
(`FORMAL.md` phase 7). 27 of the 30 files pass `timeout=`, so that is not a
detail of the module's surface — it is most of what it would be for.

### What the minimal honest subset WOULD be, sized

Stated so the next reader does not have to re-derive it, and so the number in
the table above is not a guess:

  * `run_code(path)` / `run1(path, a)` / `run2(path, a, b)` — a fixed argv,
    because a variadic call is a LIST and a list is a frame blob
    (`formal/hostmods/shutil.mojo`'s `gcdn` is the established shape for this).
    `posix_spawn` + `waitpid`: **two libc calls.**
  * `run_capture(path, n, out_buf, len_out)` — `pipe(2)` twice, the read loop,
    and a caller-allocated buffer with its length as an out-parameter, because
    captured output is bytes of unknown length. **Two more libc calls plus a
    loop and two out-parameters, and the caller owns the buffer.**
  * `TimeoutExpired` is an EXCEPTION, and `tools/tu_grind.py:43` catches it. So
    a `timeout=` needs a deadline poll and a second failure answer, and this path
    has neither (`FORMAL.md` phase 7). **This is the whole of the remainder.**
  * `env=` (`cwd=` is fine — `chdir` exists) needs `environ`, a `char **` walk, which
    `formal/hostmods/os/__init__.mojo` names as absent for the same reason it
    names for `listdir` before `listdir` landed. 6 of the 30 files.

**Recommendation: do not write it.** The honest subset is a day's work, moves
zero files, and its one missing capability is an EXCEPTION rather than an
argument-binding rule. The argument-binding half of the original recommendation
is done and measured; what remains is `FORMAL.md` phase 7.

## `glob` — writable now, and worth 4 findings rather than a module

`.tmp/sweep-arm-5.txt`'s row is `glob x7`: `bootstrap-validate.mojo`,
`checked_run.py`, `test_no_new_container_casts.py`, `test_relaxed_imports.mojo`,
`tools/audit_selfhost_ast.py`, `tools/fix_genexpr_anyall.py`, `tools/suite.py`.

**What has changed since `bugs/FORMAL_platform_reachable_row_measured.md` §3
measured it, and it is the reason this is now a decision rather than a "not
attempted":** the listing exists. `formal/hostmods/os/__init__.mojo` has `walk`,
`walk_free`, `listdir_len`, `listdir_get` as a `malloc`'d blob of paths in
PRE-ORDER, and `formal/hostmods/pathlib.mojo` and `formal/hostmods/fcntl.mojo`
between them hold one bracket matcher (`fnmatch.match_core` with a
does-`*`-cross-`/` flag, which `pathlib.match_seg` already calls). So both halves
`glob` was waiting for are in the tree.

**What would still have to be written** is the result API and `**`:

  * `glob.glob(root, pattern)` → a blob, with `glob_len` / `glob_get` /
    `glob_free`, exactly as `listdir` does. **Mechanical**, and the blob shape is
    proven.
  * `has_magic(pattern)` and `escape(pattern)`. **Small**, and pure.
  * `**` matching zero or more path SEGMENTS, recursively. This is the hard part
    and it is the reason the earlier note withdrew "ship the pattern half
    alone": a `**` walk wants recursion over the blob, and
    `formal/hostmods/shutil.mojo`'s `rmtree` shows the shape (walk, then a loop
    over the blob's words) — so it is now a real implementation rather than a
    redesign, but it is a day.
  * `recursive=True` is a KEYWORD (`checked_run.py:213`,
    `tools/audit_selfhost_ast.py:57`,
    `test_no_new_container_casts.py:157`), and `checked_run.py`'s whole use is
    `glob.glob(pat, recursive=True)`. **§CORRECTION changes what that costs and
    not what it blocks**: a keyword binds across the boundary into a declared
    parameter, so a `glob(pattern, recursive=0)` module makes all three of those
    lines callable, and the author of the module chooses the declaration. What is
    left of `glob` is the `**` walk above and nothing else.
  * `iglob` is a generator and `escape`/`translate` need a consumer; both absent
    the way `fnmatch`'s are.

**Worth: 0 to PASS and about 4 files into `codegen`.** Two of the seven
(`test_no_new_container_casts.py`, `tools/audit_selfhost_ast.py`) were measured
to land on refusals in themselves, and the rest want `subprocess` or a keyword
argument. So a day for four findings and no pass — which is the `fnmatch`
arithmetic in `FORMAL_platform_reachable_row_measured.md` §5, arrived at again
from the other side. **The one dependency this row had — the keyword-argument
capability — is measured and pinned as already present (§CORRECTION), so
`glob` is no longer waiting on that change.** What it IS waiting on, measured
2026-10-03, is a different one this document did not predict: the cross-module
call path, for a container-typed export whose body calls its own helpers. See
the §CORRECTION addition above.**

## `copy` — 1 file, which imports it and does not use it

`tools/apply_extraction.py:14` is `import copy` and there is **no other mention
of `copy` in the file** — measured, `grep -n copy` returns exactly one line. So
the row is one file, and the file's problem is not `copy`.

**And `copy` itself is not writable in an honest subset.** The full argument is
`bugs/FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md`, which
decomposes it; the short form is that `copy.copy` promises a shallow copy of an
arbitrary object and `copy.deepcopy` promises a graph walk, and a value on this
path is one 64-bit word, so the only implementable answer is
`copy.copy(x) -> x` for a scalar — a function whose name promises a
transformation and delivers the identity, which is the same shape as a wrong
`time.time()` and the reason `formal/hostmods/shutil.mojo` refuses to return
`""` for a copy it did not make. `copy.floor`/`ceil`/`trunc`/`round`/`fabs` are
absent from `formal/hostmods/math.mojo` for exactly this reason and the
reasoning is there.

**Recommendation: no module.** The file moves to `dataclasses`, which a stubbed
`copy` measured as its real next obstacle, and the root cause is the clone
capability — `FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md`.

## `ctypes` — 1 file, permanent

`module_loader.py` spells `ctypes.Structure`, `ctypes.c_char_p`,
`ctypes.c_void_p`, `ctypes.c_int32`, `ctypes.CDLL(...)` and
`ctypes.POINTER(_ReflectSym)` — measured, `grep -n "ctypes\." module_loader.py`.
`CDLL` is `dlopen` on a library this image does not link, which contradicts the
premise that a formal image links libSystem and nothing else, and
`ctypes.Structure`/`POINTER` is a type-definition API this path does not have.
`formal/imports.py` has had `ctypes` in `HOST_UNREACHABLE` under "a dynamic
loader for foreign code" since before any of this, and nothing measured here
changes it. **Recommendation: no module, no doc. The existing tier entry is the
record.**

## `concurrent.futures` — 4 files, permanent

All four spell `concurrent.futures.ThreadPoolExecutor(max_workers=…)` as a
CONTEXT MANAGER — measured, `test_formal.py:298`, `run_ft_sample.py:78` and
`:101`, `test_py314_full.py:152`, `rerun_and_consolidate_v2.py`. A thread pool is
threads: there is no thread, no scheduler and no `with` on this path
(`formal/imports.py`'s `HOST_UNREACHABLE` says "a thread, and a proved model of
one"). **Recommendation: no module, no doc.**

---

## The one line to take from this document

**There is no compiler capability standing between this row and its five
modules.** The one that used to be named here — a call across a dylib boundary
that accepts keyword arguments — was measured on 2026-10-02 to exist, to work
out of declaration order, to work through the manifest with the callee's source
gone, and to refuse an unknown name on every one of those paths; §CORRECTION has
the programs and `test_formal_cross_module.py` has the rows. What each of the
five now waits on is its own work: `**` for `glob`, an EXCEPTION for
`subprocess`'s `timeout=`, `environ` for `env=`, threads for
`concurrent.futures`, a clone for `copy`, a dynamic loader for `ctypes`.

**And the remaining blocker is worth more than all five: every caller passes
`capture_output=True` / `text=True` / `timeout=` / `cwd=` / `env=` / `recursive=`
as a KEYWORD, so a module that declares those names is callable today, and one
that does not is refused by name.** That is the language's rule rather than a
gap — but it is a rule a reader of this document spent a day assuming was a gap,
and the correction is the reason the rest of the row's arithmetic can be
re-derived without re-measuring it.
