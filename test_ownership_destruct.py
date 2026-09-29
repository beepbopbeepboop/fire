"""Fixture tests for ownership_destruct.py (Phase 3 groundwork: which
local container bindings are provably a function's sole, permanent
owner). Each case lists exactly which names SHOULD be reported as
candidates for the given function — an empty set means "correctly found
nothing," which matters as much as a non-empty hit given this module's
deliberately conservative, low-recall design.
"""

import gimple_codegen  # noqa: F401  (must load before infra_infer: circular imports)
import fire_compiler as N
import mojo.middle.infra_infer as II
from ownership_destruct import (analyze_module, analyze_function, analyze_scoped_locals,
                                analyze_returns_fresh)


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
    print(ident(d))
""", "main", set()),

    ("callee_copies_its_read_parameter_into_a_field", """
struct Box:
    var items: Int

def stash(read x: Int, b: Box):
    b.items = x

def main(b: Box):
    d = {}
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
    for v in gen(d):
        pass
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

    ("a_call_result_declaration_is_a_maybe_fresh_candidate_per_declaration", """
def f(n: Int) -> Int:
    var t = 0
    for i in range(n):
        l = []
        t += len(l)
    for j in range(n):
        l = make(j)
        t += len(l)
    return t
""", "f", set(), {"l"}),

    ("read_after_the_loop_only_inside_an_fstring_is_still_a_use", """
def f(n: Int) -> Int:
    var t = 0
    for i in range(n):
        l = [1, 2, 3]
        t += len(l)
    print(f"last has {len(l)} items")
    return t
""", "f", set(), set()),

    ("an_fstring_inside_the_loop_body_is_within_the_region", """
def f(n: Int) -> Int:
    var t = 0
    for i in range(n):
        l = [1, 2, 3]
        t += len(l)
        print(f"has {len(l)} items")
    return t
""", "f", set(), {"l"}),

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

    ("call_result_is_a_maybe_fresh_candidate_codegen_decides", """
def f(n: Int) -> Int:
    var t = 0
    for i in range(n):
        l = make(i)
        t += len(l)
    return t
""", "f", set(), {"l"}),

    ("slice_concat_and_comprehension_results_are_maybe_fresh", """
def f(base: List[Int], n: Int) -> Int:
    var t = 0
    for i in range(n):
        a = base[0:2]
        b = a + base
        c = [v for v in b]
        t += len(a) + len(b) + len(c)
    return t
""", "f", set(), {"a", "b", "c"}),   # `a` is the LEFT operand of `+`: a read

    ("string_local_read_by_len_compare_condition_and_left_operand", """
def f(n: Int) -> Int:
    var t = 0
    for i in range(n):
        s = String("n=") + String(i)
        t += len(s)
        if s == "n=5":
            t += 1
        if s:
            t += 2
        u = s + "!"
        t += len(u)
    return t
""", "f", set(), {"s", "u"}),

    ("right_operand_after_a_string_literal_is_a_read", """
def f(n: Int) -> Int:
    var t = 0
    for i in range(n):
        s = String("n=") + String(i)
        u = "id:" + s
        t += len(u)
    return t
""", "f", set(), {"s", "u"}),

    ("right_operand_after_an_identifier_may_run_user_code_so_escapes", """
def f(n: Int, other: Int) -> Int:
    var t = 0
    for i in range(n):
        s = String("n=") + String(i)
        u = other + s
        t += len(u)
    return t
""", "f", set(), {"u"}),

    ("or_returns_an_operand_as_its_value_so_it_escapes", """
def f(n: Int, other: Int) -> Int:
    var t = 0
    for i in range(n):
        s = String("n=") + String(i)
        z = s or other
        t += len(z)
    return t
""", "f", set(), set()),   # `z` is an `or`, not a maybe-fresh expression, and `s` escapes through it

    ("str_of_a_string_is_the_identity_so_it_aliases", """
def f(n: Int) -> Int:
    var t = 0
    for i in range(n):
        s = String("n=") + String(i)
        x = str(s)
        t += len(x)
    return t
""", "f", set(), {"x"}),

    ("ternary_branch_value_escapes_but_its_condition_does_not", """
def f(n: Int, other: Int) -> Int:
    var t = 0
    for i in range(n):
        s = String("n=") + String(i)
        y = s if len(s) > 2 else other
        t += len(y)
    return t
""", "f", set(), set()),   # `y` is a ternary; `s` as a branch value escapes

    ("slicing_a_local_reads_it_and_is_not_an_escape", """
def f(n: Int) -> Int:
    var t = 0
    var l: List[Int] = [1, 2, 3]
    for i in range(n):
        t += len(l[0:2])
    return t
""", "f", {"l"}, set()),

]


def _returns_fresh(src, fname):
    tokens = N.py_tokenize(src)
    stmts = N.Parser(tokens).with_filename("<test>").parse_module()
    for st in stmts:
        if isinstance(st, N.FunctionDef) and st.name == fname:
            return analyze_returns_fresh(st, {}, {})
    return None


