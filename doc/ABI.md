# ABI: the module/dylib boundary contract

> The frozen C ABI for values that cross a module boundary (client ↔ stdlib
> dylib / CAS artifact). Stage 1 of `MODULE_CACHE_DESIGN.md`. Once we link
> against prebuilt artifacts instead of inlining bodies, *both sides must agree
> on this contract exactly* — it is what makes a content-addressed artifact
> reusable and what lets other languages interoperate.

**Last verified 2026-09-27 against `7604105`.** Every claim below was checked
against the tree, not carried forward on trust; four were stale and are fixed
in this revision — the header name at "Library container types" (renamed
`mojo_runtime.h` → `fire_runtime.h`), the self-hosting sibling list
(`mojo_compiler.py` → `fire_compiler.py`), the `Span` row, and the whole
exception-entry-point list. The two names were cosmetic; the last two were
**false**, which is the failure mode that matters: a contract that asserts a
`mojo_try_push` macro and a header-declared `struct Span` sends a C client
looking for declarations that do not exist. Re-verify rather than extend when
touching this file — the renames it missed (`mojo_*` → `fire_*`) are exactly
the kind of change a document at rest does not notice.

**Revised 2026-10-03**, for "The formal backend's receiver convention" only: a
receiver crosses a boundary by pointer for every struct on both formal backends,
which is the row the Methods section above already stated for the compiled
backend. That subsection is the only part of this file added since the
verification above, and it is verified against the tree in the same way — read
`formal/model.py`'s `receiver_writeback_name` for the rule and
`formal/arm64_codegen.py`'s `_allocation_split` for the storage the callee gets.
The verification date above is deliberately NOT restated: the rest of the file
was last checked at `7604105` and has not been re-read since.

