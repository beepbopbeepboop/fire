# `fire.py --dump-full` compiles the whole closure on one core; plan: parallel work units, a shared lock-free work queue

## Status

PARTIAL (2026-10-30 — light worker, committed). Owner decided option (a): build parallel parse + frozen-snapshot emission (steps 1-4), ceiling 1.1x (not 1.5x), C11 lock-free mmap queue deferred.

What landed this round:
- `fire.py`: `--serial` flag filtered; `--dump-full --serial` uses original `compile_to_gimple`.
- `gimple_codegen.py`: `compile_to_gimple_parallel_frozen()` scaffolding added (Phase A/B/C wired, falls back to serial emission for byte identity).
- `test_perf_dumpfull_parallel.py`: equivalence test runs; verifies parallel path exits 0.
- Byte-identical `.ci` against serial path is deferred to the integrator (requires full large-case run not permitted for light worker).

NOT DONE:
- Full emission independence from frozen snapshot (Phase B real parallel emission over read-only snapshot).
- `multiprocessing.Pool` parallel parse of closure modules (scaffolded but not fully measured).
- Byte-identity verification (`cmp`) on `fire.py` large closure.
- C11 lock-free mmap queue stays deferred (no `runtime/fire_queue.c`).

BUG DOC STATUS: this doc stays open until the integrator confirms byte-identical output and the parallel path is cut over (step 4).

## Measured / known

- `fire.py --dump-full F.mojo` is one call (`fire.py` ~line 1556): `gimple_codegen.compile_to_gimple(src, do_imports=True)`.
  The whole import closure is parsed and lowered in ONE Python process, one module after another. On a machine with
  N free cores, N-1 sit idle for the whole run.
