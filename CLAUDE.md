# Project Conventions

## Code Quality
- Never pick the simple/quick fix. Always pick the production-quality approach.
- Consolidate duplicates rather than maintaining parallel implementations.
- If two files do the same thing, merge them — don't symlink, don't copy-paste.

## AST Nodes
- `mojo_compiler.py` is the single source of truth for all AST node definitions.
- `myinterpreter.py` imports AST nodes as `import mojo_compiler as N`.
- `ast_nodes.py` is dead and should not exist.
