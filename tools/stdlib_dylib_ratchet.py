#!/usr/bin/env python3
"""Ratchet for the from-scratch stdlib dylib: fail only on a module that NEWLY falls back to source.

    python3 tools/stdlib_dylib_ratchet.py

`build_stdlib_dylib.build_stdlib()` builds the dylib and prints one `skip <module>: <why>` line per module that
could not be compiled (its clients fall back to source for it, so the failure is silent). The skip set must not
grow. The known set is `compile_stdlib.EXPECTED_FAILURES`, the same per-file baseline `stdlib-syntax` uses:
a module that is expected there is expected here, and a module that is not is a regression.

The symbol-collision exclusions (`excluded for symbol collisions`) are a separate, documented stopgap
(bug:CODEGEN_dylib_generic_inline_copies_share_one_symbol) and are reported, not gated.

The dylib is linked with `-undefined dynamic_lookup`, so ANY symbol it references may be left to resolve
at load — including `_std_*` symbols nothing in the dylib (or anywhere) defines. That failure is silent in
this job by construction: the skip count does not move, and `stdlib-syntax` only checks that the `.c`
parses. It aborts every compiled program at load with dyld's "symbol not found". So after a successful
build this script also reads the built dylib with `nm` and FAILS when a `_std_` symbol is referenced but
not defined by it.

Screen: only the verdict, any unexpected skip and any undefined `_std_` reference. The full build output
goes to build/stdlib_dylib.log."""
import os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from compile_stdlib import EXPECTED_FAILURES  # noqa: E402  (the one baseline, shared with stdlib-syntax)
from module_loader import STDLIB_PATH  # noqa: E402

LOG = os.path.join(ROOT, "build", "stdlib_dylib.log")


def _nm_symbols(argv):
    """The symbol names in `nm`'s output, one per line's LAST token.

    llvm-nm prints either bare symbols (`nm -u`: `_foo`) or
    `<addr> <TYPE> <name>` (`nm -gU`: `0000000000000123 T _foo`), and a
    universal Mach-O additionally prints a `file (for architecture x):`
    section header that ends in ':' — which terminates no symbol name and is
    skipped on that rule. Anything else on a line is not a symbol either, and
    taking the last token keeps both spellings working with one rule.

    A failing `nm` raises rather than returning an empty set: an empty set
    reads as "the dylib defines nothing" (every `_std_` reference would be a
    failure, a false red) or as "references nothing" (a silent green, the
    exact hole this check exists to close)."""
    r = subprocess.run(argv, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("%s failed (exit %d): %s" %
                           (" ".join(argv), r.returncode, (r.stderr or "").strip()))
    syms = set()
    for line in r.stdout.splitlines():
        line = line.rstrip()
        if not line or line.endswith(':'):
            continue
        syms.add(line.split()[-1])
    return syms


def unresolved_stdlib_refs(dylib):
    """`_std_` symbols `dylib` references but does not define, sorted.

    The dylib is monolithic — every importable stdlib symbol is supposed to
    be present in it — and it is linked with `-undefined dynamic_lookup`, so
    a module whose generated C calls a `_std_*` symbol no translation unit
    defines still links and still ships. The failure is dyld's, at load, in
    whatever program loads the dylib, and this job cannot see it any other
    way: `skip` counts only modules the compiler REFUSED, and `nm -u` against
    `nm -gU` is the only direct read of what the artifact really needs and
    really has.

    A `_std_` name in the undefined set and not in the defined set is
    exactly a missing export: nothing outside the dylib defines it either
    (the runtime's symbols are `mojo_*`, and libc's carry no `std` prefix in
    this tree's mangling)."""
    undefined = _nm_symbols(['nm', '-u', dylib])
    defined = _nm_symbols(['nm', '-g', '-U', dylib])
    return sorted(s for s in undefined
                  if s.startswith('_std_') and s not in defined)


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    r = subprocess.run([sys.executable, "-c", "import build_stdlib_dylib as b; b.build_stdlib()"],
                       cwd=ROOT, capture_output=True, text=True)
    out = r.stdout + r.stderr
    open(LOG, "w").write(out)
    if r.returncode != 0:
        print("stdlib-dylib: the build itself FAILED (exit %d); full output in %s" % (r.returncode, LOG))
        return 1
    skipped = []
    for line in out.splitlines():
        m = re.match(r"\s*skip (\S+?): ", line)
        if m:
            rel = m.group(1).split("stdlib/", 1)[-1]
            skipped.append((rel, line.strip()))
    unexpected = [(rel, why) for rel, why in skipped if rel not in EXPECTED_FAILURES]
    stale = sorted(set(EXPECTED_FAILURES) - {rel for rel, _ in skipped} - _not_in_sweep())
    excluded = re.search(r"\((\d+) modules excluded", out)
    print("stdlib-dylib: %d module(s) fell back to source (%d expected), %d symbol-collision exclusion(s) reported"
          % (len(skipped), len(skipped) - len(unexpected), int(excluded.group(1)) if excluded else 0))
    failed = False
    if unexpected:
        print("NEW dylib skips (not in compile_stdlib.EXPECTED_FAILURES):")
        for rel, why in unexpected:
            print("  " + why[:200])
        failed = True
    # The gate gap this job used to have: a dylib that referenced `_std_*`
    # symbols it never defined passed clean. The default output path mirrors
    # `build_stdlib_dylib.build_stdlib`'s own default (kept inline THERE on
    # purpose — test_runtime_dylib.py pins that source), and the ratchet's
    # build above runs with no arguments, so the default is what just ran.
    import build_stdlib_dylib as bsd
    dylib = os.path.join(ROOT, 'build', 'libmojostdlib.%s.dylib' % bsd.normalize_arch(None))
    try:
        missing = unresolved_stdlib_refs(dylib)
    except RuntimeError as e:
        print("stdlib-dylib: the undefined-reference check could not run: %s" % e)
        return 1
    if missing:
        print("stdlib-dylib: the built dylib references %d _std_ symbol(s) it does not define "
              "(clients would abort at load):" % len(missing))
        for s in missing:
            print("  U " + s)
        failed = True
    else:
        print("stdlib-dylib: no undefined _std_ references in %s" % os.path.relpath(dylib, ROOT))
    if failed:
        return 1
    if stale:
        print("note: expected modules that now build into the dylib (remove from EXPECTED_FAILURES): "
              + ", ".join(stale))
    return 0


def _not_in_sweep():
    # An entry with no source file is GONE, not stale; compile_stdlib reports it itself.
    return {rel for rel in EXPECTED_FAILURES if not os.path.exists(os.path.join(STDLIB_PATH, rel))}


if __name__ == "__main__":
    sys.exit(main())
