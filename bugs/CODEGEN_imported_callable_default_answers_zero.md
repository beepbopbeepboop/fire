# A keyword-only parameter defaulting to an IMPORTED function compiles to a
# NULL call, and now answers `0` instead of crashing

## Status

OPEN, and NEW — found 2026-10-02 while re-measuring
`bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_fsutil.md`, which pointed here
for this shape and whose doc is **deleted**, i.e. the crash was considered fixed.

## What I ran, and what I saw

```python
import os

def probe(x, *, g=os.walk):
    return g(x)

def main():
    print(probe('/r'))

main()
```

```
$ python3 fire.py run /tmp/probe.mojo       # CPython's text
<generator object walk at 0x105873b30>

$ test_gimple_runner.py's compile_mojo_to_gimple_exe, then run
0
```

**No crash.** `CODEGEN_unresolved_imported_callable_default_null_pointer`
recorded this as `SIGSEGV` — exit 139, nothing on stdout — and that doc is gone,
so whatever fixed it did stop the fault. What it did not do is make the answer
right. The program prints `0`: address 0 was called, and this runtime's
function-pointer dispatch turned that into a zero rather than a fault.

The same-module spelling is right, which is what isolates it to the IMPORT:

```python
def leaf(root):
    yield root + '/a'

def probe(root, *, walk=leaf):
    for f in walk(root):
        yield f
```

→ `/r/a`, correct on both sides.

## Why it matters more now, not less

This is the exact case
`bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_fsutil.md`'s
`Tools/c-analyzer/c_common/fsutil.py` blockers 1 and 2 rest on. Its stated
reason for refusing `_walk_tree(root, *, _walk=os.walk)` and
`glob_tree(root, *, suffix=None, _glob=glob.iglob)` was:

> Guessing "resolved" would compile the generator and then pad NULL — trading a
> refusal for a crash — so the gate says no.

That reason is now **stronger and worse**: the trade is no longer a refusal
against a crash, it is a refusal against a **silent wrong answer**. `os.walk` is
also a generator function rather than a plain one, so the same shape on the
compiled path has to resolve an imported generator's identity, pack the
arguments, and hand back a `MojoGenerator *` — the machinery
`_lower_one`'s `callable_param_generators` already builds for the same-module
case, but resolved after `lower()` rather than before it.

`bugs/UNTESTED.md` §3.3 is the general statement: a non-zero exit is the only
verdict the suite can see, and this shape reports its verdict in neither.

## The exact next step

Two halves, and the first is small enough to do on its own:

1. **Make the ordinary path refuse instead of emitting a NULL call.** `os` is
   an imported-symbol marker and `walk` is never in `func_return_types`, so the
   padded default is a bare `0` that the body then calls. The honest
   degradation this project uses everywhere else is to raise, so the module
   falls back to interpreting from source and the answer is right.
   `calls_shared._callable_value_symbol` ("what C symbol does a function used as
   a value mean") is the one place that answers that question, and it already
   answers it for a same-module function and for a generator; an imported
   `module.attr` has no answer today, and "no answer" should be a refusal
   rather than a `0`. That is a much smaller change than (2) and it converts a
   silent wrong answer into a correct one for every module that hits it,
   including two of fsutil's four.

2. **Then resolve the imported case for real**, which is what would let
   `_walk_tree`/`glob_tree` through. `_eligible` runs in `lower()` before any
   `GimpleGen` exists, so it cannot know whether `os.walk` will be resolved;
   `module_gen.py`'s `_generator_quick_eligible` runs after imports are
   compiled and is the natural home for the decision. The same-module fix in
   fsutil's doc already built the machinery (`callable_param_generators` on the
   generator's meta, `register`'s second pass resolving it against
   `_generator_api` after every generator is registered) — it needs an
   `os.walk` arm, not a new design.

## Related

- `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_fsutil.md`, whose blockers 1
  and 2 are this shape and whose Status now records the re-measurement.
- The sibling doc this one replaces, `CODEGEN_unresolved_imported_callable_
  default_null_pointer.md`, is deleted — the crash it described is fixed and
  the wrong value it did not describe was not found by anything. That is the
  §3.3 shape in its purest form: a doc deleted on the strength of a symptom
  that stopped, with the behaviour it was a symptom of still wrong.