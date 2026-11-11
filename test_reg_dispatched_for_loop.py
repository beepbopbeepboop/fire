# Regression for the deleted doc bugs/CODEGEN_dispatched_for_loop_shares_one_var_between_dict_and_list_arms.md
# (codegen half fixed; inference half tracked in PARTIAL_WORK_HANDOFF.md §2.1)
#
# `for i in <value whose type is unknown>:` lowers to a runtime dict/set/list
# dispatch in `_gen_for_iter`. The arms used to share ONE C variable, declared
# by the dict arm as `char *`, so a list of ints SIGSEGV'd on `print(i)` and a
# list of doubles or an arithmetic body misbehaved. Each case below is compiled
# through the real gimple path and must print exactly what CPython prints.
#
# Run: python3 test_reg_dispatched_for_loop.py   (or pytest)

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_gimple_runner as R  # noqa: E402

_HEAD = '''
class Reader:
    def __init__(self, items):
        self.items = items
class Owner:
    def __init__(self, items):
        self._items = items
    def read(self):
        return Reader(self._items).items
'''

# (name, loop body inside main(), expected stdout == CPython's)
CASES = [
    ('int_list_print',
     "o = Owner([10, 20])\n    for i in o.read():\n        print(i)\n",
     '10\n20\n'),
    ('str_list_print',
     "o = Owner(['a', 'bb'])\n    for i in o.read():\n        print(i)\n",
     'a\nbb\n'),
    ('dbl_list_print',
     "o = Owner([1.5, 2.25])\n    for i in o.read():\n        print(i)\n",
     '1.5\n2.25\n'),
    ('str_keyed_dict_print',
     "o = Owner({'k1': 1, 'k2': 2})\n    for k in o.read():\n        print(k)\n",
     'k1\nk2\n'),
    ('int_list_arithmetic',
     "o = Owner([3, 4])\n    t = 0\n    for i in o.read():\n        t = t + i * 2\n    print(t)\n",
     '14\n'),
    ('int_list_mod',
     "o = Owner([7, 9])\n    t = 0\n    for i in o.read():\n        t = t + i % 4\n    print(t)\n",
     '4\n'),
    ('discard_binds_nothing',
     "o = Owner([1, 2])\n    n = 0\n    for i in o.read():\n        _ = i\n        n = n + i\n    print(n)\n",
     '3\n'),
    ('int_set_sum',
     "o = Owner({5, 6})\n    n = 0\n    for i in o.read():\n        n = n + i\n    print(n)\n",
     '11\n'),
    ('str_list_len',
     "o = Owner(['xx', 'y'])\n    for i in o.read():\n        print(len(i), i)\n",
     '2 xx\n1 y\n'),
    ('list_of_lists_len',
     "o = Owner([[1, 2], [3]])\n    for row in o.read():\n        print(len(row))\n",
     '2\n1\n'),
]


def _run(body: str) -> str:
    src = _HEAD + "def main():\n    " + body + "main()\n"
    exe = R.compile_mojo_to_gimple_exe(src)
    try:
        rc = R.run_executable(exe)
        assert rc == 0, f"compiled program exited {rc} (SIGSEGV is -11)"
        return R.run_executable_stdout(exe)
    finally:
        try:
            os.unlink(exe)
        except OSError:
            pass


def test_dispatched_for_loop_matches_cpython():
    failures = []
    for name, body, want in CASES:
        try:
            got = _run(body)
        except AssertionError as e:
            failures.append(f"{name}: {e}")
            continue
        if got != want:
            failures.append(f"{name}: expected {want!r}, got {got!r}")
    assert not failures, "\n".join(failures)


if __name__ == '__main__':
    test_dispatched_for_loop_matches_cpython()
    print("PASS test_reg_dispatched_for_loop")
