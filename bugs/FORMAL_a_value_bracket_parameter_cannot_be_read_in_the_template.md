# FORMAL_a_value_bracket_parameter_cannot_be_read_in_the_template: the library is compiled from the TEMPLATE too, and `len(keys)` / `Self.keys` are refused there

**Area:** `formal/imports.py::_instantiated_sources` (why the template is
compiled at all) and the two refusals in `formal/model.py` that fire on the
template's own body. Found 2026-10-04 on `work/formal25-1`, immediately after
`bugs/FORMAL_a_value_typed_bracket_argument_is_refused_as_a_subscript.md` was
fixed — that fix makes a value bracket ARGUMENT a demand and binds the boundary
symbol, and this is the wall immediately behind it.

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

1. **`len()` reads a parameter's bracket annotation.** Contained, and the
   corpus case is one function. It must NOT read it for a *struct field*
   (`Self.keys`), because there the binding rather than the declaration decides
   the lowering three different ways — that is what the `Self.keys` refusal
   says, and it is right.
2. **`Self.<param>` in a template.** Harder, and it is a class-attribute rule
   rather than a container rule: at that point there is no instantiation, so
   `Self.keys` names a value nothing has supplied. The honest options are to
   stop compiling a template's body (it is excluded from the export set anyway)
   or to compile only the instantiations. The first is one filter in
   `_instantiated_sources`' caller and the second is the same filter; both need
   the export rule's answer for "a template is not an API" to be asked before
   the body is compiled rather than after.

Whichever is taken, `bugs/FORMAL_a_value_typed_bracket_argument_is_refused_as_a_subscript.md`
stays deleted either way: its subject is the CONSUMER-side gate, which is
fixed, and this is a different refusal with a different owner.

## Reproducing

```console
$ python3 tools/memslot.py --gb 8 --label g -- \
      python3 fire.py build --formal --no-prove -o .tmp/gm/main.arm64 .tmp/gm/main.mojo
```

Two files, four library bodies (`len(keys)`, `len(Self.keys)`,
`comptime length = len(Self.keys)`, `keys[0]`), and the last one is the
control. No Lean involved: both refusals are in `formal/build.py`'s
pre-codegen passes and the passing shape is a build.