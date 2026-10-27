# CODEGEN: an inline cast in a call argument is a hard compile error in a function without setjmp

**State: FIXED 2026-10-20 (integration of the two CODEGEN worker branches onto
master; the selfhost step of `suite.py check` was the first full build of the
merged tree and this is what broke it).** The emitted shape
`mojo_strlen ((char *) key)` — a cast sitting *inside* the argument list of a
call — is rejected by `gcc -fgimple` in `__GIMPLE`-tagged functions, and every
function in this backend gets that tag exactly when it does NOT use setjmp
(`_sig_kw = '' if gen._func_used_setjmp else '__GIMPLE '` in emit_funcs.py and
emit_loops.py). The same line parses in a setjmp-tagged function, which is why
the defect sat in the tree silently: the check that emitted it (the starless
dict key-length check, `1ad58fde`) was written, measured and tested before the
three loops that happen to live in no-setjmp functions were ever compiled
together with it in one build.

## What I ran and what I saw

`python3 test_selfhost.py` on the merged tree: the selfhost build's `.ci`
(45.7MB) fails `gcc-mp-15 -fgimple` with three paired errors, one per dict
loop in the selfhost closure:

    mojo/middle/solvers.py (mojo_middle_solvers_DispatchSolver__plan_dispatch_tables):
      error: expected expression before '(' token
      error: invalid argument to gimple call
      _t130 = mojo_strlen (<<< error >>>);
    (the same pair in _scan_callsite_param_kinds__visit_call, coro.py, and
     myinterpreter__MojoTestSuiteRunnerSkipToken___call__)

All three sites are the key-length check:

    _t129 = mojo_dict_iter_key (_t126);
    _t130 = mojo_strlen ((char *) _t129);

The `<<< error >>>` masking and the Python-line attribution in gcc's output
are this build's raw-channel feature and drifted; the true C line is the
`mojo_strlen` line. (A #line-stripped copy of the same file also corrupts the
four pool strings that CONTAIN the text `#line ` — `static char * _slit_15440
= "#line ";` — which looks like an escaper bug and is not; strip by line
prefix, not by substring.)

## Why

Under `-fgimple` GCC parses every statement as a GIMPLE statement and a GIMPLE
call takes SIMPLE operands. A cast expression in the argument list is not one.
Minimal probes on gcc-mp-15: in a `__GIMPLE`-tagged function, `f2 ((char *) p)`
fails whether the cast is a no-op, a const-strip, or a `((int64_t))` on a
literal; `f2 (p)` passes; and `q = (char *) p; f2 (q);` passes. In an
untagged function every shape passes. The 30 check sites in the merged build
split exactly 27 tagged-fine / 3 tagged-broken along the setjmp boundary: 27
live in setjmp-tagged functions (try/except bodies, the stub templates), 3 in
plain ones.

## Fix

`mojo/backend_gimple/emit_loops.py`, both emission sites (the star branch and
the starless branch): hoist the cast to its own CONVERSION statement,

    _key_cstr = gen._new_val('char *', f"(char *) {key_tmp}")
    _klen = gen._new_val('int64_t', f"mojo_strlen ({_key_cstr})")

Behavior is unchanged in both tag classes — the cast is the same conversion,
one statement earlier. Verified: `test_selfhost.py` 3/3 on the merged tree.

## Adjacent exposure (latent; none of it fires in this build)

The same "cast inside a call argument" shape is emitted by other idiom
families — `mojo_cstr_slice ((char *) ...)`, `mojo_tagged_* ((int64_t){box},
...)`, `mojo_obj_getattr((void *)obj, ...)` — but a scan of the selfhost `.ci`
places every one of them in a setjmp-tagged function or in the untagged stub
templates, so none fails today. If any of them is ever emitted inside a
no-setjmp function it breaks identically; the general rule is "hoist casts
out of call arguments" (see also the `sizeof(T)` note in emit_calls.py, which
applies the same discipline to a different non-simple operand).
