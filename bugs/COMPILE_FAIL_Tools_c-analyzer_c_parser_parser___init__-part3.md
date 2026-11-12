# Import floor: `.iterutil` — `next(...)` on a `MojoList *` receiver (part 3 of 4)

Part 3 of 4 of `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_parser_parser___init__.md`
(SPLIT 2026-11-11). This part is the C-side import-floor refusal of
`c_common/iterutil.py` in `c_parser/parser/__init__.py`'s full import chain.
The sibling parts: part 1 (`bugs/mid/…-part1.md`, the companion's tuple-target
family), part 2 (`bugs/…-part2.md`, the companion's dict-store slot) — the
companion `.cpp` work, independent of this one — and part 4
(`bugs/mid/…-part4.md`, the `..info` refusal, the other half of this floor).

## Summary

Building `c_parser/parser/__init__.py` from a copy of the upstream
`Python-3.14.6/Tools/c-analyzer/` tree refuses the imported module
`c_common/iterutil.py` before the companion `.cpp` step is reached:

```
# ERROR: compiling imported module '.iterutil' from .../c_common/iterutil.py:
  `next(...)` on next(IdentExpr) (receiver typed `MojoList *`) has no lowering
```

The site is `iterutil.peek_and_iter`: `items = iter(items)` then `next(items)`
— a REBOUND list-iterator local (the local is first a list, then its
iterator), the cheaper of the two `next(...)` floor shapes the parent doc's
2026-10-04 entry analysed. This refusal decides whether the `_iter_source`
module compiles at all under the full import chain.

**RE-MEASURE FIRST — this part may already be closed on master.** The
measurement above is from 2026-10-29. Since then master carries
`b3814dbfd` ("iter() on an already-declared container parameter binds a
cursor, so next(items) after items = iter(items) compiles
(iterutil.peek_and_iter); test: gimple_iter_rebinds_a_parameter_to_a_cursor")
and `902e17b09` ("process_filenames and iterutil now compile; test:
cpp_coroutine_iter_many_callable_param") — both dated 2026-10-30, i.e. AFTER
the parent doc's last entry. Run the repro below: if the `.iterutil` refusal
is gone, this doc is fixed-on-master; delete it in the same commit and record
the measurement in the commit message. The pinning regression for the shape
is `gimple_iter_rebinds_a_parameter_to_a_cursor` in `test_gimple_runner.py`
(run it to confirm it still passes).

## Repro / measure

```
rm -rf .tmp/ca && cp -R /Users/mrs/net/Python-3.14.6/Tools/c-analyzer .tmp/ca
python3 tools/memslot.py --gb 8 --label ca-parser-build -- \
  python3 fire.py build -o .tmp/out/rNN .tmp/ca/c_parser/parser/__init__.py
```

arm64. Grep the build output for `compiling imported module '.iterutil'`.
A cheaper first check, same signature: build the module alone,
`python3 tools/memslot.py --gb 8 --label ca-iterutil -- python3 fire.py build
-o .tmp/out/rNN .tmp/ca/c_common/iterutil.py`. (Note: the standalone build can
be green while the in-chain spelling is refused — the parent doc's 2026-09-30
entry recorded exactly that split for a sibling module; the Done-when below
is the in-chain check, so do not stop at the standalone one.)

## Root cause / next step (if the re-measurement shows it still open)

The C-side emitter's `next(...)` lowering refuses a receiver typed
`MojoList *` — the rebound-iterator shape. The parent doc's 2026-10-04 entry
(item 1) is the analysis: read it before starting, in particular its pointer
to the sibling doc `bug:CODEGEN_next_on_bound_list_iter_cursor_off_by_one`
(now deleted; its fix is the `b3814dbfd` commit above) and its warning that
the shape "is a REBOUND list-iterator local, which the compiler already
supports elsewhere". The fix shape is the `iter()` rebinding → cursor binding
that `b3814dbfd` landed for the parameter case, if the 2026-10-29 refusal
survives that commit for some other reason (measure WHY before extending).

## Done when

1. Rebuilding `.tmp/ca/c_parser/parser/__init__.py` reports NO
   `# ERROR: compiling imported module '.iterutil'` line (the floor list, if
   any, contains only the `..info` refusal tracked by part 4).
2. If the re-measurement found it already fixed on master: this doc is deleted
   in the same commit, `test_gimple_runner.py::gimple_iter_rebinds_a_parameter_
   to_a_cursor` passes, and the measurement is recorded in the commit message.
3. If it was still open: a regression next to `gimple_iter_rebinds_a_parameter_
   to_a_cursor` in `test_gimple_runner.py` covering the exact refused shape
   fails before the fix and passes after; `test_gimple_runner.py` run once in
   full shows no NEW failures.
