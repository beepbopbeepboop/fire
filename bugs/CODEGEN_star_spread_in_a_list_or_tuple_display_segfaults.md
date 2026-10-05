# A `*expr` spread in a LIST or TUPLE display SIGSEGVs; a `*args` call collects one tuple

## Status: FIXED 2026-10-04, and the doc is KEPT (partly fixed, residue written down)

All three shapes named below were re-measured on this tree and all three are
right now, on BOTH pipeline modes:

| shape | was | is |
|---|---|---|
| `[0, *a, 9]` | `rc=-11` (SIGSEGV) | `[0, 1, 2, 9]` |
| `(0, *a)` | `rc=-11` (SIGSEGV) | `(0, 1, 2)` |
| `g(1, 2, x=3)` on `def g(*a, **k)` | `((1, 2), [('x', 3)])` | `a` really is `[1, 2]`; the `(1, 2)` bracket is a different bug, see the residue below |

Four mechanisms were changed, each because it was one of the four ways this
one shape could be wrong:

1. **`mojo/middle/types.py` gains `is_star_spread`**, the ONE predicate for
   "this display element is EXTENDED, not appended". Three sites had been
   re-deriving it and disagreeing; it lives beside the other AST-shape
   questions so `mojo/middle/` and `mojo/backend_gimple/` can both ask it.
