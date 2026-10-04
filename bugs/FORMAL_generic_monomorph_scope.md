# FORMAL_generic_monomorph_scope: what a generic's instantiation does NOT cover

**Area:** `formal/monomorph.py` · **Status:** OPEN — the mechanism landed
2026-10-03 on `work/formal15-generic-monomorph` and these are its measured
remainders, not a proposal · **Layer:** 1/5 of the formal work

**§9 and §9a are DONE (2026-10-03 `formal25-3`, 2026-10-04 `formal18-4`), so
read §9a before §1**: §1a says §1's construct was unmeasurable until §9 was
fixed, and §1a is still true — §9a removed the LIBRARY half of the same wall,
which was a third bug underneath it and is named there. What is left is §1a
itself (a name resolution, and an ABI decision), §2 (a dotted application), §3
(comptime-valued parameters), §4 (a type declared in the consumer), §8 (trait
bounds), and the cross-module-library half filed as
`bugs/FORMAL_a_library_calling_another_modules_template_instantiation.md`.

The mechanism itself is `formal/monomorph.py` and its two call sites in
`formal/imports.py` (`instantiation_demands`, `imported_instantiations`); the
contract it implements is `doc/ABI.md` §Generics. What follows is what it
covers, ordered by how many real files each item is likely to be worth, with
the reason each is not merely unimplemented but **refused or inert today** — so
a reader knows which of them is a wrong answer waiting to happen and which is
simply a gap.

