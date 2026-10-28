"""Regression for INFRA: bare python3 <3.12 gives opaque TypeError on import.
Before fix: TypeError propagated raw; after: clear ImportError with floor msg."""
import importlib, sys

# Import the module-to-test by importing fire.py (it defines _load_formal_build)
import fire as _fire


def test_load_formal_build_turns_typeerror_into_legible_importerror():
    """_load_formal_build must turn PEP 604 TypeError into ImportError."""
    real = importlib.import_module

    def bad(name):
        if name == 'formal.build':
            raise TypeError("unsupported operand type(s) for |: 'type' and 'NoneType'")
        return real(name)

    importlib.import_module = bad
    try:
        try:
            _fire._load_formal_build()
        except ImportError as e:
            msg = str(e)
            assert "Python 3.12+" in msg, f"missing floor note: {msg}"
            assert "TypeError" in msg, f"missing cause: {msg}"
            return  # pass
        raise AssertionError("expected ImportError, got nothing")
    finally:
        importlib.import_module = real


if __name__ == "__main__":
    test_load_formal_build_turns_typeerror_into_legible_importerror()
    print("test_infra_py_version_fallback PASS")
