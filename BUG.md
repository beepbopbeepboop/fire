
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

### Comprehension shape matrix (x86-64 side, characterisation for whoever picks it up)

Measured on the real binaries under Rosetta, summing the result blob with a
`for` loop and reading `len` off it. This narrows both backends' behaviour to
shapes rather than "nested":

| shape | arm64 | x86-64 |
|---|---|---|
| `len([i for i in range(4)])` | 4 | 4 |
| `len([i+j for i in range(4) for j in range(4)])` | 16 | **4** |
| sum, single generator | 6 | 6 |
| sum, nested 2x2 | 4 | **225** |
| sum, nested 3x2 | 9 | **1** |
| sum, nested 4x4 | **48** | **-11 (SIGSEGV)** |
| sum, nested `[j for i in range(3) for j in range(4)]` | 18 | **-11** |
| sum, nested `[7 for i in range(3) for j in range(4)]` | 84 | **21** |

Two things this adds to the write-up above.

**x86-64's COUNT is wrong, not just its values.** `len` of the 4x4 nested is
4 — the inner generator's count — where arm64 reads 16. So on x86-64 the blob
header is being left holding the inner count, which is a different bug from
arm64's earlier "the base register is destroyed by the index store": the
appends are landing somewhere, but the count in the header is not what the
append path read. That points at `_compr_append_elem` re-reading the count
from `[R11]` while R11 no longer holds the result blob base at that point —
i.e. the recursion is leaving the wrong value in R11 or R10 across the call,
and `_emit_compr_gen`'s `label(start_label)` reload only protects the OUTER
loop's own next iteration, not the append inside the inner one.

**arm64 has a residual of its own, and it is a doubling.** The 4x4 case reads
`len` = 16 (correct) and sum = 48 = exactly 2 x 24, while 2x2, 3x2, no-`i` and
constant-element nestings are all exactly right. A correct count with a doubled
sum is not a count bug and not a wrong-value bug: it is 16 elements whose values
sum to twice the right total, or 8 iterations each appending twice. Whatever
fixes the count bug should be checked against the 4x4 case specifically, since
2x2/3x2 passing does not cover it.

Reproduction used (each is `def f(n):` with `n` unused, called with 10):

```python
def f(n):
    xs = [i + j for i in range(4) for j in range(4)]
    t = 0
    for x in xs:
        t += x
    return t                       # 24; arm64 gives 48, x86-64 segfaults
```


## arm64 instruction coverage: audited, and the highest-value gaps closed

Not a bug — a survey, kept here because the answer is not guessable and the
tooling to re-derive it should not have to be written twice.

`tools/arm64_insn_audit.py` answers "what can the codegen not emit, weighted
by how often a compiler actually emits it". Counting the encoder table is not
the same question: this backend had 52 encoders and still could not express a
single conditional branch on a comparison's flags.

Method: take the encoder inventory from `formal/arm64.py`, take the real
instruction mix by disassembling 200 system binaries (4.0M instructions, 420
distinct mnemonics), and rank the difference. Pointer-authentication
instructions (`pacibsp` and friends, ~92k) are excluded **by decision, and the
exclusion is printed** — a backend with nothing to authenticate has no use for
them, and hiding that in a filter would be dishonest accounting.

| | before | after |
|---|---|---|
| encoders | 52 | 69 |
| covered | 86.2% | **92.0%** |
| genuinely uncovered | 11.5% | **5.7%** |

Added, in the order the audit said they mattered:

* **B.cond**, all 14 conditions — by far the biggest single gap (~154k
  occurrences). `if a < b` was `cmp` + `cset` + `cbz` + branch: three
  instructions, one materialising a boolean that the branch immediately reads
  back.
* **CSEL / CSINC / CSINV / CSNEG** (~40k) — a conditional *expression* should
  not become a branch. With Rn = Rm = XZR, CSEL is exactly CSET, which is how
  the existing `encode_cset_*` is now expressed.
* **TBZ / TBNZ** (~75k) — `if x & (1 << n):` was a mask, a compare and a
  branch. Bits 0-31 only: the architectural b40 form relocates imm14, and
  encoding that from memory of the spec is how you get a branch to the wrong
  address, so bits >= 32 raise instead.
* **LDUR / STUR** (~45k) — unscaled access, which in practice means the
  NEGATIVE displacement a scaled-offset load cannot express.
* **LDRH / STRH / LDRSH / LDRSW / LDRSB** (~39k) — the remaining access widths.
* **TST / CMN / SUBS** (~36k) — flag-setting ALU with no or minimal result.

