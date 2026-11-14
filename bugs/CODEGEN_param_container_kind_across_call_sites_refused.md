# CODEGEN: a parameter whose call sites disagree on container kind, used as a container, is refused

**Found:** 2026-11-13, from the `silentnoop` job of `make check`
(`test_silent_noop_iter.py`, tracked by the `SUITE_silentnoop` bug), whose
investigation part escalated a deep defect to its own doc rather than forcing
a shallow fix.

## Symptom

`python3 tools/suite.py silentnoop` is RED: `FAIL silentnoop (644s) exit 1`
(well inside the registered `timeout=1500`, so not a clock problem). Run
direct, `python3 test_silent_noop_iter.py` reports exactly two failures, and
they are one defect:

```
FAIL  parameter_rebound_to_one_container_kind_is_not_multi_kind
FAIL  sorted_two_string_set_pinning
```

Both stop at BUILD time with the same refusal:

```
RuntimeError: parameter 'box' of 'pick' is passed a container at one call
site and a str or number at another, and the body uses it as a container;
the compiled path has no representation for that yet (the per-kind clone
pass only covers literal arguments)
```

## Reproduce

```
python3 test_silent_noop_iter.py parameter_rebound_to_one_container_kind_is_not_multi_kind
```

Fixture (shared by both cases):

```python
def pick(box, other):
    if box is None:
        box = {"a"}
    elif box == "x":
        box = {box}
    else:
        box = {v for v in box}
    return sorted(box)


def plain(items):
    return items[0]


def main():
    print(pick(None, None))
    print(pick("x", None))
    print(pick({"q", "r"}, None))
    print(plain(["first", "second"]))
```

`box` is passed `None`, `"x"` and `{"q", "r"}` at three call sites, and every
branch of the body reassigns it to a SET. CPython prints `['a']`, `['x']`,
`['q', 'r']`, `first`.

## Why it is a bug and not a known-unmodelable shape

The case's own comment is explicit: a parameter REASSIGNED to ONE container
kind in every branch is NOT a multi-kind name, and routing it through
`_multi_kind_locals` is not a safe over-approximation — that set does not
merely annotate, it switches OFF the three "trust ground truth" rules in
`_gen_stmt_AssignStmt`, so the parameter keeps whatever `_infer_param_types`
guessed from its USES and every store is then judged against that guess. Here
usage said `MojoList *` (iterated + truth-tested) while all four branches bind
a set, and `_sce_simple_emit`'s container-kind guard refused the file outright.

So the honest answer is to type `box` `MojoSet *`. The refusal names "passed a
container at one call site and a str or number at another", which is about
the CALL SITES (`None`/`"x"`/`{"q","r"}`) rather than the rebindings — worth
checking which of the two the guard is actually keyed on before fixing.

`sorted_two_string_set_pinning` is a pinning test for
`TEST_silentnoop_sorted_two_string_set_flips` (artifact retention on failure);
it compiles the same `pick`, so it cannot reach its own subject — a two-string
set's `sorted` order matching CPython — until this builds.

## Note on the suite's refusal mechanism

`_case()` in `test_silent_noop_iter.py` already takes
`expect_refusal_substring`, but `main()` calls `_case(name, CASES[name]())` and
never passes one, so NO case can declare an expected refusal today. That
mechanism is not the right disposition for this case anyway (it is a pin for a
fix), but it is currently dead — worth plumbing or removing.

## Next step

Fix the container-kind handling for a parameter whose call sites disagree and
whose body uses it as a container, then confirm both cases' compiled stdout
equals CPython's.

## Done when

`python3 tools/suite.py silentnoop` passes, and
`python3 test_silent_noop_iter.py parameter_rebound_to_one_container_kind_is_not_multi_kind`
plus `... sorted_two_string_set_pinning` both pass with CPython-equal stdout.
