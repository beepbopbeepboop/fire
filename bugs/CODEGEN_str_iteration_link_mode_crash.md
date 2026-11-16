# CODEGEN: iterating a `str` in compiled code crashes (param) or yields byte ints plus a sentinel (literal)

## Status 2026-11-16 — measured while landing the cpp-generator string-ordering fix; not fixed here

Found while probing whether `<` between a character read (`s[i]`) and a string
literal reaches `cpp_core._cpp_str_compare`'s one-`char *`-against-an-undecided-
word arm. The ordering lowering does not run there because the program dies
first; both shapes below are independent of that change (the crashing one has
no comparison at all).

## What to run

```sh
python3 tools/memslot.py --gb 8 --label repro-str-iter -- python3 - <<'EOF'
import os, shutil, sys, tempfile
sys.path.insert(0, os.getcwd())
import test_link_mode as T

pkg = {
    'gm/__init__.py': '',
    'gm/mod.py': (
        'def counter(s):\n'
        '    n = 0\n'
        '    for c in s:\n'
        '        n += 1\n'
        '    return n\n'),
    'gm/main.py': (
        'from gm.mod import counter\n'
        '\n'
        'def main():\n'
        '    print(counter("abc"))\n'
        'main()\n'),
}
root = os.path.join(os.getcwd(), 'build', 'test_link_mode')
os.makedirs(root, exist_ok=True)
td = tempfile.mkdtemp(prefix='repro_str_iter_', dir=root)
try:
    rc, out = T._build_and_run(pkg, 'gm/main.py', td)
    py_rc, py_out = T._cpython_run(td, 'gm/main.py')
finally:
    shutil.rmtree(td, ignore_errors=True)
print('rc', rc, 'stdout', repr(out), '| cpython', repr(py_out))
EOF
```

Package A above is the crashing one (plain imported function, no generator, no
comparison; CPython prints `3`). Package B swaps the body for a loop over a
literal in a cpp-path generator (`import csv` + `_get_reader=csv.reader` default
makes it eligible):

```python
def letters(*, sep=",", _get_reader=csv.reader):
    for c in "abc":
        yield c
```

Package C is B with the literal replaced by the generator's own `str` parameter.

## What was seen

```
plain_function:    rc=-11 compiled=''                    cpython='3\n'
generator_literal: rc=0   compiled='[97, 98, 99, 0]\n'    cpython="['a', 'b', 'c']\n"
generator_param:   rc=-11 compiled=''                    cpython="['a', 'b', 'c']\n"
```

- A and C build and then SIGSEGV (rc -11) before printing anything.
- B runs, but `list(letters())` is four INTEGERS with a trailing `0` — not the
  three one-character strings CPython yields.

The emitted GIMPLE for A is the ordinary string-iteration lowering, which looks
right on inspection:

```
_t1 = mojo_strlen (s);            /* 3 */
...
c = mojo_char_at_str_cp (s, _t2);
```

so the crash is downstream of the loop shape (the imported-module/dylib call
path or `mojo_char_to_str`'s static table), not a wrong source lowering.

## Expected

`for c in s` binds each character as a one-character `str`: A prints `3`, B/C
print `['a', 'b', 'c']`.

## Exact next step

Start from A (no generator, no cpp path, no comparison — `counter("abc")`), so
the crash is the smallest possible case. Compile it with
`python3 fire.py build`, then (a) run it under lldb to get the faulting frame —
if it lands in `mojo_char_to_str` / `_mojo_char_tbl`, the static 1-char table is
per-dylib and an imported module returns a pointer into a different image's
table; (b) `objdump -d` the `counter_d719e0` body and check whether the call to
`mojo_char_at_str_cp` goes through the module table (`0 misresolved` in the
export-table line) or calls a stripped stub. For B, dump the cpp unit
(`compile_to_gimple_with_cpp` on the generator) and look at how the `for` over a
literal is lowered — integers plus a trailing `0` means the literal was taken as
a byte container and the loop bound read one past its length.
