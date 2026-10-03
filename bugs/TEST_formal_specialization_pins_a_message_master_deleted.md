# TEST_formal_specialization_pins_a_message_master_deleted

**Area:** `test_formal_specialization.py` · **Status:** OPEN, one line of test
· **Found:** 2026-10-03 by `formal15-generic-monomorph`, tripping over it while
running the suite as a regression check for `formal/monomorph.py`. **The
duplicate-definition half of this was already fixed on `master` (`c11a0619`) by
another worker** — see "WHAT IS NOT THIS BUG" below, because the earlier version
of this doc claimed otherwise and was wrong.

## What is wrong

`formal/model.py` used to define `function_value_refusal` TWICE, and Python's
rebinding made the earlier copy dead — so two sentences for one refusal existed
and only the second was ever spoken. The dead copy has since been deleted and
the surviving one's docstring now carries the one measurement only the dead copy
recorded (`workgroup_function[tile_size](offset)`, `std/algorithm/backend/
tile.mojo` — the callee is a PARAMETER and the brackets are a specialization of a
function TYPE). **That part is closed.**

What is still red is the TEST. `test_formal_specialization.py`'s case
`a function read as a value is refused by name` still pins the DELETED copy's
wording:

    test_formal_specialization.py:565   check("read as a VALUE" in text, …)
    test_formal_specialization.py:568   check("no value of a function" in text, …)
    test_formal_specialization.py:571   check("has no home" not in text, …)

and the surviving message — unchanged by that fix, and the one actually spoken —
says neither:

    'plain' is a FUNCTION, and a function is not a value on this path: it has no
    representation here — a value is one 64-bit word and a function is a code
    address, so there is nothing for that word to hold, and passing one as an
    argument, storing one in a container, or returning one is refused rather
    than answered with a number that means nothing.

## What it costs, measured

    $ export PATH=/opt/homebrew/bin:$PATH
    $ python3 test_formal_specialization.py
      FAIL  a function read as a value is refused by name
            [arm64] the refusal is still a placement symptom rather than the construct: …
      formal specialization: PASS=11 FAIL=1

`formal-specialization` is a REGISTERED test in `tools/suite.py`, so every gate
pays for it. It is green on x86-64's own arm only in the sense that both
architectures produce the same message; the check fails on both.

The refusal itself is CORRECT and `test_formal_run.py`'s sibling group agrees
with it — `one_field_mutator_with_a_return_value_is_refused` and the rest are
green. This is one stale needle set, not a behavioural regression.

## The exact next step

Re-point the two needles at the surviving message. The property the case exists
to pin is real and worth keeping: the refusal names the CONSTRUCT ("a function
is not a value on this path") rather than the register allocator's failure to
hold it, and the third needle (`"has no home" not in text`) is what actually
pins that. So the two needles become the surviving wording's own load-bearing
clauses —

    "is not a value on this path"      # the construct, not a placement symptom
    "a value is one 64-bit word"       # what is missing, which is the repair
    "has no home" not in text          # …and the old symptom must not be back

— rather than a re-worded version of the deleted sentence.

**Then, while there, check the rest of the suite for needles of the same kind.**
The dead copy existed for as long as it did because no static check says a
message and its test cannot drift apart, and the three needles here were written
against the copy that lost. `ast.parse` of `formal/model.py` and a grep of every
`check("…", …)` needle in `test_formal_*.py` against the string the module
actually returns is the whole census.

## WHAT IS NOT THIS BUG, and why it is written down

The first version of this document reported that `formal/model.py` defines
`function_value_refusal` twice and that the later definition silently replaces
the earlier one, with the two needles as evidence. **That diagnosis was correct
on the tree it was measured on (`17ddeaec`) and is wrong about `master`
(`c11a0619`)**, where the duplicate is gone and the surviving docstring has been
given the dead copy's unique measurement. A bug doc that says a defect is live
when it has been fixed sends the next reader to look for something that is not
there — the same failure `bugs/FORMAL_known_limits.md` opens this repository
with, and the reason the correction is in the document rather than in the
commit message alone: the claim outlives the tree it was measured on, and only a
document says so.

What remains is the smaller, genuinely open half above: two test needles naming
text that no longer exists.