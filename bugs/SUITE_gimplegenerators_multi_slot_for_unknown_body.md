# Sibling of SUITE_gimplegenerators_multi_slot_comprehension: a `for` statement whose BODY reads an undeclared name dies with the unknown-declaration diagnostic, not the arity refusal

## Status 2026-11-14 — measured on work/bug-suite-gimplegenerators-multi-slot-co, found while fixing the comprehension sibling, not fixed here

### What was run

```sh
python3 tools/memslot.py --gb 8 --label x-probe -- \
  python3 - <<'EOF'
import gimple_codegen
src = ("def g():\n    yield 1\n\ndef main():\n"
       "    for a, b in g():\n        print(x)\nmain()\n")
try:
    gimple_codegen.compile_to_gimple_with_cpp(src, do_imports=False)
    print("COMPILED")
except Exception as e:
    print(type(e).__name__, str(e).splitlines()[0])
EOF
```

### What was seen

```
SyntaxError: <source>:6:15: error: use of unknown declaration 'x'
```

### What was expected

The `for`-statement arity refusal from `_gen_for_generator_iter`
(emit_loops.py ~3917): "cannot compile a multi-slot `for` target over a
generator whose yield arity is not a tuple" — the same diagnostic-priority
collision the comprehension case
(bugs/SUITE_gimplegenerators_multi_slot_comprehension.md, fixed 2026-11-14
by mojo/middle/coro.py's
`refuse_multi_slot_comprehension_over_nontuple_generator` running before
`unknown_decl_check.check_module`) had: `unknown_decl_check` runs at
`_run_pipeline` step 3 and answers its own, less specific question before
codegen can answer the structural one. The for-statement body only has to
read ONE undeclared name (`print(x)` above) for the pass to preempt the
refusal; a body that reads only bound names (`print(a, b)`) still gets the
refusal today, which is why `test_gimple_generator_runner.py`'s
`gen_multi_slot_target_over_one_value_generator_refused` is green while this
shape is not.

### Exact next step

Generalize the new coro.py pre-pass to walk `ForStmt` as well as
`Comprehension`: a `for` whose target is a real multi-slot tuple target
(`for_target_is_tuple` and `_single_loop_target_name` is None) over a bare-name
call of a module-level generator of the same module all of whose yields are
provably non-tuple raises the shared refusal — a second message builder next
to `multi_slot_comprehension_refusal` carrying the `for` wording above — and
add a `test_generator_refused` case beside
`gen_multi_slot_target_over_one_value_generator_refused` spelling
`for a, b in g(): print(x)`. The predicate helper
(`_yields_provably_nontuple`) is already shared; only the statement walk and
the message differ.
