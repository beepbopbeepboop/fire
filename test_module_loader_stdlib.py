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


def test_call_initialized_global_export_takes_callee_return_type(tmp_path):
    """`var N = g()` exports the same C type the defining module gives its accessor.

    The defining module types a global from a same-file callee's return type
    (pointer / char* / double pass through, everything else is int64_t); the
    export table must agree, or the importer's extern disagrees with the
    accessor and gcc rejects the importing translation unit ("conflicting
    types" for the imported accessor). Regression for an imported
    call-initialized global whose export was typed void *.
    """
    src = (
        "def g():\n"
        "    return 7\n"
        "\n"
        "def h() -> Float64:\n"
        "    return 2.5\n"
        "\n"
        "def s() -> String:\n"
        "    return \"a\"\n"
        "\n"
        "var N = g()\n"
        "var F = h()\n"
        "var S = s()\n"
        "var U = missing()\n"
    )
    path = tmp_path / "xmodexp_defn.mojo"
    path.write_text(src)
    exports = module_loader._module_loader.load_module_from_path(str(path))
    got = {n: exports[n]["c_return_type"] for n in ("N", "F", "S", "U")}
    assert got == {
        "N": "int64_t",   # g() -> int: int64_t
        "F": "double",    # h() -> Float64: double
        "S": "char *",    # s() -> String: char *
        "U": "void *",    # callee not defined in this file: unchanged default
    }, got


if __name__ == '__main__':
    # This file is pytest-style (two `test_*` functions, one taking the
    # `tmp_path` fixture) and was registered as the `module-loader-stdlib` job
    # with the command `python3 test_module_loader_stdlib.py`. With no
    # `__main__`, that command ran neither test -- exit 0, zero output, a job
    # that could never fail (the no-op registered-job class).
    # suite.py has no pytest driver, so run them here, substituting a real
    # tempdir path object for `tmp_path` -- the pattern the other pytest-style
    # file in the tree uses.
    import pathlib
    import tempfile
    import traceback

    def _run(name, fn):
        try:
            fn()
        except Exception:
            traceback.print_exc()
            print('FAIL ' + name)
            return 1
        print('PASS ' + name)
        return 0

    _cases = [
        ('test_stdlib_checkout_prefers_new_modular_when_both_exist',
         lambda: test_stdlib_checkout_prefers_new_modular_when_both_exist()),
        ('test_call_initialized_global_export_takes_callee_return_type',
         lambda: test_call_initialized_global_export_takes_callee_return_type(
             pathlib.Path(tempfile.mkdtemp(prefix='xmodexp_')))),
    ]
    _failed = sum(_run(_n, _f) for _n, _f in _cases)
    if _failed:
        raise SystemExit('%d failure(s)' % _failed)
