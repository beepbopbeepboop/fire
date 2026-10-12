# A container ELEMENT of a comprehension needs a per-iteration blob base, and
# that is a change to how a comprehension's RESULT is addressed

**Area:** FORMAL, both backends — `formal/arm64_codegen.py` and
`formal/x86_64_codegen.py`'s `_emit_comprehension` / `_emit_list` / `_emit_dict`,
and the frame blob allocator they share (`_reserve_blob`, `_list_cursor`).

**Status: the FLAT-container half of the relocation LANDED (2026-10-06), and the
NESTED-COMPREHENSION element landed 2026-10-12 by a different route than the
relocation §"What the obvious fix actually is" describes — both on BOTH
backends. A comprehension whose element is a container literal is per-iteration,
and so is an element that is ITSELF a comprehension whose result is flat: the
nested comprehension's FINISHED result blob is byte-copied into a slot of a
`cap`-sized array, so the aliasing is gone and the exit-1 count-overrun with it
(`[[x + y for x in [1, 2]] for y in [10, 20, 30]]` answers `63`, CPython's
answer, where it exited 1). What is STILL refused is an element whose
per-iteration materialisation would carry the ADDRESS of a container the element
position BUILT — a list of lists, a slice, a constructor call, and a nested
comprehension whose own element builds a container — which is the shallow-copy
boundary and is unchanged. Read "What landed 2026-10-12" first; the paragraphs
under the 2026-10-06 section price what is left.

## What landed 2026-10-12: the nested comprehension's RESULT is copied, not relocated

