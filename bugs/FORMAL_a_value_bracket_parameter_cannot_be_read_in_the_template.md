# FORMAL_a_value_bracket_parameter_cannot_be_read_in_the_template: the library is compiled from the TEMPLATE too, and `len(keys)` / `Self.keys` are refused there

**Status: option 1 of the next steps is LANDED (2026-10-04, `formal28-2`) and
option 2 is not. `len(keys)` where `keys: List[T]` now builds on both
architectures and answers CPython; `len(Self.keys)` and
`comptime length = len(Self.keys)` are still refused, for the reason §"What it
costs" gives — there is no instantiation at that point, so `Self.keys` names a
value nothing has supplied — and the filter question §"The next step" poses for
option 2 (stop compiling a template's own body, or compile only the
instantiations) is still open.**

What option 1 needed, and it is more than the classifier: **the annotation was
being thrown away at the PARSE.** `def total[T: AnyType, keys: List[T]](base:
Int)` puts `keys` in the bracket parameter block, and the block recorded the
NAME and the declared DEFAULT and discarded the TYPE — so no reader anywhere
could ask what a bracket parameter holds, which is why `len(keys)` was refused
with "the source does not say what this operand holds" while `keys[0]` in the
same body lowered. Three places moved together:

  * `fire_compiler.py` keeps the bracket parameters' declared types now
    (`FunctionDef.comptime_param_annotations`, additive);
  * `formal/model.py::param_annotation` reads that table as well as the runtime
    parameter list, and `declared_param_kind` (new) is the ONE reader of the
    question — asked by both backends' `_declared_kind_for` rather than by each
    deciding for itself;
  * `formal/model.py::ValueKinds` seeds a bracket parameter's kind from that
    annotation, which is what `len()`'s operand classifier reads.

The discrimination between a TYPE parameter and a VALUE one is self-selecting and
needs no parser support: a type parameter's annotation is a trait or a width
(`AnyType`, `DType`, `SIMDSize`, `CompilationTarget`), none of which maps to a
value kind, so only an annotation naming a container or a string produces one.

Measured: `total[Int, [1, 2, 3]](10)` prints 13 on arm64 and on x86-64, where
CPython prints 13 for `10 + len([1, 2, 3])`; the row is
`test_formal_cross_module.py`'s `a bracket VALUE parameter is read by its own
declaration`, cross-module because that is where the construct is reachable (a
module dylib is compiled from the module's own source AND from every
instantiated source, so the template's body is compiled before any
substitution). `std/collections/type_dict.mojo` — the measured casualty in §"What
it costs" — is NOT re-measured here: that is a stdlib sweep, and the one thing
this document records about it is that its `comptime length = len(Self.values)`
is option 2 and not option 1, so it does not move.

**Area:** `formal/imports.py::_instantiated_sources` (why the template is
compiled at all) and the two refusals in `formal/model.py` that fire on the
template's own body. Found 2026-10-04 on `work/formal25-1`, immediately after
the consumer-side gate for a value bracket ARGUMENT was fixed on
`work/formal25-1` (commit e12b0005: `type_arg_text` reads a LITERAL DISPLAY) —
that fix makes the argument a demand and binds the boundary symbol, and this is
the wall immediately behind it.

## What I ran

Two files, a library and a program, on both architectures:

```mojo
# lib.mojo — the value parameter is a declared List, and the body reads it
def total[T: AnyType, keys: List[T]](base: Int) -> Int:
    return base + len(keys)

# main.mojo
from lib import total
def main() -> Int:
    print(total[Int, [1, 2, 3]](10))
    return 0
```

```console
$ python3 tools/memslot.py --gb 8 --label g -- \
      python3 fire.py build --formal --no-prove -o .tmp/gm/main.arm64 .tmp/gm/main.mojo
build: main.mojo imports 'lib', which cannot be built either: lib.mojo: len(keys) —
the source does not say what this operand holds, and on this path the two things
len() can answer are told apart by what the operand IS …
```

and the same program with the read written through the receiver instead:

```console
# struct Box[T: AnyType, keys: List[T]]:  …  def total(self) -> Int: return self.first + len(Self.keys)
build: main.mojo imports 'lib', which cannot be built either: lib.mojo: Box_total:
       'Self.keys' is a field access through 'Self', and this path has no way to
       say what 'Self' holds …
