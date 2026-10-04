# FORMAL_a_construction_arity_still_reports_an_inherited_field_list_as_the_class_s_own_fault

**Area:** FORMAL (`formal/model.py`'s construction arity — `construction_arity_refusal`
and whatever asks it — against `struct_unresolved_bases`, the same pair the FIELD
read already handles). Found 2026-10-05 on `work/formal23-5` while running the
formal suites behind `bugs/FORMAL_pointer_value_model.md`'s work; **not that
claim's subject and not fixed here.** **This is an UNDECLARED red in `formal-run`**
— the registration in `tools/suite.py` carries no `expect=`, the case has been red
since at least this tree, and no doc in `bugs/` named it.

## 1. What was run

```
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py \
      constr_refuse_an_undeclared_base_by_name
  FAIL  constr_refuse_an_undeclared_base_by_name: --backend=arm64 refused, but not
        with the expected words "derives from 'Widget', which this image does not
        declare": nts and there is no other form, so this path can only place a
        word in a slot it can name. Give the fields explicitly (`MyErr()` then
        `obj.<field> = …`), which is the same program with a representation

formal run: PASS=36 FAIL=1
```

and the program, on both architectures, byte-identical apart from the
architecture word:

```
class MyErr(Widget):          # Widget is declared NOWHERE in this image
    """no fields at all"""

def boom():
    raise MyErr("the message")

def main(n):
    try:
        boom()
    except:
        pass
    return 0
```

```
build: constructing MyErr with 1 argument(s) does not match its fields (no fields
at all), and MyErr declares no `__init__` for it to call instead: with no
user-defined constructor, a struct's fields are filled in DECLARATION ORDER from
positional arguments and there is no other form, so this path can only place a word
in a slot it can name. Give the fields explicitly (`MyErr()` then `obj.<field> =
…`), which is the same program with a representation
```

**Also measured on `master` itself**, from a `git archive master` export with no
diff applied, because the case was red on this branch's base and a reader needs to
know it was not this branch's doing: identical failure, same words.

## 2. What was expected, and which half of the fix is already in

`test_formal_run.py`'s case comment states the rule and the reason the needle is
the base's NAME:

> (3) A base this image does not declare. The refusal used to say "no fields at
> all" and told the reader to declare the fields, which is advice about a class
> whose missing fields are not the problem: it INHERITS them.

**The sentence the test wants is in the tree, and it is in the FIELD READ** —
`formal/model.py`'s single-candidate field-read refusal asks
`struct_unresolved_bases(st)` and says, verbatim:

    It derives from 'Widget', which this image does not declare, so the fields it
    inherits are not in the layout this path can see — and it is NOT an
    AttributeError in the program, because CPython inherits them. Declare
    'Widget' in this module, or declare <field> on MyErr itself.

**The CONSTRUCTION never asks.** `construction_arity_refusal` is reached first and
reports the class's own field list, which for `class MyErr(Widget)` is empty, so
the reader is told to add fields to a class that inherits all of them — advice
that cannot be acted on and that `formal/model.py`'s own inheritance comment
block (the one above `CPYTHON_EXCEPTION_BASES`) names as the thing that was fixed:

> A construction's arity refused with "no fields at all" for a class that inherits
> them […] **What is NOT right is reporting the consequence as if the class had no
> base at all, which is what `construction_arity_refusal` and
> `member_read_without_a_field` did.**

So the FIELD half of that sentence is done and the ARITY half is not: the comment
block describes the intended state of both and only one arrived. That is why this
is a one-question bug rather than a design question.

## 3. The one thing to be careful about, and it is why this was not fixed in a
## hurry

**`CPYTHON_EXCEPTION_BASES` must keep its current answer.** Every class CPython's
`builtins` defines as an exception has exactly one instance field — `args`, filled
by `BaseException.__new__` from the caller's arguments — so `raise ValueError("x")`
is a legal one-argument construction of a class whose body is a docstring. That is
`model.builtin_base_fields`'s job — `CPYTHON_EXCEPTION_BASES` above it is the
table it answers from, and the doc that filed the problem was deleted with its fix,
so the citation is the table and the function. **So the repair is not "an
unresolved base means no fields":**
`class MyErr(ValueError)` has an unresolved base by the same test and MUST still
construct. Whatever distinguishes `Widget` from `ValueError` has to be
`builtin_base_fields(base)`'s answer, which is the function the field-read path
already consults before it reaches its own `struct_unresolved_bases` branch.

## 4. The exact next step

In the construction path, before `construction_arity_refusal` is asked, ask the
same question the field read asks and reuse its wording:

1. the class's merged field list is empty **and** `struct_unresolved_bases(st)` is
   non-empty **and** `builtin_base_fields(base)` contributed nothing for every one
   of those bases — that is `Widget`, and the sentence is the field read's,
   including "it is NOT an AttributeError in the program, because CPython
   inherits them";
2. otherwise the arity refusal stands exactly as it is, because `ValueError` and
   `int` reach it through the same door and one of them is legal.

The case to add beside `constr_refuse_an_undeclared_base_by_name` is the negative
half, because a fix that refuses every unresolved base breaks `raise ValueError(…)`
and nothing else in the file would say so: a `class MyErr(ValueError)` with a
docstring body and `raise MyErr("boom")` inside a `try` must still build. Both
belong in `test_formal_run.py`'s `CONSTRUCTION_REFUSALS` beside the case above,
and the `refuse:` form of both asserts the two architectures word them
identically, which is the other half of what this case is worth.

## 5. Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- \
    python3 test_formal_run.py constr_refuse_an_undeclared_base_by_name
# and the program alone, both architectures:
python3 fire.py build --formal --no-prove --backend=arm64  -o .tmp/o .tmp/base.mojo
python3 fire.py build --formal --no-prove --backend=x86_64 -o .tmp/o .tmp/base.mojo
```