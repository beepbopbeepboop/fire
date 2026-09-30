# CODEGEN: three gimplification errors remain in the self-host closure

## Status — PARTIAL. Three of six gate failures are fixed; three are not.

`make gate` fails on this branch with **6** failures. `git bisect` puts the
first bad commit at **`82bb13e`** ("Make a ~1M-parameter pure-Python LLM
compile and run under the JIT"), the first commit on the branch — **not** the
GPU work, which is exonerated. Its parent `6e69d1a7` passes, verified as an
explicit control (the bisect's `good` endpoint is `a0c0969`, and `82bb13e`'s
parent *is* an ancestor of it, so the range is valid).

Symptom: `gcc -fgimple` rejects `stage1/fire.ci`, the whole-closure dump, so
`bootstrap-stage2-cc` fails and takes `selfhost`, `mojoc`, `silentnoop` and
`stdlib-syntax` with it.

**Measured: 22 gimplification errors → 3** (landed in `d446f5be`).
`rthdrscan` is also fixed (it was the sixth failure, and independent).

## What is fixed, and how each was found

The technique that made these tractable: **compile a copy of the generated C
with the `#line` directives stripped.** gcc reports the *Mojo* source line for
a diagnostic in the C, which hides the statement that is actually wrong — and
`-fsyntax-only` reports **0 errors**, because these are gimplification errors
and `-fsyntax-only` never gimplifies. Both cost real time here; the errors
only appear with a plain `-c`.

| # | Defect | Sites | Effect |
|---|---|---|---|
| 1 | A C-style cast is not a legal GIMPLE **operand**. `x + (int64_t)1` | 6 | hard "expected expression before '(' token" |
| 2 | An unannotated param whose default is a container literal is a **container** param; the existing `_param_ctype` rule covered only `StringLiteral`/`DictExpr` | 1 rule | "conflicting types" on `GimpleGen.__init__` — **5 of the 6 gate failures from one line** |
| 3 | A comprehension's loop target is a fresh scoped binding and must not share the enclosing function's C variable; the shadow counter also restarted per function while all decls share one TU | 4 + 1 | set-of-strings comprehension assigned into an `int64_t` variable |
| 4 | `test_runtime_header_scan.py` hardcodes the `fire_runtime.h` declaration count (465, this branch adds `mojo_stream_write`) | 1 | `rthdrscan` red |

Detail and rationale for each is in the `d446f5be` commit message. Regression
suites after those fixes: `test_gimple` 334/334, `test_interp_oracle` 6/6,
`test_runtime_diff` 33/33, `test_metal_codegen` 45, `test_runtime_header_scan`
28/28, `test_link_mode` 8/8.

## What remains — 3 errors, 2 causes

### A. A delegate forwarder's return type, through a four-layer chain

```
mojo/backend_gimple/emit_funcs.py:3691
    error: invalid conversion in gimple call
    note: int64_t  vs  struct MojoList *
```

`GimpleGen._parsed_import` is a one-line delegate with **no return
annotation**, so `_sgfs_ret_ct` (emit_funcs.py:1315) falls through to body
inference on the helper `funcs_shared._parsed_import`, which ends in
`return cache[module]` where each `cache[module]` is a 3-tuple.

Traced layer by layer, with the instrumented value at each:

1. `_sgfs_ret_ct` — delegate target **is** found (`target=True`), neither
   side annotated. Correct so far.
2. `gen._infer_return_type(_tgt_fn.body)` returns **`'int64_t'`**, and it is
   truthy, so it is returned immediately and the delegate's own body is never
   consulted. This is the point where the answer is lost.
3. That inference reaches `_collect_return_types` (infra_infer.py:1427), which
   does `gen._quick_type(node.value)` on a `SubscriptExpr`. **`_quick_type`
   has no `SubscriptExpr` case at all**, so it answers the int64_t box.
4. The information needed does exist: `_scan_container_elems` records a dict's
   value ctype from its `d[k] = v` stores into a `dict_val` table. But
   `resolve_shared.py:842` does `gen._dict_val_types = {}`, so that table is
   **empty** by the time return inference runs. Verified: instrumenting
   `_collect_return_types` shows only `_BIN_OPS` and `_GD_BIN_OPS` in it, and
   no `cache`.

Two further gaps sit behind that, both left unfixed because each was
individually unmeasurable once the layer above was still missing:

- `_scan_container_elems` does not map a **container literal** stored into a
  dict slot, so `cache[module] = (path, src, stmts)` records nothing even when
  the walker reaches it. (The walker *does* recurse into `IfStmt`/`TryStmt`,
  so the assignment is reachable — this is the value mapping, not the walk.)
  `_CONTAINER_LITERAL_CTYPES` (`TupleExpr` → `MojoList *`) already exists at
  infra_infer.py:1464.
- `_collect_return_types` has no `SubscriptExpr` case to consult any such
  table.

**Next step, in order:** (a) thread the scan's `dict_val` into return
inference rather than reading the cleared `gen._dict_val_types`; (b) map a
container-literal dict store in `_scan_container_elems`; (c) add the
`SubscriptExpr` return case. Verify with
`gcc -O0 -fgimple -ftrivial-auto-var-init=zero -I runtime -c -o /dev/null -x c stage1/fire.ci`
on a fresh `bootstrap-stage1-transitive` dump — the error count is the
signal, and it is currently 3.

### B. A rewritten AST node passed where `const char *` is expected

```
ast_rewriter.py:691
    error: passing argument 2 of 'mojo_list_append_str'
           from incompatible pointer type
    note: expected 'const char *' but argument is of type 'ExprStmt *'
```

```python
value = _rewrite_node(node.value, trie)
return ExprStmt(value=CallExpr(
    func=IdentExpr(name='setenv'),
    args=[bindings['key'], value, IntLiteral(value=1)], ...))
```

`value` is a rewritten **AST node**, and the compiled path passes its address
straight into a `const char *` slot (a second site at the same line does the
same with an `IntLiteral *`). The interpreter evidently stringifies or
compares it, so the two engines disagree about what the second argument of
`setenv` is. Note `ast_rewriter.py` itself is **not** in `82bb13e`'s file
list — what changed is the compiler's lowering, so this is a pre-existing
sharp edge that only became reachable once the other four defects were fixed.

Decide deliberately which is true before fixing: either the call is genuinely
wrong and the compiled path must coerce/stringify the node, or `setenv`'s
second parameter is not a string in this codegen and the registration is
wrong. Guessing here risks "fixing" it into a different wrong answer.

## Reproducing

```sh
python3 tools/suite.py bootstrap-stage1-transitive -j1 --timeout 2400   # writes stage1/fire.ci
/opt/local/bin/gcc-mp-15 -O0 -fgimple -ftrivial-auto-var-init=zero \
    -I runtime -c -o /dev/null -x c stage1/fire.ci 2>&1 | grep -c 'error:'   # 3
```

Not `-fsyntax-only`: it reports 0 and skips gimplification entirely.

To read the offending C, `grep -v '^#line ' stage1/fire.ci > /tmp/nolines.ci`
and compile that — gcc then reports real C line numbers and prints the
statement that is wrong.

`bootstrap-stage2-cc` is the cheapest gate test for this work (~100 s with
its deps). The runner takes test names positionally, so
`python3 tools/suite.py <name>` runs exactly one.
