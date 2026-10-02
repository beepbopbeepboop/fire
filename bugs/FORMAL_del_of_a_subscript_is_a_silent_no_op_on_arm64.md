# FORMAL_del_of_a_subscript_is_a_silent_no_op_on_arm64: `del a[i]` builds, runs, and removes nothing

**Status: found, NOT fixed. Measured on this tree, both architectures.**
Found from the x86-64 sweep slice (`sweep:x86-a`, work map
`bugs/FORMAL_sweep_work_map_2026-10-02_x86-a.md`), where the x86-64 side of it
is a refusal and the arm64 side turned out to be the worse of the two.

## What it is

`del a[i]` and `del a[i:j]` — a subscript target — are a **silent no-op on
arm64**: the image builds, runs, exits 0, and the list is unchanged. On x86-64
every `del` at all is refused by name, so the two architectures do not even
disagree about the answer; one of them has no answer and the other has a wrong
one.

Two reproducers, built with `--formal --no-prove`, run, stdout shown:

```mojo
def main():
    var a = [10, 20, 30]
    del a[0]
    printf("%d %d", len(a), a[0])
    return 0
```

| | built? | stdout | `len(a)`, `a[0]` |
|---|---|---|---|
| CPython | — | `2 20` | 2, 20 |
| **arm64** | yes | **`3 10`** | **3, 10** — nothing was removed |
| x86-64 | no: `unsupported statement DelStmt on the formal x86-64 path` | — | — |

```mojo
def main():
    var a = [10, 20, 30, 40]
    del a[1:3]
    printf("%d %d %d", len(a), a[0], a[1])
    return 0
```

| | built? | stdout | CPython |
|---|---|---|---|
| **arm64** | yes | **`4 10 20`** | `2 10 40` — the slice is still there |
| x86-64 | no (as above) | — | — |

A silent no-op is the outcome this project's own emitter docstring calls the
one thing a backend may not produce, and it is worse than the x86-64 refusal in
the only way that matters: it is invisible. The refusal is a diagnostic a reader
cannot miss, and this build prints numbers.

## Root cause: the branch that would lower it is unreachable

`formal/arm64_codegen.py:8056`'s `_emit_del` walks `stmt.targets`, and the two
arms that handle a subscript are **below an unconditional `continue`**:

```python
    if isinstance(target, F.SliceExpr):
        self._emit_del_slice(target)
        continue
        if isinstance(target, F.SubscriptExpr):      # ← unreachable
            ...
            self._emit_del_list_index(target)        # ← unreachable
            self._emit_del_dict_key(target)          # ← unreachable
            self._emit_del_slice_index(target)       # ← unreachable
            continue
        raise CodegenError(f"unsupported del target ...")
```

Every subscript target therefore falls off the end of the loop body and emits
**no instructions at all**, which is why the list is untouched: there is nothing
to run, and nothing that could fail.

**The author knew about this and fixed one third of it.** The docstring says the
multi-element-index refusal "belongs at the point where the shape is still
visible rather than in a branch nothing reaches", and
`M.multi_index_refusal_for` is indeed asked at the top of the loop. So
`del a[i, j]` is correctly REFUSED — for the stated reason — while `del a[i]`
and `del a[i:j]` reach the same dead block and do nothing. The refusal was
applied to the shape that was noticed and not to the two that were not.

So the four lowering helpers this backend already has —
`_emit_del_list_index`, `_emit_del_dict_key`, `_emit_del_slice`,
`_emit_del_slice_index` — are **dead code today**, and `grep` finds no other
caller. They were written, reviewed and then stranded behind one `continue`.

## What it costs, stated as the tool would measure it

**Zero files in any sweep rate, and that is the honest number.** `del <name>[`
appears 39 times in this repository and **0 times** in the stdlib tree
(`new-modular/Mojo/stdlib/std`), and the repository's own `.py` files are
`not-answerable/host-import` on this backend anyway, so lifting or refusing this
moves no `codegen coverage` number on either architecture. It is a correctness
defect in a construct, not a coverage row — which is exactly why a sweep cannot
find it and a case can.

## The exact next step

Two steps, and **step 1 is the one that matters today** because it turns a wrong
answer into a diagnostic and needs no new lowering at all:

1. **De-deaden and refuse.** Move the subscript arm out from under the
   `continue`, and while it is there decide which of the four shapes is
   lowered: with the block unreachable, `isinstance(target, F.SliceExpr)`
   matches a `del` target that the parser produces for no spelling this tree
   emits (`a[1:3]` parses as a `SubscriptExpr` whose index is a `SliceExpr`), so
   that arm may be reachable for something else or may be dead in its own right
   — measure that before assuming. Then, for every subscript shape that is not
   lowered in this pass, raise through a **shared** `model.del_refusal(target)`,
   the way `M.multi_index_refusal_for` already is, so the message is
   architecture-free and x86-64 can print the same words.
2. **Then lower it.** The four helpers exist; de-indenting them is most of the
   work. Two constraints to respect, both visible in their own code:
   `_emit_del_list_index` shifts elements left and decrements the count (an
   out-of-range index exits, as it does for a read), and the dict arm is a
   shift-delete over the key array, not a tombstone.
3. **x86-64, after arm64 is honest.** `DelStmt` is not in
   `formal/x86_64_codegen.py`'s statement dispatch at all, so its refusal is the
   generic "unsupported statement". Once step 1 gives the two backends one
   shared message, x86-64 raises it from the same helper and the two agree by
   construction rather than by luck.

## What is NOT the next step

Widening the check without lowering produces a **wrong** image, not a failing
one: with the block reachable, `del d["k"]` on a non-dict, or `del a[i]` where
`i` is not an integer, indexes whatever the value happens to be. That is why
step 1 refuses rather than emits, and why the case below is a value assertion
and not a `refuse:` row.

## The case that keeps this from coming back

`test_formal_x86_64_parity.py`'s `REFUSALS` shape fits step 1 exactly (both
backends must refuse with the same words), and step 2 needs a new positive
group with CPython as the oracle — the same file, which already builds and runs
both architectures and compares against CPython's stdout rather than a constant:

    del lst[i]        →  len 2, first element 20
    del lst[i:j]      →  len 2, first 10, second 40
    del d["k"]        →  len 1

Until one of those exists, `del a[i]` on arm64 is green in every suite in this
repository, which is the state this file was written to record.