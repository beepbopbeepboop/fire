# FORMAL: the concrete `eval_eq_mojo_*` instances omit the two-argument environment

**Found while fixing gate job `reg-formal-ast-bridge-two-arg` (2026-11-12).**
Not fixed there: the job only checks proof GENERATION, and this is a proof
that does not check.

## What I ran

```python
from test_formal_call_proof_gen import _generate, _check_proof
src = ("def _scalar_max2(a, b):\n"
       "    if a > b:\n"
       "        return a\n"
       "    return b\n"
       "def main(x):\n"
       "    return _scalar_max2(x, x)\n")
p, err = _generate(tmp, src, "reg_two_arg", arch="arm64")   # err is None
ok, detail, _cached, n = _check_proof(p)                    # ok is False
```

## What I saw

The file generates, and `eval_eq_mojo` (the universal theorem) passes, but
every concrete instance fails:

```
reg_two_arg_proof.lean:44:2: error: Tactic `native_decide` evaluated that the proposition
  evalFunc ast (fun name arg => if name = "main" then mojo arg else ...) [UInt64.ofNat 1]
    = mojo (UInt64.ofNat 1)
is false
```

The universal theorem is stated with BOTH environments:

```lean
evalFunc ast (fun name arg => ...) [n]
  ((fun name arg0 arg1 => if name = "_scalar_max2" then _scalar_max2_go arg0 arg1 else 0))
```

while the concrete instances (`eval_eq_mojo_0`, `_1`, `_2`, `_5`) pass only
`_cf_text` and rely on `evalFunc`'s default two-argument environment (which
answers 0).  For any program containing a two-argument user call, the concrete
proposition is therefore about a different program and `native_decide`
refutes it.  `eval_eq_mojo_test` is the only concrete instance that gets
`_cf2_text`, and it is the one that passes.

## What I expected

`eval_eq_mojo_0`/`_1`/`_2`/`_5` to state the same application as
`eval_eq_mojo` and `eval_eq_mojo_test`, so they check.

## Exact next step

In `formal/arm64_proof_gen.py::generate_arm64_proof`, the concrete-instance
loop (search for `theorem eval_eq_mojo_{v}`) builds

```python
f"  evalFunc ast {_cf_text} "
f"{_entry_arg_list(_vv)} = {_apply_args('mojo', _vv)} := by\n"
```

and must also pass the second environment, exactly as `eval_eq_mojo_test`
just below it does with `{_cf2_text if '_cf2_text' in locals() else
'(fun name arg0 arg1 => 0)'}`.  One reader for "the environments this
program's AST needs", read by both sites, is the fix; the two copies are why
the universal and the concrete instances disagree.

Regression: `test_reg_formal_ast_bridge_two_arg.py` should gain a Lean
assertion (skipped without `ProofLib.olean`, as the file's other Lean rows
are) that `_check_proof` accepts the two-argument program's proof.

Related: `FORMAL_ast_bridge_cannot_state_a_user_call_of_two_or_more_arguments`
is fixed and its doc deleted; this is the concrete-instance half that fix did
not carry.
