# FORMAL: `formal/model.py` binds `SET_ALGEBRA_OPS` twice, so `no_module_level_name_is_bound_twice_in_model` is red

**Area:** FORMAL, `formal/model.py` (`CONTAINER_OP_MEANING` / `SET_ALGEBRA_OPS` /
`CONTAINER_GATED_OPS`, around line 14161). **Status: OPEN, measured 2026-10-14
on master (`d20d1466`), both architectures-irrelevant (this is a source-level
invariant, not codegen). Filed, NOT fixed: the region is a live claim
(`FORMAL_container_operators_that_need_a_per_element_stride`, `formal407-docs`,
and `FORMAL_set_value_model`, `formal410-docs`), so this is reported rather than
edited.**

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_external_call.py
  FAIL  env_round_trip: … (pre-existing; see
        bugs/FORMAL_the_env_getenv_string_constructor_is_refused_as_an_int.md)
  FAIL  no_module_level_name_is_bound_twice_in_model:
        got ['SET_ALGEBRA_OPS (lines 14161, 14176)'], expected []
external_call: PASS=50 FAIL=2
```

The `env_round_trip` red is the document named above and is not this one. The
second is new since that document was written (`PASS=51 FAIL=1` there, `PASS=50
FAIL=2` here), and no `bugs/` doc names it.

## What I saw

`test_formal_external_call.py::_module_level_names_bound_twice` walks the top
level of `formal/model.py` and reports every name assigned more than once. It
finds exactly one:

```
14161: SET_ALGEBRA_OPS = ("-", "&", "^")
14162: CONTAINER_GATED_OPS = tuple(op for op in CONTAINER_OP_MEANING
14163:                             if op not in SET_ALGEBRA_OPS)
…
14176: SET_ALGEBRA_OPS = ("-", "&", "^")      # second, identical binding
```

Both values are identical, so **no behaviour changes** — the second binding
shadows the first and the file works. What is red is the invariant the test
exists for: a module-level name bound twice is a silent shadowing, and a reader
who edits the first definition gets a green run and no behaviour change.

**The cause is a merge, not a defect in either branch.** Two parallel branches
each added the constant with its own comment:

* `15cf0383` ("formal: set algebra (& - ^) on arm64, refused by name on
  x86-64") added the SECOND block (14165-14176), whose comment names
  `_emit_set_op` (`formal/arm64_codegen.py:13387`) and `set_algebra_refusal`
  (`formal/model.py:14294`) — both exist;
* `205af6d3` ("formal arm64: `&`, `-` and `^` between two sets are …") added the
  FIRST block (14142-14163), whose comment names `_set_vars`/`is_set_expr` and
  `container_set_algebra_refusal` — the last of which does NOT exist in the file
  (the two functions are `container_operator_refusal`, 14179, and
  `set_algebra_refusal`, 14294).

Both blocks are on master after the merges, so the first block is the stale
resolution and the second names the code that actually exists.

## What I expected

One module-level binding per name, which is what
`test_formal_external_call.py`'s own case asserts and what
`test_formal_specialization.py:1172` cites it as the pin for.

## The exact next step

Keep ONE `SET_ALGEBRA_OPS` definition — the second block's, whose comment names
the functions that exist — and delete the duplicate (reconciling the first
block's one stale reference, `container_set_algebra_refusal`, into it or
dropping it; `_set_vars`/`is_set_expr` are real, in both backends and
`formal/model.py`, and may stay). `CONTAINER_GATED_OPS` stays; it reads
whichever binding survives, and both values are the same.

Then `python3 tools/memslot.py --gb 8 --label t -- python3
test_formal_external_call.py` is `PASS=51 FAIL=1` (only `env_round_trip`
remains), and `formal-external-call` is back to its documented one red.

**Measured, not argued:** the two definitions are byte-identical
(`("-", "&", "^")`), so the fix is a deletion and no generated code moves. This
is checklist-sized; it is filed rather than fixed only because the surrounding
set-algebra region is held by two live claims (see Area above).
