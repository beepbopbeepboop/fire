# CODEGEN: `glob.glob(b'/path/*.py')` (a BYTES pattern) returns `[]` in a compiled program

## Symptom (measured 2026-10-31)

CPython 3.15's `glob.py` + `fnmatch.py` compiled as sibling modules (see
`test_glob_compiled.py`, which pins the str API line by line against CPython) answer every
str pattern identically to CPython. The same call with a bytes pattern:

    glob.glob(b'/tmp/tree/*.py')                    # CPython: [b'/tmp/tree/a.py']   compiled: []
    glob.glob(b'*.py', root_dir=ROOT.encode())      # CPython: [b'a.py']            compiled: []

`test_glob_compiled.py` line 8 is the second spelling and is still RED.

## Status (2026-11-01): partial fix landed; the bytes line is still red

Landed on `work/bug-codegen-glob-bytes-pattern-returns-e-1280`. Each item was measured with a
small compiled probe (`fire.py build`, run, compared with CPython):

- **`os.scandir(bytes)`** used to read the `MojoBytes *` as a `char *` (a garbage path, then
  `FileNotFoundError: '�'`). `mojo_os_scandir` now detects a registered bytes path and builds
  bytes entries; `DirEntry.name`/`.path` are runtime-kinded words (`mojo_dirent_name` /
  `mojo_dirent_path` return a str or a bytes object). Codegen types them `'w'`
  (`coro.py`, `exprtypes.py`, `cpp_core.py`'s return-ctype table).
- **`os.fsencode(x)`** on a str OR bytes word: new `mojo_fsencode_w` (bytes pass through, str is
  encoded). It was `mojo_bytes_from_cstr`, which assumed a str.
- **Bytes regex, three bugs:**
  - `mojo_re_compile_bytes` / `mojo_re_exec_bytes` took `void *` and the codegen passed the
    `MojoBytes *` object, so the engine read the struct's `data` pointer as the pattern text.
    They now take the bytes OBJECT (`gimple_codegen.py` prototypes, `emit_methods.py` call sites
    and `fire_runtime.h` updated).
  - `pattern.match(bytes_subject)` went through `mojo_re_call`, which read the subject as a
    `char *`. The str entry points `mojo_re_compile` / `mojo_re_exec` now dispatch to the bytes
    engine on the object's kind, so a value of unknown static type (fnmatch's
    `res = bytes(...)`) is also right.
- **`str(bytes, encoding)`** lowered to `_stringify_value`, i.e. the repr `b'...'`, so
  `fnmatch.translate(str(pat, 'ISO-8859-1'))` produced `(?s:b'.*\.py')\z`. A statically bytes
  argument now goes to `mojo_bytes_decode`; an unknown-kind word goes to the new
  `mojo_str_from_word`.
- **A bytes object in a list** was recorded as an INTEGER slot, so `print([b'a'])` showed an
  address. `mojo_list_append_word` now records it under `MOJO_KIND_BYTES` (`'s'`), and boxes of
  that kind are kept as `'s'` too. `print([b'a', b'b'])` and `fnmatch.filter` output now print
  correctly.

Tests: `test_glob_bytes_regress.py` (extended with a bytes `os.scandir` generator, a bytes
`re.match` and a bytes `fnmatch.fnmatch`; it now also fails loudly if the driver does not run
under CPython or the binary exits non-zero) PASSES. Before this round the same file's
`fnmatch.translate(b'*.py')` line raised in CPython 3.15 itself, so it could never have been a
valid pin, and it did not compile `fnmatch` as a sibling.

`test_glob_compiled.py` (end to end, 2m30s under `memslot --gb 8`): every line matches CPython
except line 8 (`glob.glob(b'*.py', root_dir=...)` -> `[]`).

## Remaining (what makes line 8 red), measured on this tree

Every helper the glob chain calls, probed separately:

| step | CPython | compiled | note |
|---|---|---|---|
| `glob._listdir(b'<root>', None, False)` | `[b'a.py']` | len 1 | ok |
| `glob._glob1(b'<root>', b'*.py', None, False)` | `[b'a.py']` | len 1 | ok |
| `glob._iglob(b'*.py', root, None, False, False, False)` | `[b'a.py']` | 0 items | **the failing step** |
| `glob.glob(...)` / `glob.iglob(...)` | `[b'a.py']` | `[]` | follow from `_iglob` |
| `os.path.split(b'a/b.py')[0]` length | 1 | 0 | see `CODEGEN_bytes_os_path_and_word_len_are_str_only.md` |
| `os.path.join(b'/tmp', b'x')` | `b'/tmp/x'` | len 11 | same doc |

`_iglob`'s bytes-empty-dirname branch is `if not dirname: yield from _glob1(root_dir, basename, ...)`.
`not dirname` on an empty bytes is correct (measured) and `_glob1` called directly is correct, so
the defect is between them: the `yield from` of a bytes list inside the generator, or the
dispatch of that `yield from`. Not yet isolated.

## Next step

1. Isolate `_iglob` with a probe: a generator `def g(): yield from glob._glob1(root, b'*.py', None, False, False)`
   (no `os.path` call) versus the real `_iglob`. If the `yield from` drops the bytes list, the
   fix is in the generator's yield-kind for a `yield from` of a word list (`coro.py`'s
   `_generator_value_kind` / `YieldFromExpr`).
2. The `os.path.split` / `os.path.join` bytes gap is its own doc; `_iglob`'s final
   `yield os.path.join(dirname, name)` reaches it only when `dirname` is non-empty, so it is not
   the reason line 8 is empty, but it blocks `glob.glob(b'sub/*.py', root_dir=...)`.
3. When line 8 is green, `test_glob_compiled.py` is green. Delete this doc in that commit and run
   `python3 tools/dangling_doc_refs.py --ratchet`.
