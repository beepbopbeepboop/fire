# SUITE_gimplerunner-part3-part2-part2: Fix dict/tuple-key and container-key stdout mismatches

Parent: `bugs/hard/SUITE_gimplerunner-part3-part2.md` (split). Depends on the
triage/classification in `bugs/mid/SUITE_gimplerunner-part3-part2-part1.md`.

## Goal

Fix the compiler-bug stdout mismatches (exit 0, wrong printed text) in the
dict/tuple-key and container-keyed store/read family identified by part1, so
that content-keyed tuple/dict lookups and container-keyed stores print the
expected values. In-scope cases are drawn from the stdout-mismatch subset of
group A in `bugs/hard/SUITE_gimplerunner_21_failing.md`, including (as
classified in part1): `gimple_tuple_dict_key_is_content_keyed`,
`gimple_runtime_string_tuple_key_is_content_keyed`,
`gimple_container_keyed_store_reaches_its_own_read`,
`gimple_dict_get_str_hit_empty_string_is_not_a_miss`, and
`gimple_tuple_dict_key_lookup_does_not_grow` (stdout/value aspect).

## Acceptance

- For each in-scope case classified as a compiler-bug stdout mismatch in part1,
  the compiled program exits 0 and its stdout matches the expected output.
- Fixes are in the GIMPLE/codegen/runtime path (not by changing correct
  expectations) and do not regress passing cases in the affected area.
- No whole-closure compile, self-host build, or full gate; verify with the
  narrowest covering checks only (wrap compiles in
  `python3 tools/memslot.py --gb 8 --label <what> -- <cmd>` per project rules).

## Done when

- File path: `test_gimple_runner.py` (case `gimple_tuple_dict_key_is_content_keyed`).
- Command (quick, single representative case): `python3 tools/memslot.py --gb 8 --label gimple-stdout-dict-key -- python3 - <<'PY'
import os, subprocess, tempfile
from build_config import find_gcc
from gimple_codegen import compile_to_gimple

src = r"""
def main():
    d = {}
    k1 = ("a", 1)
    k2 = ("a", 1)
    k3 = ("a", 2)
    d[k1] = "one"
    d[("b",)] = "tuple1"
    d[(1, 2)] = "ints"
    print(d[k2], d.get(k3, "none"), d[k3] if k3 in d else "none")
    print(d[("b",)], d[(1, 2)], d.get((2, 1), "none"), d.get(("a", 1), "none"))
    d[k1] = "again"
    print(d[k2], len(d))
    lit = {(9, 9): "lit"}
    lit[(9, 9)] = "lit2"
    print(lit[(9, 9)], len(lit))
    n = {}
    n[(("x",), "y")] = 1
    print(n[(("x",), "y")], n.get((("x",), "z"), "none"))
    for name in ["alpha", "beta", "alpha"]:
        e = {}
        e[(name, len(name))] = 1
        print(e[(name, len(name))], len(e))
main()
"""
expected = "one none none\ntuple1 ints none one\nagain 3\nlit2 1\n1 none\n1 1\n1 1\n1 1\n"
here = os.path.dirname(os.path.abspath("test_gimple_runner.py"))
with tempfile.NamedTemporaryFile(mode='w', suffix='.c', delete=False) as f:
    f.write(compile_to_gimple(src))
    c_file = f.name
exe = c_file.replace('.c', '.exe')
try:
    rt = os.path.join(here, 'runtime')
    subprocess.check_call([find_gcc(), '-fgimple', f'-I{rt}', '-o', exe, c_file, os.path.join(rt, 'fire_runtime.c')], timeout=60)
    out = subprocess.check_output([exe], timeout=30).decode()
    assert out == expected, (out, expected)
finally:
    for p in (c_file, exe):
        try: os.unlink(p)
        except OSError: pass
PY`

The command exits 0 when the representative tuple-dict content-key stdout case
`gimple_tuple_dict_key_is_content_keyed` prints the expected output. This part
is fixed when that case and the rest of the in-scope dict/tuple-key and
container-key stdout cases (per part1) pass.
