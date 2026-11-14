#!/usr/bin/env python3
"""Ratchet for the from-scratch stdlib dylib: fail only on a module that NEWLY falls back to source.

    python3 tools/stdlib_dylib_ratchet.py

`build_stdlib_dylib.build_stdlib()` builds the dylib and prints one `skip <module>: <why>` line per module that
could not be compiled (its clients fall back to source for it, so the failure is silent). The skip set must not
grow. The known set is `compile_stdlib.EXPECTED_FAILURES`, the same per-file baseline `stdlib-syntax` uses:
a module that is expected there is expected here, and a module that is not is a regression.

The symbol-collision exclusions (`excluded for symbol collisions`) are a separate, documented stopgap
(bug:CODEGEN_dylib_generic_inline_copies_share_one_symbol) and are reported, not gated.

The dylib is linked with `-undefined dynamic_lookup`, so a `_std_*` symbol it references may be left for
the loader. That failure is silent in this job by construction: the skip count does not move, and
`stdlib-syntax` only checks that the `.c` parses. After a successful build this script therefore LOADS
the dylib (a tiny `dlopen(..., RTLD_LAZY)` probe, the same lazy binding a program launch uses) and FAILS
when it does not load — dyld's "symbol not found" names the offending symbol.

The load is the contract, and it is deliberately narrower than "every `_std_` reference is defined". The
dylib is a speed hack: a client uses a symbol from it if present and falls back to source for it if not
(see `build_stdlib_dylib.build`'s "it need not be complete — it must only link"), so plain CALL references
to functions the dylib does not define are expected and lazy — measured on this tree, 2026-11-12: 50 of
them, all in `__la_symbol_ptr`, and `dlopen(RTLD_LAZY)` succeeds. The fatal shape is a `_std_` reference
stored in DATA — the class tables and the reflection table take a symbol's ADDRESS, which dyld binds
eagerly, so one undefined entry aborts every client at load (the 2026-11-11
`_std_iter___init____PeekableIterator_peek` bug). The load probe catches exactly that, including a
non-`_std_` symbol, and the `nm` list below is still reported so lazy gaps stay visible.

Screen: only the verdict, any unexpected skip, any undefined `_std_` reference and a load failure. The
full build output goes to build/stdlib_dylib.log."""
import os, platform, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from compile_stdlib import EXPECTED_FAILURES  # noqa: E402  (the one baseline, shared with stdlib-syntax)
from module_loader import STDLIB_PATH  # noqa: E402
from build_config import find_gcc  # noqa: E402

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

    A REFERENCE here is not necessarily a load failure. A function call is bound lazily (the dylib's
    `__la_symbol_ptr`), so a client runs until it calls that function and the client's own source fallback
    is what normally satisfies it; a symbol whose ADDRESS is taken in a data section (the class tables, the
    reflection table) is bound eagerly and aborts every load. `dylib_load_error` below is what decides
    the gate; this function is what NAMES the gaps, for the note and for `test_stdlib_dylib_ratchet.py`.

    `unresolved_stdlib_refs` is a static read of the artifact: `nm -u` against `nm -gU`, the two commands
    the bug's repro used. A `_std_` name in the undefined set and not in the defined set is exactly a
    missing export: nothing outside the dylib defines it either (the runtime's symbols are `mojo_*`, and
    libc's carry no `std` prefix in this tree's mangling)."""
    undefined = _nm_symbols(['nm', '-u', dylib])
    defined = _nm_symbols(['nm', '-g', '-U', dylib])
    return sorted(s for s in undefined
                  if s.startswith('_std_') and s not in defined)


_LOADER_C = """\
#include <dlfcn.h>
#include <stdio.h>

int main(int argc, char **argv) {
    void *h;
    if (argc != 2) {
        fprintf(stderr, "usage: %s <dylib>\\n", argv[0]);
        return 2;
    }
    h = dlopen(argv[1], RTLD_LAZY);
    if (h == 0) {
        fprintf(stderr, "%s", dlerror());
        return 1;
    }
    dlclose(h);
    return 0;
}
"""


def dylib_load_error(dylib):
    """Why the loader cannot open `dylib`, or None when it opens.

    This is the failure the job exists to catch, tested directly instead of inferred from `nm`: a
    `dlopen` with `RTLD_LAZY` — the binding a program launch uses — fails exactly when the image has an
    undefined symbol it must bind eagerly (a symbol ADDRESS in a data section: the class tables and the
    reflection table), and its `dlerror` names that symbol. A dylib that loads is usable: missing call
    targets stay lazy, and the client's source fallback supplies them.

    The probe is a separate process, built with the tree's configured compiler, so a dylib that crashes
    in a constructor or a destructor cannot take the job down with it. A probe that cannot be built or
    run RAISES: "could not check" must never read as "loads"."""
    with tempfile.TemporaryDirectory(prefix='stdlib_load_probe_') as wd:
        src = os.path.join(wd, 'load_probe.c')
        exe = os.path.join(wd, 'load_probe')
        with open(src, 'w') as f:
            f.write(_LOADER_C)
        cc = find_gcc()
        build = [cc, '-o', exe, src]
        if platform.system() != 'Darwin':
            build.append('-ldl')
        r = subprocess.run(build, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("the load probe could not be compiled: %s"
                               % ((r.stderr or r.stdout).strip()))
        r = subprocess.run([exe, dylib], capture_output=True, text=True)
        if r.returncode != 0:
            return (r.stderr or r.stdout).strip() or ("the load probe exited %d" % r.returncode)
        return None


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
        load_error = dylib_load_error(dylib)
    except RuntimeError as e:
        print("stdlib-dylib: the undefined-reference/load check could not run: %s" % e)
        return 1
    if load_error:
        print("stdlib-dylib: the built dylib FAILS TO LOAD: %s" % load_error)
        print("An undefined symbol that the image must bind EAGERLY is the fatal shape: a class table or")
        print("the reflection table stores its ADDRESS in data, so every client aborts at load.")
        if missing:
            print("`_std_` references the artifact does not define:")
            for s in missing:
                print("  U " + s)
        failed = True
    elif missing:
        # Not a failure, and not silence either: these are lazy CALL references, which the documented
        # fallback supplies from the client's own sources. The load above is the contract; the number is
        # reported so a new one is visible, and `test_stdlib_dylib_ratchet.py` pins the two shapes.
        shown = ', '.join(missing[:5])
        print("note: %d _std_ symbol(s) are referenced by the dylib's code but not defined by it "
              "(lazy call references; clients fall back to source): %s%s"
              % (len(missing), shown, ', ...' if len(missing) > 5 else ''))
    else:
        print("stdlib-dylib: the built dylib defines every _std_ symbol it references and loads cleanly")
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
