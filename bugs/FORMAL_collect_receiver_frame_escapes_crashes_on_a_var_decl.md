# `_collect_receiver_frame_escapes` crashes on a `VarDecl`, so `test_formal_run.py` is red and the refusal it should give is never reached

**Area:** FORMAL, `formal/build.py`'s late checks. Found 2026-10-04 on
`work/formal23-2` while verifying an unrelated change; **PRE-EXISTING on this
tree's tip** (measured both with and without that change, see below). **Not
fixed here**: the receiver-frame-escape area belongs to
`bugs/FORMAL_a_one_field_struct_whose_only_field_is_a_nested_frame.md`
(claimed `formal21-2`), and a worker editing it should do this with the rest.

## What I ran, and what I saw

    $ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py
    ...
    FAIL  one_field_mutator_that_also_returns_a_frame_is_refused:
      --backend=arm64 refused, but not with the expected words
      'two hidden-word conventions': formal/build.py", line 4934, in
      _collect_receiver_frame_escapes
        target = node.target
                 ^^^^^^^^^
    AttributeError: 'VarDecl' object has no attribute 'target'

    formal run: PASS=961 FAIL=2

The second failure in the same run, `constr_refuse_an_undeclared_base_by_name`,
is a separate pre-existing red (a different refusal message than the row
expects) and is not this doc's subject.

## The defect

`formal/build.py:4929`:

```python
    for node in M.iter_nodes(getattr(fn, "body", None) or []):
        if not isinstance(node, (F.AssignStmt, F.VarDecl)):
            continue
        target = node.target          # ← `F.VarDecl` has `.name`, not `.target`
```

The `isinstance` admits `F.VarDecl` and the next line reads `F.AssignStmt`'s
attribute. The test case is the smallest program that reaches it:

```python
struct Pair:
    var a: Int
    var b: Int

struct Cell:
    var _p: Pair

    def swap(out self) -> Pair:
        var old = self._p          # ← F.VarDecl, and `self._p` is the sole field
        self._p = Pair()
        return old
```

`var old = self._p` is a `VarDecl`, so the walk raises before it can look at
the store that the row is about. `formal/model.py`'s `struct_receivers` and
`receiver_writeback_name` are already in hand at that point, so the check the
row wants — `self._p = Pair()` is a construction at the frame's escape point —
is one `getattr(node, "target", None)` away.

## Why it matters beyond the red test

A crash inside a late check is a refusal that never happens: the build dies with
an `AttributeError` instead of the sentence the row pins, so a reader is sent to
a traceback rather than to the reason. And because the exception escapes
`_run_late_checks`, whatever that check would have refused is not refused by it
either — here, an escape this check exists to catch.

## The exact next step

1. Branch on `F.VarDecl` first, which is the idiom this file already uses
   **twice** for the same walk — `formal/build.py:4807` and `:5064` both read

       if isinstance(node, F.VarDecl):
           target, value = node.name, node.value
       else:
           target = node.target …

   so the fix is to make the third such site match the first two rather than to
   invent a shape. `node.name` is a string there, so `isinstance(target,
   F.MemberExpr)` is False and the loop skips it — which is correct, because
   `var old = self._p` is a READ and the escape is the `self._p = Pair()` store.
2. Re-run `python3 test_formal_run.py` and confirm
   `one_field_mutator_that_also_returns_a_frame_is_refused` passes with its
   pinned words (`two hidden-word conventions`) and that
   `formal run: FAIL` drops to 1.
3. Worth checking in the same pass, because it is the same shape of mistake:
   every `isinstance(node, (F.AssignStmt, F.VarDecl))` in `formal/build.py`
   followed by a `.target` read. `grep -n "F.VarDecl" formal/build.py` is the
   list, and it has 21 entries; `:4807` and `:5064` already branch, `:4932` is
   the one that does not, and the rest are read individually.

## Measured both ways

The two failures above are **not** caused by the change they were noticed while
verifying (`formal/model.py`'s `frame_slot_element_refusal` and the two
emitters' `_refuse_frame_slot_element`), which is purely additive in the
codegen and runs after the build pass. Verified by re-running both cases with
that refusal monkeypatched to a no-op — same two failures, same messages:

    $ python3 .tmp/pre_existing_check.py      # patches the refusal to a no-op
    FAIL  constr_refuse_an_undeclared_base_by_name: … expected words "derives
          from 'Widget', which this image does not declare": …
    FAIL  one_field_mutator_that_also_returns_a_frame_is_refused: … 'two
          hidden-word conventions': formal/build.py", line 4934, in
          _collect_receiver_frame_escapes / AttributeError: 'VarDecl' object has
          no attribute 'target'