# Compiled mode stubs argparse, so every `parse_args()` consumer crashes

## What was run

```sh
python3 fire.py build /Users/mrs/net/Python-3.14.6/Apple/__main__.py && ./__main__ --help
```

## What was seen

The file now **compiles, links and starts** (the COMPILE_FAIL doc for it is
retired — see `bugs/` history; `fire.py build` exits 0 and the binary reaches
`main()`). It then dies:

```
Unhandled exception: AttributeError: cross_build_dir
rc=0
```

CPython's own `python3 Apple/__main__.py --help` prints usage and exits 0.

## What was expected

`--help` prints argparse's generated usage text.

## Root cause

`argparse` is never compiled into the binary. It degrades to the opaque-ctor
passthrough of a module marker (int64_t 0), so `ArgumentParser(...)`
constructs nothing, every method (`add_subparsers` / `add_parser` /
`add_argument` / `parse_args`) is an `int64_t.X() stubbed` passthrough
returning its receiver, `parse_args()` returns 0, and the first attribute read
off that result is the crash.

There is no escape hatch. `runtime/mojo_python.c`'s CPython bridge is
extern-declared but has no codegen path, and bridging OO usage (parser
instances, method chains, `Namespace` attribute reads) needs a foreign-object
model before it could be useful anyway.

This is why the program cannot get further regardless of which compile-stage
defect is fixed next: three of the four links in this file's long crash chain
(`Path(x).name`, `sys.stdout`, `signal.SIGTERM`) were genuinely fixed, and the
fourth is this one. It is feature-sized — real compiled-argparse semantics
(usage/help generation, option and subcommand parsing, error handling) is a
whole subsystem, the same size class as the pickle engine judged out of scope
in `dbpickle.md`.

## Why this is its own doc and not folded into the COMPILE_FAIL one

`bugs/COMPILE_FAIL_Apple___main__.md` is retired: the file's compile stage is
clean, and what remains is not a compile failure at all — it is an unimplemented
runtime feature that the honest, correct behaviour for is a stub. Keeping a
COMPILE_FAIL doc open for it would file a known-and-accepted stub as an open
compile bug, which is the thing CLAUDE.md's `expect=`/`disabled=` rules exist
to stop.

## Next step

Not a narrow fix. Two honest options, and the second is cheaper:

1. Implement compiled argparse. Out of scope for a bug-fix pass.
2. Make the stub LOUD. `parse_args` returning the receiver means the program
   computes with a parser object that is not a parser, silently, until the
   first attribute read crashes with an `AttributeError` that names an
   attribute of a class the program never built. A stub that raised
   `NotImplementedError: argparse is stubbed in compiled mode` at the
   `ArgumentParser(...)` construction would say the same thing at the point
   where it becomes true, and would turn this class of runtime death into a
   named one. `gimple_codegen.py`'s existing "unavailable in compiled mode"
   stub text (`BUILTIN_FUNCS` and the `mojo_*` stub emitters) is the
   mechanism; argparse just needs to route through it rather than through the
   opaque-ctor passthrough.

Option 2 is the one worth doing first regardless of whether option 1 ever
happens.