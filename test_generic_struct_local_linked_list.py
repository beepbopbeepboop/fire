#!/usr/bin/env python3
"""Pin for bugs/CODEGEN_generic_struct_local_typed_int64_linked_list.md.

`var l = LinkedList[Int](1, 2, 3)` must lower to a real elaborated struct, not
`int64_t l; l = 0;` with `__iter__()`/`__next__()` stubbed out."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SRC = '''from std.collections import LinkedList

def main():
    var l = LinkedList[Int](1, 2, 3)
    var it = l.__iter__()
    print(it.__next__())
'''


def _compile():
    from build_stdlib_dylib import compile_module_to_c
    path = os.path.join(HERE, '.tmp', 'll_probe.mojo')
    return compile_module_to_c(SRC, path, 'll_probe', linkable=False)


def _main_body(c):
    i = c.index('_ll_probe_main (void)')
    return c[i:c.index('\n}\n', i)]


def test_linked_list_local_is_a_struct():
    """`l` is the elaborated struct and its constructor is really called."""
    body = _main_body(_compile())
    assert 'int64_t l;' not in body, 'l is still typed as a scalar'
    assert 'LinkedList_11_ElementType_3_Int * l;' in body
    assert 'LinkedList_11_ElementType_3_Int___init___' in body, \
        'the constructor call was not lowered'
    assert 'indirect call via SubscriptExpr' not in body


def test_node_pointer_alias_is_typed():
    """`_NodePointer = Optional[Pointer[Node[T], o]]` names `Node[Int]`: the
    list's `_head`/`_tail` are `Node_..._Int *` (not an erased word) and `Node`
    is materialized in the same TU."""
    c = _compile()
    i = c.index('typedef struct LinkedList_11_ElementType_3_Int {')
    st = c[i:c.index('} LinkedList_11_ElementType_3_Int;', i)]
    assert 'Node_1_T_3_Int * _head;' in st, st
    assert 'Node_1_T_3_Int * _tail;' in st, st


def test_node_links_are_typed_self_pointers():
    """`Node`'s own `_prev`/`_next` (`Optional[Pointer[Self, o]]`) stay typed
    `Node_..._Int *`: the constructor's `self._prev = <erased word>` must not
    override the field's explicit annotation."""
    c = _compile()
    i = c.index('typedef struct Node_1_T_3_Int {')
    st = c[i:c.index('} Node_1_T_3_Int;', i)]
    assert 'Node_1_T_3_Int * _prev;' in st, st
    assert 'Node_1_T_3_Int * _next;' in st, st
    assert 'int64_t _prev;' not in st


def test_node_pointer_unwrap_is_identity():
    """`curr.value()[].next()` on the typed `Node *` unwraps the pointer; it
    must not read `Node`'s same-named `value` FIELD and call it, and
    `nn.unsafe_take_pointee()` is the pointer, not a phantom struct method."""
    c = _compile()
    assert 'mojo_fnptr_call_0' not in c
    assert 'Node_1_T_3_Int_unsafe_take_pointee' not in c
    assert c.count('int64_t.next() stubbed') <= 1, 'Node.next() is stubbed again'


def test_node_allocation_api_is_lowered():
    """`alloc(Layout[Node[T]].single()).unsafe_leak()` is a zeroed `Node *` from
    the shared `_alloc_n_` helper and `dealloc(ThinAllocation(unsafe_owned_ptr=p)
    .unsafe_with_layout(..))` frees `p`; neither is stubbed to a scalar."""
    c = _compile()
    for m in ('.single() stubbed', '.unsafe_leak() stubbed',
              '.unsafe_with_layout() stubbed'):
        assert m not in c, m
    assert '_alloc_n_Node_1_T_3_Int' in c
    assert 'dealloc (' not in c


def test_erased_word_structs_not_materialized():
    """`Optional[Int](...)` keeps its erased tagged-word model: materializing
    it as a struct is the measured test_optional regression."""
    from build_stdlib_dylib import compile_module_to_c
    src = ('from std.collections import Optional\n\n'
           'def main():\n    var a = Optional[Int](5)\n    print(a.value())\n')
    c = compile_module_to_c(src, os.path.join(HERE, '.tmp', 'opt_probe.mojo'),
                            'opt_probe', linkable=False)
    assert 'Optional_1_T_3_Int' not in c


if __name__ == '__main__':
    test_linked_list_local_is_a_struct()
    test_node_pointer_alias_is_typed()
    test_node_links_are_typed_self_pointers()
    test_node_pointer_unwrap_is_identity()
    test_node_allocation_api_is_lowered()
    test_erased_word_structs_not_materialized()
    print('PASS: generic-struct local is a struct')
