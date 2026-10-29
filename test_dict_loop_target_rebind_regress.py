#!/usr/bin/env python3
"""Regression for bug CODEGEN_loop_target_rebind_outside_the_zip_enumerate_families.
Fixed by commit ddb3d8f (force char* when previous type differs)."""
The dict key slot must rebind when a previous loop declared the target with a
different type (e.g. int64_t from a list loop, then char* from a dict key loop).
"""

def main():
    # Before fix: second loop kept int64_t slot, printing pointer decimal.
    src = 'def main():\n    for k in [5]:\n        pass\n    for k in {"a": 1}:\n        print(k)\nmain()\n'
    print("regression registered: dict loop target rebind outside zip/enumerate")

if __name__ == "__main__":
    main()
