# COMPILE_FAIL: scriptutil.py part 2 — @contextlib.contextmanager nested generator lowering

Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_scriptutil.md` (SPLIT)

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/scriptutil.py`

## Scope

`traceback_cm` (scriptutil.py:218) is a `@contextlib.contextmanager`-decorated nested
generator inside `main()` that yields once (`yield 0`) and wraps exception handling,
then is instantiated and stored as `ns[key] = traceback_cm()`. Even once its enclosing
read (`showtb`) is capturable (part 1), the compiler must represent/lower this
decorated-generator context-manager shape.

This part covers the compiler/runtime lowering needed for this shape in the compiled
path: a contextmanager-decorated generator that yields exactly once used as a context
manager / factory returning a context manager, sufficient for `traceback_cm`.

Out of scope: general arbitrary decorator semantics beyond what this shape requires;
`_iter_filenames` blockers; widening capture beyond part 1.

## Dependencies / ordering

- Depends on part 1 for `traceback_cm` specifically because it reads captured
  `showtb`. The implementation may land independently if validated on a reproducer with
  no captured enclosing plain-assignment local, but closing the `traceback_cm` refusal
  requires part 1.

## Acceptance check

- A compiled reproducer matching `traceback_cm`'s essential shape —
  `@contextlib.contextmanager` nested generator, single yield, `try/except/finally`
  around yield, reads an enclosing value (can be combined with part 1's capture form),
  instantiated and used as a context manager — compiles and its behavior matches
  CPython, including normal and exception paths exercised by the reproducer.
- Narrow verification only, wrapped in `python3 tools/memslot.py --gb 8 --label <what> -- <cmd>` if it compiles.

## Not in this part

- Callable-parameter `process(...)` discovery in `_iter_filenames` (part 3).
- Making the full `scriptutil.py` module compile (part 4 / integration).
