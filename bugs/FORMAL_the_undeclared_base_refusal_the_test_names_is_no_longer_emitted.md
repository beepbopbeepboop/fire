# `test_formal_run.py`'s `constr_refuse_an_undeclared_base_by_name` expects a
# refusal no code emits any more

**Area:** FORMAL — `test_formal_run.py`'s `BOTH_ARCH_CASES` row
`constr_refuse_an_undeclared_base_by_name` (a `refuse:` row, so it asserts
WORDS) against whatever classifies a class whose base this image does not
declare.
Found 2026-10-04 on `work/formal16-4` while landing the floor-division fix, by
running the suite that covers it. **Still open on `master` at the time of
writing** — measured there, not only here: the sentence
`derives from 'Widget', which this image does not declare` appears in
`master:test_formal_run.py` and NOWHERE in any `.py` on `master`
(`git grep -n "which this image does not declare" master -- '*.py'` returns the
test line and nothing else), so the expectation names a message that has no
producer.
**Not fixed here: the area is `formal16-2`'s** (`FORMAL_a_subclass_drops_the_
bases_fields.md`, `FORMAL_an_exception_constructed_with_its_message_has_no_
field_to_hold_it.md`).

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py \
      constr_refuse_an_undeclared_base_by_name
  FAIL  constr_refuse_an_undeclared_base_by_name: --backend=arm64 refused, but not
        with the expected words "derives from 'Widget', which this image does not
        declare": …
$ python3 fire.py build --formal --no-prove -o /tmp/x <the case's source>
build: constructing MyErr with 1 argument(s) does not match its fields (no fields
at all), and MyErr declares no `__init__` for it to call instead: with no
user-defined constructor, a struct's fields are filled in DECLARATION ORDER from
positional arguments and there is no other form, so this path can only place a
word in a slot it can name. …
```

The program is

```mojo
class MyErr(Widget):
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

**Both refusals are true of the program** — the class does derive from a name
this image does not declare, and it also cannot be constructed with one
argument because it declares no fields — so this is not a wrong answer. It is a
decision about WHICH refusal to say, and the two candidates belong to two
different claims.

## The next step

Decide which refusal this program should get, and make the producer and the test
agree. `formal/model.py`'s refusal-precedence table is where "which check speaks
first" lives. Two possibilities, and they are not the same piece of work:

* **the field-count check now comes first**, and it is right to: it is the more
  specific statement about this program. Then the test's expected words move to
  `does not match its fields`, and the subclass refusal needs a reproducer that
  REACHES it — a class with a field, so the constructor is not the thing that
  fails first. That reproducer does not exist today, which is why this case was
  the only thing covering `derives from 'Widget'`, and losing it silently would
  leave the subclass refusal with no test at all.
* **the subclass check is supposed to come first** and no longer does. Then the
  precedence is the defect, not the test, and the fix is in the ordering rather
  than in the wording.

Which of the two it is, is one measurement: build a subclass with a field whose
base is undeclared (`class Sub(Widget): var x: Int`) and see which message comes
out. The first possibility is the likelier one — the field-count refusal reads
like it was written to be the user-facing message — but "likelier" is not a
measurement and this document does not assert it.

## The other red in that run is FIXED on `master`, recorded so it is not re-filed

The same run had `one_field_mutator_that_also_returns_a_frame_is_refused` dying
with `AttributeError: 'VarDecl' object has no attribute 'target'` at
`formal/build.py:4934`, in the `_receiver_frame_escape` arm added by `0dfed3c5`
(`FORMAL_one_word_ctor_of_a_nested_frame_is_unexportable.md`). It reads
`node.target` off a node that may be a `VarDecl`, which carries `name`.
**`master` now reads `node.name` for a `VarDecl` and `node.target.name` for an
`AssignStmt`** (`formal/build.py:3652-3655` and `4729-4735`), so that half is
closed and needs no document.