# Self-host build fails with GCC conflicting types for `_mojo_repr_set`

Status: 2026-10-30 — root cause identified, not fully fixed.

What I ran:
- `python3 /Users/mrs/net/chatgpt/claude/work-verify/test_selfhost.py` (alone, 494s in gate, >300s locally) → `Results: 2 passed, 1 failed`, build fails.
- `python3 -c "fire.build_executable(...)"` with `quiet=False` → GCC error visible.

What I saw (exact GCC output from self-host binary compile of myinterpreter.py):
```
/mojo/backend_gimple/module_gen.py:2607:10: error: implicit declaration of function '_mojo_repr_set'; did you mean '_mojo_repr_Seq'? [-Wimplicit-function-declaration]
/myinterpreter.py:18046:15: error: conflicting types for '_mojo_repr_set'; have 'char *(MojoSet *)'
/myinterpreter.py:18046:15: note: previous implicit declaration of '_mojo_repr_set' with type 'int()'
```

Root cause: The self-hosted compiler emits a `static char * _mojo_repr_set (MojoSet *s)` definition (module_gen.py:2445) but the translation unit that includes `myinterpreter.py` uses `_mojo_repr_set` before that definition, causing GCC to implicitly declare it as `int()`. The later definition conflicts. The static-helper family (`_mojo_repr_list`, `_mojo_repr_dict`, `_mojo_repr_pair`, `_mojo_repr_set`) is emitted per-module; ordering/reference issues in the emitted `.ci` cause this for the self-host closure on master.

Next step: Inspect emitted `.ci` for `myinterpreter.py` (build scratch dir) to find the first reference site vs definition site, then adjust `gimple_codegen.py` / `module_gen.py` forward-declaration or emission order so the static definition precedes any use, or emit an explicit `static char * _mojo_repr_set(MojoSet *);` forward declaration at the top of each `.ci` that may reach it.
