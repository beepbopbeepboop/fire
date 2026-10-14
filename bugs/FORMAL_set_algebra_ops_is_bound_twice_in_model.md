# FORMAL_set_algebra_ops_is_bound_twice_in_model: `SET_ALGEBRA_OPS` has two module-level bindings, so `test_formal_external_call.py`'s shadowing case is red

**Area:** `formal/model.py`, the set-algebra table (and the module in general).
**Status: OPEN, pre-existing on master, filed 2026-10-13 (`work/formal409-docs`)
while landing the `env_round_trip` fix.** The red is NOT caused by that fix —
it reproduces with it in place and is about a different line — and it lives in
`formal407-docs`' claimed area (`bug:FORMAL_container_operators_that_need_a_per_element_stride`),
so it is filed rather than edited.

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_external_call.py
...
  FAIL  no_module_level_name_is_bound_twice_in_model: got ['SET_ALGEBRA_OPS
        (lines 14220, 14235)'], expected []

external_call: PASS=51 FAIL=1
```

The failing case is `test_formal_external_call.py`'s own
`no_module_level_name_is_bound_twice_in_model` (line 970), which walks
`formal/model.py`'s AST and asserts every module-level name is bound once. The
file is otherwise green now that `env_round_trip` passes; this one row is the
remaining red.

## What is wrong

`formal/model.py` binds `SET_ALGEBRA_OPS = ("-", "&", "^")` twice:

* line 14220, immediately before `CONTAINER_GATED_OPS` (which reads it);
* line 14235, after the paragraph that explains "the three operators that are
  SET ALGEBRA", and before `container_operator_refusal`.

The two commits that added the set-algebra gate each landed a copy —
`git blame` names `205af6d3` (`formal arm64: &, - and ^ between two sets …`)
for the first and `15cf0383` (`formal: set algebra (& - ^) on arm64, refused by
name on x86-64`) for the second — and a merge kept both. The bindings are
IDENTICAL in value, so nothing behaves differently today: this is the SILENT
shadowing the case exists to catch (the first definition is unreachable, and a
reader who edits it gets a green run and no behaviour change).

## The exact next step

Delete ONE of the two bindings and keep the paragraph's own copy, i.e. keep the
one the prose at 14224-14234 introduces and make `CONTAINER_GATED_OPS` read it
(the two are adjacent, so either order works as long as exactly one survives).
Then `python3 test_formal_external_call.py` is `PASS=52 FAIL=0`.

**Whose:** `formal407-docs` holds
`bug:FORMAL_container_operators_that_need_a_per_element_stride`, which is the
set-algebra/container-operators area this line belongs to. No doc names the
duplicate; this one does, so the fix is not lost when that worker's task ends.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_external_call.py
# FAIL no_module_level_name_is_bound_twice_in_model: got
#   ['SET_ALGEBRA_OPS (lines 14220, 14235)']
```
