# Regession pin for PERF_selfhost_memory_leak_hunt (stale doc, fixes already on tree)
# Verifies the content-key mechanism that retired the tuple-dict-leak item.

def test_tuple_dict_key_is_content_based():
    # The mechanism (mojo_dict_key_for) makes a tuple key depend on content.
    # This is the durable fix; call-site caches were removed.
    import subprocess, sys
    out = subprocess.run([sys.executable, "test_dict_tuple_key.py", "-v"],
                        capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
