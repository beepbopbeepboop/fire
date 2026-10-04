# `test_formal_specialized_method_call.py::refuse_a_field_receiver_whose_declared_type_has_a_derived_override` is red: a stale needle, or a refusal that moved

**Area:** `formal/model.py`'s frame-slot refusals (`frame_slot_value_refusal`) and
`value_method_refusal`, against a row in `test_formal_specialized_method_call.py`.
**Status: OPEN, filed by `work/formal23-1`; pre-existing, measured, and NOT fixed
here (the construct is another claim's — see "Why this worker did not fix it").**

Found 2026-10-04 on `work/formal23-1` at `8b1ab466` while running the narrow
formal files around a `print`-time refusal in `formal/model.py`:

```console
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 test_formal_specialized_method_call.py
specialized method call: PASS=16 FAIL=1
  FAIL  refuse_a_field_receiver_whose_declared_type_has_a_derived_override:
  --backend=arm64 refused, but not with the expected words 'self.emit_slice()
  is a method call on a value': expects the field: it would read the address as
  the value, and the program would build, run, and print a number the source
  never wrote. Give FancySlice the same shape as Slice — a subclass that adds no
  field of its own inherits the layout exactly — or keep Slice a plain struct
  and pass it as a field
```

**Pre-existing, measured rather than argued**: with
`formal/model.py::function_returns_a_value` monkeypatched to `lambda fn: True` —
which disables every refusal the change under test can raise, so the run is
"this tree without that change" — the same row fails with the same two messages
(`.tmp/rn2/neutral2.py` in the worktree that wrote this doc).

## What is happening

The case is a SUBCLASS that adds a field, so its receiver is a frame:

```python
struct Slice:
    var start: Int
    def emit_slice(self, mut writer: Int) -> Int:
        return self.start

struct FancySlice(Slice):
    var tag: Int                      # ← the added field: the receiver is a FRAME

struct Box:
    var _inner: Slice
    def go(self, mut writer: Int) -> Int:
        return self._inner.emit_slice(writer)
```

`self._inner` is a FRAME SLOT whose declared type is `Slice` — a one-field struct
— so the read the call needs is the frame's first word, and `model.py`'s
`frame_slot_value_refusal` answers that first, with the "expects the field: it
would read the address as the value" sentence and the remedy the class needs (make
`FancySlice` the same shape as `Slice`, or stop inheriting).

The row's needle is `self.emit_slice() is a method call on a value`, which is
`model.value_method_refusal`'s sentence — a DIFFERENT refusal about the same line,
and one that is now reached only if the frame-slot one does not fire.

## The next step, and it is a decision rather than a patch

Two repairs, and they are not equivalent:

1. **Update the needle** to the sentence the build now produces, on the reasoning
   that `frame_slot_value_refusal` is the more specific fact about the program:
   the receiver is a frame address and the call would read a field out of it,
   where "a method call on a value" describes the symptom further along. This is
   what the row's own comment shape suggests and it costs one string.
2. **Or keep the needle and reorder the two refusals**, so the method-call
   sentence is produced first — which is a change to what a reader of
   `self._inner.emit_slice(writer)` is told first, and it is worse for the OTHER
   programs that reach `frame_slot_value_refusal` without any method call at all.

(1) is almost certainly right and (2) is almost certainly wrong, which is why
this is filed rather than applied: the deciding question belongs to whoever owns
the construct, and `tools/formal_sweep_causes.py` has rows for BOTH sentences —
so a reordering would move a file between two causes in the ranking table, which
is a corpus-visible change and not a test repair.

**Worth doing alongside it, whichever way the needle goes**: the row's program is
a *differential* one in intent (the comment says "a subclass that adds no field of
its own inherits the layout exactly"), and there is no sibling row for the
`FancySlice`-IS-`Slice` shape, which is the case the refusal's remedy is written
for. A green row for the shape the message recommends would be the assertion that
the advice works.

## Why this worker did not fix it

The construct is `bugs/FORMAL_a_subscript_of_a_field_declared_a_framed_struct_is_a_
wrong_answer.md`'s (claimed by `formal23-2`) — a field declared a framed struct
read as a value — and the message that fires is one of `formal/model.py`'s
frame-slot rows, which several other docs' reproductions run through. This
worktree's rule is to report rather than edit in another claim's area.

Neither row is marked `expect=` or `disabled=`: `test_formal_specialized_method_
call.py` is a registered, ungated test, so this is a real red for it and this doc
is the queue entry.