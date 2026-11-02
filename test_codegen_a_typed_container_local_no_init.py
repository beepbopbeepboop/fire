"""Regression test for CODEGEN: a typed container local/global with no
initializer must be allocated (fresh empty container) instead of left as
an uninitialised pointer that segfaults on first use."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gimple_codegen import compile_to_gimple


def test_typed_container_local_no_init_allocates():
    src = """\
def main():
    var xs: List[Int]
    xs.append(1)
    print(xs)
"""
    c = compile_to_gimple(src, do_imports=False)
    assert "mojo_list_new ()" in c, "typed List local with no initializer was not allocated"


def test_typed_container_global_no_init_allocates():
    src = """\
var xs: List[Int]

def main():
    xs.append(1)
    print(xs)
"""
    c = compile_to_gimple(src, do_imports=False)
    assert "mojo_list_new ()" in c, "typed List global with no initializer was not allocated"


if __name__ == "__main__":
    test_typed_container_local_no_init_allocates()
    test_typed_container_global_no_init_allocates()
    print("PASS")
