#!/usr/bin/env python3
"""`_frame_methods` finds the frame-receiver methods of a real image.

`formal/arm64_proof_gen.py::_frame_methods` decides which methods of a
frame-shaped struct are leaf accessors (`set`/`get`) so that the by-reference
receiver proof path (`_generate_frame_proof`) has something to prove.  Since the
stack-floor guard moved into every prologue it found NONE: every image returned
`None`, the frame proofs were unreachable, and nothing reported it.

Two defects, both in the finder, and both pinned here through the image of a
real program (`formal/examples/wide_recv.mojo`, a two-field `Point` with
`set_x`, `get_x`, `get_y`):

  * The extent of a function was "up to the next LABEL in address order".  The
    codegen also labels points INSIDE a body (`{fname}_sf{k}_ok`, the guard's
    `_ok`), so the extent of `Point_get_x` ended at its own body and the body's
    `RET` was outside it.  A function now ends where the next FUNCTION begins.
  * The receiver's slot map was seeded at the function entry, and the body
    reads the receiver through `x19`, which the PROLOGUE copies (`ADD x19, x0,
    #0`).  Scanning from the body alone lost that copy and refused every method.
    The prologue is walked for the register copies; its loads are not accesses.

Before the fix `_frame_methods` returned `None` for this image.

    python3 test_formal_frame_method_finder.py [-v]
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import formal.arm64_proof_gen as G          # noqa: E402
import formal.build as fb                   # noqa: E402

WIDE_RECV = os.path.join(ROOT, "formal", "examples", "wide_recv.mojo")


class _Captured(Exception):
    """Raised by the spy to stop the build right where the generator is called."""


def _image_of_wide_recv(tmp_dir: str):
    """The `(prog, code, info)` the arm64 generator is handed for wide_recv.

    `fb.compile_formal` calls `generate_arm64_proof(prog, code, info)` once the
    image is built; the spy takes those three arguments and stops the build
    there, so no proof is generated.  The module attribute is patched because
    `formal/build.py` imports the generator by name at call time."""
    cap = {}
    real = G.generate_arm64_proof

    def spy(prog, code, info):
        cap.update(prog=prog, code=code, info=info)
        raise _Captured()

    G.generate_arm64_proof = spy
    try:
        fb.compile_formal(WIDE_RECV, output=os.path.join(tmp_dir, "wide.aout"),
                          prove=True, check=False)
    except _Captured:
        pass
    finally:
        G.generate_arm64_proof = real
    if not cap:
        raise AssertionError("compile_formal never reached the proof generator")
    return cap["prog"], cap["code"], cap["info"]


class TestFrameMethodFinder(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls._tmp = tempfile.mkdtemp(prefix="frame_finder_")
        cls.prog, cls.code, cls.info = _image_of_wide_recv(cls._tmp)

    def test_finds_every_leaf_accessor_of_the_frame_struct(self):
        """set_x, get_x and get_y are all found, with the right kind.

        Asserted by name and kind, so a finder that returns a list of the right
        length with the wrong members still fails."""
        found = G._frame_methods(self.prog, self.code, self.info)
        self.assertIsNotNone(found, "the finder found no frame methods at all")
        kinds = {m["fname"]: m["kind"] for m in found}
        self.assertEqual(kinds, {"Point_set_x": "set",
                                 "Point_get_x": "get",
                                 "Point_get_y": "get"})

    def test_method_extent_ends_at_its_own_return(self):
        """Each method's extent is its own body, not the next label's address.

        `Point_get_x`'s extent must include its `RET` and stop before
        `Point_get_y`, which is the next FUNCTION, not before its own
        `Point_get_x_sf3_ok` body label."""
        found = {m["fname"]: m for m in G._frame_methods(self.prog, self.code,
                                                         self.info)}
        labels = self.info["labels"]
        get_x = found["Point_get_x"]
        self.assertEqual(get_x["entry"], labels["Point_get_x"])
        self.assertEqual(get_x["end"], labels["Point_get_y"])

    def test_body_slots_follow_the_prologue_register_copy(self):
        """The body reads `self` through `x19`, a copy the prologue made.

        Scanning the body alone (no receiver map carried from the prologue) is
        what made every method invisible.  `Point_get_x` reads field `x` at
        slot 0 and `Point_get_y` reads `y` at slot 1."""
        found = {m["fname"]: m for m in G._frame_methods(self.prog, self.code,
                                                         self.info)}
        self.assertEqual(found["Point_get_x"]["pairs"], [("x", 0)])
        self.assertEqual(found["Point_get_y"]["pairs"], [("y", 1)])

    def test_body_only_scan_seeds_from_the_prologue(self):
        """`_frame_slot_accesses(..., body=)` walks the guard prologue for the
        receiver's copies, and does not count its loads as accesses.

        Compares the body-only scan against the scan from the entry, on the
        same method: they must agree on the accesses."""
        words = {self.info["base_addr"] + i:
                 int.from_bytes(self.code[i:i + 4], "little")
                 for i in range(0, len(self.code) - len(self.code) % 4, 4)}
        labels = self.info["labels"]
        entry = labels["Point_get_x"]
        body = labels["Point_get_x_sf3_ok"]
        end = labels["Point_get_y"]         # the next function: exclusive bound
        self.assertEqual(G._frame_slot_accesses(words, entry, end, body=body),
                         [(0, False)])
        # Without the prologue's register copy the body alone cannot be traced.
        self.assertIsNone(G._frame_slot_accesses(words, body, end))


if __name__ == "__main__":
    unittest.main(verbosity=2)