# (name, source, function, expected). True means EVERY call returns a brand-new
# container the caller may own and free; each False case is a way that free
# would crash or be a use-after-free.
FRESH_RETURN_CASES = [
    ("builds_a_local_and_returns_it", """
def mk(i: Int) -> List[Int]:
    var l: List[Int] = []
    l.append(i)
    return l
""", "mk", True),

    ("returns_an_empty_display", """
def mk() -> List[Int]:
    return []
""", "mk", True),

    ("returns_a_populated_display", """
def mk(i: Int) -> List[Int]:
    return [i, 1, 2]
""", "mk", True),

    ("two_branches_each_returning_fresh_is_conservative", """
def mk(c: Bool) -> List[Int]:
    if c:
        return []
    else:
        x = [1]
        return x
""", "mk", False),   # `x` is assigned at one exit only; the check needs EVERY exit (conservative)

    ("iterating_the_local_before_returning_it", """
def mk(n: Int) -> List[Int]:
    var l: List[Int] = []
    for i in range(n):
        l.append(i)
    for x in l:
        print(x)
    return l
""", "mk", True),

    ("returns_the_local_with_the_move_operator", """
def mk(i: Int) -> List[Int]:
    var l: List[Int] = []
    l.append(i)
    return l^
""", "mk", True),

    ("moving_a_parameter_out_is_not_fresh", """
def mk(l: List[Int]) -> List[Int]:
    return l^
""", "mk", False),

    ("returns_its_parameter", """
def mk(l: List[Int]) -> List[Int]:
    return l
""", "mk", False),

    ("returns_a_field_it_does_not_own", """
def get(self) -> List[Int]:
    return self.items
""", "get", False),

    ("returns_a_call_result", """
def mk() -> List[Int]:
    return other()
""", "mk", False),

    ("bare_return_hands_back_null", """
def mk(c: Bool) -> List[Int]:
    l = []
    if c:
        return
    return l
""", "mk", False),

    ("a_path_falls_off_the_end", """
def mk(c: Bool) -> List[Int]:
    if c:
        return []
""", "mk", False),

    ("returned_local_assigned_twice", """
def mk(c: Bool) -> List[Int]:
    l = []
    if c:
        l = [1]
    return l
""", "mk", False),

    ("returned_local_also_stored_in_a_field", """
def mk(self) -> List[Int]:
    l = []
    self.cache = l
    return l
""", "mk", False),

    ("returned_local_also_appended_to_a_registry", """
def mk() -> List[Int]:
    l = []
    registry.append(l)
    return l
""", "mk", False),

    ("returned_through_an_alias", """
def mk() -> List[Int]:
    l = []
    y = l
    return y
""", "mk", False),

    ("returned_local_not_assigned_on_every_exit_is_rejected", """
def mk(c: Bool) -> List[Int]:
    if c:
        l = []
        return l
    return []
""", "mk", False),

    ("returned_local_assigned_only_in_a_loop", """
def mk(n: Int) -> List[Int]:
    for i in range(n):
        l = []
    return l
""", "mk", False),

    ("returns_a_tuple_of_locals", """
def mk() -> Int:
    a = []
    b = []
    return a, b
""", "mk", False),

    ("contains_a_nested_def", """
def mk() -> List[Int]:
    l = []
    def inner():
        return l
    return l
""", "mk", False),

    ("is_a_generator", """
def mk():
    l = []
    yield 1
    return l
""", "mk", False),

    ("is_decorated", """
@cache
def mk() -> List[Int]:
    return []
""", "mk", False),
]


def _struct_scoped(src, fname):
    """(whole, scoped) for `fname` with the module's struct and function tables,
    built exactly as codegen builds them."""
    tokens = N.py_tokenize(src)
    stmts = N.Parser(tokens).with_filename("<test>").parse_module()
    funcs = II._build_analysis_funcs(stmts)
    structs = II._build_analysis_structs(stmts)
    for st in stmts:
        if isinstance(st, N.FunctionDef) and st.name == fname:
            whole = analyze_function(st, funcs, {}, structs)
            return whole, analyze_scoped_locals(st, funcs, {}, whole, structs)
    return set(), set()


_PT = """
struct Pt:
    var x: Int
    var y: Int

    def __init__(out self, x: Int, y: Int):
        self.x = x
        self.y = y

    def total(self) -> Int:
        return self.x + self.y

    def leak(self):
        registry.append(self)

    def link(self, other: Pt):
        other.peer = self

    def keep(self, items: List[Int]):
        self.items = items

    def scaled(self, k: Int) -> Int:
        return self.total() * k
"""

