# formal-runtime-link: a declared callable-table global is reported as a headerless export

**Job:** `formal-runtime-link` (`test_formal_runtime_link.py`), not in the `gate`
bucket (it is registered in `proofs` only), so the full gate does not run it.

## What I ran

```
python3 tools/memslot.py --gb 8 --label formal-runtime-link -- \
  python3 -c "import test_formal_runtime_link as t; t.test_link_line_is_the_dylibs_exports()"
```

(`python3 test_formal_runtime_link.py` runs the same case through `main()`.)

## What I saw

The arm64 and x86_64 runs each fail this check:

```
FAIL  arm64: the set of names exported with no header declarations is as expected
      (header gap closed for others): ['MojoParser', 'Python', 'PythonObject',
      'compile_to_gimple', 'int64_t_as_unsafe_any_origin', 'mojo_csv_reader_w',
      'note_list_literal', 'scan_expr']
FAIL  x86_64: ... the same list
```

Everything else in that case passes, including the §6 phase-2 word/exported/
reachable rows after their census refresh (428 / 372 / 325 on both arches).

## Why it is wrong, and where

`runtime/fire_runtime.h:2691` **does** declare it:

```c
extern void *mojo_csv_reader_w;
```

`test_formal_runtime_link.py:507` compares the dylib's export table against
`runtime_abi()`, which scans function declarations only, so a declared *global*
is on the exported side and not the ABI side and is reported as undeclared.
Commit `7e6a8ac5c` added this global as the vararg callable-table word for
`csv.reader` (`mojo/middle/calls_shared.py:452`,
`mojo/backend_gimple/cpp_async.py:1600`); the fixed `expected_extra` list in the
test predates it.

## Exact next step

Decide which side is the truth and make the test say it:

- preferred: compare the export table against function declarations **and**
  declared globals (the scanner can collect `extern` data declarations too), so
  a future callable-table global does not regress the check; or
- narrowly: add `'mojo_csv_reader_w'` to `expected_extra` at
  `test_formal_runtime_link.py:507` with a comment saying it is a declared
  `extern void *` callable-table word that `runtime_abi()` deliberately does not
  list.

Then run the case above on both architectures and confirm 0 failures in
`test_link_line_is_the_dylibs_exports`.

## Done when

`python3 test_formal_runtime_link.py` reports 0 failures (or at minimum the
`test_link_line_is_the_dylibs_exports` case has none on either architecture).
