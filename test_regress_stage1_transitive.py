"""Regression for CODEGEN_gate_bootstrap_stage1_transitive_red."""
import sys, os
sys.path.insert(0, '.')
from test_gimple import gimple_compiles

def test_nested_def_rebound_param_takes_set():
    nested = """\
def outer():
    def walk(live):
        live = set(live)
        live.add(1)
        return live
    return walk({3})

def main():
    print(len(outer()))
main()
"""
    ok, _, err = gimple_compiles(nested)
    assert ok, err

if __name__ == '__main__':
    test_nested_def_rebound_param_takes_set()
    print('PASS')
