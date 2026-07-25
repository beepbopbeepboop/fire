# CODEGEN: a bound method referenced as a plain value (not called) fails to compile

## Repro

```python
class C:
    def b(self):
        return 42
    def a(self):
        f = self.b       # reference the method as a value, don't call it here
        return f()

def main():
    c = C()
    print(c.a())
main()
```

- `python3 mojo.py run repro.py` (interpreter): correct — prints `42`.
- `python3 mojo.py build repro.py -o out`: fails to compile:
  ```
  repro.py:5:13: error: 'C' has no member named 'b'
  ```

Calling the method directly (`return self.b()`, no intermediate variable)
compiles and runs correctly — the bug is specific to referencing a bound
method as a value (to store, pass as a callback, etc.) rather than calling
it immediately. Definition order doesn't matter (confirmed with `b` defined
both before and after `a` in the class body — same failure either way).

Real stdlib trigger: `Lib/cmd.py:112`:
```python
readline.set_completer(self.complete)
```
(`self.complete` passed as a callback value to `readline.set_completer`,
not called) — `bugs/COMPILE_FAIL_cmd.md`. `Cmd.complete` is a real method
defined later in the same class (line 261); the compiler reports `'Cmd' has
no member named 'complete'; did you mean 'completekey'?`, confusingly
suggesting an unrelated attribute.

## Root cause

Not yet traced into `gimple_codegen.py`'s member-resolution code — worth
investigating whether the struct/class member-lookup machinery used when
lowering a `MemberExpr` in a CALL position (`self.b(...)`) differs from
the one used when a `MemberExpr` appears as a plain value-producing
expression (`f = self.b`), and the value-position path is missing method
lookup entirely (only checking data fields, hence the "no member named"
error, and the `did you mean` suggestion only searches data-field-shaped
names like `completekey`).

## Impact

Storing/passing a bound method as a first-class value (for a callback,
decorator, functools.partial, event handler registration, etc.) is a
common Python idiom — this is likely to affect a meaningful number of real
stdlib files beyond `cmd.py`.

## Suggested fix

Not yet planned — needs investigation into how `gimple_codegen.py` lowers
`MemberExpr` in a CALL context (where it evidently already knows how to
resolve a method by name — reuse whatever that lookup does) versus a
plain expression-value context (where it currently seems to only search
data fields). The likely correct representation for "a method referenced
as a value" is some form of bound-method/closure value (capturing both the
struct instance pointer and the method's function pointer) that can later
be invoked via a call — check whether this codegen already has a bound
value representation used elsewhere (e.g. for storing free functions as
values, closures, or callback registration) to reuse rather than invent a
new one.

## Status
**Fixed**

Root cause confirmed: `_lower_MemberExpr` in `gimple_codegen.py` only had two
outcomes for `obj.name` — a real struct field, or fall through to the
generic "unknown struct field" handling, which blindly emitted `obj->name`
regardless of whether `name` was ever a field. Calling `self.b(...)`
directly worked because that shape is intercepted earlier, in
`_lower_method_call`/`_lower_struct_method_call`, which never reaches
`_lower_MemberExpr` at all — a bare `self.b` (no call) has no such
intercept and fell all the way to the invalid field-access fallback.

Fix: a new bound-method representation, `MojoBoundMethod *` — a small
runtime struct pairing the method's real C function pointer with the bound
`self` receiver (`runtime/mojo_runtime.h`: `MojoBoundMethod`,
`mojo_bound_method_new`, `mojo_bound_method_call_0..4`). This reuses the
existing "free function referenced as a value" static-funcptr mechanism
(`_funcptr_<name>` static vars, used elsewhere for exactly this "GIMPLE
forbids `&func` as an rvalue" problem) for the function-pointer half, and
mirrors `_lower_fnptr_call`'s existing runtime-helper-indirection pattern
for the call side. No prior bound-value/closure representation existed in
this codegen to reuse directly (closures capture a struct instance's own
locals via an env pointer, a different problem), so this is a new, minimal
addition consistent with those existing conventions.

Changes:
- `gimple_codegen.py`: `_lower_MemberExpr` now recognizes `struct.method`
  used as a value (checked via `func_return_types`/`_struct_method_signatures`,
  the same "is this a method" signal `_lower_struct_method_call` already
  trusts) and routes to the new `_lower_bound_method_value`. The call-site
  dispatch in the `CallExpr` lowering now checks for a `MojoBoundMethod *`
  (or its int64_t-boxed form, via the same `_get_actual_type` convention
  used for every other struct pointer this codegen sometimes boxes) before
  falling into the plain-function-pointer path, routing to the new
  `_lower_bound_method_call`. A `_bound_method_ret_types` side table (reset
  per function, alongside `_actual_types`) tracks the real return type
  across the value's lifetime so the call site narrows correctly instead of
  assuming `int64_t`.
- `runtime/mojo_runtime.h`: added `MojoBoundMethod`, `mojo_bound_method_new`,
  `mojo_bound_method_call_0..4`, and a `<stdlib.h>` include (needed for
  `malloc` — `mojo_runtime.c` includes this header before its own
  `<stdlib.h>`, so the header must self-provide it).
- `test_gimple.py` / `test_gimple_runner.py`: added a compile-only and a
  build+run+check-output regression test respectively, covering the full
  `f = self.b; f()` round trip.

Verification:
- Manual repro: `python3 mojo.py build repro.py -o out && ./out` now prints
  `42` (previously a hard C-compiler error).
- `make check-selfhost`: pass.
- `python3 test_gimple.py` / `test_gimple_runner.py` / `test_module_cache.py`:
  all green (181/181, 10/10, 64/64).
- Full from-scratch stdlib dylib rebuild: 0 "skip <module>:" lines before
  AND after (this repo's stdlib already compiled 100% cleanly going in, per
  `bugs/compile-stdlib-boxing-stub-regression` history) — no regression.
- `Lib/cmd.py`: the original `'Cmd' has no member named 'complete'` error is
  gone. Two unrelated, pre-existing errors remain further into the file
  (`invalid conversion in gimple call` near line 353, `non-trivial
  conversion`/`type mismatch in binary expression` near line 423) — out of
  scope for this bug.
