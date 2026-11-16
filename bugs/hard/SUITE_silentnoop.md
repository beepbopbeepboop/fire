# SUITE_silentnoop: make check failure

SPLIT: SUITE_silentnoop-part2

**Status:** CLOSED 2026-11-14 — `python3 tools/suite.py silentnoop` reports
**2 passed, 0 failed** (was 1 passed, 1 failed). Not a timeout: the job runs
~5 min against its registered `timeout=1500`.

Two separate defects, both fixed:

1. **A parameter whose call sites disagree across literal kinds, used as a
   container** — refused at build time. Fixed in `e4a2cc2ed` ("specialize
   literal-kind mixed params including None/comprehensions"). Part 1
   (investigation) was closed and its doc deleted; its two cases
   (`parameter_rebound_to_one_container_kind_is_not_multi_kind`,
   `sorted_two_string_set_pinning`) pass.
2. **`zip_nested_tuple_target`** — a `zip` whose first target slot is itself a
   tuple:

   ```python
   def f(pairs, others):
       for (a, b), g in zip(pairs, others):
           print(a, b, g)
   ```

   `gen._zip_bind_slot` recursed into the nested target with the bare Python
   loop index `j`. `j` is an int and `idx_t` reaches `_rt_call` as a C
   EXPRESSION; `_rt_args` spells the argument list with `', '.join(parts)`
   and `_as_str` is deliberately identity (`return e`, see its docstring), so
   the join raised `sequence item 1: expected str instance, int found`.
   `_gen_stmt_ForStmt`'s zip branch is transactional, so that exception
   silently became the generic zero-iteration `mojo_unsupported_iter`
   fallback — the loop body never ran, printing `done` instead of `1 2 9`.
   Fixed in `6461fdf4c` (pass `str(j)`). Introduced by `1507c34f1` ("gir
   stage 2a: runtime calls take values, not text (501 sites)"), which
   converted the site from an f-string — which stringified `j` and hid the
   type error — to `_rt_call`.

Left in place deliberately: `bugs/SUITE_silentnoop-part2.md`'s Acceptance says
the parent is not deleted by that task — "if this closes the parent, say so in
the commit rather than removing the doc" — so this record is that statement.