```

and with a `comptime` class attribute instead (`comptime length = len(Self.keys)`):

```
lib.mojo: Self.length reads a `comptime` class attribute of Box, whose value is
`len(Self.keys)` — and what it reads is 'keys', a PARAMETER of Box. …
```

## What I saw

**All three refusals are on the TEMPLATE, not on an instantiation.** A module
dylib is compiled from the module's own source *and* from every instantiated
source the consumer asked for
(`formal/imports.py::_instantiated_sources` → `compile_formal_dylib([source_path]
+ [p for _t, _m, _a, p in extra_sources], …)`), so a template that reads a
bracket parameter is asked the question before any substitution has happened.
That is not obviously wrong — the template is a declaration the export gate
excludes, and it is never called — but it means the *instantiated* body is never
reached for a template whose template-shaped body is refused, which is the
opposite of the useful order.

**What does work, and is the reason this is worth writing down rather than
leaving as a shrug:** the same read spelled as a SUBSCRIPT.

```mojo
def total[T: AnyType, keys: List[T]](base: Int) -> Int:
    return base + keys[0]
```

builds, links and prints `11` against CPython's `11`, and `[7, 8, 9]` prints
`17` against `17`, on both architectures. The subscript's base is classified
from the parameter's own annotation (`keys: List[T]`), so `keys[0]` lowers,
while `len(keys)` goes through a reader that does not look at a bracket
parameter's annotation at all.

**So the gap is narrower than "a value parameter cannot be read":** it is that
the two readers that COULD answer — `len()`'s operand classifier and the field
access through `Self` — do not consult a bracket parameter's declared type, and
the one that does (`[0]` on an annotated parameter) is not the shape the corpus
writes.

## What it costs

`std/collections/type_dict.mojo` is the measured casualty: every one of its
parameters is a value, and its `comptime length = len(Self.values)` is the read
the whole API is built on. With the sibling doc's fix landed, that module is now
refused one step later than it was — the bracket is a demand and the boundary
symbol is produced, and the template's own body is what answers — so this is a
row that moves rather than a row that empties.

## The next step

One question, and it is `len()`'s, not the monomorphizer's: **should the
operand classifier read a parameter's DECLARED type?** `len(keys)` where
`keys: List[T]` is the same fact `keys[0]` is already read from, and one reader
of "what does this name hold" is what stops the two from disagreeing — which is
the failure this repository has already paid for twice in this area (a
subscript base classified one way and `len()` another is a wrong answer, not a
refusal, when the first reading is the wrong one).

Two spellings, in order of cost:

1. ~~**`len()` reads a parameter's bracket annotation.**~~ **DONE** (see §Status):
   it reads it for a bare name that the SIGNATURE binds, through one shared
   reader, and it does NOT read it for a *struct field* (`Self.keys`) — there the
   binding rather than the declaration decides the lowering three different ways,
   which is what that refusal says and why it is right. What is still open is
   option 2 below, which is a class-attribute question rather than a container
   one.
2. **`Self.<param>` in a template.** Harder, and it is a class-attribute rule
   rather than a container rule: at that point there is no instantiation, so
   `Self.keys` names a value nothing has supplied. The honest options are to
   stop compiling a template's body (it is excluded from the export set anyway)
   or to compile only the instantiations. The first is one filter in
   `_instantiated_sources`' caller and the second is the same filter; both need
   the export rule's answer for "a template is not an API" to be asked before
   the body is compiled rather than after.

Whichever is taken, the consumer-side gate stays closed either way: its
subject was the bracket ARGUMENT, which is fixed, and this is a different
refusal with a different owner.

## Reproducing

```console
$ python3 tools/memslot.py --gb 8 --label g -- \
      python3 fire.py build --formal --no-prove -o .tmp/gm/main.arm64 .tmp/gm/main.mojo
```

Two files, four library bodies (`len(keys)`, `len(Self.keys)`,
`comptime length = len(Self.keys)`, `keys[0]`), and the last one is the
control. No Lean involved: both refusals are in `formal/build.py`'s
pre-codegen passes and the passing shape is a build.