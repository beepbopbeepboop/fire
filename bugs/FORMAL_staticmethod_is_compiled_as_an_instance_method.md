# FORMAL_staticmethod_is_compiled_as_an_instance_method: a `@staticmethod` gets a receiver it is never passed, and its body is compiled against one

**Status: found and MEASURED, NOT fixed.** It is a neighbour of
`construct:declared-param-vs-call-sites` — it is one of the 13 files that
construct names, and it is not that construct's fix. Found 2026-10-01 while
splitting that row (`bugs/FORMAL_declared_parameter_against_its_call_sites.md`
§5); the measurement is repeated here so this doc stands on its own.

`fire_compiler.method_receiver_kind` is the tree's single rule for "does this
struct method declare a receiver" — decorator first, first parameter's name
second — and it is read in `mojo/middle/coro.py` (twice), `mojo/middle/module_shared.py`
and `mojo/backend_gimple/cpp_async.py`, with `emit_methods.py` reading the
verdict recorded at registration. Two readers in `formal/build.py` consult
only the parameter list, and between them they give a `@staticmethod` a receiver
on BOTH sides of a call: the definition is compiled with one and the call site
passes one, for a function whose parameter list has neither.

## 1. Smallest reproducer (16 lines), and what it says

```mojo
# .tmp/probe/shapes/g1.mojo
struct Vec:
    var a: Int
    var b: Int

struct R:
    var k: Vec
    var c: Vec

    def step(mut self) -> Int:
        var counter = self.c
        return self._single(counter)

    @staticmethod
    def _single(counter: Vec) -> Int:
        return counter.a + counter.b

def main(n: Int) -> Int:
    var r = R()
    r.k.a = 1; r.k.b = 2
    r.c.a = 7; r.c.b = 8
    return r.step()
```

CPython's transcription of the same program returns **15**.

```
$ python3 fire.py build --formal --no-prove .tmp/probe/shapes/g1.mojo
build: R__single() declares 'counter' as Vec, so it is compiled with 'counter'
as the ADDRESS of a frame of 8-byte slots, where every field is a load at
`base + 8k` — and every call site in this image hands it something else:
R__single(self, counter) passes a R frame.
```

Read the call spelling: **`R__single(self, counter)` — two arguments to a
one-parameter function.** Instrumenting `_check_declared_parameter` says where
each half comes from:

```
DBG callee=R__single position=0 p=counter struct=Vec
DBG params=['counter']
DBG fn=R__single holders=['counter', 'self'] hstruct={ self:['R'], counter:['Vec'] }
```

`self` is in a `@staticmethod`'s holder set. And the reason the message is about
`counter` at all is that **position 0 of the call is the receiver**, which the
one-parameter definition reads as `counter`.

## 2. The two halves, one line each, both measured

**(a) The definition half.** `formal/build.py:2498`:

```python
if owner is not None and owner.name in framed:
    for recv in M.struct_receivers(owner):
        holders[_fn_key(fn)].add(recv)
```

`model.struct_receivers` returns `out = {"self"}` **unconditionally** and then
adds each non-`@staticmethod` method's first parameter. The `@staticmethod` skip
(`if "staticmethod" in _decorator_names(m): continue`) stops the method's first
PARAMETER from being read as a receiver, and leaves the `self` seed standing —
which is right for its other job (deriving the field set, where `self.n` in any
method is a field write) and wrong for this one, which asks about a METHOD while
holding a CLASS answer.

Measured: adding `and F.method_receiver_kind(fn)` to the guard drops `self` from
`R__single`'s holders, and the call-site spelling below becomes the truth.

**(b) The call half.** `formal/build.py:7499`, `_receiverless_methods`:

```python
for m in M.struct_methods(st):
    if not (getattr(m, "params", None) or []):
        out.add(m.name)
```

A receiver-less method is recognised from an **empty parameter list** and
nothing else, so a `@staticmethod` with parameters is not in the set and
`_rewrite_method_calls` prepends the receiver. `def import_module(var module:
String)` in `std/python/python.mojo` is the same defect reached from the other
side, and there the declared-parameter check compares the RECEIVER against the
first declared parameter and every later argument with it — an off-by-one over
the whole parameter list, reported against the wrong argument.

Measured: `or not F.method_receiver_kind(m)` rewrites `self._single(counter)` to
`R__single(counter)` and `Python.import_module("sys")` to
`Python_import_module("sys")`.

## 3. With the declared-parameter refusal lifted, the real refusal appears

Not by accident — the two rules are different, and this is the case where saying
so matters:

```
$ python3 .tmp/probe/nolift.py build --formal --no-prove .tmp/probe/shapes/g1.mojo
build: call R__single(): too many positional arguments (2 for 1 parameter(s);
       the parameters are ['counter'])
```

That is a TRUE statement about the image, and it is why this construct was never
a silent-wrong-answer: the arity check catches the mis-bound receiver before
anything is read through it. **The consequence to plan around: fixing this
UNBLOCKS a different, true refusal rather than making a file build.** Whoever
takes it should expect `philox.mojo` and `python.mojo` to land on the next
refusal, not on `pass`.

## 4. What is left after both halves — the second construct

With (a) and (b) applied together, the reproducer's refusal becomes

```
build: R__single() declares 'counter' as Vec … R__single(counter) passes a
       name, 'counter'.
```

`var counter = self.c` is a read of a `Vec`-typed FIELD of a framed struct, and
the nested-frame placement (`model.struct_nested_frame_fields`) does not place
it — the field's type is spelled `SIMD[.uint32, 4]`, a generic application, and
the placement wants a plain struct name. So `std/random/philox.mojo` is **at
least two constructs** and the second is worth measuring on its own before
anyone promises the file.

## 5. The exact next step

1. Apply (a) and (b), each with the `method_receiver_kind` read, and each with a
   test: a `@staticmethod` with parameters, called as `S.m(x)` and as
   `self.m(x)` from an instance method, executed on both architectures and
   compared with CPython. The obvious home is `test_formal_method_param_field.py`
   (its subject is the receiver/parameter machinery) or
   `test_formal_receiver_position.py`.
2. Re-sweep `std/random/philox.mojo` and `std/python/python.mojo` and record
   where each lands — §3 says do not expect `pass`.
3. Then measure the nested-frame placement of a generic-typed field (§4), which
   is the other half of `philox.mojo`.

Not attempted here: this is `formal/build.py`'s receiver machinery, which is
`construct:receiver-position-and-no-representation` /
`construct:frame-address-escapes` territory, not
`construct:declared-param-vs-call-sites`. The measurement is the contribution.