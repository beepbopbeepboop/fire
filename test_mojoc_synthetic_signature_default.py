#!/usr/bin/env python3
"""Regression: render a synthetic signature from a precompiled record.

DIAGNOSTICS_mojoc_imports-part2-part2: the imported-struct diagnostic prints
the part-1 signature record as Mojo source text.  The tricky case is an
implicit conversion default (`W: Wrapper = __init__(Int(4))`) whose
`Wrapper.__init__` was never materialized into the artifact: the default must
be printed as written and must not raise (MOCO-4270).

Pure record-in/text-out; no compilation, no fixture package.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mojo.middle.mojoc_signature import SYNTHETIC_MARKER, render_signature


def main():
    assert SYNTHETIC_MARKER == "# note - synthetic signature", SYNTHETIC_MARKER

    # The acceptance case from the modular test.  There is deliberately no
    # Wrapper/__init__ entry anywhere in the record: an implicit conversion
    # default must be printed from its stored source text, not resolved.
    container = {
        "kind": "struct",
        "name": "Container",
        "bracket_params": [
            {"name": "T", "type": "Marked", "default": None},
            {"name": "W", "type": "Wrapper", "default": "__init__(Int(4))"},
        ],
        "runtime_params": [],
    }
    got = render_signature(container)
    want = (
        "struct Container[T: Marked, W: Wrapper = __init__(Int(4))]  "
        "# note - synthetic signature"
    )
    assert got == want, f"rendered:\n{got!r}\nexpected:\n{want!r}"

    # Non-conversion path: a plain literal default is unchanged.
    literal = {
        "kind": "struct",
        "name": "Bounded",
        "bracket_params": [{"name": "N", "type": "Int", "default": "4"}],
        "runtime_params": [],
    }
    got = render_signature(literal)
    want = "struct Bounded[N: Int = 4]  # note - synthetic signature"
    assert got == want, f"rendered:\n{got!r}\nexpected:\n{want!r}"

    # Bracket params precede runtime params, and a function record renders too.
    fn = {
        "kind": "function",
        "name": "run",
        "bracket_params": [{"name": "T", "type": "AnyType", "default": None}],
        "runtime_params": [
            {"name": "x", "type": "Int", "default": "4"},
            {"name": "y", "type": "Bool", "default": None},
        ],
    }
    got = render_signature(fn)
    want = "fn run[T: AnyType](x: Int = 4, y: Bool)  # note - synthetic signature"
    assert got == want, f"rendered:\n{got!r}\nexpected:\n{want!r}"

    # A record that came from source carries no synthetic marker.
    got = render_signature(literal, synthetic=False)
    assert got == "struct Bounded[N: Int = 4]", got

    print("ok")


if __name__ == "__main__":
    main()
