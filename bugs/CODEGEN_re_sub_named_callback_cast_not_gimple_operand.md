# CODEGEN: `re.sub(pat, named_function, src)` in a `__GIMPLE` body emits `(void *)funcptr`, which raw GIMPLE rejects

Status: OPEN. Filed 2026-11-12 by the regex-table worker on HEAD aacfc103f. Pre-existing; found while exercising the callback arm of the `re.sub` lowering for the table-address regression test.

## Symptom

A method (or lifted closure) that passes a bare top-level function as `re.sub`'s
replacement is refused by gcc even though the generated code looks legal C:

    import re

    def repl(mm):
        return "N"

    class S:
        def sub(self, s):
            return re.sub(r"[0-9]+", repl, s)

`gcc -fgimple -fsyntax-only -x c` reports, for the `__GIMPLE` body:

    _t6 = (void *)_funcptr_repl_9f63a2;
    error: invalid operand in unary operation

The same body compiles when the file is left to its `.c` suffix (gcc lowers
from C); it is the raw-GIMPLE parse (`-x c`, which `fire.py build` uses) that
rejects it.

Minimal proof it is the cast spelling and not the function pointer:

    void * fp;
    __GIMPLE void g(void) { void * t; t = (void *)fp; }   /* error: invalid operand in unary operation */
    __GIMPLE void g(void) { void * t; t = fp; }            /* accepted */

## Root cause

`emit_loops.py::_lower_re_sub_callback`'s non-closure fallback:

    cb_type, cb_val = gen.lower_expr(cb_arg)
    fn_ptr_t = gen._new_val('void *', f'(void *){cb_val}')

`cb_val` is already the file-scope `void *` value (`_funcptr_<fn>`, emitted from
`_mojo_fnaddr_...`), so the cast adds nothing — and a C-style cast is not a
legal GIMPLE operand, which is the same class of failure `_new_val` already
documents for `(int64_t)` of a literal.

## Next step

1. Reproduce: build the snippet above with
   `gimple_codegen.compile_to_gimple(src)` and gcc it with
   `-fgimple -fsyntax-only -x c -Iruntime` (a `.ci` suffix, not `.c`).
2. Emit the assignment without the cast when `cb_type` is already
   `void *`/another pointer (e.g. `gen._new_val('void *', cb_val)`), or route the
   conversion through a declared temp when a cast really is needed.
3. The quick test is the same snippet compiled with `-x c` in
   `test_gimple.py`, plus a run-vs-CPython check that the callback is invoked,
   and `test_runtime_re.py` staying green.

## Done when

The snippet compiles with `gcc -fgimple -x c` and, run, replaces digits with
`N` exactly as CPython does. Then delete this doc in that commit.
