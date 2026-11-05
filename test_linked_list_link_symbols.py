# Two link-time symbol bugs the end-to-end LinkedList[Int] build exposed (the probe in
# test_generic_struct_local_linked_list.py), each pinned on generated C:
#  1. the run-time class table (`mojo_class_setattr`) and `_mojo_classattr_read` named an OVERLOADED
#     method by its bare symbol (`LinkedList_..._pop`), but only the overload-hashed definitions
#     (`..._pop_fc238a`) exist: undefined symbols at link;
#  2. `index(i)` on an integer called `mojo_index`, which no library defines.
import os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gimple_codegen

LL = '''from std.collections import LinkedList

def main():
    var l = LinkedList[Int](1, 2, 3)
    var it = l.__iter__()
    print(it.__next__())
'''


def test_class_table_names_overload_hashed_methods():
    code, *_ = gimple_codegen.compile_linked(LL, filename='ll_probe.mojo')
    refs = set(re.findall(r'\(int64_t\)\(intptr_t\)(LinkedList_11_ElementType_3_Int_(?:pop|maybe_pop|__init__))\b', code))
    assert not refs, f'class table still names bare overloaded symbols: {sorted(refs)}'
    assert re.search(r'mojo_class_setattr\(\d+LL, "pop", \(int64_t\)\(intptr_t\)LinkedList_11_ElementType_3_Int_pop_[0-9a-f]+\)', code), \
        'pop is not registered under its overload-hashed symbol'


def test_index_of_an_integer_is_the_integer():
    code, *_ = gimple_codegen.compile_linked('''def f(i: Int) -> Int:
    return index(i) + 1

def main():
    print(f(4))
''', filename='idx_probe.mojo')
    assert 'mojo_index' not in code, 'index(i) still calls the undefined mojo_index'


if __name__ == '__main__':
    test_class_table_names_overload_hashed_methods()
    test_index_of_an_integer_is_the_integer()
    print('PASS')
