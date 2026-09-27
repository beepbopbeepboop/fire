# FORMAL_module_exports_nothing: a module that compiles fine exported nothing, so its importers could not link

The second-largest `codegen/dependency` family in the arm64 sweep — ~30 of 578
files in the default scope — and the one refusal whose *message* was the worst
in the tree. Wave 3 (agent C3).

**Status: two of the four causes are fixed; the other two are correctly
refused, and now say which one they are.**

| cause | verdict | what landed |
|---|---|---|
| a package `__init__.mojo` whose whole API is `from .sub import name` | **was a bug** | it builds now, as a NAMESPACE library (`_namespace_library`); its importer links and runs |
| a re-exported struct TYPE invisible to the importer | **was a bug** | `imported_struct_defs` follows the re-export edge |
| a module dylib built for one architecture and linked into a program for another | **was a bug** | `arch` reaches the codegen, the Mach-O header and the file name; the CAS directory is per-arch |
| every public declaration is a generic template / a private name / nothing at all | **correct as a refusal** | the message now names which, and why |

---

## The export rule, and where it lives

`formal/build.py`'s `_export_entries` (now around `:1658`) is the whole
decision, and it is not this path's own: it calls
`reflect.collect_exports_src(text, prefix)`, which is the **same function the
gimple dylib's reflection table uses**. That is deliberate and is the right
constraint — one rule, so a symbol cannot be findable in one backend's dylib and
absent from the other's. It excludes, in `reflect.py`:

| excluded | where | why |
|---|---|---|
| a `_`-prefixed name | `collect_exports`: `not s.name.startswith('_')` | private by convention, and by ABI.md's public-symbol rule |
| a generic template (`fn name[...]`) | `collect_exports_src`: `re.findall(r'\b(?:fn\|def)\s+(\w+)\s*\[', src)` | no single concrete symbol exists |
| a generic struct template (`struct S[T]`) | same regex, `\bstruct\s+(\w+)\s*\[` | no single layout exists |
| an overloaded name (2+ defs, differing signatures) | `collect_exports_src`'s `dup_def_signature_key` pass | selected per call site, not one symbol |
| a `_CLIB_SYMS` name | same function | libc provides it |

## What `doc/ABI.md` says the boundary is

Read, because the message claims a documented contract:

- **§ Functions and methods** — a free function is `R name(A a, B b)`, bare
  and unmangled unless overloaded; a struct method is `R Struct_method
  (Struct *self, …)`, module-qualified in v2. **Nothing here says which
  symbols cross** — it fixes their *spelling*, given that they cross.
- **§ Aggregates** — a type crosses as its field layout *in the reflection
  table*, not as a function symbol. This backend emits no reflection table, so
  a type-only module has nothing to put in a trie.
- **§ Generics** — the load-bearing line, verbatim: *"A generic is not a
  single symbol; each instantiation is. The boundary symbol for `Generic[Args]`
  is the **monomorphized** function, mangled as `Generic__method__<mangled-type-args>`,
  keyed in the CAS by `hash(template-id, concrete type args, comptime params)`.
  … **Until Stage 5, generics are monomorphized inline by the codegen.**"*

So the document is explicit that a generic is not exportable *as a template*,
and equally explicit about what would make it exportable: per-instantiation
symbols, keyed by type arguments. That is Stage 5 and it does not exist here.

## What the message used to say, and why that was the real cost

> `formal dylib has no public functions: X exports nothing under doc/ABI.md's
> rules (a struct-only module has no free-function API, and this backend
> compiles no struct methods)`

False for three of the four real cases, and a struct-only module is the *one*
case the rule above does not even reach, because a struct-only module's methods
are already handled separately by `_formal_exports`'s `methods` branch. Measured
against the family, by the shape of the terminal module:

