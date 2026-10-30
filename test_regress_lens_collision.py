"""Regression for the self-host link failure with undefined toplevel symbols
(fixed by removing the colliding `_lens` locals in module_gen.py).
The compiled path froze the NAME as the set, so the dict assignment
raised "cannot coerce MojoSet * to MojoDict *", which silently rolled
back module_gen.py's own compile and left four GPU siblings without
declarations or bodies (link-time undefined toplevel symbols).
Fix: rename the dict local to `_len_dict` so the names no longer collide."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def test_module_gen_lens_names_distinct():
    src = open('mojo/backend_gimple/module_gen.py').read()
    # The dict local (device-kernel pass) must NOT be named _lens anymore.
    # The set local (element-shape pass) was already renamed _elens.
    assert '_len_dict = self._device_launch_lengths.get(_nm)' in src, \
        "dict local should be renamed to _len_dict"
    # No remaining collision: only one occurrence of the old _lens = pattern.
    lines = [l for l in src.splitlines() if '_lens = ' in l and 'NOT' not in l]
    assert len(lines) == 0, f"stale _lens assignment remains: {lines}"

if __name__ == '__main__':
    test_module_gen_lens_names_distinct()
    print("PASS: module_gen _lens collision removed")
