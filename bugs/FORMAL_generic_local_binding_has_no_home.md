# A generic struct constructed with inferred (or annotated) type arguments loses its binding's home

**Area:** FORMAL/build — binding-home classification. **Found 2026-10-06,
`work/formal94-docs`.** PARTIALLY FIXED 2026-10-07 (`work/formal134-docs`): the
measured construct — a type parameter that is PHANTOM — now builds on both
architectures; a type parameter that the body USES still needs argument
inference and is the residual below. PARTIALLY FIXED again 2026-10-08
(`work/formal168-docs`): the ANNOTATED spelling of a used parameter is read as
a demand and rewrites the bare construction (executable and across the dylib);
what remains is the INFERRED spelling of a used parameter, which the inferrable
doc owns. See the two Status sections below.

## Status 2026-10-07: the reproducer and its variants are FIXED; the residual is a USED type parameter

**Root cause, one place.** `formal/monomorph.py::without_template_bodies` dropped
EVERY generic struct template from a compilation unit, on the reasoning that a
template's body is in no image and its instantiation replaces it. That reasoning
is true of a template whose type parameter is USED — the instantiation
substitutes the argument — and false of one whose parameter is PHANTOM: a
parameter that occurs nowhere outside the generic head
(`elaborate.phantom_type_params`). A phantom-parameter declaration is already
concrete, dropping the `[…]` yields the exact declaration that would run for any
argument, and removing it is what left `Marker(b.a)` with no home.

