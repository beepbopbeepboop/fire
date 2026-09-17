"""Fixture-driven accept/reject tests for ownership_check.py (Phases 1-2 of
doc/OWNERSHIP_MODEL.md: move tracking + single-call borrow exclusivity).

Each case is a small .mojo-shaped snippet expected to either produce ZERO
diagnostics ("accept") or at least one ("reject"). Mirrors
test_type_system.py's fixture-list structure per the design doc's own
Phase 1 test plan.
"""

import fire_compiler as N
from ownership_check import check_module


def _diags(src):
    tokens = N.py_tokenize(src)
    stmts = N.Parser(tokens).with_filename("<test>").parse_module()
    return check_module(stmts)


ACCEPT = [
    ("plain_use", """
def main():
    x = 1
    print(x)
"""),
    ("transfer_then_no_more_use", """
def consume(owned x: Int):
    print(x)

def main():
    x = 1
    consume(x^)
"""),
    ("reassign_after_move_is_fine", """
def consume(owned x: Int):
    print(x)

def main():
    x = 1
    consume(x^)
    x = 2
    print(x)
"""),
    ("moved_in_both_branches_then_reassigned", """
def consume(owned x: Int):
    print(x)

def main():
    x = 1
    if True:
        consume(x^)
    else:
        consume(x^)
    x = 2
    print(x)
"""),
    ("read_param_never_moved", """
def peek(read x: Int):
    print(x)

def main():
    x = 1
    peek(x)
    peek(x)
    print(x)
"""),
    ("loop_reassigns_each_iteration", """
def consume(owned x: Int):
    print(x)

def main():
    for i in range(10):
        x = i
        consume(x^)
"""),
    ("struct_method_owned_self_transfer", """
struct Box:
    fn consume(owned self):
        pass

def main():
    b = Box()
    b.consume()
"""),
    ("unrelated_names_not_confused", """
def consume(owned x: Int):
    print(x)

def main():
    x = 1
    y = 2
    consume(x^)
    print(y)
"""),
    ("comptime_member_access_after_move", """
def consume(owned x: Int):
    print(x)

def main():
    x = 1
    consume(x^)
    y: Int = x.type
"""),
    ("type_of_after_move", """
def consume(owned x: Int):
    print(x)

def main():
    x = 1
    consume(x^)
    y = type_of(x)
"""),
    ("returning_branch_excluded_from_merge", """
def consume(owned x: Int):
    print(x)

def pick(found: Bool) -> Int:
    x = 1
    if found:
        consume(x^)
        return 0
    return x
"""),
    ("try_except_handler_sees_pre_try_state", """
def consume(owned x: Int):
    print(x)

def main():
    x = 1
    try:
        consume(x^)
        raise "boom"
    except:
        print(x)
"""),
    ("owned_arg_without_caret_is_a_copy_not_a_move", """
# Real Mojo semantics: passing a bare identifier to an `owned` parameter
# WITHOUT `^` is an implicit COPY (for a Copyable type), not a move — `^`
# is the only real move trigger, always. An earlier version of this
# checker got this backwards and rejected exactly this shape, which is
# valid, common code (found via a false-positive sweep against Modular's
# actual std/os/path.mojo, std/runtime/asyncrt.mojo, std/iter/__init__.mojo).
def consume(owned x: Int):
    print(x)

def main():
    x = 1
    consume(x)
    print(x)
"""),
    ("distinct_names_to_two_mut_params_fine", """
def swap(mut a: Int, mut b: Int):
    pass

def main():
    x = 1
    y = 2
    swap(x, y)
"""),
    ("same_name_to_two_read_params_fine", """
def combine(read a: Int, read b: Int) -> Int:
    return a + b

def main():
    x = 1
    combine(x, x)
"""),
    ("unresolvable_callee_not_flagged", """
def main(fn):
    x = 1
    fn(x, x)
"""),
]

REJECT = [
    ("use_after_transfer", """
def consume(owned x: Int):
    print(x)

def main():
    x = 1
    consume(x^)
    print(x)
"""),
    ("double_transfer", """
def consume(owned x: Int):
    print(x)

def main():
    x = 1
    consume(x^)
    consume(x^)
"""),
    ("moved_in_one_branch_only", """
def consume(owned x: Int):
    print(x)

def main():
    x = 1
    if True:
        consume(x^)
    print(x)
"""),
    ("moved_in_if_not_else", """
def consume(owned x: Int):
    print(x)

def main():
    x = 1
    if True:
        consume(x^)
    else:
        pass
    print(x)
"""),
    ("moved_before_loop_used_inside", """
def consume(owned x: Int):
    print(x)

def main():
    x = 1
    consume(x^)
    for i in range(10):
        print(x)
"""),
    ("moved_at_bottom_of_loop_used_at_top_next_iteration", """
def consume(owned x: Int):
    print(x)

def main():
    x = 1
    for i in range(10):
        print(x)
        consume(x^)
"""),
    ("same_name_aliases_two_mut_params", """
def swap(mut a: Int, mut b: Int):
    pass

def main():
    x = 1
    swap(x, x)
"""),
    ("same_name_aliases_mut_and_read_params", """
def transfer(mut dst: Int, read src: Int):
    pass

def main():
    x = 1
    transfer(x, x)
"""),
]


def run():
    failures = []
    for name, src in ACCEPT:
        d = _diags(src)
        if d:
            failures.append(f"ACCEPT case {name!r} unexpectedly flagged: "
                             + "; ".join(str(x) for x in d))
    for name, src in REJECT:
        d = _diags(src)
        if not d:
            failures.append(f"REJECT case {name!r} was NOT flagged (expected a diagnostic)")

    total = len(ACCEPT) + len(REJECT)
    passed = total - len(failures)
    for f in failures:
        print("FAIL:", f)
    print(f"{passed}/{total} ownership_check fixture cases passed")
    return 0 if not failures else 1


if __name__ == '__main__':
    import sys
    sys.exit(run())
