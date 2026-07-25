# CODEGEN: a bound method referenced as a plain value (not called) fails to compile

## Repro

```python
class C:
    def b(self):
        return 42
    def a(self):
        f = self.b       # reference the method as a value, don't call it here
        return f()

def main():
    c = C()
    print(c.a())
main()
```

- `python3 mojo.py run repro.py` (interpreter): correct — prints `42`.
- `python3 mojo.py build repro.py -o out`: fails to compile:
  ```
  repro.py:5:13: error: 'C' has no member named 'b'
  ```

Calling the method directly (`return self.b()`, no intermediate variable)
compiles and runs correctly — the bug is specific to referencing a bound
method as a value (to store, pass as a callback, etc.) rather than calling
it immediately. Definition order doesn't matter (confirmed with `b` defined
both before and after `a` in the class body — same failure either way).

Real stdlib trigger: `Lib/cmd.py:112`:
```python
readline.set_completer(self.complete)
```
(`self.complete` passed as a callback value to `readline.set_completer`,
not called) — `bugs/COMPILE_FAIL_cmd.md`. `Cmd.complete` is a real method
defined later in the same class (line 261); the compiler reports `'Cmd' has
no member named 'complete'; did you mean 'completekey'?`, confusingly
suggesting an unrelated attribute.

## Root cause

Not yet traced into `gimple_codegen.py`'s member-resolution code — worth
investigating whether the struct/class member-lookup machinery used when
lowering a `MemberExpr` in a CALL position (`self.b(...)`) differs from
the one used when a `MemberExpr` appears as a plain value-producing
expression (`f = self.b`), and the value-position path is missing method
lookup entirely (only checking data fields, hence the "no member named"
error, and the `did you mean` suggestion only searches data-field-shaped
names like `completekey`).

## Impact

Storing/passing a bound method as a first-class value (for a callback,
decorator, functools.partial, event handler registration, etc.) is a
common Python idiom — this is likely to affect a meaningful number of real
stdlib files beyond `cmd.py`.

## Suggested fix

Not yet planned — needs investigation into how `gimple_codegen.py` lowers
`MemberExpr` in a CALL context (where it evidently already knows how to
resolve a method by name — reuse whatever that lookup does) versus a
plain expression-value context (where it currently seems to only search
data fields). The likely correct representation for "a method referenced
as a value" is some form of bound-method/closure value (capturing both the
struct instance pointer and the method's function pointer) that can later
be invoked via a call — check whether this codegen already has a bound
value representation used elsewhere (e.g. for storing free functions as
values, closures, or callback registration) to reuse rather than invent a
new one.
