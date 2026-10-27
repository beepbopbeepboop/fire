# Regression test for bugs/CODEGEN_dylib_module_path_drops_generated_cpp.md
# The dylib path must refuse a module whose C++20 coroutine definitions
# it cannot link (generated_cpp non-empty), not silently drop them.

def test_refuses_generated_cpp():
    import sys, os
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, repo)
    from build_stdlib_dylib import compile_module_to_c, _DylibGeneratedCppError
    src = ("def deco(f):\n    return f\n\n"
           "@deco\n"
           "def gen(n):\n"
           "    for i in range(n):\n"
           "        yield i * i\n")
    raised = False
    try:
        compile_module_to_c(src, 'gen_probe.py', 'gen_probe')
    except _DylibGeneratedCppError as e:
        raised = 'gen_probe' in str(e) and 'generated_cpp' in str(e)
    assert raised, "expected _DylibGeneratedCppError for decorated generator"
    # Plain module must still compile (refusal must not cost anything here)
    plain = "def f(n):\n    return n + 1\n"
    c = compile_module_to_c(plain, 'plain_probe.py', 'plain_probe')
    assert isinstance(c, str) and len(c) > 0

if __name__ == "__main__":
    test_refuses_generated_cpp()
    print("PASS: dylib module path refuses unlinkable generated_cpp")