**The doc's own framing was that a nested-comprehension element needs the
nested `res_offset` to become a run-time register address, because the nested
result is reserved by `_emit_comprehension` before the walk. It does not.**
The nested result is a complete `[count][element…]` blob in the frame by the
time the element site is reached (its comprehension has finished), so the
element site can do exactly what it already does for a flat container literal:
copy the blob into a per-iteration slot and hand the COPY to
`_compr_append_elem`. The only difference is the size — the flat case's size is
the ledger delta (the literal's own reservation), while a nested comprehension's
delta also carries its iterables, so the emitters read the size the nested
comprehension RECORDED when it reserved its result (`_last_compr_result_size`,
set at the one `_reserve_blob` call in each `_emit_comprehension`). The copy is
sound under the same rule the flat predicate states, one level in, which is what
`model.comprehension_result_is_flat` decides: the nested result's WORDS must be
scalars or deliberately shared references, never the address of a container the
element position built. It recurses through a nested comprehension and rejects a
container-building element, so a nested comprehension over a container element
stays refused (pinned by
`a_nested_comprehension_over_a_container_element_is_refused`).

**Why this is not the relocation the section below priced, and why that is
fine.** Nothing in `_emit_compr_gen` changes: `res_offset` stays a compile-time
constant, every `_compr_append_elem`/`_compr_append_pair` base recompute is
untouched, and no register has to survive `_emit_expr`. The per-iteration
storage is the ARRAY, indexed by the outer result count, which the flat case
already introduced; this only teaches it a second blob size and a second source.

**Measured, both architectures, after** (the same program on arm64 and x86-64):

| program | CPython 3.14 | before | after |
|---|---|---|---|
| `[[x + y for x in [1, 2]] for y in [10, 20, 30]]`, sum of `v[0]` | `63` | refused (was `93`, exit 1 before the refusal) | **`63`** |
| `[[x * y for x in [1, 2]] for y in [3, 4]]`, `r[0][1] r[1][1]` | `6 8` | refused | **`6 8`** |
| three-level `[[[z for z in [1, 2]] for y in [1]] for x in [1, 2]]`, `r[i][0][1]` | `2 2` | refused | **`2 2`** |
| `[[x + y for x in [1, 2] if x > 1] for y in [10, 20, 30]]`, `r[i][0]` | `12 22 32` | refused | **`12 22 32`** |
| `[{k: k + y for k in [1, 2]} for y in [10, 20, 30]]`, `sum(d[1])` | `63` | refused | **`63`** |
| `[[[z] for z in [1]] for y in [10, 20, 30]]` (element builds a container) | — | refused | refused (recursion boundary) |

**What is left, and it is the genuine runtime-blob-base relocation below:** an
element whose per-iteration storage must carry a container built INSIDE it — the
list of lists (`[[y]]`), a slice (`a[0:2]`), a constructor call, and the
dict-VALUE that opens a container (`{k: [v for v in …] for k in …}`, whose value
site is the dict branch's `_refuse_an_element_blob`, not
`_materialize_compr_element`). Copying those shallowly would carry an inner
ADDRESS, so they keep the refusal.

## What landed 2026-10-06: the flat-container element is per-iteration

**The refusal was replaced by real per-iteration storage for the shapes a byte
copy makes sound, on both backends.** `model.comprehension_element_is_flat_container`
is the one predicate: the element is a list / tuple / set / dict literal and
NOTHING inside it builds a second container (a nested literal, a comprehension, a
slice or a call). Both emitters' `_materialize_compr_element` then reserve a
`cap`-slot array beside the element's own scratch blob and, at the element site,
`memcpy` the element's blob into slot `i`, where `i` is the result blob's count
word — the number appended so far, so the append that follows stores the copy and
not the scratch. The predicate is shared so the two architectures cannot disagree
about which elements are representable; the message stays
`model.comprehension_element_blob_refusal` for the shapes that are not.

| program | CPython 3.14 | before | after |
|---|---|---|---|
| `[[y, y + 1] for y in [10, 20, 30]]`, `r[i][1]` | `11 21 31` | refused | **`11 21 31`** |
| `[(y, y + 1) for y in [10, 20, 30]]`, `r[i][0]` | `10 20 30` | refused | **`10 20 30`** |
| `[{y, y + 1} for y in [10, 20, 30]]`, `r[i][0]` | `10 20 30` | refused | **`10 20 30`** |
| `[[x + y for x in [1, 2]] for y in [10, 20, 30]]`, sum `v[0]` | `63` | refused | refused (runtime base) |
| `[[[y]] for y in [10, 20, 30]]` (a list of lists) | — | refused | refused (shallow copy) |
| `[a[0:2] for y in …]` (a slice) | — | refused | refused (shallow copy) |
| `[[x + y for x in [1, 2]] for y in [10]]` (one outer iteration) | `11` | `11` | `11` |

**Why the shallow copy is sound exactly here, and only here.** The copy carries
the element blob's WORDS; a nested container would be carried as its ADDRESS, so
every iteration's outer container would point at one inner object — the same
defect one level down. A NAME is deliberately not a container: `[a, b]` over two
outer lists copies the outer list and shares `a`/`b`, which is what CPython does.
That is why the predicate recurses rather than keying on the element's node type.

**Pinned in `test_formal_run.py`** (`COMPREHENSION_ELEMENT_CASES`): three
build-and-run rows that read `r[i][j]` (the CONTENT, not `len`, because three
copies of the last iteration and one element per iteration have the same count),
the nested / dict-value / list-of-lists refusals, and the one-iteration guard.

**The machinery is not in the wrong place, and that is what this doc
establishes.** There is no per-element-site allocator to use: a
comprehension's element site reserves through the ONE sequential frame ledger
(`_reserve_blob` against `_list_cursor`), and it runs once at COMPILE time while
running N times at RUN time — so any reservation it makes is one allocation for
N iterations. Measured on both architectures.

## What landed (2026-10-05): the refusal, and the ledger measurement that asks it

**The question is asked of the emitters' OWN ledger, not of a predicate.**
`_emit_compr_gen`'s leaf — the one place an element is emitted — now takes
`self._list_cursor` either side of the element's emission and refuses when the
delta is not zero. A container's blob is reserved by the `_reserve_blob` family
through that one variable, so the delta *is* "this element allocated something",
and the set of allocating constructs is whatever the emitters allocate rather
than a list of node types kept in step with them by hand. A hand-kept list would
be a second copy of `_reserve_blob`'s callers, and the defect this class is about
— a construct nobody remembered — is exactly the defect such a list grows.

`_refuse_an_element_blob` is one small method in each backend (both ask
`model.comprehension_element_blob_refusal`, so the two architectures cannot
refuse this differently), and `model.expr_spelling` gained a `Comprehension`
arm because the nested case quoted `Comprehension` — the AST type name — in a
diagnostic whose whole job is to name the line the reader has open.

**`cap <= 1` is exempt, and that is soundness rather than politeness.**
`_compr_cap` is an UPPER BOUND on the iteration count, so `cap == 1` means the
body runs at most once and one shared blob is then shared by nothing. The sibling
document's acceptance row *"the first program with ONE outer iteration, `for y in
[10]`"* keeps answering `11`, and
`test_formal_run.py::a_one_iteration_comprehension_element_container_still_builds`
is the row that says so.

**Measured, both architectures, after:**

| program | CPython 3.14 | before | after |
|---|---|---|---|
| `[[y, y + 1] for y in [10, 20, 30]]`, `r[0][1] r[1][1] r[2][1]` | `11 21 31` | `31 31 31` | **refused** |
| `[[x + y for x in [1, 2]] for y in [10, 20, 30]]`, sum of `v[0]` | `63` | `93`, exit 1 | **refused** |
| `[[x + y for x in [1, 2]] for y in [10]]`, sum of `v[0]` | `11` | `11` | `11` (the `cap <= 1` exemption) |
| `[i + j for i in [1, 2] for j in [3, 4]]`, flat, two generators | `4 5 5 6` | `4 5 5 6` | `4 5 5 6` |
| `[x + y for x in [1, 2]]` as a statement in a `for` body | `66` | `66` | `66` |

**What it costs, precisely.** One row of the sibling document's acceptance set:
*"an element that does not depend on the loop variable (→ 3, correct today only
because the shared blob happens to hold the right value)"*. That row is refused
now, and it is the row the sibling document itself marks as "correct by
coincidence — … which is why the coincidental row must not be mistaken for a
pass". The other two acceptance rows survive, and so does the whole of
`test_formal_run.py`'s `nested_comprehension_in_a_generator_iterable`, whose
subject is the `_ci{d}`/`_cb{d}` DEPTH agreement for a comprehension reached
through a generator's ITERABLE — an iterable allocates in the ITERABLE, not in
the element, which is the distinction the refusal is drawn on. That row's fourth
shape (a dict comprehension whose values are comprehensions) moved into
`COMPREHENSION_ELEMENT_REFUSALS`, so the shape is still covered and is now
covered by an assertion stronger than "builds and answers".

**The coverage census, and it is ZERO on this tree — which corrects the sibling
document's "6 of the 610 stdlib modules".** Measured 2026-10-05 over 443
`*.mojo` files (this worktree plus the 252 files of
`../new-modular/Mojo/stdlib/std`, `.tmp`/`.git` pruned): **0 files** hold a
comprehension at all, live. The three the grep finds
(`std/python/numpy.mojo`, `formal/hostmods/textwrap.mojo`,
`formal/hostmods/ast.mojo`, `mojo_failures.mojo`) are docstring examples inside
`>>> [c for c in range(128) …]`, which the parser throws away. So the sibling
document's "6 of the 610" counted prose. **That is why the refusal was
affordable here and it is also why it must not be read as evidence that the
construct is rare** — a corpus that writes no comprehension measures nothing
about it, and the next module that writes one pays this refusal.

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

**The second of those three is the ONE the refusal cannot have**, and it is
stated here rather than discovered by the next reader: with the wrong answer
gone there is nothing left to distinguish it from the first row, so a refusal at
this position takes it. The other two survive and are pinned by
`test_formal_run.py::a_one_iteration_comprehension_element_container_still_builds`
and the `nested_comprehension_in_a_generator_iterable` /
`comprehension_body_is_not_a_container_position` rows.

**A refusal is the alternative and it is cheap**, which is the trade the other
doc names and measures (6 of the 610 stdlib modules contain a comprehension
whose element opens a list literal — **and that count is wrong**: see "What
landed" above, where the measured figure is 0 files with any comprehension in
them, because the six are docstring examples). Refusing
`model.comprehension_element_is_per_iteration`-shaped elements by name is a
`model.py` predicate plus one call site per backend and needs no allocator
change at all — a wrong element list is worse than a refusal, because a caller
that appends to the comprehension's result gets a list whose elements are all
one object, which is silent in a way a missing feature is not. **Whoever takes
this should decide between the refusal and the relocation before writing the
relocation**, and the census above is what makes the refusal affordable.
**Decided: the refusal.** The predicate is `model.comprehension_element_blob_refusal`
and it is asked of the ledger rather than of the node type; the census that made
it affordable is the measured 0 above.

## Reproducing

    $ export PATH=/opt/homebrew/bin:$PATH
    $ cat .tmp/ds/alias.mojo      # the program above
    $ python3 .tmp/ds/alias.mojo                        # 63
    $ python3 tools/memslot.py --gb 8 --label t -- \
          python3 fire.py build --formal --no-prove -o .tmp/al .tmp/ds/alias.mojo
    Built: .tmp/al  [arm64/macho]
    $ .tmp/al                                          # 63, and the same on --backend=x86_64
    # …and the shapes that are STILL refused, in one line each:
    $ python3 tools/memslot.py --gb 8 --label t -- \
          python3 fire.py build --formal --no-prove -o .tmp/ll .tmp/ll.mojo
    build: a comprehension in main: the element `[[y]]` opens a container, …
    $ grep -n "def _reserve_blob" formal/arm64_codegen.py      # the ONE ledger
    $ grep -n "def _refuse_an_element_blob" formal/arm64_codegen.py
    $ grep -n "def _compr_append_elem" formal/arm64_codegen.py # where offset goes

and the tests, no builds for the census:

```sh
python3 test_formal_run.py a_comprehension_element_that_is_a_list_literal_is_per_iteration \
  a_comprehension_element_that_is_a_tuple_literal_is_per_iteration \
  a_comprehension_element_that_is_a_set_literal_is_per_iteration \
  a_nested_comprehension_as_the_element_is_per_iteration \
  a_dict_comprehension_as_the_element_is_per_iteration \
  a_dict_comprehension_whose_value_opens_a_container_is_refused \
  a_list_of_lists_as_the_element_is_refused \
  a_nested_comprehension_over_a_container_element_is_refused \
  a_one_iteration_comprehension_element_container_still_builds \
  nested_comprehension_in_a_generator_iterable \
  comprehension_body_is_not_a_container_position
python3 test_refusal_taxonomy.py
```