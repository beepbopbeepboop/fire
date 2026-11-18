"""A local the pre-pass could not type is not a "str or number" call site.

`_infer_local_var_types_core` types a value it cannot resolve with the
`int64_t` STORAGE DEFAULT. `_is_noncontainer_arg` read that default as proof
the argument is a str or a number, so a container parameter fed the very same
value at another call site was refused:

    parameter 'stmts' of '_to_returns' is passed a container at one call site
    and a str or number at another, ...

Two of the compiler's OWN modules have that shape —
`mojo/middle/out_result.py`'s `_to_returns` recurses its statement list through
`v = getattr(st, f.name)`, and `mojo/backend_gimple/emit_calls.py`'s
`_choose_overload_symbol` is handed `over.get(fname_raw)` — so both fell out of
the closure with `# ERROR: compiling imported module` and
`bootstrap-stage1-transitive` failed on a program that is correct.

The fix is the same confidence rule the rest of the pre-pass already applies
(`_is_confident_scalar`): only a PROVEN scalar (`n = 3`, `q = n + 0`) is a real
number; the `int64_t` box is silence, because it may hold a container. The
negative control below pins that the refusal still fires for a proven int, so
the narrowing cannot silence the genuinely mixed case.
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

# mojo/middle/out_result.py's `_to_returns` shape: a container parameter
# recursed into through a local bound to `getattr(...)`, whose type the
# pre-pass cannot resolve. Every call site really passes a list.
GETATTR_RESULT_BESIDE_LIST = '''\
def walk(stmts, name):
    for i, st in enumerate(stmts):
        if isinstance(st, list):
            walk(st, name)
        else:
            v = getattr(st, 'name', None)
            if isinstance(v, list):
                walk(v, name)
def main():
    walk([['a'], ['b']], 'n')
main()
'''

# mojo/backend_gimple/emit_calls.py's `_choose_overload_symbol` shape: the
# container parameter takes a local bound to `dict.get(...)`. Every call site
# really passes a list.
DICT_GET_RESULT_BESIDE_LIST = '''\
def show(xs):
    for x in xs:
        print(x)
def pick(d):
    xs = d.get('k')
    show(xs)
def main():
    pick({'k': [1, 2]})
    show([3, 4])
main()
'''

# Negative control: a PROVEN int local beside a list is still the mixed case
# the refusal exists for.
PROVEN_INT_BESIDE_LIST = '''\
def each(xs):
    for x in xs:
        print(x)
def main():
    n = 3
    each(n)
    each([4, 5])
main()
'''


def _assert_compiles(src, test_name):
    for mode, kwargs in MODES:
        try:
            gimple_codegen._run_pipeline(src, filename='container_arg.py',
                                         **kwargs)
        except RuntimeError as e:
            raise AssertionError(
                f'{test_name} [{mode}]: refused a container parameter whose '
                f'unknown argument may be a container: {str(e)[:300]}')


def _assert_refused_for_the_mixed_parameter(src, test_name):
    for mode, kwargs in MODES:
        try:
            gimple_codegen._run_pipeline(src, filename='container_arg.py',
                                         **kwargs)
        except RuntimeError as e:
            msg = str(e)
            assert "'xs'" in msg and "'each'" in msg, (
                f'{test_name} [{mode}]: refused, but not for the mixed '
                f'parameter: {msg[:300]}')
        else:
            raise AssertionError(
                f'{test_name} [{mode}]: compiled, so the binary would read '
                f'the int as a list (SIGSEGV)')


def test_a_getattr_result_is_not_a_number_observation():
    _assert_compiles(GETATTR_RESULT_BESIDE_LIST,
                     'a_getattr_result_is_not_a_number_observation')


def test_a_dict_get_result_is_not_a_number_observation():
    _assert_compiles(DICT_GET_RESULT_BESIDE_LIST,
                     'a_dict_get_result_is_not_a_number_observation')


def test_a_proven_int_beside_a_list_still_refuses():
    _assert_refused_for_the_mixed_parameter(
        PROVEN_INT_BESIDE_LIST, 'a_proven_int_beside_a_list_still_refuses')


if __name__ == '__main__':
    test_a_getattr_result_is_not_a_number_observation()
    test_a_dict_get_result_is_not_a_number_observation()
    test_a_proven_int_beside_a_list_still_refuses()
    print('PASS')
