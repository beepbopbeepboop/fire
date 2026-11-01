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

## CORRECTION (2026-10-31, later) — the cProfile table below is wrong about shares; use the numbers here

`cProfile` inflates call-heavy code (hundreds of thousands of tiny calls) by 3-4x, so the table
below overstated `ast_rewriter` (22% profiled) and the gimplegen scan (27% profiled). Measured with
`time.perf_counter` wrappers around single outermost calls (no profiler; `/tmp`-style script in the
commit message of this change), `compile_to_gimple(fire.py, do_imports=True)` on a loaded 18-core machine:

| | seconds |
|---|---|
| total (CPU == wall, single thread) | 197 (before `f77b8ec21`) |
| `_compile_imported_module` (227 imported-module compiles, includes their parses) | 189 |
| `ast_rewriter.rewrite` (all modules) | 8.7 |
| `gen_func` (per-function emission, outermost only) | 8.3 |
| `_selfhost_scan_gimplegen_extra_fields` (once per process) | 2.6 |
| tokenize+parse+rewrite of 44 compiler sources, standalone | 2.9 |

So parsing, rewriting and the gimplegen scan together are about 12 s of ~197, i.e. roughly 6%: the
plan below that targets them (rule index, persisted scan) is NOT worth its self-host risk. ~170 s of the
total is inside `_compile_imported_module` and is not parse or emission of the entry; the next measurement is
a per-phase split INSIDE it (function lowering vs signature/inference passes vs `coro.lower` vs the
call-site contract walks in `module_gen`), taken with the same wrappers, before any design.

Also recorded here because the measurement caught it: `f77b8ec21` (list iterator across a call) made a
call-site-contract walk quadratic (a whole-body scan per call argument) and took the same compile from 197 s to
368 s; memoised per body in `itcursor.escaping_iter_names` it is 214 s. The remaining ~17 s over the 197 s
baseline has not been attributed (other commits landed in between); do that first.

## Sampling profile (2026-10-31, no profiler overhead) and the first landed win

A sampler thread reading `sys._current_frames()` every 20 ms (5,679 samples over a 214 s compile of fire.py;
the script is 25 lines, `sample.py` in the commit message) gives real inclusive shares:
`coro.lower` 29.4% (all of it `_scan_callsite_param_kinds` -> `_collect_from` -> `_static_env`, 25.3%, of which
`coro._walk` is 22.8% SELF time), `_parsed_import` 14% (tokenize 6.3%, parse 4.3%, rewrite 4.2%),
`_infer_return_maybe_kinds` 9.5%, `_gmi_binding_index` 6.4%, `os.path.realpath` 4.8% (40,000 calls from
`methods_shared._is_selfhost_sibling_alias` / `_is_selfhost_source_file`, each resolving the same
`_SELFHOST_DIR`), `gen_func` 4.8%.

