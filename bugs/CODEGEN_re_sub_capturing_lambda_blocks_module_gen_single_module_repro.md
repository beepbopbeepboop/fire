# CODEGEN: a capturing `re.sub` lambda refuses, so the sanctioned single-module repro of `module_gen.py` no longer generates C

Status: OPEN, filed 2026-11-12 by a worker landing the `enumerate` unpack
shadow-store fix. Not a wrong-answer bug — the compiler refuses honestly — but
it regressed the measurement every other single-module bug doc in this tree is
verified with.

## Symptom

`compile_module_to_c` on `mojo/backend_gimple/module_gen.py` (the sanctioned
single-module repro of that module) now stops during `gen_module_impl` with:

```
RuntimeError: re.sub(..., <capturing lambda>, ...) is not supported:
a capturing lambda is a MojoBoundMethod, not a bare function pointer, and
this codegen cannot wire its env into the regex callback ABI. Use a
non-capturing lambda or refer to a closure (IdentExpr) instead.
```

The instance is `mojo/backend_gimple/module_gen.py:19994`:

```python
self.generated_cpp = re.sub(
    r'@@CSYM:([A-Za-z0-9_]+)@@',
    lambda _m: self._func_csym(_m.group(1)), self.generated_cpp)
```

The lambda captures `self`, so the lowering's `cb_val in gen._closure_vals`
test routes it to the refusal (`glo._lower_re_sub_callback`,
`mojo/backend_gimple/emit_loops.py`).

## Why it matters

Before the 2026-11-12 regex-callback work (99d4fe467 / 4cf72bd58 /
c8433b8f3) this program generated C, and the import-extern and unpack-loop
docs measured their instances by compiling it. It now cannot be generated at
all, so those docs' full-module measurements are blocked, even though the
reduced per-bug repros still work.

## What was measured

    python3 tools/memslot.py --gb 8 --label mg-repro -- python3 .tmp/repro_mg.py

where `repro_mg.py` reads `mojo/backend_gimple/module_gen.py`, calls
`build_stdlib_dylib.compile_module_to_c(src, path, 'module_gen')`, writes the
C and runs `gcc -fgimple -Os -g -ftrivial-auto-var-init=zero -c`. The call
raises the RuntimeError above before any C is written; peak memory 0.2 GB.

## Next step

Teach `_lower_re_sub_callback` the capturing-lambda case it currently refuses:
materialize the bound method's env and pass it as the callback's `env`
argument (the non-capturing/named-callback arms already compute `fn_ptr_t` and
`env_t`), and make the C++/C trampoline read `self`/captures from `env` — the
same shape `_closure_vals` already carries for other bound-method callbacks.
Until that lands, compile the full-module repro from a revision before
99d4fe467, or keep using reduced per-bug programs.
