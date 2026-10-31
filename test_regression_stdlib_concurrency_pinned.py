"""Regression: stdlib test concurrency must be pin-able (root cause of 34.9/52.2 GB spread)."""
import os, sys, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("test_stdlib", os.path.join(HERE, "test_stdlib.py"))
mod = importlib.util.module_from_spec(spec)

# Before fix: MAX_WORKERS always 20; after: respects env.
old_env = os.environ.pop("TEST_STDLIB_MAX_WORKERS", None)
try:
    # Load with default
    spec.loader.exec_module(mod)
    default = mod.MAX_WORKERS
    assert default == 20, f"default should be 20, got {default}"

    # Load with env pinned
    os.environ["TEST_STDLIB_MAX_WORKERS"] = "1"
    spec2 = importlib.util.spec_from_file_location("test_stdlib_2", os.path.join(HERE, "test_stdlib.py"))
    mod2 = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(mod2)
    pinned = mod2.MAX_WORKERS
    assert pinned == 1, f"pinned should be 1, got {pinned}"
finally:
    if old_env is not None:
        os.environ["TEST_STDLIB_MAX_WORKERS"] = old_env
    elif "TEST_STDLIB_MAX_WORKERS" in os.environ:
        del os.environ["TEST_STDLIB_MAX_WORKERS"]

print("PASS: concurrency pin-able")
