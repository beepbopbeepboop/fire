"""Compatibility shim - implementation moved to `mojo.backend_gimple.spec_gen`.

`import gimple_spec_gen` and `from gimple_spec_gen import ...` keep working.
Prefer `mojo.backend_gimple.spec_gen` in new code.
"""

# Re-export implementation from mojo.backend_gimple.spec_gen (self-hosted globals() is a weak stub).
from mojo.backend_gimple.spec_gen import *  # noqa: F401,F403
