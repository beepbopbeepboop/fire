"""The one host-module failure convention (hoststatus).

There are no exceptions on this path (FORMAL.md phase 7). A function that
can fail returns a status: 0 on success, -1 on failure. Use
`status_ok()` / `status_err()` rather than writing `0` / `0 - 1` by hand so
the rule is discoverable and greppable (hoststatus.mojo). Predicates (`json.valid`, path tests)
return 1/0 and are NOT statuses. A "kind or none" sentinel uses
`status_err()` for the "none" case only when CPython would fail or when the
value is absent by the API's contract. The rule is that failure is a return
value, never a raised exception: a `raise` on this path terminates the process.
"""

def status_ok() -> int:
    """The success status: 0. Failure on this path is a return value (see the module docstring)."""
    return 0


def status_err() -> int:
    """The failure status: -1. Failure on this path is a return value (see the module docstring)."""
    return 0 - 1
