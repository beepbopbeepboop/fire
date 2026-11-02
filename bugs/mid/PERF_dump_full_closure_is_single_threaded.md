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
Sampling profile after both wins (4,106 samples, 158.5 s): `_parsed_import` 18.8% (tokenize 8.0, parse 6.4, rewrite 5.8),
`_infer_return_maybe_kinds` 13.0% (`module_gen._mk_round`, 4 fixpoint rounds x 6 `gen_module` calls; a body that calls
nothing in `callee_kinds` has the same answer every round, so rounds 2+ can reuse round 1's result for it),
`_gmi_binding_index` 8.7% / `_xg_record_scalar_args` 8.3%, `os.path.realpath` 6.7% (`methods_shared._is_selfhost_*`),
`gen_func` 6.7%, `coro.lower` 5.0% (was 29.4%).
Third win: `methods_shared._cached_realpath` memoises the `os.path.realpath` calls of `_is_selfhost_source_file` /
`_is_selfhost_sibling_alias` (84k calls, all about `_SELFHOST_DIR` and the compiler's own sources): realpath 6.7% -> 1.1% of
samples, compile 155 s. Its first version was an unannotated helper and BROKE the self-host build (`methods_shared.py:141:
invalid operands to binary + (have 'double' and 'char *')`), caught by `test_selfhost.py`; it is annotated now and
`test_selfhost.py` passes 3/3 and `compile_stdlib.py` GCC CAS stays 610/610. Any edit under `mojo/middle` needs `test_selfhost.py`.
Measured and REJECTED: memoising f-string field tokenization. `py_tokenize` is called 17,696 times, but 17,141 of those are
tiny f-string field texts; with the memo the calls drop to 2,884 and the time does not move (19.1 s -> 22.2 s, whole compile
167 s vs 171 s at the same low load). The 19 s is the ~550 real module sources, every one distinct, so only a faster tokenizer
(or caching tokens across processes) would help. Call count is not time: measure before building.
Fourth win: `module_gen._xg_record_scalar_args` called `_gmi_identifier_literal_ctype`, which rebuilt the ENCLOSING function's binding
index (`_gmi_binding_index`, a whole-function walk) for every identifier argument of every call in it. The index is now built once per
function (`_xg_enc_index`) and passed in. `fire.py` compile 167 s -> 151 s at load ~3; generated C byte-identical for all 610 stdlib
modules (GCC CAS 610/610 with the change reversed), `test_selfhost` 3/3.
Fifth win: `module_gen._mk_round` reuses round 1's `_infer_return_maybe_kinds` answer, in the fixpoint's later rounds, for any body that
calls nothing in the grown callee set (the answer depends on the set only through call names); the call spellings of each body are
recorded once in round 1. Sampled share of `_mk_round` 13.8% -> 8.8%; sampled whole compile 168 s -> 153 s (both under the sampler);
generated C byte-identical for all 610 stdlib modules, `test_selfhost` 3/3.
Measured, not changed: `_infer_local_var_types` is called 278,673 times for 3,801 distinct functions (one function up to 308 times) and costs
11.6 s of a 146 s compile (8%). A per-function memo is NOT safe as it stands: the inference reads `_quick_type`, which reads `gen` tables
(`func_return_types`, `var_types`, struct field types) that GROW during the compile, so two calls on one function can legitimately differ. The
safe form keys the memo on a version stamp of exactly the tables it read (or finds the passes that re-ask with unchanged tables); do that
measurement first -- count how many of the 308 repeats return an identical dict -- before writing any cache.
MEASURED (same run, results hashed per function): 278,673 calls yield only 4,081 distinct (function, result) pairs, at most 8 per function, so 98.5% of the
calls recompute a result already seen. The cache is worth ~11 s (7%) but needs an invalidation key; count-only fingerprints (`len(table)`) miss a
REFINED entry, so the table writes themselves have to bump a version (the tables are plain dicts written from many places -- a ~dozen
write sites per table must be found first). Not attempted: a stale entry here is a silent wrong C type.
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

## Plan (2026-11-01): the `_infer_local_var_types` cache — what the write-site census says, and why a dict subclass is not the way

Question left open above: which write sites must bump a version before `_infer_local_var_types` (278,673 calls, 4,081 distinct
(function, result) pairs, ~11 s of a 146 s compile) can be memoised. Census (`grep` of `self.|gen.<table>[...] =` and
`.update/.setdefault/.pop/.clear`, this tree): `func_return_types` 100 write sites in 11 files, `struct_field_types` 98 in 5,
`var_types` 83 in 11 (`_struct_method_signatures` 1; `global_var_types` 0). So instrumenting the writes by hand is ~280 edits across
the middle and backend tiers, each one a place a future write can forget to bump: not acceptable for a cache whose failure mode is a
silent wrong C type.

The tempting alternative, a `dict` subclass whose mutators bump a counter (assign it to those three tables in `GimpleGen.__init__`),
does NOT work here: this compiler is self-hosted, and the compiled path has no dict subclassing (a `dict` is a `MojoDict *` runtime
object; `class V(dict)` is a struct with no dict protocol), so the change would pass the interpreted reference and break
`test_selfhost.py`. Verify that first with a 10-line probe before any further design.

What does work under self-host, in order of preference:
1. Key the memo on a CONTENT stamp of exactly what the inference read, not on write events: record the (table, key) pairs
   `_quick_type` consults during one call (a per-call read set, collected by a thread-global list the three lookups append to when it
   is non-None), store the values read alongside the result, and reuse the cached result only when every recorded read still
   returns the same value. Cost: a handful of dict lookups per hit instead of a function walk. Sound by construction (a stale entry
   cannot survive a changed read), needs no write-site audit, and uses only plain dicts/lists.
2. Cheaper and unsound-looking: a per-pass epoch (6 `gen_module` calls x 4 fixpoint rounds = 24 epochs) — only valid if the tables are
   frozen within a round, which the 8-results-per-function maximum suggests but does not prove. Do not do this without 1's read-set
   check running alongside as an assertion for a full `fire.py` compile (expect 0 mismatches).
Tests that will prove it: the generated `.ci` of the `fire.py` closure byte-identical before/after (`cmp`), `compile_stdlib.py` GCC CAS
610/610 hits, `test_selfhost.py` 3/3, and a unit test that mutates a table entry between two calls and sees the cache miss.

## Measured (2026-11-01): who calls `_infer_local_var_types`, and why the read-set cache above is not buildable either

Wrapper around `rs._infer_local_var_types` on the same `compile_to_gimple(fire.py, do_imports=True)` (wall 258 s with the wrapper;
289,513 calls, 3,905 distinct functions, up to 313 calls for one function; 25.5 s inside = ~10%, more than the 8% above). By call site:

| calls | seconds | site |
|---|---|---|
| 63,406 | 6.2 | `module_shared._gmi_phase17_collect_appends` (the `isinstance(_n, FunctionDef)` branch) |
| 58,141 | 9.9 | `module_gen.gen_module_impl` ~8994 (`self._inferred_var_types[name] = ...` over `all_functions`) |
| 58,141 | 6.8 | `module_gen.gen_module_impl` ~12683 (the same loop again, after the return-type fixpoint) |
| 35,459 + 35,459 | 0.5 + 0.6 | the two struct-method twins of those loops |
| 26,321 / 11,734 | 0.5 / 0.2 | `gen_module_impl` ~8286 / ~8571 |

So 22.9 s of the 25.5 s is three loops, each of which re-infers every function of the module being compiled once per `gen_module`
call (the `_mk_round` fixpoint's 4 rounds x several `gen_module` calls per module) although the answer almost never changes.

Why the read-set cache is dropped: `_infer_local_var_types_core` seeds a scratch copy of the WHOLE `var_types` table and calls
`_quick_type` / `_local_value_type`, which read `func_return_types`, `struct_field_types`, `_struct_method_signatures`, class
attrs, generator tables, ... transitively (a struct name comes from a callee's return type, not from any identifier in the body).
Reads are as numerous and as scattered as the 280 writes counted above, so neither a write version nor a read set can be audited.

Direction that CAN be sound, by analogy with `_mk_round`'s fifth win: skip a re-inference only when the INPUT TABLES' relevant
slice is unchanged, where "relevant" is computed by a closed set, not guessed: (1) per function, record in round 1 the set of
callee names, struct names and global names its body mentions plus the types of its parameters; (2) between rounds, track which
`func_return_types` / `struct_field_types` entries CHANGED (diff the two snapshots once per round: a cheap dict compare, not a
per-write hook); (3) re-infer a function only if a changed entry is reachable from its mention set through the struct graph
(changed struct S is relevant if the body mentions S or any struct whose field types name S). Gate it on a full-compile assertion
mode that re-infers anyway and compares (expect 0 mismatches over the fire.py closure) BEFORE the skip is enabled. Expected gain
~15-20 s of 258 (6-8%). Not started: needs the assertion harness first.

## Measured (2026-11-01, later): the "fingerprint the mentioned names" skip is NOT sound and would not pay — drop the `_infer_local_var_types` memo line of work

Assertion harness (`/tmp`-style script in this commit message: wrap `_infer_local_var_types`, key each call on `(function, hash of
func_return_types / struct_field_types / var_types entries for every name the body mentions + its params + the three table sizes)`, and
compare the result whenever a key repeats), run over the same `fire.py` compile (wall 268 s, 290,494 calls):

- repeated keys: only 40,811 of 290,494 calls (14%). The tables' SIZES move between the rounds, so most calls have a new key.
  A skip could therefore save at most ~3.5 s (14% of the 25 s), and
- 20 of those 40,811 repeats returned a DIFFERENT result (`selfhost_fingerprint`, `_refine_generic_return_type`, `scan_expr`,
  `collect_assigned_types`, `_factory_return_for`, ...): a mentioned-names fingerprint misses inputs (types reached through a callee's
  return type, per the analysis above), i.e. it would have served a stale local type from cache.

So: unsound AND small. Removed from the plan. What is left in this doc is the part that actually scales: the parallel work-unit plan
(parse the closure's modules in worker processes, then emit from a frozen snapshot), plus the tokenizer (12% parse of imports) and the
`coro.lower`/`_gmi_binding_index` walks listed above. Do not revisit a per-function type-inference memo without a way to enumerate
every table the inference reads; the call-count (290k for 3.9k functions) is better attacked by running fewer `gen_module` rounds per
module than by caching their bodies.

## Correction (2026-11-01): there is no "several gen_module calls per module"

Counted `module_gen.gen_module_impl` calls per `self.module_name` over the same fire.py compile (wall 269 s): 61 calls, 61 distinct
modules, every one called exactly ONCE (the histogram is `[(1, 61)]`). The "4 fixpoint rounds x 6 `gen_module` calls" arithmetic
earlier in this doc, and the advice just above to "run fewer `gen_module` rounds per module", are wrong: imported modules are not
`gen_module`d one by one, they are compiled inside the importer's call (`_compile_imported_module`; inclusive times nest, e.g.
root 261 s > build_config 242 s > reflect 238 s > ...). The 290k `_infer_local_var_types` calls therefore come from loops INSIDE one
`gen_module_impl` (the ~8994 / ~12683 loops over `all_functions` run per imported module's own pass, and `_gmi_phase17_collect_appends`
once per function per scan), not from repeated whole-module passes. To find the repetition factor: count calls per (module, call site)
rather than per module; the earlier census (63k + 58k + 58k for ~3.9k functions) says each function is re-inferred ~15 times in those
three loops, so the question is which outer loop re-enters them (`_mk_round` fixpoint iterations over the module's functions, or the
retry passes `MOJO_DEBUG` reports for generators), measured with the call-site key above.