The header names, the `mojo_*` ABI prefix, and the `__mojo_reflect` symbol are
load-bearing elsewhere and are **not** candidates for renaming.

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
  `len()` / `.__len__()` reads `_len`.

  **This one is not yet a usable ABI row, and the gap is deliberate and
  recorded rather than papered over.** The fat pointer is a *hardcoded model
  inside the lowering* — `mojo/backend_gimple/emit_calls.py:5324` ("Span is
  erased to a hardcoded fat-pointer `{_data, _len}` struct") and its siblings
  at `:5864` and `:6022` — not a `struct Span` in `runtime/fire_runtime.h`. So
  unlike every other row here, a C client has nothing to `#include` to write the
  declaration against, which is exactly what the Principle section above
  promises. It is listed because the layout is already load-bearing on both
  sides of an existing boundary (`test_gimple.py:1603` builds a `struct Span` in
  a fixture to test `print`'s bottom layer), not because it is closed. Closing
  it means moving the declaration into the runtime header; that is a change to
  this contract and belongs in the header, not in a client.

## Library container types (current runtime representation)

These cross the boundary as opaque pointers to the runtime types in
`runtime/fire_runtime.h`:

| Mojo | C ABI |
|---|---|
| `String` / `str` | `char *` |
| `Str` | `MojoStr *` |
| `List` / `list` | `MojoList *` |
| `Dict` / `dict` | `MojoDict *` |
| `Set` / `set` | `MojoSet *` |

### `Optional[T]` on the formal backends: the payload word, and a NICHE for `None`

**A formal value is one 64-bit word, so an `Optional[T]` is one word: the
payload. `None` is a word `T` cannot produce.** That word is decided by
`formal/model.py::optional_none_word`, mirrored in `lib/ProofLib.lean` as
`optionalNoneWord`, and it is per payload type rather than per `Optional`:

| Mojo `T` | the word `None` is |
|---|---|
| `String`, `Pointer[T]`, a container, a frame address, any struct of the module | `0` — an address, and no address a program can hold is 0 |
| `Bool` | `2` — a `Bool` is a word holding 0 or 1 |
| `Int8`/`Int16`/`Int32`, `UInt8`/`UInt16`/`UInt32` | `1 << w` — a `w`-bit value is sign-extended into a 64-bit register, so `2^w` is outside its range |
| `Int`, `Int64`, `UInt`, `UInt64`, `Float64`, `Float32`, `DType`, an unstated payload, a struct of another module | **refused** — every word is a value of it, or nothing here says what a value of it is |

So the boundary spellings are:

| Mojo | at the ABI |
|---|---|
| `Some(v)` / `Optional[T](v)` | the word `v` — the constructor is the IDENTITY |
| `None` / `Optional[T]()` | the niche word |
| `x is None`, `x == None` | `x == niche` — the same question, the same word |
| `x != None`, `x is not None` | `x != niche` |
| `x.or_else(d)`, `x.value_or(d)`, `x.or(d)` | `x == niche ? d : x` |
| `x.unsafe_value()` | `x` — there is no second word to unwrap |
| `bool(x)`, `if x:` | `x != niche` (`Optional.__bool__` is "does this Optional HAVE a value") |

**Nothing above needs a second register, a hidden word, or a frame**, which is
the whole reason it is a niche and not a tagged pair: a `w`-bit scalar's niche
is a word it cannot produce, so the value stays one word and crosses a
function boundary, a module dylib and a frame slot in the return register like
any other value. The two-word alternative — `Optional[T]` the ADDRESS of a
`{tag, payload}` pair — is what a payload with no niche needs, it reuses the
frame machinery this file's receiver section already documents, and its cost and
its three measured obstacles are in `bugs/FORMAL_optional_needs_a_niche.md`.

**A client binding one of these symbols needs to know the niche only if it
hand-builds the value.** For a payload whose niche is 0 — every
reference-shaped one — a client cannot tell the two apart by construction either,
which is why the table's word is 0 for exactly that family: an `Optional[String]`
crossing this boundary uses the same null convention a bare `String` does, and
one convention is better than two that agree today.

**This row changed an existing contract, and it is a fix rather than a break for
the same reason the receiver section is.** Before it, `None` was the word 0 for
EVERY payload, so `Some(0)` and `None` were one word: `if z is None` on
`var z: Optional[Int] = 0` took the empty branch on both architectures, with no
diagnostic. Cached artifacts built against the old convention are invalidated by
the `Stability` section below (their content hash covers the ABI), and a client
that hard-coded "0 means empty" for a `Bool` or narrow-integer payload needs the
table above.

## Functions and methods

- **Free function** `fn name(a: A, b: B) -> R` →
  `R name (A_abi a, B_abi b);` (C-keyword names get the documented `mojo_` prefix).
  If `name` is overloaded (2+ definitions with the same name, different
  signatures), the emitted symbol is `name` plus a 6-hex-digit suffix hashed
  from the C parameter types (`_func_csym`/`overload_suffix_for` in
  gimple_codegen.py) — e.g. `abs_a1b2c3`. Non-overloaded names, entry points,
  `@export`-decorated functions, and libc names are never mangled this way.
- **Struct method** `Struct.method(self, args…)` →
  `R Struct_method (Struct *self, args…);` (self first, by pointer), plus the
  same overload-hash suffix as above when the method is overloaded within its
  struct (`_method_overload_id`).
- **Module-qualified struct method symbols** (v2, this section supersedes the
  bare form above whenever a real module identity applies): a struct's method
  symbol is prefixed with its **home module's qualifier** —
  `<module-qualifier>_Struct_method<overload-suffix>` — computed as
  `module_loader.module_name_for_path(path)` on the struct's defining source
  file (path-relative to `STDLIB_PATH`; falls back to the file's own basename
  outside `STDLIB_PATH`, e.g. a test fixture). Example: `std/utils/_ansi.mojo`'s
  `struct Color` and `std/gpu/host/_tracing.mojo`'s `struct Color` — both
  compiled into one `libmojostdlib.dylib` — become `std_utils__ansi_Color_*`
  and `std_gpu_host__tracing_Color_*` respectively, never colliding at the
  linker regardless of how many unrelated modules define a same-named struct
  (see STDLIB-BUGS.md and `GimpleGen._struct_method_qualifier`/
  `_struct_method_csym`/`_struct_method_csym_static`).
  - **No qualifier** (bare form) applies to: the root module of an ordinary
    `mojo build`/`mojo run` invocation (never compiled alongside another
    module in the same dylib, so no collision risk), and this compiler's own
    self-hosting compiles of its `.py` sources (`gimple_codegen.py`,
    `fire_compiler.py`, `myinterpreter.py`, `module_loader.py`, …) — their
    bootstrap structs (`Scope`, `Parser`, `Interpreter`, …) are exempt by a
    dedicated file-identity gate (current file is a `.py` source under this
    repo's own directory), independent of whether `module_name` happens to
    be set for that particular compile.
  - **Reflection table entries** (`__mojo_reflect`, Stage 4) advertise the
    same qualified symbol the defining module actually emits
    (`reflect.collect_exports`'s `module_prefix` parameter) — a cross-module
    importer that only sees a struct via dylib reflection (no source
    available) derives its home-module qualifier directly from the
    already-qualified symbol string the reflection table provides,
    guaranteeing the client's call site and the dylib's real definition
    always agree.
- **`external_call["sym", Ret](args…)`** → a direct call to the C symbol `sym`
  with `Ret`/arg C types as lowered; one `extern` prototype per symbol is emitted
  (libc names already in our headers are not re-declared). This is the escape
  hatch to libc / OS syscalls (e.g. `write`).
- Functions are forward-declared so mutual recursion and cross-module calls work.

### The formal backend's receiver convention

**Every method's receiver crosses a boundary by POINTER, on both formal
backends, for every struct.** This section is that rule; the row above it
(`R Struct_method (Struct *self, args…)`) is the same rule, and the formal
backend used to disagree with it on exactly one shape.

| struct | receiver at the boundary | who owns the storage |
|---|---|---|
| two or more fields | the address of a frame of 8-byte slots, one per field, in declaration order | the caller, for the whole call |
| exactly one field | the address of a **one-word cell** | the caller, for the whole call |
| a method with no mutating convention (`self`) | the value, by register | the callee's copy |

So `self.f = x` in a method of either shape writes into storage the caller still
owns, and the write is visible without a convention of its own. Two consequences
are worth stating because they are what a client has to know:

- **A mutating method's return register carries the DECLARED return value and
  nothing else.** `def pop(mut self) -> Int` is one function with two effects:
  the receiver is updated through the pointer, and the popped element comes back
  in the return register. It used not to be lowerable — the return register was
  the receiver, so a method that both changed the receiver and produced a value
  had nowhere to put the value — which is why `std/collections/binary_heap.mojo`
  did not build and why 165 files behind it did not either.
- **The mutating conventions are `mut self`, `out self` and `inout self`.**
  `inout self` names the same convention as `out self` here; it is a different
  spelling, not a different ABI.

A receiver that is a method of a one-field struct is the case worth reading twice,
because the struct's *whole state* is one word: `self._value` and `self` are the
same storage (`formal/build.py`'s `_rewrite_self_fields`), which is why passing
the receiver by pointer is the only way a store to it can reach the caller at
all. A receiver passed by value there would be a copy, and the caller would keep
the old word.

**This is a change to a boundary contract, and the reason it is a fix rather than
a break is that the old convention was not describable in one.** It only worked
for a call in statement position: `c.bump(5)` became `c = Cell_bump(c, 5)`, and a
mutator call in an argument position (`sink(c.bump(5))`) or a call into another
module had nowhere to put that store and silently dropped it — the callee
computed the new value, the caller kept the old one, and both architectures
agreed on the wrong answer. See `bugs/FORMAL_binary_heap_mojo_after_the_len_value.md`
and the commit on `work/formal15-mutator-return-abi`.

**A client calling one of these symbols from C needs no declaration of its own**
if it follows the row above: `int64_t pop(struct Cell *cell)` for
`def pop(mut self) -> Int`, with `*cell` the receiver's current value on entry
and the updated value on exit. A C client that wants the receiver's value
*returned* instead — which is what a caller written against the old convention
was effectively doing — is reading a register the callee never promised.

### Exception-handling entry points

**There is no `mojo_try_push` macro.** An earlier version of this document
specified one, and it was wrong about the current design: `setjmp` is emitted
**directly into the generated function** by the try lowering
(`mojo/backend_gimple/emit_stmts.py:3531` sets `gen._func_used_setjmp`, and the
region is emitted there — `runtime/fire_runtime.h:164-165` says so in as many
words: *"setjmp is emitted directly in generated functions"*). That is why
`_mojo_exc_stack` and `_mojo_exc_top` are exported `extern` globals rather than
reached through an accessor: the generated code indexes them itself. A client
that wants to establish a catch point increments `_mojo_exc_top` and calls
`setjmp(_mojo_exc_stack[_mojo_exc_top])` in its *own* frame, for the same reason
the old macro had to be a macro.

- **`mojo_exc_pop()`** — pops the topmost frame (`void`).
- **`mojo_raise()`** — `longjmp`s to the current frame (`void`). A real function
  with no `setjmp` of its own, so it is safe to call from a wrapper
  (`runtime/fire_runtime.h:166`).
- **`mojo_exc_msg_set` / `mojo_exc_msg_get`** — set/get the string payload of a `raise` (`void` / `char *`).
- **`mojo_exc_obj_set` / `mojo_exc_obj_get`** — set/get the opaque typed exception object (`void *`).
- **`mojo_exc_type_set` / `mojo_exc_type_get`** — set/get the exception type tag
  (`void` / `int64_t`, over `extern int64_t _mojo_exc_type`;
  `runtime/fire_runtime.h:185-187`). Added since this section was first
  written and load-bearing for typed exceptions.

**Cleanup-thunk registry.** `mojo_raise`'s `longjmp` skips every C statement
between the raise site and the catching `setjmp`, including any `mojo_*_free`
call the codegen emitted for an owned local — those sit at the function's
return/fallthrough points, not on the exception path. This registry is a
userland stand-in for what a real unwinder's landing pads provide: codegen
pushes a thunk after constructing an owned local, and cancels it at the same
free call it already emits on the normal path. `mojo_raise` walks and invokes
every still-live thunk back down to the catching try's checkpoint before it
`longjmp`s, so an owned local is freed exactly once on whichever path actually
runs. All `void` except `mojo_cleanup_cancel_n` (`int64_t`);
`runtime/fire_runtime.h:203-221`, rationale at `:189-202`, and
`doc/OWNERSHIP_MODEL.md`.

- **`mojo_cleanup_push_dict` / `_list` / `_set`** — push a heap-owning thunk (`void *`).
- **`mojo_cleanup_push_dict_stack` / `_list_stack` / `_set_stack`** — push a
  *stack*-allocated thunk. Distinct from the above because an unwind past one
  of these must call `mojo_*_destroy` (buffer-only teardown) and never
  `mojo_*_free`, which would `free()` a stack address.
- **`mojo_cleanup_cancel_n(int64_t n)`** — pop the `n` most-recently-pushed
  thunks **without invoking them**; called immediately before the inline frees
  they duplicate.
- **`mojo_cleanup_checkpoint_save()`** — record the current depth as the
  catching try's checkpoint.

**Coroutine boundary.** `extern int _mojo_exc_pending` with
`mojo_exc_pending_set` / `mojo_exc_pending_get` (`runtime/fire_runtime.h:250-252`).
This is the one entry set a client must not guess at: the generated C++
generator body calls it at the `extern "C" _resume()` boundary, because an
ordinary `yield from` delegation loop re-throws as a C++ exception and gets
unwound for real, while GIMPLE C code calls `mojo_raise()` itself. A callee on
that boundary that is not a live GIMPLE C frame must not have its `longjmp`
cross ordinary live C frames (`runtime/fire_runtime.h:240-249`).

## Generics

A generic is not a single symbol; each instantiation is. The boundary symbol for
`Generic[Args]` is the **monomorphized** function, mangled as
`Generic__method__<mangled-type-args>`, keyed in the CAS by `hash(template-id,
concrete type args, comptime params)`. The reflection table exposes the generic
*template* plus a C-ABI `instantiate` entry point so a client (or another
language) can request an instantiation that is then published into the shared
CAS.

**Implemented, 2026-10-03, on the formal dylib path** (`formal/monomorph.py`).
A module dylib is compiled for the instantiations its importers ask for, each as
a CONCRETE declaration under the mangled name — `struct Pair[Int]` becomes
`struct Pair_1_T_3_Int` — compiled into that module's own library and exported
with that module's qualifier, so the boundary symbols are
`<module>_Pair_1_T_3_Int` and `<module>_Pair_1_T_3_Int_<method>`. Everything the
export rule already knew how to say is unchanged; what changed is that a module
declaring only a template now HAS something to export, and
`formal/build.py::no_public_api_reason`'s "a parametric type has no single
boundary layout either" no longer describes a module whose instantiations are
known.

Three properties are load-bearing and are worth stating here because the failure
mode in each case is a program that builds and computes the wrong answer:

* **A type argument must be a TYPE, and a name the reading scope does not bind
  as a value.** `Pair[t]()` with `var t = Float64` is not an instantiation of
  anything: the substitution would produce `var first: t` in a module that does
  not declare `t`, and the build would not notice — a field's declared type is
  not read by the framing decision — so `first + second` would compile as
  integer addition and print `3` where the source says `4.0`. The demand is
  dropped instead, and the call site keeps its brackets.
* **The demand set is part of the artifact's identity**, in the cache key and in
  the file name, for the same reason `arch` is: `Pair[Int]` and `Pair[String]`
  are two different libraries, and a program handed the wrong one binds a
  symbol it did not ask for.
* **A template is never exported under its base name.** One trie entry cannot be
  two instantiations.

The mangling is `monomorphize.mangle`, and `Pair[Int]` is `Pair_1_T_3_Int` — not
`Pair_Int`, and the difference is load-bearing: `mangle` is INJECTIVE, each
argument emitted as `{len(name)}_{name}_{len(value)}_{value}` under the base
name, so a name cannot be read back ambiguously and two instantiations cannot
collide (`monomorphize.py`'s `mangle` and `_fields` state both, and
`bugs/CODEGEN_imported_generic_never_elaborated_calls_nothing_defines.md` is why
the flat spelling was replaced). It is what the compiled path's `Elaborator`
computes and what its objects are named.

That is the one place where this section's illustrative spelling
(`Generic__method__<mangled-type-args>`) is not what is emitted, and it is
spelled out here rather than left for a reader to discover: one mangling in the
tree, two sections that could each be read as mandating their own, and a
consumer that computed the other one would bind nothing. **A document that
states a mangled spelling states THIS one, and says where it comes from** — the
stale spelling is a defect in the CONTRACT, not only in a test, so
`test_formal_monomorph.py::a_stated_mangled_spelling_is_the_one_the_mangler_produces`
reads every `doc/` and `bugs/` file and fails on any mangled spelling
`monomorphize.mangle` does not produce.
`bugs/FORMAL_generic_monomorph_scope.md` records what the mechanism does not yet
cover.

The compiled (GIMPLE) path continues to monomorphize generics inline in its
codegen rather than through this module's demand set; the two are different
engines on different backends and share the mangling and the substitution.

### When a module dylib is built at all: per EDGE, not per module

**2026-10-04, `formal/imports.py::library_free_edges`.** A module dylib exists
so that something on an import edge can bind a symbol in it, so whether it is
built is a question about the EDGE and not about the module. An edge that binds
no name the dependency could publish as one boundary symbol gets no library:
`from .binary_heap import BinaryHeap` binds a template, and since a template is
never published under its base name (above), that edge cannot bind a symbol
whatever `binary_heap.mojo` exports. Measured cost of asking per module instead:
163 swept files, 162 of which named nothing the refusing module declares — they
import a package that re-exports one template.

Four things keep a library on an edge, and each is a binder the import statement
does not enumerate: a bare `import m` (so `m.f(…)` is possible), `from m import *`
(the export set is a fact about a library that does not exist yet), a `from m
import …` inside a function body, and a **demanded instantiation** — that last
one is why `Pair[Int]()` still builds the library that publishes
`Pair_1_T_3_Int`.

A bare call to one of these names is still a refusal, and it is refused at the
call: `widen(3)` names no instantiation, so no spelling of it has a callee.
Naming the callee and the rule is the message's job
(`formal/model.py::imported_callee_refusal`), because the alternative — a
library that was never built — leaves the link-time bind audit to explain it.

## Stability

This contract is versioned with the reflection-table schema. A change to any row
above is an ABI break and invalidates cached artifacts (their content hash
includes the ABI/target, so stale artifacts are simply never matched — they are
not silently mis-linked).
