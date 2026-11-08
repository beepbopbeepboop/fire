# step-22 verdicts (chunk b)

| # | file | verdict | message (first 100 chars) | reason / fix | commit |
|---|------|---------|---------------------------|-------------|--------|
| 12 | test_formal_hostmods_conformance.py | T | build: parse error: Expected ASSIGN got COLON(':') at 1256:28 | Not Mojo source (Python test file swept as Mojo). | 503663bd7 |
| 13 | test_formal_interop.py | T | build: parse error: Expected ASSIGN got COLON(':') at 577:46 | Not Mojo source (Python test file swept as Mojo). | 503663bd7 |
| 14 | test_formal_os_backing.py | T | build: parse error: Expected ASSIGN got COLON(':') at 2071:15 | Not Mojo source (Python test file swept as Mojo). | 503663bd7 |
| 15 | test_formal_shlex.py | T | build: parse error: Expected ASSIGN got COLON(':') at 580:13 | Not Mojo source (Python test file swept as Mojo). | |
| 16 | test_formal_str_methods.py | T | build: parse error: Expected ASSIGN got COLON(':') at 674:27 | Not Mojo source (Python test file swept as Mojo). | |
| 17 | test_llm/dumb_gemm.mojo | T | [FloatLiteral] * m * k is a REPETITION, and this path can only lower one whose count it can read | Runtime repetition count `[0.0]*(m*k)` (lines 49-51) is not a build-time literal; formal frame-only path cannot reserve dynamic slots. | |
