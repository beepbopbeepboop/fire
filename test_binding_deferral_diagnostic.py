#!/usr/bin/env python3
"""Regression test: a failed struct binding reports the constraint that failed it.

Modular's test/mojo-parser/failed_binding_deferrals.mojo requires:

    struct NeedsCopyablePos[T: Copyable, n: Int](Movable where False) where n > 0
    def failed_binding[U: Movable & Deinitable](
        x: NeedsCopyablePos[CondCopyable[U], 0])          # error: violated constraint
    def successful_binding[U: Movable & Deinitable](
        x: NeedsCopyablePos[CondCopyable[U], 1])          # error: lacking evidence

Three things had to hold for the failing binding:

* The requirement named in the note is the struct's own `where` clause
  (`n > 0`). The header regex used to read `False) where n > 0`, because the
  base list's `Movable where False` is a `where` too.
* The failing binding reaches the user as `error: ... violated constraint`
  whichever path instantiates it. The in-TU elaboration queue used to leak the
  raw exception, while an explicit `Struct[...]` in a body was wrapped.
* A satisfied binding of the same shape compiles with no diagnostic.

Part 2 (modular parity): only the error that failed the binding is reported,
with no deferred-constraint noise. The `n == 0` binding is provably false
(`violated constraint`); the `n == 1` binding is not provably false (any
"lacking evidence" for the conditional `T: Copyable` requirement is deferred
and must not surface as noise on a violated binding).
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import driver
import elaborate
from gimple_codegen import compile_to_gimple

_HEAD = (
    'struct CondCopyable[T: Movable & Deinitable](\n'
    '    Copyable where conforms_to(T, Copyable), Movable\n'
    '):\n'
    '    var value: Self.T\n'
    '\n'
    '\n'
    'struct NeedsCopyablePos[T: Copyable, n: Int](Movable where False) where n > 0:\n'
    '    pass\n'
    '\n'
    '\n'
)

_NEEDS = (
    'struct NeedsCopyablePos[T: Copyable, n: Int](Movable where False) where n > 0:\n'
    '    pass\n'
)


def _write(src):
    d = tempfile.mkdtemp(prefix='binding_deferral_')
    p = os.path.join(d, 't.mojo')
    with open(p, 'w') as fh:
        fh.write(src)
    return p


def _driver_compile(src):
    """Compile through driver.compile_program, the path `fire` uses for a
    program. Returns the exception text, or None when it compiled."""
    p = _write(src)
    try:
        driver.compile_program(p, src, output=os.path.join(os.path.dirname(p), 'a.out'),
                               run=False)
    except Exception as e:
        return f'{type(e).__name__}: {e}'
    return None


def test_where_clause_text_is_the_clause_not_the_base_list():
    # The base list's `Movable where False` is not a clause of the struct, so
    # the requirement must be read as `n > 0`.
    try:
        elaborate.check_where_clauses('', _NEEDS, {'T': 'CondCopyable[Int]', 'n': '0'})
    except elaborate.WhereConformanceError as e:
        assert str(e) == "requirement 'n > 0' is not satisfied", str(e)
        return
    raise AssertionError('a provably false struct where clause was accepted')


def test_generic_failed_binding_reports_violated_constraint():
    src = _HEAD + (
        'def failed_binding[U: Movable & Deinitable]():\n'
        '    var a = NeedsCopyablePos[CondCopyable[U], 0]()\n'
        '\n'
        '\n'
        'def main():\n'
        '    failed_binding[Int]()\n'
    )
    text = _driver_compile(src)
    assert text is not None, 'a failed binding compiled'
    assert "invalid instantiation of 'NeedsCopyablePos': violated constraint" in text, text
    assert "requirement 'n > 0' is not satisfied" in text, text
    assert 'False) where' not in text, text
    assert text.count('error:') == 1, f'more than one diagnostic: {text}'


def test_explicit_failed_binding_uses_the_same_wording():
    src = _HEAD + (
        'def main():\n'
        '    var a = NeedsCopyablePos[CondCopyable[Int], 0]()\n'
    )
    try:
        compile_to_gimple(src, do_imports=True, filename=_write(src))
    except RuntimeError as e:
        assert "invalid instantiation of 'NeedsCopyablePos': violated constraint" in str(e), str(e)
        assert 'False) where' not in str(e), str(e)
        assert str(e).count('error:') == 1, f'more than one diagnostic: {e}'
        return
    raise AssertionError('a failed explicit binding compiled')


def test_satisfied_generic_binding_compiles():
    src = _HEAD + (
        'def successful_binding[U: Movable & Deinitable]():\n'
        '    var a = NeedsCopyablePos[CondCopyable[U], 1]()\n'
        '\n'
        '\n'
        'def main():\n'
        '    successful_binding[Int]()\n'
    )
    text = _driver_compile(src)
    assert text is None, f'a satisfied binding was refused: {text}'


def test_failed_binding_reports_only_the_failing_error_no_deferred_noise():
    # n == 0 is provably false (violated constraint) even though CondCopyable[U]
    # is only conditionally Copyable for a generic U. The diagnostic must report
    # only the error that failed the binding, with no deferred/lacking-evidence
    # noise about the conditional Copyable requirement.
    src = _HEAD + (
        'def failed_binding[U: Movable & Deinitable]():\n'
        '    var a = NeedsCopyablePos[CondCopyable[U], 0]()\n'
        '\n'
        '\n'
        'def main():\n'
        '    failed_binding[Int]()\n'
    )
    text = _driver_compile(src)
    assert text is not None, 'a failed binding compiled'
    assert "invalid instantiation of 'NeedsCopyablePos': violated constraint" in text, text
    assert "requirement 'n > 0' is not satisfied" in text, text
    assert 'lacking evidence' not in text, text
    assert 'invalid bindings in signature' not in text, text
    assert text.count('error:') == 1, f'more than one diagnostic: {text}'


def test_signature_failed_binding_reports_violated_constraint():
    # A provably-false binding in a function-signature parameter annotation
    # must be rejected at declaration time. The modular test's
    # failing binding is a PARAMETER type in a function signature, not a body
    # instantiation. Its `where` clause (`n > 0`) is provably false at n == 0,
    # so the declaration must fail with modular's own wording and nothing else.
    src = _HEAD + (
        'def failed_binding[U: Movable & Deinitable](\n'
        '    x: NeedsCopyablePos[CondCopyable[U], 0]):\n'
        '    pass\n'
    )
    text = _driver_compile(src)
    assert text is not None, 'a failed binding in a signature compiled'
    assert 'error: violated constraint' in text, text
    assert 'lacking evidence' not in text, text
    assert text.count('error:') == 1, f'more than one diagnostic: {text}'


def test_signature_unproven_binding_reports_lacking_evidence():
    # bugs/hard/DIAGNOSTICS_binding_deferrals-part2.md. `CondCopyable[U]` is
    # Copyable only where `U: Copyable`; this signature only knows
    # `U: Movable & Deinitable`, so the `T: Copyable` requirement is neither
    # provable nor provably false. Modular reports `lacking evidence` and the
    # declaration must fail with that single diagnostic.
    src = _HEAD + (
        'def successful_binding[U: Movable & Deinitable](\n'
        '    x: NeedsCopyablePos[CondCopyable[U], 1]):\n'
        '    pass\n'
    )
    text = _driver_compile(src)
    assert text is not None, 'an unproven binding in a signature compiled'
    assert 'error: invalid bindings in signature: lacking evidence' in text, text
    assert 'violated constraint' not in text, text
    assert text.count('error:') == 1, f'more than one diagnostic: {text}'

    # Positive control: the same struct instantiated with a provably Copyable
    # type and a satisfied where clause still compiles.
    src = _HEAD + (
        'def satisfied_binding(\n'
        '    x: NeedsCopyablePos[Int, 1]):\n'
        '    pass\n'
    )
    text = _driver_compile(src)
    assert text is None, f'a satisfied signature binding was refused: {text}'


if __name__ == '__main__':
    test_where_clause_text_is_the_clause_not_the_base_list()
    test_generic_failed_binding_reports_violated_constraint()
    test_explicit_failed_binding_uses_the_same_wording()
    test_satisfied_generic_binding_compiles()
    test_failed_binding_reports_only_the_failing_error_no_deferred_noise()
    test_signature_failed_binding_reports_violated_constraint()
    test_signature_unproven_binding_reports_lacking_evidence()
    print('ok')
