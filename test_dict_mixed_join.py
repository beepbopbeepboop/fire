#!/usr/bin/env python3
"""A dict whose values disagree on kind is joined to 'mixed', literal or store, so no typed accessor misreads a slot.

Regression for the silent wrong answer `d = {"a": "s", "b": 2}; x = d["b"]; print(x + 1)`, which printed 1 (the slot
read as a string) instead of 3 (CPython). Runs through the gimple harness.

    python3 test_dict_mixed_join.py
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_gimple_runner import compile_mojo_to_gimple_exe, run_executable_stdout

CASES = [
    ("literal_str_then_int_arith",
     'def main():\n    d = {"a": "s", "b": 2}\n    x = d["b"]\n    print(x + 1)\n', "3\n"),
    ("store_str_then_int_arith",
     'def main():\n    d = {"a": "s"}\n    d["b"] = 2\n    x = d["b"]\n    print(x + 1)\n', "3\n"),
    ("uniform_int_unchanged",
     'def main():\n    d = {"a": 1, "b": 2}\n    print(d["b"] + 1)\n', "3\n"),
    ("uniform_str_unchanged",
     'def main():\n    d = {"a": "x", "b": "y"}\n    print(d["a"])\n    print(str(d["b"]))\n', "x\ny\n"),
]


def main():
    failed = 0
    for name, src, expected in CASES:
        exe = None
        try:
            exe = compile_mojo_to_gimple_exe(src)
            out = run_executable_stdout(exe)
        except Exception as e:
            print("FAIL %s: %s" % (name, str(e).splitlines()[0][:160]))
            failed += 1
            continue
        finally:
            if exe:
                try:
                    os.unlink(exe)
                except OSError:
                    pass
        if out == expected:
            print("PASS %s" % name)
        else:
            print("FAIL %s: expected %r, got %r" % (name, expected, out))
            failed += 1
    print("%d failure(s)" % failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