Landed: `coro._static_env` walked its function seven times; it now walks once (`_fn_nodes`). The generated C
for generator programs is byte-identical before/after (68 KB generator program compared; `fire.py`'s own
closure differs only in the compiled `_static_env` function, as the compiler source changed).
Second win, same round: `_scan_callsite_param_kinds._collect_from` built `_static_env` for EVERY function of
the whole import closure on every pass, though almost none calls one of this module's generators. The env is now
built lazily on the first call the visitor will act on (`_wants_call`, the same two tests the visitors make), and the
CallExpr list of each function is found once per scan and reused (`_calls_in`). Measured on the same compile of
fire.py (`time.perf_counter` around the outermost call, machine load 14): 214 s -> 160 s. Generated C is unchanged:
`compile_stdlib.py` GCC CAS 610/610 hits (every module's C hashes to what it was before), plus a byte-identical
generator program.
Remaining, in order of share: the other `_walk` users in `_scan_callsite_param_kinds` (cache per function across
the two `_one_pass` rounds and the six `lower` calls: needs an invalidation story because the contract maps evolve);
`realpath` memo for the constant `_SELFHOST_DIR`; `_infer_return_maybe_kinds`; `_gmi_binding_index`.

## Status (2026-10-31) — Step 0 measured ON fire.py (profile-inflated, see the correction above): the dominant serial cost is not emission, and two of the three biggest items are not parallelisable work at all

Method: `cProfile` around `gimple_codegen.compile_to_gimple(fire.py_src, do_imports=True, filename=fire.py)`
(the exact call `fire.py --dump-full` makes through `compile_to_gimple_parallel_frozen`, which today forwards to
`_run_pipeline`), 18-core machine, other agents running (load average 8-13, so wall numbers are inflated;
shares are what to read). Profiled in-process time 91.7 s. For scale, an un-profiled `fire.py --dump-full fire.py`
took 4m45s-5m18s wall on the same loaded machine.

| item (cumulative, share of 91.3 s) | s | share | calls |
|---|---|---|---|
| `gen_module_impl` (all lowering, 6 `gen_module` calls) | 63.5 | 69.5% | |
| of which `_compile_imported_module` (the 227 imported-module compiles) | 54.7 | 60.0% | 227 |
| **`_selfhost_register_gimplegen`** (one call, once per process) | **27.4** | **30.0%** | 1 |
| of which `_selfhost_scan_gimplegen_extra_fields` | 24.4 | 26.7% | 1 |
| `_selfhost_parsed_source` (parse + tokenize + rewrite of the COMPILER'S OWN sources) | 28.5 | 31.2% | 845 |
| `_parsed_import` (the closure's own modules) | 25.3 | 27.7% | 1406 |
| **`ast_rewriter.rewrite`** (all 101 parsed modules) | **20.4** | **22.3%** | 101 (662,556 `_rewrite_node`) |
| `py_tokenize` | 19.1 | 20.9% | 1033 |
| `parse_module` | 17.3 | 19.0% | 101 |
| `coro.lower` (`_scan_callsite_param_kinds` 10.5 s) | 13.2 | 14.4% | 6 |
| `_detect_generator` / `_scan_yield_bearing` | 8.3 | 9.1% | 3.0 M |
| per-function emission, `gen_func` (previous profile: ~21-23%) | not separately re-measured | | |

What this changes in the plan:

1. **27% is a once-per-process scan that re-parses the compiler's own ~60 sources** (`emit_funcs.py:1224`
   `_selfhost_scan_gimplegen_extra_fields` -> `_selfhost_parsed_source`, `funcs_shared.py:1963`, cached
   in-process by (path, mtime)). Its OUTPUT is a tiny `{attr: ctype}` dict and is a pure function of the file
   contents. Fork-parallelising it would still pay it once per worker; persisting it removes it. The fix is a
   content-keyed on-disk cache for `_selfhost_parsed_source` (pickled rewritten AST) or for the scan's result,
   keyed by file SHA + `cas.selfhost_fingerprint()` (the larger set that covers the parser and rewriter; NOT
   `compiler_fingerprint()`, which omits them). **Constraint:** these functions are compiled into the self-hosted
   binary (`mojo/middle/funcs_shared.py`, `emit_funcs.py`), so the cache must live behind a Python-only seam that
   the binary does not lower (or be skipped when running compiled); the owed gate for that edit is
   `test_selfhost.py` + `make bootstrap`, which is why it is a separate round and not in this one.
2. **22% is `ast_rewriter`** (`candidate_rules` -> `try_rewrite` -> `_term_discriminator`: 618,792 `try_rewrite`
   calls, 3.2 M `_term_discriminator` calls, 105 M `isinstance`). It is per-node dispatch cost, not I/O: a rule
   index keyed by node class (dict lookup instead of testing every rule) is a single-process win that stacks with
   any parallelism, and it must produce an identical tree (`cmp` of `.ast` over the corpus).
3. Parallelising the 101 closure parses (the original step 2) is bounded by the ~19% parse + ~20% tokenize + the
   rewrite, i.e. up to ~45% of the profile, but only the closure modules, not the 27% scan; and unpickling a large
   AST back from a Pool worker costs real time. Measure that unpickle cost BEFORE building it (one module,
   `pickle.dumps(ast)` size and `loads` time).
4. The owner's 1.1x ceiling decision applied to emission only. Items 1 and 2 are not emission and do not need the
   frozen snapshot, so they are not subject to it.

Implementation order (each step independently `cmp`-verifiable, gate = `compile_stdlib.py` + the targeted test):
(a) rule index in `ast_rewriter.candidate_rules` -> identical `.ast` for every `*.py`/`*.mojo` in the repo;
(b) persist the gimplegen field scan's result keyed by `selfhost_fingerprint` + file hashes, Python-only seam;
(c) measure pickle round-trip of one parsed module, then decide on the Pool parse;
(d) only then the frozen-snapshot emission. Re-run this profile after each and record the table here.

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
