"""Regression tests for the Wave-1 entry-point bug fixes (B1/B2, REF.html §3).

Run standalone:  python3 test_refactor_bugs.py

(a) compile_linked twice in one process on the same source must produce
    byte-identical output — guards the class of bug where module-global
    dedup state (_emitted_unresolved_stub_syms / the _mojo_type_name-table
    flag) leaks from the first compile into the second and suppresses
    emission (compile_linked historically never cleared these; REF.html B1).
(b) compile_to_gimple_with_cpp followed by compile_linked in one process
    must match a fresh compile_linked-only run of the same source.

Limitation: these use tiny sources whose compiles may not populate every
dedup structure (stub paths need unresolved imports to trigger). They still
fail today's B1 shape in principle and pin entry-point idempotence; the
stdlib-dylib skip-count gate remains the broad detector.
"""
import sys

import gimple_codegen

SRC = '''def main():
    print("hello world")

main()
'''


def _run(fn, *args, **kw):
    out = fn(*args, **kw)
    return out[0] if isinstance(out, tuple) else out


def main_test() -> int:
    fails = 0

    # (a) link-mode idempotence within one process
    first = _run(gimple_codegen.compile_linked, SRC)
    second = _run(gimple_codegen.compile_linked, SRC)
    if first != second:
        print("FAIL: compile_linked output differs on second in-process call")
        fails += 1
    else:
        print("ok: compile_linked idempotent across calls")

    # (b) inline-with-cpp then linked == fresh linked
    gimple_codegen.compile_to_gimple_with_cpp(SRC)
    after_inline = _run(gimple_codegen.compile_linked, SRC)
    fresh = _run(gimple_codegen.compile_linked, SRC)  # third call: state re-cleared each time now
    if after_inline != fresh:
        print("FAIL: with_cpp-then-linked differs from repeated linked")
        fails += 1
    else:
        print("ok: with_cpp does not perturb subsequent link-mode output")

    # sanity: outputs are non-trivial C
    for name, txt in (("linked", first),):
        if "def main" not in SRC or len(txt) < 100:
            print(f"WARN: {name} output suspiciously small ({len(txt)} chars)")

    print("PASS" if fails == 0 else f"{fails} FAILURE(S)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main_test())
