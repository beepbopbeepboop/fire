# Module System: Cached-Dylib + CAS + Reflection — Design & Rationale

> Status: **design of record.** Implementation is staged (see the bottom of this
> file). This document exists so collaborators understand *what* we're building
> and, more importantly, *why* it is fast and efficient. Companion docs:
> `ABI.md` (the boundary contract), `METAL.md` (GPU offload), `IMPL.md` (what's
> implemented today).

## The problem

We are moving the compiler from hand-written `runtime/*.c` stubs to compiling
against the **real upstream Mojo stdlib**. The MLIR floor is in place
(`mlir.py`, `external_call`, memory + struct GEP, the `Span` model) — the real
`FileDescriptor.write_bytes` already lowers natively. The remaining blocker is
the **import/module boundary**: today `do_imports` transpiles-and-inlines the
*entire transitive closure* — **6.9 MB of C for a one-line `print`** — with no
caching and no linkable artifact. That does not scale to the stdlib, let alone a
monorepo.

## The model in one sentence

**Source + transitive closure is the semantic ground truth; a content-addressed
machine-code cache (shipped as a dylib) is a pure speed hack over it** — present
→ `dlopen`/mmap and demand-fault; absent → recompile the closure (boundable for
sanity). Both paths produce *identical* results.

This is exactly how mature toolchains already work (libc is a `.dylib`; your
hello-world links a declaration, it doesn't inline `printf`). We are applying
that discipline to a generic, comptime-heavy language — and doing it without
C++'s waste.

## Why it is fast and efficient (the whole point)

### Compile speed
- **`import` = `dlopen` + read a C-ABI reflection table.** No re-parsing headers,
  no re-typechecking the library per client. The client compiles only *its own*
  code plus extern declarations.
- **Instantiations are compiled once, globally.** A generic instantiation
  (`List[Foo]`) is keyed by a content hash of all its compile inputs and stored
  in a shared content-addressed store (CAS). The first builder anywhere compiles
  it; everyone else faults in the result. Compile cost across the fleet =
  **sum of *unique* instantiations**, not (translation units × instantiations).
- **Comptime is compiled once and cached as machine code**, then *executed* by
  the compiler — not re-interpreted from a syntax tree every build.

### Runtime speed
- Generics are **monomorphized to concrete machine code** — no boxing, no vtable
  indirection on the generic path. As fast as hand-written C.
- The cache is **`mmap(MAP_SHARED, PROT_READ)`**. The OS page cache shares
  physical pages across every process; a multi-GB stdlib costs only the pages a
  program actually touches. Demand paging *is* the "only used code costs
  anything" guarantee.

### Why this is "not as stupid as C++"
| | C++ | Here |
|---|---|---|
| Import | re-parse headers per TU | `dlopen` + read reflection table |
| Templates | re-instantiate per TU, dedup at link (COMDAT: compile-many-discard-many) | content-addressed, compiled **once globally** |
| Comptime | re-run per build | compiled once, cached as machine code, executed |
| Reflection | none (RTTI is a pale shadow) | first-class, plain-C-ABI, polyglot |

## The three layers

1. **Ground truth — source + transitive closure.** A module means its source
   compiled with its transitive imports. Always correct; optionally bounded for
   memory/sanity. (This is what `do_imports` does today, minus the boundary.)

2. **Acceleration — content-addressed artifact cache (the dylib).** Compiling a
   module or an instantiation yields a machine-code artifact keyed by a hash of
   *all* inputs (source + imported signatures + concrete type args + comptime
   params + target + flags). Two artifact kinds share one pipeline and one cache:
   - **runtime code** — monomorphized concrete functions/instantiations;
   - **comptime code** — comptime functions compiled to the *same* machine code,
     which the compiler `dlopen`s and **calls** at compile time. The old
     interpreter was *simulating* execution; now we execute the real thing. This
     is how comptime becomes Turing-complete *and* fast.

3. **Visibility — plain-C-ABI reflection section per dylib.** Each artifact
   carries a metadata table: exported symbols (name, mangled symbol, signature,
   calling convention, kind); types (name, size/align, field name/type/offset,
   trait conformances, generic params + constraints); generic templates
   (descriptor + a C-ABI *instantiate* entry point); comptime entry points.
   **The compiler's own `import` path consumes exactly this table** — so `import`
   *is* `dlopen` + reflection. Because it is plain C ABI, **any language** can
   `dlopen` a Mojo dylib and fully interoperate: call functions, read layouts,
   even request new instantiations. Reflection is the one unified interface.

## Concurrent build-out (256-core / 3 TB-class machines, full load)

Content-addressing is what makes this sane: artifact name = content hash, so the
build-out is **mostly lock-free and needs no central request mediator on the hot
path**.

- **Warm path (99% once stdlib + common instantiations exist): mmap only.** Zero
  locks, zero syscalls after the initial mmap; pages shared via the page cache.
  You cannot beat this; it needs no coordinator.
- **Writes never conflict.** Same inputs → byte-identical bytes at the same hash
  path. Write temp + atomic `rename()`; last-writer-wins is harmless. Immutable
  artifacts + a release-published index entry = crash-consistent for free.
- **The only real coordination is in-flight dedup (single-flight).** A
  **sharded, lock-free in-flight table** in shared memory (e.g. 1024 shards): the
  miss-winner builds and publishes, others coalesce. Near-zero contention at 256
  cores; once an artifact is durable, lookups skip the table entirely.
- **Never block a core.** The compiler is a **work-stealing task graph**; a task
  that hits an in-progress miss *suspends* (a continuation keyed on the artifact)
  and the worker steals other ready work; the builder wakes continuations on
  publish. Result: no idle cores under saturation.
- **Grow the mmap without invalidation.** **Segmented append arenas** +
  append-only segment table; bump-allocate (`atomic_fetch_add(tail)`), fill,
  release-publish the offset. Nothing moves; pointers stay valid.
- **Failure tolerance.** `BUILDING` leases carry a TTL; a dead builder's lease
  expires and another worker retries — a failure mode a single-servicer design
  cannot survive.
- **The "single owner" thread survives — demoted to off-critical-path
  compaction.** One background thread (optionally per-NUMA-node) owns
  *compaction/GC*: fold per-worker arenas into the big always-hot bundle, rebuild
  a dense index, prune dead leases. It owns the bundle (lock-free) and is never in
  the latency path. That is the right home for "single owner, owns everything" —
  not request mediation.
- **Lifts to multi-machine for free.** Hashes are location-independent: local
  mmap = L1, a shared object-store CAS = L2 (the Bazel remote-cache model);
  distributed single-flight = the TTL `BUILDING` lease in the shared index.

**Design note — why not the obvious "single servicer thread mediates all cache
build-out"?** It centralizes a problem that is 99% embarrassingly parallel.
Content-addressing makes reads and writes lock-free with no coordinator; the only
coordination left (in-flight dedup) is handled by a sharded table with no central
thread. A single mediator would bottleneck a 256-core box on coordination and die
as a single point of failure. So we keep the single owner *only* for compaction.

## Monomorphization

- The stdlib dylib carries every instantiation the library closes over itself;
  clients use those freely.
- A client using `Generic[ClientType]` computes
  `key = hash(template-id, type args, comptime params)`; hit → fault in; miss →
  instantiate, compile, **publish into the shared global CAS** so the *next*
  client (or build) reuses it. Instantiate once, ever.
- Engine home: the existing `DispatchSolver` / `FunctionCompilability` /
  `TypePromotionSolver` (`gimple_codegen.py`), extended with cache keying.

## Resolved decisions

- **Cache shape:** content-addressed store (CAS). A monolithic stdlib dylib is
  the prebuilt warm bundle / first form of it.
- **Client instantiations:** **shared global CAS** — instantiate once, ever.
- **Comptime sequencing:** **foundation-first** — boundary + cache + reflection +
  monomorphization first; keep the `_eval_const_*` interpreter as fallback;
  comptime-as-cached-machine-code is the final stage.
- **Concurrency tier:** **dup-tolerant CAS first** (immutable hash-named
  artifacts, atomic-rename, mmap reads, segmented arenas, background compactor),
  then **sharded single-flight** (pairs with the shared CAS). Defer
  task-suspension/work-stealing until core saturation justifies the scheduler.
  Tiers are strict additions — never a rearchitect.

## Staged implementation (each stage independently verifiable)

1. **ABI freeze + extern-decl import boundary.** Formalize the C ABI for
   boundary-crossing types (`ABI.md`); switch imports from inline-transpile to
   extern decls; keep transitive-closure compile as the *artifact builder*.
2. **Stdlib dylib build + link** → `build/libmojostdlib.dylib`; client links it.
3. **Content-addressed cache** (dup-tolerant, then single-flight) → `cas.py`/`cas.c`.
4. **Reflection metadata section (C ABI)** → `reflect.py` + C header; `import`
   reads it; a non-Mojo C program proves polyglot interop.
5. **Monomorphization engine** publishing into the shared global CAS.
6. **Comptime-as-compiled-code** — compiler `dlopen`s and calls cached comptime.

## End-to-end success criteria

- A one-line `print("hello")` client: tiny object, links the stdlib dylib, runs,
  writes via the real walked-in `FileDescriptor.write_bytes` →
  `external_call["write"]`. Small RSS despite a large stdlib (demand paging).
- Warm vs cold cache produce byte-identical artifacts; warm is a load only.
- A non-Mojo C program `dlopen`s a stdlib dylib, reads the reflection table, and
  calls a stdlib function.
- Existing suites stay green throughout: `make check-gimple` (153),
  `test_runner.py` (8), `compile_stdlib.py` (642/643).