| terminal | real reason | old message |
|---|---|---|
| `std/stat/stat.mojo` | 7 public functions, every one generic (`S_ISLNK[intable: Intable]`) | "struct-only, no free-function API" |
| `std/sys/_assembly.mojo` | one public function, generic (`inlined_assembly[…]`) | same |
| `std/algorithm/backend/tile.mojo` | one public function, generic (`tile[…]`) | same |
| `std/reflection/function.mojo` | one generic struct template; no function at all | same |
| `std/utils/_select.mojo` | one declaration, and it is private | same |
| `std/sys/_io.mojo` | **no declaration at all** — three `comptime` constants | same |
| `std/gpu/host/nvidia/__init__.mojo` | **no declaration at all** — a docstring | same |
| `…/__init__.mojo` (a re-export-only package) | a real, complete public API in a submodule | same |

A refusal that is wrong about the file is worse than no refusal: it sends the
reader looking for a struct that is not there, which is what made 30 files read
as one 30-file bug. `no_public_api_reason` (`formal/build.py`) now names which
of the four it is, from the module's own declarations, and names the offending
declarations.

## The real bug: a package `__init__.mojo` is a module with an API

Most of the stdlib's packages are re-export-only `__init__.mojo` files —
`std/stat`, `std/atomic`, `std/ffi`, `std/compile`, `std/sys`,
`std/reflection`, `std/gpu/sync`, `std/algorithm/backend`, and the rest are
nothing but `from .sub import a, b, c`. Such a module has a real, public,
importable API. It was refused, so **every file that imports the package**
could not build — over a module with nothing wrong with it.

The definition was there the whole time, compiled and exported, in the
submodule whose dylib was already on the importer's link line. The fix is to
stop pretending the package needs a symbol of its own:

- `formal/imports.py`'s `reexported_names` computes the names a module binds by
  re-export and does not define, each with the *declared kind* in the defining
  module (`declared_kinds`).
- `formal/build.py`'s `_namespace_library` emits a real MH_DYLIB with **no code
  and an empty export trie**, and a manifest with `kind: "namespace"`,
  `exports: []`, and the forwarding recorded under `reexports`.

**The empty trie is the design, not a shortcut.** A re-export is not a new
definition, so the symbol must not be copied into the package's table: the
export trie is an *address* lookup, and an entry for a symbol this image does
not contain sends every consumer of the package to an address inside a file
with no code. The names already resolve — the consumer's symbol map is built
from the manifests of every library on its link line, and the submodule's
manifest maps `bump` to the symbol the submodule really defines. So the correct
export table for a namespace library is the empty one, and the only thing that
has to be right about it is that it is empty. `test_formal_imports.py`'s
`test_namespace_library_exports_nothing` asserts exactly that, reading the trie
with a reader independent of the writer.

Two guards keep this from trading a build error for a wrong answer:

- `load_dylib_manifests` accepts an empty `exports` list **only** for
  `kind: "namespace"`. Its "a library with nothing to offer is a mistake worth
  refusing" check is unchanged for every other library.
- A re-exported **function** that no dependency exports is still refused, naming
  the name (`test_reexport_of_an_unexported_name_is_refused`). Otherwise the
  package would build, the consumer's call would stay unbound, and the failure
  would move to dyld at launch.

A re-exported **type** is deliberately *not* in that set: a type has no function
symbol to bind. It crosses as a layout in the reflection table and reaches the
importer as a `StructDef`, so `imported_struct_defs` now follows the same
re-export edge (`test_reexported_type_reaches_the_importer`).

## Why the generic case is a refusal and not a fix

**MOVED (wave 4, D5) to [`FORMAL_known_limits.md`](FORMAL_known_limits.md) §1.2,
"What would close it, and what it costs", which now owns the Stage 5
monomorphization limit together with its per-module audit.** The short
version, kept here because it is the reason the rule exists rather than the
limit itself: the tempting one-line change is to stop excluding generic
templates so `stat.mojo` exports `S_ISREG` and 20-odd files build, and **that
would be wrong, not conservative.** `S_ISREG` as one trie entry is *one*
function; called at `Int` and at some other `Intable` it is two, and one
address cannot be both. A consumer with different type arguments would
silently bind the first instantiation's body — a build-time error traded for a
run-time wrong answer, which is the one trade this whole mechanism exists to
refuse.

## The per-architecture dylib bug (wave 2's B4, left open)

> `example_imports.mojo` cannot load on x86-64: `mach-o file, but is an
> incompatible architecture`

