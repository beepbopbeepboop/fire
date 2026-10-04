# `_collect_receiver_frame_escapes` reads `node.target` off a `VarDecl` and raises `AttributeError`

**Area:** `formal/build.py::_collect_receiver_frame_escapes`, reached from
`_prepare_functions` — the one-field mutator's receiver hand-off.
**Status: OPEN, filed by `work/formal23-1` while verifying an unrelated change;
NOT fixed here, and the reason is "Why this worker did not fix it".**

Found 2026-10-04 on `work/formal23-1` at `8b1ab466`, running the one narrow file
that covers a `print`-time change in `formal/model.py` plus both emitters:

```console
$ python3 tools/memslot.py --gb 8 --label run -- python3 test_formal_run.py
formal run: PASS=962 FAIL=1
  FAIL  one_field_mutator_that_also_returns_a_frame_is_refused: --backend=arm64
  refused, but not with the expected words 'two hidden-word conventions':
  .../formal/build.py", line 4934, in _collect_receiver_frame_escapes
      target = node.target
               ^^^^^^^^^^^
  AttributeError: 'VarDecl' object has no attribute 'target'
```

**Pre-existing, and that is measured rather than argued**: with
`formal/model.py::function_returns_a_value` monkeypatched to `lambda fn: True`
— which disables every refusal the change under test can raise, so the run is
"this tree without that change" — the same row fails with the same traceback
(`.tmp/rn2/neutral.py` in the worktree that wrote this doc).

## What is wrong

`formal/build.py:4931`:

```python
    for node in M.iter_nodes(getattr(fn, "body", None) or []):
        if not isinstance(node, (F.AssignStmt, F.VarDecl)):
            continue
        target = node.target
```

The tuple admits a `F.VarDecl` and the next line reads `node.target`, which a
`VarDecl` does not have — it carries `name` (a `str`) and `value`. So a one-field
mutator whose body contains ANY `var x = …` statement raises out of
`_prepare_functions`, and the row that exists to check the returned-frame refusal
for that shape sees a traceback instead.

**This is a crash and not a wrong answer**, which is why it is filed rather than
tolerated: an `AttributeError` out of the prepare phase is reported to the reader
as an internal error with no subject, and the sweep's own taxonomy cannot even
classify it — `tools/formal_sweep_causes.py` ranks MESSAGES, and a crash produces
none (it lands in the `backend-crash` class instead, which the 2026-10-04 sweep
counts as 0 across 710 files, so this one is invisible to the census entirely).

## The exact next step

A `VarDecl` cannot be the store this reader is looking for — a `var` declaration
binds a NAME and a field is written by an assignment — so the one-line form is to
ask the target of the statement that HAS one:

```python
        target = getattr(node, "target", None)
        if not (isinstance(target, F.MemberExpr)
                and target.member == field
                ...
```

which leaves the `VarDecl` in the tuple for its `.value` (the construction-site
test two lines down reads `node.value`, which both statement forms carry) and
turns the crash into the refusal the row expects.

**Then re-run the row** (`python3 test_formal_run.py
one_field_mutator_that_also_returns_a_frame_is_refused`): it is expected to pass,
and if it does not, the second refusal it wants is the real finding and belongs in
this doc rather than in a fix to the first one. Worth a second row beside it for
the shape the fix then decides: a `var x = Widget()` INSIDE such a mutator is not
a receiver store and must not be reported as one — which the `getattr`-is-`None`
skip gives for free.

## Why this worker did not fix it

**It is another claim's area.** This is the one-field mutator's receiver hand-off:
`bugs/FORMAL_a_one_field_mutator_has_no_method_contract.md` is claimed by
`formal21-2` (and `bugs/FORMAL_a_one_word_frame_holder_constructor_is_answered_by_
the_receiver_rule.md` by `formal23-2`), and `bugs/OPEN_WORK.md` says in as many
words that the receiver convention for this construct landed on 2026-10-03 with
the contract still open. The rule this worktree works under is to report rather
than edit in another claim's area, and this one wants that contract's own
measurements behind it: whether a `var x = <construction>` inside a mutator
should be an escape at all is a question about the convention, and a patch from a
worker who has not read that doc could answer it wrongly in the safe-looking
direction.

The sibling red this was found beside — `formal/model.py`'s
`construction_arity_refusal` dropping the `bases` clause its own docstring
promises, which made `constr_refuse_an_undeclared_base_by_name` red — **is
fixed**, in the same commit as this doc's predecessor was folded into it
(`formal/model.py`: the base clause is asked first, because a class whose fields
are short because of a base this image cannot see is a different program from
one the call under-fills, and each one's remedy is advice about the other's
problem). Its doc was closed by `5cf72641`, so no claim held that area.