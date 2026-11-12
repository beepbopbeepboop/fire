# CODEGEN: compiled-regex tables are assigned to pointer variables and `gcc -fgimple` refuses ("non-trivial conversion in 'var_decl'"), breaking the self-host build

Status: OPEN. Filed 2026-11-12 from a failing self-host build. No small repro yet: finding one is the first step. Class: easy.

## Symptom

```
elaborate.py: In function 'elaborate_Elaborator_elaborate_overload_call':
elaborate.py:1481:1: error: non-trivial conversion in 'var_decl'
const struct ReNode *
const struct ReNode[55]
_t62 = _re17_prog;
  (the same for  const struct ReRange * / const struct ReRange[2]   _t63 = _re17_ranges;
                 const struct ReClassInfo * / const struct ReClassInfo[1]   _t64 = _re17_classinfo;)

fire_compiler.py: In function 'fire_compiler_Parser__merge_string_literals':
fire_compiler.py:7379:1: error: non-trivial conversion in 'var_decl'
  _t109 = _re26_prog;   _t110 = _re26_ranges;   _t111 = _re26_classinfo;   (14 / 4 / 2 elements)
```

Six errors, one cause: a static table (`static const ReNode _reN_prog[] = {...}`, emitted by `regex_compile.py`) is bound to a pointer-typed GIMPLE temporary by plain assignment (`_tNN = _reN_prog;`). In `-fgimple` an array to pointer decay is a "non-trivial conversion"; the address (`&_reN_prog[0]`) or a cast has to be spelled out.

The emitters are `gen._new_val('const ReNode *', info['prog_var'])` (and the `ranges_var` / `classinfo_var` twins) at `mojo/backend_gimple/emit_loops.py` (lines ~359 and ~454) and `mojo/backend_gimple/emit_methods.py` (~2485).

The two functions in the build are the ones that use `re`: `fire_compiler.py` `_merge_string_literals` does `re.sub(r'(\\N\{[^{}]*\})|([{}])', lambda ..., _inner)` (line 7364), and `elaborate.py` `elaborate_overload_call` calls `re.sub` (line 1478). (The reported lines are a few lines past the statement: see `CODEGEN_line_directives_drift_so_gimple_errors_name_the_wrong_line.md`.)

## What I could not reproduce

Standalone programs in the same shape compile cleanly on master with `-Og` and with the build's own flags (`-Os -g -fgimple -ftrivial-auto-var-init=zero`): a module-level `re.compile(r"a+")` with `.split`, `re.sub(r"\s+", " ", s)`, and `re.sub(r'(\\N\{[^{}]*\})|([{}])', lambda m: ..., s)`. Their `.ci` contains `_t2 = _re0_prog;` and gcc accepts it. So plain assignment of the array works in those, and the failing case differs in something not yet identified. Candidates to check, in order:

1. The failing functions are huge and sit in the whole-closure `fire.ci`: is the table declared with a bound (`[55]`) at the point of use there, while in the small cases it is `[]` (completed later)? The error text names the sized type.
2. Whether the temporary is declared at function scope or inside a nested block in the failing functions.
3. Whether this started recently: the emitter is old (2026-09/10), but the whole-closure build passed on 2026-10-25, so something in how these two functions are now lowered changed.

## Scope

Find the smallest program that fails (compile the two functions' module in isolation first: `python3 fire.py elaborate.py --dump-full` or `fire_compiler.py`, then `gcc -fgimple -c`), then fix the emitter to spell the pointer explicitly. Fix the emitter at all three sites together; do not special-case the two functions.

## Acceptance

- The smallest failing program found is added as a regression test and compiles under `gcc -fgimple` with the build's flags.
- `_merge_string_literals` and `elaborate_overload_call` no longer produce `non-trivial conversion in 'var_decl'` (check in the generated `.ci` that the assignment is explicit).
- Behaviour unchanged: `re.sub` / `.split` / `findall` tests still pass (the existing regex codegen tests).

## Done when

The new regression test passes together with the existing narrow regex tests. The `fire.o` step of the full self-host build is the integrator's check, not a worker's; report it as not run.
