# ABI: the module/dylib boundary contract

> The frozen C ABI for values that cross a module boundary (client ↔ stdlib
> dylib / CAS artifact). Stage 1 of `MODULE_CACHE_DESIGN.md`. Once we link
> against prebuilt artifacts instead of inlining bodies, *both sides must agree
> on this contract exactly* — it is what makes a content-addressed artifact
> reusable and what lets other languages interoperate.

## Principle

A boundary symbol is an ordinary C function with a stable, plain-C signature.
No name mangling beyond what is documented here; no hidden arguments. If you can
write the `extern` declaration, you can call it from C, Rust, or anything that
speaks the C ABI. The reflection table (Stage 4) records these signatures so the
declaration can be generated automatically.

## Scalar types

Mojo scalars are newtypes over MLIR builtins (see `mlir.py`); at the ABI they are
the obvious C scalars:

| Mojo | C ABI |
|---|---|
| `Int` | `int64_t` (machine word; = `__mlir_type.index`) |
| `Int8/16/32/64` | `int8_t` / `int16_t` / `int32_t` / `int64_t` |
| `UInt` | `uint64_t` (machine word) |
| `UInt8/16/32/64` | `uint8_t` … `uint64_t` |
| `Bool` | `_Bool` |
| `Float16/32/64` | `__fp16` / `float` / `double` |
| `None` | `void` (return) |

## Pointers

| Mojo | C ABI |
|---|---|
| `UnsafePointer[T]` / `OwnedPointer` / `ArcPointer` / `Pointer` | `T *` |
| `OpaquePointer` / `!kgen.pointer<none>` / `!llvm.ptr*` | `void *` |

All address spaces collapse to a plain C pointer at the ABI.

## Aggregates

- **Structs are passed and returned by pointer** (`StructName *`). Allocation is
  via the `_alloc_StructName()` helper the codegen emits; the boundary never
  passes a struct by value. Field layout (name → C type, in declaration order) is
  recorded in the reflection table and must match on both sides.
- **`Span[T, _]` / `StringSlice[…]`** → `Span *`, the fat pointer
  `struct Span { char *_data; int64_t _len; }`. `.unsafe_ptr()` reads `_data`;
  `len()` / `.__len__()` reads `_len`. (Seeded in `gimple_codegen.py`; see the
  `Span` model added when walking `FileDescriptor.write_bytes`.)

## Library container types (current runtime representation)

These cross the boundary as opaque pointers to the runtime types in
`runtime/mojo_runtime.h`:

| Mojo | C ABI |
|---|---|
| `String` / `str` | `char *` |
| `Str` | `MojoStr *` |
| `List` / `list` | `MojoList *` |
| `Dict` / `dict` | `MojoDict *` |
| `Set` / `set` | `MojoSet *` |

## Functions and methods

- **Free function** `fn name(a: A, b: B) -> R` →
  `R name (A_abi a, B_abi b);` (C-keyword names get the documented `mojo_` prefix).
- **Struct method** `Struct.method(self, args…)` →
  `R Struct_method (Struct *self, args…);` (self first, by pointer).
- **`external_call["sym", Ret](args…)`** → a direct call to the C symbol `sym`
  with `Ret`/arg C types as lowered; one `extern` prototype per symbol is emitted
  (libc names already in our headers are not re-declared). This is the escape
  hatch to libc / OS syscalls (e.g. `write`).
- Functions are forward-declared so mutual recursion and cross-module calls work.

### Exception-handling entry points

- **`mojo_exc_pop()`** — pops the topmost frame (`void`).
- **`mojo_raise()`** — `longjmp`s to the current frame (`void`).
- **`mojo_try_push()`** — *macro*, not a function: `(++_mojo_exc_top, setjmp(_mojo_exc_stack[_mojo_exc_top]))`.
  Must be a macro so `setjmp` executes in the caller's frame; calling it as
  a function would push the `setjmp` frame into the wrapper and break `longjmp`
  (undefined behavior on macOS arm64).
- **`mojo_exc_msg_set` / `mojo_exc_msg_get`** — set/get the string payload of a `raise` (`void` / `char *`).
- **`mojo_exc_obj_set` / `mojo_exc_obj_get`** — set/get the opaque typed exception object (`void *`).

## Generics (forward-looking — Stage 5)

A generic is not a single symbol; each instantiation is. The boundary symbol for
`Generic[Args]` is the **monomorphized** function, mangled as
`Generic__method__<mangled-type-args>`, keyed in the CAS by
`hash(template-id, concrete type args, comptime params)`. The reflection table
exposes the generic *template* plus a C-ABI `instantiate` entry point so a client
(or another language) can request an instantiation that is then published into
the shared CAS. Until Stage 5, generics are monomorphized inline by the codegen.

## Stability

This contract is versioned with the reflection-table schema. A change to any row
above is an ABI break and invalidates cached artifacts (their content hash
includes the ABI/target, so stale artifacts are simply never matched — they are
not silently mis-linked).
