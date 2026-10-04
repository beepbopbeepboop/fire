# FORMAL_construction_arity_refusal_never_reads_the_bases_it_is_handed, so an inherited-field class is told to declare fields it inherits

**Area:** FORMAL — `formal/model.py::construction_arity_refusal` and the
`refuse:` cases in `test_formal_run.py`. **Status: OPEN, measured on
`work/formal25-2` 2026-10-04 while running that suite over a change of its own,
and NOT fixed there: it is the struct-construction refusal area, not the arm64
machine model or the AST bridge.** The parameter exists, three call sites fill it
in, and the function never looks at it — so one `test_formal_run.py` case is red
on master.

## What I ran

```
$ python3 tools/memslot.py --gb 8 --label tfrun -- python3 test_formal_run.py
formal run: PASS=981 FAIL=1
  FAIL  constr_refuse_an_undeclared_base_by_name: --backend=arm64 refused, but
  not with the expected words "derives from 'Widget', which this image does not
  declare": nts and there is no other form, so this path can only place a word
  in a slot it can name. Give the fields explicitly (`MyErr()` then
  `obj.<field> = …`), which is the same program with a representation
```

and the program behind that case, built by hand on both backends:

```python
class MyErr(Widget):          # a base this image does not declare
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
$ python3 fire.py build --formal --no-prove --backend=arm64   -o .tmp/w/m.arm64 .tmp/w/myerr.mojo
$ python3 fire.py build --formal --no-prove --backend=x86_64 -o .tmp/w/m.x86_64 .tmp/w/myerr.mojo
build: constructing MyErr with 1 argument(s) does not match its fields (no
fields at all), and MyErr declares no `__init__` for it to call instead: with no
user-defined constructor, a struct's fields are filled in DECLARATION ORDER from
positional arguments and there is no other form, so this path can only place a
word in a slot it can name. Give the fields explicitly (`MyErr()` then
`obj.<field> = …`), which is the same program with a representation
```

**Identical on both architectures**, which is worth saying: this is one shared
message, not two that happen to agree today.

## Why

`construction_arity_refusal(name, got, summary, missing=(), bases=())`
(`formal/model.py:26712`) has a `bases` parameter, and its OWN DOCSTRING says
what it is for:

> `bases` is the bases this unit does not declare, and it is the clause that
> keeps the message honest about WHY the field list is short. A class with a base
> it inherits its fields from and a class that declares none are the same
> refusal with opposite repairs: the first is fixed by making the base visible,
> the second by declaring the fields. The sentence this replaces told the reader
> of `LaunchError(Exception)` — a docstring and no fields — to "give the fields
> explicitly", which is advice about a class whose missing fields are not the
> problem.

**Neither return branch reads `bases`.**  Three call sites fill it in —
`formal/model.py:27122`, `:27409` and `:27427`, all with
`bases=struct_unresolved_bases(struct_def)` — so the reader is told to declare
fields the class INHERITS, which is the advice the docstring says was replaced.

## What I expected

The refusal to name the base, because the test's needle is the base's NAME and
says why: "the needle is the base's NAME, because that is what the reader has to
go and look for."

## The exact next step

One clause in `construction_arity_refusal`, in the `if not missing:` branch (a
class that declares no fields of its own is the case `bases` speaks for; the
`missing` branch is about fields the class DOES declare and could have filled):

```python
if not missing:
    if bases:
        return (f"constructing {name} inherits its fields from "
                f"{', '.join(repr(b) for b in bases)}, which this image does "
                f"not declare, so there is no field list to place an argument "
                f"in: …")          # the repair is making the base visible
    return ( … )                    # today's text, for the class that declares none
```

Three things to decide with it, all of them the kind this tree decides rather
than guesses:

1. **the shared predicate** — `struct_unresolved_bases`
   (`formal/model.py:20708`) is what the call sites already use, so the message
   and the computation cannot disagree about which bases count.  Read its
   docstring before writing the clause: it also answers "a builtin container or a
   class from a module this image cannot read", which is the same `bases` tuple
   and a DIFFERENT repair again (`Exception` is not a missing declaration, it is
   a base with no fields to merge), so the clause has to say which of the two it
   is looking at rather than naming every entry the same way;
2. **whether the `missing` branch needs it too** (a subclass of an undeclared
   base that also leaves one of its OWN fields unfilled has two facts, and the
   message should carry both or name the one that is the repair);
3. **the needle** — `test_formal_run.py` wants `"derives from 'Widget', which
   this image does not declare"`, so either the message contains that sentence
   or the needle moves.  `tools/refusal_taxonomy.py` and
   `test_refusal_taxonomy.py` carry samples of this family (257/257 green today
   with today's text), so a reword wants the same sweep the other message
   changes in this tree get.

**Not a value-model bug**: both architectures agree, the refusal itself is
correct (`MyErr("the message")` against a class with no fields and no
`__init__` is a `TypeError`), and the `struct_unresolved_bases` computation is
already there and already used.  What is missing is that anyone READS it.