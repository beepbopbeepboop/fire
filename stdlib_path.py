"""Where the Mojo stdlib source tree lives — the ONE definition of it.

This module is deliberately a LEAF: it imports `os` and nothing else from this
project. That is the whole point of it existing separately from
`module_loader`, which is where the finder used to live.

`cas.stdlib_fingerprint()` needs the stdlib path to hash "which stdlib was this
compiled against", and it used to get it with a function-scoped
`from module_loader import STDLIB_PATH`. `module_loader` is part of the
compiler's own import closure (it imports `gimple_codegen`, which imports
nearly everything), and this compiler inlines a function-scoped import's whole
module into the translation unit. So ANY compile whose closure touched `cas` —
including a four-line `import cas` snippet — inlined the entire compiler:
measured on 2026-11-21 as 123 MB of generated C and a 6.5 GB peak for
`test_gimple.py`'s `import cas` case, which is why the `gimple` job (registered
`tiny`, 4 GB) was RESOURCE-killed. A cache key that asks "which stdlib is this"
depends on a path, not on a compiler, so the path lives here and the
compiler-sized module no longer does.

`module_loader` re-exports `STDLIB_PATH` (the value it computes from
`_find_stdlib_path()` here, exactly as it did when the finder lived in that
file), and `_STDLIB_CHECKOUTS` / `_is_stdlib_root` / `_find_stdlib_path` too, so
every existing caller keeps importing them from the module it always did.
"""
import os

# The Mojo library checkouts this tree can be built against, most-preferred
# first.
_STDLIB_CHECKOUTS = (
    ('new-modular', 'Mojo/stdlib'),
    ('modular', 'mojo/stdlib'),
)


def _is_stdlib_root(path):
    """True if `path` is a Mojo stdlib root rather than some same-named dir.

    Both checkouts keep the importable package tree under `stdlib/std`, so that
    subdirectory is what distinguishes a real root from, say, a build output
    directory that happens to be called `stdlib`.
    """
    return os.path.isdir(os.path.join(path, 'std'))


def _find_stdlib_path() -> str:
    """Find stdlib path using multiple strategies.

    1. Check MOJO_STDLIB environment variable
    2. Try each known checkout location (see _STDLIB_CHECKOUTS)
    3. Search upward from current directory
    4. Return the first candidate (runtime handles a missing stdlib gracefully)
    """
    # Strategy 1: Environment variable override
    if 'MOJO_STDLIB' in os.environ:
        path = os.environ['MOJO_STDLIB']
        if os.path.isdir(path):
            return path

    # Strategy 2: Known checkout locations, most-preferred first
    for checkout, rel in _STDLIB_CHECKOUTS:
        abs_path = f'/Users/mrs/net/chatgpt/claude/{checkout}/{rel}'
        if _is_stdlib_root(abs_path):
            return abs_path

    # Strategy 3: Search upward from current working directory
    cwd = os.path.abspath(os.getcwd())
    for _ in range(10):  # Search up to 10 levels
        for checkout, rel in _STDLIB_CHECKOUTS:
            candidate = os.path.join(cwd, checkout, *rel.split('/'))
            if _is_stdlib_root(candidate):
                return candidate
        cwd = os.path.dirname(cwd)
        if cwd == '/':
            break

    # Fallback: return the preferred path (runtime will handle missing stdlib gracefully)
    return f'/Users/mrs/net/chatgpt/claude/{_STDLIB_CHECKOUTS[0][0]}/{_STDLIB_CHECKOUTS[0][1]}'
