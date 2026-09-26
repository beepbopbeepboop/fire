
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

**Status: FIXED on arm64** (the default backend). The cause was not the
register reuse described below, and it was not specific to nesting — a
SINGLE-generator comprehension failed exactly as hard as a nested one.
`test_x86_64_containers.py --arch arm64` went 32/45 -> 37/45, and
`test_formal_run.py` now carries eight comprehension cases (single, nested 2x2,
nested 3x2, over a list literal, with a condition, inside a for-loop, plus
`len(range(n))` with a runtime bound).

The actual cause: `_collect_var_names`'s `walk_compr_temps` was called with
`f.body` — a statement LIST — and recursed only through
`__dataclass_fields__`, which a list does not have. It therefore returned
immediately and **no comprehension control temp was ever allocated, in any
function**. `_ci{d}` (index) and `_cb{d}` (blob base) both fell through
`_store_var`/`_load_var`'s unknown-name path, which uses X19 — so the two
temps shared one register, and storing the index destroyed the base. Every
comprehension then executed `ldr xN, [x0]`.

Disassembly at the fault (`ldr x1, [x9]`, x9 = 0):

```
add  x0, x9, #0x0     ; blob base
add  x19, x0, #0x0     ; _cb0 -> X19
mov  w0, #0x0
add  x19, x0, #0x0     ; _ci0 -> X19 as well; base destroyed
add  x9, x19, #0x0
ldr  x1, [x9]          ; reads address 0 -> SIGSEGV
```

The sibling `walk_for_temps` did not have this bug because it iterates
`stmts or []` at its own top level.

**x86-64 is NOT fixed by this** — still 98 for 100. Its own write-up follows.

### x86-64 handoff: nested comprehension returns 98 for 100

Exact reproduction (`test_x86_64_containers.py:229`, n = 5):

```python
def f(n):
    xs = [i + j for i in range(n) for j in range(n)]
    t = 0
    for x in xs:
        t += x
    return t                      # want 100 (5*10 + 5*10), gets 98
```

It is 2 short, not a crash and not a wrong count, so elements ARE being
appended — a couple carry the wrong VALUE. A single-generator comprehension is
correct, and so is the same nesting on arm64, so it is specific to the
recursion in `X86_64Codegen._emit_compr_gen` (`formal/x86_64_codegen.py:2529`).

**Already ruled out**, so nobody re-checks these:

* The control temps ARE allocated. `walk_compr` (line 224) is invoked per
  statement — `for st in (f.body or []): walk_compr(st, 0, acc_c)` — so unlike
  arm64 it is handed a statement, not the list, and `_ci{i}`/`_cb{i}` exist.
  That was the arm64 bug; it does not apply here.
* The append cursor is NOT register-held. `_compr_append_elem` re-reads the
  count from the blob header (`R10 = [R11]`) and writes it back, so nested
  generators accumulate into one shared blob correctly — which is why the
  element COUNT is right and only values are wrong.
* The outer loop is self-healing for R10/R11: `label(start_label)` reloads
  both from `_cb{di}` on every iteration, so nothing needs to survive the
  recursive call in those registers.

**Where to look.** These four are live across the
`self._emit_compr_gen(expr, gi + 1, ...)` call at line 2599, and the inner
generator uses every one of them for the same purposes:

    R10   element count        R11   blob base
    R8    condition result     RDI   element address

The outer's element address is computed into RDI at line 2578
(`_emit_elem_addr(R11, RAX, RDI)`) and the value loaded from it at 2579, before
the target is stored and before the recursion — so if anything between there
and the recursive call needs RDI again, or if the target store is reordered
against the element load, the outer's element is the thing that goes stale.
`_emit_compr_append_elem` also takes RDI for the address it is about to write.

