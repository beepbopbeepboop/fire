# FORMAL_an_f_string_parameter_default_is_the_raw_token: a default expression is in `param_defaults`, a DICT, so neither the fold nor the refusal walk reaches it

**Area:** `formal/model.py::fold_constant_interpolated_literals` and
`refuse_interpolated_literals` (both walk `stmts` with `iter_nodes`, which
descends into `list`/`tuple` but not into a `dict`), both backends. **Status:
OPEN, measured 2026-10-19 while fixing the unannotated-parameter default kind
bug on this branch — the f-string default was recorded there as a related,
separate root cause and is moved here so that fix could delete its own doc.**

## What I ran, and what I saw

```console
$ cat .tmp/probe/fh.mojo
def f(x=f"n={5}"):
    return x

def main():
    print(f())

$ python3 .tmp/probe/fh.mojo         # the same text as a Python script
n=5

$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove -o .tmp/probe/fh.arm64 --backend=arm64 -n 3 .tmp/probe/fh.mojo && .tmp/probe/fh.arm64
Built: .tmp/probe/fh.arm64  [arm64/macho]
f"n={5}"                            # arm64; the same token on x86-64
```

**The build exits 0 and prints the SOURCE TOKEN, not its value.** An ordinary
default (`def f(x="plain")`) is correct on both machines; this is the
interpolated-literal spelling only.

The shape moved when the parameter-default kind claim landed. Before it, the
callee was told `x` held a word, so `print(f())` rendered the literal's address
as a decimal (the previous measurement, `4365846718`). Now the default is
classified as a string and the same raw token is printed as text. Neither is
`n=5`: the defect is that the default EXPRESSION is never seen by the pass that
decides what an interpolated literal becomes.

## Why

`FunctionDef.param_defaults` is a DICT, and `iter_nodes` descends into
`list`/`tuple` but not into a `dict`. Both `refuse_interpolated_literals` and
`fold_constant_interpolated_literals` are called with the module statements, so
a default expression is not visited at all: the refusal never fires on
`f"n={5}"` and the fold never rewrites a field-less `f"n=7"`. The emitter then
materializes the literal the parser kept, which for an interpolated literal is
the whole source token (`f"n={5}"` including the prefix and quotes).

## What was expected

CPython's `n=5`. A field-less `f"n=7"` should fold to the ordinary literal
`"n=7"` and BUILD; a literal with a field should be REFUSED by name with the
interpolated-literal sentence, exactly as the same literal at a statement site
is.

## The exact next step

Teach the walk to reach `param_defaults` VALUES, which is the walker question
rather than a second pass: `iter_nodes` descends `list`/`tuple` and should
descend a `dict`'s values the way `formal/build.py::_fold_target_queries_in`
already walks `param_defaults` on purpose. If that is too wide a change for one
commit, the narrower one is to call both passes on `fn.param_defaults.values()`
for every function in `formal/build.py::_prepare_functions`, which is the same
visitor without changing `iter_nodes` for every other caller.

Add a row to `test_formal_run.py`: `def f(x=f"n=7"): return x` builds and prints
`n=7` on both architectures, and `def f(x=f"n={5}"): return x` is refused with
the interpolated-literal sentence. Corpus weight is 0 (a grep for `= f"` in a
parameter list finds none in this repository or the stdlib), which is why this is
a correctness row rather than a sweep row.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ printf 'def f(x=f"n={5}"):\n    return x\n\ndef main():\n    print(f())\n' > .tmp/fh.mojo
$ for A in arm64 x86_64; do
    python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove -o .tmp/fh.$A --backend=$A -n 3 .tmp/fh.mojo && .tmp/fh.$A
  done        # f"n={5}" on both; CPython prints n=5
```
