
---

## BUG: `ARM64Codegen.__init__()` does not accept `dylib_syms` — every formal build fails

**Status:** FIXED (reported 2026-09-25, `test_x86_64_examples.py` back to 43/43
within the minute; the arm64 side now takes the same `dylib_syms` keyword the
x86-64 side does). Kept for the record. **Affects:** every `./fire.py build
--formal` (arm64 is the default backend), which died before emitting a byte.
**Found:** 2026-09-25, from `test_x86_64_examples.py`, whose arm64 reference leg
went from 43/43 to 0/43 with:

```
TypeError: ARM64Codegen.__init__() got an unexpected keyword argument 'dylib_syms'
```

**Not mine to fix** — the in-flight dylib-linking change in `formal/build.py`
introduces it. I have completed the x86-64 half of the same interface
(`X86_64Codegen.__init__(test_input, extern_style, dylib_syms)`, mangling the
callee to the linked dylib's exported spelling), so only the arm64 side is
outstanding.

### The mismatch

`formal/build.py:540-551`

```python
def _make_codegen(arch: str, fmt: str, test_input: int, dylib_syms: dict = None):
    if arch == "arm64":
        return ARM64Codegen(test_input=test_input, dylib_syms=dylib_syms)
```

`formal/arm64_codegen.py:374`

```python
def __init__(self, test_input: int = 10):
```

### Fix

Either accept and store the map in `ARM64Codegen.__init__` (and use it at the
call site the way `formal/x86_64_codegen.py:_emit_call` does), or drop the
keyword at `formal/build.py:551` until the arm64 side is ready. The first is
what keeps `--backend=arm64` and `--backend=x86_64` on one interface.

### Why it is worth catching with a test rather than by eye

`_make_codegen` is shared by both backends now, so a keyword added for one of
them breaks the other at *runtime*, and only on the branch that takes it —
nothing at import time, and a build-only check that never reaches the
constructor's mismatch would still be green. `test_x86_64_examples.py` catches
it because it builds the same example through BOTH backends.

## x86-64 build dies on the `structs` keyword (arm64 work in progress)

`formal/build.py`'s shared `_codegen_and_link` passes `structs=structs` into
`codegen.compile(...)`, but `X86_64Codegen.compile` did not take it:

```
X86_64Codegen.compile() got an unexpected keyword argument 'structs'
```

Every x86-64 build failed, so `formal/x86_64_model_test.py` and the x86-64
proof path could not run at all. Fixed on the x86-64 side by accepting and
ignoring the argument (`formal/x86_64_codegen.py:412`) — one interface, two
backends, and no dependency on the arm64 struct work landing first. If the
x86-64 backend later needs the map, it is already threaded through.

## `make check-native-dumpfull`: self-hosted `mojoc` writes no `fire.ci` at all

While gating the x86-64 model work:

```
✗ ./mojoc fire.py --dump-full produced NO fire.ci (exit 0) - the known
  original SIGBUS in _rewrite_assign_stmt writes the correct file before
  crashing, so an ABSENT file is a worse regression, not the known issue
```

This is the *documented-in-wrong-direction* failure, not the documented one.
`bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md` records a SIGBUS that
happened AFTER the correct `fire.ci` was written; here nothing is written at
all, and the exit code is 0.

**Status: still open, symptom changed.** After the fire/master merge (which
brought a `try/except AttributeError` around the `sys.platform` read in
`mojo/middle/comptime.py:eval_const` — the very `AttributeError: platform`
this presented as) the failure is no longer "exit 0, nothing written": mojoc
now dies on **signal 9 (SIGKILL)** with still no `fire.ci`. So it is not
silently exiting any more, but nothing is written either. The x86-64 model
work is now committed (f6046f3) and this is reproducible on a clean tree, so
the "not in fire.py's input graph" reasoning below no longer explains it.

Not caused by the x86-64 work, and not by anything else in the working tree
either:

  * `mojoc` was deleted and rebuilt from current sources — it still fails, so
    it is not a stale binary.
  * `./mojoc fire.py --dump-full` compiles `fire.py` alone, and `fire.py` does
    not import `formal/`, so none of the x86-64 model/`formal/` changes are in
    its input graph.
  * `git status` is clean for every dump-full input (`fire.py`,
    `gimple_codegen.py`, `module_loader.py`, `mojo_compiler.py`, `runtime/`).
  * The python3-interpreted reference still produces a correct 37MB
    `fire.ci` for the same source, so the divergence is native-codegen-only,
    which is the whole point of this check.

`fire.py` was last modified at 16:13, before the x86-64 session began, so the
regression most likely came in with that change. Left for whoever owns
`fire.py`; fixing it from here would mean editing a file another agent has
open.

## `make bootstrap`: `verify` still fails, on the documented pre-existing bug

`FAIL stage1 vs stage2: <file>.ci` on 15 files, then
`✗ Stage verification FAILED`. The core of the set — `fire.ci`,
`fire_compiler.ci`, `fire_main.ci`, `mojo.ci`, `myinterpreter.ci`,
`module_loader.ci`, `bootstrap-validate.ci` — is exactly the 14-file failure
recorded in `bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md`, with a
few peripheral `.ci` files differing from that write-up (that doc notes
`PYTHONHASHSEED`-dependent nondeterminism in the reference path itself, so the
set is not expected to be stable).

The x86-64 work cannot reach it: every file changed here is under `formal/`,
`lib/*.lean`, `Makefile`, `.gitignore` or `BUG.md`, and the only `Makefile`
edits are to the Lean `.olean` rules — `bootstrap`/`verify` are untouched.

## `len(x)` is not implemented on either formal backend — it links to a libc symbol

**Status:** FIXED on both backends (arm64 then x86-64; the x86-64 half waited
only because `formal/x86_64_codegen.py` was another agent's active file, and
landed once that agent was stopped). `len(range(10))` now returns 10 on
arm64 and on x86-64 under `arch -x86_64`. Five cases in
`test_formal_run.py` pin it (list, range, empty, nested, and two lens added).
On arm64 the symptom was worth stating exactly, because it is not a wrong
answer: the image built and then **aborted in the loader** with
`dyld: Symbol not found: _len`. A string argument is refused by name on both
backends — a string is a bare `char *` with no length prefix, so there is no
count at offset 0 to read, and returning the pointer would be a
plausible-looking wrong answer.

Found while gating the x86-64 machine model. `formal/x86_64_model_test.py` is
green, but the container suite has one failure
(`test_x86_64_containers.py`: 44/45), and the same input is wrong on arm64 too.

```python
def f(n):
    return len(range(n))     # f(10) should return 10
```

| backend | expected | actual |
|---|---|---|
| arm64    | 10 | -6 |
| x86_64   | 10 | -6 |

Root cause, confirmed from the emitted image rather than inferred: `len` is
not a builtin the codegen knows. `_emit_call` (`formal/x86_64_codegen.py:2683`)
special-cases `range` and then treats every other callee as either a known
function or an extern, and `len` matches neither, so it becomes an extern call:

```
$ python3 -c "...compile and print info['extern_calls']..."
extern call: {'sym': 'len', 'addr': 4294968347, 'kind': 'call'}
```

There is no `len` in libSystem, so the call binds to nothing meaningful and
returns whatever was in RAX — hence the same `-6` on both architectures rather
than two independent wrong answers. `len` is listed in
`formal/comptime_runner.py:116`'s `_KEYWORDS`, so the comptime path knows about
it; the compiled path does not.

Fix: lower `len` the way `range` is lowered — read the blob's count field (the
first 8 bytes) into RAX. It is one case in `_emit_call` plus the same in
`formal/arm64_codegen.py`.

Originally left alone deliberately: both files were open with another agent
doing the arm64 formal sweep, and a one-case builtin is not worth a collision.
Not an x86-64 regression and not a machine-model problem —
`formal/x86_64_decode.py` decodes the image correctly and the model agrees
with the hardware on all 43 examples (`test_x86_64_examples.py`: 43/43).

## Nested comprehensions: the second generator's loop corrupts the first

```python
def f(n):
    xs = [i + j for i in range(2) for j in range(2)]
    t = 0
    for x in xs: t += x
    return t                     # 4
```

| backend | expected | actual |
|---|---|---|
| arm64    | 4 | SIGSEGV (-11) |
| x86_64   | 4 | 177 |

Both wrong, differently — which points at shared structure rather than one
backend's register allocation. `_compr_cap` (`formal/x86_64_codegen.py:1458`)
documents that nested generators MULTIPLY and does so, so the reservation is
right for a 2x2; the corruption is in `_emit_compr_gen`'s recursion, where the
inner generator reuses R10/R11/R8/RDI — the same scratch the outer generator's
loop bookkeeping is mid-way through. The arm64 segfault rather than a wrong sum
is consistent with an append running past its reservation.

A single-generator comprehension is correct on both backends, so this is
specific to the nesting, not to comprehensions.
