# GPU offload: where the transform hooks in

Companion to `doc/METAL.md`, which holds the idea. This document is the
answer to a narrower question: **given the tree as it actually is, which
seams do we cut, in what order, and what is the first runnable
increment.** `METAL.md` is a parking lot; this is the plan.

## The one thing that changes the plan

`METAL.md` assumes the offline toolchain: emit MSL/AIR, run `xcrun metal`,
then `xcrun metallib`, ship a `.metallib`, load it at run time.

**We do not need any of that.** `test_llm/metal.m` already compiles MSL at
run time with `-[MTLDevice newLibraryWithSource:options:error:]`, and
`test_llm/kernels.metal.inc` already carries the MSL *as a C string*
precisely so a single generated C file is self-contained. That is a
different, better deal:

| | offline `.metallib` (METAL.md) | runtime `newLibraryWithSource:` (proven) |
|---|---|---|
| build wiring | `xcrun metal` + `metallib` in the build, per-arch caching | none — it is a C string in the `.ci` |
| artifact | a second file to ship and cache-key | the `.ci` alone is the whole program |
| portability | re-compile per GPU family | the same source, JIT'd by the driver for the GPU actually present |
| debuggability | need the MSL file to hand anyway | the MSL is a literal in the `.ci` you already read |

So the MSL becomes a **sidecar string emitted by the compiler**, not a
separate compiled object. That removes the entire "how does this get
built and cached" question, and it is the reason this is worth doing now
rather than after the CPU path is solid.

What we still take from `METAL.md`: the host/device split, `external_call`
as the handoff, and the table-driven lowering discipline.

## The three seams

They are at three different granularities, which is why none of them can
do the other's job.

### Seam 1 — device region selection (function level, *before* emission)

A pass that partitions the module's `FunctionDef`s into host and device.
It cannot live in the emitter, because "emit this function to MSL instead
of C" has to be decided before the emitter starts that function.

New: `mojo/backend_gimple/device_select.py`.

Selection, in priority order — explicit beats inferred, always:

1. **Explicit marker.** `'gpu' in fdef.decorators`. `FunctionDef.decorators`
   is already a list of strings and `module_gen.py:3631` already reads it
   for `'export'`, so this costs nothing and is the thing you write when
   you mean it.
2. **Stdlib reachability.** A function referenced as the callee of
   `DeviceContext.compile_function[...]` / `enqueue_function` is a kernel.
   This is the *upstream* shape, and it is what makes the hand-written
   stdlib GPU code work without editing it: see
   `stdlib/test/asyncrt/test_device_pointer_kernel.mojo:34-72`, where
   `vec_add` is an ordinary `def` and the test hands it to
   `ctx.compile_function[vec_add]()`. The compiler has to recognise the
   *call*, because the function itself carries no marker.
3. **Inferred loop nests.** A recognised parallel loop nest over contiguous
   numeric containers. This is increment 3, and it is deliberately last:
   inference is the part that can be wrong, and it should be built on a
   path that is already proven correct when explicitly asked for.

Rule 2 is the one that answers "transform the hand-written speciality code
as well as normal Python" — the stdlib kernels are unmarked, so reachability
is the only honest way to find them.

### Seam 2 — MSL emission (statement/op level)

A second emitter, parallel to `mojo/backend_gimple/emit_exprs.py`, selected
by a target flag on the gen object (`gen.target`, `'c'` today, `'metal'`
for a device function). This is the "two-target codegen shape" `METAL.md`
already names: same AST, same walk discipline, different sink.

New: `mojo/backend_gimple/emit_metal.py`, and its op table
`mojo/middle/metal_ops.py`.

**`mlir.py` is the right model for the table, and the right place for the
GPU ops** — its own docstring says so: *"adding a newly-met op is one row
here, not new backend control flow."* It already classifies the entire GPU
op surface and defers it (`mlir.py:207-211`):

```python
_DEFERRED_PREFIXES = {
    'nvvm.':  'GPU (NVIDIA) — see METAL.md / CUDA path',
    'rocdl.': 'GPU (AMD)   — see METAL.md / ROCm path',
}
```

with `pop.call_llvm_intrinsic` and `pop.inline_asm` deferred alongside. So
every one of the ~100 `llvm_intrinsic[...]` sites and ~141
`inlined_assembly` sites in `std/gpu/` is *already classified* — the
classifier works, the lowering does not exist. Building the lowering is
therefore table work against an existing index, not new plumbing.

The `mlir.*` family splits by vendor, and this is a Metal target, so the
split is:

- `llvm.air.*` / `llvm.agx3.*` → **MSL** (this target)
- `llvm.nvvm.*` → PTX (a different target, same table shape)
- `llvm.amdgcn.*` → ROCm (ditto)

The one hard fact to design around: `mlir.py:71-77` collapses every address
space to a plain C pointer (`!llvm.ptr<1>` global, `<3>` shared, `<7>`
shared-cluster all become `void *`). For the host that is right. For a
device it is **wrong in a way that matters** — `threadgroup` is not
`device`, and the barrier semantics differ. So a device emitter must
*break* that collapse, not inherit it. This is the one place the device
target genuinely diverges from the host's type model, and it is where the
first increment will hit.

### Seam 3 — the artifact channel (module level)

The C backend returns one string (`module_gen.gen_module_impl`). A device
region produces a *second* artifact. Rather than change that return type
(the single-TU `--dump` path and the JIT both consume one string), the
device emitter fills side buffers on the gen object:

- `gen.device_source` — the MSL text, which `gen_module_impl` embeds as a C
  string literal (the `kernels.metal.inc` trick)