None of these is a regression: before 2026-10-03 the whole class was one
refusal (`formal/build.py::no_public_api_reason`, "a parametric type has no
single boundary layout either"), so every item below was already refused.

---

## 1. A type argument in a NON-CALL position is not a demand

**The construct.** `def keep(p: Pair[Int]) -> Int` , `var xs: List[Pair[Int]]`,
a `Pair[Int]` field's annotation, a `Pair[Int]` in a `return_type`. The
instantiation exists — `Pair_1_T_3_Int` is what the boundary symbol has to be,
because `monomorphize.mangle` is the one mangler and it is injective (§6) — and
nothing looks for it, so the program is refused with
`formal/model.py::specialization_call_refusal` at the constructor that has to
bind it.

**Why it is not a third fix in the same commit.** `formal/monomorph.py`'s demand
walk reads CALL SITES because that is the only place the type arguments are
written as a bracket. A parameter annotation is a STRING in
`fire_compiler.FunctionDef.params` (`(name, type)`), a field's is a string on
`F.VarDecl`, and a `return_type` is an expression — three different shapes, none
of them a subscript node, so recognising them means recognising
`Pair[Int]`-shaped text in a type position, which is a second spelling rule
beside the AST one rather than an extension of it. It is the right next step and
it is a step, not a line.

**What it costs to measure.** `grep -c 'Pair\[' ` over a stdlib module is not
the measurement; `formal_declared_param_census.py`'s harness is, and it already
walks parameter annotations.

### 1a MEASURED 2026-10-04 (`formal25-3`): §1 is not a DEMAND question, and the
### wall in front of it is bigger than §1

The cost-to-measure line above was followed, and the measurement moves the item.
**The demand is recorded and the layout crosses; what is missing is that a type
POSITION is not RESOLVED to the instantiation's name**, and the first place that
shows is the cross-image frame-holder contract, which compares names.

Four programs, each built on both architectures with
`fire.py build --formal --no-prove`:

| # | shape | before |
|---|---|---|
| 1 | `struct Box[T]: var v: T` + `Box[Int]()` in ONE file | **refused by name** — §9, FIXED 2026-10-04 |
| 2 | `def twice[T]` + `twice[Int](n)` in ONE file | **builds** (the local specialisation machinery) |
| 3 | library declares `struct Pair[T]` + a method; program applies `Pair[Int]()` and calls the method | **refused by name** — §9, FIXED 2026-10-04 |
| 4 | library declares `struct Pair[T]` **and** `def keep(p: Pair[Int]) -> Int`; program applies `Pair[Int]()` and passes it to `keep` | **refused, and the message is the point** |

Row 4's message, verbatim:

```
build: a Pair receiver is passed to keep() at argument position 0, and keep's own
manifest says the parameter in that position is a frame holder of Pair: the module
that defines keep() compiled it that way, so a field re…
```

`Pair` is the TEMPLATE and `Pair_1_T_3_Int` is the instantiation. `keep` is
compiled inside the library, where its parameter annotation reads `Pair[Int]` and
resolves to the template's own name; the caller holds the instantiation, because
that is the only name it was given. So the demand, the mangling and the layout
all worked — row 3 gets as far as a method call — and what refuses is two
spellings of one type.

**So §1's next step is not a second spelling rule; it is a NAME RESOLUTION, and
it carries a question this document has not asked.** `libA` is compiled ONCE per
demand set (`demands_key` is part of the artifact's CAS key), and `keep`'s
annotation names a type whose instantiated name depends on that set. A library
asked for both `Pair[Int]` and `Pair[String]` has ONE `keep`, so either it is
compiled per instantiation of the types in its signature — i.e. a function whose
signature mentions an instantiated type is itself a template — or the annotation
resolves to a set-independent name and the per-parameter contract carries the
instantiation rather than a name. **Both are ABI decisions, which is why this
document is where they belong and a patch is not.**

And the measurement §1 asked for is **0 programs today**, for a reason worth
recording: a program that needs an instantiation has to write the bracket
somewhere it can be seen. The only way to obtain a `Pair[Int]` value without
writing `Pair[Int]()` is a function that returns one — and a function that
CONSTRUCTS one writes the bracket in the module that declares the template, which
is row 1's shape. **§1 was unmeasurable until §9 was fixed**, which is the order
the two were in.

---

## 2. A DOTTED application — `mod.Pair[Int]()`

**The construct.** `import std.collections.binary_heap as bh`, then
`bh.BinaryHeap[Int]()`.

**Why it is refused rather than demanded.**
`mojo/middle/comptime.specialization_name` — the one recogniser of the shape,
which `formal/model.py::subscript_callee_names` and both backends'
`_specialization_of` already ask — answers `None` for a dotted base, BY DESIGN
(`formal/model.py::refuse_a_dotted_specialized_callee_names` is what depends on
it). Widening it here would mean a second recogniser that disagrees with the
one every backend consults, and the disagreement's failure mode is a call bound
to the wrong module's instantiation.

**Note that the ALIASED IMPORT form is not affected**: `from pairlib import Pair
as P` then `P[Int]()` is a bare name, and `formal/imports.py::import_bindings`
already maps `P` back to `pairlib`'s `Pair`. The gap is only the
`module.Name[…]` spelling.

---

## 3. A comptime specialization of an IMPORTED template — `tile[2, 3](…)`

**The construct.** `std/algorithm/backend/tile.mojo`'s four `def tile[…]`
overloads, called with a bracket of VALUES. This is the `uses:` row in
`bugs/FORMAL_sweep_work_map_2026-10-03_b8.md` §3.1: 4 files, all of them using
`tile`.

**Why it is a different feature with a different ABI.** A `T` is a type and the
mangling is `safe_suffix(type)`; a comptime parameter is a VALUE and its identity
belongs in the CAS key as a comptime param (`doc/ABI.md` §Generics says
`hash(template-id, concrete type args, comptime params)` — the third component is
this case and nothing in the current key carries it). Admitting it now would
publish `tile_2_3` for a specialization of a value parameter and put two
different notions of identity in one mangled name.

**What closes it.** `elaborate.elaborate_generic_call`'s own `ArgC` fold is the
precedent for folding a non-type argument into the instantiation identity;
`formal/monomorph.py::instantiate` would grow a `comptime` mapping beside
`type_args`, and `demands_key` would carry both.

---

## 4. A type argument that is a type declared in the CONSUMER's own file

`formal/monomorph.py::type_arg_text` accepts a bare identifier when the reading
scope does not bind it as a VALUE — `formal/build.py::_names_bound_in` for a
function, `formal/model.py::collect_module_symbols` for the module level. A
struct the consumer's OWN file declares is therefore not accepted as an
instantiation's type argument, so:

    # lib.mojo
    struct Pair[T]:
        var first: T
    # prog.mojo
    struct Colour:
        var rgb: Int
    def main():
        var a = Pair[Colour]()      # refused

**Why the conservative direction is right.** The instantiation is compiled into
`lib`'s library, and `lib` does not declare `Colour`, so `Pair_1_T_6_Colour`
would be a body whose field layout the defining module cannot compute. Accepting
it would mean threading the layout across the boundary — which is a layout
question, not a mangling one, and belongs with whoever grows the reflection
table.

**What it costs.** `formal/model.py::struct_is_framed` counts FIELDS and does not
read a declared type, which is why item §5 below is a wrong answer rather than a
refusal. Reading a field's declared type is a value-model question with a doc
(`bugs/FORMAL_string_value_model.md` is the measured instance of it).

---

## 5. (not a gap — the reason §4 is conservative, recorded so it is not
## rediscovered) A field's DECLARED type is not read by the framing decision

`formal/model.py::struct_is_framed` asks `struct_field_count(st) > 1`. It does
not look at `st.fields[i].type_ann`. So a generated `struct Pair2_t: var first:
t` frames as two words and compiles, whatever `t` meant.

That is load-bearing for §4 and for the whole argument in
`formal/monomorph.py::type_arg_text`: **a substitution that produces a
nonexistent type produces no diagnostic anywhere in the build.** Measured, on the
case §4 is built from:

    # lib.mojo
    struct Pair2[T]:
        var first: T
        var second: T
        def scaled(self) -> T:
            return self.first + self.second
    # prog.mojo
    def main():
        var t = Float64
        var a = Pair2[t]()
        a.first = 1.5
        a.second = 2.5
        print(a.scaled())        # CPython 4.0, the formal path 3

and `test_formal_monomorph.py`'s `a non-concrete type argument is still refused`
now asserts the build REFUSES it, so a regression to the silent version fails a
test rather than a program.

---

## 6. The mangling spelling, and `doc/ABI.md`'s example

**Corrected 2026-10-04.** This section used to assert that `monomorphize.mangle`
emits `Pair_Int`; it emits `Pair_1_T_3_Int`, and it has emitted that since the
encoding was made injective — 1512 collisions over 1752 generated
`(name, type_args)` pairs under the flat scheme, measured in
`monomorphize.py::safe_suffix`'s docstring, and
`bugs/CODEGEN_imported_generic_never_elaborated_calls_nothing_defines.md` is the
defect that motivated the change. Every spelling in `doc/ABI.md` §Generics and in
this document now states the injective one and names `monomorphize.mangle` as
where it is stated, and `test_formal_monomorph.py::a_stated_mangled_spelling_is_the_one_the_mangler_produces`
reads every `doc/` and `bugs/` file so a stale one cannot be written again — the
`refuse_without:` class of defect, in prose: a document that names a repair the
tree has already replaced sends a reader to build the thing that exists.

`doc/ABI.md` §Generics illustrates `Generic__method__<mangled-type-args>`. That
is illustrative and not wrong, and it is why the section says so explicitly;
`Pair[Int]`'s real spelling is stated beside it. The tree has one mangler, which
is the correct number, and the two documents that could each be read as mandating
their own now agree.

The choice was made by reuse rather than by decision: `monomorphize.mangle` is
what `elaborate.Elaborator` puts in `info['symbol']` and what the compiled
path's objects are named, so a second spelling would make the two backends'
symbols disagree for one source — and nothing on either side would notice until
a link failed. `doc/ABI.md` §Generics is the load-bearing citation for the
*decision* (a generic is not one symbol) and its illustration is illustrative;
it has been amended in place to say so, which is the resolution the two
sentences can have.

**What would make it a decision rather than a deferral:** an ABI version bump
plus a change to the spelling itself, with the CAS key folding the version —
`cas.ABI_VERSION` is the mechanism and the gimple path already invalidates on
it. Not worth doing for a spelling nothing consumes yet, and note that a change
to the encoding is now a change to every cached artifact by construction.

---

---

## 7. MEASURED 2026-10-03: what the stdlib's own generic struct templates look
## like, and why none of them is a one-line widening of this

Four probes, all `fire.py build --formal --no-prove` on a program that APPLIES a
template from the stdlib, because "it works on a fixture" and "it works on the
codebase it exists for" are different claims and only the second one is worth
anything.

| what was tried | what happened |
|---|---|
| `from std.collections.binary_heap import BinaryHeap` + `BinaryHeap[Int]()` | `binary_heap.mojo: BinaryHeap.pop() both changes its receiver and returns a value` — `mutating_receiver_return_refusal`, a PREP-time refusal that pre-empts everything else in the file. **This is the FIRST wall and it is not this mechanism's.** It is `formal13-5`'s `receiver_writeback_name` area and `formal15-mutator-return-abi`'s row |
| `from std.collections import Deque` / `from std.collections.deque import Deque` + `Deque[Int]()` | the same refusal, reached through `deque.mojo:20`'s `from std.collections import Deque`. **Every module in `std/collections` imports the package `__init__`, which re-exports `BinaryHeap`** — which is `FORMAL_sweep_work_map_2026-10-03_b8.md` §3.1's "162 of the 165 name nothing `binary_heap.mojo` declares", restated as an import |
| `from stat import S_ISREG` + `S_ISREG[Int](1)` | `S_ISREG[…](…) calls a name this unit does not compile`. **Not a gap in this module**: `resolve_module_path` prefers Mojo source over the stdlib loader, so `stat` resolved to `formal/hostmods/stat.mojo`, which declares no templates. The stdlib's `std/stat/stat.mojo` was never reached |
| `std/complex/complex.mojo`'s `ComplexSIMD[dtype: DType, length: SIMDLength]` | its arguments are written `.float32` — a `F.DottedLiteral` — and `type_arg_text` has no arm for one. Same class as §3: a parameter whose identity is a VALUE, not a type. `std/utils/static_tuple.mojo`'s `StaticTuple[element_type, size]` is worse for a different reason (`__mlir_type[…]` in a `comptime` field) |

So the shape that is actually common in the stdlib is §3 (a comptime-valued
parameter) and §7's trait bound, and the shape §1–§2 leave alone is the one
these fixtures exercise. **That is the finding, and it is a statement about
what to widen rather than an excuse:** widening to `DType`/comptime parameters
(§3) is worth more stdlib files than anything else in this list, and it is a
different ABI question because the third component of `doc/ABI.md` §Generics'
CAS key — `comptime params` — is exactly that case and nothing in the current
`demands_key` carries it.

Until `binary_heap.mojo`'s `pop()` lowers, no measurement of *file coverage* is
possible from here at all: the terminal refusal is upstream of every template in
`std/collections`. Removing the export gate (this branch) and removing that
refusal (`formal15-mutator-return-abi`) are both necessary and neither is
sufficient.

---

## 8. What is NOT here, deliberately

* **A generic with a trait bound.** `formal/monomorph.py::instantiate`
  substitutes without checking conformance, where
  `elaborate.check_bounds` does. `std/collections/binary_heap.mojo`'s
  `BinaryHeap[T: Copyable & Comparable & Deinitable]` is the shape, and the
  substituted body is checked by the ordinary build for whatever it can check —
  but a conformance VIOLATION is currently a field type that does not exist,
  which is §5's failure mode. **The first time this feature meets a bounded
  template in the stdlib, this is the hole it will fall through**, and the repair
  is `elaborate.check_conformance` reached from here.
* **Instantiating a template from inside the template.** `Pair[T]` whose body
  says `Pair[T]()` is not a recursion here — `instantiate` substitutes text and
  does not descend — and the result is correct, because `Pair_1_T_3_Int` is a
  struct in the same module. Worth knowing rather than worth a guard.
* **Lean.** `DylibExport` is stated over arm64 machine code with (name, address)
  rows read from the manifest, and an instantiation adds rows of that shape. No
  instruction, no calling convention, no model change; `formal/dylib`'s proved
  path is exercised unchanged.

---

## 9. FIXED 2026-10-04 (`formal25-3`): a STRUCT template the module DECLARES can
## itself apply — it was refused by name

**Found while measuring §1** (§1a), and it was not in this document: the one
demand set no caller could see was a module's OWN.

`formal/monomorph.py::demands` skips a consumer's own templates on purpose, and
`formal/imports.py::instantiation_demands` passes `own_templates` for the same
reason — `demands`'s own docstring gives it, and the reason is **true of a
FUNCTION template and false of a STRUCT template**:

| shape | before | why |
|---|---|---|
| `def twice[T]` beside `twice[Int](n)` | builds | `_specialization_of` → `comptime.specialization_name` is a CALL specialisation and needs no declaration |
| `struct Box[T]` beside `Box[Int]()` | **refused on both architectures** | a call to a name this unit does not compile: `_callee_defs(functions)` is a table of FUNCTIONS, and the instantiation is emitted under a mangled name nothing had emitted |

```
build: Box[…](…) calls a name this unit does not compile, so the brackets cannot
be bound. If `Box` is a generic of another module then its instantiation is the
boundary symbol … so a call arriving here asked for none …
```

The sentence is true of the file and the file is not wrong: it asks an importer's
question of a module's own body. One field or two, executable or library — the
same refusal in all four shapes.

**What landed.** `formal/imports.py::imported_instantiations` asks for the
module's own demands as well (`own=()`, this file's own templates) and
`_own_instantiations` runs them through the same `instantiate_all` /
`rewrite_instantiation_calls` the imported half uses, so the declaration and the
rewrite stay one table — the property that function is built around. **The
instantiated source is APPENDED to `stmts`,** and that is the half the imported
set does not need: an imported template's body is compiled into the library that
declares it, while an executable IS the whole compilation unit. The intermediate
state is worth recording because it is the trap: with the declaration but not the
body, a program constructed the struct, read and wrote its fields, and then failed
the first METHOD call with the link audit's sentence — a message about the link
line where the construct is `a.get()`. **A declaration without its body makes the
diagnostic worse, so the body is not optional to this change.**

Measured after: the one-file case builds and RUNS on both architectures, and so
does the cross-module case with a method (§1a's rows 1 and 3).
`test_formal_monomorph.py`'s `a struct template the module declares can itself
apply` is the differential on both, with TWO instantiations in one file (prints 7
then 1) because the failure this must not have is the two collapsing onto one
symbol; its `lib=None` option is the one-file shape, which no case had.

### 9a FIXED 2026-10-04 (`formal18-4`): the LIBRARY half, and the two things behind it

**Status: DONE.** `016d938f` and `c466b3ee` on `work/formal18-4`. The measured
refusal, on both architectures and with the message this section quotes:

```
build: main.mojo imports 'pairlib', which cannot be built either: pairlib.mojo:
`Pair[…](…) calls a name this unit does not compile, so the brackets cannot be
bound … so a call arriving here asked for none
```

is gone, and `pairlib.mojo` — which declares `struct Pair[T]`, applies it at
`Pair[Int]`, and publishes `make_pair` — builds as a dylib, runs, and answers
7 on arm64 and on x86-64. The three changes, one per reader, and each of them a
function that already existed for the executable path:

  * **`monomorph.own_demands`** is the own demand set as a NAME, and
    `build_module_dylib` merges it into `mine` **before `demands_key`**. That
    position is the substance of the first half: the own instantiations change
    what the library publishes, so they belong in the artifact's identity
    exactly as an importer's demand does, and a library built for its own
    `Pair[Int]` must not share a path with one built for its own `Pair[Bool]`.
    `test_formal_monomorph.py`'s "two demand sets are two libraries" is what
    that key is for, and the own half now feeds it.
  * **`compile_formal_dylib(statements={path: stmts})`** — the same seam
    `compile_formal`'s own `stmts` parameter is, and for the same reason: the
    rewrite is on the AST (`rewrite_instantiation_calls`), and publishing a
    rewritten COPY of the module would have had to reproduce its prefix, its
    line numbers and its error text, and the file on disk would stop being what
    the library was built from. `build_module_dylib` parses ONCE and hands the
    result over, so a module that needs the rewrite pays no second parse and
    `{}` means "parse here" for every other caller.
  * **the library's sources are a MERGED struct table for every source's
    preparation**, which this section did not know about and which is a bug in
    its own right — see below.

**The thing behind it, and it is the reason this was not a two-line change: a
library compiled from SEVERAL sources could not use a struct declared in another
one.** `_prepare_functions` runs once per source with that source's own
declarations, which is right for an executable (there is only one) and wrong
here for every fact that is a property of the IMAGE — the frame-holder analysis
that writes `fn._frame_slots`, and the method dispatch table. Measured, both
architectures, `libx.mojo` declaring `Thing` and `liby.mojo` writing `t.v = 7`:

```
formal dylib: use_it: 't.v' is a field access through 't', and this path has no
way to say what 't' holds … Bind the base from a constructor whose declaration
THIS IMAGE can see (`x = S()`)
```

— with `libx.mojo` one file above it on the same command line. The emitter was
meanwhile handed the MERGED `library_structs`, so two halves of one build
disagreed about one image. The instantiated declaration arrives as a SECOND
source of the library, so §9a could not land without this.

The merge is dropped again the moment the analysis has had it, PER FILE, and
that is not tidiness: `_method_exports` derives a method's module qualifier from
the file its struct was declared in, so a per-file table carrying its siblings'
declarations publishes `Thing.get` under the prefix of the file that USES it —
a library that builds, links, and then fails to load with "Symbol not found"
for a method it does export. A ONE-source library is untouched: the merge is
empty and the filter a no-op, so every module dylib `build_module_dylib` builds
is byte-identical to what it was until it has an instantiation to publish.

**Tests.** `test_formal_dylib.py`'s "a library source can use a sibling
source's struct" is the merge on its own — both architectures, both field
shapes (one field is the value, two is a frame address), and the export
qualifier pinned per file. `test_formal_monomorph.py`'s "a module that applies
its own template publishes it" is §9a — a CPython differential, TWO
instantiations in one library so the two cannot collapse onto one symbol, plus
the manifest's `pairlib_Pair_1_T_3_Int_get_first`, which is the half that says
the mechanism ran rather than having been inlined.

**Two stale rows this fixed, which is the other half of the answer.**
`test_formal_run.py` was RED on `master` over `struct Box[T: AnyType, U:
AnyType]` + `Box[Int, Int](7)`: §9 — the module that both DECLARES and APPLIES
a template — made that program build, and two rows still expected the refusal
it no longer owes. Measured RED with this change reverse-applied, so they were
this change's consequence and not a second defect. One is now an answer row (7,
both backends), and one is deleted because `refuse_without:` cannot be said
about a program that builds; its twin assertion survives on the row that puts a
VALUE in the bracket, which still refuses and still asserts the absence of the
same two sentences. `test_formal_run.py` is 997/997.

**What is still open on the LIBRARY side, and it is a different piece of work:**
a library that applies ANOTHER module's template (`libb` calling `liba`'s
`Pair[Int]`) is still refused, and the refusal's last sentence — "so this call
is one that asked for none" — is FALSE about it: the demand is computed, the
dependency publishes the instantiation, and only the call-site rewrite and the
declaration are missing. Measured, both architectures, with the reason and the
exact next step:
`bugs/FORMAL_a_library_calling_another_modules_template_instantiation.md`.

**The original text, which is what the fix had to satisfy:** a module that
applies its own template **and is built as a dylib** is refused, with the same
message. `compile_formal_dylib` re-parses each source and never calls
`_imported_structs`, so `imported_instantiations` — which mutates `stmts` — is
not on that path at all; the two halves that would fix it are
`build_module_dylib`'s `mine` (the demand set, which `own_templates` empties)
and a rewrite of the call sites in the statements `compile_formal_dylib` parses
itself. Compiling the instantiation into the library **without** the rewrite is
the trap above with a stranger message, which is why it is not done here.

§1a is upstream of it for a library, because §1a is the name resolution and the
library's own body needs the same one: `keep(p: Pair[Int])` inside `libA` names
the template whatever the demand set is.

### 9b The measurement that put §1a and §9 in this order

`--mix` corpus aside, the ordering is not a preference: §1's construct is
unreachable until a value of an instantiated type can be obtained at all, and the
only source of one is a function that constructs it, which writes the bracket in
the module that declares the template. **Anything that measures §1 has to fix
§9 first**, and a planner reading this document in the other order will measure
zero and conclude the item is worth nothing.
