# FORMAL_a_comptime_origin_alias_is_an_mlir_attribute_template: `Span[StaticString, ImmStaticOrigin]`
# is two links behind an MLIR template, and neither link says so

**Area:** FORMAL (the multi-element subscript classifier,
`formal/model.py::multi_index_refusal`'s `MULTI_INDEX_COMPTIME_PARAMS` arm, over
`../new-modular/Mojo/stdlib/std/sys/arg.mojo:51`). **Status: the SENTENCE half is
FIXED and so is §3's other half; what is NOT fixed is LINK 1, which is
`bugs/FORMAL_mlir_dialect_refusal_is_false_of_the_word_valued_ops.md`'s area and
not this doc's.** §5 is the sentence clause (landed 2026-10-05, both branches)
and §6 is `StaticString` becoming resolvable (landed 2026-10-05,
`work/formal40-1-r2`), which is what makes the MIXED branch fire for
`arg.mojo` and names the culprit. **Link 1 — `std/origin/__init__.mojo`'s
`comptime` alias whose value is an MLIR attribute template — is still open and
is claimed by another lane** (`FORMAL_mlir_dialect_refusal_is_false_of_the_word_
valued_ops`, live). So this document stays, for link 1 and because §6's fix is a
message improvement rather than a build.

## 6. What landed 2026-10-05: `StaticString` is a TYPE this image knows, so the
## contrast fires and the reader is told which element to go and look at

**§5's closing paragraph said the remaining half "needs `StaticString` to be
resolvable, which is a fact about a module this repository does not own". That
was half right, and the half that was wrong is the whole fix: `StaticString` is
not in another module at all, it is a language BUILTIN, so there is no
declaration to reach and none of the four tables could ever have found one.**

```console
$ grep -rn "StaticString" ../new-modular/Mojo/stdlib/std --include=*.mojo | wc -l
56            # files that spell it, as an ANNOTATION
$ grep -rn "^struct StaticString\|StaticString =" ../new-modular/Mojo/stdlib/std --include=*.mojo
(no match)   # nothing DECLARES it
```

56 files use it and no file declares it, which is what a builtin looks like —
and it is why §5's own measurement (220 reachable struct declarations,
`StaticString` in none of them) read as "not reachable" rather than as "there is
nothing to reach for". `type_constructor_kind`'s documented `None` means "not a
type constructor AT ALL", so the bracket element classified as a bare name this
image cannot resolve — **false about the language**, and a fact about a table
read as a fact about the target. `myinterpreter.py` already knows it
(`myinterpreter.py:2519` lists `StaticString` among the borrowed-string-view
types), so the two halves of this compiler disagreed about whether it is a type.

**The fix is one name in the table whose job is exactly this** —
`UNREPRESENTABLE_TYPE_CTORS`, "real types with NO representation on this path" —
because that is what `StaticString` is here for the ordinary reason: a
compile-time string is not a `char *`, so one 64-bit word does not carry it.
Being in that tuple is also what routes a bare `StaticString(…)` call to the
honest refusal instead of a `BL StaticString` dangling extern, which is the same
improvement the tuple's own comment records for `bytearray`/`bytes`.

**Measured, `std/sys/arg.mojo`, byte-identical refusal on both architectures
before and after** — the verdict does not move, only which element it names:

> Of its 2 element(s): element 1 `StaticString` is a type this image knows; and
> element 2 `ImmStaticOrigin` is a bare name this image cannot resolve to a
> declaration. **That is where the missing word is.**

**So the doc's own §3 proposal is landed, and §3's diagnosis of WHY the reader
was stuck was the thing that had to be wrong for it to be possible**: it said the
sentence "is FALSE for the other bracket in the same corpus that this arm
refuses (`size_of[type, target]`, where both elements are types…)", and named
the missing distinction as a message-level one. It was a table-level one.

### The two tests, and what each is load-bearing for

Three rows in `test_formal_run.py`, and the first two are CHANGED rather than
added — the expectation moved because the classifier moved, and both had
`StaticString` as their stand-in for "a name this image cannot resolve":

