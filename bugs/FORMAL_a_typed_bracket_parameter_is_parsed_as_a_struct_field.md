# FORMAL_a_typed_bracket_parameter_is_parsed_as_a_struct_field: a one-field
# instantiation with a VALUE argument SEGFAULTS when a free function takes it

**Area:** `fire_compiler.py`'s struct parser (the field list of a bracket with a
typed parameter), surfacing through `formal/build.py::_frame_receivers` /
`_parameter_frame_contract` and `formal/build.py::check_imported_frame_handoffs`.
**Both architectures.** Found 2026-10-12 while landing the comptime VALUE
argument (`bugs/FORMAL_an_explicit_parameter_list_naming_a_comptime_value.md`),
but it is NOT caused by that change: it is reachable today through the LITERAL
DISPLAY spelling, which was already a demand before it. **Not fixed here** — the
first fix is in `fire_compiler.py`, the shared parser, which owes a full
`make gate` this worker is not allowed to run.

## What I ran

The parser, on the declaration of every value-parameterised template:

```console
$ python3 -c '
import sys; sys.path.insert(0,".")
from formal.build import parse_module
for src in ["struct Box[T]:\n    var v: T\n",
            "struct Tagged[T, origin: Int]:\n    var v: T\n"]:
    st = list(parse_module(src))[0]
    print(repr(src.splitlines()[0]), "->",
          [(f.name, f.type_ann) for f in st.fields])'
'struct Box[T]:'        -> [('v', 'T')]
'struct Tagged[T, origin: Int]:' -> [('origin', 'Int'), ('v', 'T')]
```

A TYPED bracket parameter (`origin: Int`) becomes a struct FIELD. A type-only
one (`T`) does not. `elaborate.type_param_names` reads the bracket off the
SOURCE text and so is right — the AST is what is wrong.

That phantom field has a consequence the emitters cannot see coming, and it is a
wrong answer rather than a refusal. The two-file program below is
`struct Tagged` in a library and a free function taking its instantiation; the
caller passes a one-field struct (its receiver IS its field, so the value goes
in a register) while the callee's own compilation classified the parameter as a
FRAME address of the (phantom) multi-field `Tagged`:

```mojo
# tagged.mojo
struct Tagged[T, origin: Int]:
    var v: T

def untag_int(t: Tagged[Int, 7]) -> Int:
    return t.v
```

```mojo
# main.mojo
from tagged import Tagged, untag_int
def main():
    var t = Tagged[Int, 7]()
    t.v = 5
    print(untag_int(t))
```

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove -o .tmp/g.bin .tmp/ep7/g.mojo      # Built
$ .tmp/g.bin
Segmentation fault: 11                             # exit 139
```

The manifest the library publishes is the defect in one line:

```console
$ GMOJO_HOME=$PWD/.tmp/gmj python3 fire.py build --formal --no-prove \
      -o .tmp/g.bin .tmp/ep7/g.mojo
$ python3 -m json.tool .tmp/gmj/cas/formal-imports/arm64/tagged.*.manifest.json \
    | grep -A1 frame_params
      "frame_params": [
          [ "Tagged" ]          # a FRAME of the bare template name
      ]
```

With the value argument REMOVED (`struct Tagged[T]`, `def untag_int(t: Tagged[
Int])`) the same build publishes `"frame_params": [null]` — an ordinary word —
and the program prints `5`. So the disagreement is exactly the value argument,
and `_frame_receivers` sees two structs for it: `Tagged` (the template, with
`origin` materialised as a field, hence multi-field/framed) and the real
instantiation `Tagged_1_T_3_Int_6_origin_1_7` (one field). The parameter's
annotation `Tagged[Int, 7]` resolves through `annotation_base_name` to the bare
`Tagged`, and the caller's value is read as that frame.

`_parameter_frame_contract` answers `[["Tagged"]]` from the phantom struct, and
`check_imported_frame_handoffs` never fires because a one-field struct is passed
by VALUE — the hand-off is parked only for a frame address, so the contract is
never consulted on the path that would have caught it.

## It is reachable WITHOUT a comptime value argument, through a display

The literal spelling is not the only door. A DISPLAY value argument
(`Tagged[Int, [1, 2]]`) was already a demand before 2026-10-12
(`test_formal_monomorph.py::test_a_value_bracket_argument_reaches_the_boundary_symbol`),
and a one-field struct with one SEGFAULTS the same way on both machines:

```mojo
# tagged.mojo
struct Tagged[T, keys: List[T]]:
    var v: T

def untag_int(t: Tagged[Int, [1, 2]]) -> Int:
    return t.v
```

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove -o .tmp/l.bin .tmp/epB/l.mojo      # Built
$ .tmp/l.bin
Segmentation fault: 11                             # exit 139
```

With TWO fields instead of one the cross-image frame contract DOES fire and the
program is refused (`"a Tagged receiver is passed to untag_int() … whose frame
is Tagged_1_…"`), which is why this is a hole in that check rather than in the
contract itself.

## The exact next step

1. **The parser.** `fire_compiler.py`'s struct-head parser must keep a typed
   bracket parameter out of `StructDef.fields` — only `var`/`let` declarations
   in the body are fields. That is the root cause and it is the change that owes
   a full `make gate`; the instantiated structs are already correct
   (`formal/monomorph.py::instantiate` drops the whole head), so nothing in
   `formal/` compensates for it today.
2. **The contract, as the belt-and-braces half.** A ONE-FIELD struct argument
   reaching an imported callee whose contract names a frame is currently not
   parked, so the disagreement is invisible. `_parameter_frame_contract` should
   publish `["one-word"]` for such a parameter (it has the `declared` evidence)
   and the hand-off should be parked for a one-word receiver too, so the pair
   refuses instead of segfaulting even if a second route to the phantom struct
   exists.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove -o .tmp/l.bin .tmp/epB/l.mojo && .tmp/l.bin   # SIGSEGV, exit 139
$ python3 -c 'import sys;sys.path.insert(0,".");from formal.build import parse_module;
print([(f.name,f.type_ann) for f in list(parse_module("struct T[x: Int]:\n    var v: Int\n"))[0].fields])'
# [('x', 'Int'), ('v', 'Int')]
```
