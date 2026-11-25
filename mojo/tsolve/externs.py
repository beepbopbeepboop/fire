"""Facts about EXTERNAL modules: what the functions and attributes the closure calls return.

bugs/GIR_type_solver_precision.md, 4.2a. An external module (one the loader does not resolve,
`os`, `json`, ...) is not an unknown object: its names have the types CPython gives them.
Each row states a fact about CPython, and `test_tsolve.py` checks every callable row against
CPython on sample arguments, so a wrong row cannot pass silently (risk R4).

Keys are dotted names as the source spells them after the module alias is resolved
(`os.path.join` for `import os` then `os.path.join(...)`, or `from os.path import join`).
Values are annotation text for `sty.from_annotation`.

Plain dicts only: this module is compiled by the closure (doc/GIR.md rule 2).
"""

FUNCS = {
    'os.path.basename': 'str',
    'os.path.dirname': 'str',
    'os.path.join': 'str',
    'os.path.abspath': 'str',
    'os.path.normpath': 'str',
    'os.path.splitext': 'tuple[str, str]',
    'os.path.split': 'tuple[str, str]',
    'os.path.exists': 'bool',
    'os.path.isfile': 'bool',
    'os.path.isdir': 'bool',
    'os.getcwd': 'str',
    'json.dumps': 'str',
    'textwrap.dedent': 'str',
    'textwrap.indent': 'str',
    'shlex.quote': 'str',
    'math.floor': 'int',
    'math.ceil': 'int',
    'math.sqrt': 'float',
}

ATTRS = {
    'os.sep': 'str',
    'os.path.sep': 'str',
    'os.environ': 'dict[str, str]',
}

# Names the AST rewriter (`ast_rewriter.py`) introduces, with their contracts. `os.environ.get(k, d)`
# is rewritten to `mojo_c_getenv(k)` guarded by a `not not` ternary, so these are not CPython
# facts and are not checked against it: `mojo_c_getenv` is the runtime's getenv, `str | None`.
INTERNAL = {
    'mojo_c_getenv': 'str | None',
}
