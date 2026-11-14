# COMPILE_FAIL: a consumer program importing `c_common/tables.py` fails to link (`_mojogen_*` undefined)

## Status 2026-11-13 — measured, not fixed

Building `c_common/tables.py` itself now succeeds (see
`bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md`'s 2026-11-13 part-1
entry: `fire.py build -o .tmp/ca/tables_out .tmp/ca/c_common/tables.py` exits
0 and the binary exits 0). A **consumer program** that imports it still fails
at LINK, so the module is not actually usable from a program yet.

### What was run

Sources copied from `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/` into
`.tmp/ca/` (the standard `c-analyzer` tree), plus:

```sh
# .tmp/ca/data.tsv = "a\tb\n1\t2\n3\t4\n"
cat > .tmp/ca/_check_rt.py <<'EOF'
from c_common.tables import read_table

def main():
    for row in read_table('data.tsv', 'a\tb'):
        print(row)
main()
EOF
cd .tmp/ca && python3 ../../fire.py build -o _check_rt _check_rt.py
```

### What was seen

Linking fails with `Undefined symbols for architecture arm64` for exactly the
module's compiled-generator symbols:

```
  "__mojogen_c_common_tables__fix_read_default_resume",
  "__mojogen_c_common_tables__fix_read_default_start",
  "__mojogen_c_common_tables__fix_read_default_value",
  "__mojogen_c_common_tables__fix_write_default_start",   # only when write_table is imported too
  "__mojogen_c_common_tables_read_table_destroy",
  "__mojogen_c_common_tables_read_table_resume",
  "__mojogen_c_common_tables_read_table_start",
  "__mojogen_c_common_tables_read_table_value",
```

Ordinary functions from the same module resolve, so the module's `.o` is
linked; only its C++ generator translation unit is missing.

`MOJO_DEBUG=1` prints the reason (twice, once per pass):

```
[gimple_codegen] failed to compile link-mode inline-module cpp unit: Command
['g++-mp-15', '-std=c++20', '-fPIC', '-I<tree>/runtime', '-c', '-o',
'.tmp/mojo_linkmod_cpp_XXXX/link_inline_module.o',
'.tmp/mojo_linkmod_cpp_XXXX/link_inline_module.cpp'] returned non-zero exit status 1.
```

`emit_infra._compile_link_inline_cpp_unit` swallows g++'s stderr; the `.cpp`
is left behind in `.tmp/mojo_linkmod_cpp_XXXX/`, so compiling it by hand shows
the real error:

```
link_inline_module.cpp:378:22: error: invalid conversion from 'int64_t'
  {aka 'long long int'} to 'char*' [-fpermissive]
  378 |  infile = (int64_t)mojo_open_file_ex((char *)(infile), (char *)("r"), (char *)(""));
```

inside `_mojogen_c_common_tables_read_table_impl(char*, char*, char*, int64_t,
int64_t, int64_t)` — i.e. in the imported-module compile `read_table`'s
`infile` parameter is typed **`char *`**, so the with-open arm's
`(int64_t)mojo_open_file_ex(...)` assignment (`cpp_core._cpp_with_stmt`, the
`_open_manager and _open_alias_name is not None` branch, cpp_core.py:9062)
does not type-check.

In the ROOT build of the same file the same statement does compile, because
there `infile` is inferred as the `int64_t` word (the `isinstance(infile, str)`
evidence path in `cpp_async._gen_cpp_generator_unit`'s parameter-ctype loop,
which consults `coro_mod._PTR_EVIDENCE[fn.name]`). So the parameter ctype —
`char *` vs the word — differs between "compiled as the root file" and
"compiled as a transitive import", and only the imported spelling reaches the
bad statement.

### What was expected

The consumer program builds, links and prints `('1', '2')` / `('3', '4')`
(CPython's answer), exactly as `c_common/iterutil.iter_many`,
`c_common/strutil.parse_entries` and trivial cross-package cpp generators
already do on this tree (all three were measured to link and run).

### Exact next step

Two separable defects, in this order:

1. **The type divergence.** Compare `coro_mod._PTR_EVIDENCE.get('read_table')`
   in the root compile of `.tmp/ca/c_common/tables.py` against the
   `_compile_imported_module` temp_gen compile of it. The evidence scan that
   turns `isinstance(infile, str)` into "this parameter is the word" clearly
   runs for the root but not for the import; make it a property of the parsed
   module (e.g. populated where the module's statements are registered) rather
   than of whichever gen happened to be the root.
2. **The swallowed diagnostic.** `_compile_link_inline_cpp_unit` returns
   `None` on a g++ failure and only files a `_debug_note` that does not
   include the compiler's stderr. Pass `capture_output=True, check=False` and
   raise/report the stderr (the function is already CAS-cached; the failing
   text is right there in `<tmp>/mojo_linkmod_cpp_*`), so this class of failure
   names itself instead of surfacing 8 lines later as undefined symbols.

Do NOT "fix" #1 by casting the assignment to the local's declared type inside
the with-open arm: after `with _open(...) as infile:` the local must hold the
runtime's file WORD (`mojo_close((void *)(intptr_t)(infile))` and iteration
both read it that way), so re-typing the parameter as `char *` would make the
body wrong even if the cast compiled.

### Verification for the fix

```sh
cd .tmp/ca && python3 ../../fire.py build -o _check_rt _check_rt.py && ./_check_rt
```

must print the two rows and exit 0; then `python3
test_gimple_generator_runner.py` (the cpp generator file) must still be green.