Reproduced, and **the cause was one level deeper than "one arch-agnostic path
in the CAS"**. Three separate keys were not the thing being keyed:

1. **`compile_formal_dylib` had no `arch` parameter at all.** It hardwired
   `ARM64Codegen(...)` and called `build_macho_dylib` with no `arch`, so a
   module dylib was *always* an arm64 image — the same class of defect as the
   executable path's, and the one that actually made an x86-64 program
   unloadable. `build_macho_dylib` and `_make_codegen` were already
   arch-parameterised; nothing called them with the architecture.
2. **One CAS directory for both.** `out_dir` was
   `cas/formal-imports`, so the two architectures overwrote each other's
   library. Now `formal-imports/<arch>/`, *and* the architecture is in the file
   name, because a caller may pass any directory and a name that collides
   across architectures reintroduces the same overwrite one level up.
3. **`_BUILT` was keyed by source path alone**, so a process that built the same
   module for two architectures got the first one's dylib back for the second
   request. Now keyed `(arch, path)`. A fourth, found while testing: a relative
   import spelled `.sub` was used *literally* as the module identity, so every
   package's `from .sub import …` wrote `_sub.dylib` into one shared directory
   and two packages' libraries silently replaced each other. A relative name is
   now qualified by the module that spelled it (`_module_identity`).

The observable symptom was the worst kind: the program **built, linked, and
passed every static check**, and then dyld refused to load it. Nothing in the
build pipeline could see it.

### B4's no-publish rule is still needed

`tools/formal_sweep.py` declines to cache a verdict for an image that links a
formal dylib, "because the dylib is not in the key". Fixing the architecture
does **not** close that, and the rule should stay:

`cas.formal_build_key` folds in the importing file's own source,
`formal_fingerprint()` (formal/**, the parser, mojo/middle), the Python
interpreter, the build flags and the sweep tool's own bytes. It deliberately
does **not** fold in the stdlib — its own docstring says so, for the
non-importing case. But a formal dylib is built from the *imported module's*
source, so a stdlib edit changes the dylib without changing the importing
file's key, and a cached `ok` could outlive the library it was measured
against. That is a false PASS, the outcome worse than being wrong the other
way.

(The sweep's own comment now understates the reason — it names only the
architecture overwrite. That comment wants updating to name the stdlib source as
well; `tools/formal_sweep.py` is C1's file and was left untouched.)

## What is still open

- **Stage 5 monomorphization on the formal path.** MOVED to
  `FORMAL_known_limits.md` §1.2, which owns it and re-measures the family.
  (The count here was stale: it read "23 of the 28 remaining refusals,
  `_assembly` ×14"; on the 2026-09-26 tree the family is **33 files over 8
  terminal modules**, `_assembly` ×19 — the three extra are files whose
  blocking reason moved when the by-reference work landed, not new refusals.
  Six of the 33 are *permanent* and would not be unblocked by it at all — the
  three behind `_io.mojo`, the one behind `_unicode_lookups.mojo`, the
  docstring-only `__init__.mojo`, and the private `_select.mojo` — so the real
  ceiling is 27, not 33.)
- **`_candidates` destroys `..` and `.`** (`formal/imports.py`: `rel =
  module_name.replace(".", os.sep)` turns `".."` into `"/"`, so the real parent
  directory is never tried and the leaf fallback finds the importing file's OWN
  `__init__.mojo` instead). So `from .. import X` inside
  `std/gpu/host/nvidia/` resolves to `std/gpu/host/nvidia/__init__.mojo` rather
  than `std/gpu/host/`. Not fixed here: the leaf fallback in the same function
  is load-bearing for `import formal.types` inside `formal/`, so the blast
  radius is every dotted import in the tree, and it is a different bug from
  this one.
- **Struct methods across modules for a struct-only module.** A struct-only
  module's methods are exported by name (`_method_exports`) but the *symbol*
  naming and the codegen's idea of a struct's frame have to agree for a
  cross-module method call to bind. `test_a_struct_method_is_callable_across_
  modules` passes for a one-field struct; the by-reference work (C2) is what
  makes the wider case reachable, and that is C2's lane.
