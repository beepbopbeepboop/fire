# A `for` over an unknown-API generator binds each yield as an UNTAGGED word

Class: small. Residual of
`bug:CODEGEN_loop_over_plain_function_returning_generator` (that doc's loop
lowering is now handle-driven; this is the one value-kind hole it cannot
close from the information it has).

## Symptom

When a `MojoGenerator *` reaches a `for` loop with no
`_generator_var_api` entry (it escaped another function through a plain call),
`_gen_for_unknown_generator` (mojo/backend_gimple/emit_loops.py) drives the
handle through the generic `__mojo_gen_resume` / `__mojo_gen_value` entry
points. The generic protocol stores the yield in a bare `int64_t` slot and
carries no value-kind, so the loop target is a word of unknown kind. An `int`
or a string pointer renders/compares right through that path, but a generator
whose declared yield kind is `double` (or `bool`) puts the DOUBLE'S BIT
PATTERN in the target, and `print(x)` shows that integer:

    def fr(n):
        i = 0
        while i < n:
            yield i * 0.5
            i += 1
    def make(v):
        if isinstance(v, int):
            return fr(v)
        return iter(v)
    def main():
        for x in make(3):
            print(x)
    main()

CPython prints `0.0 / 0.5 / 1.0`; the compiled program prints
`0 / 4602678819172646912 / 4607182418800017408`. Exit 0, no diagnostic.
(The single-return shape `def make(n): return fr(n)` is NOT affected:
`_fn_returns_generator` records the api on that call's temp, so the known-API
lazy arm — which reads `<base>_value` and unboxes the double — runs.)

## Cause

The known-API arm reads `<base>_value`, whose trampoline in
`mojo/middle/coro.py::_C_TRAMPOLINE_TMPL` unboxes by the generator's own
declared `value_kind`. The generic entry points have no such fact: the kind is
recorded only in the runtime's per-handle signature table
(`_gen_handle_peek`, populated by `mojo_gen_note_a3` with a vkind), and a
handle that is only ever passed through a plain function's return is never
registered there.

## Fix (next step)

Two halves, both small, and the second is what makes the value readable:

1. Where the handle ESCAPES as a `MojoGenerator *` return value
   (`emit_stmts.py`'s ReturnStmt arm, whose sibling already does this for a
   return slot that is a plain word), emit `mojo_gen_note_a3(handle, vkind)`
   with the api's `value_ctype` mapped exactly like the two existing sites
   (`{'int64_t': 0, '_Bool': 1, 'double': 2, 'char *': 3}`).
2. In `_gen_for_unknown_generator`'s handle arm, read the value by the
   registered kind instead of raw: a runtime `mojo_gen_handle_value(w)` that
   peeks the signature and returns `mojo_box_from_double(value)` for vkind 2
   (the `sg->value` fn is `double (*)(void*)` there), a bool/int box as
   appropriate, else the raw slot word — i.e. exactly `mojo_next_word`'s
   value switch (runtime/fire_runtime.c ~18848), which cannot be reused
   directly because it raises StopIteration on exhaustion and the loop needs
   a non-raising step.

A handle whose signature is still unregistered (a different module compiled
separately, a container round-trip) keeps the raw-word behaviour; that is the
honest answer for a value whose kind genuinely is not known.

## Done when

The program above prints `0.0 / 0.5 / 1.0` compiled, and a `bool`-yielding
twin prints `True / False`, added as a case in
`test_gimple_runner.py::test_for_loop_over_plain_function_returning_a_generator`.
