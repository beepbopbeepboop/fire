# FORMAL_host_import_row_5_measured: what is left of the `not-answerable/host-import` row after `stat`, `math`, `shutil` and `fcntl`, and what each remaining module is worth

**Status: the row is CLOSED for four modules and DECIDED for the other five.
Written 2026-10-02 on the `sweep5:hostmods-more` claim, which covered the whole
`.tmp/sweep-arm-5.txt` row. Everything below is measured on this tree or is a
reference to a measurement that already exists; the "worth" column is the number
that decides each one and it is stated before the reasoning, because the
reasoning is easier to argue with than the number is.**

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
| `subprocess` | 30 | **0** | measured below: every caller spells `capture_output=True`, and a keyword argument to a host module is REFUSED |
| `glob` | 7 | **0 to PASS, 4 into `codegen`** | the listing exists, the blob API would work, and the callers iterate the result as a list |
| `copy` | 1 | **0** | the one file imports `copy` and never uses it |
| `ctypes` | 1 | **0** | a dynamic loader for foreign code |
| `concurrent.futures` | 4 | **0** | threads |

---

## `subprocess` — the decisive measurement, and it is not about `posix_spawn`

**The capability is there.** `posix_spawn(3)`, `pipe(2)`, `fork`/`execve` and
`waitpid(2)` are all in libSystem, and `formal/hostmods/os/_syscalls.mojo` is
where a Mojo module's C calls live. So the usual reason — "this image links
libSystem and nothing else, and there is no child to spawn" — is **false**, and
a reader who stopped there would conclude the module is unwritable when it is
merely unwritten.

**The blocker is the CALLERS, and it is measured.** All 30 files use
`subprocess.run`, and every one of them passes at least one KEYWORD argument —
`capture_output` in **29 of the 30**, `text=True` in 27, `timeout=` in 27,
`cwd=` in 25, `env=` in 6, plus `stdout=subprocess.PIPE`
(`tools/tu_grind.py:41`) and `input=source_code`
(`tools/analyze_stdlib_errors.py:31`). And **a keyword argument to a host module
is refused**:

```
$ cat .tmp/w/kw.mojo
from pathlib import match
def main() -> int:
    printf("b=%lld\n", match(path="/x.py", pattern="*.py"))
    return 0
$ python3 fire.py build --formal --no-prove -o .tmp/w/kw2 .tmp/w/kw2.mojo
build: call match(): unexpected keyword argument 'path'
```

(the positional spelling of the same call builds and runs, printing `a=1`.)

So **no `subprocess` module written in `formal/hostmods/` could be called by any
of the 30 files**, however complete it was. The yield is 0 by a mechanism that
no amount of implementation removes, and that is a different statement from the
usual "worth zero because they are test drivers".

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
    has neither (`FORMAL.md` phase 7).
  * `env=` (`cwd=` is fine — `chdir` exists) needs `environ`, a `char **` walk, which
    `formal/hostmods/os/__init__.mojo` names as absent for the same reason it
    names for `listdir` before `listdir` landed.

**Recommendation: do not write it.** The honest subset is a day's work, moves
zero files, and adds a keyword-argument refusal to every one of the 30 instead of
a resolution. **The thing worth doing instead** is the capability behind the
refusal: a call across a dylib boundary that ACCEPTS keyword arguments and
applies the callee's defaults. That is the same capability
`bugs/FORMAL_default_argument_not_applied_across_a_dylib.md` is about from the
callee's side, and it is the one that would make `subprocess`, `shutil`'s
`copytree` flags, `glob`'s `recursive=True` and `re`'s flags all reachable at
once — **four of this row's modules and several others are blocked on one
compiler change, and that is the highest-value thing in this document.**

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
    `test_no_new_container_casts.py:157`) — **so those three files could not call
    it either**, by the same refusal as `subprocess`. `glob.glob(pat,
    recursive=True)` is the whole of `checked_run.py`'s use.
  * `iglob` is a generator and `escape`/`translate` need a consumer; both absent
    the way `fnmatch`'s are.

**Worth: 0 to PASS and about 4 files into `codegen`.** Two of the seven
(`test_no_new_container_casts.py`, `tools/audit_selfhost_ast.py`) were measured
to land on refusals in themselves, and the rest want `subprocess` or a keyword
argument. So a day for four findings and no pass — which is the `fnmatch`
arithmetic in `FORMAL_platform_reachable_row_measured.md` §5, arrived at again
from the other side. **Recommendation: after the keyword-argument capability, not
before.**

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

**Recommendation: no module.** The file moves to `dataclasses` (which
`FORMAL_glob_copy_collections_io_not_attempted.md` §`copy` measured as its real
next obstacle), and the root cause is the clone capability that doc already names.

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

**Four of the five remaining modules, and a fifth (`glob`) beside them, are
blocked on ONE compiler capability: a call across a dylib boundary that accepts
keyword arguments.** That is worth more than all nine host modules together, it
is the only item here that is not a module, and it is
`bugs/FORMAL_default_argument_not_applied_across_a_dylib.md` seen from the
caller's side. It is the next step I would take, and I have deliberately not
taken it here: it is a change to how a call is lowered in both backends, which is
outside what a host-module claim owns.
