# FORMAL_generic_monomorph_scope: what a generic's instantiation does NOT cover

**Area:** `formal/monomorph.py` · **Status:** OPEN — the mechanism landed
2026-10-03 on `work/formal15-generic-monomorph` and these are its measured
remainders, not a proposal · **Layer:** 1/5 of the formal work

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
instantiation exists — `Pair_Int` is what the boundary symbol has to be — and
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
`lib`'s library, and `lib` does not declare `Colour`, so `Pair_Colour` would be a
body whose field layout the defining module cannot compute. Accepting it would
mean threading the layout across the boundary — which is a layout question, not
a mangling one, and belongs with whoever grows the reflection table.

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

`monomorphize.mangle` emits `Pair_Int`. `doc/ABI.md` §Generics illustrates
`Generic__method__<mangled-type-args>`. They are different strings and the tree
has one mangler, which is the correct number.

The choice was made by reuse rather than by decision: `monomorphize.mangle` is
what `elaborate.Elaborator` puts in `info['symbol']` and what the compiled
path's objects are named, so a second spelling would make the two backends'
symbols disagree for one source — and nothing on either side would notice until a
link failed. `doc/ABI.md` §Generics is the load-bearing citation for the
*decision* (a generic is not one symbol) and its illustration is illustrative;
it has been amended in place to say so, which is the resolution the two
sentences can have.

**What would make it a decision rather than a deferral:** an ABI version bump
plus a change to both spellings at once, with the CAS key folding the version —
`cas.ABI_VERSION` is the mechanism and the gimple path already invalidates on it.
Not worth doing for a spelling nothing consumes yet.

---

## 7. What is NOT here, deliberately

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
  does not descend — and the result is correct, because `Pair_Int` is a struct
  in the same module. Worth knowing rather than worth a guard.
* **Lean.** `DylibExport` is stated over arm64 machine code with (name, address)
  rows read from the manifest, and an instantiation adds rows of that shape. No
  instruction, no calling convention, no model change; `formal/dylib`'s proved
  path is exercised unchanged.