### `test_arm64_encoders.py`: every encoder against `as -arch arm64`

209 instructions, each assembled by Apple's assembler and compared **byte for
byte**. This is a real oracle rather than a hand-derived bit layout, and it
immediately earned its keep — six of the new encoders were wrong on first
write and the harness said exactly how:

    csel family   CSNEG and CSINV have bit 31 SET (0xDA..), not clear
    ldrh / strh   the immediate scales by /2, not /4
    tst           no destination, so the Rn field is 31
    cmn           64-bit base has bit 30 clear (0xAB..)
    b.cond        imm19 counts INSTRUCTIONS, so the range is +-1MB — my first
                  version allowed 2MB, which lands a branch 1MB from where the
                  reloc intended and passes every value-level test

That last one is why the test also asserts the bound is **enforced** rather
than clamped: a silently truncated branch offset produces a program that runs
and computes something else.

One trap worth writing down: `otool -s __TEXT __text` prints each word in
display order, so decoding it little-endian yields the byteswapped
instruction and every comparison then fails for the same uninteresting reason.

### Not yet wired up: using B.cond and CSEL in the codegen

The encoders exist and are verified; the codegen does not emit them yet. It
still materialises a boolean and branches, via the `_record_cond_branch()` +
`encode_cbz_xn` pattern (66 `cset` sites). Wiring B.cond means giving the
comparison-emitting path a way to say "branch on these flags" instead of
"produce 0/1 and branch on it", which is a behaviour change on the hot path
for every `if` — worth doing, worth doing with the full gate behind it, and
not worth folding into a commit that also adds seventeen encoders.

Also still uncovered and genuinely worth having, in the audit's order:
`ccmp` (0.34%), `rev`, `ror`, `ubfx`/`ubfiz`, `madd`, and the float/convert
family (`fmov`, `ucvtf`, `fcmp`) — none of which this one-word integer model
has a use for yet.


## Emitting the new instructions: what it actually bought (measured, not assumed)

Wired up where it does NOT touch the proof-visible structure, since the
proof-generator work is deliberately deferred:

* **CSEL for a conditional expression** (`a if c else b`) and for
  short-circuit **`and`/`or`** as a value.
* **LDUR/STUR for spill slots** — a spill slot is a fixed displacement from
  the frame pointer, which is exactly what the unscaled form is for.

### The measurement, and the part that is not a win

A benchmark mixing a ternary, `and`, `or` and fourteen spilled locals, built at
818a851 and again after:

    total   176 -> 174 instructions
    sub     38 -> 33     ldr  3 -> 0     str  2 -> 0
    ldur    0 ->  3      stur 0 -> 2
    b        4 ->  1     cbz  3 -> 1     cbnz 1 -> 0
    csel    0 ->  3
    ldp     14 -> 18     stp 14 -> 18     <-- the cost

Same result (253) before and after, so nothing changed semantically.

**LDUR/STUR is the real win**: 10 instructions gone, because each spill access
was `mov` + `sub` + access and is now one instruction.

**CSEL is NOT an instruction-count win here, and the +8 stack pairs say why.**
The three CSELs replace three branches (-6 branch/cbz/cbnz) but need four
push/pop pairs to keep the operands live across the flag-setting compare,
because arm evaluation clobbers the flags. For a ternary whose arms are pure
and therefore *cheap* — which is exactly what the purity guard allows — two
`stp`/`ldp` pairs cost more than the branch they remove. It buys:

  * fewer BRANCHES, which is a pipeline argument, not a size one, and
  * fewer basic blocks, which is what `arm64_proof_gen` has to filter around:
    it picks a block ending in a recorded `cbz` as an entry condition, and a
    short-circuit CBZ ends a block identically — the reason
    `_cond_branches` exists as a filter at all. CSEL removes that ambiguity
    rather than adding to it.

So: keep both, but the honest summary is "10 instructions smaller and 6 fewer
branches", not "CSEL made it smaller".

The way to make CSEL a genuine size win is to stop needing the stack — keep
the two arms in registers that expression evaluation does not clobber. X9/X10
are not safe for that today (`_emit_list_base` alone uses X9), so it needs a
reserved-scratch convention first. Worth doing; not done here.

### Still blocked, and only on the deferred proof work

`B.cond` is the biggest single instruction in the audit (~154k occurrences) and
the codegen still does not emit it, because **all four** conditional sites
(`if`/`elif`, `while`/`for`, the ternary, and a comprehension's generator
conditions) call `_record_cond_branch()`, and `arm64_proof_gen` finds an entry
condition by looking for a block whose terminator is a recorded `cbz` and
reading the register that CBZ tests. A `B.cond` there is neither a `cbz` block
nor a register, so the proof would silently lose the condition. That is the
work being deferred, and it is the only thing standing between the current
tree and the largest win available in the audit.


