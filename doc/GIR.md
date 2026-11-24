# GIR: a typed IR for the gimple backend

Status (2026-11-23): stages 0, 1, 2a, 2b, 3a, 3b, 3c, 5a, 5b and 6 are landed, and stage 7 T1-T6 are done. Stage 4
(types) and stage 5c (None) are the open stages. This file is the plan and the rules. Read it
before changing anything under `mojo/backend_gimple/` or `mojo/ir/`.

## 1. What is wrong today (measured 2026-11-13)

The gimple backend is `gimple_codegen.py` + `mojo/backend_gimple/*.py` +
`mojo/middle/*.py`: 148,753 lines, 2,591 functions. GCC's own C front end
needs about 2,700 lines to read the same GIMPLE text (`c/gimple-parser.cc`).

- **A type is a Python string** holding C spelling. There are 1,652 inline
  `== 'int64_t'`-style comparisons, 354 `.endswith(' *')` pointer tests, and ten
  different hand-written "scalar integer type" sets.
- **`int64_t` means four things**: a real integer, a pointer stored in an
  integer ("erased"), a dynamic word of unknown kind, and a tagged box. Which
  one a value is lives in about 57 dictionaries on `gen` keyed by the temp's
  NAME (`_elem_types`, `_boxed_vals`, `_dyn_word_vals`, ...). A copy
  `x = y` must copy up to 57 entries by hand; forgetting one is 15% of sampled
  backend bug fixes.
- **A statement is a string.** 2,850 call sites build text
  (`gen._emit(f"  {t} = mojo_list_len ({v});")`). Facts are then recovered by
  reading the text back: `_emit_raw` finds ` = mojo_` to decide ownership,
  `startswith('return ')` to decide control flow, and a `try` frame slices the
  value out of a `return` line.
- **Twelve functions hold 26% of the code** (`gen_module_impl` is 15,397 lines).

What is NOT wrong, also measured: the emitted text is type-consistent at the C
level. Over 188 generated files (726,918 statements) the checker finds 191
type findings, all of them call arguments. Explicit cast statements (106,000 in
`fire.ci`) make every copy legal. So the type-unsafety is in how the generator
REASONS, not in a flood of illegal statements. `_KNOWN_SIGS` (606 runtime
signatures, hand-written) also agrees with `runtime/*.h` on all but 2 entries.

### The call-argument hole (proven)

