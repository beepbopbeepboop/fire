# step-22 verdicts (chunk b)

| # | file | verdict | message (first 100 chars) | reason / fix | commit |
|---|------|---------|---------------------------|-------------|--------|
| 12 | test_formal_hostmods_conformance.py | T | build: parse error: Expected ASSIGN got COLON(':') at 1256:28 | Not Mojo source (Python test file swept as Mojo). | 503663bd7 |
| 13 | test_formal_interop.py | T | build: parse error: Expected ASSIGN got COLON(':') at 577:46 | Not Mojo source (Python test file swept as Mojo). | 503663bd7 |
| 14 | test_formal_os_backing.py | T | build: parse error: Expected ASSIGN got COLON(':') at 2071:15 | Not Mojo source (Python test file swept as Mojo). | 503663bd7 |
| 15 | test_formal_shlex.py | T | build: parse error: Expected ASSIGN got COLON(':') at 580:13 | Not Mojo source (Python test file swept as Mojo). | 3484a6f6e |
| 16 | test_formal_str_methods.py | T | build: parse error: Expected ASSIGN got COLON(':') at 674:27 | Not Mojo source (Python test file swept as Mojo). | 3484a6f6e |
| 17 | test_llm/dumb_gemm.mojo | T | [FloatLiteral] * m * k is a REPETITION, and this path can only lower one whose count it can read | Runtime repetition count `[0.0]*(m*k)` (lines 49-51) is not a build-time literal; formal frame-only path cannot reserve dynamic slots. | 3484a6f6e |
| 18 | test_pin_FORMAL_declared_parameter.py | T | build: test_pin_declared_param_fix_present: 'os' has no home: module-level symbol table empty for  | Not Mojo source (Python test file swept as Mojo; build error reflects Python test body). | 5851f1e29 |
| 19 | test_regress_callable_ctype_param.py | T | build: test_callable_ctype_parameterized: 'types' imported from `mojo.middle`, module-level name o | Not Mojo source (Python test file swept as Mojo). | 5851f1e29 |
| 20 | test_regress_gencodec_pinned.py | T | build: test_gencodec_compile_exits_0: sys.path reads 'path' out of imported module `sys`, module n | Not Mojo source (Python test file swept as Mojo). | 5851f1e29 |
| 21 | test_regress_split_coro.py | T | build: __module_body__: sys.path reads 'path' out of imported module `sys`, module not a value thi | Not Mojo source (Python test file swept as Mojo). | 2c0f32aaf |
| 22 | test_regress_stale_budget_literal_fix.py | T | build: test_gimple_uses_shared_constants_at_named_sites: 'os' has no home: module-level symbol tab | Not Mojo source (Python test file swept as Mojo). | 2c0f32aaf |

T=11 M=0 S=0 C=0