## The largest codegen win in the project: immediates above 4095

Found by asking where the instructions actually GO, after the audit's
instruction-count measurement came out suspiciously small.

`_emit_sub_imm` / `_emit_add_imm` split any immediate above 4095 into a chain
of 4095-sized `SUB`/`ADD` instructions. The formal backend subtracts its 128KB
scratch from the frame pointer at the top of **every** list base, dict,
comprehension, container append and indexed access — and 131072 is
`32 << 12`, which arm64's `SUB (immediate)` encodes in ONE instruction via the
optional `LSL #12` on its 12-bit field.

So every container operation in the backend was paying **33 instructions** for
an address computation, and a program using lists and dicts was roughly 4x
larger than it needed to be:

    container benchmark, before -> after
      997 -> 261    (shifted immediates)
      261 -> 246    (fold the frame-base SUB)
      246 -> 225    (one SUB from X29 instead of mov + three subs)

Same answer (58) at every step. The 12 new cases in
`test_arm64_encoders.py` check the `sh` variants against `as -arch arm64`, so
the encoding is the assembler's and not a bit layout recalled from the spec.

The lesson worth keeping: an instruction-count audit that only asks "can we
express what a compiler expresses" misses this entirely. `sub` was fully
covered the whole time. The defect was not a missing instruction but a
*misuse* of one that was present — which is a different question, and the one
that actually decides how big the generated code is.

Also folded while in there: `_emit_list_base` emitted `mov x9, x29` followed
by up to three separate adjustments, when the whole displacement is a
compile-time constant and fits the shifted form in one.


## What is left in the instruction work, measured rather than guessed

Two items remain, and both are recorded here with their real cost so the next
person does not have to re-derive them.

**`B.cond` (the biggest single item in the audit, ~154k occurrences) is now
wired at every site that has flags to branch on**, and wiring it turned up two
real bugs rather than just closing a gap.

A comparison becomes `CMP` + `B.cond` — one branch, and no boolean round trip
through a register. It fires at `if`/`elif`, `while`, the `for`-range test, the
ternary's fallback, and a comprehension's generator conditions. It
deliberately does *not* fire for a call condition, a truthiness test, or a
short-circuit chain: those genuinely need a value, because there are no flags
to read. Branching on the FALSE case keeps the block shape byte-identical to
the old `cbz` lowering, so nothing downstream had to move.

Two bugs, both found by the first thing that actually ran the code:

  1. `Assembler.resolve()` had cases for `B`, `BL`, `CBZ` and `CBNZ` but none
     for `B.cond`. The displacement was never written, `imm19` stayed 0, and
     every conditional branch pointed at **itself**: `if a > b:` with a false
     condition was a one-instruction infinite loop. The first fix was wrong in
     a way worth recording — it identified the opcode with
     `insn & 0xff00001f == 0x54000000`, masking off the cond field and then
     comparing against a *zero* cond, which can never match. The top byte
     alone identifies `B.cond`; both the encoder and the model hit this same
     trap independently.

  2. `test_arm64_encoders.py` compares four instruction *bytes* against `as`.
     It therefore cannot see a missing *relocation*, which is why a perfectly
     green encoder suite coexisted with a compiler that hung on any false
     comparison. `test_arm64_emission.py` now checks that no branch resolves
     to its own address; that check was verified to fail when the fix is
     removed, so it is not vacuous.

The proof side is deliberately unfinished — the generator is to be thinned and
closed with `sorry` once the instruction work is done, and the `sorry`s
attacked after that.

**A reserved scratch-base register would take the frame base from two
instructions to one**, worth ~5% on a container-heavy function
(225 -> ~214 on the benchmark above). It is not worth doing: the register has
to come out of the callee-saved pool, so one fewer local lives in a register
and one more spills, and the saving is only realised if the extra spill does
not cost more than the base computation it replaced. It also changes the
prologue, which the proof generator models. That trade needs measurement
across a corpus, not one benchmark.

Two smaller things were checked and are already optimal:

  * `add x4, x9, #8` + `add x4, x4, x1, lsl #3` (17 occurrences) is an
    address computation that cannot be one instruction — arm64 has no
    scaled-index addressing, that is an x86-ism.
  * The `and`/`or` and ternary CSEL paths cost two push/pop pairs, which is
    the price of evaluating both arms without a stack frame convention for
    expression temporaries. Making them one needs registers that expression
    evaluation provably does not clobber; X9 alone is used by
    `_emit_list_base`.


