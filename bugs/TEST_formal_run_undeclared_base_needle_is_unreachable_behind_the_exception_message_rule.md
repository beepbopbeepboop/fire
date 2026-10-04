# TEST_formal_run_undeclared_base_needle_is_unreachable_behind_the_exception_message_rule: `constr_refuse_an_undeclared_base_by_name` can no longer reach the refusal it names

**Area:** `test_formal_run.py`'s `CONSTR_*` group (the needle), and the refusal
order in `formal/build.py`'s construction checks. Found 2026-10-04 on
`work/formal25-1`. **Pre-existing on master**; proved from the case text and
from `formal/model.py`'s own message, neither of which this branch touched.

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py
  FAIL  constr_refuse_an_undeclared_base_by_name: --backend=arm64 refused, but not
        with the expected words "derives from 'Widget', which this image does
        not declare": nts and there is no other form, so this path can only
        place a word in a slot it can name. …
formal run: PASS=981 FAIL=1
```

## What I saw

The case (one file, no imports, no brackets):

```python
class MyErr(Widget):
    """no fields at all"""

def boom():
    raise MyErr("the message")
```

expects `refuse:derives from 'Widget', which this image does not declare`, and
gets:

```
build: constructing MyErr with 1 argument(s) does not match its fields (no
fields at all), and MyErr declares no `__init__` for it to call instead: with
no user-defined constructor, a struct's fields are filled in DECLARATION ORDER
from positional arguments and there is no other form, so this path can only
place a word in a slot it can name. …
```

**Both refusals are true; the case has stopped reaching the one it names.**
`MyErr(Widget)` names a base this image does not declare, AND `MyErr("the
message")` constructs a fieldless struct with one argument. The construction
check now fires FIRST, so the base check is unreachable for this exact text.

The second refusal is the newer and the deliberate one: it is
`bugs/FORMAL_an_exception_constructed_with_its_message_has_no_field_to_hold_it`
(claimed by `formal16-2`), and a fieldless exception carrying its message has
nowhere to put the message — which is a fact about `raise E("…")` in general,
not about this one class. So the needle is stale in the sense the sibling
`TEST_formal_receiver_position_expect_marker_outlived_its_three_cases.md` and
`TEST_formal_specialization_pins_a_message_master_deleted.md` describe: a rule
moved in front of the case, and the case's marker now names a refusal nothing
reaches.

## Why it is pre-existing

The case source at `test_formal_run.py:11523` is a single file with no `import`
statement and no bracket, so nothing `work/formal25-1` changed
(`formal/monomorph.py`'s `type_arg_text`, reached only from
`formal/imports.py`'s import-driven demand walk) is on its path at all. Running
the same file by hand reproduces the same message.

## The next step

Decide, then make the case say the same thing twice:

1. **Keep the base refusal and reach it** — give the exception a field to hold
   its message so the construction is well-formed and the undeclared base is
   what is left:

   ```python
   class MyErr(Widget):
       var msg: String
   ```

   That is the honest way to keep testing the base rule, and it makes the case
   about the base rather than about which of two true refusals wins.
2. **Or split it** — a `refuse:` row for the construction and a separate row for
   the base, so a move in the refusal order cannot silently retire one of them.

Either way the row must keep naming a sentence the build still emits: this
group's value is that `refuse:` rows are checked against the actual message, and
a row that has stopped reaching its refusal is exactly what that check cannot
report.