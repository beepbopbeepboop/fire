# FORMAL_dataclass_own_eq_is_still_refused_though_dispatch_works: `own_eq_refusal`'s stated reason is fixed, and what is left is the transform's own half

**Area:** CODEGEN/FORMAL: `formal/dataclass_transform.py`'s `own_eq_refusal`,
reached from `formal/build.py`'s `check_dataclass_constructs`. Found 2026-10-02
while deleting `FORMAL_eq_does_not_dispatch_to_a_user_dunder.md`, whose premise
this document is the remainder of. **Not fixed here**: the transform is a
shared front-end file and the two halves that have to agree about the
comparison are one in the transform and one in the frame analysis.

## What it was

```python
@dataclass
class T:
    x: int
    y: int
    def __eq__(self, other):
        return True
```

CPython keeps the user's `__eq__` in preference to the generated one, so the
class is legal and its meaning is unambiguous. The transform refused it, and
the reason it gave was measured rather than asserted: `==` on this path was ONE
flag-setting compare of two words and never dispatched by name, so
`T(1) == T(2)` answered 0 where CPython answers True, while an explicit
`T(1).__eq__(T(2))` answered 1 under both.

## That reason is false now

`==` dispatches to a declared `__eq__` when both operands are bare names this
image can say are values of the same struct —
`formal/build.py::_rewrite_eq_on_frame_receivers` (and since 2026-10-02 for a
one-field struct as well, whose value is a word rather than a frame address;
`bugs/FORMAL_eq_dispatch_on_a_frame_receiver.md`). Measured, both
architectures, after that change: a two-field class whose `__eq__` returns True
gives `eq(p, q) == 1`, which is what CPython gives.

So accepting the class is no longer "build an image that runs the comparison as
an address compare", and the refusal's message was corrected to say what still
holds — the refusal itself is unchanged, and
`test_dataclasses_formal.py`'s needle moved from "`==` … never dispatches by
name" to "FIELD-WISE chain", because a refusal whose stated reason has been
fixed is one nobody looks at again.

## What is left, and it is real

`dataclass_transform.rewrite_equality` **desugars** `==` into a field-wise chain
for a `@dataclass` (`x == y` becomes `x_a == y_a and x_b == y_b`). A class that
declares its own `__eq__` must NOT get that chain — that is precisely the case
CPython resolves in the user's favour. So accepting the class means skipping the
desugaring for it and letting the operator's own dispatch answer, which is
where the two halves have to agree about ownership of the comparison:

1. `rewrite_equality` needs to know that this class declares `__eq__`, and skip
   the rewrite for it. The information is right there — `own_eq_refusal` is
   raised because the class declares one — so this is a filter on the same fact
   and not a new analysis.
2. The operator dispatch then has to REACH it. It requires both operands to be
   bare names classified as values of the same struct, so the shapes that still
   do not reach a dunder are the ones `FORMAL_eq_dispatch_on_a_frame_receiver.md`
   §2 and §3 list: a comparison against something that is not a value of the
   same struct (`s == 5`, `s == None`), and a chain with a call in an operand.
   For a dataclass those are real programs — `T(1) == 5` is a comparison any
   user writes — so accepting the class without answering them would trade a
   refusal for a wrong answer, which is the trade this transform exists to
   avoid.
3. So the honest order is: land the dispatch for §2 and §3 first (they are the
   value model's `NotImplemented` and a statement-level unrolling, both named
   as projects in that document), or scope the acceptance to the shapes that do
   dispatch — a class whose fields are all one-word and whose comparisons are
   all between bare names — and say so in the message.

## The `__repr__` half is NOT affected

`repr` on a struct receiver SEGFAULTS today (measured) rather than merely
answering wrongly, so that refusal keeps its reason and its repair unchanged,
and it is a separate clause in the same file.
