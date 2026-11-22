# GIR stage 5b: carrying `Box` through a copy needs the bind-side fact split

Stage 5b step 4 landed the one-record-per-temp storage (`mojo/middle/valueinfo.py`):
a `ValueInfo` per temp with `kind` `Int / Erased(T) / DynWord / Box / Plain` and
the flags `Tagged` / `SlotKinds` / `BoxedContainer`, with the six historical
sets as derived read-only views. `WordFacts.carry` carries `dyn`,
`int_word`, `slot_kinds` and `boxed_container`; a copied `Box` becomes a
`DynWord` (the read-side half: "the runtime decides the kind") but is not
recorded as a `Box`.

## Still open

Carry the `Box` kind (and its `Tagged` flag) itself. `_boxed_vals` used to mean
two things, and the record separates them:

- READ side: "this word's kind is a runtime fact; render it by kind"
  (`mojo_repr_boxed`, `mojo_cstr_or_int_str`, `mojo_truthy_word`). True of
  every copy of a box, and `DynWord` already says it.
- BIND side: "this word is a heap box that `mojo_box_word` must unbox" — the
  representation decision `emit_stmts._gen_stmt_AssignStmt` takes for a NAME.
  It also reads the value's `Tagged` flag (`_keep_tagged_box`,
  `_tagged_bind`), and a tagged value stored into a pointer-typed name is a
  hard REFUSAL.

A pass-through temp is not a name anybody bound, so the bind-side fact must not
travel with a copy.

## Measured 2026-11-21

With `WordFacts.carry` promoting the destination to `KIND_BOX` (+ `Tagged`):

- `mojo/middle/infra_infer.py` (a self-host-closure module) refuses:
  `'_pn2': a name bound to a container or pointer value (container value of C
  type 'MojoList *') elsewhere in this function and also to a tagged generator
  word here cannot also hold a value of another C type; no representation
  holds both; refused`. Source line: `_pn2 = _chosen.get('param_names') or []`.
  The `or` merge lowers through `_copy`; the dict-get arm is a tagged box
  (rendered by kind); the tag reaches the merge temp, and the next statement
  stores that temp into a `MojoList *` local.
- Also refused: `mojo/backend_gimple/emit_stmts.py` (`_nbytes` bound to a
  tagged yield and to a str) and `elaborate.py` (`cands`, list vs tag).
- Carrying `Box` WITHOUT `Tagged` builds and is C-identical on
  `tools/pydiff_corpus`, but it only feeds the `may_be_box -> mojo_box_word`
  unboxing arm at a bind (which strips a str/None/bool box to its plain word),
  so it is a precision loss, not a gain.
- Corpus C with the landed (non-Box) carry: 285 programs, 9 differ from the
  pre-record backend, all already WRONG/CRASH (4 box-render, 4 truthiness, 1
  isinstance fold). No CPython verdict changes. `is_dyn` answering true for a
  `Box` is what changes those 9: a box may also be a CONTAINER pointer
  (`mojo_list_get_boxed` returns one), so an `or` merge of a boxed container
  is lowered as an `int64_t` word iterated through the runtime's kind dispatch
  instead of as the typed pointer. Safe but less precise; the split below is
  also where a Box that came from a container read can be narrowed again.

## Next step

1. Add a bind-side flag to `ValueInfo` (e.g. `FLAG_BIND_BOX`, "a NAME holding
   this needs the box") that `carry` does NOT move, and have `mark_boxed` /
   `mark_tagged` set it only where a name is being represented as a box.
2. Move the bind-path readers onto it: `_keep_tagged_box`, `_tagged_bind`,
   `_boxed_get_into_container`, `_for_copy`, `_call_tagged` and the
   `_boxed_vals`-as-needs-unbox reads in `emit_stmts`/`stmts_shared`/
   `emit_infra`; leave the renderers on `may_be_box`.
3. Then let `carry` promote `_d.kind = KIND_BOX` and the `Tagged` flag, and
   re-run the per-program C hash over `tools/pydiff_corpus` plus the 60
   compiler modules (the same measurement as the record's landing).
4. Flip `test_gimple.py`'s `test_word_facts_one_record_per_temp` "Box does not
   travel" assertions to the new answer, with the measured diff in the status.

## Done when

`WordFacts.carry` carries `Box`/`Tagged`; `mojo/middle/infra_infer.py`,
`mojo/backend_gimple/emit_stmts.py` and `elaborate.py` still compile (a
per-module `compile_to_gimple(..., do_imports=False)` is enough); no corpus
program changes its CPython verdict; and the record test's carry-boundary
assertions state the new fact. Delete this doc in that commit.