- `gen.device_glue` — host-side C declarations for the dispatch shims

and the function-emission loop at `module_gen.py:8808` routes a device
`fdef` to the MSL emitter instead of the C one.

**Landed.** `mojo/backend_gimple/device_glue.py` emits the whole channel as
pure C appended to the module, and the C API it calls lives in
`runtime/fire_metal.h` / `fire_metal.m`. Pure C is a hard constraint, not a
preference: the `.ci` is compiled `gcc -fgimple -x c`, and gimple is a C
front end, so `@autoreleasepool` and `id<MTLLibrary>` do not survive it.
`fire_metal.m` is therefore the only file in the tree that touches Metal, it
is Objective-C, and the registry row that links it
(`build_config._OPTIONAL_RUNTIME_UNITS`) carries the per-unit `clang` +
`-fobjc-arc` that the build-wide gcc cannot provide.

Four things this cost that the plan did not foresee, each of which failed
silently rather than loudly:

- **The scalar ABI.** MSL declares a scalar kernel parameter as
  `constant T &`, and the device reads exactly the bytes bound at that index.
  Binding a host `double` for a Mojo `Int` (MSL `int`, 4 bytes) delivered
  the low 4 bytes of a float's mantissa, so `len=1024` arrived as `0`: every
  thread took the bounds guard, the kernel wrote nothing, and the program
  exited 0 with plausible arrays and no output. The widths now travel from
  the emitter (which chose the MSL type) to the wrapper (which narrows the
  value) to the runtime, which binds that many bytes.
- **The grid.** Under-dispatching leaves the tail of the output
  uninitialised and over-dispatching is safe because kernels guard on `len`,
  so the runtime covers the largest buffer exactly.
- **Copy-back needs a length, and a `float *` has none.** The contract is the
  kernel's first `Int`/`Int64` parameter, which every hand-written kernel
  here already has, and it is *checked* rather than guessed: a kernel with no
  length raises at compile time, because silently copying back nothing
  produces a program that runs and is wrong.
- **The optional-unit probe.** A code generator that emits C from Python
  string templates has those templates in its own source, and compiling the
  compiler inlines them as `_slit_N` initializers — so the emitted
  `_mg_have_device = (int64_t) mojo_metal_init(...)` text made every build
  that imports `build_config` link Metal. Fixed in the probe
  (`build_config._strip_c_literals_and_comments`), which also removes the
  "followed by `(` and not preceded by a quote" heuristic's real blind spot,
  not by renaming anything around it.

**Still open, and it is the next thing.** A program written in Mojo cannot yet
*reach* a dispatch: `MojoList` is boxed, so there is no way to obtain the
contiguous `float *` a kernel takes. The plumbing is complete and verified —
generated MSL, embedded string, launch wrappers, a routed call site, a real
dispatch, `max |diff| = 0.000e+00` — and the missing piece is the buffer
representation, which is on the critical path for auto-offloading ordinary
Python anyway. The end-to-end GPU test therefore drives the generated launch
wrapper from a C harness, and asserts the Mojo call site on the generated C.
That is a real gap, stated plainly rather than papered over: nothing yet
computes on the GPU from a program whose source is Mojo.

## Order of work

**Increment 1 — prove the path with one explicit kernel.** `@gpu def
matvec(...)` → MSL → embedded string → host dispatch → numbers match
CPython. Every seam is exercised; nothing after this is architecturally
new. If the MSL emitter, the sidecar, and the dispatch are right here, they
are right for everything else.

**Increment 2 — the hand-written speciality code.** With a device emitter
that exists, make the stdlib's device primitives lower into it: `llvm.air.*`
→ `threadgroup_barrier` / simdgroup ops, `pop.call_llvm_intrinsic` and
`pop.inline_asm` → real MSL instead of the `0` stubs at
`emit_calls.py:1135`. `std/gpu/primitives/id.mojo`'s `global_idx` and
friends start returning real values. This is the half of the request that
is about *existing* code, and it is table work plus a barrier/address-space
model.

**Increment 3 — auto-offload for ordinary Python.** Recognise a parallel
loop nest, synthesise a kernel, replace the host loop with a dispatch.
This is the "simple Python in" half and the one that is genuinely new
analysis.

Increment 3 also has a hard prerequisite that is *not* GPU work: kernel
arguments must be **contiguous device memory**, and today a Python list is
a `MojoList` of boxed slots accessed through `mojo_list_get_double`. The
measured cost of that is the ~19× residual between the compiler's `-O2`
output and hand-written C on the same loop. Making numeric containers
contiguous helps the CPU target too, so it is worth doing on its own
merits and should not be buried inside the GPU work.

## What is deliberately not in the plan

- **No `xcrun metal`/`metallib` build wiring.** Superseded by runtime
  compilation (table above).
- **No `MTL4` / Metal 4.** `newLibraryWithSource:` is enough and is
  proven here.
- **No PTX/ROCm.** Same table shape, different target; not now.
- **No claim about the whole stdlib.** `std/gpu/` is 41k lines; increment 2
  is scoped to the primitives a first kernel actually needs, not to making
  all of it compile.

## Open questions this plan does not settle yet

- **Argument marshalling.** A `MojoList` cannot cross to the GPU, so the
  ABI question ("what is a kernel argument?") is really the contiguity
  question above. Resolved by fixing contiguity first, not by inventing an
  ABI.
- **Grid sizing.** Infer from the loop trip count, or require the marker to
  carry it. Inference is what increment 3 needs anyway.
- **When the runtime-compiled library is rebuilt.** Per process, per
  distinct MSL text — the same content-addressing the JIT already does for
  binaries.
