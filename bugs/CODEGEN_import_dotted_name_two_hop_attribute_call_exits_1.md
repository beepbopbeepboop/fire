# `import p.sub` then `p.sub.tri(14)` — the compiled program exits 1 with NO output on BOTH pipelines, where CPython prints 42

**State: OPEN. Found 2026-09-29 by `work/hard-fn-import` while fixing
the (now fixed and deleted) cross-module-import report; see the 2026-09-29
section of `bugs/hard/README.md`. Verified pre-existing: identical with that
fix's source files reverted, so not a regression from that work.**

## What I ran

```python
# p/__init__.py   (empty)
# p/sub.py
def tri(x):
    return x * 3
# p/main.py
import p.sub
print(p.sub.tri(14))
```

Single-TU (`do_imports=True`) and link mode (`link_mode=True`) through
`gimple_codegen._run_pipeline`, then `gcc -fgimple` + `runtime/fire_runtime.c`,
vs CPython on the same text with the package root on `sys.path`.

## What I saw

CPython prints `42`. Both compiled pipelines **compile and link cleanly**
(no GCC diagnostic) and then:

```
$ ./main
$ echo $?
1
```

Empty stdout, exit 1, on both. So this is neither a compile refusal nor a
wrong value — the program starts, raises, and dies without a message.

## What I expected

`42`, exit 0.

## Why it is easy to miss

It is one of very few shapes in this area that produces a NON-ZERO exit
code, and every other failure nearby is exit 0 with a wrong or noisy
stdout. A harness that asserts "exit code == 0" reads this as a
build/environment problem; one that asserts stdout reads it as an empty
answer. Nothing prints "unavailable in compiled mode", so the usual tell
that something was stubbed is absent — this one is a genuine runtime
failure, not a stub.

## Where

Not yet traced. The next step is to see what the program actually does:
compile the repro to a binary, run it under `lldb`/`gdb`, or read the
generated C for the `_toplevel` body and find the raise. The two facts
worth establishing first:

1. whether `import p.sub` binds `p` as a module alias at all on this path
   (`_module_alias_names` / `imported_symbols['p']`), and
2. whether the failure is in the attribute call `p.sub.tri(14)` — two
   attribute hops, one of them through a module that is a PACKAGE
   directory rather than a file — or in the module-resolution step itself.

`from p.sub import tri` and `from .sub import tri` (both fixed, see
cross-module-import report's series — see `bugs/hard/README.md` — and
`from .sub import tri` in a function body (works, same series) work, so whatever is broken is specific to the `import DOTTED.name` +
two-hop-attribute-call spelling rather than to dotted module names as
such.

## Exact next step

```python
# minimal container
import os, subprocess, sys, tempfile
sys.path.insert(0, '<repo>')
import gimple_codegen
from build_config import find_gcc
GCC = find_gcc(); RUNTIME = os.path.join('<repo>', 'runtime')
d = tempfile.mkdtemp(); os.makedirs(d + '/p')
open(d + '/p/__init__.py', 'w').write('')
open(d + '/p/sub.py', 'w').write('def tri(x):\n    return x * 3\n')
open(d + '/p/main.py', 'w').write('import p.sub\nprint(p.sub.tri(14))\n')
e = os.path.join(d, 'p/main.py')
c = gimple_codegen._run_pipeline(open(e).read(), filename=e, do_imports=True)[0]
open(d + '/m.c', 'w').write(c)
subprocess.run([GCC, '-fgimple', f'-I{RUNTIME}', '-o', d + '/m', d + '/m.c',
                RUNTIME + '/fire_runtime.c'], check=True)
```

then run the binary under a debugger, and read `_toplevel` in `m.c`.

If the raise turns out to be a "module has no attribute" / NULL-call
shape, the fix belongs with the marker-binding work already recorded in
`CODEGEN_link_mode_bare_submodule_marker_call_silent_wrong_value.md` — the
`import DOTTED.name` spelling is the same "bind a module marker, then
reach a symbol through it" problem reached from the other direction — and
the two should be fixed together rather than separately.
