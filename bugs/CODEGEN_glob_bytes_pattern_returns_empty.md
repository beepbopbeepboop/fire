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

## Next step

Measure which call in that chain first loses the bytes (print the intermediate values in a
single-module copy of glob.py, as the str path was debugged), then give the run-time
`re` a bytes entry (`mojo_re_compile`/`mojo_re_exec` over a `MojoBytes *`'s data and length).
The test to turn green is a bytes line added to `test_glob_compiled.py`'s driver.
