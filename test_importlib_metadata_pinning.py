"""Pinning: importlib/metadata/__init__.py refusal mode (regression for fd909e9).
Before emission fix: six opaque g++ errors (map/filter/str/Pair/url_req_space/quoted_marker).
After: honest structural refusal, not an undeclared-identifier compile error."""

def test_importlib_metadata_refusal_is_honest():
    src = "/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py"
    from gimple_codegen import compile_to_gimple_with_cpp
    try:
        compile_to_gimple_with_cpp(mojo_src=open(src).read(), do_imports=False)
    except Exception as e:
        msg = str(e)
        assert "UnsupportedGeneratorShape" in msg or "unresolved callee" in msg or "generator function" in msg, \
            f"expected honest refusal, got: {msg[:200]}"
