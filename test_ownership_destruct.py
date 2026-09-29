"""Fixture tests for ownership_destruct.py (Phase 3 groundwork: which
local container bindings are provably a function's sole, permanent
owner). Each case lists exactly which names SHOULD be reported as
candidates for the given function — an empty set means "correctly found
nothing," which matters as much as a non-empty hit given this module's
deliberately conservative, low-recall design.
"""

import fire_compiler as N
from ownership_destruct import analyze_module, analyze_function, analyze_scoped_locals


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

    ("passed_to_mut_param_that_never_escapes_is_fine", """
def modify(mut x: Int):
    pass

def main():
    d = {}
    modify(d)
""", "main", {"d"}),

    # A callee's parameter is trusted only because the callee's OWN body proves
    # it does not escape (ownership_destruct._summarize_params) — never because
    # of its `read`/`mut` keyword: this compiler lowers a copy as the same
    # pointer, so a `read` parameter that is copied into a field would stay
    # reachable after the caller frees it. Each case below is a callee that
    # keeps, or might keep, its parameter.
    ("callee_returns_its_parameter", """
def ident(read x: Int) -> Int:
    return x

def main():
    d = {}
    y = ident(d)
""", "main", set()),

    ("callee_copies_its_read_parameter_into_a_field", """
struct Box:
    var items: Int

def stash(read x: Int, b: Box):
    b.items = x

def main():
    d = {}
    b = Box()
    stash(d, b)
""", "main", set()),

    ("callee_aliases_its_parameter", """
def stash(read x: Int):
    y = x
    keep.append(y)

def main():
    d = {}
    stash(d)
""", "main", set()),

    ("callee_stores_parameter_in_another_container", """
def stash(read x: Int):
    registry.append(x)

def main():
    d = {}
    stash(d)
""", "main", set()),

    ("callee_only_reads_and_mutates_its_parameter", """
def fill(x: Int, n: Int):
    for i in range(n):
        x.append(i)
    print(len(x))

def main():
    d = []
    fill(d, 3)
""", "main", {"d"}),

    ("callee_passes_parameter_on_to_a_retaining_callee", """
def inner(x: Int):
    registry.append(x)

def outer(x: Int):
    inner(x)

def main():
    d = {}
    outer(d)
""", "main", set()),

    ("callee_passes_parameter_on_to_a_non_retaining_callee", """
def inner(x: Int):
    print(len(x))

def outer(x: Int):
    inner(x)

def main():
    d = {}
    outer(d)
""", "main", {"d"}),

    ("recursive_callee_is_conservative", """
def rec(x: Int, n: Int):
    if n > 0:
        rec(x, n - 1)

def main():
    d = {}
    rec(d, 3)
""", "main", set()),

    ("generator_callee_keeps_its_parameter_alive", """
def gen(x: Int):
    yield len(x)

def main():
    d = {}
    g = gen(d)
""", "main", set()),

    ("decorated_callee_may_be_wrapped", """
@wrap
def use(x: Int):
    print(len(x))

def main():
    d = {}
    use(d)
""", "main", set()),

    ("callee_name_shadowed_by_a_local_is_not_resolved", """
def use(x: Int):
    print(len(x))

def main():
    use = other
    d = {}
    use(d)
""", "main", set()),

    ("reassigned_twice_is_not_a_candidate", """
def main():
    d = {}
    d = {}
""", "main", set()),

    ("appended_element_excluded_but_outer_container_still_fine", """
# `d` is correctly excluded (now reachable through `outer`, an unresolved
# `.append()` call). `outer` itself is still a valid candidate: freeing it
# alone is genuinely safe because `mojo_list_free` (runtime/fire_runtime.c)
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


def _scoped(src, fname):
    """(whole-function candidates, block-scoped candidates) for `fname`."""
    tokens = N.py_tokenize(src)
    stmts = N.Parser(tokens).with_filename("<test>").parse_module()
    for st in stmts:
        if isinstance(st, N.FunctionDef) and st.name == fname:
            whole = analyze_function(st, {}, {})
            return whole, analyze_scoped_locals(st, {}, {}, whole)
    return set(), set()


# (name, source, function, expected whole-function set, expected scoped set).
# The scoped set is what a LOOP BODY owns; see analyze_scoped_locals.
SCOPED_CASES = [
    ("loop_body_local_read_and_appended", """
def f(n: Int) -> Int:
    var t = 0
    for i in range(n):
        var l: List[Int] = []
        l.append(i)
        t += len(l)
    return t
""", "f", set(), {"l"}),

    ("while_body_local", """
def f(n: Int) -> Int:
    var t = 0
    var i = 0
    while i < n:
        s = {1, 2}
        i += 1
        t += len(s)
    return t
""", "f", set(), {"s"}),

    ("nested_loops_each_own_their_local", """
def f(n: Int) -> Int:
    var t = 0
    for i in range(n):
        var a: List[Int] = []
        for j in range(3):
            var b: Dict[String, Int] = {}
            b["k"] = j
            t += len(a) + b["k"]
    return t
""", "f", set(), {"a", "b"}),

    ("function_level_and_scoped_are_disjoint", """
def f(n: Int) -> Int:
    d = {}
    for i in range(n):
        l = []
        l.append(i)
        d["a"] = len(l)
    return len(d)
""", "f", {"d"}, {"l"}),

    ("read_after_the_loop_is_not_scoped", """
def f(n: Int) -> Int:
    for i in range(n):
        l = [1, 2]
    return len(l)
""", "f", set(), set()),

    ("iterated_local_is_not_an_escape", """
def f(n: Int) -> Int:
    var t = 0
    for i in range(n):
        var l: List[Int] = []
        l.append(i)
        for x in l:
            t += x
        t += len([y for y in l if y > 0])
    return t
""", "f", set(), {"l"}),

    ("iterated_function_level_local_is_a_candidate", """
def f(n: Int) -> Int:
    var t = 0
    var l: List[Int] = []
    l.append(1)
    for x in l:
        t += x
    return t
""", "f", {"l"}, set()),

    ("returned_after_being_iterated_still_escapes", """
def f(n: Int) -> List[Int]:
    var l: List[Int] = []
    for x in l:
        pass
    return l
""", "f", set(), set()),

    ("iterable_returned_call_result_still_scanned", """
def f(n: Int) -> Int:
    var t = 0
    var l: List[Int] = []
    for x in keep(l):
        t += x
    return t
""", "f", set(), set()),

    ("same_name_declared_in_two_sibling_loops_qualifies_in_both", """
def f(n: Int) -> Int:
    var t = 0
    for i in range(n):
        l = []
        t += len(l)
    for j in range(n):
        l = []
        t += len(l)
    return t
""", "f", set(), {"l"}),

    ("same_name_in_nested_loops_is_rejected", """
def f(n: Int) -> Int:
    var t = 0
    for i in range(n):
        l = []
        for j in range(n):
            l = []
            t += len(l)
        t += len(l)
    return t
""", "f", set(), set()),

    ("same_name_rebound_twice_in_one_body_is_rejected", """
def f(n: Int) -> Int:
    var t = 0
    for i in range(n):
        l = []
        l = [1]
        t += len(l)
    return t
""", "f", set(), set()),

    ("same_name_assigned_outside_any_loop_body_is_rejected", """
def f(n: Int) -> Int:
    var t = 0
    l = []
    for i in range(n):
        l = []
        t += len(l)
    return t
""", "f", set(), set()),

    ("one_loop_declares_a_non_constructor_value_is_rejected", """
def f(n: Int) -> Int:
    var t = 0
    for i in range(n):
        l = []
        t += len(l)
    for j in range(n):
        l = make(j)
        t += len(l)
    return t
""", "f", set(), set()),

    ("declaration_not_a_direct_child_of_the_body", """
def f(n: Int) -> Int:
    var t = 0
    for i in range(n):
        if i > 1:
            l = []
            t += len(l)
    return t
""", "f", set(), set()),

    ("loop_with_else_is_skipped", """
def f(n: Int) -> Int:
    var t = 0
    for i in range(n):
        l = []
        t += len(l)
    else:
        t += 1
    return t
""", "f", set(), set()),

    ("stored_into_outer_container_escapes", """
def f(n: Int) -> Int:
    outer = []
    for i in range(n):
        l = [i]
        outer.append(l)
    return len(outer)
""", "f", {"outer"}, set()),

    ("returned_from_inside_the_loop_escapes", """
def f(n: Int) -> Int:
    for i in range(n):
        l = [i]
        if i == 3:
            return l
    return 0
""", "f", set(), set()),

    ("non_constructor_value_is_not_a_candidate", """
def f(n: Int) -> Int:
    var t = 0
    for i in range(n):
        l = make(i)
        t += len(l)
    return t
""", "f", set(), set()),
]


def run():
    failures = []
    for name, src, fname, exp_whole, exp_scoped in SCOPED_CASES:
        whole, scoped = _scoped(src, fname)
        if whole != exp_whole or scoped != exp_scoped:
            failures.append(f"{name!r}: expected whole={exp_whole} scoped={exp_scoped}, "
                            f"got whole={whole} scoped={scoped}")
    for name, src, fname, expected in CASES:
        got = _candidates(src, fname)
        if got != expected:
            failures.append(f"{name!r}: expected {expected}, got {got}")
    total = len(CASES) + len(SCOPED_CASES)
    passed = total - len(failures)
    for f in failures:
        print("FAIL:", f)
    print(f"{passed}/{total} ownership_destruct fixture cases passed")
    return 0 if not failures else 1


if __name__ == '__main__':
    import sys
    sys.exit(run())
