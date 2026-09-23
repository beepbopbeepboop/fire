"""Compatibility shim - implementation moved to `mojo.middle.solvers`.

`import gimple_solvers` and `from gimple_solvers import ...` keep working.
Prefer `mojo.middle.solvers` in new code.
"""

# Re-export implementation from mojo.middle.solvers (self-hosted globals() is a weak stub).
from mojo.middle.solvers import *  # noqa: F401,F403
from mojo.middle.solvers import _C_RESERVED_FUNCS, _find_escaping, _find_idents, _scan_for_escaping
