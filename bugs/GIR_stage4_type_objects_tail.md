# GIR stage 4 (tail): the remaining type-string tests become `TypeLattice` / `Type` calls

Plan source: `doc/GIR.md`, Stage 4 (`var_types` holds `Type`, not strings).

## Measured now (2026-11-21, after this round)

`python3 test_type_string_ratchet.py --counts`:

| pattern | count | baseline |
|---|---|---|
| `in (.., 'int64_t', ..)` | 17 | 17 |
| `== 'int64_t'` | 54 | 54 |
| `== 'char *'` | 62 | 62 |
| `endswith(' *')` | 16 | 16 |
| `== 'MojoList *'` | 29 | 29 |
| `== '_Bool'` | 2 | 2 |
| `== 'double'` | 8 | 8 |
| `gen._emit( text` | 266 | 266 (stage 2b, not this doc) |
| direct word-set use | 10 | 10 (stage 5b, not this doc) |

Per-file: `python3 test_type_string_ratchet.py --per-file` (the census; the packet docs
`bugs/GIR_W1_*.md` carry a snapshot of it).

## What this round landed (2026-11-21)

- **The representation-class predicates** in `TypeLattice` (`mojo/middle/types.py`):
  `is_dict`, `is_set`, `is_bytes`, `is_uword`, `is_char`, `is_voidp`, `is_boxable`,
  `is_word_value`, `is_c_scalar`, `is_number_scalar`. The union ones COMPOSE the single-type
  predicates instead of re-spelling memberships, so a class that gains a member is gained at
  every call site at once; `is_int_word_or_voidp` was rewritten to compose `is_int_word` /
  `is_voidp` for the same reason.
- **`tools/type_string_codemod.py`** now maps a tuple to a tuple of predicate names and emits a
  PARENTHESISED disjunction for a union of classes (`x in ('int', 'int64_t', 'uint64_t')` ->
  `(is_int_word(x) or is_uword(x))`), reads a tuple wrapped across lines, accepts a single-level
  call as the left side (`decl.get(k) in (...)`, a keyword argument's value), and rewrites a
  module that imports `TypeLattice` directly — which is why `mojo/middle/exprtypes.py` (no
  `gimple_ctypes` name at all) had been invisible to it, 43 -> 5 sites.
- **`test_type_lattice_predicates.py`** (new): an answer key for every predicate's exact
  membership, plus a check that every codemod `TUPLES` entry's emitted predicates accept exactly
  its tuple. Six entries are deliberately wider and are listed with the exact extra member they
  add (the tuples had forgotten `unsigned int`, the other integer widths, or `__fp16`).
- **Counts**: `in (..)` 115 -> 17; `endswith` 32 -> 16; `== 'int64_t'` 59 -> 54; `== 'char *'`
  70 -> 62; `== '_Bool'` 6 -> 2; `== 'double'` 9 -> 8; `== 'MojoList *'` 31 -> 29. Generated C
  byte-identical on all 285 `tools/pydiff_corpus` programs (`tools/c_oracle.py check --base
  ba509fb5d`).

## What is left (17 tuple sites) and why each is not mechanical

1. **`('int64_t', '_Bool', 'bool', 'int')` x4** (`cpp_core.py`) — the C++ spelling `bool`
   alongside `_Bool`. `is_bool` answers `_Bool` only (200+ call sites rely on that), so this
   needs a decision: either `is_bool` learns `bool` (a wide behaviour change to measure), or a
   separate `is_cpp_bool` predicate is added for the C++ path.
2. **The unsolved-type spellings** `''` (and `'unknown'`): 8 sites
   (`emit_calls.py:6158,6783`, `emit_exprs.py:2093`, `emit_methods.py:6348`,
   `module_gen.py:10344,19865`, `funcs_shared.py:378`, `loops_shared.py:119`). An empty/`'unknown'`
   ctype means "not inferred yet"; whether that belongs in one predicate
   (`is_int_word_or_unsolved`) depends on the stage-5c None/unsolved decision, so it is not a
   mechanical rewrite.
3. **`'long'`** (`emit_infra.py:9475`, `emit_methods.py:9143`) — a C spelling this backend emits
   only from `__builtin_bswap64`; it is not in the lattice tables.
4. **`'MojoStr *'`** (`emit_calls.py:7338`), **`'uint8_t'` beside `char`/`int`/`_Bool`**
   (`emit_exprs.py:7259`) — one site each; `is_str`/`is_u8` would be predicates with one caller.
5. **`('Span *', 'int64_t')`** (`emit_resolve.py:3921`) — the span proof, a shape of its own.

A packet that resolves (2) also unblocks `('','int64_t','void')` and `('int64_t','int','long','')`.

## Next step

1. Decide (1) and (2) above (or hand each of the 17 sites a predicate/composition once decided).
2. Lower `BASELINE` in `test_type_string_ratchet.py` to the count reached, and extend
   `ANSWER_KEY` in `test_type_lattice_predicates.py` for any new predicate.
3. Then the tuple pattern is at 0 and the ratchet can only shrink again.

## Done when

    python3 test_type_string_ratchet.py                     # passes, with the tuples at 0
    python3 test_type_lattice_predicates.py                 # passes
    python3 tools/memslot.py --gb 8 --label c_oracle -- \
        python3 tools/c_oracle.py check --base <sha before the change> -j 4
                                                            # all 285 programs identical C

The quick test that proves a rewrite did not change behaviour is
`test_type_lattice_predicates.py` (membership) plus `test_type_string_ratchet.py` (the count);
the byte-identical-C check is the behavioural one.

## Acceptance

- `test_type_string_ratchet.py` passes at a lower baseline.
- Generated C byte-identical on `tools/pydiff_corpus` (hash before and after).
