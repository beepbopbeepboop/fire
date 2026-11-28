#!/usr/bin/env python3
"""`mixed_field_names` and `param_value_class` (doc/GIR.md stage 5c, bugs/mid/
GIR_stage5c_none_representation.md "DECISION"): a struct field stored `None`
AND a scalar is the box-holding kind; one stored `None` and only references is
not. An unannotated parameter is classified by its call sites' arguments.

Run:  python3 test_gimple_mixed_field_names.py
"""
import sys
import fire_compiler
from mojo.backend_gimple import emit_infra


def _struct(src):
    p = fire_compiler.Parser(fire_compiler.py_tokenize(src))
    p._filename = "t.mojo"
    for node in p.parse_module():
        if type(node).__name__ in ('StructDef', 'ClassDef'):
            return node
    raise AssertionError("no class in source")


def _mixed(src):
    return sorted(emit_infra.mixed_field_names(_struct(src)))


def _classify(src):
    """Compile `src` and return `(classes, mixed)` over the real call-site
    pass: `{'callee.param': class}` and `{struct: [mixed fields]}`."""
    import build_stdlib_dylib as b
    seen = {}
    orig = emit_infra.collect_param_value_obs

    def spy(gen, *args):
        orig(gen, *args)
        classes = {}
        for key in gen._param_value_obs:
            parts = key.split(emit_infra._PV_SEP)
            classes[parts[0] + '.' + parts[1]] = emit_infra.param_value_class(
                gen, parts[0], parts[1])
        seen['classes'] = classes
        seen['mixed'] = {n: sorted(emit_infra.mixed_field_names(st, gen))
                         for n, st in gen._pv_structs.items()}
    emit_infra.collect_param_value_obs = spy
    try:
        b.compile_module_to_c(src, 't.mojo', 't', linkable=False)
    finally:
        emit_infra.collect_param_value_obs = orig
    return seen.get('classes', {}), seen.get('mixed', {})


def _call_site_cases():
    fails = []

    def check(name, src, want_classes, want_mixed):
        classes, mixed = _classify(src)
        for k in want_classes:
            if classes.get(k, 'unknown') != want_classes[k]:
                fails.append(f"{name}: {k} expected {want_classes[k]}, got {classes.get(k, 'unknown')}")
        for k in want_mixed:
            if mixed.get(k) != want_mixed[k]:
                fails.append(f"{name}: mixed[{k}] expected {want_mixed[k]}, got {mixed.get(k)}")

    # The 03 shape: the field receives None and a parameter whose call sites
    # pass an int -> scalar -> mixed.
    check('scalar param', '''
class C:
    def __init__(self):
        self.s = None
    def open(self, x):
        self.s = x
c = C()
c.open(42)
''', {'C_open.x': 'scalar'}, {'C': ['s']})

    # The 12 shape: the parameter receives a constructor call, a references-only
    # field and the default None -> refs -> NOT mixed.
    check('refs param', '''
class Node:
    def __init__(self, v, nxt=None):
        self.v = v
        self.next = nxt
class L:
    def __init__(self):
        self.head = None
    def push(self, v):
        self.head = Node(v, self.head)
n = Node(1)
n2 = Node(2, n)
''', {'Node___init__.nxt': 'refs'}, {'Node': [], 'L': []})

    # None arguments are ignored: a parameter passed None and an int is
    # scalar, and one passed only None has no class at all.
    check('none ignored', '''
class C:
    def __init__(self):
        self.s = None
    def put(self, x):
        self.s = x
    def clear(self, y):
        self.s = y
c = C()
c.put(None)
c.put(5)
c.clear(None)
''', {'C_put.x': 'scalar', 'C_clear.y': 'unknown'}, {'C': ['s']})

    # Both kinds at the call sites is the TAGGED WORD (the box), not silence:
    # rule 3's "no evidence" is the `unknown`-only case, and a mixed slot's
    # reads must dispatch by kind. Its field store is mixed for the same
    # reason.
    check('both kinds', '''
class C:
    def __init__(self):
        self.s = None
    def put(self, x):
        self.s = x
c = C()
c.put(5)
c.put("a")
''', {'C_put.x': 'mixed'}, {'C': ['s']})

    # A keyword argument and a scalar default count too.
    check('kw and default', '''
def f(a, b=7):
    return a
f(a=[1])
''', {'f.a': 'refs', 'f.b': 'scalar'}, {})
    return fails


def main():
    fails = []

    reduction = '''
class C:
    def __init__(self):
        self.s = None
    def open(self, x):
        self.s = 42
    def take(self):
        self.s = None
'''
    got = _mixed(reduction)
    if got != ['s']:
        fails.append(f"reduction: expected ['s'], got {got}")

    only_none = '''
class C:
    def __init__(self):
        self.s = None
    def take(self):
        self.s = None
'''
    if _mixed(only_none) != []:
        fails.append("only-None field must not be mixed")

    only_int = '''
class C:
    def __init__(self):
        self.n = 0
    def bump(self):
        self.n = 7
'''
    if _mixed(only_int) != []:
        fails.append("int-only field must not be mixed")

    nested = '''
class C:
    def __init__(self):
        self.s = None
    def set(self, flag):
        if flag:
            self.s = 3.5
'''
    if _mixed(nested) != ['s']:
        fails.append(f"store inside an if block must count: got {_mixed(nested)}")

    refs_only = '''
class C:
    def __init__(self):
        self.s = None
    def set(self, flag):
        self.s = "text"
        self.t = None
        self.t = [1]
'''
    if _mixed(refs_only) != []:
        fails.append("a str/list literal beside None is references-only, not mixed")

    non_literal = '''
class C:
    def __init__(self):
        self.s = None
    def set(self, x):
        self.s = x
'''
    if _mixed(non_literal) != []:
        fails.append("a non-literal store is no evidence of a kind")

    fails.extend(_call_site_cases())

    if fails:
        for f in fails:
            print("FAIL:", f)
        return 1
    print("mixed_field_names / param_value_class: 0 failures")
    return 0


if __name__ == '__main__':
    sys.exit(main())
