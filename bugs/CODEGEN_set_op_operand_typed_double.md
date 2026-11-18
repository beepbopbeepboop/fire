# A set-typed loop local is lowered as `double` for a set-operation operand

Class: high. Hard gcc failure in the `bootstrap-stage2-cc` gate (the
self-host bootstrap TU), measured 2026-11-18 on master 2fb10b162 with the
function-scoped-import fix already applied.

## Symptom

    mojo/middle/coro.py:6387: error: invalid types in conversion to integer
     6387 |             resolved = {}

(gcc points at the loop body start; the invalid statement is the set
difference at `coro.py:6411`.) Reproduce:
`python3 tools/suite.py bootstrap-stage2-cc` (stage1 passes; stage2 gcc
fails with this error, twice — the expression is evaluated in two
branches of the same `and`).

## The generated C (stage1/fire.ci, `_scan_callsite_param_kinds__classify`)

The local is a boxed word:

    int64_t kinds;

The SAME variable, `None in kinds` (line 6411, first use) lowers correctly
through the boxed-word convention:

    _t67 = (MojoSet *)kinds;
    _t68 = mojo_set_contains_none (_t67);

but `kinds - {None}` (same line, second use) lowers it as a DOUBLE:

    _t72 = mojo_box_double (kinds);
    _t73 = (MojoSet *)_t72;
    _t74 = mojo_set_difference (_t73, _t71);

`double` → `MojoSet *` is not a legal GIMPLE conversion, hence the error.

## Root cause (as far as traced)

`mojo/backend_gimple/emit_exprs.py`'s set-op lowering
(`_lower_binary_set_op`, the `-` arm) receives the left operand's lowered
C type as `double` for `kinds` and funnels it through `_lb_as_set`, which
creates a `double` local for a non-`MojoSet *` operand and casts it —
legal for a real double, fatal for a set word. The `in` operator's own
lowering read the same variable as a word. So the binary-op path and the
`in`-op path disagree on the variable's internal type: one says
`double`, the other the boxed word. The C declaration (`int64_t`)
follows the word view; only the set-difference operand site used the
`double` view.

`kinds` comes from the dict-items unpack `for pname, kinds in
slot.items()` and is rebound by `kinds = _merge_list_holes(kinds)`
(annotated `-> set`). The `double` view is presumably a stale/unified
local type recorded earlier for the same name (whole-function
unification territory — see `gen_module_impl`'s note that a re-widening
via whole-function unification is the known failure mode for reassigning
a local). Not pinned to a single write site yet.

## Fix direction

The set-op lowering must not trust an operand type that is not a set
view: for an operand whose variable is a boxed container word (the
`int64_t` slot convention), `_lb_as_set` should cast the WORD, not box
it as the recorded scalar type. Separately, find where `kinds`'
`double` view is recorded and why it wins over the set view for one
operand only.

## Status

Blocks `bootstrap-stage2-cc` (with
CODEGEN_frozenset_global_decl_word_vs_ptr.md). NOT fixed by the
function-scoped-import fix (that one's errors are gone from the gate's
gcc output; regression:
test_gimple_function_scoped_import_extern.py / suite
`reg-gimple-function-scoped-import-extern`).
