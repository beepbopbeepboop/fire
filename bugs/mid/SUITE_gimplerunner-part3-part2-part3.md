# SUITE_gimplerunner-part3-part2-part3: Fix dict value/repr and misc stdout mismatches

Parent: `bugs/hard/SUITE_gimplerunner-part3-part2.md` (split). Depends on the
triage/classification in `bugs/mid/SUITE_gimplerunner-part3-part2-part1.md`.

## Goal

Fix the remaining compiler-bug stdout mismatches (exit 0, wrong printed text)
identified by part1 outside the tuple/container-key subset of part2. This
covers dict value/repr and pair/list formatting cases and other stdout-output
cases, including (as classified in part1):
`gimple_dict_items_pair_var_prints_as_a_pair`,
`gimple_dict_value_repr_uses_the_struct_dunder`,
`gimple_dict_value_repr_remaining_two_shapes`,
`gimple_list_slice_mixed`,
`gimple_str_window_matches_cpython`,
`gimple_math_module_members_lower_to_libm`, and
`gimple_nested_class_var_attr_from_str_param`. Cases determined in part1 to be
wrong expected stdout are corrected as expectations (not compiler changes)
within this part when that is the minimal, self-contained fix.

## Acceptance

- For each in-scope case classified in part1, the compiled program exits 0 and
  its stdout matches the correct/expected output; where part1 classifies the
  recorded expectation as wrong, the expectation is corrected to match the
  verified correct behavior.
- Fixes do not regress passing cases in the affected area.
- No whole-closure compile, self-host build, or full gate; verify with the
  narrowest covering checks only (wrap compiles in
  `python3 tools/memslot.py --gb 8 --label <what> -- <cmd>` per project rules).

## Done when

- File path: `test_gimple_runner.py` (case `gimple_dict_items_pair_var_prints_as_a_pair`).
- Command (quick, single representative case): `python3 tools/memslot.py --gb 8 --label gimple-stdout-repr -- python3 - <<'PY'
import os, subprocess, tempfile
from build_config import find_gcc
from gimple_codegen import compile_to_gimple

src = r"""
def ints():
    d = {"a": 1, "b": 2}
    for (v) in d.items():
        print(v)
        print(str(v))
        print(f"{v}")
        print(v.key, v.value)

def strs():
    d = {"a": "x", "b": "y"}
    for (v) in d.items():
        print(v)

def main():
    ints()
    strs()
"""
expected = ("('a', 1)\n('a', 1)\n('a', 1)\na 1\n"
            "('b', 2)\n('b', 2)\n('b', 2)\nb 2\n"
            "('a', 'x')\n('b', 'y')\n")
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

The command exits 0 when the representative dict-items pair stdout case
`gimple_dict_items_pair_var_prints_as_a_pair` prints the expected output. This
part is fixed when that case and the rest of the in-scope dict value/repr and
misc stdout-mismatch cases (per part1) pass.
