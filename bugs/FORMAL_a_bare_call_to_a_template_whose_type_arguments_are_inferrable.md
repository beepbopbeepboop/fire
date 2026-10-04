# FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable: the row
# the per-edge export gate hands 98 of the 163 files to

**Area:** `formal/monomorph.py` (`demands`) / `formal/model.py` (the callee
refusal) · **Status: PARTIAL — §2's half is FIXED (2026-10-04): the refusal no
longer tells a correct caller to add brackets, and says which side the fault is
on. The inference is NOT done, and §5 is the measurement of what it would take:
of 115 measured call sites, 32 are a matcher over annotation strings and 83 need
a type inferrer or a trait-bound resolver, so §3's single feature is three of
different sizes and §5 reorders them.** Measured 2026-10-04 by
`project18:export-gate`, and §5 by `formal21-1` · **Layer:** 1/5 of the formal
work

Found while implementing the per-edge export-gate rule
(`formal/imports.py::library_free_edges`, `work/formal18-export-gate`), which
emptied `binary_heap.mojo`'s 163-file row at the gate and exposed what is behind
it. **This is the next row, and it is one feature, not 98 bugs.**

## 1. The measurement

`bugs/FORMAL_sweep_work_map_2026-10-03_b9.md` §4.1's 163 files, each built on
the tree with the per-edge rule (`python3 fire.py build --formal --no-prove`,
`--no-prove` so no lean runs, both architectures' refusal identical):

| verdict | files | terminal cause |
|---|---|---|
| **BUILT** | **3** | — (`std/_gpu/host/__init__.mojo`, `std/compile/__init__.mojo`, `std/os/path/__init__.mojo`) |
| moved off the gate, still refused | 130 | **123 of them a bare call to a name the defining module cannot export**; 7 something else (MLIR, `inlined_assembly`, a comptime explicit-parameter list, `CompilationTarget`) |
| still at the gate | 30 | `std/sys/_io.mojo` (17) and a `constants.mojo` (13) — both, all 30, "declares no function and no type at all — only module-level constants" |

So the row moves **3 files to a pass** and hands the rest to the shape below.
`bugs/FORMAL_sweep_work_map_2026-10-03_b9.md` §4.1 predicted "8-in-10 land on
`tile.mojo`'s bracketed specialization" from a probe that returned `None` for
every module the gate refused. **That probe also removed the refusal a bare call
gets**, so it read one layer further out than the tree does: with the gate fixed
and the bare call still refused, the first thing a build meets is this row.

The 123, by the callee named in the refusal:

| files | the call | the declaration |
|---|---|---|
| **68** | `FormatStruct(writer, "Allocation")` | `std/memory/alloc.mojo:450` calling `std/format/_utils.mojo:287`'s `struct FormatStruct[T: Writer, o: MutOrigin]` |
| **29** | `dealloc(allocation^)` | `std/memory/alloc.mojo:99` (and 110, 111, 123, 231, …) calling its own module's `std/memory/alloc.mojo:904` — `def dealloc[T: AnyType, /](var allocation: Allocation[T, alignment=_], /)` |
| 13 | `is_negative(value)` | `std/bit/mask.mojo:26` — `def is_negative[dtype: DType, //](value: SIMD[dtype, _]) -> type_of(value)` |
| 6 | `PhiloxRandom(seed)` | `std/random/philox.mojo` — a generic struct constructor |
| 3 | `align_up(x)` | `std/math/math.mojo` |
| 4 | one each: `keep`, `isnan`, `strided_load`, `stat` | `.compiler`, `std.utils.numerics`, `std.sys.intrinsics`, `..fstat` |

**`std/memory/alloc.mojo` carries the first two**, and it is in the import
closure of nearly every stdlib file, which is why these two rows are large and
why they do not overlap in the FILE list: the build walk stops at the first
refusal, so a file that would have hit `dealloc` reports whichever of the two it
reaches first.

## 2. Why it is one feature and not 98 refusals

**Every one of those type arguments is INFERABLE from the call's own arguments.**
`FormatStruct(writer, "Allocation")` — `writer: Some[Writer]` gives `T`, and `o`
is the origin parameter's own default. `dealloc(allocation)` — `allocation` is an
`Allocation[T, …]`, so the argument's type IS `T`. `is_negative(value)` —
`value: SIMD[dtype, _]` is the whole signature: `dtype` is a spelling of the
argument's element type.

Mojo's own rule is that a type argument may be omitted when it can be inferred,
and the stdlib relies on it in these three places at least. So this is not "the
caller forgot a bracket"; it is **the monomorphizer reading the argument types
instead of the brackets**, and
`bugs/FORMAL_generic_monomorph_scope.md` §1 already records the shape from the
other side — a demand is read from *call sites with brackets*, and everything
without one is invisible to it. That doc's §"what is not covered" list is where
this belongs; it is filed separately because it is worth 123 measured files here
rather than a class.

The refusal itself was already the right sentence
(`formal/model.py::imported_callee_refusal`) — **and for these 123 that advice
was WRONG**, because the source is correct Mojo and the brackets are optional.
That was the part of this doc worth having: a refusal whose next step is wrong
about correct code sends the reader to edit working stdlib.

**FIXED 2026-10-04.** The sentence now says, for the bare case, that the SOURCE
is right and this path is short — Mojo infers a template call's type arguments,
so `FormatStruct(writer, "Allocation")` is correct code and this path does not
infer them yet — names the demand pipeline that reads them off a bracket, points
at this doc for the inference and its 123 measured files, and offers
`name[<a type>](…)` explicitly as a **workaround for this gap rather than a
correction to your code**. The refusal is still a refusal and still names the
export rule; only the next step changed. `test_formal_monomorph.py`'s `a bare
call to an imported generic is still refused` pins all four properties (says the
source is right, names the inference, calls the bracket a workaround, and does
NOT contain the old imperative) on both architectures, because a property of the
message a program gets belongs on the case that produces it.

**What is still not fixed is the inference itself, and §3 says what it is.** The
short version: the type argument is not IN the call, it is a property of the
argument's DECLARED TYPE (`writer: Some[Writer]` gives `T`; `value: SIMD[dtype,
_]` gives `dtype`), so the monomorphizer needs enough type structure to read a
template parameter out of an annotation, with the trait bounds to choose between
candidates — and for two of the three measured shapes (`dealloc`, whose argument
is `Allocation[T, …]` in the DEFINING module itself, and `is_negative`, whose
bound is a `DType`) what falls out is the CALLER's own parameter, which is a
specialization of the same template rather than a new instantiation. Those are
not the same feature as `FormatStruct` and the doc should not claim 123 files for
one of them.

## 3. The exact next step

1. In `formal/monomorph.py::all_instantiation_calls`, accept a BARE callee whose
   base is a declared template, and derive its type arguments from the call's
   argument types instead of from a bracket: match each of the template's
   declared parameters against the parameter it appears in (`T` against
   `Allocation[T, …]`, `dtype` against `SIMD[dtype, _]`), read the argument
   expression's declared type, and mangle what falls out. A parameter that
   cannot be resolved that way stays a non-demand and keeps today's refusal —
   the fallback has to be "refused", not "guessed", for the reason
   `type_arg_text`'s docstring gives.
2. `check_library_free_calls` (`formal/imports.py`) then stops firing for these,
   because the demand makes the edge non-exempt; no change is needed there, and
   that is the test that the two features compose: **the per-edge rule's own
   exemption is what makes a call to a template reach the point where inference
   can answer it**, which is why the order of the two commits matters.
3. `test_formal_monomorph.py` gains the three measured cases as
   build-and-RUN comparisons against CPython (`FormatStruct`, `dealloc`,
   `is_negative`), and `imported_callee_refusal`'s sentence stops telling a
   correct caller to add brackets — or keeps it only for the parameters that
   genuinely cannot be inferred.

## 4. Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
S=../new-modular/Mojo/stdlib

# one of the 68 — refused while building std/builtin/constrained.mojo's closure
python3 tools/memslot.py --gb 8 --label fmt -- python3 fire.py build --formal \
  --no-prove -o .tmp/fmt.aout $S/std/format/__init__.mojo

# the declaration and the two bare calls, side by side
sed -n '287p' $S/std/format/_utils.mojo     # struct FormatStruct[T: Writer, o: MutOrigin]
sed -n '450p' $S/std/memory/alloc.mojo       #   FormatStruct(writer, "Allocation").params(
sed -n '904p' $S/std/memory/alloc.mojo       # def dealloc[T: AnyType, /](var allocation: Allocation[T, …])

# §5's measurement, over the repository, formal/hostmods and the stdlib
python3 tools/memslot.py --gb 8 --label tlc -- \
  python3 tools/formal_template_call_census.py
```

The 163-file classification this table comes from is one `fire.py build
--formal --no-prove` per file under `tools/memslot.py`, and the list of paths is
`grep -o 'CODEGEN/DEPENDENCY: [^ ]*' bugs/sweeps/sweep-arm-9{,-retry}.txt` on
the lines that mention `binary_heap`. No lean runs; both architectures produce
the same refusal, which is `bugs/FORMAL_sweep_work_map_2026-10-03_b9.md` §2.2's
standing measurement.
## 5. §3's one feature is three, and the biggest of the three is not the one §1's table leads with

**What was run.** `python3 tools/memslot.py --gb 8 --label tlc -- python3
tools/formal_template_call_census.py`, over this repository, `formal/hostmods/`
and all 252 stdlib files — a parse and a walk, no build, no link, no Lean, and
architecture-blind because the question is about source. 391 files, **115 call
sites** of a bare call to a name the defining module declares a **template**
(`formal/monomorph.py::template_names`, which is `reflect.export_exclusions`'s
generic set, so "is a template" is the export rule's own answer).

**§2's claim, measured.** It says "**every one of those type arguments is
INFERABLE from the call's own arguments**", and that is TRUE of Mojo's semantics
and FALSE of what this path can read at a call site:

| what it would take | sites | the callee that carries the row |
|---|---:|---|
| **solvable from the annotations at the call site** — every type parameter is decided by a parameter of the declaration (or by a default), and every matched argument has an annotation to unify with | **32** | `ThinAllocation` 17, `is_32bit` 5, `is_negative` 2, `fcntl` 2 … |
| **the argument's type is written but does not unify** — the parameter is **trait-bounded** and the annotation is spelled independently, so the answer needs bound resolution | **28** | `FormatStruct` 19, `isnan` 2, `_isnan` 2 … |
| **the argument's type is not written down** — the argument is a call, an operator, a subscript or a literal, so the type has to come from a RETURN type | **52** | **`dealloc` 26**, `Named` 14, `umod` 2, `Repr` 2 … |
| **a type argument is not in the arguments at all** — a phantom with no default | **3** | `Pointer` 3 |
| the declaration could not be read | 0 | — |
| of which some parameter is trait-bounded | 66 | |
| of which the declaration writes it as `Self.T` / `Self.o` | 60 | |

**Three findings, and each one reorders §3.**

1. **The `dealloc` row is not a unification at all.** §1 counts it 29 files and
   §2 says "`allocation` is an `Allocation[T, …]`, so the argument's type IS
   `T`". At the call site the argument is `allocation^` — a `UnaryOp` — and its
   type comes from the *enclosing* declaration, which for a
   `var allocation = alloc(Layout[Int].single())` spells nothing at all. So the
   second-largest row in §1 needs **return-type inference through `alloc`**,
   which this path does not have anywhere: nothing in `formal/` computes a
   function's result type from its body. That is the single biggest piece of the
   three and §3 does not mention it.
2. **The `FormatStruct` row is a trait-bound resolution, not a match.** Its
   parameter is `ref[Self.o] writer: Self.T` bounded `T: Writer`, and the
   argument is `writer: Some[Writer]` — an EXISTENTIAL. Unifying the two
   annotation strings does not produce a type argument; something has to choose a
   concrete writer type for it. That is why the doc's §2 says "with the trait
   bounds to choose between candidates" and why §3, which says "match each of
   the template's declared parameters against the parameter it appears in", reads
   as if the bounds did not matter: **they are the whole difficulty of the
   largest row in the corpus** (111 of the 170 files, per
   `bugs/FORMAL_sweep_work_map_2026-10-04_b10.md` §3.1).
3. **A quarter of the corpus's largest row IS a matcher**, so the feature has a
   cheap half and it is worth landing first: 32 sites need nothing but a
   structural comparison of two annotation strings (`SIMD[dtype, _]` against
   `SIMD[dtype, _]`), which is arithmetic and not inference.

**Two places the census itself had to be corrected, recorded because both
produced a wrong number first and both are the kind a reader will hit.**

* **`Self.o` is not in the AST.** `fire_compiler` normalises
  `ref[Self.o] writer: Self.T` to the annotation `Self.T` and the conv `ref`, so
  a census reading the AST finds `o` mentioned by nothing and files the whole
  `FormatStruct` row as a phantom — 111 files in the wrong bucket, from a field
  the parser drops. The mention text has to be read off the declaration SOURCE.
* **A multi-line signature is a signature.** Reading parameters a line at a time
  sees `struct Pointer[` and `def __init__(` as unclosed brackets, reports a
  declaration with no parameters at all, and files `ThinAllocation` and both
  measured intrinsics as phantoms — the stdlib's line length, as a bucket.

**What this does NOT do.** It does not infer anything, and a row is a claim about
the SOURCE, not about the emitted code: even the 32 solvable sites need the call
site REWRITTEN to the instantiation the answer names, and `monomorph.demands` is
only half of that (§3 step 2 is the other half, and it is the half the demand
pipeline already does for a bracket). Landing the matcher bucket without the
rewrite would produce a demand the emitter cannot bind — a worse answer than the
refusal, which is why neither half is landed here.

**The tests**, both in `test_formal_monomorph.py`, because that is where the
refusal this measurement sizes is pinned:
`test_the_census_answers_each_of_the_five_questions` asks the classifier each of
the five buckets on sources small enough to read — one per bucket, including the
`Self.o` mention and a defaulted parameter — and
`test_the_census_reads_the_measured_shapes_out_of_the_corpus` asks it the three
shapes §1 measured (`FormatStruct` → no-unify and bounded, `dealloc` →
not-written-down, `is_negative` → solvable), so a stdlib that moves these
declarations says so here rather than in the next sweep. The second skips
loudly, and counts the skip, when there is no stdlib checkout beside the tree.

```console
$ python3 tools/formal_template_call_census.py --rows 6
files scanned: 391   bare calls to an imported name that is a declared template: 115   call sites classified: 115
       32  solvable from the annotations at the call site
       28  the argument's type is written but does not unify
       52  the argument's type is not written down
        3  a type argument is not in the arguments at all
        0  the declaration could not be read
   of which some parameter is trait-bounded (`B`): 66
   of which the declaration writes it as `Self.T` (`S`): 60

   callee                                defining module        bucket                                                   sites
   dealloc                              std.memory.alloc      the argument's type is not written down         26
   FormatStruct                         std.format._utils     the argument's type is written but does not unif  19
   ThinAllocation                       std.memory.alloc      solvable from the annotations at the call site    17
   Named                                std.format._utils     the argument's type is not written down         14
```

**The next step, in the order this measurement gives.** (a) The matcher bucket —
32 sites, `formal/monomorph.py::all_instantiation_calls` unifying two annotation
strings, plus the call-site rewrite that makes the demand bindable; it is the
only piece of the three that is a patch. (b) Return-type inference, 52 sites and
the `dealloc` row; nothing in `formal/` has it, and §3's step 1 does not name it
because §2 believed the argument's type was written down. (c) Bound resolution
against an existential, 28 sites and the `FormatStruct` row — the biggest number
of files and the one that needs the most machinery. **And one thing §3 step 3
still owes whoever takes this:** the three build-and-RUN comparisons against
CPython are only meaningful for a bucket this census calls solvable, so they
belong with (a) and not before it.
