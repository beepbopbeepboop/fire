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

## Status (2026-11-01) — stage 1 LANDED: shadow frame stack for sys._getframe / f_back / f_lineno / f_code.co_name

Implemented the design above, first slice, for plain functions and methods of any module that says `_getframe`:

- **Runtime** (`runtime/fire_runtime.[ch]`, "Python-level frames"): a frame stack of `{name, file, firstlineno, lineno}`;
  `mojo_frame_enter/leave/set_line`, `mojo_getframe(depth)` (raises `ValueError: call stack is not deep enough`), and
  `mojo_frame_back/lineno/firstlineno/name/file`. A frame "object" is a word (its 1-based stack index, 0 is None). Enter pushes a
  `MOJO_CLEANUP_FRAME` record on the existing cleanup stack, so an exception unwinding past a frame pops it too (exact pairing with
  `mojo_frame_leave`, same discipline as the class-attribute cell records).
- **Compiler**: `module_gen` marks a module that mentions `_getframe` (`gen._frames_mods`); `emit_methods._frame_enter` runs before
  `_cattr_restore_begin` and `_frame_leave` rides `_cattr_leave` (every `return`, and fall-off-the-end); `emit_stmts.gen_stmt` sets
  the line per statement; `emit_methods._lower_method_call` lowers `sys._getframe(n)`; `emit_exprs._lower_MemberExpr` lowers
  `f_code`/`f_back`/`f_lineno`/`co_name`/`co_qualname`/`co_filename`/`co_firstlineno`; `resolve_shared._quick_type` types the string
  attributes. A module that never says `_getframe` emits nothing new: `compile_stdlib.py` GCC CAS 610/610 with the compiler change
  reversed (generated C unchanged for every stdlib module).
- **Tests**: `gimple_sys_getframe_names_lines_and_callers` (test_gimple_runner.py: names, lines, callers through a raise/catch, recursion,
  branches that return from two places) matches CPython; `test_selfhost.py` 3/3.

**Not done (stage 2+)**: the `<module>` frame (module-level code is not a frame, so a walk up `f_back` ends one frame earlier than
CPython); generators/coroutines (`gi_frame`, `f_generator`, `cr_frame`; their frames are not pushed); exception tracebacks
(`__traceback__`, `tb_frame`, `tb_next`: `mojo_raise` does not snapshot the chain yet); `frame.clear()` and its executing/suspended
checks; a frame word kept past its function's return (it names whatever frame reuses the slot); a read-only `f_locals` snapshot;
frames in modules that do not themselves mention `_getframe` (their functions are invisible, like C frames in CPython).
Next step: the exception snapshot (heap frame records captured in `mojo_raise`, attached as `__traceback__`), which `tb_frame`,
`tb_next`, `tb_lineno` and test_frame's `clear()` cases need.

## Status (2026-11-01, later) — stage 2 LANDED: tracebacks and the `<module>` frame

- **`<module>` is a frame** (`emit_methods._frame_enter_module`, emitted around `_gen_toplevel`'s statements), so a walk up `f_back` or a
  traceback ends where CPython's does.
- **Tracebacks**: `mojo_raise` snapshots the live frame stack once per exception (keyed by the exception's message/object pointers, so a bare
  `raise` keeps the original), before the unwind pops it. `e.__traceback__` lowers to `mojo_traceback(<current depth>)`, which builds the
  chain from the catching frame down to the raising one; `tb_frame`, `tb_next`, `tb_lineno` read an entry, and the heap snapshot records
  are valid frames for `f_code`/`f_lineno`/`f_back`. Test `gimple_traceback_chain_names_and_lines` matches CPython (names and lines through
  a re-raise).
- **Statement lines**: the parser built `if`/`while`/`raise`/`def`/... with `line=0`, so those statements carried no line (neither for
  `f_lineno` nor for the `#line` directives of the generated C). `Parser._parse_stmt_into` now stamps the line the statement starts on
  (`_stamp_stmt_line`). This is global: every module's C gains `#line` directives for those statements (semantics unchanged;
  `compile_stdlib.py` 0 failed, `test_selfhost` 3/3, `test_gimple.py` 421 pass with the same 2 failures as before).

Still open: generator/coroutine frames (`gi_frame`, `f_generator`, `cr_frame`, the suspended/executing flags `frame.clear()` checks),
`frame.clear()` itself, `__traceback__` on an exception object other than the one currently handled (it reads the last snapshot),
`f_locals`, `f_trace`, and instrumented-module-only visibility (a module that never mentions `_getframe`/`__traceback__`/`tb_frame`/`f_back`/
`f_lineno` has no frames). Run `Lib/test/test_frame.py` through the compiler next to see which of its cases now compile and which refusal is first.

## Status (2026-11-01, stage 3 first slice): a suspended generator no longer leaves its frame live

Measured first: `test_frame.py` does not compile yet (`fire.py build` refuses: generator functions with `nonlocal`/try-finally yields,
`async def t3`, `frame.f_generator`), and while looking for the first refusal a stage-1 defect turned up: the generator body's frame
(`__mgco_g_body`) stayed on the shadow frame stack across a `yield`, so `sys._getframe()` in the consuming loop named the generator,
and the resumer's `mojo_frame_leave` cancelled the generator's cleanup record instead of its own.

Landed: `mojo_coro_slice_save/restore` (`runtime/fire_runtime.c`) called from `__mojo_coro_yield`/`coro_run` (`runtime/fire_coro.c`):
a yield detaches the frame and cleanup records the body pushed since it was resumed, the next resume re-pushes them above the
resumer's current depth (so it also covers async coroutines, and the cleanup records of any kind the body holds across a yield).
`_frame_enter` names the frame after the source function (`g`, not `__mgco_g_body`; a method generator drops its struct prefix).
Test `gimple_generator_frame_is_live_only_while_running`; the stage 1/2 frame tests unchanged.

Still open: `f_generator`/`gi_frame`/`cr_frame`, `frame.clear()` and its executing/suspended checks, `f_locals`, `f_trace`, and the
generator shapes above that make test_frame.py refuse at the module level (nonlocal + try/finally yield, nested async def).
Also fixed, because master's self-host was red on it: `mojo_bytes_from_str` gained an `errors` parameter (a492e9c71) and three
callers still passed two arguments (`bytearray(text)`, `_coerce_to_bytes`, the cpp path's `bytes(text, enc)`).
