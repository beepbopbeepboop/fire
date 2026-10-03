# FORMAL_arm64_set_union_result_blob_has_the_wrong_count: `a | b` iterates correctly and hands back a blob that says 5 where CPython says 3

**Area:** FORMAL / codegen. Found 2026-10-03 on `work/formal12-x86-parity-audit`
by the arm-vs-x86 construct audit. **NOT FIXED** — it is a wrong answer in
`formal/arm64_codegen.py`'s `_emit_set_union`, it is not an x86-64 parity gap,
and this branch's subject is the sweep probe and the parity corpus. Nothing in
`bugs/` records it and no claim names it.

## What was run

    $ cat > u.mojo
    def main():
        var c = {1, 2} | {2, 3}
        printf("n=%d e=%d,%d,%d", len(c), c[0], c[1], c[2])
        return 0

    $ python3 fire.py build --formal --no-prove --backend=arm64 -o u.arm64 u.mojo
    $ ./u.arm64
    n=5 e=1,2,0            # CPython: n=3 e=1,2,3

Four shapes, all exit 0, all with the same wrong answer:

| source | arm64 | CPython |
|---|---|---|
| `len({1,2} \| {2,3})` | 5 | 3 |
| `{1,2} \| {2,3}` then `c[0],c[1],c[2]` | `1,2,0` | `1,2,3` |
| the same after a `for v in {1,2} \| {2,3}` loop (which is RIGHT) | `4,5,0` | `4,5,6` |
| `a` and `b` as set LOCALS, `c = a \| b` | `n=5 e=1,2,0` | `n=3 e=1,2,3` |

**What is NOT wrong, and is why this is worth a careful pass rather than a
patch.** The same emitter answers correctly when the result is ITERATED:

    var s = 0
    for v in {1, 2} | {2, 3}:
        s += v
    printf("%d", s)        # arm64 6, CPython 6

which is what `test_formal_run.py`'s `set_union_is_a_set_on_arm64_and_refused_on_
x86_64` pins, and that case passes. So the element SELECTION is right (the
dedup scan drops `3` from the left and keeps `2` from the right) and the count
field the result blob hands to a `len` or a subscript is not.

The two facts together are what a for-in walk can survive and a `len` cannot: a
walk that reads elements until it hits something else gets the right three, and
a `len` that reads `[base + 0]` gets a number nothing wrote. **A case that only
iterates the result is the one shape that cannot see this**, which is why the
existing case is green.

## The second thing this makes false, in a message users read

`formal/model.py::set_union_refusal` — the shared refusal text — ends with

> Use `+` if a concatenation is what you want, or build the union with an
> explicit membership test. **arm64 lowers this operator correctly**

and x86-64 prints exactly that when it refuses `a | b` (measured, verbatim in the
transcript above). It is false in the shape above. The clause is also the whole
reason that message is an ANSWER rather than a shrug (its own docstring says so:
"it says which backend does lower it, because 'this is not supported' is the
answer that sends a reader looking for a spec when the answer is an emitter"), so
the fix is not to delete it — it is to make it true, and it becomes true the
moment the count is right. **Left alone deliberately**: editing shared text to
match an unfixed bug would have to be reverted when the bug is fixed, and
`test_formal_run.py` and the parity file both key on that wording.

## The next step

1. Read `_emit_set_union` (`formal/arm64_codegen.py:8505`) against
   `_emit_list_concat` beside it, which the comment says had the same class of
   bug once ("its left-copy loop was leaving on its first iteration for the same
   reason concat's did"). The question is where the result blob's COUNT is
   written: `_compr_append_elem` is the shape that keeps `[base]` and `[base+8*k]`
   in step, and a union that writes elements by hand has to do the same for the
   count. Measured starting point: `n=5` for a three-element union, so the count
   is being written from something other than the number of appended elements —
   `_blob_est`, which returns 8 for a literal operand, is the first thing to
   check.
2. Before any of that: `printf("%d", len(c))` is the smallest reproduction and
   it must go in `test_formal_run.py` next to the existing `SET_UNION_CASES` entry
   as a second row — "the same union read as a VALUE", which the existing row,
   by iterating it, structurally cannot fail on.
3. x86-64 needs nothing: its refusal is correct and is already pinned by that same
   case. If arm64's union becomes right, `set_union_refusal`'s clause becomes
   true with no edit at all.