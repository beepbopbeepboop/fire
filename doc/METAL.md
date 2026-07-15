# Metal GPU Offload on macOS (Future Work)

> Status: **design note / parking lot.** Not implemented. Captured now so we
> don't lose the plan; we build it down the road once the CPU path (stdlib →
> MLIR → GIMPLE → C) is solid.

## The idea in one line

On a Mac we already have a full GPU toolchain in the box: identify the Mojo
kernels we want to offload, lower their inner bodies to **Metal Shading Language
(MSL)** / **LLVM Metal IR**, run them through **Apple's IR→binary compiler** to
get a real `.metallib` for this machine, and call that from the C we already
emit. Result: actual GPU offload on macOS with no external runtime.

## Why this is tractable here

Apple ships every layer we need:

- **Metal Shading Language (MSL)** — a C++14-based kernel language. Our GPU
  kernels can be emitted as MSL the same way we emit GIMPLE C for the host.
- **LLVM-based Metal IR (AIR)** — Metal compiles through an LLVM IR dialect
  ("Apple IR" / AIR). Since we already live in LLVM/MLIR land conceptually, we
  can route kernel bodies into this IR instead of (or alongside) MSL text.
- **`metal` / `metallib` compilers** — Apple's offline toolchain turns MSL/AIR
  into a `.metallib` *binary glob* targeted at the host GPU. That's the
  "IR → binary for your machine" piece the user noted.
- **Metal runtime (C API via `Metal/Metal.h`)** — load the `.metallib`, build a
  pipeline state, bind buffers, dispatch the grid, read results back. All
  callable from the C we generate, so the host side is just normal extern calls.

## Pipeline (host + device split)

```
   Mojo source
       │
       ▼
  identify kernels   ──►  inner kernel bodies            host glue stays on CPU
  (offload targets)        │                              │
                           ▼                              ▼
                  "metalize": lower to            GIMPLE C  (already done)
                  MSL / LLVM Metal IR                 │
                           │                          │  external_call into the
                           ▼                          │  Metal host wrapper
                   xcrun metal / metallib             │
                           │                          ▼
                           ▼                  load .metallib, set buffers,
                     foo.metallib  ◄──────────  dispatch, copy back
                  (binary for THIS Mac's GPU)
```

1. **Kernel identification.** Mark/detect the functions to offload (e.g. a
   `@gpu`/kernel attribute, or analysis of `for`-over-grid patterns). Everything
   else stays on the CPU path we already have.
2. **Metalize the inner stuff.** Lower the kernel body to MSL (text) or to
   LLVM Metal IR (AIR). This reuses the same lowering discipline as `mlir.py` /
   `gimple_codegen.py` — just a different backend target for the device region.
3. **Router across into LLVM land → binary.** Hand the MSL/AIR to Apple's
   offline compiler (`xcrun -sdk macosx metal …` → `.air` → `xcrun metallib …`
   → `.metallib`). Out comes a real binary for this machine's GPU.
4. **Call it from C.** Emit a small host wrapper (Objective-C/C using
   `Metal/Metal.h`) that loads the `.metallib`, creates the compute pipeline,
   marshals arguments into `MTLBuffer`s, dispatches, and copies results back.
   The generated GIMPLE C reaches it through the same `external_call` mechanism
   we just built — so from the program's perspective, the kernel is "just a
   call." Voilà: offload on a Mac.

## What we already have that feeds this

- **`external_call` lowering** — the host→device handoff is just calls into the
  Metal host wrapper; no new calling machinery needed.
- **`mlir.py` (table-driven)** — the discipline for replaying MLIR ops as a
  concrete backend is exactly what a "lower kernel body to MSL/AIR" pass needs;
  the device target is another table of op → emission rules.
- **Two-target codegen shape** — host code already goes Mojo → C; device code
  becomes Mojo → MSL/AIR as a parallel lowering, split at the kernel boundary.

## Open questions (for when we pick this up)

- Kernel marking: explicit attribute vs. inferred from grid/`for` patterns.
- Emit **MSL text** (simpler, lean on `xcrun metal`) vs. **AIR/LLVM IR**
  directly (tighter, but needs the AIR dialect details).
- Argument marshaling/ABI: how Mojo buffers/`Span`s map to `MTLBuffer` bindings
  and threadgroup sizing.
- Host wrapper language: Objective-C (`Metal/Metal.h`) vs. the C++ `metal-cpp`
  headers; pick whichever links cleanly from our emitted C.
- Build wiring: invoking `xcrun metal`/`metallib` from the build and embedding
  or shipping the resulting `.metallib`.

## Upstream alignment

The real stdlib already carries Apple-GPU paths (`is_apple_gpu()`,
`_metal_print_write`, the `print` Metal branch in `std/io/io.mojo`). When the CPU
walk-into-stdlib is mature, those branches are the natural seams to light up the
Metal target rather than inventing our own kernel surface.
