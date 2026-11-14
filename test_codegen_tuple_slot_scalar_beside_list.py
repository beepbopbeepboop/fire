"""Regression test for bug:CODEGEN_str_in_tuple_slot_refusal_beside_list.

`_infer_local_var_types_core` types every tuple-unpack target with the
`int64_t` STORAGE DEFAULT, so the box said nothing about `s` in
`s, n = pair()`.  `_is_noncontainer_arg` therefore exempted every unpack
target; the only surviving observation at `each(...)` was `each([4, 5])`,
`xs` resolved `MojoList *`, and the str slot was read as a list header --
SIGSEGV in the compiled binary.  The fix classifies a callee's return-tuple
slot from the callee's own return statements: a slot every return proves
scalar records the non-container observation (so the existing mixed-container
refusal fires), a slot every return proves a container stays exempt, and an
unprovable or disagreeing slot stays silent.

Both the doc's repro (a str slot) and a number slot are asserted.  A number in
a tuple slot is the same SIGSEGV through the same path -- the refusal message
already says "a str or number" -- and it is what distinguishes this
implementation from a str-only proof: the number case fails if
`_element_is_scalar` stops accepting scalar literals.  The container-slot case
is the negative control: the exemption must survive, or the coro
`_async_method_setup` tuple is refused.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import gimple_codegen  # noqa: E402

MODES = (
    ('single-TU', {'do_imports': True}),
    ('link-mode', {'link_mode': True}),
)

# The doc's repro: `pair` returns the str in slot 0, `main` unpacks it and
# passes it to the iterated parameter beside a list literal.
STR_SLOT_BESIDE_LIST = '''\
def pair():
    return "de", 1
def each(xs):
    for x in xs:
        print(x)
def main():
    s, n = pair()
    each(s)
    each([4, 5])
main()
'''

# The same slot path with a number literal in slot 0: `n` is a provably
# non-container slot, so it is the same mixed-kind observation as the str.
NUMBER_SLOT_BESIDE_LIST = '''\
def pair():
    return 7, "de"
def each(xs):
    for x in xs:
        print(x)
def main():
    n, s = pair()
    each(n)
    each([4, 5])
main()
'''

# Negative control, the coro `_async_method_setup` shape: the unpacked
# `real_params` is a container slot on every return, so it must stay exempt
# from the non-container observation and the program must still compile.
CONTAINER_SLOT_IS_EXEMPT = '''\
def _setup(fn, is_method):
    real_params = fn.params[1:] if is_method else fn.params
    return 1, real_params
def walk(xs):
    for x in xs:
        print(x)
def direct(fn, is_method):
    real_params = fn.params[1:] if is_method else fn.params
    walk(real_params)
def via_tuple(fn, is_method):
    n, real_params = _setup(fn, is_method)
    walk(real_params)
'''


def _pipeline(src, kwargs):
    return gimple_codegen._run_pipeline(src, filename='tuple_slot.py', **kwargs)


def _assert_refused_for_the_mixed_parameter(src, test_name):
    for mode, kwargs in MODES:
        try:
            _pipeline(src, kwargs)
        except RuntimeError as e:
            msg = str(e)
            assert "'xs'" in msg and "'each'" in msg, (
                f'{test_name} [{mode}]: refused, but not for the mixed '
                f'parameter: {msg[:300]}')
        else:
            raise AssertionError(
                f'{test_name} [{mode}]: compiled, so the binary would read '
                f'the scalar slot as a list (SIGSEGV)')


def _assert_compiles(src, test_name):
    for mode, kwargs in MODES:
        try:
            _pipeline(src, kwargs)
        except RuntimeError as e:
            raise AssertionError(
                f'{test_name} [{mode}]: refused a container slot: '
                f'{str(e)[:300]}')


def test_a_str_in_a_tuple_slot_beside_a_list_refuses():
    _assert_refused_for_the_mixed_parameter(
        STR_SLOT_BESIDE_LIST, 'a_str_in_a_tuple_slot_beside_a_list_refuses')


def test_a_number_in_a_tuple_slot_beside_a_list_refuses():
    _assert_refused_for_the_mixed_parameter(
        NUMBER_SLOT_BESIDE_LIST,
        'a_number_in_a_tuple_slot_beside_a_list_refuses')


def test_a_container_in_a_tuple_slot_is_still_exempt():
    _assert_compiles(CONTAINER_SLOT_IS_EXEMPT,
                     'a_container_in_a_tuple_slot_is_still_exempt')


if __name__ == '__main__':
    test_a_str_in_a_tuple_slot_beside_a_list_refuses()
    test_a_number_in_a_tuple_slot_beside_a_list_refuses()
    test_a_container_in_a_tuple_slot_is_still_exempt()
    print('PASS')
