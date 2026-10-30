# FORMAL: printf container-refusal test rows expect wording the code no longer emits

Carried forward from the round-two bulk-merge dropped-definitions bug (filed in
`4ebc73738`; its definition-level items were verified fixed on the merged tree
2026-10-29 and this is the one item left). The text, as written on `master` at `61ee5bcef`:

> The `printf("%d", <container>)` refusal rows in `test_formal_run.py` expect a
> wording (`... and \`xs\` is \`list:int\``) the code no longer emits. Pre-existing
> on master and only visible now that the census no longer dies first.

## Status (2026-10-29)

- NOT re-verified in this round. The check that would settle it is one run of
  `test_formal_run.py` (heavy: ~1300 rows), so it was left for a run that can
  afford it. The claim is master's, carried over as-is.
- What is known: `test_formal_run.py` has refusal rows for `printf("%d", <container>)`
  (the comment block near `printf_d_of_a_list_length_and_element_still_prints`
  and the `REFUSAL_CASES` rows referenced there), and the refusal sentence is
  produced in `formal/model.py` (grep `printf_kind_conversion_refusal`).

## Next step

1. Run only the rows that name the container refusal: pull them out of
   `test_formal_run.py`'s `REFUSAL_CASES` by grepping `printf` and `container`,
   run them under `python3 tools/memslot.py --gb 8 --label printf-refusal -- ...`.
2. If the rows fail on wording only, decide ONE of: make the row's expected
   text match the message the code emits (if the message is the intended one),
   or restore the message the rows expect (if the rows describe intended
   behaviour). Do not weaken the assertion to a substring that both satisfy.
3. Delete this doc in the same commit as the fix.
