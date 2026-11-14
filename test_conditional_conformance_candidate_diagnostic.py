#!/usr/bin/env python3
"""Regression: conditional trait conformance candidate selection diagnostics (part 3)."""

from gimple_codegen import compile_to_gimple


def _compile(src, filename='t.mojo'):
    return compile_to_gimple(src, do_imports=False, filename=filename)


def _assert_raises(src, msg, notes=None):
    try:
        _compile(src)
    except RuntimeError as e:
        out = str(e)
        assert msg in out, out
        for note in (notes or []):
            assert note in out, out
        return out
    assert False, "expected RuntimeError"


# 1. AmbiguousUnconditionalAndConditional
def test_ambiguous_unconditional_and_conditional():
    src = (
        'trait Copyable:\n'
        '    pass\n'
        'trait AmbiguousMethodTrait:\n'
        '    def perform(self): ...\n'
        '\n'
        'struct AmbiguousUnconditionalAndConditional[T: AnyType](\n'
        '    AmbiguousMethodTrait where conforms_to(T, Copyable)\n'
        '):\n'
        '    var v: T\n'
        '    def __init__(out self, v: T):\n'
        '        self.v = v\n'
        '    def perform(self):\n'
        '        pass\n'
        '    def perform(self) where conforms_to(T, Copyable):\n'
        '        pass\n'
    )
    _assert_raises(src,
                   "does not implement all requirements for 'AmbiguousMethodTrait'",
                   notes=["ambiguous use of 'perform'"])


# 2. AmbiguousBothConditional
def test_ambiguous_both_conditional():
    src = (
        'trait Copyable:\n'
        '    pass\n'
        'trait Intable:\n'
        '    pass\n'
        'trait MultipleConditionsTrait:\n'
        '    def run(self): ...\n'
        '\n'
        'struct AmbiguousBothConditional[T: AnyType](\n'
        '    MultipleConditionsTrait where conforms_to(T, Copyable) and conforms_to(T, Intable)\n'
        '):\n'
        '    var v: T\n'
        '    def __init__(out self, v: T):\n'
        '        self.v = v\n'
        '    def run(self) where conforms_to(T, Copyable):\n'
        '        pass\n'
        '    def run(self) where conforms_to(T, Intable):\n'
        '        pass\n'
    )
    _assert_raises(src,
                   "does not implement all requirements for 'MultipleConditionsTrait'",
                   notes=["ambiguous use of 'run'"])


# 3. UnprovableWithValidCandidate
def test_unprovable_with_valid_candidate():
    src = (
        'trait Copyable:\n'
        '    pass\n'
        'trait Intable:\n'
        '    pass\n'
        'trait UnprovableCandidateTrait:\n'
        '    def f(self): ...\n'
        '\n'
        'struct UnprovableWithValidCandidate[T: AnyType](\n'
        '    UnprovableCandidateTrait where conforms_to(T, Copyable)\n'
        '):\n'
        '    var v: T\n'
        '    def __init__(out self, v: T):\n'
        '        self.v = v\n'
        '    def f(self) where conforms_to(T, Copyable):\n'
        '        pass\n'
        '    def f(self) where conforms_to(T, Intable):\n'
        '        pass\n'
    )
    _assert_raises(src,
                   "does not implement all requirements for 'UnprovableCandidateTrait'")


# 4. DisprovedWithWhereNot
def test_disproved_with_where_not():
    src = (
        'trait Copyable:\n'
        '    pass\n'
        'trait ContradictingConstraintTrait:\n'
        '    def g(self): ...\n'
        '\n'
        'struct DisprovedWithWhereNot[T: AnyType](\n'
        '    ContradictingConstraintTrait where conforms_to(T, Copyable)\n'
        '):\n'
        '    var v: T\n'
        '    def __init__(out self, v: T):\n'
        '        self.v = v\n'
        '    def g(self) where not conforms_to(T, Copyable):\n'
        '        pass\n'
    )
    _assert_raises(src,
                   "does not implement all requirements for 'ContradictingConstraintTrait'")


# --- positive controls -----------------------------------------------------

def test_single_provable_candidate_selected():
    _compile(
        'trait Copyable:\n'
        '    pass\n'
        'trait Intable:\n'
        '    pass\n'
        'trait T:\n'
        '    def f(self): ...\n'
        '\n'
        'struct S[X: AnyType](T where conforms_to(X, Copyable)):\n'
        '    var v: X\n'
        '    def __init__(out self, v: X):\n'
        '        self.v = v\n'
        '    def f(self) where conforms_to(X, Copyable):\n'
        '        pass\n'
        '    def f(self) where not conforms_to(X, Copyable):\n'
        '        pass\n')


def test_single_unconditional_candidate_compiles():
    _compile(
        'trait T:\n'
        '    def f(self): ...\n'
        '\n'
        'struct S(T):\n'
        '    def f(self):\n'
        '        pass\n')


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for t in tests:
        t()
    print(f'OK: {len(tests)} tests passed')