## `for i in range(a, b)` never terminated: the loop had no exit test at all

Found while wiring `B.cond` into the for-range test. This is the worst-shaped
bug in this file, because it is not a wrong answer — it is a hang, and it was
sitting in a code path the test suite never entered.

The for-range lowering called `_emit_cmp(...)` at the top of the loop and then
**never branched on the CSET it left behind**. The emitted loop was:

```
loop:  cmp x0, x1          ; i vs end
       cset x0, lo         ; x0 = (i < end)   <- and then?
       add x0, x20, #0x0   ; x0 is overwritten here
       ...body...
       b loop
```

`cset` is flags-to-register; nothing consumed the register. There is no `cbz`
anywhere in the loop and no other exit, so control reaches the end of the
function's range only by running out of stack.

Every `for i in range(...)` therefore hung. It survived because comprehensions
use their own loop emitter, and the range cases in `test_formal_run.py` went
through comprehensions rather than a `for` statement.

Two bugs, both fixed:

  * **The missing exit test.** Now `CMP` + `B.cond` on the flags, the same
    shape as the `while` condition. Seven cases in `test_formal_run.py`
    (ascending, empty, descending, stride 2, single-argument, nested, `break`).

  * **Descending ranges exited immediately.** The test was hard-coded
    `i < end`, so `range(4, 0, -1)` — whose *counter* already advanced
    correctly, via `SUB` — compared `4 < 0` and did nothing. The comparison now
    follows the step's direction. A step whose sign is only known at runtime
    (`range(a, b, -step)`) is now **refused with a clear error** rather than
    compiled to a loop bound that is the wrong way round: a wrong answer, not
    a slow one.

### Still open: comparisons involving negative values are unsigned

Found in the same pass, and NOT fixed, because the root cause is a type bug
that would invalidate the whole condition-code table.

`range(-3, 2)` returns 0. So does `if -3 < 2: return 1`. Arithmetic is fine
(`0 - 3 + 5` is 2); only *comparisons* are wrong, and only when a negative
value is involved:

`infer_expr` returns `None` for `UnaryOp('-', IntLiteral(3))` — the parser
keeps `-3` as a negation, not a negative literal, and nothing gives it a type.
`common_type` then returns `None`, and `cmp_signed(None)` is `False`
(`formal/types.py:260`), so the comparison is emitted with the **unsigned**
condition codes. `-3` is `0xFFFF...FD` as a `UInt64`, so `-3 < 2` is false.

This is backend-wide, not a loop bug, which is why it is recorded here rather
than papered over in the for-range path. The fix is in `formal/types.py`:
give a negated literal a signed type. It has to be done there, because the
`B.cond` lowering deliberately shares `_cmp_conds` and the
`cmp_signed(common_type(...))` decision with the `CSET` value path — so
fixing it in one place fixes both, and fixing it in only one place would make
a comparison branch one way and evaluate the other. `formal/model.py`'s flag
lemmas (`arm64_flag_lt` and friends) and the B.cond condition-code table would
need re-checking against it.


## CURRENTLY RED, DELIBERATELY: the arm64 proof generator is half-wired for B.cond

`test_formal_dylib.py` is 8/1, not 9/9. The failure is
`default path emits a checked proof` — a *proof* case, and the proof side of
the `B.cond` work is deliberately unfinished.

What is done and working: the codegen, the `B.cond` encoders, the
`arm64_step` model case, and the Python-side block/step handling
(`_STEP_CONDS` entry 51, block shape, `_branch_target`, `_cset_cond`,
`_regs_written`, the run guard, and the two `step_ok` emitters).

What is NOT done: the entry-condition theorem. The generator finds a block's
entry condition by reading the register its terminator tests, and a `B.cond`
terminator has no register — its low 5 bits are the condition code. Rather
than state a theorem about the wrong register, such blocks currently take the
existing "no source-level condition" path and no entry condition is stated at
all, which is weaker but not unsound. The end-to-end CFG walk still rejects
some shapes it used to accept.

This is on purpose, and in this order: finish instruction selection, then thin
the generator and close everything with `sorry`, then attack the `sorry`s.
Anyone running the full gate in the meantime should expect this one case to
fail, and should not read it as a codegen regression — every runtime suite is
green (`test_formal_run.py` 26/26, `test_arm64_emission.py` 5/5,
`test_formal_imports.py` 11/11).