The structural fix worth considering, and the one arm64 gets for free: arm64
re-derives every value from memory *inside* the loop body — it re-loads
`_cb{di}` into X9 and the index at the top of each iteration, and the cursor
lives in the blob header. Nothing is carried in a register across the
recursion there, so the nesting simply works. Making the x86 body do the same
(re-derive the element address from `_cb{di}` + the index var after the
target is bound, rather than keeping RDI) removes the whole class rather than
one instance of it. A `push`/`pop` pair around the recursive call is the
smaller change if you would rather not restructure.

Suggested first experiment, cheapest thing that discriminates: make the
element expression `i` alone (so the element IS the bound variable, loaded
straight out of `_cb{di}`) and see whether 98 becomes 100. If it does, the
fault is in carrying the element across the recursion. If it does not, the
fault is in the target store or the shared blob, and the next thing to try is
giving each generator depth its own append scratch instead of sharing
R10/R11/RDI.

### Two gaps found while fixing this, both still open

**A dict comprehension computes the wrong value. PARTIALLY FIXED, still
broken.**

```python
d = {i: 100 + i for i in range(3)}
d[0]        # 100 — correct
d[1]        # 1, want 101
d[2]        # 1, want 102
len(d)      # 3  — correct
```

The right keys and the right count sit next to wrong values. It was masked
until the register-aliasing fix above, which killed every comprehension before
a value could be observed. A list comprehension with the same element
expression is correct (`[i * 2 for i in range(3)][2] == 4`) and dict
*literals* index correctly, so it is specific to `_compr_append_pair`.

**Two of the three defects are fixed** (arm64, committed):

1. The value never reached the pair append. The leaf case evaluated the VALUE
   into X0, then `ldp_sp_post(0, 2)` restored BOTH X0 and X1 from the stack —
   overwriting the value and leaving X1 holding whatever the loop last put
   there. It now saves the key alone and moves the value into X1.
2. The two pushes in `_compr_append_pair` are read back the wrong way round.
   The second `stp` lands lower, so `[sp+0]` is the value and `[sp+8]` is the
   key; the code loaded `[sp+0]` as the key and `[sp+8]` as the value, so
   every pair stored its key in the value slot. Fixing this is what moved
   `d[0]` from 0 to the correct 100.

**What is left.** Only the FIRST pair is right; every later one is wrong, and
its value reads as 1. So the cursor or the bound check is still off by
something. The suspect is the out-of-bounds guard, which reads:

```python
self.asm.emit(encode_cmp_xn_xm(1, 2))      # count vs cap
self.asm.emit(encode_cset_xd_cond(3, "cs"))  # X3 = count >= cap
self.asm.emit(encode_cbnz_xn(0, 3))         # branches on X0 — the KEY
self.asm.emit_label_rel(oob, here_offset=-4)
```

`emit_label_rel` only RECORDS a reloc (`formal/arm64.py:607`), and it patches
the displacement of the instruction 4 bytes back — so the `3` is a placeholder
and the real target is `oob`, taken when **X0** is non-zero. X0 is the key (or,
in `_compr_append_elem`, the element), never the count; the flag computed into
X3 is never tested. `_compr_append_elem` has the byte-identical sequence, so
whatever the right form is, it wants fixing in both.

Note this is NOT triggered by a zero element: `[0]`, `[5, 0]` and
`[i * 0 for i in range(3)]` are all correct, because a list *literal* goes
through `_emit_list`, which has no such guard. The comprehension path is where
it bites. Fixing it means testing the bound flag and not the payload — e.g.
branch when X3 is SET — and then re-checking both comprehensions, since the
list one is on the same code path and has simply not been exercised at a
non-zero element with a full count.

**Subscripting a comprehension directly is unsupported.**

```python
[i * 2 for i in [1, 2, 3]][2]
```

    build: subscript base must be a list/tuple name or literal on the formal
    arm64 path (got Comprehension)

Binding to a local first works. The subscript path recognises a name or a
literal base but not a comprehension, and since a comprehension produces a
blob in exactly the same shape, admitting it is a small change.

### Original report, for the record

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
