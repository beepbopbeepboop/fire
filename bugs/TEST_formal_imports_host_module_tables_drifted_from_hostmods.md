# TEST: five host-module tables in formal/imports.py disagree with the tree (test_formal_imports.py, 5 FAIL)

Status: FIXED in 587e71dc6 (and 84da0d25f for item 1). All five rows now pass; the import test's last failure is a load-sensitive timing bound (see that commit).  Filed 2026-11-11 on master. Measured: `python3 test_formal_imports.py` gives `PASS=90 FAIL=5`; after item 1, `PASS=91 FAIL=4`.
These are not caused by the out-self or lexer work. They were red on master before it. The struct RECOVER commit does not
own them: none of the five test names appear in its version of the file.

## The five failures (measured reasons, verbatim from the run)

1. **FIXED (test row moved, not the table)**: **no standard-library module is left in neither tier**: `host_module_tier('builtins')` is `''`, not `'unreachable'`.
   `builtins` is the interpreter's own namespace (`set(dir(builtins))`). It was written as `formal/hostmods/builtins.mojo`
   on 2026-11-08 and left the unreachable table by that rule, so its tier is `''`. The test still expected `unreachable`;
   the test's `placed` row moved to its `written` table, which is the rule the test's own docstring states.

2. **a host-module refusal says what this target offers instead**: the refusal does not name that the record callers
   want is a struct. The advice pointed at the removed constants-only exports-nothing bug doc, which did
   not exist in the tree.

3. **a host-module refusal carries its measured next step**: the same refusal, same missing doc
   (the removed constants-only exports-nothing bug doc). The real reason is not stated anywhere it can be
   read from.

4. **every host-module advice entry is honest**: `HOST_MODULE_ADVICE['collections']` tells a reader to write a struct,
   but `formal/hostmods/collections.mojo` exists. The advice tells a reader to write what is already in the tree.

5. **every name has one named verdict, and no answer is an absence**: `copy` is `written` (`formal/hostmods/copy.mojo`
   exists), but this row lists it in `HOST_MODELLED` as a gap with an owner. A name cannot be both.

## Cause

`formal/hostmods/` gained `collections.mojo`, `copy.mojo` and `builtins.mojo` after the tables that describe them were
written. The tables were not updated, and the test is the thing that noticed.

## Decided behaviour

- A module with a source in `formal/hostmods/` is `written`. Its advice entry is removed, because the advice is for a
  module the tree does not have. Its `HOST_MODELLED` line is removed.
- `builtins` is `unreachable`: it is the interpreter's own namespace, so no tier applies to it other than that one.
- The refusal names a doc that exists, or names the real reason in words. A citation to a missing doc is a
  defect of the same kind as the advice above.

## Fix order

1. Read `formal/imports.py`'s `host_module_tier`, `HOST_MODELLED` and `HOST_MODULE_ADVICE`. Measure each of the five
   against the current `formal/hostmods/` listing, not from memory.
2. Make the tables agree with the tree, one commit per table, and rerun `test_formal_imports.py` after each.
3. For item 2 and 3, decide the refusal text first, then the doc it cites: either write the doc or name the reason.
4. Delete this doc in the commit that makes the last of the five pass.

## Resolution (2026-11-11, commit 587e71dc6)

All five rows pass. Item 1 (builtins) fixed in 84da0d25f. Items 2 and 3 (refusal wording and its cited reason) by the host-module branch in `unresolvable_import_error` and by naming the constants-only exports-nothing reason directly. Item 4 (advice for a written module) by the constants-only exemption, checked against the file. Item 5 (copy's verdict) by the test row moving to `written`.
