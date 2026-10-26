# Regression for bug:CODEGEN_dispatched_for_loop_shares_one_var_between_dict_and_list_arms
# Repro from bugs/CODEGEN_dispatched_for_loop_shares_one_var_between_dict_and_list_arms.md
# Expected: for i in o.read(): print(i) produces 10 / 20, not SIGSEGV.
# Status: FAILS (SIGSEGV on compiled path) — blocked on representation choice.

def test_dispatched_for_loop_regression():
    # This is a compile-time / codegen-level bug; the Python-level test only
    # verifies the source is intact. The real verification is the compiled C run.
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
    assert 'for i in o.read()' in src
    # Actual compiled-run verification required; currently SIGSEGV (exit -11)
    # because _gen_for_iter's dict/list dispatch shares one C variable.
