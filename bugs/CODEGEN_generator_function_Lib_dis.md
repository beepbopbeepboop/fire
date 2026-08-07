# CODEGEN_generator_function: Lib/dis.py

## Status (updated 2026-08-06)

**STILL FAILING**, confirmed reproducing identically against current
master (`2b0c4c5`) — the 2026-07-30 note's diagnosis was correct; this
elaborates it with the exact mechanism and impact.

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/dis.py
[gimple_codegen] generator '_get_instructions_bytes' not eligible for C++ coroutine path, falling back to honest refusal: _get_instructions_bytes: generator parameter 'arg_resolver' has unsupported type 'ArgResolver *' (only int64_t/double/_Bool/char*/MojoList*/MojoDict*/MojoSet* parameters are supported for compiled generators)
Error building: cannot compile module: function(s) _get_instructions_bytes (generator function(s), contain a `yield`/`yield from`) — ... falling back to interpreting this module from source instead
```

**Classification: `bugs/hard/CODEGEN_generator_struct_typed_param_
refused.md`** — `_get_instructions_bytes(code, linestarts=None,
line_offset=0, co_positions=None, original_code=None, arg_resolver=None)`
takes `arg_resolver`, whose real, correctly-inferred type is
`ArgResolver *` (a user-defined class instantiated by every real caller
— `disassemble()` constructs one and passes it in). `_gen_cpp_generator_
unit`'s parameter-support step deliberately refuses ANY parameter type
outside a fixed scalar/container allow-list
(`int64_t`/`double`/`_Bool`/`char *`/`MojoList *`/`MojoDict *`/
`MojoSet *`) — struct-typed parameters were never brought into scope for
the coroutine codegen project. Because this refusal happens for a
MODULE-LEVEL (not imported) generator function, it escalates to a fatal
whole-module `RuntimeError` for `dis.py` itself — despite the error text
claiming a graceful source-fallback, `mojo.py build`'s CLI path does not
actually take that fallback for the top-level file being built (see the
hard-bug doc's Symptom section for why, and its "What a fix would need"
section for why simply widening the type allow-list likely just moves
the failure into the generator's BODY the first time it calls a method
on `arg_resolver`, e.g. `arg_resolver.get_argval_argrepr(op, arg,
offset)` at dis.py:786).

Not fixed here — this is a genuine, documented codegen scope boundary
(not a narrow accidental bug), and per this task's guidance, only
narrow/safe fixes clearly outside the shared inference machinery were in
scope for this pass.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/dis.py
