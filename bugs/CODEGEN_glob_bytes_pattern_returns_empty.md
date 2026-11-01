# CODEGEN: `glob.glob(b'/path/*.py')` (a BYTES pattern) returns `[]` in a compiled program

## Symptom (measured 2026-10-31)

CPython 3.15's `glob.py` + `fnmatch.py` compiled as sibling modules (see
`test_glob_compiled.py`, which pins the str API line by line against CPython) answer every
str pattern identically to CPython - literal, `*`, `?`, `**`, `root_dir=`. The same call with
a bytes pattern:

    glob.glob(b'/tmp/tree/*.py')     # CPython: [b'/tmp/tree/a.py']   compiled: []

## Where it goes wrong (not yet traced)

`glob._iterdir` / `_glob1` take a bytes `dirname`, `os.fsencode` each `entry.name`, build
a `bytes` regex (`fnmatch._compile_pattern` -> `translate(str(pat, 'ISO-8859-1'))` ->
`bytes(res_str, 'ISO-8859-1')`) and match bytes names against it. In the compiled program a
bytes value is a registered `MojoBytes *` where a str is a `char *`, and each step of
that chain needs the bytes arm: `os.scandir(bytes)`, `fsencode`, `re.compile(bytes)` (the
run-time engine, `runtime/fire_re_engine.inc`, compiles patterns from `char *` only), and
`.match(bytes)`.

## Status (2026-11-01)

- Added bytes regression line to `test_glob_compiled.py`: `glob.glob(b'*.py', root_dir=ROOT.encode())`.
- Runtime `mojo_re_compile_bytes` / `mojo_re_exec_bytes` present in `runtime/fire_runtime.c`; `fre_compile_bytes` / `fre_exec_bytes` present in `runtime/fire_re_engine.inc`; codegen (`emit_methods.py`, `gimple_codegen.py`) emits bytes passes.
- `os.scandir` bytes arm (`scandir_bytes`) and `fsencode` bytes arm still missing from runtime — unverified whether those are also needed for full `glob.glob(b'...')`.
- Full end-to-end compile verification of `test_glob_compiled.py` + the bytes line still needed (compile ~30s per attempt; skipped per light-worker rule, integrator gates).

## Next step

Run `test_glob_compiled.py` with the bytes driver line under `python3 tools/memslot.py --gb 8 --label glob-bytes --` and confirm output matches CPython; if green, `git rm` doc and run `python3 tools/dangling_doc_refs.py --ratchet`. If red, trace which chain step (`scandir`, `fsencode`, `re.compile`, `.match`) first loses bytes.
