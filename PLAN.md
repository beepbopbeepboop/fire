# Language Implementation Plan

Future work only. See `IMPL.md` for everything already done.

---

## Stdlib Parser: Remaining Blocking Issues

Current pass rate: **182/277 files (65.7%)**. Top error patterns in the 95 failing files:

| # files | Error | Root cause |
|---|---|---|
| ~15 | Expected RBRACKET got ASSIGN | Complex nested subscripts with keyword args: `Type[mut=False, origin=T](...)` |
| ~15 | Unexpected COMMA | Tuple unpacking in non-var expressions: `a, b = divmod(...)` |
| ~9 | Unexpected COLON | MLIR region syntax; `__extension` edge cases |
| ~6 | Expected RBRACE got ASSIGN | Dict/set literal syntax; comprehensions |
| ~5 | Various | Edge cases: `Expected NAME got KW('var')`, unexpected ARROW, etc. |

**Quick wins (~1 hr each):**
- Statement-level tuple assignment for remaining 6 files
- Dictionary/set literal parsing (+6 files)

**Medium effort (~2-3 hrs):**
- Full subscript keyword argument semantics — the biggest remaining blocker (15 files)
- MLIR backtick types in more expression contexts

---

## Priority 5: Create Missing Mojo Spec Files

| File | Should define |
|---|---|
| `mojo-type-system.md` | Type lattice and promotion rules, numeric hierarchy, UnsafePointer semantics, generic type parameters, struct field resolution, return type inference |
| `mojo-runtime-api.md` | MojoList, MojoDict, MojoSet, MojoStr types; all container/pointer/exception/string runtime functions |

---

## Enhance Existing Specs

### Expand `GNU-EXTENSIONS.md` Module System Section

Missing details (to add):
- Struct method mangling rules for imported types
- Generic type parameters and instantiation across module boundaries
- Private/public symbol visibility enforcement
- Module initialization and top-level code execution
- Circular import detection and error handling
- Re-export semantics (`from X import *` then re-export)
- Multiple search path handling (MOJO_PATH, stdlib, current dir)

### Expand `mojo-simple-statements.md`

Missing:
- Detailed import semantics and scope rules
- Module resolution algorithm (search paths, file naming conventions)
- Aliasing and name shadowing rules
- Re-export semantics
- Circular import detection

### Expand `mojo-operators.md`

Missing:
- Operator overloading via dunder methods (`__add__`, `__matmul__`, etc.)
- Comparison chaining semantics
- Custom operator definitions on user types

---

## TODO: Medium

### Conditional Trait Conformance (`where` clauses)

`where` is currently skipped in the parser. Target behavior:
- `struct Wrapper[T](Writable where conforms_to(T, Writable))` → `class Wrapper` with comment
- `def __bool__(self) where conforms_to(Self.T, Boolable)` → emit method unconditionally, add comment
- `where` clause is informational only in Python output

### ~~Lifetime/Origin Tracking~~ — COMPLETE

✅ All target behaviors implemented:
- `ref x: T` parameter → emit as `x: T` (convention prefix stripped)
- `ref` return type → drop `ref` keyword
- `Pointer(to=value)`, `UnsafePointer(to=value)` → emit as stub `Pointer(value)`
- Origin annotations → drop entirely

Parser bugs fixed (4 bugs, +12 stdlib files):
1. ✅ KW tokens (`mut`, `ref`, etc.) accepted as `.member` names
2. ✅ KW tokens accepted as keyword arg names in subscripts (`Type[mut=False, ...]`)
3. ✅ Function-call types support chained member access (`type_of(x).Foo`)
4. ✅ Subscripted exception types in `raises` clauses (`raises ExcType[Param]`)

### `UnsafePointer` Full Memory Semantics

Currently stub class only. Operations not translatable to Python:
- `ptr.bitcast[T]()` → stub returning `ptr`
- `ptr.strided_load(stride)` / `ptr.strided_store(v, stride)` → stub
- `ptr.gather(offsets)` / `ptr.scatter(v, offsets)` → stub
- `ptr.destroy_pointee()` / `ptr.take_pointee()` → stub
- `alloc[T](n)` → `[None]*n` stub
- `ptr.free()` → no-op

---

## Deferred

### Full GPU Codegen

Stub classes emitted (`DeviceContext`, `DeviceBuffer`, `HostBuffer`). GPU execution model has no Python equivalent. Full codegen would require:
- `ctx.enqueue_function(kernel, *args, grid_dim=..., block_dim=...)` → no-op stub
- `barrier()`, `syncwarp()` → no-op stubs
- `block_idx`, `thread_idx`, `global_idx` → constants returning 0
- `shuffle_*`, `prefix_sum` → warp-reduction stubs
- `LayoutTensor`, `Layout` → stub classes with `__getitem__`/`__setitem__`

Tagged **deferred** — GPU semantics cannot be faithfully emulated in Python.

### Mojo-from-Python Extension Modules

`PythonModuleBuilder`, `def_py_init()`, `def_function()`, `def_method()` etc. are the Mojo-side API for building Python extension modules. No Formal English mapping defined yet. Tagged **deferred** pending a design.
