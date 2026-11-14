#!/usr/bin/env python3
"""Part 1 of DIAGNOSTICS_binding_deferrals-part2: type-argument bound evidence.

Pure parse/decision checks for elaborate.type_arg_bound_evidence and the strict
mode of _constraint_implied_for_evidence. No compilation.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import elaborate


_SRC = (
    'struct CondCopyable[T: Movable & Deinitable](\n'
    '    Copyable where conforms_to(T, Copyable), Movable\n'
    '):\n'
    '    var value: Self.T\n'
    '\n'
    '\n'
    'struct NeedsCopyablePos[T: Copyable, n: Int](Movable where False) where n > 0:\n'
    '    pass\n'
)


def main():
    src = _SRC
    needs_tmpl = elaborate.extract_struct_source(src, 'NeedsCopyablePos')
    assert needs_tmpl, 'missing NeedsCopyablePos template'

    assert elaborate.type_arg_bound_evidence(
        src, needs_tmpl, 'T', 'CondCopyable[U]',
        {'U': {'Movable', 'Deinitable'}}) == 'unproven'

    assert elaborate.type_arg_bound_evidence(
        src, needs_tmpl, 'T', 'CondCopyable[U]',
        {'U': {'Movable', 'Deinitable', 'Copyable'}}) == 'proven'

    assert elaborate.type_arg_bound_evidence(
        src, needs_tmpl, 'T', 'U', {'U': {'Copyable'}}) == 'proven'

    assert elaborate.type_arg_bound_evidence(
        src, needs_tmpl, 'T', 'Int', {}) == 'unknown'

    assert elaborate.type_arg_bound_evidence(
        src, needs_tmpl, 'T', 'CondCopyable[Int]', {}) == 'unknown'

    assert elaborate.type_arg_bound_evidence(
        src, needs_tmpl, 'T', 'CondCopyable[U]', {}) == 'unproven'

    assert elaborate.type_arg_bound_evidence(
        src, needs_tmpl, 'n', '1', {}) == 'unknown'

    assert elaborate._constraint_implied_for_evidence(
        'conforms_to(U, Copyable)', 'conforms_to(U, Movable)',
        src, {}, strict=True) is False
    assert elaborate._constraint_implied_for_evidence(
        'conforms_to(U, Copyable)', 'conforms_to(U, Copyable)',
        src, {}, strict=True) is True

    print('ok')


if __name__ == '__main__':
    main()
