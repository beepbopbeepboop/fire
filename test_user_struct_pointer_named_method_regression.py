"""Regression test: a USER STRUCT's own method spelled like a raw-pointer
protocol method (`load`, `store`, `offset`, ...) must dispatch to the struct
method, not to the `UnsafePointer` lowering.

Before the fix, `_lower_method_call`'s raw-pointer branch fired on any
`ot.endswith(' *')` receiver whose method name was in `_RAW_PTR_METHODS`, so
`self._a.load()` on a user struct `A` compiled to `_t = *self->_a;` -- the
CALL DROPPED, the whole struct copied by value. That is what broke the
self-host build: myinterpreter.py's `_LazyImportTarget.load` (PEP 810 lazy
imports) became `*self`, so `_LazyImportTarget_load` returned a struct where
gcc wanted a word ("aggregate value used where an integer was expected",
"non-register as LHS of unary operation") and `_LazyImportType.resolve`'s
`self._target.load()` became a `*self->_target` deref.

The discriminator is narrow on purpose: only a struct that actually DEFINES
the name. A genuine `UnsafePointer[T]` receiver has no `load` in
`_struct_method_names` and must keep its raw-pointer meaning -- the third test
below pins that.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gimple_codegen import compile_to_gimple


def _compile(src: str) -> str:
    return compile_to_gimple(src, do_imports=False)


def test_struct_load_method_is_called_not_dereferenced():
    src = """\
struct A:
    var x: Int

    def __init__(out self):
        self.x = 7

    def load(self) -> Int:
        return self.x


struct B:
    var _a: A

    def __init__(out self):
        self._a = A()

    def via_field(self) -> Int:
        return self._a.load()

    def via_local(self) -> Int:
        var a = self._a
        return a.load()
"""
    c = _compile(src)
    # The struct method's own C symbol must be CALLED, not bypassed by a
    # by-value copy of the receiver. `A_load (` matches both the definition
    # and a call, so anchor on the assignment form the call site emits.
    assert '= A_load (' in c, (
        "a user struct's own `load` method was not called; the raw-pointer "
        "branch dereferenced the receiver instead")
    # And the receiver must not be dereferenced as a whole struct on the way.
    assert '=*self->_a' not in c and '= *self->_a' not in c, (
        "the receiver was dereferenced by value instead of calling A.load")


def test_struct_store_method_is_called_not_dereferenced():
    src = """\
struct A:
    var x: Int

    def __init__(out self):
        self.x = 0

    def store(self, v: Int):
        self.x = v


struct B:
    var _a: A

    def __init__(out self):
        self._a = A()

    def put(self, v: Int):
        self._a.store(v)
"""
    c = _compile(src)
    assert 'A_store (' in c, (
        "a user struct's own `store` method was not called")


def test_unsafepointer_load_still_dereferences():
    # The counter-case: a genuine `UnsafePointer[T]` receiver must keep the
    # raw-pointer meaning. `UnsafePointer` has no `load` in
    # `_struct_method_names`, so the raw-pointer branch still owns it.
    src = """\
def copy_val(src: UnsafePointer[Int], dst: UnsafePointer[Int]) -> None:
    var v: Int = src.load()
    dst.store(v)


def nth_elem(p: UnsafePointer[Float64], n: Int) -> Float64:
    var q: UnsafePointer[Float64] = p.offset(n)
    return q.load()
"""
    c = _compile(src)
    # `_t1 = *src;` -- the pointer is dereferenced, not a struct method called.
    assert '= *src;' in c, (
        "UnsafePointer.load() no longer dereferences the pointer")
    # `*_tN = ...;` -- the store writes through the pointer.
    import re
    assert re.search(r'\*\w+ = ', c), (
        "UnsafePointer.store() no longer writes through the pointer")


if __name__ == "__main__":
    test_struct_load_method_is_called_not_dereferenced()
    test_struct_store_method_is_called_not_dereferenced()
    test_unsafepointer_load_still_dereferences()
    print("PASS")
