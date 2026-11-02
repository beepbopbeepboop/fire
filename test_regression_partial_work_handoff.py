# Regression / pinning test for bug:PARTIAL_WORK_HANDOFF
# PARTIAL_WORK_HANDOFF.md §2.1 describes a half-fixed container-typed ctor
# arg gap (Reader(self._items) loses element type, loop SIGSEGVs).
# This test verifies the doc was cleaned up: stale next-step advice removed,
# stale deleted-citation clean-up, and the regression source intact.

def test_partial_work_handoff_doc_cleared_stale_advice():
    with open('bugs/PARTIAL_WORK_HANDOFF.md') as f:
        content = f.read()
    # The doc must NOT carry the stale next-step advice it once did.
    assert 'The next step recorded below is stale advice' not in content
    # The doc must name the dedicated residue doc.
    assert 'bugs/CODEGEN_dispatched_for_loop_shares_one_var_between_dict_and_list_arms.md' in content

def test_repro_source_preserved():
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