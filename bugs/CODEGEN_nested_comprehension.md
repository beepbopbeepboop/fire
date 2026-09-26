# CODEGEN_nested_comprehension: the second generator's loop corrupts the first

## Status: FIXED on arm64 (the default backend); x86-64 still open on two
## distinct observables

Split out of the old root `BUG.md`, which was an append-only ledger spanning
several subsystems rather than a set of bug reports. **Ownership is mixed in
this one and the split is not clean, so the whole cluster is here rather than
sliced:** the arm64 half is the other agent's work, the x86-64 half is ours,
and the root cause below is the context for both. Cutting it in half would
leave each part without the cause that explains it.

The arm64 material that used to stay in `BUG.md` has since been split into
`FORMAL_arm64_instruction_coverage.md`, `FORMAL_arm64_known_proof_gaps.md` and
`CODEGEN_arm64_cmp_flags_and_loop_signedness.md`.

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

## x86-64 handoff: nested comprehension returns 98 for 100

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

## Two gaps found while fixing this, both still open

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

## Original report, for the record

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

## Comprehension shape matrix (x86-64 side, characterisation for whoever picks it up)

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