GCC verifies only functions tagged `__GIMPLE` (top-level `def`s are emitted
untagged, as plain C), and even in a tagged function it never checks a call's
arguments. A mismatched argument is passed unconverted:

    __GIMPLE int64_t g (void) {
      int _t1; int64_t _t2;
      _t1 = getint ();          /* returns -5 */
      _t2 = show (_t1);         /* show (int64_t) */

`show` receives 4294967291 at `-O0` and 9223372032559808507 at `-O2`
(gcc-mp-15 15.3, arm64): no sign extension is emitted. An integer passed to a
`double` parameter arrives in the wrong register. Real instances in the
compiler's own output: `MojoString.byte_length` (`mojo_box_word (<int>)`) and a
`pow (2.0, <int64_t>)` in `myinterpreter.py`.

## 2. The target

    AST --lowering--> GIR (typed values, typed instructions) --printer--> text
                           |
                           +-- verifier (every function, every argument)

Four layers, in `mojo/ir/`:

| file | what | state |
|---|---|---|
| `types.py` | `Type` objects, interned. `trivially_convertible`, `mismatch_class`, `cast_is_legal` are the ONLY code that decides type compatibility | landed |
| `instr.py` | `Ex` (operand), `Instr` (statement), `Function`, `Module`, `Sig`. Ten statement shapes cover 98% of today's emission | landed |
| `verify.py` | type-checks a `Module`, returns `Finding`s with stable codes | landed |
| `reader.py` | TRANSITIONAL. Parses emitted `.ci` text and `runtime/*.h` into a `Module`, so the verifier can check today's string backend | landed |
| `build.py` | the builder the lowering code will call instead of `gen._emit(f"...")` | landed: `gen._emit` sites are 0; `raw` is the adapter for the rest |

Beside it, in `mojo/middle/`: `rt_sigs.py` (generated runtime signatures) and
`rt_call.py` (which scalar arguments need a conversion statement).

Rules that hold from now on:

1. **No new type-compatibility logic outside `mojo/ir/types.py`.** If you need
   to know whether two types match, call it.
2. **`types.py`, `instr.py`, `verify.py`, `build.py` must stay self-hostable**:
   plain classes, every field annotated in `__init__`, no closures, no lambdas,
   no `re`, no tuple unpacking, no `getattr`, no generators. `reader.py` is
   tool-side and may use anything; the compiler must never import it.
3. **Unknown is not `int64_t`.** The verifier never guesses: an undeclared name
   or unknown callee is counted in `Report.unknown` and not checked.
4. **A finding count may only go down.** `test_gimple_lint.py` holds the
   baseline.

## 3. How to use the checker

    python3 fire.py --dump x.mojo            # writes x.ci
    python3 tools/gimple_lint.py x.ci        # summary by finding code
    python3 tools/gimple_lint.py -v --code arg-int-widen x.ci
    python3 test_gimple_lint.py              # unit tests + the ratchet (10 s)

Finding codes are `<position>-<class>`:

| position | meaning |
|---|---|
| `copy` | `a = b;` |
| `op` | an operand of a binary operation or `?:` |
| `cmp` | the two sides of a comparison |
| `ret` | `return v;` against the function's return type |
| `arg` | a call argument against the callee's parameter |
| `cast` | `a = (T) b;` where `T` is not `a`'s type |
| `lit` | as above, but the operand is a literal of the wrong KIND |

| class | meaning |
|---|---|
| `int-widen` | narrower integer where a wider one is expected |
| `int-narrow` | wider integer where a narrower one is expected (truncation) |
| `int-sign` | same width, different signedness |
| `bool-int` | `_Bool` vs integer |
| `int-ptr` | integer vs pointer (the erased-pointer hazard) |
| `int-float` | integer vs floating point |
| `ptr-kind` | two different pointer types. GIMPLE allows it; GIR does not |

Plus `cmp-result` (a comparison stored into a non-`_Bool`), `cast-illegal`,
`arg-count`.

The fix for an `arg-*` finding is almost always the same: the call was spelled
as text. Route it through `gen._call_expr(ret, fname, [(ctype, value), ...])`
or `gen._emit_call(...)`, which coerce each argument to the declared parameter
type from `_KNOWN_SIGS`.

## 4. Stages

Each stage has a ratchet, so partial progress is safe to land and cannot
regress. Byte-identical `.ci` output over a corpus is the oracle for any stage
that is meant to be behaviour-preserving:

    # before and after the change, in two empty directories:
    for f in <corpus>; do python3 fire.py --dump $f; done ; diff -r before after

`tools/c_oracle.py check` is the same oracle for both backends, and it has TWO
corpora because one cannot see both printers: `tools/pydiff_corpus` (285
programs, compiled with the default coroutine backend, so no companion `.cpp` at
all) and `tools/cpp_corpus` (13 coroutine programs, compiled with `MOJO_CORO=cpp`,
where an empty companion is an ERROR). A `cpp_core.py`/`cpp_async.py` change
that leaves the first corpus identical and the second one changed is detected, so
stage 7 has an oracle before it has a builder.

- **Stage 0 (landed).** `mojo/ir` types, instructions, verifier, reader;
  `tools/gimple_lint.py`; `test_gimple_lint.py` registered as `gimple-lint`.
- **Stage 1 (landed 2026-11-13). The call-argument hole is closed for
  runtime calls.** `mojo/middle/rt_sigs.py` is GENERATED from `runtime/*.h`
  (`python3 tools/gen_rt_sigs.py`; 1,014 signatures, where the hand-written
  `_KNOWN_SIGS` has 606). `_repr_fix_args` in `emit_infra.py` is the last step
  of `_emit_call`: it takes the parameter type from the headers and the
  argument's type from its DECLARATION (`gen.var_types`), trusting neither the
  caller's `(ctype, value)` claim nor the partial table, and emits the
  conversion as its own statement. Three calls that were spelled as text
  (`mojo_cmp_fold`, `pow`, `main`'s `return result;`) were routed through it.
  Over the 188-file corpus (727,209 statements) the findings went 191 -> 1;
  the one left is `compile_to_gimple (src)` in `fire.py`'s single-module dump,
  a call to a program function with 1 of its 4 arguments (defaults not padded
  across modules), which is not a runtime call.
  `BASELINE` in `test_gimple_lint.py` is empty and must stay empty.
  Not covered: a call spelled as TEXT (`gen._new_val(t, f"mojo_x ({v})")`)
  never reaches `_emit_call`. That is stage 2.
- **Stage 2a (landed 2026-11-13). Runtime calls take values, not text.**
  `gen._rt_call(ret, 'mojo_x', [a, b])`, `gen._rt_into(dst, 'mojo_x', [a, b])`
  and `gen._rt_void('mojo_x', [a, b])` (`emit_resolve.py`) are THE way to call
  a runtime function. They take values, never `(ctype, value)` claims, and
  run the same `_repr_fix_args` as `_emit_call`. A script rewrote 501 of the
  527 text-spelled runtime calls, and the last 26 were rewritten by hand
  (2026-11-13), so `TEXT_CALL_BASELINE` in `test_gimple_lint.py` is 0 and may
  only shrink from there. A call guarded by an inline `if` is lowered with
  `gen._cond_goto` and `gen._rt_void`: raw GIMPLE rejects both `&&` and a
  non-`goto` `if` body, so the conditional shape could not be spelled as text
  in a `__GIMPLE`-tagged method at all.
- **Stage 2a, computed callees (landed 2026-11-14).** The same three
  primitives take a COMPUTED callee name: `gen._rt_call('_Bool',
  f"{base}_resume", [h])`, `gen._rt_void(f"mojo_list_set_{suf}", [l, i, v])`.
  178 such calls (generator `_resume`/`_value`/`_destroy`, `_alloc_X`,
  `_mojo_at_X`, `mojo_list_get_X`, `setjmp`, the function-pointer helpers)
  were text and are not any more. `TEXT_ANY_CALL_BASELINE` (7: the primitive
  itself, two `free` lines inside a C `if` block, a function header, a Metal
  `for`) counts a call of ANY callee spelled as text and may only shrink.
- **Stage 2a, casts (landed 2026-11-13).** `gen._cast(ctype, v)` and
  `gen._cast_into(dst, ctype, v)` state the type once. A script rewrote 540 of
  548 casts spelled as text, and the last 8 by hand (2026-11-13, one of them a
  false positive of the lint's `_new_val` cast pattern: a parenthesized
  DEREFERENCE is not a cast); `TEXT_CAST_BASELINE` is 0.
  `gimple-lint` is in the LANDING gate (`tools/gates.json`), so a branch that
  adds a text-spelled runtime call or cast, or a call-argument finding, does
  not land.
- **Stage 2a, control flow (landed 2026-11-13).** `gen._goto(l)`,
  `gen._cond_goto(c, a, b)`, `gen._ret(v)`, `gen._ret_void()` are the only
  spellings of a jump or a return (364 sites rewritten, 1 left:
  `TEXT_CF_BASELINE`). They still emit text that `_emit_through` and
  `_emit_raw` pattern-match; stage 3 moves that matching INTO these four
  functions and deletes it from the emitter.
- **Stage 2a, copies (landed 2026-11-13).** `gen._copy(dst, src)` is the
  only spelling of `dst = src;` (183 sites). It reads both variables'
  declared types and writes the conversion out when their representations
  differ, so a caller cannot emit a "non-trivial conversion" copy.
- **Stage 2a, binary operations (landed 2026-11-14).**
  `gen._binop(ctype, a, '+', b)`, `gen._cmp(a, '<', b)` (a `_Bool`) and
  `gen._binop_into(dst, a, op, b)` are the spelling of arithmetic, a bit
  operation or a comparison (219 sites). A variable operand whose declared
  scalar type differs from what GIMPLE requires is converted by its own cast:
  to the result type for arithmetic, to the wider operand for a comparison.
  `TEXT_BINOP_BASELINE` is 0: the last 16 text-spelled sites were rewritten on
  2026-11-14 and the baseline followed them down.
- **Stage 2b (landed 2026-11-21). The builder.**
  `mojo/ir/build.py`: `raw`, `copy`, `cast_into`, `assign`, `binop_into`,
  `call_into`, `call_void`, `label`, `comment`, `cond_br`, `if_block`,
  `else_if_block`, `else_block`, `end_block`, `if_call`. Each builds a typed
  `Instr` and appends it to `gen.body_lines` through one chokepoint,
  `build.append`, which applies the `#line` stamping rule the text emitter
  used to apply AND clears `gen._last_was_terminal` (the text emitter did
  that for every ordinary statement; a family that moved without it turned
  the statement after a jump into a block terminator and dropped an emitted
  `goto` — measured on `flow/15_try_finally_order.py`). `raw` is the adapter
  for a statement no family has claimed yet and `_emit_raw` is its only
  backend caller. Landed in two rounds: copies (`_copy`), casts
  (`_cast_into`), arithmetic (`_binop_into`), runtime calls
  (`_rt_call`/`_rt_into`/`_rt_void`), program calls (`_emit_call`'s three
  result/void sites) and labels (`_emit_label`); then every remaining
  `gen._emit` site — assignments of every destination spelling, comments,
  the one- and two-armed conditional branch, if/else-if/else/end blocks and
  the `if (c) f (...);` one-statement body — across `emit_calls`,
  `emit_exprs`, `emit_methods`, `emit_stmts`, `emit_loops`, `emit_infra`,
  `emit_funcs`, `emit_resolve` and `cpp_async`. `_rt_args` and
  `_binop_text` gained a list-returning sibling (`_binop_operands`) so the
  coercion stays where it is while the statement becomes a shape.
  Byte-identical `.ci` on all 285 `tools/pydiff_corpus` programs against
  master (`tools/c_oracle.py`). Ratchet: `test_type_string_ratchet.py`
  counts `gen._emit(` / `self._emit(` (300 on 2026-11-20; 266 on
  2026-11-21 before the first round; 245 under the corrected pattern, which
  no longer counts `emit_metal.py`'s 21 `self._emit` calls — that file emits
  Metal Shading Language and writes no gimple statement, so they could never
  move and made the floor 21 instead of 0; 235 after the first round;
  **0** now) and `build.raw(` (1: `_emit_raw`), so the adapter cannot become
  the way around the first count. `test_gimple_lint.py`'s
  `TEXT_ANY_CALL_BASELINE` fell 4 -> 1 (the one left is the Metal `for`, not
  a gimple statement) and `TEXT_CF_BASELINE` 1 -> 0 (`_cond_goto` is
  `build.cond_br` now).
  Not 2b's: the cast expressions (`_new_val(T, f"(T2){x}")`, 418 on
  2026-11-20, 41 on 2026-11-21) become `gen._cast(T, x)`; `load_field` /
  `store_field` as named shapes (an assignment already models the statement,
  and its operands are spellings until stage 4); `br` / `ret` as `Instr`s,
  which needs `_emit_cf` to take an `Instr` instead of its statement text —
  do that one alone; and the coercion (which operand needs a conversion)
  moving in from `rt_call`/`_rt_args`/`_binop_operands`, which is the stage-4
  boundary. The control-flow four stay text because `_emit_cf` is told the
  statement KIND and rewrites exits for a `try`/`with` teardown; stage 3a's
  paragraph below says why.
- **Stage 3a (landed 2026-11-13). Exits are told, not recognised.**
  `_emit_cf` (`emit_infra.py`) replaces `_emit_through`. `gen._goto`,
  `gen._ret`, `gen._ret_void` hand it the KIND of statement and its label or
  value; it runs the `try` / `with` teardown for the frames the exit leaves.
  Nothing matches `startswith('return ')` or slices a value out of a line any
  more, and `_emit_raw` no longer infers "terminal" from text. `gen._emit`
  REFUSES a jump or return spelled as text (it would skip the teardown).
- **Stage 3b (landed 2026-11-14). Ownership is told, not recognised.**
  `note_call_result(gen, dst, fname)` (`emit_infra.py`) records that a call
  to a `_FRESH_CONTAINER_RETURNS` / `_FRESH_STRING_RETURNS` function hands
  back a brand-new object. `_rt_call`, `_rt_into` and `_emit_call` call it;
  they know the callee. `_emit_raw` no longer searches a line for ` = mojo_`.
  It now appends the line and its `#line` directive and does nothing else.
  CONSEQUENCE: a call with a result that is spelled as text
  (`gen._new_val(t, f"{fn} ({x})")`) is never marked fresh, so its result
  leaks. Use `gen._rt_call(t, fn, [x])` -- a computed callee name is fine.
- **Stage 3c (landed 2026-11-21). Statements are `Instr`, not strings.**
  `gen.body_lines` holds `Instr`; `Instr.line()` is the ONE rule that renders
  a body entry (two spaces of indent for a modelled statement, verbatim for
  'opaque', and a blank line then column 0 for a label), and the four
  function-assembly sites spread `ginf.body_text(gen)`. A statement no
  family has modelled yet is an 'opaque' `Instr`, so this landing changed no
  output; what changed is that a statement's shape now travels with it
  instead of being recovered from its text. `mojo/ir` is in the compiler's
  own import closure now, which is what its rule 2 was written for.
- **Stage 4. Types are `Type`, not strings.** `var_types` holds `Type`.
  The ten scalar sets and the 2,400 string tests are replaced by `Type`
  methods. Ratchet (landed 2026-11-20, `test_type_string_ratchet.py`): the
  counts of `.endswith(' *')` (344; 67 after the codemod), `== 'int64_t'` (404), `in (.., 'int64_t')`
  (312), `== 'char *'` (398; 159 after the 2026-11-20 codemod that turned 240 of them into `TypeLattice.is_cstr(x)`, byte-identical C on 284 programs), `== '_Bool'` (68; 23 after the codemod), `== 'double'` (187) and
  `== 'MojoList *'` (203) may only shrink.
  *Measured 2026-11-21 after the stage-4 tail* (two rounds: the first added the representation-class
  predicates — `is_dict`, `is_set`, `is_bytes`, `is_uword`, `is_char`, `is_voidp`, `is_boxable`,
  `is_word_value`, `is_c_scalar`, `is_number_scalar` — and taught the codemod to emit a
  disjunction of classes for a tuple that is a union of them; the second added the single-type
  spellings the tail still needed — `is_str`, `is_span`, `is_u8`, `is_c_long`, `is_void`,
  `is_cpp_bool`/`is_cpp_int_scalar` for the C++ emitter's `bool` — and the unsolved marker
  `is_unsolved` (`''`/`'unknown'`) with its two word compositions, and took the tuple pattern to
  **0**): `in (..)` 0, `== 'int64_t'` 54, `== 'char *'` 62, `endswith(' *')` 16, `== 'MojoList *'`
  29, `== '_Bool'` 2, `== 'double'` 8, C byte-identical on all 285 `tools/pydiff_corpus` programs.
  `python3 test_type_string_ratchet.py --per-file` is the per-file census;
  `test_type_lattice_predicates.py` pins each predicate's exact membership and each codemod table
  entry. The remaining `==` tests are the ones whose left side is an expression the codemod
  deliberately does not accept; the tuple pattern can only shrink from here.
  *Census 2026-11-23 (the exact rewrites and the single-type codemod).* Stage 4's string tests are about 930, not
  about 30. The ratchet had counted seven spellings; `test_type_string_ratchet.py` now counts every comparison
  against a C type spelling in three patterns (`== type string`, `in (type tuple)`, `endswith('*')`). Before this
  round a grep on master counted 619 `==` tests, 270 tuple tests and 38 `endswith`. The widened tuple rewrites of
  `6a89c722e` and `cf600c4d5` are now exact (`is_no_type` and the `is_c_int`/`is_i8`/.../`is_c_float` predicates
  replace the widening predicates, and `ALLOWED_EXTRA` is gone). The single-type equality codemod ran over the
  backend for `MojoDict *`, `MojoBytes *`, `void`, `MojoSet *`, `void *`, `char` and `MojoStr *`. The ratchet now
  measures 216 `==` / 263 tuple / 38 `endswith`, and those are its BASELINE. Still open: the `== 'int'` and
  `== 'float'` equalities (their exact predicates exist; mapping them is a separate change).
  *One vocabulary (landed 2026-11-23, migration step 1 of
  `bugs/hard/GIR_stage4_one_type_vocabulary.md`).* `mojo/ir/types.py` is the single source: `Type` is
  interned by C SPELLING (`char`/`int8_t`, `long`/`int64_t`, `bool`/`_Bool` are distinct objects) and
  carries `cls`, the semantic type, so `trivially_convertible`, `mismatch_class` and `cast_is_legal`
  compare `.cls` and still treat `long` and `int64_t` as one GIMPLE class. Every `TypeLattice.is_*`
  now delegates to `spelled(t)` plus a `Type` method and answers exactly the spellings it did; the nine
  union predicates are frozen (no new callers). C is byte-identical on all 285 programs. Next: move
  one side table (`_elem_types`) to `Type`.
- **Stage 5a (landed 2026-11-14). A value's facts travel with a copy.**
  `carry_value_info(gen, dst, src)` (`emit_infra.py`) copies what the backend
  knows about a VALUE from one name to another, and `gen._copy` calls it for
  every same-typed copy. It carries the 18 type tables (`_elem_types`,
  `_dict_val_types`, `_actual_types`, `_tuple_slot_types`, the callable and
  generator tables, ...), only ADDS facts (a fact already recorded for the
  destination wins; the rule for the value kinds is stage 5b's, below), and never
  carries ownership (`_fresh_vals`, `_owned_*`).
  This CHANGES generated code: 33 compiler modules compile differently
  (about 770 fewer statements; a boxed fallback read becomes a typed read
  where the element type is now known). Small programs are unchanged.
  The six dynamic-word facts (`_boxed_vals`, `_dyn_word_vals`,
  `_tagged_word_vals`, `_int_word_vals`, `_maybe_kinds_vals`,
  `_boxed_container_vals`) joined it in stage 5b step 4 (below), which
  carries `dyn` / `int_word` / `slot_kinds` / `boxed_container` across a copy
  and, since step 5 (LANDED), the `Box` kind and its `Tagged` flag as well;
  the bind-side half ("a name holds a box") is the separate `BindBox` flag,
  which a copy does not carry.
- **Stage 5b. One value-info record. LANDED 2026-11-21 (steps 1-5).**
  The name-keyed tables are fields of one `ValueInfo` record per temp:
  `kind` is `Int / Erased(T) / DynWord / Box / Plain` and the flags
  `Tagged`, `SlotKinds`, `BoxedContainer` and `BindBox` carry the facts that
  are not a kind. `int64_t` therefore splits into
  Int / Erased(T) / DynWord / Box in the value's info. No writer sets `Erased(T)`
  yet: `carry` moves it (a Box source upgrades a Plain, Dyn or Erased destination;
  only an Int destination is protected, `mojo/middle/valueinfo.py` `carry`), and
  `erased_type` is read, but nothing marks a value Erased. It is modelled and
  carried only.
  *Measured 2026-11-20 (the guide for the next round).* The six
  dynamic-word sets, by uses / files / writers (`.add`, `.update`, `[x] =`):
  `_boxed_vals` 93/11/30, `_dyn_word_vals` 75/8/51, `_tagged_word_vals`
  61/7/19, `_int_word_vals` 46/7/9, `_maybe_kinds_vals` 84/11/33,
  `_boxed_container_vals` 17/6/8: about 376 sites.
  Plan, in order, each step byte-identical C on `tools/pydiff_corpus` except
  steps 4-5, which the plan allows to change C (hash
  `compile_to_gimple_with_cpp` output before and after, review per program):
  1. (LANDED 2026-11-20, byte-identical on 284 programs) A plain class `WordFacts` (new `mojo/middle/valueinfo.py`) that OWNS the
     six sets and has `save()` / `restore(saved)`; `FuncState` keeps ONE
     `fs_words` instead of twelve fields.
   (Steps 2 and 3 LANDED 2026-11-20: 100 readers and 148 writers go through the `gen._word_*` wrappers; `test_type_string_ratchet.py` counts the direct spelling, now 0. `== 'int64_t'` also moved to `TypeLattice.is_word`, 405 -> 101.)
  2. Add read predicates on it (`words.may_be_box(name)`, `words.is_tagged(name)`,
     `words.is_dyn(name)`, `words.is_int_word(name)`) and move the ~200 readers
     (`x in gen._boxed_vals`) onto them by codemod, as the type-string codemods
     did. Ratchet: a text count of `gen._boxed_vals` etc. may only shrink.
  3. Add writers (`words.mark_tagged(name)` ...) and move the ~150 writers.
  4. (LANDED 2026-11-21) The storage is one `ValueInfo` record per temp,
     holding the `Int / Erased(T) / DynWord / Box` kind and the three flags the
     old sets spelled (`Tagged`, `SlotKinds`, `BoxedContainer`; step 5 adds
     `BindBox`); the six
     historical sets are derived READ-ONLY views (`WordFacts.boxed`, ...).
     Two consequences a single kind forces, each measured over the 285 corpus
     programs (`compile_to_gimple_with_cpp` output, before vs after) and
     reviewed per program:
     * `is_dyn` is true for a Box (a box is a word whose kind only the runtime
       knows). 9 programs change C and NONE changes its CPython verdict (all 9
       were already WRONG/CRASH): 4 print a boxed word through
       `mojo_cstr_or_int_str` instead of `mojo_repr_boxed`, 4 ask
       `mojo_truthy_word` instead of comparing the box against 0 (the correct
       truthiness for a `False` box), and one stops folding an `isinstance`
       over a word of runtime-known kind. Only 2 of the 9 change their stdout
       at all, and in both the old and the new output is an address where
       CPython prints a value — the programs were wrong before too. A Box may
       also be a CONTAINER pointer (`mojo_list_get_boxed` hands one back), so
       a lowering that asks `is_dyn` takes the runtime-word path there instead
       of the typed-pointer one (e.g. an `or` merge of a boxed container
       becomes an `int64_t` iterated through the runtime's kind dispatch).
       That is safe (`mojo_truthy_word` handles registered lists/dicts/sets and
       `mojo_cstr_or_int_str` renders boxes by kind), just less precise; the
       bind/read split in the next item is where it gets refined.
     * `Box` travels AS a Box since step 5 (LANDED 2026-11-21): a copy is the
       same word, so the `Box` KIND and its `Tagged` flag travel with it, and
       every reader of "this word's kind is a runtime fact" sees the copy as
       the box it is. The BIND-side fact is the separate `BindBox` flag
       (`bind_box` / `bind_tagged`), set by `mark_boxed` / `mark_tagged` and
       NOT moved by `carry`, and the bind path (`_keep_tagged_box`,
       `_tagged_bind`, `_for_copy`, the `mojo_box_word` unbox arms in
       `emit_stmts` / `stmts_shared`) reads it. Without the split, carrying
       `Box`/`Tagged` made two self-host-closure modules refuse to compile —
       `mojo/middle/infra_infer.py` (`_pn2 = _chosen.get('param_names') or []`,
       the `or` merge's dict-get arm is tagged, the merge temp is stored into a
       `MojoList *` local) and `elaborate.py` (`cands`) — because the bind path
       read the copy's tag as a decision about the NAME's representation. A
       pass-through temp is not a name anybody bound, so with the split both
       compile and the bind path's answers are exactly what they were when a
       copy was carried as a `DynWord`. The read side had to learn the same
       lesson one level down: `+ - *` on a maybe-box operand beside an integer
       now selects by the box's kind (`mojo_mul_word` / `_float_param_arith`)
       instead of coercing the operand to a `double`, which had made the
       result — and every local it was stored into — a C double. `carry`'s
       docstring carries the measurement; `test_gimple.py`'s
       `test_word_facts_bind_side_does_not_travel` and
       `test_a_carried_box_operand_keeps_an_int_result`, and
       `test_dict_slot_read_regression.py`'s Test 7 pin it.
   5. (LANDED 2026-11-21) Split the bind half of `boxed` out of the read half
      (the `BindBox` flag, the bullet above), so `carry` can move the `Box`
      kind and `Tagged`. The bind path answers exactly as it did when a copy
      was carried as a `DynWord` (every bind-side reader moved, and only for
      copies); and once a copy IS a box, `+ - *` beside an integer selects the
      answer by its kind (`_tagged_arith_select`, `mojo_mul_word` /
      `_float_param_arith`) instead of coercing the operand to a C `double` —
      the coercion turned an ordinary integer local into a double and made
      `mojo/backend_gimple/emit_stmts.py` refuse in the whole-closure compile
      (`'_nbytes': ... cannot also hold a str value (char *)`). Measured:
      `mojo/middle/infra_infer.py`, `mojo/backend_gimple/emit_stmts.py` and
      `elaborate.py` compile (`compile_to_gimple(..., do_imports=False)`; the
      first and third refuse with the bind path on `is_tagged`), and the
      closure compile of `fire.py`'s tiny `import cas` program reports no
      module falling back to source inclusion.
     `test_gimple.py`'s `test_word_facts_one_record_per_temp` pins the record,
     the read-only views and the carry boundary; `test_gimple_runner.py`'s
     `test_copy_of_a_dynamic_word_keeps_it` pins the copied dynamic word.
- **Stage 5c. Optional values (measured 2026-11-20; first slice landed).**
  Why the split in 5b matters, measured on `tools/pydiff_corpus`: of 240
  programs only 60 matched CPython, and the largest single cause (about a
  quarter of the wrong ones) is that `None` and the integer 0 are the same
  word. `def find(...): ... return i ... return None` is emitted as an
  `int64_t` function and `return None` is `0LL`; `print(find(..))` shows `0`,
  `find(xs, 0) is None` is True. The runtime already has the answer: a TAGGED
  WORD, where `None` is the shared box `mojo_box_none()` (a pointer to a
  kind-`n` box), an int is the plain word, and `mojo_word_is_none` /
  `mojo_repr_boxed` / `mojo_box_word` read it. Generators and "mixed return"
  functions (pointer beside a scalar) already use it; the plain-function path
  only used it when one arm was a pointer. What is missing is the DECISION
  "this value may be None, carry it tagged", and it cannot be taken from the
  C type, because `int64_t` is an int, a None, a String and a struct pointer
  at once (`infra_infer._return_arms_need_boxed_word`'s note: "`None` is never
  evidence", since for an erased pointer None must stay NULL). So the rule
  needs the 5b split: a value is `Int` (provably a number), `Erased(T)` (a
  pointer whose None is NULL), `DynWord` (tagged) or `Box`.
  Landed: a function with a `None` arm and a provably scalar arm (a literal or
  a comparison, `scalar_shape_arm_kind`) returns the tagged word
  (`_return_arms_are_int_or_none`). NOT done: an arm that is a name or a call
  (`return i`, the common case) counts only when the local is provably an
  int (`_local_is_provably_int`: an unconditional `i = <int literal>` first,
  every rebinding `i = <int literal>` or `i op= <int literal>`), so `find`
  above now returns the tagged word. A copy `y = x` of a name bound to such a
  call keeps the box (`tagged_next_bind_name`). Still lost: a tagged value
  stored in a list/tuple/dict slot, and one passed as an argument (the
  parameter is a plain word).
  Landed 2026-11-20, the "may be None" decision widening past returns:
  (a) an UNANNOTATED parameter declared `= None` is a tagged word
  (`infra_infer.param_default_none_names`): `_param_ctype` keeps the
  `int64_t` slot, `_box_param_call_args` boxes every argument by kind
  (`mojo_box_none` for None, `mojo_box_int` for 0, including the omitted
  argument's padded default), and `_reset_func` registers the name in
  `boxed`/`tagged`/`dyn_word_locals` so reads and `print`/`str` dispatch by
  the box's kind. `def label(value=None)` now tells `label()`, `label(None)`
  and `label(0)` apart. Detection is limited to a slot that would otherwise
  be the plain `int64_t`: an annotation or a call-site/usage-inferred
  pointer type wins.
  (b) `dict.get(k)` with NO default on a scalar/unknown value domain is the
  boxed read (`runtime/fire_runtime.c`'s `mojo_dict_get_boxed*`, one lookup;
  `emit_methods._ldm_get`): the slot's own word on a hit, `mojo_box_none()`
  on a miss, so `print({"a": 1}.get("zz"))` is `None`. A binding
  `x = d.get(k)` keeps the box (`emit_infra.dict_get_call_is_tagged`), so
  `x is None`, `print(x)` and `x + 1` use the tagged machinery.
  (c) a LOCAL whose every binding is `None` is the box-holding word
  (`mixed_value_locals`' `{'none'}` rule), so `x = None; print(x)` prints
  `None`. A name that also holds a str/container keeps its first-declared C
  type, and module globals are excluded.
  (d) `str(None)`, `repr(None)`, `f'{None}'` and `'%s' % None` spell `None`
  (`_stringify_value`, `str`, `repr`), and `x is None` folds for a local
  PROVABLY an int (`_local_is_provably_int`: `n = 0; n is None` is False).
  Still lost: a name bound to `None` BESIDE another kind (it keeps the other
  binding's C type), a `dict.get` on a double/str value domain or through a
  container slot, a tagged word stored in a list/tuple/dict slot, and one
  passed to a parameter not declared `= None`. Next, in order: (1) widen the
  local-int proof to arithmetic on proven ints, `len(..)` and comparisons;
  (2) carry the box across the remaining bindings (the 5b split); (3) read
  list/tuple slots and every `.get` domain back as `DynWord`. Do NOT define
  `x == None` as `x == 0`: that was tried and reverted (it makes
  `0 == None` true).
  *Decision (2026-11-23, owner-delegated):* a slot represents `None` according to what it can hold.
  If it holds references only, `None` is NULL (`Erased(T)`; today's behaviour, and the compiler's own
  code). If it holds a scalar beside `None`, `None` is the `mojo_box_none()` box (`DynWord`/`Box`) and
  every read is box-aware. If it has no informative evidence, nothing changes. An unannotated
  parameter is classified by the argument kinds at its call sites. Details and the next slice are in
  `bugs/mid/GIR_stage5c_none_representation.md`.
- **Stage 6, counted loops (started 2026-11-14).** `gen._loop_head(idx, n,
  bb_cond, bb_body, bb_post, bb_after, stmt)` and `gen._loop_tail(idx,
  bb_cond, bb_post, bb_after, stmt)` (`emit_resolve.py`) are the skeleton of
  `while idx < n: ...; idx += 1`: the test, the branch, the body label, the
  `loop_stack` / depth bookkeeping of a `for` statement, the increment and
  the exit label. 16 of the hand-written copies use them (two comprehension
  loops spelled the increment constant `1LL`; they now emit `(int64_t)1`
  like the rest, the one output change of this step). Passing `''` for
  `bb_post` makes the three-block form (an internal loop with no `continue`
  target, the increment at the end of the body block); 7 more copies use
  that. NOT converted: the cursor loops with no increment, and three loops
  whose increment is not the last thing in the body.
- **Stage 6, arms of the giant functions (2026-11-14, finished
  2026-11-15).** `tools/extract_arm.py` moves one top-level `if` arm of a
  function into its own function and replaces it with a call. It computes what
  the arm reads from the parent, refuses an arm whose inputs are not bound on
  every path, that binds a name the parent reads later, or that calls a nested
  function, and checks that the moved body is the same syntax tree. 35 arms
  were moved on 2026-11-14: `_lower_call` 3,261 -> 2,060 lines (`_lc_*`),
  `_lower_method_call` 3,951 -> 1,423 (`_lmc_*`). 26 more followed out of the
  eight remaining functions, so `--list FILE PARENT 25` now prints `0 lines
  can be moved` for every one of them and only the tool's own refusals
  (`NO (...)`) remain: `_lower_dict_method` 557 -> 101 (`_ldm_*`),
  `_lower_subscript` 724 -> 291 (`_ls_*`), `_lower_IdentExpr` 679 -> 303
  (`_lie_*`), `_lower_call` 2,084 -> 1,708 (`_lcx_*`), `_lower_named_call` 983
  -> 757 (`_lnc_*`), `_lower_MemberExpr` 1,728 -> 1,533 (`_lme_*`),
  `_lower_binary_tail` 1,421 -> 1,274 (`_lbt_*`), `_lower_struct_method_call`
  482 -> 410 (`_lsmc_*`). `test_gimple_arms_extracted.py` pins that state.
  Three arms came back afterwards — `_lower_IdentExpr`'s builtin-value-map
  arm in the 2026-11-21 stage-4 type-predicate codemods (`1b94b71d4`) and
  `_lower_binary_tail`'s two `x == None` / `x is None` arms (the second
  added by `70e483ef9`) — and the pin went 6/8. All three were re-extracted
  on 2026-11-22 as `_lie_builtin_value_map_fastpath`,
  `_lbt_boxed_none_compare` and `_lbt_proven_int_is_none`, with
  byte-identical C on both corpora.
  Every other compiler source and test program in the dump corpus emits a
  byte-identical `.ci`; the new parameters have the C types the parent's
  locals had in the compiler's own output, the one exception being
  `_ls_pointer_arith`'s `ot`, which the parent casts at the call site
  (`MojoList *`) because that arm uses it as a container.
- **Stage 6, passes of `gen_module_impl` (started 2026-11-16).**
  `module_gen.py` now compiles in single-file `--dump` mode (one
  `any(<generator expression>)` was in the way) and is in gimple-lint's
  corpus. `tools/extract_arm.py --phase` moves a WHOLE top-level statement
  (a pass: a `for`, an `if` with its test) into a function that returns
  nothing; it refuses a statement that returns, that binds a name the
  parent or one of its nested functions reads afterwards, or that calls a
  nested function. 18 passes were moved (`_gmp_*`, 3,731 lines):
  `gen_module_impl` is 15,554 -> 11,841 lines. Generated output for the
  corpus is byte-identical. In the compiler's own output the new
  parameters have the C types the locals had; a list or dict parameter
  whose elements are strings is annotated `list[str]` so element reads
  stay typed. About 100 of 54,000 runtime calls in `module_gen.ci` differ,
  most of them boxing calls that are gone because a local no longer
  shares its name with a differently-typed local of another pass.
  Second round (2026-11-16): `tools/hoist_nested.py` lifts a nested
  function to module level when the only names of the parent it reads are
  the parent's parameters and other liftable nested functions; those
  become its first parameters and every call passes them. 30 of the 59
  nested functions were lifted (`_gmh_*`, 1,074 lines), which freed 18 more
  passes to move. `gen_module_impl` is 9,416 lines.
  Third round (2026-11-21): 13 more passes, 856 statement lines -> 13 call
  sites, so `gen_module_impl` is 9,107 lines. The largest was the 478-line
  AST struct-table pre-seed, gated on one bool.
  Fourth round (2026-11-21): the remaining 14 passes, 447 statement lines ->
  14 call sites, so `gen_module_impl` is **8,674** lines and
  `extract_arm.py --list-phases` prints `0 lines can be moved`: every
  statement still in the parent is one of the tool's own refusals (returns,
  binds a name read later, or calls a nested function).
  `test_gimple_module_passes.py` pins the extracted rows, their annotations,
  the 8,674-line ratchet and the `0 lines can be moved` end state.
  Fifth round (2026-11-23): the two blocks `4e2efdfee` added to the parent moved out
  (`_gmp_publish_definer_pts`, `_gmp_emit_str_pool_forward_decl`), and
  `test_gimple_module_passes.py` pins them. The parent is now 8,679 lines; the 5 over the
  8,674 ratchet are call-site lines the moves left and one call wrapped by `2adea3531`, so
  its ratchet is raised to the measured count, with the reason written beside it.
  NOT moved: 25 of the 32 nested functions (30 direct) read a name bound in
  `gen_module_impl`'s own body (measured 2026-11-23 by an AST pass; `self` and the
  parent's parameters do not count). Lifting one needs a typed parameter per captured
  local. Also not moved: the passes that call them, and the passes that bind a name
  read later (those need to return a value).
- **Stage 7. Other printers.** The C++ coroutine lowering (`cpp_core.py`,
  `cpp_async.py`, 16,400 lines, a second walk of the same AST) becomes a printer
  over GIR. A direct GCC bridge (`gcc/fire/fire-gimple-bridge.cc`) is not in this
  repository: there is no `gcc/` directory, and `git log --all` has no commit for
  that path. So stage 7's T1-T8 cover only the C++ printer. Its oracle is in place and
  is the second corpus `tools/c_oracle.py` hashes (`tools/cpp_corpus`, 13
  coroutine programs compiled with `MOJO_CORO=cpp`, both promise shapes).
  Shape step (2026-11-22): `extract_arm.py` moved every top-level `if` arm of
  the five dispatch functions into its own module-level function — 30 arms,
  `_cpp_expr` 3,566 -> 101 lines, `_cpp_stmt` 1,582 -> 73, `_cpp_with_stmt`
  344 -> 256, `_cpp_yield_from` 716 -> 595, `_cpp_for_stmt` 1,846 -> 456 —
  so `--list ... 25` prints `0 lines can be moved` for all five and an arm is
  the unit that later returns an `Ex`. Both corpora are byte-identical.
  `test_gimple_cpp_core_arms.py` pins it.

## 5. The two oracles every worker uses

A worker is only as good as the check it runs. Two checks, and a worker never
reports success without them.

1. **Byte-identical C** (behaviour-preserving work: codemods, extractions,
   builder migration). Hash the generated C of `tools/pydiff_corpus` at the base
   commit and on the worker's tree; every hash must match. Today this is the
   `tools/c_oracle.py`: the scratch script of 2026-11-20/21 became it, and it caches
   the base hashes per commit so a worker runs only its own side.
2. **CPython agreement** (behaviour-changing work: stage 5c, bug fixes).
   `python3 tools/pydiff.py <repro>` prints `OK`, and `python3
   test_pydiff_ratchet.py` keeps every listed program OK.

Plus the cheap gates every change runs: `python3 test_gimple_lint.py`,
`python3 test_type_string_ratchet.py`, `python3 tools/dangling_doc_refs.py
--ratchet`, and `python3 -c "import ast; ..."` over every touched file (a
regex codemod once turned `x not in (...)` into `x is_int_word(not)`).

**The blind spot.** Both oracles run the Python reference compiler. Neither can
see a self-host failure: stage 5b steps 1-3 passed both and still broke
`make bootstrap` (the self-hosted compile stubbed every `WordFacts` method).
A per-module `python3 fire.py --dump <module>.py` does NOT see it either
(measured 2026-11-21 at `ef53815a1`: 0 stubs in `loops_shared.ci`, where the
closure had ten). Only the whole-closure dump does, so the self-host check is

    python3 tools/c_oracle.py check --base <sha> --closure

which runs `fire.py --dump-full fire.py` (what `bootstrap-stage1-transitive`
runs) for both sides and fails on any NEW weak stub. It costs 5-8 minutes and
about 6 GB, so the orchestrator runs it once per wave on the merged tree, not
each worker. Any change that adds a module, a class, or a method called across
modules gets it. The full check is still `make bootstrap` (owner-run; see CLAUDE.md, `## Verification policy`).

## 6. Stage 7: status and todo (measured 2026-11-23)

The T0 baseline, measured on master with an AST pass over `cpp_core.py` before T3 (kept for the record): 0 statement
f-strings left; 0 expression f-string leaves left (the last two are ported on master); 24 `.show()` boundaries; 39
functions returning `list[...]` of statement text; 11 functions returning `str`; the three statement helpers have 186
(`_cpp_ir_line`), 112 (`_cpp_assign_line`), 52 (`_cpp_call_line`) and 60 (`_cpp_instr`) call sites, plus 20
`_cpp_opaque` and 3 `_cpp_if_break_line`. Re-measured 2026-11-23, after T6: 12 `.show()` calls in `cpp_core.py`
(`grep -c`); the functions annotated `-> str` are `_cpp_expr` (`cpp_core.py`) and `_cpp_dict_key_expr` and
`_cpp_fresh_name` (`cpp_async.py`); `_cpp_str_compare` is annotated `str | None` (see T3).

- [x] T1. Statement helpers return `Instr` (with `indent` set), not `str`: `_cpp_ir_line`, `_cpp_assign_line`,
      `_cpp_call_line`, `_cpp_instr`, `_cpp_opaque`, `_cpp_if_break_line`. Consumers that test a line as text (for
      example `'co_yield' in ln` over `finally_lines`) must test the Instr's `show()`.
- [x] T2. The statement printers return `list[Instr]` (merged `cec0b197f`; verified on master 2026-11-23).
- [x] T3. The `-> str` functions become `Ex` (or stay as text only at a named boundary). Done 2026-11-23, see the T3 status below.
- [x] T4. The `.show()` calls are removed as their consumers take `Ex`/`Instr` (58 to 7 at T4, and 12 after T6;
      see the T4 and T6 status below).
- [x] T5. One rendering edge: each `Instr` is rendered by `.line()` through `render_lines` (`mojo/ir/instr.py`), and
      the function-assembly joins that print the rendered lines are the `cpp_async.py` and `emit_funcs`/`emit_loops`
      sites. Done 2026-11-23, see the T5 status below.
- [x] T6. Call-slot text lists (`_cpp_call_arg_expr` and its consumers) take `Ex`. Done 2026-11-23, see the T6 status below.
- [ ] T7. Verify: `test_gimple_cpp_core_arms.py`; `c_oracle check` identical on all 285 pydiff and all coroutine
      programs; `compile_stdlib.py` `FAILED: 0`, no skips.
- [ ] T8. Done criterion: delete this doc in the same commit, with `python3 tools/dangling_doc_refs.py --ratchet`.

### Status 2026-11-23: T6 (call-slot text lists take `Ex`)

`_cpp_call_arg_expr(gen, a) -> Ex` now returns an `Ex` (the list-literal case already did): `_cpp_list_literal_arg_expr`
or `gen._cpp_expr_ex(a)`, no `.show()`. Its consumers now take the Ex:
- The slot binder `_cpp_generator_call_slot_pairs` returns `[(Ex, ctype), ...]`. Its leading, tail and default slots
  are normalised there (`_as_ex`, `ex_text`), so no caller hands it text.
- `_cpp_emit_generator_start_expr` and `_cpp_generator_start_kwargs_expr` build the `<base>_start` arguments with
  `_cpp_cast_ex`/`_paren_ex` and `_cpp_call_ex`, not f-strings.
- The `yield from` and `for ... in` consumers: the pointer and word casts are `_cpp_cast_ex`; the `', '.join(arg_exprs)`
  joins are gone, and the `_mojogen_sub_guard` line is `ex_cat(..., _cpp_call_ex(<base>_start, arg_exprs), ...)`.
  The `for ... in` `_mj_w(...)` wrap is `_cpp_call_ex`.
- The builtin-call function (`args = [_cpp_call_arg_expr(gen, a) ...]`): its `f"(T)({args[N]})"` casts and
  `(void *)(intptr_t)(...)` casts are `_cpp_cast_ex`/`_paren_ex`, the `ex_text(args[0])` wrappers are dropped, and the
  `tuple`/`list` copy line is `_cpp_iter_word_ex`. The min/max result and the `mojo_reversed` wrap are `_cpp_call_ex`.

Counts (the call-argument path; `.show()` and f-string sites over the argument lists, master `63e597a35` vs this round):
- Call sites of `_cpp_call_arg_expr` whose result is text: 7 before (the 4 slot/cargs sites at 2315, 2343, 2439, 2442,
  plus 4933, 10396, 13656), 0 after. Every one now feeds an Ex list.
- f-string sites over an argument (`{args[...]}`, `{a}` of an argument list, the `(T)(...)` slot casts): 19 before, 2
  after. Both are statement text (see below).
- `.show()` calls in `cpp_core.py`: 8 before, 12 after. The one in `_cpp_call_arg_expr` is gone; the 5 added are the
  text edges listed below, each rendering an argument once at the point it becomes statement text.

Text consumers left in the call-argument path, each a text edge (statement or shape test), with the reason:
1. The min/max statement body (`_body`, `_a = args[_ai].show()`, `args[0].show()`): built as a C statement string in the
   reduction lambda. Moving it to `Instr` statements is the next step, not T6's.
2. The `*args` pack (`_pack_stmts`, `args[_i].show()`): a text list of printed statements (see the T4 note on 5974).
3. The rethrow argument text (`_cargs = ", ".join(...)` over `[x.show() for x in args]`), passed to
   `_cpp_rethrow_pending`, which takes text.
4. The `yield from` shape test (`re.fullmatch(r'-?\d+|true|false', arg_exprs[_ai].show().strip())`): a regex over the
   printed argument, so it must read the text. The decision is unchanged.

Verification (worktree `work-t6`, branch `work/gir-stage7-t6`, base `63e597a35`):
- `test_gimple_cpp_core_arms.py`: `30 arm(s) pinned across 5 printer(s), 0 failure(s)`.
- `c_oracle check --base master`: `all 285 programs generate identical C to 63e597a35a6e` and `all 35 coroutine programs
  generate identical C++ companion to 63e597a35a6e`.
- `compile_stdlib.py` (default parallelism): `PASSED: 610`, `FAILED: 0 (0 expected, 0 unexpected)`, no `skip` lines, exit 0.
  The run was a cold build (`Codegen CAS: 0/610 hits`, `GCC CAS: 0/610 hits`).

T6 is T6-done.

### Status 2026-11-23: T5 (one rendering edge)

The rule `Instr -> text` now lives in one place: `render_lines(lines)` in `mojo/ir/instr.py` (next to `Instr.line()`,
which it calls). It was previously a copy in `cpp_core.py` (`_cpp_render_lines`) and a second copy as the body of
`emit_infra.body_text`. `cpp_core` no longer defines it; its callers import `render_lines`.

Rendering edges after T5 (each statement line is rendered once, by `Instr.line()`, through `render_lines`):
- `mojo/backend_gimple/emit_infra.py` `body_text(gen)`: the function-body edge for `emit_funcs.py` (3 assemblies) and
  `emit_loops.py` (1 assembly). It delegates to `render_lines(gen.body_lines)`.
- `mojo/backend_gimple/cpp_async.py`: the coroutine function bodies (`render_lines(gen._cpp_stmt(...))` for the body
  text, then `'\n'.join(render_lines(lines))` at each of the 3 assemblies).
- `mojo/backend_gimple/cpp_core.py` 3168: the one loop lambda that is joined into a single opaque block.

Direct `.line()` calls outside the edge: before 6 (cpp_core render helper, `emit_funcs` main-return check,
`emit_infra.body_text`, two `emit_resolve` diagnostics, `mojo/ir/build.py` `append`), after 2 (`render_lines` itself,
and `build.py` `append`, which renders once to test whether a statement is blank or a `#` directive and prints nothing).

Statement-to-text joins, measured by an AST pass over `mojo/backend_gimple/*.py` and `mojo/ir/*.py` (a `''`, `' '`,
`'\n'` join whose argument names statement lines): 46 before, 44 after. The two removed in `cpp_core.py` are the
statement-list joins: the `' '.join(stmts[:-1])` of the string-join lambda (12858) and the `' '.join(_pack_stmts)` of the
`**kwargs` pack lambda (6018), which now pass one opaque statement each to the lambda body (its `show()` joins them with
the same single space). The function-assembly `'\n'.join(lines)` sites in `emit_funcs`, `emit_loops`, `cpp_async` and
`emit_infra` join text that is already rendered, so they are not counted as renders. Joins of text fragments that are
not statement lists (`''.join(parts)` in `cpp_core`, C-text processing in `emit_infra`) are unchanged.

Verification (worktree `work-t5`, branch `work/gir-stage7-t5`, base `9904b3b03`):
- `test_gimple_cpp_core_arms.py`: `30 arm(s) pinned across 5 printer(s), 0 failure(s)`.
- `c_oracle check --base master`: `all 285 programs generate identical C` and `all 35 coroutine programs generate
  identical C++ companion`.
- `compile_stdlib.py` (default parallelism): `PASSED: 610`, `FAILED: 0 (0 expected, 0 unexpected)`, `skips: 0`, exit 0.
- Targeted: `test_gir_builder.py` (0 failures), `test_codegen_yield_from_walk_ast_memo.py` (PASS); the latter imports
  `render_lines` directly now.

T5 is T5-done.

### Status 2026-11-23: T4 (`.show()` removed as consumers take `Ex`)

`.show()` calls in `mojo/backend_gimple/cpp_core.py`: 58 on master `3a215425a` (`grep -c`, and 58 occurrences by
`grep -o`; the T3 entry above said 60), 7 after this round. The statement sites that built their line as an f-string
with an interpolated `.show()` are now `Ex` compositions rendered by the statement helper.

What landed:
- `mojo/ir/instr.py`: a concatenation kind `Ex('cat')` and `ex_cat(*parts)` (parts are Ex or text), so a line that is
  partly text and partly an operand stays an Ex until the statement helper renders it.
- `_cpp_ir_line` takes an Ex operand (as `_cpp_assign_line` and `_cpp_instr` already did); `_cpp_call_line` takes Ex args.
- `_cpp_counted_loop_ex(ctr, lst)` (the `for` header over a list, 7 sites, was copy-pasted) and `_cpp_iter_word_ex(src)`
  (`mojo_iter_word((int64_t)(intptr_t)(...))`, 5 sites).
- The dynamic-call wrapper `_cpp_dyn_call_text` is gone; its 5 callers use `_cpp_dyn_call_expr` directly, which returns Ex.
- `_cpp_module_global_field`'s literal string, `_cpp_boxed_list_literal_expr`, `_cpp_list_literal_arg_expr`, the
  and/or word pick (`_cpp_cond_ex`), the `while` list/dict/set tests, the raise messages (`ex_cat` of the message Ex,
  three throw sites), the `yield from` sorted/`sorted` lists, and the list/dict/set iteration reads now take Ex.

Remaining `.show()` calls, each a text boundary, with the reason:
- `cpp_core.py` 563 (`_kwfwd` lambda): its `lines` are `_cpp_opaque` text blocks (`_cpp_opaque(ln)`).
- 2482 (generator spread lambda): a `_cpp_opaque` text block joined with text lines.
- 2573 (boxed list literal): the element `parts` are joined into a `_cpp_opaque` text block.
- 2653 (`_cpp_call_arg_expr`): returns text; its consumers are the call-slot text lists, which is T6.
- 5334 (`next(<generator call>)`): the handle is tested with `.isidentifier()` in `_cpp_next_on_generator_expr`, so it is text.
- 5974 (`**kwargs` literal key): the key goes into `_pack_stmts`, a text list of printed statements.
- 7014 (`_cpp_expr`): the named text boundary (`_cpp_expr_ex(gen, e).show()`), with its 232 callers.

Verification (worktree `work-t4`, branch `work/gir-stage7-t4`):
- `test_gimple_cpp_core_arms.py`: `30 arm(s) pinned across 5 printer(s), 0 failure(s)`.
- `c_oracle check --base master`: `all 285 programs generate identical C` and `all 35 coroutine programs generate
  identical C++ companion`.
- `compile_stdlib.py`: `PASSED: 610`, `FAILED: 0 (0 expected, 0 unexpected)`, no `skip` lines, exit 0.

T4 is T4-done.

### Status 2026-11-23: T2 verified on master (merge `cec0b197f`)

T2 (statement printers return `list[Instr]`) was merged before verification and is verified now:
- `test_gimple_cpp_core_arms.py`: 30 arms, 0 failures.
- `c_oracle check --base 3dec79e25` (the commit before T2): identical C on all 285 pydiff programs and identical C++ on all 35 coroutine programs.
- `compile_stdlib.py` (default parallelism): `PASSED: 610`, `FAILED: 0 (0 expected, 0 unexpected)`, no skips. The run was served almost entirely from the content-addressed cache (100% codegen and GCC hits), so it confirms the same code compiles, not a fresh build.

T2 is T2-done.

### Status 2026-11-23: T3 (`-> str` functions return `Ex`)

The AST pass (`FunctionDef` whose `returns` unparses to `str`) finds 7 functions in `cpp_core.py`; the other 4 of
the "11" are annotated `str | None` and are listed below as not converted.

Converted:
- `_cpp_as(ctype, expr) -> Ex`: `_cpp_cast_ex(ctype, _paren_ex(_as_ex(expr)))`, 87 call sites. 44 are f-string fields
  now `{...show()}`, the text sinks for statement lines. The Ex consumers (`_cpp_call_ex` args, `_cpp_comma_ex`,
  `ex_text(...)` wrappers) take the Ex directly.
- `_cpp_in_link(gen, a: Ex, a_node, b: Ex, b_node, negate) -> Ex`: built from `_cpp_call_ex`, `_cpp_cast_ex`,
  `_paren_ex`, `_cpp_not_ex`. The `in` branch of the compare-chain arm computes its operands as Ex; the other
  comparisons keep the text boundary, because `_cpp_str_compare` takes text.
- `_cpp_apply_fstring_spec(part_val: Ex, spec) -> Ex` and `_cpp_fstring_list_piece(gen, expr_node, v) -> Ex`
  (unannotated before, now Ex because it feeds the same pieces).
- `_cpp_string_literal_expr(gen, val, is_interp) -> Ex`: the pieces are Ex, the `mojo_str_cat` chain is
  `_cpp_call_ex`. 3 call sites.
- `_cpp_tagged_operand_word(gen, node) -> Ex`: `_cpp_cast_ex` chain. 1 call site.
- `_cpp_build_container_from_iterable`: the annotation was `-> str` but the body already returned an Ex
  (the lambda). Annotation corrected to `-> Ex`.

Kept as text, on purpose:
- `_cpp_expr(gen, e) -> str` is THE named text boundary (`_cpp_expr_ex(gen, e).show()`), 232 callers. Its callers
  that need text are the sinks T4/T6 remove.

Not converted (annotated `str | None`, outside the literal `-> str` pass):
- `_cpp_percent_format`, `_cpp_fn_container_shape`, `_cpp_str_compare` (takes text operands),
  `_cpp_literal_slot_ctype` (a C type spelling, not an expression). The first three are the next candidates.

Irreducible text leaves (`ex_text`), recorded here:
- C string literal spellings (`"..."`, `""`, `"True"`, `"False"`, `"fill"`) and the constants `'0'`, `'NULL'`,
  `'-1'`, which are `ex_text` leaves with no shape.
- `_cpp_word_of_kind(ctype, text)` (in `mojo/middle/exprtypes.py`, returns str): its result is an `ex_text` leaf
  inside `_cpp_tagged_operand_word`. Converting it is that module's own step.

Show count in `cpp_core.py`: 15 on master, 60 now. The new `.show()` calls are each a text sink (`_cpp_assign_line`,
`_cpp_ir_line`, f-string conditions, `_cpp_instr` text). T4 removes them as those sinks take Ex.

Verification (worktree `work-t3`, base `master` HEAD 051634f49):
- `test_gimple_cpp_core_arms.py`: `30 arm(s) pinned across 5 printer(s), 0 failure(s)`. One fixture line changed:
  the `_EGen` stub's `_cpp_in_link` takes and returns Ex, because the interface changed.
- `c_oracle check --base master`: `all 285 programs generate identical C` and `all 35 coroutine programs generate
  identical C++ companion`. A first run caught a leftover placeholder (`_cpp_marker_void`), fixed before the run
  reported here.
- `compile_stdlib.py`: `PASSED: 610`, `FAILED: 0 (0 expected, 0 unexpected)`, no `skip` lines, exit 0.

T3 is T3-done.

Status: stage 7 T1 (statement helpers return `Instr`) and T2 (statement printers return `list[Instr]`) are on
master and verified. T3 to T6 are done since (see their entries). Status (2026-11-23): still open: T7 and T8.
This file is the only GIR document; the dated history of
the stage 7 work is in git history (the stage 6 and 7 bug log, deleted 2026-11-23).

## Selfhost closure: remaining errors (2026-11-24)

`python3 test_selfhost.py` compiles the whole compiler closure into one C translation unit and
runs gcc on it. On master it failed with 67 gcc `error:` lines at `8f244354d`. The state after
the fixes merged on 2026-11-24:

Fixed (merged; each is a real fix, not a workaround):
- `expected expression before '('` (13): `_ensure_local` materialises a literal cast into a
  register (`92e4e806a`, coro for-loop family).
- `invalid operands to binary` on doubles (13): a may-box operand of a bitwise operator is read
  as its integer (`65454bf70`, float8 family).
- `'_FLOAT'/'_SIGNED'/'_UNSIGNED' undeclared` (3) and `makes integer from pointer` for
  `MojoDict *` in `emit_funcs.py` (2): an imported container global keeps its real C type, and a
  global_var export is not a function's return type (`77abd738a`, `fa8f13afa`, funcptr family).
- The `_mj_w` and struct-constructor `Ex` reprs in generated C++ (`ead016231`, `9ba501e2b`), which
  broke `test_gimple_generator_runner.py` (520/0 on master).

Open, with bug docs:
- `bugs/GIR_selfhost_extern_return_types.md`: `conflicting types` (30). A WIP commit
  (`e9e4ea4a9`, merged to master as `913aa3780`) removes those 30 but adds pointer-conversion
  errors, so it is RED. The fix is a pre-pass that records each definer's return type before any
  importer is generated.
- `bugs/GIR_selfhost_unexplained_error_kinds.md`: `'Scope' has no member 'declared_types'` (11),
  `'MojoFunction' has no member 'param_types'` (10), `non-trivial conversion in 'component_ref'`
  (10), `'Interpreter' has no member '_try_depth'` (8), and the smaller rows. Not diagnosed.

The self-host gate (`bootstrap-stage1-transitive`, disabled, `bugs/gate-bootstrap-stage1-transitive.md`)
stays disabled until the closure compiles with zero gcc errors and the stage 2/3 chain runs.
