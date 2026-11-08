#!/usr/bin/env python3
"""Regression test for SUITE_selfhost: default debug flag must be supported by the toolchain.

The toolchain's debug linker is set to level 2, so -g3 is unsupported.
This test asserts that build_executable's default debug level is -g2.
"""

import inspect
import sys

def test_default_debug_flag_is_supported() -> bool:
    """The default debug level for build_executable must be -g2 (not -g3).

    The toolchain's debug linker is set to level 2, so -g3 is unsupported.
    """
    import fire
    src = inspect.getsource(fire.build_executable)
    if 'debug_flag or "-g3"' in src:
        print("FAIL: build_executable still uses -g3 as default debug flag")
        return False
    if 'debug_flag or "-g2"' not in src:
        print(f"FAIL: build_executable default debug flag not found or changed")
        import re
        match = re.search(r'debug_flag or "([^"]+)"', src)
        if match:
            print(f"  Found: debug_flag or \"{match.group(1)}\"")
        return False
    print("PASS: build_executable default debug flag is -g2 (supported by toolchain)")
    return True


if __name__ == "__main__":
    ok = test_default_debug_flag_is_supported()
    sys.exit(0 if ok else 1)
