# FORMAL_a_comptime_origin_alias_is_an_mlir_attribute_template: `Span[StaticString, ImmStaticOrigin]`
# is two links behind an MLIR template, and neither link says so

**Area:** FORMAL (the multi-element subscript classifier,
`formal/model.py::multi_index_refusal`'s `MULTI_INDEX_COMPTIME_PARAMS` arm, over
`../new-modular/Mojo/stdlib/std/sys/arg.mojo:51`). **Status: MEASURED, not
fixed.** The refusal is CORRECT; the SENTENCE is what is wrong about it, and the
root cause is two links down in a module this repository cannot edit.

Filed 2026-10-04 on `work/formal25-5` because two bug docs said this construct had
no doc of its own — `bugs/FORMAL_std_os_io_round2_scope_is_one_refusal_shape.md`
§3 ("Link 2 has NO bug doc and no claim … it is filed nowhere of its own, and 4
files of this scope sit behind it, so it is worth a doc rather than a mention")
and `bugs/FORMAL_std_builtin_sys_time_slice_2026-10-04.md` §3 row 12, which
filed it under monomorphisation. **Both of those attributions are wrong, and this
doc is the measurement that says so.**

## What I ran

```console
$ S=../new-modular/Mojo/stdlib/std
$ for a in arm64 x86_64; do python3 fire.py build --formal --no-prove \
      --backend=$a -o .tmp/arg.aout $S/sys/arg.mojo; done
build: Span[StaticString, ImmStaticOrigin] is a compile-time explicit-parameter
list on a generic, not a subscript: the brackets name types and comptime values,
none of which is a runtime word. This path has no type or comptime parameter to
bind, so what the call means depends entirely on which parameters were passed.
Refused rather than read as an index — a binding for `size_of[type, target]`
would have to come from a target description this backend does not have, and a
plausible constant is a fabricated answer.
```

Byte-identical on both architectures. 4 files of the `std/{os,io,pathlib,
hashlib,base64,ffi,python,_gpu}` scope reach it (measured with
`tools/formal_chain_probe.py`, round 1 of that scope's walk), and it is
`std/sys/arg.mojo`'s own terminal — every file importing `std.sys` reports it.

## The root cause, which is NOT monomorphisation

`std/sys/arg.mojo:51` is `var result = Span[StaticString, ImmStaticOrigin]()`, and
the classifier is right that this is an explicit-parameter list: the base `Span`
IS a struct template this image can classify (`imported_struct_defs` finds it
without an import statement, which is a separate oddity and not this doc's).
The unbindable argument is the SECOND one. `ImmStaticOrigin` is not a struct; it
is a comptime ALIAS in `std/origin/__init__.mojo:123`:

```mojo
comptime ImmStaticOrigin = Origin[
    _mlir_origin=__mlir_attr[
        `#lit.origin.field<`,
        `#lit.static.origin : !lit.origin<false>`,
        `, "__constants__"> : !lit.origin<false>`,
    ]
]()
```

**and that module does not build.** Measured, arm64:

```console
$ python3 fire.py build --formal --no-prove -o .tmp/origin.aout \
      ../new-modular/Mojo/stdlib/std/origin/__init__.mojo
build: the module-level comptime binding 'AnyOrigin' is initialized from an MLIR
attribute template: __mlir_attr[`#lit.any.origin : !lit.origin<`, +mut._mlir_value,
`>`] assembles an MLIR attribute from a template of backtick-quoted literal
fragments and compile-time sub-expressions: it is not a subscript, and there is
no MLIR on this path for the template to become.
```

So the chain is two links, and only the second is this construct:

```
std/origin/__init__.mojo     a comptime alias whose VALUE is an MLIR attribute
      │                      template                             ← link 1
      ▼
ImmStaticOrigin              a name with no WORD to bind
      │
      ▼
Span[StaticString, ImmStaticOrigin]()      ← link 2, the refusal as reported
```

Link 1 is `bugs/FORMAL_mlir_dialect_refusal_is_false_of_the_word_valued_ops`'s
area (`formal19-4`), and it is the same wall the chain walk measures at its
eighth link on the same scope (`reflect.mojo: the module-level comptime binding
'_field_types_of' is initialized from an MLIR attribute template`). **Link 2 is
this doc's, and it is not a monomorphisation question**: the instantiation
machinery is not consulted, because the argument has no value to instantiate
WITH.

## What is wrong with the message, precisely

`multi_index_refusal`'s `MULTI_INDEX_COMPTIME_PARAMS` arm says *"This path has no
type or comptime parameter to bind"* — a claim about the BACKEND, offered as the
diagnosis of a bracket whose two arguments are a struct template this image can
see and a comptime name whose initializer is an MLIR template this image cannot
fold. The reader is sent looking for a capability limit in the compiler, and the
thing that would make the bracket bindable is a different module's comptime
binding.

**The cheap fix is a name in the sentence, not a new rule**: `multi_index_kind`
already receives `structs_by_name` and `callee_defs`, and each bracket ELEMENT is
either a bare name (classifiable against those tables), a member expression, or a
call. So the arm can say which element is not a type or a foldable literal —
"`ImmStaticOrigin` is a `comptime` name whose value this build cannot fold, so the
list has nothing to bind for it" — which is the sentence a reader of `arg.mojo`
needs, and it is FALSE for the other bracket in the same corpus that this arm
refuses (`size_of[type, target]`, where both elements are types and the sentence
above is the right one). The two need distinguishing because they are two
different walls; today they are one sentence.

**What it is worth:** 4 files of one scope, and the honest number for the corpus
is not measured here. Take it from a sweep rather than from this doc.

## The near-identical case that BUILDS, because it rules out the easy reading

If "an explicit-parameter list on an imported generic" were the gap, this would
be refused too, and it is not — a library declaring `struct Box[T: AnyType, O:
Int]` with `comptime ORIGIN = 0`, applying `Box[Int, ORIGIN]()` in the library,
and a program importing the function that returns it:

```console
$ cd .tmp/genchk2 && python3 ../../fire.py build --formal --no-prove -o a.out main.mojo
Built: a.out  [arm64/macho]
```

So the capability is there for a comptime argument that FOLDS. What is missing is
the ability to bind one that does not — and "does not fold" is a fact about a
module this repository does not own, which is why this doc's next step is a
message and not a lowering.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ S=../new-modular/Mojo/stdlib/std
$ python3 tools/memslot.py --gb 8 --label arg -- \
      python3 fire.py build --formal --no-prove -o .tmp/arg.aout $S/sys/arg.mojo
$ python3 tools/memslot.py --gb 8 --label arg -- \
      python3 fire.py build --formal --no-prove -o .tmp/origin.aout $S/origin/__init__.mojo
$ python3 tools/memslot.py --gb 8 --label arg -- \
      python3 tools/formal_chain_probe.py 2 arm64 $S/sys $S/_gpu
```