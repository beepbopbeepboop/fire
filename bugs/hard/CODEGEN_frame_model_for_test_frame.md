# Frame introspection for test_frame.py: research for Sonnet 5.5

Owner direction (2026-10-30): maximal compatibility with Python; eventually fix all bugs. The owner has latitude on how to frame the model, but compiled code must coexist with the C API (external calls such as fopen and write) and its usual limits. Research and ANSWER, do not start a fix.

## The question
Does the compiler get a frame model (option b) or keep test_frame.py refused (option a)?
The surface in question: sys._getframe, f_back, clear, f_generator, gi_frame, tb_frame.

## What to answer
1. What is the smallest frame model that makes these work for generators and ordinary functions, and what does it cost at run time?
2. Which of these can never be exact in compiled C (for example a live f_locals), and what limit should the owner accept?
3. Recommend (a) or (b) and give the first step.

Source context: frame model feature for test_frame.py (bug fixed: generator division-by-zero and method self-capture); not the frame-model feature itself.

## Status (2026-10-31) — the answer; no code landed

Measured this round: neither engine has any frame model today. `grep` finds no `_getframe`, `f_back`,
`tb_frame`, `gi_frame` or `f_generator` in `myinterpreter.py`, `gimple_codegen.py`, `mojo/` or `runtime/`;
the only run-time exception state is `mojo_exc_*` (a message, a type tag and one object pointer,
fire_runtime.h:528) and source positions exist only as compile-time `#line` directives
(`emit_stmts.py:70-95`). `Lib/test/test_frame.py` uses exactly the surface the doc lists
(`sys._getframe(n)`, `f_back`, `f_lineno`, `f_code.co_firstlineno`, `f_generator`, `gi_frame`,
`tb_frame`, `tb_next`, `frame.clear()`, `f_trace`).

### Recommendation: (b), staged, and OFF unless the program asks for it

1. **The model: a shadow frame stack, enabled per compile by a static scan.** The scan looks for
   `sys._getframe`, `inspect.currentframe/stack/getframeinfo`, `traceback`, `__traceback__`, `tb_frame`,
   `gi_frame`, `cr_frame`, `f_back`, `f_generator` over the compile's closure. When it finds none, nothing
   is emitted and the cost is zero, so every existing program and the byte-identical-C rule are untouched.
   The flag is part of the compile's CAS key (it changes the OUTPUT, same reasoning as `auto_gpu` in
   `cas.compile_key`).
2. **When on, per call:** a function whose frame is reachable gets a stack-allocated
   `MojoFrame { MojoFrame *back; const MojoCodeInfo *code; int32_t lineno; void *gen; uint8_t flags; }`,
   pushed in the prologue and popped on every exit path (the same exit paths `exc_depth` cleanup already
   walks in `emit_funcs`). `MojoCodeInfo` is a static per-function table (`co_name`, `co_qualname`,
   `co_filename`, `co_firstlineno`), emitted next to the `#line` data. `lineno` is updated by one store per
   statement, where `emit_stmts.py` already emits `#line`. A `try` records the frame top at entry and the
   catch path restores it, so a `longjmp` unwind cannot leave stale frames.
3. **Tracebacks:** `mojo_raise` snapshots the live chain into heap `MojoFrameObj`s (frames are stack
   objects and die on pop; `tb_frame` must outlive them), attached to the exception object as
   `__traceback__` with `tb_next/tb_lineno/tb_frame`. This is also what makes `e.__traceback__.tb_frame.f_back`
   work after the raise.
4. **Generators and coroutines:** the frame record is embedded in the generator object (the A3 stack-switch
   runtime's handle), pushed on resume and popped on yield or finish. That gives `gi_frame`, `gi_running`,
   `f_generator` (the handle; `None` for plain functions, as the test asserts), `f_back` = the resumer while
   running and `None` while suspended, and the `suspended`/`executing` flags `frame.clear()` needs to raise
   `RuntimeError`.
5. **C API coexistence:** only compiled-Python functions have frames. A C callee (`fopen`, `write`, a qsort
   callback trampoline) is invisible, exactly as CPython shows only Python frames, so the chain stays
   correct across external calls. A Python callback called from C pushes its own frame on top of whatever is
   current, and `f_back` skips the C frames.

### What can never be exact in compiled C (the limits to accept)

- **Live `f_locals`.** C locals live in registers or the stack, and under `-fgimple` the compiler does not
  keep an addressable name table. A read-only SNAPSHOT dict of the locals the codegen spilled to the frame is
  possible later (stage 2); writes through `f_locals`, and `f_locals` aliasing the real variables
  (the PEP 667 view), are not.
- **Tracing.** `sys.settrace`, `f_trace`, `f_trace_lines/opcodes` and `test_lineno_with_tracing`'s
  trace-dependent line reporting: `f_lineno` is exact at statement granularity, per-opcode events are not.
- **Reference-lifetime assertions.** Tests like "the reference was released by `.clear()`" and the
  refcycle checks rest on CPython's refcount and cycle GC. The compiled runtime frees by ownership analysis,
  not refcounts, so those cases cannot pass and should be listed in `EXPECTED_FAILURES`-style with that
  reason rather than chased.
- **`f_code` identity and mutation** beyond the read-only metadata above (`replace()`, bytecode, `co_code`).

### Cost

Estimate, NOT measured (no frame code exists to measure): about two stores and two loads per instrumented
call plus one store per statement, so low single-digit percent on call-heavy code when the flag is on and
exactly zero when it is off. Gate cost: edits under `mojo/backend_gimple/*` and `runtime/` change
`compiler_fingerprint()`, so one cold rebuild (~8 min dylib, ~32 min bootstrap, measured elsewhere in this
queue) plus `make gate`; the stdlib-dylib `skip` count and `compile_stdlib.py` `U` must not rise, and the C
of a large program with no frame use must be byte-identical before and after.

### First step (next round)

Runtime: `mojo_frame_push/pop/top` and the `MojoFrame`/`MojoCodeInfo` structs in `fire_runtime.[ch]`
(update the ABI census). Compiler: the static scan in `module_gen.py` (sets `gen._frames_enabled`), prologue/
epilogue emission in `emit_funcs.py`, the per-statement line store in `emit_stmts.py`. Lowering of
`sys._getframe(n).f_code.co_name` / `.f_lineno` / `.f_back` in `emit_methods.py`. Test: a three-function chain
printing `sys._getframe(0..2).f_code.co_name` and `f_lineno`, run-compared with CPython (the
`test_interp_oracle.py` pattern), plus one program with no frame use whose `.ci` must `cmp` identical to
master's.
