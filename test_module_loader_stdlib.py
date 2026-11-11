import os

import module_loader


def test_stdlib_checkout_prefers_new_modular_when_both_exist():
    """New-modular stdlib is the current target; prefer it over the old modular checkout.

    Regression for BUILD_link_errors_modular: using the wrong stdlib checkout
    can produce ABI/symbol mismatches that surface as link errors in modular
    test builds.
    """
    old_env = os.environ.get("MOJO_STDLIB")
    try:
        os.environ.pop("MOJO_STDLIB", None)
        # Simulate both checkouts being present by checking the preference order
        # in the source-of-truth constant used by _find_stdlib_path().
        names = [c[0] for c in module_loader._STDLIB_CHECKOUTS]
        assert names[:2] == ["new-modular", "modular"], names
        # If the new-modular checkout exists on this machine, it must be selected.
        new_mod = "/Users/mrs/net/chatgpt/claude/new-modular/Mojo/stdlib"
        if os.path.isdir(os.path.join(new_mod, "std")):
            found = module_loader._find_stdlib_path()
            assert os.path.realpath(found) == os.path.realpath(new_mod), found
    finally:
        if old_env is None:
            os.environ.pop("MOJO_STDLIB", None)
        else:
            os.environ["MOJO_STDLIB"] = old_env
