# Elaboration: the CAS-backed semantic driver — Design & Rationale

> Status: **design of record + first slice.** Elaboration is the semantic middle
> of the front end — the phase that turns *parametric* Mojo into *concrete* Mojo
> by resolving and running everything compile-time. We have the engines
> (`monomorphize.py`, `comptime.py`) and the substrate (resolution authority,
> CAS, reflection, link line) but no driver. Elaboration is that driver.
> Companions: `MODULE_CACHE_DESIGN.md`, `ABI.md`.

## The problem

Today the compiler goes mostly AST → C, with fragments of compile-time handling
smeared into `gimple_codegen` ad hoc (skip `[T]` blocks, unroll `comptime for`,
const-fold `comptime if`). The real engines exist but **nothing drives them**:
`monomorphize.instantiate` and `comptime.evaluate` are tested mechanisms with no
caller that decides *what* to instantiate or evaluate. There is no pass that says
"this call needs `List[MyType]` — instantiate it," or "this comptime param needs
evaluating." That decision-and-orchestration layer is **elaboration**, and it is
the missing organ.

## What elaboration does

Given a resolved program, elaborate each construct into concrete form:

1. **Overload / name resolution** — bind each call to a concrete callee.
2. **Generic instantiation (monomorphization)** — `foo[T]` at concrete `T` → a
   concrete function, via `monomorphize.instantiate` (CAS-cached).
3. **Comptime evaluation** — run comptime params/exprs via `comptime.evaluate`
   (compile-and-call) or the const-folder; substitute results.
4. **Trait / conformance resolution** — check a type satisfies a bound.
5. Output: concrete, typed code with no generics or comptime left — ready to lower.

## The architecture: demand-driven, CAS-backed elaborator service

Two real choices: a **separate pass** that produces a fully concrete AST the
codegen then lowers, or an **incremental layer** the codegen calls into at
generic/comptime sites. **We choose the incremental, demand-driven service**, for
three reasons:

- it matches our structure (the codegen already does fragments of this);
- demand-driven pairs perfectly with the CAS — we elaborate **only what is used**,
  and cache it;
- it is far less disruptive than a whole concrete-AST rewrite, and the decisions
  still centralize in one `Elaborator`.

Layering (each layer already exists except the top):

```
  Elaborator            decides WHAT to instantiate / evaluate / resolve   (NEW)
     │
     ├─ monomorphize.instantiate   executes + CAS-caches an instantiation
     ├─ comptime.evaluate          compiles + calls a comptime fn (cached)
     ├─ imports.Resolver           resolves names; one module per name; ABI
     └─ _link_dylibs               records each result's dylib on the link line
```

The Elaborator is the brain; the rest are organs it already has. Today they are
tested islands; elaboration is the bridge.

## The CAS connection (what the previous, CAS-less design could not do)

This is the key advance. Every elaboration result is **content-addressed**:

- A generic instantiation is keyed by `(template identity, concrete type args,
  comptime params, ABI, toolchain)` — `cas.instantiation_key`. Elaborate
  `box[Int64]` **once, ever**; the next program (or client) faults it in.
- A comptime evaluation is keyed by `cas.comptime_key`; run-and-cache once.
- The dylib each instantiation produces is **recorded on the link line** through
  the same `_link_dylibs` path imports use, so the loader binds it.

So elaboration cost across a fleet = the number of **distinct** instantiations,
not (program × instantiation). A CAS-less elaborator re-elaborates everything in
every build; ours elaborates each unique thing once and shares it. This is the
"compile speed = sum of unique work" property, applied to the semantic phase.

## Where it plugs into the codegen

- **Generic call site** `Generic[Args](x)` → elaborate to a concrete symbol +
  record its dylib; lower the call to that symbol.
- **Comptime value** beyond const-folding → `comptime.evaluate`, substitute.
- **Imported name** → resolved through the authority; generic templates resolved
  to instantiations on demand.

## Staged slices (each independently verifiable)

1. **Generic call elaboration** ✅ (the spine). `Generic[TypeArgs](args)` from an
   imported generic → instantiate via the CAS, record the object on the link
   line, emit the concrete call. Resolution + monomorphize + CAS + link line +
   codegen, end to end.
2. **Type-inferred generics** ✅ — `Generic(args)` with no explicit `[…]`: infer
   the type args from the argument C types (`elaborate.infer_type_args`).
3. **Comptime params/exprs** ✅ — a comptime call to an imported function with
   constant args is run at compile time via `comptime.evaluate` (cached machine
   code), wired into `_eval_const_int` so it drives `comptime if`/`for` and
   comptime assignments. Recursive comptime works (`fib(10)` → 55 at compile time).
4. **Overload resolution** — pick the concrete `fn` among candidates by argument
   types.
5. **Generic structs** ✅ — `Struct[TypeArgs]` instantiates the *type*: the
   struct + its methods are monomorphized into a CAS object; the client
   materializes the concrete layout (typedef + `struct_field_types`), constructs
   it, and calls its methods (`Box_Int64_unbox`) from the linked object.
   `Box[Int64](42).unbox()` → 42. (Traits/conformance bound-checking still ahead.)

## Decisions

- **Incremental demand-driven service**, not a separate concrete-AST pass.
- **Everything content-addressed** — elaborate once, ever; warm = cache hit.
- **Identity from the resolution authority** — one module per name, so "which
  generic" is unambiguous before we instantiate it.

## Verification

- `box[Int64](42)` from an imported generic module: first build instantiates
  (CAS miss), a second build / different client is a hit; the program links the
  instantiation dylib and runs; output matches a from-source build.
- Existing suites stay green: `make check` (gimple + runner + module-cache).
