# COMPILE_FAIL (hard): Tools/clinic/clinic.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/clinic/clinic.py`

Root cause: see `CODEGEN_aliased_external_import_no_backing_symbol.md` in
this directory (that file has the minimal test case). Summary: `from
libclinic.cli import main` imports from an external/unmodeled package
(`libclinic`); `load_module()` can't resolve it, so `main`'s call site has
no real C symbol to call, and the auto-stub declaration for the bare name
`main` collides with this program's own synthesized `int main(int,
char**)`.

Originally reported (and previously misdiagnosed) as "conflicting types for
'_gimple_main'" — that specific bogus diagnostic was fixed by commit
12ff719 (this call site is no longer wrongly redirected to the synthesized
entry point). The file still doesn't compile, now for the legitimate,
deeper reason above.

## Current error (2026-08-05, after commit 12ff719)

```
$ python3 mojo.py build Tools/clinic/clinic.py
...
/Users/mrs/net/Python-3.14.6/Tools/clinic/clinic.py:22:5: error: conflicting types for 'main'; have 'int(int, const char **)'
/Users/mrs/net/Python-3.14.6/Tools/clinic/clinic.py:342:9: note: previous declaration of 'main' with type 'int64_t()' {aka 'long long int()'}
```

Exit code: 1. No object file produced.

The relevant source (`clinic.py`):

```python
from libclinic.cli import main

if __name__ == "__main__":
    main()
```
