# A container ELEMENT of a comprehension needs a per-iteration blob base, and
# that is a change to how a comprehension's RESULT is addressed

**Area:** FORMAL, both backends — `formal/arm64_codegen.py` and
`formal/x86_64_codegen.py`'s `_emit_comprehension` / `_emit_list` / `_emit_dict`,
and the frame blob allocator they share (`_reserve_blob`, `_list_cursor`).

**Status: NOT FIXED, and this is the measurement of WHY** — the second half of
`bugs/FORMAL_a_comprehension_element_container_aliases_every_iteration.md`, whose
"next step" says *"if it is a slot reserved per element SITE (as
`frame_slots`/the local allocator would do), the fix is a per-iteration
materialisation or a copy at the append"* and that the machinery "is being used
in the wrong place". **The machinery is not in the wrong place, and that is what
this doc establishes.** There is no per-element-site allocator to use: a
comprehension's element site reserves through the ONE sequential frame ledger
(`_reserve_blob` against `_list_cursor`), and it runs once at COMPILE time while
running N times at RUN time — so any reservation it makes is one allocation for
N iterations. Measured on both architectures.

## What was run

    $ cat .tmp/ds/alias.mojo
    def main():
        s = 0
        for v in [[x + y for x in [1, 2]] for y in [10, 20, 30]]:
            s = s + v[0]
        print(s)
        return 0
    main()
    $ python3 .tmp/ds/alias.mojo
    63
    $ python3 fire.py build --formal --no-prove -o .tmp/al --backend=arm64 \
          .tmp/ds/alias.mojo && .tmp/al
    93                      # 31 × 3 — every element is the SAME list

(identical on `--backend=x86_64`; the full table is in the other doc, and every
row there reproduces.)

## What the obvious fix actually is, measured

The natural implementation — reserve `cap` slots of the element's own size and
index them by the iteration counter — **works for a list-literal and a
dict-literal element, and does not work for a NESTED COMPREHENSION element,
which is the doc's own reproducer.** Both were built and measured on arm64:

| element of the outer comprehension | after the array fix |
|---|---|
| `[[y, y + 1] for y in [10, 20, 30]]` (a list literal) | correct |
| `[{k: 1} for k in d]` (a dict literal) | correct |
| `[[x + y for x in [1, 2]] for y in [10, 20, 30]]` (a nested comprehension) | **still 93, and exits 1** |

**Why the third row is different, and it is structural.** A list literal's own
allocation happens *inside* `_emit_list`, so making it per-iteration is a change
to `_emit_list` alone: skip `_reserve_blob`, and recompute the base as
`frame + array_base + result_count · stride`. The result count is the index,
because the element is built before the append that increments it.

A nested comprehension's allocation is **not** inside the element's lowering —
it is the comprehension's own `offset`, reserved by `_emit_comprehension` before
the walk, and then passed down as `res_offset` to `_emit_compr_gen`, which hands
it to `_compr_append_elem`/`_compr_append_pair` to recompute a base for every
store. So relocating it means `res_offset` stops being a compile-time constant
and becomes a **register holding a run-time address**, and every one of those
recomputes has to read that register instead of calling `_emit_list_base`.

**That is the whole of what is left, and it is not a patch.** Concretely, on
each backend:

1. `_emit_comprehension` must be able to say "my result lives at a slot of my
   parent's array" and then keep that address in a register for the whole walk,
   through `while_counter` frames and every pending-finally push/pop;
2. `_compr_append_elem`, `_compr_append_pair`, `_emit_compr_gen`'s base
   recomputes, and the final "materialize the result address" must all take that
   register rather than an offset;
3. the register has to survive `_emit_expr` on the element — the same clobber
   problem `_emit_block_store`'s "recompute the base per store" docstring is
   about, which is why the register discipline here is not free.

## What was tried and withdrawn

The arm64 half of steps 1-3 was written (a `_compr_elem_arrays` map,
`_reserve_comprehension_element_array`, `_emit_compr_elem_base`, and the
`_emit_list`/`_emit_dict` hooks) and **withdrawn rather than landed unverified**:

* it is half the change — x86-64's `_compr_append_elem`/`_emit_compr_gen` are
  separate code, so landing arm64 alone would make the two architectures
  disagree about a comprehension's result address;
* the two rows it did fix are covered by the OTHER doc's table as cases a fix
  must not break, and they only pass *because* the nested row is broken in the
  same build — so there is no partial landing that is a partial fix;
* one real defect in it is worth recording: `_blob_est` counts **elements**, and
  every blob is `[count][element…]`, so a slot sized `8 * _blob_est(...)` is one
  word too small and the third iteration's count header overwrote the second
  iteration's last element — the reproducer exited 1 at the append guard until
  the `1 +` was added.

## The exact next step

Steps 1-3 above, on **both** backends, with the whole of the other doc's table
as the acceptance set — and in particular its three rows that a fix must NOT
break, which are the reason a partial landing is not one:

* one outer iteration (`for y in [10]` → 11),
* an element that does not depend on the loop variable (→ 3, correct today only
  because the shared blob happens to hold the right value),
* a two-generator FLAT comprehension (`[i + j for i in [1,2] for j in [3,4]]` →
  20, which is B1's shape).

**A refusal is the alternative and it is cheap**, which is the trade the other
doc names and measures (6 of the 610 stdlib modules contain a comprehension
whose element opens a list literal). Refusing
`model.comprehension_element_is_per_iteration`-shaped elements by name is a
`model.py` predicate plus one call site per backend and needs no allocator
change at all — a wrong element list is worse than a refusal, because a caller
that appends to the comprehension's result gets a list whose elements are all
one object, which is silent in a way a missing feature is not. **Whoever takes
this should decide between the refusal and the relocation before writing the
relocation**, and the census above is what makes the refusal affordable.

## Reproducing

    $ export PATH=/opt/homebrew/bin:$PATH
    $ cat .tmp/ds/alias.mojo      # the program above
    $ python3 .tmp/ds/alias.mojo                        # 63
    $ python3 tools/memslot.py --gb 8 --label t -- \
          python3 fire.py build --formal --no-prove -o .tmp/al .tmp/ds/alias.mojo
    $ .tmp/al                                                  # 93
    $ grep -n "def _reserve_blob" formal/arm64_codegen.py      # the ONE ledger
    $ grep -n "def _compr_append_elem" formal/arm64_codegen.py # where offset goes