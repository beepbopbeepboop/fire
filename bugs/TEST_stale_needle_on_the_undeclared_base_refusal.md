# A stale needle: `constr_refuse_an_undeclared_base_by_name` expects a refusal that a different one gets to first

**Area:** TEST (a test row asserting a diagnostic the tree no longer produces at
that site). Found 2026-10-04 on `work/formal26-float`, while running
`python3 test_formal_run.py` in full as the regression check for the binary64
work. **NOT FIXED, and not mine** — the construct is exception construction and
the row belongs with `formal/model.py`'s `construction_arity_refusal`, which is
outside the `project26:float` claim. Filed because the full suite's one red is
otherwise unattributable, and a reader who finds it will reasonably suspect the
last change to touch `formal/model.py`.

## What was run

```
$ python3 test_formal_run.py            # in full, both architectures
…
  FAIL  constr_refuse_an_undeclared_base_by_name: --backend=arm64 refused, but
        not with the expected words "derives from 'Widget', which this image does
        not declare": nts and there is no other form, so this path can only place
        a word in a slot it can name. Give the fields explicitly (`MyErr()` then
        `obj.<field> = …`), which is the same program with a representation

formal run: PASS=1003 FAIL=1
```

The program is `test_formal_run.py:11523`:

```mojo
class MyErr(Widget):
    """no fields at all"""

def boom():
    raise MyErr("the message")
…
```

and the refusal it actually gets is `construction_arity_refusal`:

> constructing MyErr with 1 argument(s) does not match its fields (no fields at
> all), and MyErr declares no `__init__` for it to call instead: …

## Why this is not the binary64 change

Measured, not argued. `formal/model.py`, `formal/types.py`,
`formal/arm64_codegen.py` and `formal/x86_64_codegen.py` were restored from the
commit before the float work (the four files are the whole write set of that
change) and the same program was rebuilt:

```
$ python3 fire.py build --formal --no-prove --backend=arm64 -o … base.mojo
build: constructing MyErr with 1 argument(s) does not match its fields (no
fields at all), and MyErr declares no `__init__` for it to call instead: …
```

Byte-for-byte the same refusal. So the row is red on the tree the float work
started from, and `PASS=1003 FAIL=1` is the pre-existing count for this file.

## What it actually is

Two refusals can fire for this program and the row was written against the
second one:

1. `construction_arity_refusal` — the construction puts a word in a slot it can
   name, and `MyErr` has no fields. This one is reached FIRST.
2. `member_read_without_a_field`'s `struct_unresolved_bases` arm — the
   "derives from 'Widget', which this image does not declare" sentence, which
   is about the BASE's fields not being in the layout.

`model.py`'s own comment above `CPYTHON_EXCEPTION_BASES` records that the second
message was reworded from "as if the class had no base at all" to naming the
undeclared base — so the wording the row pins is current, but the row's program
no longer reaches it. `MyErr` has no fields to read either, so there is no
`MyErr(<field>)` for the inheritance arm to be about; the two refusals are about
different slots and this program only has the first one.

## The exact next step

One of these, and the choice is a judgement about intent rather than about the
code:

- **If the row means "a base this image does not declare is named"**, give it a
  program that has a field to read as well as an undeclared base — a subclass
  with one `var` field, read as `e.field` inside the `except` — so the
  inheritance refusal is the one reached. The needle then stays as it is.
- **If the row means "a construction with no field to place is refused"**, move
  its needle to `construction_arity_refusal`'s text (`does not match its
  fields`) and note in the row that it is the same diagnostic
  `construction_arity_refusal` owns, so a second copy of the sentence is not
  introduced.

The first is the smaller change and keeps both refusals covered; the second is
the one to pick if the inheritance arm turns out to be uncovered elsewhere in
the file (it has other rows — `constr_refuse_a_subclass_whose_base_methods_
would_change_layout` is one — so it may already be).

Whatever is chosen, `test_formal_run.py` is currently red on one row and
`tools/suite.py`'s registration for it should be checked against the fix rather
than against this document.