* `sub_multi_index_comptime_params_with_nothing_resolvable_says_so` and
  `…_names_the_two_shapes` now spell their two elements `ImmOrigin,
  ImmStaticOrigin` — both `comptime` origin ALIASES, both in no table — so the
  **all-names branch stays reachable and stays pinned**. Re-spelling them was
  forced, not tidier: with `StaticString` a type, that branch is unreachable for
  that spelling, and leaving the rows as they were would have deleted the only
  coverage of a branch that still exists.
* `sub_multi_index_comptime_params_names_the_culprit_when_a_builtin_type_is_
  spelled` is new, on `StaticString, ImmStaticOrigin`, with the needle the
  CULPRIT SPELLING and the clause "That is where the missing word is" — because
  the whole difference from the all-names branch is which element is named.

`test_formal_run.py` is **1126 pass / 0 fail** (1125 before this change, +1 row).
`test_formal_monomorph.py` 27/0 — its census reads the `Self.o` mention off the
declaration SOURCE and is unaffected — and `test_formal_int_semantics.py`
162/162. `test_formal_type_application.py` has one failure
(`a_subscripted_value_called_is_not_a_type_application`) and it is
**pre-existing**: measured with and without this change, `PASS=5 FAIL=1` both
ways.

## 5. What landed 2026-10-05 (the sentence clause), and the measurement §6 corrects

**The two-shapes clause is now in BOTH branches of
`_comptime_param_element_sentence`, and it was in only one.** It used to be
appended by the MIXED branch — "element 1 `Int` is a type this image knows; and
element 2 `ImmStaticOrigin` is a bare name…" — and the all-names branch stopped
at "None of its 2 element(s) names something this image can resolve to a
declaration (StaticString, ImmStaticOrigin), so there is no word to bind for any
of them." Two unresolved names leave the reader with two candidates and no way to
choose, and the clause that says what a bare name can BE was the answer to that.
It is now one module-level string, `_UNRESOLVABLE_NAME_SHAPES`, used by both, so
there is one sentence about it rather than two that can drift. Pinned by
`test_formal_run.py`'s
`sub_multi_index_comptime_params_with_nothing_resolvable_names_the_two_shapes`.

**And the reason that fix could not do what §3 wanted is measured here, and §6
shows the measurement was right about the numbers and wrong about the cause.**
§3's proposal was to distinguish `Span[StaticString, ImmStaticOrigin]` from
`size_of[type, target]` by classifying `StaticString` as the type it is, so the
contrast would fire and the message would name `ImmStaticOrigin` alone. On the
tree of the day, **`StaticString` was in none of the four tables this call
holds.** Run over `std/sys/arg.mojo`:

```
$ python3 -c "… I.imported_struct_defs('…/std/sys/arg.mojo', stmts, root) …"
imported structs reachable from arg.mojo: 220
StaticString in it: False
ImmStaticOrigin in it: False
```

So the `Span[StaticString, ImmStaticOrigin]` case landed in the **all-names**
branch and the sentence that reached a reader of `arg.mojo` was the all-names
one. That is why the clause had to go there rather than in the mixed branch, and
why it is worth having at all.

**§6 corrects the last two sentences of that.** The 220 are right and
`ImmStaticOrigin` in none of them is right; what was wrong was reading "not among
the reachable DECLARATIONS" as "not a type". `StaticString` is a builtin, so
there is no declaration to be among — the fix was one table entry and no
import-reachability work at all.

**What this does NOT do.** It changes no lowering and no refusal: the same
programs are refused on both architectures with the same verdict, and
`test_formal_run.py`'s four other `sub_multi_index_comptime_params_*` rows are
unchanged — including `…_of_literals_says_nothing_extra`, which asserts with
`refuse_without:` that the clause is ABSENT when every element is bindable. That
row is the load-bearing half: a change that appended the clause everywhere would
pass the four positive rows and fail it.

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
different walls; today they are one sentence. **§6 is the distinction landing**:
`arg.mojo` now takes the MIXED branch and is told which element to look at, and
`size_of[type, target]` keeps the plain sentence — which is the whole of what
this paragraph asked for.

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