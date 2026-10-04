# INTERP: a MULTI-item specialization bracket drops the call-time arguments and answers None

**Area:** INTERP (`myinterpreter.py`, `_MojoBoundComptimeFunction`). Found
2026-10-03 on `work/formal18-tile-specialization`, while differential-testing
the two-bracket form of a specialization through a function value — the shape
`std/algorithm/backend/tile.mojo`'s `tile2d` writes
(`workgroup_function[tile_size_x, tile_size_y](x, y)`). **NOT FIXED. It is not
about function values: the same program fails with the callee named directly,
which is what makes it separable from the work that found it.**

## What was run

```sh
export PATH=/opt/homebrew/bin:$PATH
cat > .tmp/mb.mojo <<'EOF'
def add(a: Int, b: Int) -> Int:
    return a + b

def direct(x: Int) -> Int:
    return add[2, 5](x)

def main() -> Int32:
    print(direct(10))
    return 0
EOF
python3 fire.py run .tmp/mb.mojo
```

```
  File ".../myinterpreter.py", line 5281, in _apply_binary_op
    return self._wrap_int(left + right)
TypeError: unsupported operand type(s) for +: 'int' and 'NoneType'
```

`add` is NOT generic — it has no comptime parameters — so the bracket binds
nothing the callee declares, and `add(2, 5, 10)` in Python is a `TypeError` for
the third argument rather than a `+` on `None`. What the interpreter computes is
worse than an arity error: the callee body ran with a parameter bound to `None`.

## What I see, measured across the three shapes

| program | interpreter | this repository's `formal` path |
|---|---|---|
| `widen[3](5)`, `widen` a one-parameter generic, called BY NAME | **15** | 15 |
| `widen[3](5)` through a function VALUE (`call_it(widen, 5)`) | **15** | 15 |
| `add[2, 5](10)` called BY NAME | **`None` → TypeError** | refused: "`add[…](…)` is a subscript whose index is a tuple" |
| `f[2, 5](x)` through a function VALUE | **`None` → TypeError** | **7** (`add(2, 5)`, the third argument dropped) |

So a ONE-item bracket is fine on both engines and through both callee kinds; a
TWO-item bracket loses the call-time arguments on the interpreter whichever way
the callee is reached.

**The one-item case forwards its trailing arguments, which is what makes this
specific to a MULTI-item bracket and is the measurement this file exists to
take:**

```sh
cat > .tmp/mb3.mojo <<'EOF'
def widen[x: Int](a: Int, b: Int) -> Int:
    return a * 100 + b + x

def direct(y: Int) -> Int:
    return widen[3](y, 7)

def main() -> Int32:
    print(direct(5))
    return 0
EOF
python3 fire.py run .tmp/mb3.mojo
510                      # 5*100 + 7 + 3 — both call-time arguments arrived
```

So the trailing arguments are NOT dropped in general: with one bracket item they
are appended after the bindings, and with two or more they are not. That is a
different defect from "the items replace the arguments" and it is why the second
row of the table cannot be read as the general rule.

**What is right about the `formal` side, for the record.** A bracket on a value
with NO declaration is a specialization by
`formal/model.py::value_call_bracket_reading` and its items become leading
arguments, so `f[2, 5](x)` reaches `add` as `add(2, 5)` and the third argument is
dropped by the ABI, giving `7`. The same source spelled with a NAME is refused
outright, because this build has `add`'s declaration and can see it declares no
comptime parameters — a strictness the value path cannot have, and the
documented unagreed direction of
`bugs/FORMAL_function_value_calls_are_not_proved_to_be_calls.md`.

## What I expected

Either an arity error naming the extra argument, or `7` (the interpreter's
documented rule for a call-site subscript is to bind the items to comptime names
BY POSITION and pass the rest through — `_parse_generic_params_capture`'s
docstring, "enough for the interpreter to bind a call-site subscript
(`f[Int32]()`) to names by position"). `None` is neither: it is a body run with
an unbound parameter.

## The next step

`grep -n '_MojoBoundComptimeFunction' myinterpreter.py`, then the `__call__` at
`myinterpreter.py:1075` (`func._invoke(interp, self.comptime_bindings, args,
kwargs)`). The fix is to forward `*args` after the bracket bindings rather than
the bindings alone, and to check the arity the same way the ONE-item path
already does — a specialization of a function with no comptime parameters
supplies items that bind nothing, which is a program whose own declaration
refutes it and which this engine already refuses elsewhere.

The measurement above narrows the search: look for the branch that binds a
bracket of length != 1 (a `TupleExpr`/`ListExpr` index, or a loop over
`len(items)`), because the length-1 path demonstrably forwards `*args` and the
longer one demonstrably does not.
