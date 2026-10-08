# Five rows of `test_formal_run.py` are red on `master`, in the `comptime` class-attribute area

**Area:** the `comptime` class-attribute / template-parameter resolution —
`formal/model.py`'s `comptime_class_attribute_parameter_refusal` and the reader
that precedes it, plus `formal/imports.py`'s `origin_of` answer. **Filed by
`work/formal42-1` 2026-10-05**, out of its claim, because a worker that changes
this area needs to know the floor is already red: it is easy to spend a session
believing five rows it broke.

**Status: NOT FIXED, and PRE-EXISTING — measured, not inferred.** Reverse-applied
this branch's `formal/model.py` and `formal/monomorph.py` diff (never
`git checkout`), kept the tests, and re-ran the five: **all five fail identically
with the change reversed.** So they are red on `master` (`80cea3bd`).

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py
formal run: PASS=1138 FAIL=5

$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py \
    comptime_binding_reading_a_struct_parameter_is_its_own_refusal \
    comptime_binding_reading_a_variadic_parameter_is_its_own_refusal \
    comptime_binding_with_a_literal_value_still_builds \
    origin_of_in_a_local_type_annotation_is_still_a_type \
    type_argument_list_on_a_struct_this_unit_declares
formal run: PASS=73 FAIL=5          # and PASS=73 FAIL=5 with the diff reversed
```

## What I saw — three distinct failures, not five

**1. Two rows expect a REFUSAL and the program now BUILDS.** The subject is
`comptime length = len(keys)` where `keys` is a bracket parameter of the
template, read back through `Self`:

```mojo
struct Box[T: AnyType, keys: List[T]]:
    comptime length = len(keys)
    def size(self) -> Int:
        return Self.length
def main(n):
    return 0
```

```console
$ python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/a .tmp/a.mojo
Built: .tmp/a  [arm64/macho]          # the row asserts a refusal
```

`comptime_binding_reading_a_struct_parameter_is_its_own_refusal` and
`comptime_binding_reading_a_variadic_parameter_is_its_own_refusal` (the second
is the stdlib's own `TypeDict` shape, over `*values: T`). **This one is very
likely CORRECT and the rows STALE**, and the reason is
`formal/monomorph.py::without_template_bodies`: a template's own body is not in
any image, so the class body is dropped rather than compiled, and a program whose
only content is a template declaration has nothing left to refuse. A row that
asserts a refusal cannot tell that from a bug. is in any image, so the class body is dropped rather than compiled, and a program whose
only content is a template declaration has nothing left to refuse. A row that
asserts a refusal cannot tell that from a bug. The doc for the fourth spelling of
this subject — a `comptime` class attribute of a generic struct read through the
TEMPLATE's name — is FIXED as of this branch's second commit (deleted with its
fix; the fix is in the rewrite of a `Template.<attr>` READ). These rows are about
the class BODY, which is a different position. **Deciding whether they are stale
or wrong is the first step, and it is a decision about the template-body rule
rather than about the refusal.**

**2. The CONTROL row of that same group now refuses where it must build.** This is
the one that matters most, because it is the row that stops the fix above being a
blanket ban:

```mojo
struct Box[T: AnyType, keys: List[T]]:
    comptime length = 3
    def size(self) -> Int:
        return Self.length
def show() -> Int:
    return Box.length          # a class-attribute READ, through the TEMPLATE name
```

```console
build: show: 'Box' has no home: the module-level symbol table is empty for this
unit, and the reading function declares no local or parameter by that spelling.
```

`comptime_binding_with_a_literal_value_still_builds` requires exit 0 and stdout
`3`. **The value is a LITERAL and there is no call site**, so the instantiation
this read would name does not exist and nothing rewrites it — which is exactly
the ambiguity rule `formal/monomorph.py::unique_reads` states (a base demanded
EXACTLY ONCE). So the refusal is defensible; what is missing is a case that says
so, because the row asserts the opposite. **Either the row is wrong (a read
through a template name with no instantiation has no answer, so it must refuse)
or the reader is wrong (the literal is foldable, so it could be answered without
an instantiation at all) — and those are different fixes.**

**3. Two rows are message drift, not behaviour.** Both build/run the right answer
and fail on the WORDS:

| row | expects | gets |
|---|---|---|
| `origin_of_in_a_local_type_annotation_is_still_a_type` | exit 7 | an `import`-based `origin_of` sentence (the value is right; the text is not) |
| `type_argument_list_on_a_struct_this_unit_declares` | `compile-time explicit-parameter list` | the wide-receiver sentence, which cites `bugs/FORMAL_wide_recv_model_has_no_domain_for_a_struct.md` |

The second is almost certainly the `FORMAL_wide_receiver_by_reference` work
(`formal42-5`) having moved the message, and it wants a re-worded needle rather
than a code change.

## The exact next step

1. **Decide (1) before touching it.** Read the two rows against
   `monomorph.without_template_bodies` and answer: is a dropped template body a
   refusal (and the rows are stale), or a dropped store (and
   `FORMAL_toplevel_statements_dropped` is live again)? One grep of
   `without_template_bodies`'s own tests answers it.
2. **Decide (2) as a question about the READ, not the body.** Either add the
   literal-foldable case beside `a_class_attribute_read_of_two_instantiations_is_refused`
   in `test_formal_monomorph.py` — a `Template.<attr>` read with a LITERAL value
   and no call site — or teach the reader that a foldable class attribute needs
   no instantiation. **Do not relax `unique_reads` to fix this row**: it would
   make an ambiguous read resolve to an arbitrary instantiation, which is the
   false-PASS this project treats as its worst outcome.
3. **Re-word the two needles in (3)** after checking which change moved them;
   `test_formal_run.py`'s `refuse:`/`refuse_without:` modes exist for exactly
   this and `case_refused_without` in `test_formal_toplevel.py` is the
   anti-rewording form.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py
formal run: PASS=1138 FAIL=5
```
