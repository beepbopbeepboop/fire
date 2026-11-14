# 26 runtime calls are still spelled as text and skip argument conversion

Class: easy. One mechanical rewrite, 26 sites, no new logic and no second
implementation. Read `doc/GIR.md` section 4 "Stage 2" first (5 minutes).

Measured 2026-11-13 on this tree: `python3 test_gimple_lint.py unit` prints
`26 runtime calls spelled as text (baseline 26)`. Set `TEXT_CALL_BASELINE = 0`
in `test_gimple_lint.py` and the same command lists every site, one per line:

    mojo/backend_gimple/emit_calls.py:6314: mojo_list_new
    mojo/backend_gimple/emit_methods.py:6185: mojo_frozendict_check_no_mut_method
    ...

## Why it matters

GCC does not check or convert the arguments of a call in a `__GIMPLE`
function. An `int` variable passed to an `int64_t` parameter arrives with
garbage in its upper 32 bits. The only code that converts an argument is
`_repr_fix_args` (`mojo/backend_gimple/emit_infra.py`), and a call reaches it
only through `gen._emit_call`, `gen._call_expr`, or the three helpers below. A
call written as text inside `gen._emit(f"...")` or `gen._new_val(t, f"...")`
never reaches it.

## Goal

Rewrite each of the 26 sites with one of these three helpers
(`mojo/backend_gimple/emit_resolve.py`):

    # before                                             # after
    t = gen._new_val('int64_t', f"mojo_list_len ({v})")   t = gen._rt_call('int64_t', 'mojo_list_len', [v])
    gen._emit(f"  {t} = mojo_list_new ();")               gen._rt_into(t, 'mojo_list_new', [])
    gen._emit(f"  mojo_list_append_int ({l}, {x});")      gen._rt_void('mojo_list_append_int', [l, x])

Rules for the argument list:

- Each argument is a Python `str`: the temp or variable name, or literal C text.
- An argument that was literal text in the f-string stays a string:
  `mojo_raise_type_error ("bad")` becomes
  `gen._rt_void('mojo_raise_type_error', ['"bad"'])`.
- An argument that is not certainly a `str` (an `int`, a value read from a
  dict) is wrapped so it formats as before: `{n}` becomes `f"{n}"`.
- Keep the first argument of `_new_val` (the C return type) exactly as it was.
- Do not change which function is called, the argument order, or anything
  around the call.

501 other sites were already rewritten this way by a script on 2026-11-13. The
26 left are the ones the script would not touch: a string-literal argument, a
call split across several `gen._emit` lines, or a spacing other than
`name (a, b)`. Do them by hand, one at a time.

## Acceptance

- `python3 test_gimple_lint.py unit` passes with `TEXT_CALL_BASELINE = 0`.
- The emitted C is unchanged. For each file you touch, dump one program that
  exercises it before and after and compare:
  `python3 fire.py --dump hello.mojo` then `cmp` the two `hello.ci` files. A
  difference is allowed only if it is an added cast statement
  (`_tN = (int)_tM;`) directly before the call.
- No new helper, no new table, no change to `_rt_call` / `_rt_into` / `_rt_void`.

## Done when

File: `test_gimple_lint.py`
Command: `python3 test_gimple_lint.py unit`
Green with `TEXT_CALL_BASELINE = 0`. Red today if you set it to 0: it lists the
26 sites.

Partial progress is fine: convert some sites, lower `TEXT_CALL_BASELINE` to the
new count in the same commit, and leave this doc with the remaining count.

## Where to start

`mojo/backend_gimple/emit_methods.py` has 12 of the 26, eight of them the same
call (`mojo_frozendict_check_no_mut_method`). Convert one, run the command,
then do the other seven the same way.
