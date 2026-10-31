#!/usr/bin/env python3
"""Regression for bug:LEAN_proof_verdict_key_ignores_lib_dir_so_a_relative_repo_root_caches_a_failure_for_everybody.

A relative repo_root used to resolve lib_dir against the proof's own cwd,
producing a broken LEAN_PATH that cached a search-path failure for everybody.
The fix: absolute lib_dir in LEAN_PATH + v5 key with proof-dir digest.
This test fails on the pre-fix code (key ignores directory; LEAN_PATH relative)
and passes after.
"""
import os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from formal import lean as L

def test_relative_repo_root_cannot_poison_library_path():
    """_run_lean must absolutise lib_dir regardless of repo_root."""
    src = L.__file__
    import inspect
    code = inspect.getsource(L._run_lean)
    assert "os.path.abspath(lib_dir)" in code, "_run_lean must absolutise lib_dir"

def test_key_changes_with_proof_directory_content():
    """The verdict key must include the proof's directory contents."""
    assert b"formal-proof-verdict-v5" in L._VERDICT_VERSION, "version must be v5"
    lib = tempfile.mkdtemp(prefix="vk-lib-")
    try:
        a = tempfile.mkdtemp(prefix="vk-a-")
        b = tempfile.mkdtemp(prefix="vk-b-")
        try:
            text = "import ProofLib\ntheorem t : 1 = 1 := by trivial\n"
            for d in (a, b):
                with open(os.path.join(d, "p.lean"), "w") as f:
                    f.write(text)
            with open(os.path.join(b, "Helper.lean"), "w") as f:
                f.write("def h : Nat := 1\n")
            ka = L.proof_verdict_key(os.path.join(a, "p.lean"), lib, "lean")
            kb = L.proof_verdict_key(os.path.join(b, "p.lean"), lib, "lean")
            assert ka != kb, "directories with different siblings must diverge"
        finally:
            import shutil
            shutil.rmtree(a, ignore_errors=True); shutil.rmtree(b, ignore_errors=True)
    finally:
        import shutil
        shutil.rmtree(lib, ignore_errors=True)

if __name__ == "__main__":
    test_relative_repo_root_cannot_poison_library_path()
    test_key_changes_with_proof_directory_content()
    print("OK: lean-proof-verdict-key regression")
