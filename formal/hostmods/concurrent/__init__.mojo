"""`concurrent` — the package, and the two futures executors with the pool admitted.

`import concurrent` is the package and answers no name of its own: CPython's
`concurrent` is a namespace with `futures` and `futures.interrupt` and
`futures.process` under it, and `dir(concurrent)` on this tree's CPython 3.14.6
is `['futures']` after the submodules are imported.  So this file exists to make
the package resolvable and exports nothing, which is why it declares no admitted
contract and the module census counts it as zero -- a zero is a measurement, not
an absence, and `formal/admitted.py`'s `counts_by_module` reports both.

The work is in `formal/hostmods/concurrent/futures.mojo`, which is the module the
thirteen files that say `from concurrent.futures import …` actually import.
"""

def concurrent_futures_package() -> int:
    """The package marker, so this file exports something rather than nothing.

    A `.mojo` module with no declarations is refused by `formal/build.py`'s dylib
    export gate -- "formal dylib has no public functions", the message that
    `bugs/FORMAL_known_limits.md` §1.1 audits -- and a file importing `concurrent`
    would then be refused for a package that in CPython binds no name either.  One
    function is the cheapest thing that makes the module a module, and it is named
    after what it is rather than invented: a caller who wants `concurrent.futures`
    imports that, and this one exists so `import concurrent` resolves.
    """
    return 1
