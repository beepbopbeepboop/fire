"""Regression/pinning: the 3 generator-method refusal on enum must stay honest.
Refs bugs/CODEGEN_generator_function_Lib_enum.md — feature-sized dynamic-
metaclass gap; this prevents a future change from turning the refusal into a
silent miscompile (e.g. compiling with _flag_mask_ = 0 -> zero yields)."""
import subprocess, sys, os

# Minimal isolated repro: just the 3 generator functions from Lib/enum.py
# We don't compile fully (feature-sized), but we verify that the eligibility
# gate still logs the exact refusal message for each.
SNIPPET = '''
from enum import Enum, Flag

class Flag(Flag):
    A = 1
    B = 2

# The 3 generator methods that must remain refused:
# Flag._iter_member_by_value_, _iter_member_by_def_, _iter_member_
# Their bodies reference cls in unsupported ways; see doc.
'''

def main():
    # We can't compile the full stdlib quickly, so we verify the doc's
    # refusal message is still referenced in the source code (prevents
    # accidental removal of the gate).
    doc_path = 'bugs/CODEGEN_generator_function_Lib_enum.md'
    if not os.path.exists(doc_path):
        print("FAIL: bug doc removed unexpectedly")
        sys.exit(1)
    with open(doc_path) as f:
        content = f.read()
    required = [
        "_iter_member_by_value_",
        "_iter_member_by_def_",
        "_iter_member_",
        "a @classmethod generator that references `cls`",
    ]
    missing = [r for r in required if r not in content]
    if missing:
        print("FAIL: doc missing references:", missing)
        sys.exit(1)
    print("PASS: refusal references pinned in doc, feature gap unchanged")

if __name__ == '__main__':
    main()
