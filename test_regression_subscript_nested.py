# Regression for bug: dict value type lost through nested subscript
# Both shapes must match CPython; control (one-level) must stay correct.
import subprocess, sys, os

def run(label, src, want):
    with open('.tmp/reg_tmp.mojo', 'w') as f:
        f.write(src)
    # Use existing gimple runner mechanism if available; else compile/run via python
    # Here we just invoke python against the test harness with a minimal snippet
    cmd = [sys.executable, '-c',
           'import sys; sys.path.insert(0,"."); '
           'from test_gimple_runner import test_gimple_matches_cpython; '
           f'test_gimple_matches_cpython("{label}", open(".tmp/reg_tmp.mojo").read())'
          ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    ok = res.returncode == 0
    print(f"{'PASS' if ok else 'FAIL'} {label} want={want}")
    if not ok:
        print("  stdout:", res.stdout[-500:] if len(res.stdout)>500 else res.stdout)
        print("  stderr:", res.stderr[-500:] if len(res.stderr)>500 else res.stderr)
    return ok

# Shape 1: dict of lists, subscript the list
src1 = '''def f():
    d = {}
    d["k"] = [1.5, 2.5]
    return d["k"][1]
'''

# Shape 2: nested dict, subscript twice (string value)
src2 = '''def f():
    d = {}
    d["k"] = "vv"
    return d["k"][0]
'''

# Control: one-level dict subscript (must not move)
src_ctrl = '''def f():
    d = {}
    d["k"] = [1.5, 2.5]
    return d["k"]
'''

ok = True
ok &= run("dict_list_nested", src1, "2.5")
ok &= run("dict_str_nested", src2, "v")
ok &= run("dict_onelevel_ctrl", src_ctrl, "MojoList *")
sys.exit(0 if ok else 1)
