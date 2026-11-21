# GIR W1 packet `cpp_core`: rewrite the remaining C-type string tests in 1 file(s)

STOP: claimed by the Claude W1 wave (doc/GIR_WORKERS.md); the orchestrator removes this line if the wave releases it

Stage 4 tail of `doc/GIR.md`, run as described in `doc/GIR_WORKERS.md` (W1). Mechanical, and the
generated C must NOT change. About 39 sites, all in these files and nowhere else:

| file | sites left (by ratchet pattern) |
|---|---|
| `mojo/backend_gimple/cpp_core.py` | == 'int64_t': 11, in (.., 'int64_t', ..): 4, == 'char *': 12, == 'MojoList *': 12 |

Re-measure before you start: `python3 test_type_string_ratchet.py --per-file` is the census; the
table above is a snapshot (2026-11-21, after the stage-4 tail round).

`tools/type_string_codemod.py` already rewrote every site it can match. The sites left have a left
side it does not accept (a call, a `.get(..)`, a parenthesized expression) or a tuple it has no
predicate for.

## Before you start

    START=$(git rev-parse HEAD)      # the base every check compares against

## What to do, site by site

Rewrite a test ONLY with a predicate whose answer is EXACTLY the old test's answer for every value,
`None` and `''` included. The predicates, all `gimple_ctypes.TypeLattice.<name>(t)` (defined in
`mojo/middle/types.py`; do not edit that file):

| old test | new spelling |
|---|---|
| `t == 'char *'` | `is_cstr(t)` |
| `t == 'MojoList *'` | `is_list(t)` |
| `t == '_Bool'` | `is_bool(t)` |
| `t == 'double'` | `is_double(t)` |
| `t == 'int64_t'` | `is_word(t)` |
| `t.endswith(' *')` | `ends_in_star(t)` (only where `t` cannot be `None`) |
| `t in ('int', 'int64_t')` | `is_int_word(t)` |
| `t in ('int', 'int64_t', '_Bool')` | `is_int_word_or_bool(t)` |
| `t in ('int', 'int64_t', 'void *')` | `is_int_word_or_voidp(t)` |
| `t in ('int64_t', 'double', '_Bool', 'char *')` | `is_py_scalar(t)` |
| `t in ('int64_t', 'char *')` | `is_word_or_cstr(t)` |
| `t in (None, 'int', 'int64_t')` | `is_int_word_or_none(t)` |
| `t in (None, 'int64_t')` | `is_word_or_none(t)` |
| `t in ('int64_t', 'MojoBytes *')` | `is_word_or_bytes(t)` |
| `t in ('int64_t', 'MojoList *')` | `is_word_or_list(t)` |

Tuple order does not matter. `t != X` and `t not in (...)` become `not <predicate>(t)`.

The rest of the vocabulary is the `TUPLES` table in `tools/type_string_codemod.py`: a tuple that is
the union of several representation classes maps to a DISJUNCTION of their predicates
(`is_uword`, `is_char`, `is_voidp`, `is_dict`, `is_set`, `is_bytes`, `is_boxable`,
`is_word_value`, `is_c_scalar`, `is_number_scalar`), e.g.
`t in ('int', 'int64_t', 'uint64_t')` -> `is_int_word(t) or is_uword(t)`. Run the codemod
(`python3 tools/type_string_codemod.py --check`) before working by hand: it rewrites every one of
these, including tuples wrapped across lines, in a file that names either `gimple_ctypes` or
`TypeLattice`. `python3 test_type_lattice_predicates.py` pins every entry's exact membership.

SKIP (leave unchanged and list in your report): a test inside a string (emitted C text, a message, an
f-string), a chained comparison (`a == b == 'int64_t'`), a tuple not in the table, and any site where
you are unsure. Do not add predicates, do not edit any file outside the table above, and do not
change any ratchet baseline: the orchestrator does that when it merges.

## Checks, in this order, before you report

    python3 -c "import ast; [ast.parse(open(f).read()) for f in ['mojo/backend_gimple/cpp_core.py']]"
    python3 tools/c_oracle.py check --base $START -j 4   # must print: all ... programs generate identical C
    python3 test_gimple_lint.py                    # passed: 0 failure(s)
    python3 test_type_string_ratchet.py --counts   # your files' counts fell

If the oracle reports ANY program whose C differs, find the site that caused it, put it back, list it
under "reverted", and run the oracle again. Never "fix" a difference.

## Report

One commit with all your changes, message `GIR W1 cpp_core: N type-string tests become TypeLattice predicates`.
Then report: the commit sha, sites rewritten per file, sites skipped (file:line and why), sites
reverted, and the four check results.
