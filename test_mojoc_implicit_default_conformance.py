#!/usr/bin/env python3
"""Regression: a `.mojoc` struct with an implicit-default bracket parameter
reports the full three-line conformance diagnostic.

Modular's `import_mojoc_implicit_default_param.mojo` (precompiled-import
diagnostics): the package is precompiled and its sources deleted; the
consumer instantiates `Container[NotMarked]` where `NotMarked` does not
implement `Marked`.  Expected, exactly:

    error: 'Container' parameter 'T' has 'Marked' type, but value has type 'AnyStruct[NotMarked]'
    note: 'Container' declared here
    struct Container[T: Marked, W: Wrapper = __init__(Int(4))]  # note - synthetic signature

The last line is the part-2 renderer's spelling of the stored record: the
implicit conversion default is printed from its source text, never resolved
(the `Wrapper.__init__` it would need was deliberately never materialized).

In-process only: write and read the artifact, then run the one import-time
checker on the record.  No native build and no compilation.
"""

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mojo.middle import mojoc_artifact
from mojo.middle.mojoc_conformance import conformance_diagnostic
from mojo.middle.mojoc_signature import SYNTHETIC_MARKER


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


CONSUMER = (
    "@fieldwise_init\n"
    "struct NotMarked(Copyable, Movable):\n"
    "    var value: Int\n"
    "\n"
    "\n"
    "def main():\n"
    "    _ = Container[NotMarked]()\n"
)


def main():
    tmp = os.path.join(HERE, ".tmp", "mojoc_implicit_default_conformance")
    if os.path.exists(tmp):
        shutil.rmtree(tmp)
    pkg = os.path.join(tmp, "src", "pkg")
    _write(os.path.join(pkg, "__init__.mojo"),
           "from .container import Container, Marked, Wrapper\n")
    _write(os.path.join(pkg, "container.mojo"),
           "trait Marked:\n"
           "    def marked(self):\n"
           "        ...\n"
           "\n"
           "struct Wrapper:\n"
           "    def __init__(out self, v: Int):\n"
           "        pass\n"
           "\n"
           "struct Container[T: Marked, W: Wrapper = __init__(Int(4))]:\n"
           "    var value: Int\n"
           "\n"
           "    def __init__(out self):\n"
           "        self.value = 0\n")

    artifact = os.path.join(tmp, "deps", "pkg.mojoc")
    mojoc_artifact.write_artifact(pkg, artifact)
    # Sources gone: everything below comes from the stored signature.
    shutil.rmtree(os.path.join(tmp, "src"))

    records = mojoc_artifact.load_artifact(artifact)
    structs = records.get("structs", {})
    container = structs["Container"]
    by_name = {p["name"]: p for p in container["bracket_params"]}
    assert by_name["T"].get("type") == "Marked", by_name
    assert by_name["W"].get("default") == "__init__(Int(4))", by_name

    got = conformance_diagnostic(container, ["NotMarked"], CONSUMER, structs)
    want = (
        "error: 'Container' parameter 'T' has 'Marked' type, but value has "
        "type 'AnyStruct[NotMarked]'\n"
        "note: 'Container' declared here\n"
        "struct Container[T: Marked, W: Wrapper = __init__(Int(4))]  "
        + SYNTHETIC_MARKER
    )
    assert got == want, f"diagnostic:\n{got!r}\nexpected:\n{want!r}"

    # A conforming argument must still be accepted silently.
    conforming = (
        "@fieldwise_init\n"
        "struct Good(Copyable, Movable):\n"
        "    var value: Int\n"
        "\n"
        "    def marked(self):\n"
        "        pass\n"
        "\n"
        "\n"
        "def main():\n"
        "    _ = Container[Good]()\n"
    )
    assert conformance_diagnostic(container, ["Good"], conforming,
                                  structs) is None

    print("ok")


if __name__ == "__main__":
    main()
