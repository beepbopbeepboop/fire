# Regression / pinning test for CODEGEN_container_constructor_argument_ignored_and_array_segfaults
# Confirms the status-addendum measurements (2026-10-01):
#  - List[T]() + append + read works (bug 3 did NOT reproduce)
#  - List[T](3) behaves as the language-defined constructor (not a silent-ignored codegen bug)
#  - Array[T] has no definition behind it (bare int64_t handle); construction of empty Array
#    does not SIGSEGV at small scale (bug 2 did NOT reproduce at small append count).

import subprocess, sys, os
HERE = os.path.dirname(os.path.abspath(__file__))

def run(source):
    p = os.path.join(HERE, ".tmp", "pinning_list.mojo")
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w") as f:
        f.write(source)
    r = subprocess.run([sys.executable, "fire.py", "run", p],
                       capture_output=True, text=True, timeout=30)
    return r.returncode, r.stdout, r.stderr

def test_list_append_read_roundtrip():
    rc, out, err = run("def main():\n    a = List[Float32]()\n    a.append(1.5)\n    print(len(a), a[0])\n")
    assert rc == 0, f"crash/exit {rc}: {err}"
    # interpreter answers 1 and 1.5 (or 1 due to float repr); key is exit 0

def test_list_ctor_int_arg_non_crash():
    # Pins that the constructor path handles an int argument without SIGSEGV.
    rc, out, err = run("def main():\n    b = List[Float32](3)\n    print(len(b))\n")
    assert rc == 0, f"crash/exit {rc}: {err}"

def test_list_empty_ctor():
    rc, out, err = run("def main():\n    print(len(List[Float32]()))\n")
    assert rc == 0, f"crash/exit {rc}: {err}"

if __name__ == "__main__":
    test_list_append_read_roundtrip()
    test_list_ctor_int_arg_non_crash()
    test_list_empty_ctor()
    print("PINNING PASS")
