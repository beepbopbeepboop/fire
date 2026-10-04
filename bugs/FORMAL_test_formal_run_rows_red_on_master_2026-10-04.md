# Two `test_formal_run.py` rows are red on this tree, each for a cause that is not a stale needle

**Area:** `formal/model.py::construction_arity_refusal` (a `bases` parameter
neither message arm uses) and `formal/build.py::_collect_receiver_frame_escapes`
(an `AttributeError` on a `VarDecl`). **Status: OPEN, filed by
`work/formal23-1` while verifying an unrelated change; NOT fixed here, and the
reason is in "Why this worker did not fix it".**

Found 2026-10-04 on `work/formal23-1` at `8b1ab466`, running the one narrow file
that covers a `print`-time change in `formal/model.py` plus both emitters:

```console
$ python3 tools/memslot.py --gb 8 --label run -- python3 test_formal_run.py
...
formal run: PASS=961 FAIL=2
```

**Both are pre-existing, and that is measured rather than argued**: with
`formal/model.py::function_returns_a_value` monkeypatched to `lambda fn: True`
— which disables every refusal the change under test can raise, so the run is
"this tree without that change" — the same two rows fail with the same two
messages (`.tmp/rn2/neutral.py` in the worktree that wrote this doc).

## 1. `constr_refuse_an_undeclared_base_by_name`: a message arm LOST its `bases` clause

```
FAIL  constr_refuse_an_undeclared_base_by_name: --backend=arm64 refused, but
not with the expected words "derives from 'Widget', which this image does not
declare": nts and there is no other form, so this path can only place a word in
a slot it can name. Give the fields explicitly (`MyErr()` then `obj.<field> =
…`), which is the same program with a representation
```

The case is `class MyErr(Widget): """no fields at all"""` with
`raise MyErr("the message")` — a class whose fields are missing because its BASE
is a type this image does not declare, not because the call under-fills them.

`formal/model.py::construction_arity_refusal` still TAKES the clause and still
DOCUMENTS it:

```python
def construction_arity_refusal(name: str, got: int, summary: str,
                               missing=(), bases=()) -> str:
    ...
    `bases` is the bases this unit does not declare, and it is the clause that
    keeps the message honest about WHY the field list is short. A class with a
    base it inherits its fields from and a class that declares none are the
    same refusal with opposite repairs: the first is fixed by making the base
    visible, the second by declaring the fields. The sentence this replaces
    told the reader of `LaunchError(Exception)` — a docstring and no fields —
    to "give the fields explicitly", which is advice about a class whose
    missing fields are not the problem.
```

**…and neither of the two `return` arms below that docstring mentions `bases` at
all.** `grep -rn "which this image does not declare" formal/` finds nothing: the
string the docstring promises and the row pins does not exist in the tree. So
`bases` is accepted, passed in by the caller (`formal/build.py`'s construction
merge), and dropped — which makes the reader of this exact case be told to
"give the fields explicitly" about a class whose missing fields are not the
problem, which is the failure the docstring says the clause exists to prevent.

**Next step.** Put the clause back, in BOTH arms, in the place the docstring
implies: when `bases` is non-empty the sentence has to say the class derives
from `<base>`, which this image does not declare, so the fields that base would
have contributed cannot be named — and the remedy is making the base visible,
not naming the fields. The arm that is currently about `missing` fields with no
default is the wrong message for it. Two shapes, one decision: `bases` non-empty
selects the base clause whether or not `missing` is empty, and the docstring's
"the first is fixed by making the base visible, the second by declaring the
fields" is the test. `test_formal_run.py`'s row is already the assertion and
needs no change; a `bases`-and-`missing` case (a base this image declares AND a
field no default) is the one worth adding, because "both" is the shape whose
message nobody has written yet.

## 2. `one_field_mutator_that_also_returns_a_frame_is_refused`: an `AttributeError` where a refusal belongs

```
FAIL  one_field_mutator_that_also_returns_a_frame_is_refused: --backend=arm64
refused, but not with the expected words 'two hidden-word conventions':
net/chatgpt/claude/work-386/formal/build.py", line 4934, in
_collect_receiver_frame_escapes
    target = node.target
             ^^^^^^^^^^^
AttributeError: 'VarDecl' object has no attribute 'target'
```

`formal/build.py:4931`:

```python
    for node in M.iter_nodes(getattr(fn, "body", None) or []):
        if not isinstance(node, (F.AssignStmt, F.VarDecl)):
            continue
        target = node.target
```

The tuple admits a `VarDecl` and the next line reads `node.target`, which a
`VarDecl` does not have — it carries `name` (a `str`) and `value`. So a
one-field mutator whose body contains ANY `var x = …` statement raises out of
`_prepare_functions`, and the row sees a traceback where it expected the
returned-frame refusal.

**This is a crash and not a wrong answer**, which is why it is filed rather than
tolerated: a `AttributeError` out of the prepare phase is reported to the reader
as an internal error with no subject, and the sweep's own taxonomy has no row
for it (`tools/formal_sweep_causes.py` classifies MESSAGES, and there is no
message).

**Next step.** A `VarDecl` cannot be the store this reader is looking for — a
`var` declaration binds a NAME and a field is written by an assignment — so the
one-line form is to ask the target of the statement that has one:

```python
        target = getattr(node, "target", None)
        if not (isinstance(target, F.MemberExpr) ...
```

which leaves the `VarDecl` in the tuple for its `.value` (the construction site
test two lines down reads `node.value`, which both statement forms carry) and
turns the crash into the refusal the row expects. Worth a second row beside it
for the shape that then decides: a `var x = Widget()` INSIDE such a mutator is
not a receiver store and must not be reported as one, which the
`getattr`-is-`None` skip gives for free. **Then re-run the row**: it is expected
to pass, and if it does not, the second refusal it wants is the real finding and
belongs in this doc rather than in a fix to the first one.

## Why this worker did not fix it

**Both are in areas another worker holds.** §1's construct is the base/field
merge — `bugs/FORMAL_a_subclass_drops_the_bases_fields.md` is claimed by
`formal16-2`, and `construction_arity_refusal` is the message that merge reports
through. §2 is the one-field mutator's receiver hand-off, which is
`bugs/FORMAL_a_one_field_mutator_has_no_method_contract.md` (claimed by
`formal21-2`) and
`bugs/FORMAL_a_one_word_frame_holder_constructor_is_answered_by_the_receiver_rule.md`
(claimed by `formal23-2`). The rule this worktree works under is to report rather
than edit in another claim's area, and both of these are one-line edits whose
WRONG version is a message that lies about a class — so they want the claim
holder's own measurements behind them, not a patch from a worker who has not read
them.

Neither row is in the `expect=`/`disabled=` census: `test_formal_run.py` is
registered and ungated-red is a real red for it, so this doc is the queue entry.