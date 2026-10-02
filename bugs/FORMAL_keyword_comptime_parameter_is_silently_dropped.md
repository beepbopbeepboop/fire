# A KEYWORD comptime parameter is silently bound to 0: `f[*, scale=2](x)` drops the `scale=2`

**Area:** FORMAL (the comptime specialization ABI; the shared
`mojo/middle/comptime.py`). Found 2026-10-01 on `work/formal2-re-and-slice`
while fixing the derived field set. **NOT FIXED — pre-existing, and NOT this
branch's construct.**

## What was run

```
$ cat kwcp.mojo
struct Cell:
    var value: Int
    var pad: Int
    def show[*, scale: Int](self, n: Int) -> Int:
        return self.value * 100 + scale * 10 + n

def main() -> Int:
    var c = Cell()
    c.value = 4
    c.pad = 1
    printf("v=%d", c.show[scale=2](3))
    return 0

$ python3 fire.py build --formal --no-prove --backend=arm64 -o kwcp.out kwcp.mojo
Built: kwcp.out  [arm64/macho]
$ ./kwcp.out
v=403                          # 4*100 + 0*10 + 3.  CPython says v=423.
```

**`403` instead of `423` is `scale = 0`, not `scale = 2`.** The argument is
read, added, multiplied by ten and printed — so the program computes an answer,
exits 0, and is wrong by exactly the dropped parameter. Nothing crashes and
nothing is refused.

## It is pre-existing, and the tree it was measured on

Byte-identical output on this branch and on the tree with `formal/model.py` at
its previous contents (`v=403` both). The same drop is visible in a
non-comptime-reading form: a bracketed method whose whole body is
`self._value + T + k` gives `v=8` where CPython says `v=15` — again `T = 0`.

## Where it is, and why it is silent

`mojo/middle/comptime.py`'s `specialization_args` (`:282`) is the one function
that decides which expressions bind a generic's comptime parameters at a call
site. It reads the bracket out of `call.func.index` and nothing else:

```python
idx = call.func.index
supplied = list(idx.elements) if isinstance(idx, (_fc.TupleExpr,
                                                  _fc.ListExpr)) else [idx]
```

`SubscriptExpr` keeps POSITIONAL brackets in `index` and **keyword** brackets in
a separate `attrs` field (`fire_compiler.py:408`, `attrs: object = None   #
keyword bracket params, e.g. MLIR op attrs [pred=..., _type=...]`). `attrs` is
never consulted, so a keyword-supplied comptime parameter is not "missing" — it
is **invisible**, and the length check then pads it with
`IntLiteral(value=0)`, which is this backend's documented "unknown compile-time
value".

The `0` padding is what makes it silent rather than loud. It is the right answer
for a comptime parameter the call site genuinely does not supply, and it is
indistinguishable from the answer for one that was supplied and thrown away. A
program that relies on the default cannot tell the difference, and a program that
supplies the value explicitly gets a number the source never wrote.

**This is the same class as the docs in `bugs/FORMAL_*_specialization*` and it is
distinct from them.** `bugs/FORMAL_x86_64_comptime_specialization_abi.md` is
about x86-64 not PASSING the comptime arguments at all (arm64 does, and is
right); this is about arm64 not READING the keyword ones. Neither backend's
problem is the other's.

## Blast radius, and who it belongs to

`mojo/middle/comptime.py` is shared: the gimple compiled path and the x86-64
formal path use the same `specialization_args` as arm64 (arm64 reaches it
through `formal/arm64_codegen.py`'s `_specialization_args`, `:5704`). So a fix
here moves all three, and that is the right place for it — but it is a change
to the comptime ABI rather than to a formal lowering, and it is NOT claimed by
`construct:re-merge-and-builtin-slice`.

Measured exposure of the shape in the stdlib: the keyword-bracket spelling
`def m[*, name: T](...)` is how the stdlib writes a defaulted comptime parameter,
and `std/collections/optional.mojo`'s `_write_to[*, is_repr: Bool]` plus
`std/collections/list.mojo`'s `_write_self_to[*, is_repr: Bool]` are two
instances of it in files the field-set fix already unblocks. A full sweep was NOT
run to count them — that is the integrator's.

## The next step

One branch in `specialization_args`: when `call.func.attrs` is non-empty, pair
each `(name, expr)` with the comptime parameter it names, in `ct_params` order,
and bind BY NAME for those rather than by position. Two details decide whether
it is right, and both are the reason this was not a one-liner here:

1. **`*,` keyword-only parameters.** `def m[*, scale: Int]` parses `scale` as a
   keyword-only parameter, so a `attrs` entry and a positional `index` entry
   never compete for the same slot — but a mix (`def m[T, *, scale: U]`) does,
   and the pairing has to respect which is which. `comptime_params` is the
   declared record to pair against.
2. **A keyword for a name the generic does not declare.** Today that is
   ignored (the docstring's own rule for over-supplied arguments), and it should
   stay ignored rather than become a hard error, for the reason that docstring
   gives: `comptime_params` is a LOSSY record, so an unrecognised bracket is far
   more often a parser gap than a mistake in the source.

Two cases for `test_formal_specialized_method_call.py` (which is where the
positional-order case already lives and pins):

* `def show[*, scale: Int](self, n: Int)` called as `c.show[scale=2](3)` —
  differential against CPython, arm64.
* a MIX, `def mix[T: Int, *, by: Int](self)` called as `c.mix[3, by=10]()`, so
  the positional/keyword split is exercised in one program and a fix that bound
  everything by position produces a different number rather than a failure.

## What was measured, and what was not

* The repro above, on arm64, on this branch and on the previous
  `formal/model.py`.
* That a positional-only bracket of the same method is correct (`v=15`), so the
  defect is specific to the `attrs` half and not to specialization as a whole.
* That `attrs` is a distinct field on `SubscriptExpr` and is read by other paths
  (`formal/model.py:4855`, `formal/arm64_codegen.py:3491`), so the parser does
  carry it — only this binding ignores it.
* **NOT measured: the x86-64 and gimple answers for the same source**, and NOT
  measured: the sweep count of affected files.