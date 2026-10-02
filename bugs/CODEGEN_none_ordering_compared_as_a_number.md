# CODEGEN: `None` on either side of `<` / `<=` / `>` / `>=` is compared as a NUMBER, and every answer is wrong

**State: OPEN, measured on `master` (2026-10-01), not fixed.** Found while fixing
the `<`/`<=`/`>`/`>=` operators between two CONTAINERS (fixed 2026-10-01 and
covered by `test_container_ordering.py`; its doc is deleted). This is the
SCALAR half of the same operator
family: no operand here is a container, so it is outside that fix's scope and
outside the claim that fix was made under. The compiled path does not raise at
all — it answers.

## What was run, and what it showed

```python
def main() -> Int:
    print(None < 1)
    print(None <= 1)
    print(None > 1)
    print(None >= 1)
    print(None == 1)
    print(None != 1)
    print(None < None)
    return 0
```

CPython 3.14.7 raises on line 2 and never gets to line 3:

```
TypeError: '<' not supported between instances of 'NoneType' and 'int'
```

The compiled program exits 0 and prints seven answers, none of which CPython
would give for that program:

```
True     <- None < 1
True     <- None <= 1
False    <- None > 1
False    <- None >= 1
False    <- None == 1
True     <- None != 1
False    <- None < None
```

Verified pre-existing: the identical seven lines compiled from a pristine
`git archive HEAD` checkout of the tree print the same seven values, so this
predates the container-ordering work. It was not introduced by it.

## Why it is silent

Because the answers are *plausible*. `None` is a NULL `char *` in this model
(`_eq_operand_kind` returns `None`/no evidence for it, and the generic numeric
tail is what claims the operator), so `None < 1` is the C comparison
`0 < 1` — a real comparison of real values, giving a stable, repeatable and
entirely meaningless answer. No diagnostic, exit 0. Same class of failure as the
container pointer comparison this file's sibling had, one level down: a
verdict produced by the wrong question rather than no verdict at all.

`None == 1` being False is CORRECT (CPython agrees), and `None != 1` being
True follows from it — so the equality half is right here by accident of the
NULL comparing unequal to 1, not because `None` is understood. The ordering
half has no such accident to save it.

## Blast radius

Any compiled program that compares `None` against a number with an ordering
operator. The common shape is a guard written as a comparison:

```
    if value < 0:        # value is None when a lookup missed
    if lo <= x <= hi:    # None silently takes a branch
```

Both are silent wrong-branch selections, exit 0. `None` against a `str` has the
same shape (`None < "a"`), and so does `None` against a container — except the
container case is now REFUSED by `test_container_ordering.py`'s
`refuse-str-list` / `refuse-int-list` family, because there the operator
reaches the container lowering and the kind pair is decidable. The
scalar-vs-`None` pair is not, because `None` has no lowering kind of its own.

## Exact next step

`None` needs a lowering KIND, the way `list`/`dict`/`set` have one, so that the
ordering lowering can see "one side is `None`, which has no ordering against
anything" the same way it sees "one side is a dict".

The concrete shape, in `mojo/backend_gimple/emit_exprs.py`:

* `_eq_operand_kind` (the function that answers "which container kind is this
  operand", used by all six comparison operators) currently returns `None` for
  a `NoneLiteral` — but `None` there means "NO EVIDENCE", the same `None` that
  means "erased", which is why the caller cannot tell "this operand is None"
  from "I do not know what this operand is". Give `None` its own sentinel, or
  have `_lower_binary_tail` test `gen._is_none_literal(left_node)` /
  `_is_none_literal(right_node)` before the container block, the way the
  `x == None` NULL-pointer case just below it already does.
* Then emit the same `mojo_raise_type_error` + never-taken-result shape that
  `_lower_container_ord_refusal` uses (that helper is the model to copy, and it
  already produces CPython's exact text), with the type name `NoneType`.

The `_is_none_literal` helper and the exact `TypeError` text shape both already
exist in this file; this is a routing change, not a new mechanism. A test
belongs beside `test_container_ordering.py`'s `REFUSALS` — which already has
the harness for "CPython raises and the compiled program must raise with the
same text" — as a scalar case.

Note for whoever picks it up: `None == None` and `None == 0` must keep
answering as they do today. CPython says `None == None` is True and
`None == 0` is False, and the compiled path gets both right today, so the fix
has to be additive to `==` and must not route it through the refusal.