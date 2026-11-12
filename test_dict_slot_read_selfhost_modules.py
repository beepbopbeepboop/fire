#!/usr/bin/env python3
"""Regression test: the compiler's own modules must compile through the compiled path.

Bug (bugs/CODEGEN_dict_slot_reads_refuse_compiler_sources.md, found 2026-11-10): after the dict-slot read
work (7ae229803) a dict subscript read was tagged as a generator word, so a name later rebound to a str or
float C type was refused with MIXED_NAME_NON_INT64_REFUSAL. The fire.ci self-host build then refused
`ast_rewriter.py` ('node') and `module_shared.py` ('_fd'); `coro.py` was refused in the same family.

7fe6798cc stopped tagging dict-slot reads, so these modules compile. This test compiles the three named
modules by their real paths with the same entry point the self-host build uses
(`build_stdlib_dylib.compile_module_to_c`, linkable=False) and fails if any of them is refused or yields no C.

Without 7fe6798cc's change, `ast_rewriter.py` and `module_shared.py` raise the mixed-name refusal.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from build_stdlib_dylib import compile_module_to_c  # noqa: E402

MODULES = [
    ("ast_rewriter.py", "ast_rewriter"),
    ("mojo/middle/module_shared.py", "module_shared"),
    ("mojo/middle/coro.py", "coro"),
]


def main() -> int:
    failures = []
    for rel, name in MODULES:
        path = ROOT / rel
        src = path.read_text()
        try:
            c_text = compile_module_to_c(src, str(path), name, linkable=False)
        except RuntimeError as e:
            failures.append(f"{rel}: refused: {str(e)[:300]}")
            print(f"  FAIL {rel}: refused")
            continue
        if not c_text or not c_text.strip():
            failures.append(f"{rel}: produced no usable C")
            print(f"  FAIL {rel}: no C text")
            continue
        print(f"  PASS {rel}: compiled ({len(c_text)} bytes of C)")
    if failures:
        print("FAILED:")
        for f in failures:
            print("  " + f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
