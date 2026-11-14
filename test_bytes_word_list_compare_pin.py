#!/usr/bin/env python3
"""Pinning regression: bytes list element compares equal to bytes literal."""
# This verifies the root fix: a bytes-word list element compares by content,
# not by identity / raw word.

def test_bytes_element_eq_literal():
    # Direct check of the runtime equality for registered bytes words
    assert b"a.py" == b"a.py"
    # Two distinct bytes objects compare by content
    assert (b"a." + b"py") == b"a.py"
    # List equality compares elements by content
    assert [b"a.py"] == [b"a.py"]
    assert [b"a.py", b"b.txt"] == [b"a.py", b"b.txt"]
    # Ordering / sorting of bytes elements by content, not address
    assert sorted([b"b.py", b"a.py"]) == [b"a.py", b"b.py"]
    print("PASS bytes-word list compare pin")

if __name__ == "__main__":
    test_bytes_element_eq_literal()
