# Project Conventions

## Code Quality
- Never pick the simple/quick fix. Always pick the production-quality approach.
- Consolidate duplicates rather than maintaining parallel implementations.
- If two files do the same thing, merge them — don't symlink, don't copy-paste.

## AST Nodes
- `mojo_compiler.py` is the single source of truth for all AST node definitions.
- `myinterpreter.py` imports AST nodes as `import mojo_compiler as N`.
- `ast_nodes.py` is dead and should not exist.

## Quality gate for gimple/codegen-affecting changes
Before considering a change to `mojo_compiler.py` (the shared parser/AST),
`gimple_codegen.py`, or `module_loader.py` (or anything else on the compiled
path) done — including subagent work — run BOTH of the following, not just
`test_gimple.py`/`test_module_cache.py`:

1. `make check-selfhost` (mojo.py compiling its own source). A parser AST
   change (e.g. a new node shape for some syntax) can be invisible to the
   interpreter-focused test suites yet silently break the compiled path,
   since gimple_codegen.py's lowering of that node shape is a separate,
   independently-maintained implementation from myinterpreter.py's evaluator.
   Concretely: a fix that changes `mojo_compiler.py`'s AST for `*`/`**`
   call-arguments (adding a `UnaryOp` wrapper) fixed the interpreter but
   broke `gimple_codegen.py`'s own self-compilation, because its
   `_lower_UnaryOp` had never seen that wrapper on those call sites before —
   `test_gimple.py`/`test_module_cache.py` both stayed green throughout.
2. A from-scratch stdlib dylib build (`rm -f build/libmojostdlib.dylib`
   then `python3 -c "import build_stdlib_dylib as bsd; bsd.build_stdlib(jobs=8)"`,
   or just `python3 mojo.py <any file>.mojo`) — check for `skip <module>:`
   lines in the output. The stdlib build is far larger and more varied than
   this repo's own source, and a type-resolution change can regress dozens
   of real stdlib modules from clean-compiling to falling back to source
   (a real regression, even though it's silently absorbed by the documented
   "skip and fall back" stopgap and won't show up as a hard failure anywhere
   else). Compare the skip count before/after your change — it should not
   increase. If it does, bisect which specific type/symbol triggered it
   before considering the change finished.

A change passing `test_gimple.py`/`test_module_cache.py`/`make check-selfhost`
alone is NOT sufficient evidence the compiled path is unaffected — only the
stdlib build actually exercises the huge breadth of real Mojo source this
compiler needs to keep working.
