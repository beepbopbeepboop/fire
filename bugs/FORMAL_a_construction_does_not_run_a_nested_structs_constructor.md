# A construction that brings up a nested frame does not RUN that frame's constructor, so the frame holds zeros where the source wrote stores

**Area:** FORMAL (a SILENT WRONG ANSWER in the frame bring-up, both backends).
Found 2026-10-04 on `work/formal29-3` while landing step 2 of
`FORMAL_method_call_on_a_construction_is_not_rewritten.md` (deleted with its fix).
**NOT FIXED. It is one decision in one emitter arm in each backend, and the
decision is which of two answers the bring-up owes.**

## What was run

```console
$ cat .tmp/nested_init.mojo
struct Opt:
    var v: Int
    var has: Int

    def __init__(out self):
        self.v = 41
        self.has = 1

struct Box:
    var inner: Opt

    def get(self) -> Int:
        return self.inner.v

    def poke(self, x: Int):
        self.inner.v = x

def main() -> int:
    var b = Box()
    printf("b=%d\n", b.get())
    return 0

$ python3 tools/memslot.py --gb 8 --label probe -- \
      python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/x .tmp/nested_init.mojo
Built: .tmp/x  [arm64/macho]
$ ./.tmp/x
b=0                     # CPython: b=41
$ …--backend=x86_64 …; ./.tmp/x
b=0                     # CPython: b=41
```

Builds, runs, exits 0, and prints `0` where CPython prints `41`. **The store
never runs and nothing reports it.**

## Why

A construction brings a nested frame up in TWO different places, and they are not
the same code.

* **A construction of the struct itself.** `var o = Opt()` lowers the
  constructor body into the fresh block at the construction site
  (`formal/model.py::init_body_stores`), so `Opt`'s `__init__` runs. Measured:
  the same file with `var o = Opt()` prints `o=41` on both architectures.
* **A construction that brings a FRAME up** — `Box()` — is the emitter's own
  placement walk. `formal/model.py::struct_default_word`'s `("nested_frame", …)`
  arm hands `arm64_codegen.py:8470` / `x86_64_codegen.py:10145` the nested struct,
  and each does `_emit_frame_nested` → `_emit_frame_defaults` →
  `_emit_frame_nested_addresses`. **`_emit_frame_defaults` writes each field's
  CLASS-LEVEL DEFAULT, and nothing calls the nested struct's `__init__`** — in
  Mojo `T(...)` calls it, and a frame bring-up is not a construction call.

So the two paths disagree about what `T()` means, and the disagreement is
invisible in both directions: `var o = Opt()` is right and `var b = Box()` is
wrong, from the same declarations in the same file.

**It is not only the one-field shape.** A MULTI-field holder does it too — the
nested frame is placed the same way:

```console
$ … struct Wide: var inner: Opt; var pad: Int … var w = Wide(); w.get()
w=0                     # CPython: 41
```

and at DEPTH 2, where the bring-up writes the inner frame's ADDRESS
(`_emit_frame_nested_addresses`) and so leaves a whole subtree at defaults:
`struct Deep: x, y` / `struct Inner: a, b, d: Deep` / `struct Outer: n: Inner`
answers 0 for `Outer().read_d().x` where CPython says whatever `Deep`'s
constructor wrote.

## What is already true, and is the reason this is a decision and not a bug in
## one place

**The store-initialised shape is REFUSED, not answered, when the stores are on
the HOLDER.** `struct Box: var inner: Opt` with `Box.__init__` doing
`self.inner.v = 41` is refused by `formal/model.py::construction_init_body_refusal`
("a local assignment (`self.inner.v = …`)"), and that is right. What is missing is
the same refusal, or the same inline, one level DOWN — for the nested struct's own
constructor.

**The lift over this shape is now refused too**, so nothing new can be wrong
because of it: `formal/build.py::_call_receiver_verdict`'s `construction_frame`
verdict, gated on `formal/model.py::construction_bringup_is_complete`, which
refuses a construction receiver when any struct in the nested subtree declares an
`__init__`. Pinned by
`test_formal_receiver_position.py::refuse_a_method_call_on_a_construction_whose_nested_constructor_is_not_run`,
whose message names the `__init__` by name. That gate is a consequence of this
bug, not a fix for it: `var b = Box(); b.get()` — no construction receiver, no
gate — still answers 0.

## The next step, and the two answers

Both are in the same three lines of each backend's construction arm, so this is
one decision rather than a project:

1. **Inline the nested constructor's stores at the bring-up**, the way
   `init_body_stores` does for the construction of the struct itself. The stores
   are `self.<field> = <expr>` in the NESTED struct's own `__init__`, the frame's
   slots are known (`_emit_frame_defaults` already writes them), and the
   expressions are in the enclosing scope unless the constructor binds a local —
   which is exactly the condition `init_body_stores` already refuses on. **This is
   the fix that makes the answer CPython's**, and it is the one to take: a refusal
   would have to name every program that constructs a holder whose nested struct
   has a constructor, and those programs are ordinary.
2. Refuse the construction instead, by the same reasoning
   `construction_init_body_refusal` uses. Correct, and it buys nothing over the
   wrong answer for the corpus — `struct_default_word` would need a fourth kind
   beside `("none")`, `("int")`, `("string")`, `("opaque")` and
   `("nested_frame")`, which is a wider change to the constructor layout table
   than inlining is.

**The cost, measured where it is knowable.** Nothing in this repository's own
`*.mojo`/`*.py` constructs a one-word holder of a nested frame whose nested
struct declares an `__init__` (grep for a `struct` whose sole field's declared
type is another struct of the same file, then for an `__init__` on the inner
one), so the answer is 0 files here; the stdlib is not editable from a repository
worktree. **That census is a grep and has not been run** — the next session should
run it before choosing, because inlining is the right answer and a census is
what says what it costs.

**Not measured:** whether the constructor's stores can be evaluated at the
construction site when they name something the enclosing scope does not have (a
nested `__init__` parameter is refused by `init_stores_a_parameter_struct`
already, so the delegating case is covered); and the DEPTH-2 and multi-field
variants above are asserted from the same code path rather than each measured —
they are named as the shapes to check, not as results.

## Reproducing

```console
$ python3 test_formal_receiver_position.py        # 39/39, both architectures
$ python3 tools/memslot.py --gb 8 --label probe -- python3 fire.py build \
      --formal --no-prove --backend=arm64 -o .tmp/x .tmp/nested_init.mojo
```