# Gate: stdlib-syntax is red on master

**Job:** `stdlib-syntax`. Created when branch `work/bug-codegen-gimple-tag-ignored-on-pointe-3` (task `bug-codegen-gimple-tag-ignored-on-pointe-3`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `work/bug-codegen-gimple-tag-ignored-on-pointe-3`: reproduce it there (`python3 tools/suite.py stdlib-syntax`), then fix the cause. Do not skip or mark the test.

**Fixed at the root in f4a7ee488** (integrated as 73de7fe82): `__mlir_op` reported a blanket
`int64_t` result, so a `__GIMPLE`-checked body got `int64_t _t = _t1 & _t2;` over `_Bool`
operands, which gcc rejects with "type mismatch in binary expression". The op now joins its
value operands' types and reports that. The doc was left behind; retire it here.

## Done when

`python3 test_gimple.py` reports PASS for the regression cases `mlir_bool_simd_and_xor`,
`mlir_bool_simd_xor_attr_operand` (the 153b/153c pinning cases added with f4a7ee488) and
`mlir_bool_simd_or` (153d, the third op of the same trio, `std/builtin/bool.mojo`'s
`__and__`/`__or__`/`__xor__`); all three fail before f4a7ee488 with gcc's "type mismatch in
binary expression".
