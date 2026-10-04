# RUNTIME: compiled mode stubs a module it never compiled; `argparse` (and `math`, and `signal`) are among them

**The title this doc used to carry — "…so every `mod.method()` consumer
computed with a 0" — stated the defect as if it were still open, and it is
not.** The stub now raises `NotImplementedError` at the call instead of echoing
the marker back, so the program names the absence, exits non-zero, and can
still catch it. The bug that remains is the subsystem below: those modules are
not compiled into the binary at all. Retitled 2026-10-02 (`work/bugs4-9-c`)
because a doc whose title says "crashes" is read as "still crashes", and the
next person to look at `argparse` here would re-do the diagnosis this Status
already records.

## Status (2026-10-02 — the stub is LOUD; the subsystem is still not implemented)

Option 2 of the two this doc offered, which it said was the one worth doing
first regardless of whether option 1 ever happens: **a stub that raised at the
call would say the same thing at the point where it becomes true.**

`import argparse` binds a module MARKER — an `int64_t` global initialised to 0
(`_root_globals.argparse = 0`), because `module_loader.can_resolve_module_path(
'argparse')` is false: there is no source under this checkout's stdlib to
compile. Every method on that marker was answered by the generic scalar
passthrough in `mojo/backend_gimple/emit_methods.py`, which returns the
receiver unchanged. So:

```
_t3 = _t2;  /* int64_t.ArgumentParser() stubbed */
_t9 = _t4;  /* int64_t.add_argument() stubbed */
_t11 = _t10;  /* int64_t.parse_args() stubbed */
```

`ArgumentParser(...)` "constructed" a 0, every method echoed the 0 back, and
CPython's own `Apple/__main__.py` — whose `--help` prints argparse's generated
usage and exits 0 — instead died with `Unhandled exception: AttributeError:
cross_build_dir` **and exited 0**.

Now:

```
$ python3 fire.py build .../Apple/__main__.py && ./__main__ --help
Unhandled exception: NotImplementedError: argparse.ArgumentParser: module 'argparse' is not compiled into this binary
rc=1
```

Same point in the program, named, non-zero, and **catchable** —
`except NotImplementedError` around the construction works, which is the whole
reason a raise is better than the `mojo_print` + `return 0` stub shape used
elsewhere: a program that genuinely probes for the capability can still say so.

### What landed

* `runtime/fire_runtime.c` — `mojo_raise_not_implemented` (the sixth typed
  raiser, same mechanism and same `crc32(name) & 0x7fffffff` tag derivation as
  the five above it) and `mojo_module_not_compiled(module, member)`, one entry
  point so the message cannot drift between the two spellings.
* `mojo/backend_gimple/emit_methods.py` — `_uncompiled_module_marker()`, and a
  hook at the TOP of the `_ALL_SCALARS` block. Top deliberately: a marker is
  not a scalar, so none of the comparison/arithmetic arms below mean anything
  on it either, and `argparse.__doc__ == x` should say the module is missing
  rather than answer a question about the integer 0.
* The predicate is keyed on `gen._module_alias_names`, NOT
  `gen.imported_symbols`, for the ambiguity that set's own docstring records at
  length: an unresolved `from X import name` binding has the identical dict
  shape, and an earlier attempt at the broader key wrongly excluded the genuine
  `block_idx.x` GPU-intrinsic accessor shape.
* `test_gimple_runner.py` — `gimple_module_marker_call_raises` (the doc's own
  program, against the named message) and
  `gimple_module_marker_call_is_catchable` (the same program with a `try` /
  `except NotImplementedError`, which must still reach its `print`).

### The blast radius, measured rather than assumed

This is the GENERAL form of the doc's fix: it fires for any method call on any
bare-imported module marker, not just `argparse`. That is the honest scope —
by the time a call reaches the generic passthrough, nothing has provided it —
and the two obvious counter-examples are already handled above that point:
`os.getcwd()` still works (ast_rewriter rewrites the `os` surface before
`_lower_method_call` sees it) and `os.environ` still works.

What it does change is a family of **silent wrong answers into named ones**:

| program | before | after |
|---|---|---|
| `print(math.floor(1.5))` | `0`, exit 0 | `NotImplementedError: math.floor: module 'math' is not compiled into this binary`, exit 1 |
| `signal.signal(2, print)` | `1`, exit 0 (the call echoed the marker) | same raise, exit 1 |

That is the trade this codebase's own rules make explicitly — "a silent
wrong-answer is worse than a crash", and here it is not even a crash, it is an
exit-0 program that printed the wrong number. The rest of that family is filed
separately rather than fixed here:
`bugs/CODEGEN_a_method_call_on_an_uncompiled_module_marker_is_a_silent_zero.md`.

Verified no new reds: `test_gimple_runner.py` 295 passed / 9 failed (the same
9 that fail on a pristine `bc17a62b`), `test_gimple.py` 368 passed / 0 failed,
`test_runtime_diff.py` 46 passed / 0 failed. The last of those is the one that
matters for blast radius: it is the CPython-oracle suite, it exercises `os`,
`sys`, `re`, `struct`, `collections` and `subprocess` shapes end to end, and it
is unchanged.

## What was run

```sh
python3 fire.py build /Users/mrs/net/Python-3.14.6/Apple/__main__.py && ./__main__ --help
```

## What was seen (before this change)

The file now **compiles, links and starts** (the COMPILE_FAIL doc for it is
retired — see `bugs/` history; `fire.py build` exits 0 and the binary reaches
`main()`). It then dies:

```
Unhandled exception: AttributeError: cross_build_dir
rc=0
```

CPython's own `python3 Apple/__main__.py --help` prints usage and exits 0.

## What was expected

Either the usage text, or — since the subsystem is out of scope — a named
failure at the point where the absence becomes true. It is now the second, and
the first is still option 1 below.

## Root cause (unchanged)

`argparse` is never compiled into the binary. It degrades to the opaque-ctor
passthrough of a module marker (int64_t 0), so `ArgumentParser(...)`
constructs nothing, every method (`add_subparsers` / `add_parser` /
`add_argument` / `parse_args`) is an `int64_t.X() stubbed` passthrough
returning its receiver, `parse_args()` returns 0, and the first attribute read
off that result used to be the crash.

There is no escape hatch. `runtime/mojo_python.c`'s CPython bridge is
extern-declared but has no codegen path, and bridging OO usage (parser
instances, method chains, `Namespace` attribute reads) needs a foreign-object
model before it could be useful anyway.

This is why the program could not get further regardless of which compile-stage
defect was fixed next: three of the four links in this file's long crash chain
(`Path(x).name`, `sys.stdout`, `signal.SIGTERM`) were genuinely fixed, and the
fourth was this one. It is feature-sized — real compiled-argparse semantics
(usage/help generation, option and subcommand parsing, error handling) is a
whole subsystem, the same size class as the pickle engine judged out of scope
in `dbpickle.md`.

## Why this is its own doc and not folded into the COMPILE_FAIL one

`“COMPILE_FAIL: Apple/__main__.py”` is retired: the file's compile stage is
clean, and what remains is not a compile failure at all — it is an unimplemented
runtime feature for which the honest, correct behaviour is a stub. Keeping a
COMPILE_FAIL doc open for it would file a known-and-accepted stub as an open
compile bug, which is the thing CLAUDE.md's `expect=`/`disabled=` rules exist
to stop.

## What is still not done

Option 1: **implement compiled argparse.** Usage/help generation, option and
subcommand parsing, and error handling. A whole subsystem, and out of scope for
a bug-fix pass. Nothing in this change makes it more or less likely; it makes
the absence visible, which is the precondition for anyone attempting it.