"""Shared file discovery for the aside/bside A/B dump-compare harness
(tools/ab_run_one.py, tools/gen_ab_makefile.py, tools/ab_compare.py).

Single source of truth for "which files get A/B-tested" and "what key
identifies each one" so the Makefile generator and the comparator can
never disagree about the file set.
"""
import os
import sys
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Same stdlib subtree convention as compile_stdlib.py's DEFAULT_ROOTS, so
# this harness's coverage matches what that gate already considers "the
# stdlib" — just .mojo files there (no .py in stdlib), vs this repo's own
# top-level .py sources (the compiler's own source + its test scripts).
STDLIB_ROOTS = ['benchmarks', 'std', 'test', 'tools', '_core', 'collections',
                'io', 'math', 'os']


def stdlib_path():
    sys.path.insert(0, REPO)
    from module_loader import STDLIB_PATH
    return STDLIB_PATH


def discover():
    """Yield (key, abs_path) for every file this harness A/B-tests.

    `key` is a stable, slash-separated, extension-free identifier used to
    mirror the source tree under aside/<key>.ci and bside/<key>.ci (mojo.py
    --dump names its outputs after the input's own basename, so the key's
    last path component doubles as that basename).
    """
    for name in sorted(os.listdir(REPO)):
        full = os.path.join(REPO, name)
        if name.endswith('.py') and os.path.isfile(full):
            yield (f"root/{name[:-3]}", full)

    sp = Path(stdlib_path())
    if sp.exists():
        for root in STDLIB_ROOTS:
            search_root = sp / root
            if not search_root.exists():
                continue
            for mojo_file in sorted(search_root.rglob('*.mojo')):
                rel = mojo_file.relative_to(sp).with_suffix('')
                yield (f"stdlib/{rel.as_posix()}", str(mojo_file))


if __name__ == '__main__':
    n = 0
    for key, path in discover():
        print(f"{key}\t{path}")
        n += 1
    print(f"# {n} files", file=sys.stderr)