**What landed.** `elaborate.phantom_type_params(template_src, params)` is the
predicate (a parameter with no occurrence in `_code_only`'s body). `formal/
monomorph.py::concrete_struct_templates(src)` names the struct templates all of
whose parameters are phantom, and the EXECUTABLE path (`compile_formal` →
`_without_own_template_bodies(..., concrete_generics=True)`) passes them as
`without_template_bodies`'s `keep`. The declaration then stays in the unit, so
the ordinary constructor/holder path classifies the binding exactly as it does
for a non-generic struct.

Two narrowings keep the change from moving anything else. A phantom template the
source applies with BRACKETS is EXCLUDED (`_bracketed_callee_bases`): an explicit
application is already answered by the instantiation machinery or by the refusal
the bracket earns, and keeping the declaration as well moved it — measured,
`Triple[Int, s, False](5)` lost "a S receiver is stored in a container" and drew
the tuple-index refusal. And the bracket question reads the ORIGINAL source
through the memoised `_consumer_statements`, because by the time the filter runs
`_imported_structs` has rewritten bracketed type applications to their mangled
names, so a statement-list walk no longer sees them (measured: `Box[Int, [1, 2,
3]]()` was rewritten, its phantom template was then wrongly kept, and the build
refused).

**The LIBRARY path deliberately does NOT pass it, and that is the difference
between this row and an ABI change.** A kept declaration joins
`_method_exports`' source set, so it would publish a phantom template's methods
under the template's own name — a change to a dylib's export surface, which
belongs with `bugs/FORMAL_generic_monomorph_scope.md`'s ABI decisions rather
than here. So an inferred-argument construction of a phantom template inside a
LIBRARY is still refused; the executable (this doc's reproducer) is fixed.

Measured after, **both architectures**, each against `fire.py run` (which ran the
program before the change too):

| shape | before | now |
|---|---|---|
| `var m = Marker(b.a)` (`var v: Int`) | refused `nothing this image can see about 'm'` | builds, answers 7 |
| `var m: Marker[Int] = Marker(b.a)` | refused | builds, answers 7 |
| `var m: Marker[origin_of(b)] = Marker(b.a)` | refused | builds, answers 7 |
| `Marker[Int](b.a)` (explicit) | builds | builds (unchanged) |

Pinned by `test_formal_monomorph.py`'s `a phantom struct template is kept` (the
filter and the predicate, with a USED-parameter control), and end to end by
`test_formal_run.py`'s `an_inferred_generic_struct_construction_binds_its_home`
(BOTH architectures) — the doc's own reproducer — and by its
`origin_of_in_a_local_type_annotation_is_still_a_type` row, which was
re-pointed at the refusal while this was open and is an answer row again.

Merged 2026-10-13 (`work/formal252-docs`): a parallel bare-construction
recogniser for this same class was dropped in favour of the keep above (its
keep condition did not carry the bracketed-application exclusion whose
regression the narrowing above measured), and its one unique row landed in
`test_formal_run.py`: `both_arch_an_unused_type_parameter_construction_needs_
no_bracket` (a one-field WORD and a two-field FRAME in one program, 349,
both architectures).

## Status 2026-10-08 (`work/formal168-docs`): the ANNOTATED half of a USED type
## parameter is FIXED; the INFERRED half of it is not

A type argument in a local `VarDecl` annotation (`var m: Marker[Int] =
Marker(b.a)`) is now read as a DEMAND and the bare construction on the right is
rewritten to the mangled instantiation, so the annotated spelling binds `m`
exactly as `Marker[Int](b.a)` does. It works in an executable and across a dylib
boundary, both architectures. What landed:

* `formal/monomorph.py::annotated_construction_demands` — the reader. An
  annotation is a STRING on `VarDecl.type_ann`, so `all_instantiation_calls`
  (which walks CALL sites) cannot see the bracket in it; this reads
  `Base[…]` out of the annotation, requires the right-hand side to be a bare
  `Base(…)`, and refuses to speak for an argument it cannot name exactly (a
  nested application, or a name the scope binds as a value), which keeps the
  refusal of a USED parameter's `Marker[origin_of(b)]` unchanged.
* `formal/monomorph.py::own_annotation_demands` — the own-struct-template table,
  merged into BOTH demand sets: `formal/imports.py::_own_instantiations` (the
  executable path) and `build_module_dylib`'s `mine` (the library path, whose
  own demand set is also the artifact's identity).
* the annotation arm of `rewrite_instantiation_calls`, which rewrites the bare
  construction the annotation demanded.

Pinned by `test_formal_monomorph.py`'s `a type argument in a local annotation is
a demand` (one file, two instantiations, CPython differential, both arches) and
`a library with an annotated construction publishes it` (the dylib boundary,
with the manifest assertion that the instantiation was published), plus
`a bare local construction with no annotation is still refused`, which pins the
boundary.

**The INFERRED half of a USED parameter is unchanged and is not this doc's to
close.** `var m = Marker(b.a)` with a used parameter and no bracket anywhere
states no type argument, so no demand is invented and the refusal stands — the
inference a bare call needs is the feature
`bugs/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`
names, and doing it here would bind an instantiation nobody wrote. (For a
PHANTOM parameter the same spelling is no longer a refusal at all: the
2026-10-07 section above keeps the declaration, and the 10-07 residual is a
used-parameter statement only.) Between the two fixes the title's halves stand
as: "annotated" DONE for both phantom and used parameters; "inferred" DONE for
a phantom parameter, still open for a used parameter.

## The residual, and it is a different feature

A type parameter the body USES — `struct Marker[T: AnyType]: var v: T` — with an
INFERRED construction is still refused:

```
def tag(b: Bag) -> Int:
    var m = Marker(b.a)      # still refused; Marker[Int](b.a) builds
    return m.v
```

That is not the phantom rule's case: the instantiation `Marker_1_T_3_Int` must
substitute `Int` for `T`, and inferring it means typing the constructor's
arguments. The same session's scoping is what keeps this honest rather than
half-done: the fix above removes the drop only where the argument cannot matter,
so it cannot publish a wrong instantiation. The exact next step is the original
one — infer the type arguments from the construction's arguments and add the
demand, then rewrite the call site, the way `demands`/`instantiate_all` already
do for a bracketed call — and it is the same "argument type inference" the
interpreter performs and the compiled path reaches through
`elaborate.infer_struct_type_args`. **Not attempted in the 2026-10-07
session; no test pins it there either.** Updated 2026-10-08
(`work/formal168-docs`): the ANNOTATED spelling of this same shape is no
longer residual — `var m: Marker[Int] = Marker(b.a)` with a used parameter is
the fix in the Status section above, executable and across the dylib. What is
left is exactly the inferred spelling, which is the feature
`bugs/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`
owns, and `test_formal_monomorph.py`'s `a bare local construction with no
annotation is still refused` is the row that has to change when it lands.

## Original report

## What was run

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/probe/t16 .tmp/probe/t16.mojo
```

```mojo
struct Marker[T: AnyType]:
    var v: Int
struct Bag:
    var a: Int
    var b: Int
def tag(b: Bag) -> Int:
    var m = Marker(b.a)      # type arguments INFERRED
    return m.v
def main(n: Int) -> Int:
    var g = Bag(); g.a = 7; g.b = 8
    return tag(g)
```

## What was seen

**Historical — the reproducer below is FIXED (see the Status at the top); kept
because it is the measurement the fix was verified against.** Both architectures
refused:

```
build: tag: 'm.v' is a field access through 'm', and this path has no way to say
what 'm' holds. ... nothing this image can see about 'm's binding establishes
which ...
```

The SAME program with the type arguments spelled on the construction builds and
runs (`var m = Marker[Int](b.a)` — prints 7). An annotated local was no better:
`var m: Marker[Int] = Marker(b.a)` failed identically, and so did
`var m: Marker[origin_of(b)] = Marker(b.a)` — the annotation is not the
subject. (All three now build; see the Status.) A NON-generic one-field struct
in the same positions builds and runs
(`var m = Marker(b.a)` with plain `struct Marker` is fine; so are
`def tag(b: Int) -> Int: var m: Marker = Marker(b)` and `var m: Marker =
Marker(7)` in `main`).

So the defect is exactly: a generic struct's construction whose type arguments
are inferred or supplied via the variable's type ANNOTATION never lands in a
binding the frame/holder analysis can classify, and every field access through
that name is refused. `def tag(ref b: Bag)` vs `def tag(b: Bag)` makes no
difference; it is inference-vs-explicit on the generic.

## Expected

`Marker(b.a)` with the generic's argument inferred from the field's type should
bind `m` the same way `Marker[Int](b.a)` does.

## Next step (updated 2026-10-07 to the residual; 2026-10-13 to the merged tree)

Both fixes that landed since the 10-07 measurement are now in: the phantom case
(keep the declaration — 2026-10-07, work/formal134-docs) and the ANNOTATED
spelling for a phantom or used parameter — the type argument WRITTEN in the
variable's annotation (work/formal168-docs, 2026-10-08: the annotation's demand
is recorded by `formal/monomorph.py::annotated_construction_demands` /
`own_annotation_demands`, and the construction is then monomorphized,
instantiated, and rewritten the way a bracketed call already is). What remains
is exactly the INFERRED spelling of a USED type parameter — `Marker[T]: var v:
T` + `Marker(b.a)`, or the equivalent `var m = Marker(b.a)` with no bracket
anywhere — and the next step is the original one restricted to it: infer the
type arguments from the construction's arguments, add the demand, then rewrite
the call site, the way `formal/monomorph.py::demands`/`instantiate_all`/
`rewrite_instantiation_calls` already do for a bracketed call. The compiled path
already has the inference (`elaborate.infer_struct_type_args`), and the
interpreter performs it; the formal side needs the arguments' types, which is
the part this backend does not currently compute for a call argument. The
demand-recording half of that work is done, so the inference work only has to
produce the bracket. The residual is owned by
`bugs/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`;
it is pinned by `test_formal_monomorph.py`'s `a bare local construction with no
annotation is still refused` (the row that has to change when it lands), and a
regression to the dropped-declaration or unrecorded-demand behaviour fails
`a phantom struct template is kept`, `a type argument in a local annotation is a
demand`, and `a library with an annotated construction publishes it`.
