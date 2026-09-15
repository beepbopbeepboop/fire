"""Fixture tests for ownership_destruct.py (Phase 3 groundwork: which
local container bindings are provably a function's sole, permanent
owner). Each case lists exactly which names SHOULD be reported as
candidates for the given function — an empty set means "correctly found
nothing," which matters as much as a non-empty hit given this module's
deliberately conservative, low-recall design.
"""

import mojo_compiler as N
from ownership_destruct import analyze_module


def _candidates(src, fname):
    tokens = N.py_tokenize(src)
    stmts = N.Parser(tokens).with_filename("<test>").parse_module()
    result = analyze_module(stmts)
    return result.get(fname, set())


CASES = [
    ("never_escapes_own_methods_only", """
def main():
    d = {}
    d["a"] = 1
    d["b"] = 2
""", "main", {"d"}),

    ("used_via_len_and_print_is_fine", """
def main():
    d = {}
    d["a"] = 1
    print(len(d))
""", "main", {"d"}),

    ("returned_is_not_a_candidate", """
def make() -> Int:
    d = {}
    d["a"] = 1
    return d
""", "make", set()),

    ("transferred_is_not_a_candidate", """
def consume(owned x: Int):
    print(x)

def main():
    d = {}
    consume(d^)
""", "main", set()),

    ("aliased_is_not_a_candidate", """
def main():
    d = {}
    e = d
    print(e)
""", "main", set()),

    ("passed_to_unresolved_call_is_not_a_candidate", """
def main():
    d = {}
    mystery_function(d)
""", "main", set()),

    ("passed_to_read_param_is_fine", """
def peek(read x: Int):
    print(x)

def main():
    d = {}
    peek(d)
    d["a"] = 1
""", "main", {"d"}),

    ("passed_to_mut_param_is_not_a_candidate", """
def modify(mut x: Int):
    pass

def main():
    d = {}
    modify(d)
""", "main", set()),

    ("reassigned_twice_is_not_a_candidate", """
def main():
    d = {}
    d = {}
""", "main", set()),

    ("appended_element_excluded_but_outer_container_still_fine", """
# `d` is correctly excluded (now reachable through `outer`, an unresolved
# `.append()` call). `outer` itself is still a valid candidate: freeing it
# alone is genuinely safe because `mojo_list_free` (runtime/mojo_runtime.c)
# does NOT recursively free contained elements, so this doesn't double-free
# `d` -- `d` just leaks (a miss, not corruption), which is exactly the
# conservative direction this analysis is allowed to err in.
def main():
    outer = []
    d = {}
    outer.append(d)
""", "main", {"outer"}),

    ("captured_by_nested_def_is_not_a_candidate", """
def main():
    d = {}
    def inner():
        print(d)
    inner()
""", "main", set()),

    ("deleted_is_not_a_candidate", """
def main():
    d = {}
    del d
""", "main", set()),

    ("parameters_are_never_candidates", """
def main(d):
    d["a"] = 1
""", "main", set()),

    ("struct_method_candidate", """
struct Box:
    fn build(self):
        d = {}
        d["a"] = 1
""", "Box.build", {"d"}),

    ("list_and_set_constructors_too", """
def main():
    l = []
    s = {1, 2, 3}
    l.append(1)
""", "main", {"l", "s"}),

    ("assigned_only_in_one_if_arm_is_not_definitely_assigned", """
def main(cond: Bool):
    if cond:
        d = {}
        d["a"] = 1
    print("done")
""", "main", set()),

    ("assigned_in_both_if_and_else_still_excluded_by_rule_2", """
# Not a definite-assignment gap -- rule 2 ("assigned exactly once,
# STATICALLY") counts textual AssignStmt nodes, so two separate
# constructor-assignments (one per branch) are excluded regardless of
# branching, even though only one runs per path. A flow-sensitive
# per-path assignment COUNT (as opposed to just definite-assignment,
# which this module already does) would be a real future enhancement,
# not a bug -- this fixture locks in the CURRENT, documented behavior.
def main(cond: Bool):
    if cond:
        d = {}
    else:
        d = {}
    d["a"] = 1
""", "main", set()),

    ("assigned_only_inside_loop_body_is_not_definitely_assigned", """
def main():
    for i in range(10):
        d = {}
        d["a"] = i
""", "main", set()),

    ("assigned_before_loop_is_definitely_assigned", """
def main():
    d = {}
    for i in range(10):
        d["a"] = i
""", "main", {"d"}),

    ("assigned_only_in_try_body_is_not_definitely_assigned", """
def main():
    try:
        d = {}
    except:
        pass
    print(d)
""", "main", set()),
]


def run():
    failures = []
    for name, src, fname, expected in CASES:
        got = _candidates(src, fname)
        if got != expected:
            failures.append(f"{name!r}: expected {expected}, got {got}")
    total = len(CASES)
    passed = total - len(failures)
    for f in failures:
        print("FAIL:", f)
    print(f"{passed}/{total} ownership_destruct fixture cases passed")
    return 0 if not failures else 1


if __name__ == '__main__':
    import sys
    sys.exit(run())
