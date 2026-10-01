# FORMAL_imported_class_reached_as_a_value: `GPUInfo.current_accelerator()` has no symbol to bind, and the diagnostic says it is a VARIABLE

**Status: found, NOT fixed.** Measured 2026-10-01 on the
`formal2-mlir-comptime` branch. It came out of re-measuring
`FORMAL_mlir_unit_hoist_is_unreachable_on_the_new_stdlib.md`, whose claim was
that `_gpu/globals.mojo`'s verdict is not an MLIR symptom — that is right, and
this is the other half of why: the verdict it does report is itself
misdescribed.

## The reproducer (two modules, no stdlib)

`.tmp/x/lib.mojo`

```mojo
struct Info:
    var width: Int
    comptime DEFAULT: Int = 8

    @staticmethod
    def current() -> Info:
        var i = Info()
        i.width = Info.DEFAULT
        return i

def helper(n: Int) -> Int:
    return n * 2
```

`.tmp/x/prog.mojo`

```mojo
from lib import Info

fn main() -> Int32:
    var info = Info.current()
    printf("%d %d %d", info.width, helper(21), Info.DEFAULT)
    return Int32(0)
```

```
$ python3 fire.py build --formal --no-prove .tmp/x/prog.mojo -o .tmp/x/prog
build: prog.mojo imports 'lib', which cannot be built either: lib.mojo: the
library would bind 1 symbol(s) that nothing provides, so it could not be
loaded: Info. Nothing on this link line defines them: not the C library, and
not any library this program linked. Two different causes produce that, and the
distinction is not lost — each name in this list is either a call the codegen
emitted (`info['external_syms']`, so some construct was not lowered and the call
is dangling) or a name that entered the image as a bare reference with no call
site behind it. …
```

`helper(21)` — an imported FREE FUNCTION — is the shape the dylib boundary is
built for. `Info.current()` is a call on an imported CLASS, and it is refused by
a message that cannot say which of its two causes this is.

## Why: a class crosses as a LAYOUT DESCRIPTOR, and a descriptor has no symbol

Exact, and every step is a function someone already wrote:

* `reflect.collect_exports` emits a class as a `SYM_TYPE` entry
  (`reflect.py:267`), alongside a `SYM_METHOD` entry for each of its methods.
* `reflect.emit_table_c` **skips** `SYM_TYPE` entries when it emits the table
  ("TYPE entries are layout descriptors with no runtime symbol — they carry a
  NULL address and are never forward-declared"), and `formal/build.py`'s
  `_abi_symbol` returns `None` for the same kind.
* So `Info_current` crosses as a symbol and `Info` crosses as nothing at all.
* `Info.current()` in the importer is a member read of a bare name, which is a
  bare reference in the image, and the linker's provider check finds nothing
  defining it.

The two-module message is byte-identical at HEAD and with the current tree, so
this is pre-existing and not a regression of anything.

## What is misdescribed, and where

`formal/model.py`'s `module_global_refusal` is what the same read is reported
as on the path where the import resolves (`formal/build.py`'s
`_formal_module_functions`, which is the instrument
`FORMAL_mlir_unit_hoist_is_unreachable_on_the_new_stdlib.md` measured with):

```
'Info' is imported from `lib`, and it is a module-level name of another
module. This path compiles an import into a dylib, and a dylib publishes
FUNCTIONS and folded CONSTANTS … What it cannot publish is a VARIABLE: there is
no storage for one here … So this name's value is a real global with nowhere to
live, which is a property of the value model rather than of this call:
`lib.fn(...)` where `lib` publishes that function as a function is the same
program with a representation.
```

Every clause of that is true of a list or a stream object, and the last two
sentences are **false about a class name**, which has no value to live anywhere.
The repair it offers is also the wrong shape: the source wants a method of a
class, not a free function, and `mod.fn(...)` is not what that file wrote.

`std/_gpu/globals.mojo:74` is the real one — `from .host.info import GPUInfo`
followed by `return GPUInfo.current_accelerator().warp_size`.

## What was tried, and why it is not landed

A sharper refusal was written: an `imported_struct_value_fact` in
`formal/model.py`, appended to `module_global_refusal` at the same place and in
the same "say both facts" shape `type_as_value_fact` uses (so the quoted module
name `tools/formal_sweep.py` reads survives). It is **unreachable on every
measured path**, which is the only reason it is not in the tree:

* the EXECUTABLE path resolves imports first (`formal/build.py:1065`,
  `build_module_dylib` inside `_resolve_imports`), and the library fails to link
  before `_prepare_functions` — and so before `check_module_symbols` — ever runs;
* the DYLIB path (`_formal_module_functions`) passes no `extra_structs`, so an
  imported class is not in `structs_by_name` and the new test cannot fire there
  either.

A 50-line diagnostic that fires nowhere is the same cost-with-no-benefit the MLIR
hoist doc declined to land, so it is written down here instead.

## The exact next step

Two options, and the first is the smaller one.

1. **Decide the linker's two causes for the names it lists.** The message
   already names them ("either a call the codegen emitted … or a name that
   entered the image as a bare reference with no call site behind it") and
   explicitly says the question "is asked nowhere in this backend". The build
   knows the answer for a specific subset: a name that is an imported STRUCT
   (`_imported_structs` already collects the declarations, and
   `module_symbols()` already marks the name `site == "imported"`) cannot be a
   call target. One predicate over the two tables the build already publishes
   would let the linker name the cause for that subset, which is what
   `std/_gpu/globals.mojo` needs and is a change to ONE message.
2. **Make the class crossing the boundary mean something**, so
   `Info.current()` lowers: rewrite `S.m(...)` on an imported class to
   `S_m` (`reflect.export_csym` already computes that symbol, and
   `_rewrite_method_calls` already rewrites `v.m(...)` on an imported VALUE), and
   publish the class's layout through the manifest the way a cross-module frame
   hand-off already does. That is a real capability, not a diagnostic, and it is
   worth more than the message: it is the difference between `std/_gpu/globals.mojo`
   and the twenty-odd files behind it building or not.

Option 2 is the one that changes the sweep's numbers. Option 1 only changes what
one file says about itself, and it is the one to take first because it is small.