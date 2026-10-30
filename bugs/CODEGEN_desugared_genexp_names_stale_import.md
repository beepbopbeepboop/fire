# CODEGEN: `_verify_desugared_genexps` reads a stale, always-empty name list

Found 2026-10-29 while fixing bugs/COMPILE_FAIL_collections___init__.md.

## What is wrong

`fire_compiler.desugar_genexps` ends with
`DESUGARED_GENEXP_NAMES = [fn.name for fn in d.hoisted]`, which REBINDS the
module global. `gimple_codegen.py` imports the name by value
(`from fire_compiler import ... DESUGARED_GENEXP_NAMES`), so its own binding
keeps pointing at the list that existed at import time, which is `[]`.

Its compile choke point (`_desugared_names = list(DESUGARED_GENEXP_NAMES)`,
gimple_codegen.py ~6107) therefore always reads `[]`, and
`_verify_desugared_genexps(code, gen, [])` checks nothing. The check that
exists to turn a silently-dropped generator expression into a loud error is a
no-op.

## Measured

```
import fire_compiler as fc, gimple_codegen as gc
st = Parser(py_tokenize('def f(n: int):\n    return sum(i for i in range(n))\n')).parse_module()
fc.desugar_genexps(st)
fc.DESUGARED_GENEXP_NAMES   -> ['__genexp_0']
gc.DESUGARED_GENEXP_NAMES   -> []
```

## Next step

Clear and extend the list IN PLACE in `desugar_genexps` (`del L[:]` then
`L.extend(...)`), the way `DESUGARED_NAMEDTUPLE_NAMES` is done in
`fire_compiler.desugar_namedtuples`, so every importer sees the same object.
Then `_verify_desugared_genexps` starts doing real work, which can newly fail
programs that were silently wrong before: run the full gate
(`make gate`, including `stdlib-dylib` and `stdlib-syntax` skip/unexpected
counts) before landing it, not just the quick tests. Regression: a build-and-run
of a program whose genexp is refused by both lowering paths must fail loudly.
