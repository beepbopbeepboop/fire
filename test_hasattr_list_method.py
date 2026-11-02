"""Regression: hasattr on list method reports False (CODEGEN_hasattr_on_list_method_reports_false)."""
import sys, test_gimple_runner as R

CASES = {
    'hasattr_list_append_true': """\
def main():
    xs = [3, 1, 2]
    print(hasattr(xs, "append"))
    print(hasattr(xs, "extend"))
    print(hasattr(xs, "pop"))
    print(hasattr(xs, "sort"))
    print(hasattr(xs, "nosuchmethod"))
main()
""",
}

def main():
    for name, src in CASES.items():
        R.test_gimple_matches_cpython(name, src)
    print(f'\n{R._PASS} passed, {R._FAIL} failed')
    return 1 if (R._FAIL or R._TIMEOUT) else 0

if __name__ == '__main__':
    sys.exit(main())
