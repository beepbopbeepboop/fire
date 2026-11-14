#!/usr/bin/env python3
"""Regression: precompile a package to a .mojoc signature artifact and read it
back after deleting the sources (DIAGNOSTICS_mojoc_imports-part2-part1).

Parses/reads only; no compilation, no memslot wrapper needed.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mojo.middle import mojoc_artifact


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def main():
    tmp = os.path.join(HERE, ".tmp", "mojoc_precompile_sig")
    if os.path.exists(tmp):
        shutil.rmtree(tmp)
    src = os.path.join(tmp, "src")
    deps = os.path.join(tmp, "deps")
    os.makedirs(deps, exist_ok=True)

    _write(os.path.join(src, "pkg", "__init__.mojo"), "from .container import Container, Marked, Wrapper\n")
    _write(os.path.join(src, "pkg", "container.mojo"),
           "trait Marked:\n"
           "    pass\n"
           "\n"
           "struct Wrapper:\n"
           "    fn __init__(out self, v: Int):\n"
           "        pass\n"
           "\n"
           "struct Container[T: Marked, W: Wrapper = __init__(Int(4))]:\n"
           "    pass\n")

    out = os.path.join(deps, "pkg.mojoc")
    cmd = [sys.executable, os.path.join(HERE, "fire.py"), "precompile",
           os.path.join(src, "pkg"), "-o", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, f"precompile failed:\nstdout={r.stdout}\nstderr={r.stderr}"

    # Sources gone: the record must come from the artifact.
    shutil.rmtree(src)
    assert not os.path.exists(os.path.join(src, "pkg")), "sources should be deleted"

    recs = mojoc_artifact.load_artifact(out)
    structs = recs.get("structs", {})
    assert "Container" in structs, structs.keys()
    c = structs["Container"]
    bparams = c.get("bracket_params", [])
    # Find by name for robustness.
    by_name = {p["name"]: p for p in bparams}
    assert "T" in by_name and "W" in by_name, bparams
    assert by_name["T"].get("type", "") in ("Marked", "Marked"), by_name["T"]
    assert by_name["W"].get("type", "") == "Wrapper", by_name["W"]
    assert by_name["W"].get("default") == "__init__(Int(4))", by_name["W"]

    # Reader via -I dir resolution path: resolve pkg.Container from deps only.
    resolved = mojoc_artifact.resolve_import("pkg", "Container", [deps])
    assert resolved is not None, "resolve_import should find Container in pkg.mojoc"
    rb = {p["name"]: p for p in resolved.get("bracket_params", [])}
    assert rb["T"].get("type") == "Marked", rb
    assert rb["W"].get("type") == "Wrapper" and rb["W"].get("default") == "__init__(Int(4))", rb

    print("ok")


if __name__ == "__main__":
    main()