# (name, function source appended to the struct, function, whole, scoped)
STRUCT_CASES = [
    ("struct_local_with_field_access_only", """
def f(n: Int) -> Int:
    p = Pt(n, 2)
    return p.x + p.y
""", "f", {"p"}, set()),

    ("struct_local_in_a_loop_body", """
def f(n: Int) -> Int:
    var t = 0
    for i in range(n):
        p = Pt(i, 2)
        t += p.x + p.y
    return t
""", "f", set(), {"p"}),

    ("struct_local_calling_a_method_that_only_reads_self", """
def f(n: Int) -> Int:
    p = Pt(n, 2)
    return p.total() + p.scaled(3)
""", "f", {"p"}, set()),

    ("method_that_registers_self_is_an_escape", """
def f(n: Int) -> Int:
    p = Pt(n, 2)
    p.leak()
    return 0
""", "f", set(), set()),

    ("method_that_stores_self_into_another_object_is_an_escape", """
def f(n: Int, other: Pt) -> Int:
    p = Pt(n, 2)
    p.link(other)
    return 0
""", "f", set(), set()),

    ("bound_method_taken_as_a_value_captures_self", """
def f(n: Int) -> Int:
    p = Pt(n, 2)
    g = p.total
    return g()
""", "f", set(), set()),

    ("unknown_method_name_is_an_escape", """
def f(n: Int) -> Int:
    p = Pt(n, 2)
    return p.not_a_method()
""", "f", set(), set()),

    ("returned_struct_is_an_escape", """
def f(n: Int) -> Pt:
    p = Pt(n, 2)
    return p
""", "f", set(), set()),

    ("struct_passed_to_an_unresolved_function_is_an_escape", """
def f(n: Int) -> Int:
    p = Pt(n, 2)
    return unknown(p)
""", "f", set(), set()),

    ("struct_passed_to_a_function_that_only_reads_it", """
def peek(q: Pt) -> Int:
    return q.x

def f(n: Int) -> Int:
    p = Pt(n, 2)
    return peek(p)
""", "f", {"p"}, set()),

    ("struct_passed_to_a_function_that_stores_it", """
def stash(q: Pt):
    registry.append(q)

def f(n: Int) -> Int:
    p = Pt(n, 2)
    stash(p)
    return 0
""", "f", set(), set()),

    ("method_that_keeps_an_argument_makes_the_argument_escape", """
def f(n: Int) -> Int:
    p = Pt(n, 2)
    l = [1, 2, 3]
    p.keep(l)
    return len(l)
""", "f", {"p"}, set()),

    ("method_used_before_the_binding_in_a_loop_is_still_checked", """
def f(n: Int) -> Int:
    for i in range(n):
        if i > 0:
            p.leak()
        p = Pt(i, 2)
    return 0
""", "f", set(), set()),

    ("struct_operand_runs_user_operators_so_it_escapes", """
def f(n: Int) -> Int:
    var t = 0
    for i in range(n):
        p = Pt(i, 2)
        q = p + 1
        t += q.x
    return t
""", "f", set(), {"q"}),

    ("field_assignment_stores_into_the_struct_and_is_not_an_escape_of_it", """
def f(n: Int) -> Int:
    p = Pt(n, 2)
    p.x = 5
    return p.x
""", "f", {"p"}, set()),

    ("struct_with_a_retaining_init_is_not_owned", """
struct Reg:
    var v: Int

    def __init__(out self, v: Int):
        self.v = v
        registry.append(self)

def f(n: Int) -> Int:
    r = Reg(n)
    return r.v
""", "f", set(), set()),

    ("struct_with_a_base_class_is_not_in_the_table_so_never_vetted_as_a_struct", """
struct Child(Base):
    var z: Int

def f(n: Int) -> Int:
    c = Child(n)
    c.leak()
    return c.z
""", "f", {"c"}, set()),   # analysis credits a plain call result; codegen drops it (not fresh)
]


def run():
    failures = []
    for name, body, fname, exp_whole, exp_scoped in STRUCT_CASES:
        src = body if "struct " in body else _PT + body
        whole, scoped = _struct_scoped(src, fname)
        if whole != exp_whole or scoped != exp_scoped:
            failures.append(f"{name!r}: expected whole={exp_whole} scoped={exp_scoped}, "
                            f"got whole={whole} scoped={scoped}")
    for name, src, fname, expected in FRESH_RETURN_CASES:
        got = _returns_fresh(src, fname)
        if got != expected:
            failures.append(f"{name!r}: expected returns_fresh={expected}, got {got}")
    for name, src, fname, exp_whole, exp_scoped in SCOPED_CASES:
        whole, scoped = _scoped(src, fname)
        if whole != exp_whole or scoped != exp_scoped:
            failures.append(f"{name!r}: expected whole={exp_whole} scoped={exp_scoped}, "
                            f"got whole={whole} scoped={scoped}")
    for name, src, fname, expected in CASES:
        got = _candidates(src, fname)
        if got != expected:
            failures.append(f"{name!r}: expected {expected}, got {got}")
    total = len(CASES) + len(SCOPED_CASES) + len(FRESH_RETURN_CASES) + len(STRUCT_CASES)
    passed = total - len(failures)
    for f in failures:
        print("FAIL:", f)
    print(f"{passed}/{total} ownership_destruct fixture cases passed")
    return 0 if not failures else 1


if __name__ == '__main__':
    import sys
    sys.exit(run())
