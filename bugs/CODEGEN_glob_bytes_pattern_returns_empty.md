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

## Round 3 (2026-11-01): root cause isolated; plan; runtime infrastructure landed

### Root cause for line 8 (read from the generated GIMPLE and the runtime, not guessed)

`glob._iglob` in the compiled program is GIMPLE-emitted. Its first statement lowers to:

    _t14 = mojo_cstr_or_int_str (pathname);     // pathname is a bytes WORD
    _t13 = int64_t_path_split (_t14);

`mojo_cstr_or_int_str` (`runtime/fire_runtime.c`, ~line 12956) answers a registered bytes
object with `mojo_bytes_repr`, i.e. the TEXT `b'*.py'`. So `os.path.split` splits
`"b'*.py'"`: dirname `''`, basename `"b'*.py'"`. `_glob1` then matches that text against the
names, finds nothing, and `glob.glob` returns `[]`. A direct `yield from glob._glob1(root, b'*.py', ...)`
yields one element (count measured; the element's contents were not printed correctly in that
probe), so the earlier "yield from kind" hypothesis is not the cause of the empty result.

The same coercion is likely wherever a word is passed to a `char *` parameter. The GIMPLE of
the module shows `glob__join_1b532c (char *, char *)`, and its body is `mojo_truthy_cstr` plus
`int_join` (the str join), so `_join`'s bytes arguments arrive typed as `char *`. Whether
each call site coerces through `mojo_cstr_or_int_str` was NOT checked on this round (the kept
scratch was lost); step 3 below must check it.

A second, separate defect: `cpp_core.py` (the C++ coroutine emitter) has no `os.path.split`
arm, so a generator it emits lowers the split to `0.split(...)` and every unpacked target to
`0`. See `CODEGEN_coroutine_os_path_split_lowers_to_zero.md`.

Also observed (not isolated): a bytes word printed through `.decode()` inside a generator
printed as a pointer, and `yield d` of a bytes part printed garbage. Whether that is the same
`char *` coercion is not established.

### What landed this round

- `runtime/fire_runtime.c` / `.h`: `mojo_os_path_split_w(int64_t)` (a word-kinded split: a
  bytes word gives two bytes parts, a str word the existing str pair), `mojo_os_path_join_w`
  now bytes-aware (bytes+bytes is a bytes join; mixing str and bytes raises the CPython
  `TypeError`), and `mojo_truthy_word` answers a bytes word by its length. **Infrastructure:
  no lowering calls these yet.** Verified by `test_path_word_runtime.py`, which compiles a C
  harness against the real `fire_runtime.c` and requires every line to equal CPython's
  `posixpath` for the same inputs. On `HEAD` that test does not build (`mojo_os_path_split_w`
  is undefined), so it fails before the change and passes after.
- `test_regress_glob_bytes_pattern.py` removed. It was `sys.exit(0 if 'PASS' else 1)`, which
  always exits 0, so it pinned nothing.
- `test_glob_bytes_regress.py` unchanged; it still passes on this tree.

### Next step (the implementation plan, in order)

1. **GIMPLE `os.path` lowering for word arguments.** In `mojo/backend_gimple/emit_methods.py`,
   the `os.path.split` arm (~line 2526) and the `join` arm: when the argument's C type is
   `int64_t` (a word), call `mojo_os_path_split_w((int64_t)arg)` / `mojo_os_path_join_w(...)`
   and do NOT pass the argument through `mojo_cstr_or_int_str`. Keep `int64_t_path_split` for a
   `char *` argument. Element type of the result: `int64_t` (raw word), read with
   `mojo_list_get_int`.
2. **The kind of the split elements.** `mojo/middle/coro.py` `_OS_PATH_PAIR_FNS` (~line 597)
   marks every unpacked element of `os.path.split` as `'p'` (str). It must be `'w'` when the
   argument's kind is `'w'`, so that `not dirname` is `mojo_truthy_word` (length for bytes),
   not `strlen`.
3. **Word parameters.** `glob._join(char *, char *)` and `_iglob`'s `pathname`/`root_dir`
   are typed `char *`/word by the call-site scan (`_scan_callsite_param_kinds`). A parameter
   that receives a bytes value at ANY call site (the driver passes `root_dir=ROOT.encode()`)
   must be a word, not `char *`. Check the generated `glob__join_*` signature in the kept
   `.ci` after the change.
4. **`join` yield kind.** A yield of `os.path.join(dirname, name)` must be `'w'` when an
   argument is `'w'` (`coro.py` `_yield_kind`). This was drafted and reverted unverified; re-add
   it with step 1.
5. **Quick test.** Extend `test_glob_bytes_regress.py` with these lines (they are the probe
   that fails on this tree and on `HEAD`):

       def split_pair(p):
           d, b = os.path.split(p)
           return [d, b]
       print(split_pair(b'a/b.py'))     # CPython [b'a', b'b.py']
       print(split_pair(b'*.py'))       # CPython [b'', b'*.py']
       print([os.path.join(b'/tmp', b'x')])   # CPython [b'/tmp/x']
       print(glob.glob(b'*.py', root_dir=ROOT.encode()))   # CPython [b'a.py']

   Measured on this tree: `split_pair` prints str garbage (`['', '��7...']`), the join prints
   garbage, `glob.glob` prints `[]`. These lines need `glob.py` copied as a sibling (already
   done in that test). `test_glob_compiled.py` line 8 is the end-to-end pin.
6. When line 8 is green, delete this doc in that commit and run
   `python3 tools/dangling_doc_refs.py --ratchet`.

### Known pre-existing failure on the same probe (not a regression)

A driver that calls `collect(glob._iglob(b'*.py', root, None, False, False, False))` after
a `yield` generator bus-errors (`mojo_list_get_int` on a bad pointer, lldb). `HEAD` does the
same, so it is not from this round. It is most likely the same `char *` coercion, reached in
the generator's list result; step 1-3 should remove it, and it must be re-checked then.
