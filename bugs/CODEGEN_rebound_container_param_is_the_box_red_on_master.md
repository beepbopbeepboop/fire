# CODEGEN: `test_rebound_container_param_is_the_box` fails on master

Found 2026-10-29 while verifying the merge of
`fix-merge-bug-codegen-next-on-a-user-defined-itera`. Not caused by that merge.

## What I ran

`python3 test_gimple.py` in a `git archive master` copy (under `.tmp/`), wrapped
in `python3 tools/memslot.py --gb 8 --label ...`. The same file on the merged
branch gives the same single failure.

## What I saw

    FAIL  rebound_container_param_is_the_box: compiles=True walk.live='MojoSet *'
          same_kind.live='MojoList *' (want 'int64_t' and 'MojoList *': a rebound
          to ANOTHER kind is the box, to the SAME kind is not)

`test_gimple.py` on master: 417 pass / 1 fail (this one).

## What I expected

Per `bugs/CODEGEN_selfhost_closure_set_kind_refusal_double_compiles_the_module.md`
(line 24-25), the test "fails before, passes after" the commit that added it,
9057a9fed "CODEGEN: a parameter rebound to another container kind is the box".
On master it fails, so either that fix is not in effect for this shape or a
later commit undid it.

## Shape

`test_gimple.py:666` `test_rebound_container_param_is_the_box`: a parameter
`live` is rebound to another container kind (`set(live)` in a nested def
`walk_stmts`). The walk's `live` should be the box (`int64_t`), the same-kind
negative control should stay `MojoList *`. Instead the walk's `live` is
`MojoSet *`.

## Next step

1. `git bisect` between 9057a9fed and master over `test_gimple.py` with
   `-k`-equivalent single-test invocation (`test_rebound_container_param_is_the_box`
   via `_run_isolated`) to find the commit that stopped the box.
2. Fix at the root of that commit (do not special-case the test's shape).
3. Delete the doc, or update its Status if the fix is partial.
