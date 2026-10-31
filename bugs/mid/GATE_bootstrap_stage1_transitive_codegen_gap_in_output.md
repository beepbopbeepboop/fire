# GATE: `bootstrap-stage1-transitive` exits 0 but its output holds `# ERROR: compiling imported module` / `unavailable in compiled mode`

## Status (2026-10-31, OPEN, filed from a full `make bootstrap` run; not yet diagnosed)

    FAIL bootstrap-stage1-transitive (1216s) exit 0, but the output contains
    '# ERROR: compiling imported module|unavailable in compiled mode'
    -- a real codegen gap that does not abort the compiler

The job is a whole-closure `fire.py --dump-full` (about 20 minutes). It does not fail; the runner's
`reject=` regex found a codegen-gap marker in its output. Two markers can match:

- `# ERROR: compiling imported module <m>`: the transitive compile of an imported module raised and
  the compiler continued without it, so that module's symbols are missing from the dump.
- `<name>: unavailable in compiled mode`: a weak stub the codegen emitted for a name it could not
  resolve (`mojo/backend_gimple/emit_stmts.py`, "Auto-stub completely unknown names").

## Next step

1. Read the first marker line and the few lines before it in `build/suite.log` (the FAIL block carries the
   job's complete output). Record the module or name here.
2. If it is a module compile error, reproduce it with that module alone
   (`compile_to_gimple_with_cpp(src, do_imports=False, filename=...)`) and fix the refusal; if a name,
   find which import is unresolved.
3. Candidate cause to check first: `myinterpreter.py` now contains a generator
   (`_mojo_struct_iter_steps`, 422ab8a9) and `next(iterator, *default)`; see
   `GATE_bootstrap_stage1_dumps_myinterpreter_exit_1.md` (its fix is being landed from `work/s1`). A
   transitive compile that reaches `myinterpreter` would print exactly `# ERROR: compiling imported
   module myinterpreter`.

## Related

- `bugs/mid/CODEGEN_gate_bootstrap_stage1_transitive_red.md`: an earlier, different red of the same job.
