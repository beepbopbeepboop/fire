# TEST_formal_sweep_dyld_probe_fixture_cannot_build: a registered test is RED and 15 of its cases are not running

**Area:** FORMAL / TEST (and the dylib export rule behind it). Found 2026-10-03
on `work/formal12-x86-parity-audit` while adding cases to
`test_formal_sweep.py`. **NOT FIXED** — the cause is the dylib export-name rule,
which `formal10-2` holds (`FORMAL_dylib_export_loops_and_frame_bounds`,
`FORMAL_dylib_several_exports_have_no_proved_contract`), so it is reported rather
than edited. It is filed because the symptom is a REGISTERED test that is red on
master and the failure is in `setUpClass`, which is the quiet kind: every case in
the class is skipped and the suite's own output says one error, not fifteen
missing cases.

## What was run

    $ python3 test_formal_sweep.py
    ERROR: setUpClass (__main__.TestDyldProbe)
    ...
    AssertionError: building __pkg.mojo failed: _helper_twice_9f63a2. A consumer
    that binds one of these dies in dyld at load, and its own bind audit cannot
    catch it: the name comes from a manifest, so it reads as provided. …
    Ran 98 tests in 9.462s
    FAILED (errors=1)

`test_formal_sweep.py` is registered as `formal-sweep` in `tools/suite.py`
(bucket `proofs`, no `expect=`), so this is a red in the gate and not a local
one. The build that fails is the fixture `TestDyldProbe.setUpClass` builds for
both architectures:

    __pkg.mojo      from ._helper import twice
                    fn main() -> Int:  var x: Int = twice(21); return x
    _helper.mojo    fn twice(a: Int) -> Int:  return a + a

    $ python3 fire.py build --formal --no-prove --backend=arm64 -o /tmp/x __pkg.mojo
    build: __pkg.mojo imports '._helper', which cannot be built either:
    _helper.mojo: this library's manifest advertises 1 export(s) its own image
    does not define: __pkg__helper_twice_9f63a2. …
    # identical on --backend=x86_64, so it is not an architecture question

**Confirmed pre-existing and not caused by this branch's work.** The fixture text
is byte-identical to the base commit's (`git show c5ab524d:test_formal_sweep.py`
lines 378-381), and this branch's only `formal/` change is `_emit_star_splice` in
`formal/arm64_codegen.py` — a list literal with a `*` operand, of which this
fixture has none, and the refusal is identical on both architectures. Measured by
extracting the base fixture's own two source strings and building them directly
on this tree:

    $ python3 fire.py build --formal --no-prove --backend=arm64 -o /tmp/b __pkg.mojo
    build: __pkg.mojo imports '._helper', which cannot be built either:
    _helper.mojo: this library's manifest advertises 1 export(s) its own image
    does not define: __pkg__helper_twice_9f63a2. …

## The shape, and what is NOT the cause

The sibling fixture `relpkg/{__init__,_helper}.mojo` — the SAME relative import,
in a package DIRECTORY — builds and runs:

    $ python3 fire.py build --formal --no-prove --backend=arm64 -o /tmp/r relpkg/__init__.mojo
    Built: /tmp/r        $ /tmp/r ; echo $?      ->  42

so it is not "a relative import from a module whose name begins with an
underscore" in general. `formal/imports.py::_module_identity` qualifies the
import by the module that spelled it, so the export prefix is
`abi_module_name("__pkg._helper")` = `__pkg__helper`, and the manifest advertises

    __pkg__helper_twice_9f63a2

## Where the two names come apart — measured, not inferred

`formal/build.py::_advertised_but_absent` is the check that refuses, and its own
comment states the convention it applies: *"A Mach-O name is its C name with
dyld's leading underscore, which is what `_c_export_name` takes back off in the
other direction"* — so it looks for `"_" + advertised` in the trie. With the
refusal bypassed (`FB._advertised_but_absent = lambda path, exports: []`, then
`formal.imports.build_module_dylib("__pkg._helper", …, "arm64")`), the dylib
builds and its export trie reads

    ['__pkg__helper_twice_9f63a2']

— the C name ITSELF, with no underscore prepended. The check was looking for
`___pkg__helper_twice_9f63a2`, which is not there. For the working `relpkg` case
the trie holds `_relpkg__helper_twice_9f63a2` and the check's `"_relpkg__…"`
matches, because that C name does not itself begin with an underscore.

**So the disagreement is exactly one case: an exported C name that already starts
with `_`.** `reflect.export_csym` builds it as
`f"{module_prefix}_{base}" + overload_suffix`, and with `module_prefix` =
`__pkg__helper` that is `__pkg__helper_twice_9f63a2` — a name whose leading
underscore the writer's own normalisation then consumes, while the audit's
prepend is unconditional. `formal/build.py:12705` (`_abi_symbol`'s docstring)
states the intended convention: *"It is a C identifier (no leading underscore);
the Mach-O name is that with `_` prepended, which is what the export trie stores
and what dyld looks up."*

**This is the same defect class as `bugs/FORMAL_relative_submodule_abi_prefix_
off_by_one.md`, whose doc was DELETED when its fix landed** — that fix closed the
case where the prefix begins with `_` because the PACKAGE name does not, and left
the case where the prefix begins with `__`. `bugs/TEST_formal_sweep_relative_
import_precondition_is_stale.md` is the surviving doc from the same area and is
about an assertion in this same class, not about this refusal.

## The next step

One decision, in the dylib export-name rule: **which side is right for a C name
that begins with `_`** — the trie entry (`__pkg__helper_twice_9f63a2`, as written
today) or `"_" + C name` (`___pkg__helper_twice_9f63a2`, as
`_advertised_but_absent` and `_abi_symbol`'s docstring both assume). Whatever the
answer, the SAME normalisation has to be applied where the trie is written and
where the manifest is read, or a consumer binds a name the library does not
define — which is the failure `_advertised_but_absent` exists to catch, and which
it currently catches by refusing a correct library.

Then, separately and cheaply: `TestDyldProbe.setUpClass` should not be able to
take fifteen cases down with it. A fixture that cannot be built should skip the
class with the build's own message, not raise from `setUpClass` — the probe's
coverage is worth more than the fixture's exact shape, and right now it is worth
exactly nothing.