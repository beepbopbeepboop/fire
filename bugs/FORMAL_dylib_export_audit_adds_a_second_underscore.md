# FORMAL_dylib_export_audit_adds_a_second_underscore: `formal-sweep` is red on master — the audit re-derives a C name the writer already decided

**Not mine, found on 2026-10-03 while re-measuring the dylib-module-body row
(§6 of `bugs/FORMAL_sweep_work_map_2026-10-02_b7.md`, closed the same day), and
it is an UNDECLARED red**: `test_formal_sweep.py::TestDyldProbe` fails in `setUpClass`,
`formal-sweep` is a registered job in the `proofs` bucket with no `expect=`
(`tools/suite.py:2007`), and nothing in the suite says so. It is a one-line
disagreement between two functions about one spelling.

## What I ran, and what it said

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 test_formal_sweep.py
# ERROR: setUpClass (__main__.TestDyldProbe)
# AssertionError: building __pkg.mojo failed: _helper_twice_9f63a2. A consumer
# that binds one of these dies in dyld at load, and its own bind audit cannot
# catch it: the name comes from a manifest, so it reads as provided.
```

Reduced to the two files the fixture is made of, outside the suite:

```sh
mkdir -p .tmp/usfix
printf 'fn twice(a: Int) -> Int:\n    return a + a\n' > .tmp/usfix/_helper.mojo
printf 'from ._helper import twice\n\nfn main() -> Int:\n    var x: Int = twice(21)\n    return x\n' \
  > .tmp/usfix/__pkg.mojo
python3 fire.py build --formal --no-prove -o .tmp/usfix/pkg.aout .tmp/usfix/__pkg.mojo
# build: __pkg.mojo imports '._helper', which cannot be built either:
# _helper.mojo: this library's manifest advertises 1 export(s) its own image does
# not define: __pkg__helper_twice_9f63a2.
```

**It is pre-existing, measured rather than assumed.** I reverted this branch's
`formal/` changes (`git diff c5ab524d..HEAD -- formal/ > patch; git apply -R
patch`), rebuilt the same two files, and got the byte-identical refusal; the
patch was then re-applied and the tree is clean.

## The cause: two answers to "what is the C name of this export"

`formal/macho_linker.py::_export_trie` writes the export into the trie, and
**prepends dyld's underscore only when the name does not already have one**:

```python
raw = (export["symbol"] if export["symbol"].startswith("_")
       else "_" + export["symbol"]).encode("utf-8")
```

`formal/build.py::_advertised_but_absent` verifies the same library by
**re-deriving the name and always prepending**:

```python
    # A Mach-O name is its C name with dyld's leading underscore, which is what
    # `_c_export_name` takes back off in the other direction.
    return [s for s in advertised if f"_{s}" not in defined]
```

`defined` comes from `macho_dylib_exports`, which returns the trie's own bytes.
So for every export whose ABI symbol ALREADY begins with an underscore the check
looks for a name one underscore longer than the one that is really there, does
not find it, and reports the library as advertising an export its own image does
not define.

**Measured, from the artifacts this tree built:**

| artifact | trie / `macho_dylib_exports` | manifest symbol | audit looks for |
|---|---|---|---|
| `helper.f31a7abc4656.arm64.dylib` | `_helper_add_2dbb98` | `helper_add_2dbb98` | `_helper_add_2dbb98` ✓ |
| `relpkg__helper.810655b26e66.arm64.dylib` | `_relpkg__helper_twice_9f63a2` | `relpkg__helper_twice_9f63a2` | `_relpkg__helper_twice_9f63a2` ✓ |
| `__pkg__helper.810655b26e66.arm64.dylib` | `__pkg__helper_twice_9f63a2` | `__pkg__helper_twice_9f63a2` | `___pkg__helper_twice_9f63a2` ✗ |

Only the third is wrong, and the difference is exactly one leading underscore in
the module's own NAME: `abi_module_name` flattens the dots, so a relative import
inside a module called `__pkg` produces the ABI prefix `__pkg__helper`. That is
the shape `TestDyldProbe` exists for — its own comment says the prefix must begin
with an underscore, and `test_formal_sweep.py` says of that fixture "The parent
has to be a module whose own NAME begins with an underscore, because that is the
only place one survives".

So the defect is in the only shape the fixture was built to cover, and the
fixture is not asserting a wrong thing: the library the writer produced carries
the export under the name its own writer chose.

## The next step, and what "correct" means here

Make the audit ask the writer instead of re-deriving. `_export_trie` already owns
the spelling (it is what dyld has to find), so the trie reader and the verifier
should share ONE function that maps an ABI export symbol to the bytes the trie
carries — the same relationship `_bind_info` states for the other direction — and
`_advertised_but_absent` should ask it. A local `f"_{s}"` in a second file is the
third statement of this rule in this tree; the bug is that nothing made the first
two share it.

**Two things to decide, and the second is why this was not fixed in passing:**

1. Which spelling is authoritative — `_export_trie`'s conditional prepend, or the
   unconditional one. The conditional one is what the other two rows in the table
   above demonstrate for their own prefixes (`_helper_add_2dbb98` and
   `_relpkg__helper_twice_9f63a2` are in their tries and their consumers bind
   them), so the audit is the side that must move. **Not measured here**: nothing
   ever links the `__pkg__helper` library, because the refusal stops the build —
   so whether dyld loads that image is the first thing to check after the fix,
   and the fix should be validated by loading it rather than by re-running the
   audit.
2. Whether an export symbol beginning with an underscore should be allowed at
   all. `formal/build.py::_c_export_name` answers "no" for a name beginning with
   two underscores — but that is about names dyld binds as C symbols, which is a
   different question from what the TRIE carries for this path's own
   `mod.fn` naming. Answering it changes what is exported, and that is a design
   decision, not a spelling fix.

A test belongs next to whichever way it goes: build a module whose ABI prefix
begins with an underscore and assert the audit ACCEPTS the library it just wrote
(the `__pkg__helper` case above is the smallest), beside the existing
`_advertised_but_absent` coverage — and while there, a library that advertises a
name its image really lacks must still be refused, or the fix has removed the
check rather than corrected it.

Until then `formal-sweep` is red in the `proofs` bucket for a reason that is a
compiler bug in the export audit, not a defect in the sweep.