2. **`_literal_slot_kinds` (`mojo/backend_gimple/emit_exprs.py`)** replaces two
   `''.join(_list_literal_slot_kind(...))` sites, one in the list lowering and
   one in the tuple lowering. It emits one byte per slot **up to the first
   spread**, which is what restored the runtime's own invariant (`_KindRow.
   kinds` is "one byte per slot") and removed the segfault: the spread used to
   contribute one byte carrying the OPERAND's kind (`'l'`, the nested-list
   slot), so `[0, *a, 9]` recorded `"ili"` for a four-slot list and slot 1 — the
   integer `1` inside `a` — was rendered through the nested-list arm as
   `(MojoList *)1`. Dropping just that byte is not enough and still crashes
   (`"il"` moves the `'l'` onto `a`'s first element), so the answer has to
   STOP at the spread.
3. **`_emit_star_spread`** replaces the two `mojo_list_extend` emissions with
   one, and fixes the two ways the operand could be wrong: a `char *` operand
   is a STRING spread and was handed to a `MojoList *` parameter
   (`mojo_str_chars` is the runtime's own answer to "what does iterating this
   string yield", already used by `mojo_iter_boxed_list`), and a non-pointer
   operand is coerced rather than passed at its own declared type.
4. **Both lowerings lower a spread element's OPERAND, not the `UnaryOp`
   wrapper.** `_lower_UnaryOp` reads `*x` as a POINTER DEREFERENCE for any
   operand type outside its container whitelist, so `(0, *a)` over a `str`
   emitted `_t2 = *a;` — the operand's first character — and extended the
   tuple with `(MojoList *)'a'`. Inside a display a `*x` element never means a
   dereference, and the display is the only place that knows that.
5. **`_infer_list_elem_type` (`mojo/middle/resolve_shared.py`)** no longer lets
   a spread's operand CONTAINER type into the element-type join (and does let
   in the operand's ELEMENT type when it is the literal's only evidence, or
   when the operand is a `str` and therefore provable). Measured: `[0, *a, 9]`
   joined `int` with `MojoList *`, looked heterogeneous, got no uniform repr
   reader, and the generic walker's "a zero slot is a boxed None" heuristic
   printed `[None, 1, 2, 9]`.

Regression tests, all through `test_gimple_matches_cpython` on both pipeline
modes, in `test_gimple_runner.py`:
`gimple_star_spread_in_a_list_display_extends`,
`gimple_star_spread_in_a_tuple_display_extends`,
`gimple_call_star_args_collects_loose_arguments_once`.

### Why this doc is not deleted

Two residues are real, measured, and each has its own doc rather than being
folded in here:

* the generated repr walker's "any registered two-element list is a
  runtime-built pair" heuristic, which printed `[(1, 2)]` for an ordinary
  inner list `[1, 2]` — that is where the third shape's `(1, 2)` bracket came
  from. FIXED 2026-10-04 (`work/bugs7-1`): the predicate now asks
  `mojo_is_tuple`, which is what `mojo_mark_as_tuple` records at every real
  pair site, with the length left as a cheap guard in front of it; pinned by
  `test_gimple_runner.py`'s `gimple_two_element_list_is_not_a_pair`, which
  holds every real pair shape (tuple display, tuple beside a plain list,
  `enumerate`, `dict.items()`) in the same program. The vararg PACKING that
  the third shape is really about was already correct and is asserted through
  `len(a)` and `sorted(a)`; a test that pinned it through the printed tuple
  would have been pinning this other bug.
* `bugs/CODEGEN_a_star_spread_of_a_string_beside_its_own_slots_prints_its_int_
  zero_as_none.md` — `(0, *'ab')` prints `(None, 'a', 'b')` where CPython
  prints `(0, 'a', 'b')`. `[*'ab']` alone is right. Making the mixed spelling
  right needs a RUNTIME-LENGTH kinds string, which is a change to the runtime's
  private kinds table (with `mojo_list_repeat` as the worked precedent) and
  was deliberately not smuggled in behind a codegen fix.

## What I ran (the original measurement)

Each compiled with `test_gimple_runner.py`'s own
`compile_mojo_to_gimple_exe`, run, and compared with CPython on the same text.
One program per run, because the runner spawns a `gcc -fgimple` per case and
running several in one process made the harness itself fall over.

## What I saw

    # list_spread
    def f(a: list) -> list:
        return [0, *a, 9]
    print(f([1, 2]))
    compiled rc=-11 (SIGSEGV)   cpython: [0, 1, 2, 9]

    # tuple_spread
    def f(a: list) -> tuple:
        return (0, *a)
    print(f([1, 2]))
    compiled rc=-11 (SIGSEGV)   cpython: (0, 1, 2)

    # call_star_args
    def g(*a, **k):
        return sorted(a), sorted(k.items())
    print(g(1, 2, x=3))
    compiled rc=0 out="((1, 2), [('x', 3)])"   cpython: "([1, 2], [('x', 3)])"

Three shapes, and the third is the informative one: `g(1, 2, x=3)` bound `a`
to `((1, 2),)` — the compiler collected the loose arguments into ONE tuple
and put THAT tuple in the varargs list — so `sorted(a)` sorted a one-element
list and printed the tuple inside it. `**kwargs` is correct in all three, so
this is the `*` side alone.

The interpreter has all three right: `myinterpreter.py`'s
`eval_ListLiteral` / `eval_TupleLiteral` both call
`_spread_operand(e, "*")` and `extend`/`result.extend`. The parser's
convention is the same one the `**` case uses — a `UnaryOp(op='*',
operand=<iterable>)` element in the literal's `elements` — and
`eval_SetLiteral` has the identical `update` shape.

## Why it matters more than a segfault on a test program

A SIGSEGV at exit -11 with no output is the worst failure shape this codebase
has: `test_gimple_runner.py`'s cases are the only thing standing between a
`[*a]` in real source and a crashed artifact, and a list/tuple display with a
spread is ordinary Python (`[*items]`, `(head, *rest)`).

## Exact next step

The sibling that was just fixed gives the shape. `_lower_dict_literal` now
asks `_dict_literal_spread_operand(key_expr)` and merges with
`mojo_dict_update`; the three sites to mirror it are

1. the list-display lowering (`_lower_list_literal` / `_emit_container_new`'s
   list caller in `mojo/backend_gimple/emit_exprs.py`) — merge with
   `mojo_list_extend(res, spread)`,
2. the tuple-display lowering, same helper, and
3. the CALL path — `_lower_named_call`'s / `_lower_struct_method_call`'s
   handling of a `UnaryOp(op='*')` argument. `_lower_UnaryOp` is supposed to
   pass an already-packed `MojoList *` through unchanged (the comment at
   `emit_calls.py` around `_call_has_spread` says so), but `g(1, 2)` has no
   spread in the SOURCE, so the loose arguments are being packed once as a
   tuple and then collected again. Compare against
   `_pack_vararg_trailing_params` (`emit_calls.py`), which is the one place
   that already reasons about this.

`mojo_list_extend` is the helper the comprehension path already uses
(`emit_exprs.py:5094`, `:5556`), so the runtime side needs nothing new.

A `test_gimple_runner.py` case per shape, in the same style as
`test_gimple.py`'s `dict_literal_star_star_pair_merges_instead_of_storing`
(asserted against CPython's stdout on both pipeline modes), is what should
pin all three.