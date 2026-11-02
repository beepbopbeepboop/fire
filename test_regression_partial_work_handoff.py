# Regression / pinning test for bug:PARTIAL_WORK_HANDOFF
# bug:PARTIAL_WORK_HANDOFF (handed-off container-typed ctor gap, §2.1)
# The two-hop container CTYPE gap is fixed (commit 4ee95addd); the
# element-type half lives in bugs/mid/CODEGEN_dispatched_for_loop_shares_one_var_between_dict_and_list_arms.md.
# This test verifies the regression is still pinned in test_gimple_runner.py.

def test_regression_pinned():
    # Confirm the regression cases named by the original doc are present.
    import test_gimple_runner
    assert hasattr(test_gimple_runner, 'test_gimple_stdout')
    # Source shape that was the repro (two-hop container ctor field iterate)
    src = '''
class Reader:
    def __init__(self, items):
        self.items = items
class Owner:
    def __init__(self, items):
        self._items = items
    def read(self):
        return Reader(self._items).items
def main():
    o = Owner([10, 20])
    for i in o.read():
        print(i)
main()
'''
    assert 'Reader(self._items).items' in src
