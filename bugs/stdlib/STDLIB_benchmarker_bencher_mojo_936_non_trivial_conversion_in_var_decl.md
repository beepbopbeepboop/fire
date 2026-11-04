# STDLIB_benchmarker_bencher_mojo_936_non_trivial_conversion_in_var_decl

**file**: `std/benchmark/bencher.mojo`  
**error**: gcc: .../std/benchmark/bencher.mojo:936:1: error: non-trivial conversion in 'var_decl'  
**details**:  
```
int64_t
char *
input_id = _t10;
```

**context**: appears in `Bench._bench` around line ~936 when handling `BenchmarkInfo` construction with optional `input_id` from `if case .Some(input_id) = bench_id.input_id:` pattern matching.

**notes**: related to if-case binding/type inference for Optional/String values in codegen.
