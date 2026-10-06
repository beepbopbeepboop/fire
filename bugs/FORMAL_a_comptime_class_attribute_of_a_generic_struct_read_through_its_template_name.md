# `TypeDict.length`: a `comptime` class attribute of a generic struct, read through the TEMPLATE's name

**Status: OPEN, and it is NOT the wall the previous document was about.** The
refusal below is a NAME RESOLUTION and the previous subject — a bracket value
parameter read inside the template's own body — is fixed and its document is
deleted with the fix. What is left is spelled here because it was measured on
the same afternoon and a reader who finds either should be told about the other.

Found 2026-10-05 while landing `formal/monomorph.py::without_template_bodies`,
which closed the bug whose doc is gone with the fix: **a bracket value
parameter read inside the template's own body was refused, and all three
spellings of that construct were this project at once** — `len(keys)` in a
function template, `len(Self.<param>)` in a method, and
`comptime <attr> = len(Self.<param>)` at class scope. The first two build and
answer CPython on both architectures and are pinned by
`test_formal_monomorph.py::test_a_struct_templates_body_is_not_the_body_that_runs`
and `::test_the_same_read_works_in_one_file`. This is the third, and it is
refused by a different pass for a different reason.

## What I ran, and what I saw

Two files, on arm64:

```mojo
# sizelib.mojo
struct TypeDict[T: AnyType, values: List[T]]:
    comptime length = len(Self.values)
    var n: Int

    def get(self) -> Int:
        return self.n

# main.mojo
from sizelib import TypeDict

def main():
    var d = TypeDict[Int, [1, 2, 3, 4]]()
    print(TypeDict.length)
    print(d.get())
```

```
build: TypeDict.length reads a `comptime` class attribute of TypeDict, whose
value is `len(Self.values)` — and what it reads is 'values', a PARAMETER of
TypeDict. A parameter's value belongs to an INSTANTIATION: the use site supplies
it as an argument (`TypeDict[…, <value>, …]`), and that argument is a value, not
a literal written in this class body, so there is nothing here to write
somewhere else. …
```

`formal/model.py::comptime_class_attribute_parameter_refusal`'s message, via
`formal/build.py::_apply_constant_sites`. CPython prints `4`.

## Why it is a different subject, and the measurement that says so

**The template's body is no longer in the compilation unit**, which is what the
previous document was about, so that cannot be the reason here — and the
instantiated body this library actually publishes is exactly right:

```
$ python3 -c "import sys; sys.path.insert(0,'.'); from formal import monomorph as MM; \
    made,_ = MM.instantiate_all(open('.tmp/bp4/lib.mojo').read(), {'TypeDict': {('Int','[1, 2, 3, 4]')}}); \
    print(open(made[0][3]).read())"
struct TypeDict_1_T_3_Int_6_values_52__x005B1_x002C_x00202_x002C_x00203_x002C_x00204_x005D:
    comptime length = len([1, 2, 3, 4])
    var n: Int

    def get(self) -> Int:
        return self.n
```

`len([1, 2, 3, 4])` is a foldable literal. So the class attribute is COMPUTABLE
and the declaration that carries it is already built — **what is missing is that
the consumer's `TypeDict.length` names the TEMPLATE, and the consumer's struct
table holds the MANGLED struct.** `formal/imports.py::borrowed_structs` carries
the instantiated declarations for a call site that APPLIES the template
(`TypeDict[Int, [1, 2, 3, 4]]()` is in this program and is rewritten to
`TypeDict_1_T_3_Int_…`), but a class-attribute read is not a call site, so
nothing asks for that instantiation on its account and the read finds the bare
`TypeDict` — whose alias value is still the unsubstituted `len(Self.values)`,
which is the sentence quoted above.

**So this is `FORMAL_generic_monomorph_scope.md` §1 — "a type argument in a
NON-CALL position is not a demand" — in a spelling §1 does not list.** That
document's §1 enumerates a parameter annotation, a field's annotation and a
`return_type`, and its §1a says the item is "a name resolution, and an ABI
decision". This is a fourth spelling of the same question and it belongs in that
list; the doc is claimed, so this file records it rather than editing it.

## The exact next step

1. `formal/imports.py::instantiation_demands` (via `formal/monomorph.py::demands`,
   which walks CALL SITES through `all_instantiation_calls`) must also count a
   **class-attribute or module-attribute read spelled `Template.<name>`** as a
   demand on `Template`. One more shape in the demand walk, and the same
   `demap` then rewrites the read as well as the constructor — which is why it
   is one change and not two: a rewritten constructor with an unrewritten read
   is the "a declaration with no rewrite / a rewrite with no declaration" pair
   `_own_instantiations`' docstring warns about.
2. The rewrite has to reach a `MemberExpr`, not only a `CallExpr`.
   `monomorph.rewrite_instantiation_calls` is written over call sites, so this
   is an extension of its traversal rather than a new pass — and the reason it
   must be the SAME traversal is that the declaration and the rewrite have to
   come out of one table (the property `imported_instantiations` is built
   around), or a rewritten read can name a struct nothing published.
3. Pinned by a case in `test_formal_monomorph.py` beside
   `test_a_struct_templates_body_is_not_the_body_that_runs`, with CPython as the
   oracle and two instantiations of different lengths so a lowering that
   answered the first program's value for both is caught.

## What is NOT the answer

* **Not reading the class attribute off the TEMPLATE and substituting eagerly.**
  That is monomorphising the class body, which is the ABI decision §1a already
  names, and it would have to happen for a body this path never compiles.
* **Not relaxing the refusal.** The literal in the message ("this one is closed
  by binding the parameter values at the instantiation site, not by editing the
  expression") is true of the class body and false of the consumer's read — which
  is exactly why the read needs the rewrite above rather than a reworded
  diagnostic. A reader who edits the expression to a literal gets `comptime
  length = len([1, 2, 3, 4])` in the template, which is right for that one
  instantiation and wrong for every other.