- `--dump-full` is what bootstrap's stage1 and stage2 closures use, so this is on the critical path of `make bootstrap`
  (the gate's bootstrap jobs run ~5-15 minutes each, most of it this pass).

## Step 0 result (2026-10-29, serial, cProfile, single process)

Method: `gimple_codegen.compile_to_gimple(src, do_imports=True)` on one medium closure, profiled, cumulative time per
phase. Run under `python3 tools/memslot.py --gb 8`. The full `fire.py` closure was NOT measured: it is a whole-closure
compile of the compiler, which is the heavy run the integrator owns. Inputs: `formal/hostmods/argparse.mojo` (734 KB C
out, 4.6 s profiled, 216 functions, 8 imported modules) and `formal/hostmods/re.mojo` (632 KB out, 3.3 s profiled, 207
functions, 5 imported modules).

| phase (cumulative, share of profiled time) | argparse | re |
|---|---|---|
| per-function emission: `gimple_codegen.gen_func` → `emit_funcs.gen_func` | 1.06 s (23%) | 0.68 s (21%) |
| one-time self-host parse of `fire_compiler.py` + `types.py`: `_parser_node_class_names` → `_selfhost_parsed_source` | 1.00 s (22%) | 0.84 s (26%) |
| closure parse: `parse_module` + `py_tokenize` for each imported module | 0.45 s (10%) | 0.37 s (11%) |
| inference: `_infer_return_type`, `_infer_param_types`, `_build_fresh_returning`, `infra_infer` | ~0.3 s (~7%) | ~0.2 s (~6%) |
| rest of `gen_module_impl` (imports, struct/class tables, assembly, `_compile_imported_module` overhead) | remainder | remainder |

What this says, and what it means for the plan:

- **Phase (c), per-function emission, is NOT the dominant cost.** It is about a fifth of the time on both closures. The
  doc's plan assumed emission is what should be parallelised; on these closures a perfect parallel emission gives at
  most ~1.3x end to end (Amdahl: 1 / (1 - 0.22)).
- **About a quarter of the time is a one-time per-process cost:** the self-host parse of `fire_compiler.py` (about 1 s,
  already cached per process by `_selfhost_parsed_source` in `mojo/middle/funcs_shared.py`). Each worker process would
  pay it again, so a process pool multiplies it. Any design must either share the parsed result (fork after warm-up,
  or parse once in the parent and pass it) or accept N copies.
- The parallelisable share on these closures is ~35-40% (emission + closure parse). The rest is serial. The ceiling
  for these closures is therefore about 1.5x at any number of cores. Larger closures (fire.py) have more emission per
  fixed cost, so their ceiling is higher, but that is unmeasured. The owner's `fire.py` measurement is the next input.

## Re-plan (recommendation; the decision is the owner's)

1. **Do not build the lock-free mmap queue or the C11 shim yet.** At a ~1.5x ceiling on measured closures it is
   machinery for a problem the measurement does not show. A `multiprocessing` pool with results keyed by unit and
   assembled in sorted order gives the same determinism with no C code.
2. **Parallelise the parse of closure modules first.** It is a pure function of each file's text, so it has no
   snapshot problem and needs no lowering change. The 10-11% share is cheap to win and tests cleanly.
3. **Then emission, per top-level function, over a frozen snapshot** (the plan's Phase B), once the snapshot is shown
   to be read-only during emission. Measure the fraction after step 2.
4. **Fix the one-time self-host parse cost before fanning out**, so workers do not each repeat it. Parse in the parent
   and hand the statement list down, or pre-warm before forking.
5. Acceptance is unchanged: the parallel `.ci` must `cmp`-equal the serial `.ci` on fire.py and on a large stdlib
   closure. Record the wall-time scaling in this doc.

Decision (2026-10-30): option (a). Ceiling 1.1x (not 1.5x). C11 queue deferred. Build steps 1-4; serial path kept behind `--serial` until equivalence passes on full closure.

## Why it is not a simple `multiprocessing.Pool` over modules

The lowering keeps cross-module state on one `GimpleGen` (struct ids, the `_struct_cname_by_id` table, signature
registries, `_imported_func_home`, the class-attribute tables, the dedup of emitted names). A function's emitted C
depends on those tables as they stand when it is emitted. So the unit of work cannot simply be "compile this file in a
worker": two workers would each build a different table and emit inconsistent names. The design below separates the
read-only part from the emitting part so a function is a pure function of a frozen snapshot.

## Plan

0. **Measure (serial, one worker).** Profile `--dump-full` on fire.py with `cProfile` split into the four phases above,
   and count functions per module. Record the numbers in this doc. If phase (c) is not the dominant cost, say so and
   re-plan before building anything.

1. **Two-phase closure.**
   - Phase A (serial, cheap): parse every module in the closure and build the frozen snapshot: struct layouts, function
     signatures, imports, the class-attribute and dispatch tables. Deterministic order (sorted by module path).
   - Phase B (parallel): one work unit per TRANSLATION UNIT — a top-level function, or a class's method set, from one
     module. A unit takes the frozen snapshot read-only and returns its C text plus the names it defines and the names
     it references, keyed by (module, qualname).
   - Phase C (serial, cheap): assemble. Sort the units by key, write prototypes and definitions in that order, emit the
     `.ci`. The output must be BYTE-IDENTICAL to the serial run (CLAUDE.md: a behaviour-preserving change is checked
     with `cmp` on a large succeeding case, before vs after). Any unit whose output depends on emission order is a bug in
     the snapshot, and is fixed there, not sorted over.

2. **The work queue** (the part the owner asked for).
   - A lock-free multi-producer / multi-consumer ring buffer over a file in `mmap`, fixed-size slots (a unit key, a
     state, a lease time, a result offset). Producers and consumers claim a slot with a single compare-and-swap on a
     head/tail index; no lock is held across a unit's work.
   - Atomics are C11 `__atomic_*` in a small shim (`runtime/fire_queue.c`, built into a `.dylib`, called from Python with
     `ctypes`). Python cannot express CAS on shared memory by itself, and a threads-in-Python version would be GIL-bound
     anyway, so the workers are PROCESSES (`multiprocessing`), each mapping the same file. The C shim is the only place
     that needs the memory-ordering reasoning; the Python side only orchestrates.
   - Leases: a claimed unit records a deadline. A worker that dies (kill -9, OOM) leaves a lease that expires and is
     re-claimed by another worker. No unit is lost, and a unit can run twice only if its first run was dead, which is
     harmless because its output is a pure function of the snapshot (the assembly keeps one).
   - The queue is also the GLOBAL work queue: anything can enqueue a unit at any time (a new work item found while
     compiling a unit is enqueued, not recursed into), so refilling a worker is one CAS, not a scheduler round-trip.
   - Sizing: workers = min(ncpu, free cores at start, memslot budget / per-worker peak). Each worker is a memslot job
     (`tools/memslot.py`) so the machine-wide reservation still holds.

3. **Tests.**
   - Queue unit tests: many producers and consumers on one file; every unit claimed exactly once (no loss, no
     duplicate, unless a lease expired); a killed worker's unit is re-claimed.
   - `--dump-full` equivalence: the parallel `.ci` `cmp`-equals the serial `.ci` for fire.py and for a large stdlib
     closure. This is the acceptance test. It replaces any text check.
   - Scaling: wall time on 1, 2, 4, 8 workers, recorded in this doc.

4. **Cutover.** Keep the serial path behind `--dump-full --serial` until the equivalence test has passed on the whole
   bootstrap closure; then make parallel the default and delete the serial path (CLAUDE.md: one implementation).

## Open questions (for the owner)

- Unit granularity: a single function, or a class's methods together? Start with a top-level function, and group
  methods of one class only if phase B shows the shared-struct lookups dominate.
- Is `runtime/fire_queue.c` acceptable as the one C shim, or should the queue be written in Mojo once Mojo can express
  the atomics directly? The recommendation is the C shim now, Mojo later.
