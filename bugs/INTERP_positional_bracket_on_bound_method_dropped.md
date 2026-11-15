# INTERP: a positional bracket on a bound method is dropped, so the body reads None

Filed 2026-11-15 while fixing `GPU_offload_validation_modular-part5` (the
under-supplied comptime bracket). This is the *supplied* counterpart on the
method spelling; the doc for that fix was deleted with its fix.

## Symptom

A method specialized positionally at the call site ignores the bracket and
runs the body with the comptime parameter bound to `None`:

    class P:
        def f[x: Int](self) -> Int:
            return x

        def go(self) -> Int:
            return self.f[3]()


    def main():
        print(P().go())

`python3 tools/memslot.py --gb 8 --label probe-method-bracket -- python3
fire.py run .tmp/probe/method.mojo` prints `None` and exits 0. Real Mojo prints
`3`. A silent wrong answer, not even an error.

## Cause

`BoundMethod.__getitem__` (`myinterpreter.py`, `class BoundMethod`) is:

    def __getitem__(self, key):
        return self

so every positional bracket item on `obj.method[...]` is discarded before the
call. The keyword spelling does not share the hole: `eval_SubscriptExpr` sends
`attrs` through `Interpreter._bind_bracket_comptime`, which resolves
`obj.bound_func` and returns `_MojoBoundComptimeReceiver` — that is why
`self.body[f_key=show]()` works (`test_interp_oracle.py`'s
`method_keyword_bracket_binds_comptime_params`).

`BoundMethod.__getitem__` predates the keyword path, and returning `self` was
the old "brackets are ignorable" shortcut (the same one `_MojoGenericCtor` and
`_MojoSelfType` still use for type constructors, where it is harmless).

## Next step

Make `BoundMethod.__getitem__` bind by position, the way `MojoFunction.
__getitem__` does for a free function:

1. The receiver's declared parameters live on `self.bound_func`
   (`comptime_params` / `comptime_param_defaults` / `_pd`), exactly as
   `_bind_bracket_comptime` already reads them.
2. Refuse `len(values) > len(comptime_params)` and any omitted parameter with
   no default through the same `_unbound_comptime_param` /
   `_raise_unbound_comptime_error` helpers the free-function path now uses, so
   the subscript site renders the one `failed to infer parameter ...`
   diagnostic (and so `self.f[3, 4]()` on a one-parameter method is the same
   "too many" refusal, not a silent drop).
3. Return `_MojoBoundComptimeReceiver(self, bindings)`, which already exists
   for the keyword spelling.

The quick test belongs next to `test_interp_oracle.py`'s
`method_keyword_bracket_binds_comptime_params` (an `INTERPRETER_ONLY` case whose
want is `3\n` for the program above), or as a new `test_*method*bracket*`
alongside the other focused regression files. It must fail before the change
(it prints `None`, exit 0) and pass after.
