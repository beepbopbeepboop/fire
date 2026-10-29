# `fire.py --dump-full` compiles the whole closure on one core; plan: parallel work units, a shared lock-free work queue

## Status

OPEN. Planned, not started. Filed 2026-10-29 by the orchestration owner for a worker (or the owner) to implement.

## Measured / known

- `fire.py --dump-full F.mojo` is one call (`fire.py` ~line 1556): `gimple_codegen.compile_to_gimple(src, do_imports=True)`.
  The whole import closure is parsed and lowered in ONE Python process, one module after another. On a machine with
  N free cores, N-1 sit idle for the whole run.
- `--dump-full` is what bootstrap's stage1 and stage2 closures use, so this is on the critical path of `make bootstrap`
  (the gate's bootstrap jobs run ~5-15 minutes each, most of it this pass).
- NOT YET MEASURED: how the time splits between (a) parsing and the cross-module registries, (b) return-type and
  signature inference (`resolve_shared`, `infra_infer`), (c) per-function emission (`emit_*`), (d) the final
  assembly. Step 0 below measures it. Nothing is parallelized before that.

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
