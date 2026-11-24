# GIR stage 4: two type vocabularies disagree; decide the one before `var_types` holds `Type`

Design work (hard class): decide this before any more stage-4 migration. Written 2026-11-23,
reviewing stage 4 of `doc/GIR.md`.

## The goal, and what exists

Stage 4's goal is "`var_types` holds `Type`": the 2,400 string tests become `Type` methods. What
landed is a BRIDGE. About 40 string predicates on `TypeLattice` (`mojo/middle/types.py`), such as
`is_cstr(t: str)` and `is_int_word_or_voidp(t: str)`, plus codemods that route ~1,300 tests through
them. That is the right first step: every test now has one spelling to change later. But:

1. **Two vocabularies.** `mojo/ir/types.py` (the plan's rule 1: "No new type-compatibility logic
   outside `mojo/ir/types.py`") defines `Type` and `type_named`. The string predicates are a second
   classification, and they disagree with it:
   - `type_named('char')` is `I8`, a signed 8-bit int, so `Type.is_int()` is True for `char`. But
     `TypeLattice.is_int('char')` is False, and `char` has its own `is_char`.
   - `type_named('long')` IS `type_named('int64_t')` (the same interned object, LP64). But the
     backend distinguishes `is_c_long` from `is_word`.
   - `type_named('bool')` IS `type_named('_Bool')`. But the backend has `is_cpp_bool` beside `is_bool`.
   - `Type.is_int()` excludes `_Bool` (kind `bool`). The string `is_int` excludes it too, but
     `is_cpp_int_scalar` includes both bools.
   The backend's distinctions are SPELLING distinctions: it prints `char` vs `int8_t` and `long` vs
   `int64_t` differently, and the C++ printer needs `bool`. Interning by C semantics loses them. So
   "`var_types` holds `Type`" as `mojo/ir/types.py` is written today would change generated text.
2. **Union-shaped predicates.** Nine predicates name a historical tuple, not a concept:
   `is_int_word_or_bool`, `is_int_word_or_voidp`, `is_word_or_cstr`, `is_int_word_or_none`,
   `is_word_or_none`, `is_word_or_bytes`, `is_word_or_list`, `is_word_or_unsolved` and
   `is_int_word_or_unsolved`. Some were added in W0 by the orchestrator, some later. Each one
   freezes an accident of some call site into the vocabulary, and none maps to a `Type` method.
3. **`None` / `''` / `'unknown'` are not types.** The backend passes them as "unsolved". The
   predicates answer False (or True, for `is_unsolved`) for them, and `ends_in_star(None)` answers
   False where `.endswith` used to raise, so a caller with a missing type now silently takes the
   "not a pointer" branch. A `Type` world needs an explicit `UNSOLVED` (or `Optional[Type]`), not
   magic strings.

## Decisions needed (with the trade-offs)

A. **Where the vocabulary lives.** Option 1: `TypeLattice`'s predicates delegate to
   `type_named(t)`, so `mojo/ir/types.py` is the one source and the string API is a thin adapter.
   Option 2: `TypeLattice` stays the source and `mojo/ir/types.py` follows it. Option 1 is what the
   plan's rule 1 says. It requires (B).

B. **Spelling-preserving types.** Either `Type` keeps the source spelling (an interned
   `(semantic type, spelling)` pair, so `char` and `int8_t` are distinct objects that share a
   class), or the backend is changed to print one canonical spelling per class, which changes
   generated C and needs its own review. The first is behaviour-preserving and lets the migration
   stay byte-identical.

C. **Union predicates.** Freeze them: add no new ones, and the codemod emits an `or` of class
   predicates instead. When a call site moves to `Type`, its union becomes the `or` of `Type`
   methods. Then delete the nine.

D. **Unsolved.** Pick `Optional[Type]` (None = unsolved) or an `UNSOLVED` sentinel `Type`, and
   decide whether `'unknown'` and `''` are one thing (today `is_unsolved` says yes, while several
   hand-written tuples named only `''`; see `bugs/GIR_stage4_rewrites_must_be_exact.md`).

## Then the migration (each step byte-identical on `tools/c_oracle.py`, closure check per step)

1. Implement (B) in `mojo/ir/types.py`, then make every `TypeLattice.is_*` delegate to it. Pin the
   equivalence in `test_type_lattice_predicates.py`.
2. Move ONE side table to `Type` (for example `_elem_types`), with `type_named` at the writers and
   `.name` at the text edge. Measure, then do the next table.
3. `var_types` last: it has about 730 references.

## Related

- `bugs/GIR_stage4_rewrites_must_be_exact.md`: undo the 15 widened rewrites first, so the bridge is
  exact before it is moved.
- `bugs/GIR_stage4_ratchet_counts_every_type_string.md`: the honest census (about 930 string tests).
- `bugs/GIR_stage4_single_type_equalities_codemod.md`: the cheap mechanical part.

## Status

### 2026-11-23: decisions A-D and migration step 1 LANDED

- **A.** `mojo/ir/types.py` is the source. Every `TypeLattice.is_*` that is a spelling test (all but
  `is_pointer`, `ends_in_star`, `is_unsolved`, which are structural or about the unsolved marker)
  calls `gir_types.spelled(t)` and one `Type` method (`is_word`, `is_cstr`, `is_ranked_int`, ...).
  Each answers EXACTLY the spellings it did: `test_type_lattice_predicates.py` keeps ANSWER_KEY
  unchanged and adds `check_legacy_equivalence` (every predicate against its old literal over 70
  probes, including `char*`, `long long`, `ssize_t`, padded text) and `check_type_vocabulary`.
- **B. Design: intern by spelling, share a class.** `type_named(name)` returns one object per C
  spelling. A spelling that is a class's own name is the canonical object (`I64`, `I8`, `BOOL`); any
  other (`long`, `int8_t`, `bool`, `ssize_t`, `unsigned int`) is a new `Type` with the same kind,
  bits and signedness and `cls` pointing at the canonical one. `trivially_convertible`,
  `mismatch_class`, `same_pointee` and `cast_is_legal` compare `.cls` instead of identity, so
  `long` is still `int64_t` to GIMPLE. A pointer to a spelled type has the matching pointer class.
  Chosen over canonical printing (which changes C) and over a pair `(class, spelling)` (a second
  object per use). `BASE_TYPES` still maps to the canonical types, so `reader.py`, `verify.py`
  and `build.py` are unchanged. `spelled(t)` is `type_named` that answers `OPAQUE` for text it would
  normalise (`char*`), since predicates answer for exact spellings only. `Type.ranked` marks the 13
  spellings of the arithmetic lattice (`RANKED_SPELLINGS`, pinned equal to `generated_dispatch`).
- **C.** The nine union predicates carry "frozen: no new callers; compose class predicates instead"
  and are pinned by the test. Nothing of that shape was added.
- **D.** `None`, `''`, `'unknown'` are untouched: every predicate answers what it did; `is_unsolved`
  stays string-level. No predicate's membership changed.
- Verified: `tools/c_oracle.py check` identical C on 285 programs and C++ on 35 coroutine programs.

**Next (migration step 2):** move ONE side table, `_elem_types`, to `Type`: `type_named` at its
writers, `.name` at the text edge, then the predicates take the `Type` directly (add `Type`-taking
overloads beside `spelled`). Measure the C diff per table, then do the next. Step 3 (`var_types`)
stays last. `is_pointer`/`ends_in_star` need a `Type` form before they can delegate; the union
predicates go when their callers become `or` of class methods.
