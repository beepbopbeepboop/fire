# plan/step-19b: the formal link line opts into the optional unit a word-shaped call names
Class: mid      Size: M      Depends: 19a      Blocks: 19c
Source: `bugs/FORMAL_known_limits.md` §3.1; `formal/build.py::_runtime_library_for` (:21880), `_runtime_word_calls` (:21818), call site at :2285-2287.

## Current state (verify first: `grep -n "def optional_runtime_dylib" build_stdlib_dylib.py` finds 19a's function)
- `_runtime_library_for(ordered, arch, fmt)` returns `(one lib entry, covered names)`; at :2285 `runtime_lib, runtime_calls = ...; if runtime_lib is not None: linked = linked + [runtime_lib]` appends ONE entry LAST. A name that is word-shaped but not in the core library's export map (e.g. `mojo_sqlite3_close`) is dropped and later refused ("the library does not export the name").
- Pinned: `test_formal_runtime_link.py::test_word_shaped_but_not_exported_links_nothing` (:341) — it uses a sqlite3 name today; this step must DELIBERATELY update it (see Work order 4).

## Decisions already made
- `_runtime_library_for` returns `(list_of_lib_entries, covered_names)`: the core library when any covered name is in its map, plus, for each optional unit whose namespace (`build_config.optional_unit_namespace`) prefixes a still-uncovered word-shaped name, `load_dylib_manifests([optional_runtime_dylib(unit, arch)])[0]` (build its manifest the way `runtime_library` does) — in registry order, after the core library. A name is covered by the FIRST library whose map contains it.
- The call at :2285 becomes `linked = linked + runtime_libs`. Everything downstream (bind ordinal, `_audit_link_line_containers`, LC_LOAD_DYLIB) already treats entries uniformly (docstring of `runtime_library`); do not special-case.
- The rule "a box in an argument or the return is refused regardless" is unchanged: only `entry['word']` names are considered (`_runtime_word_calls` already filters).
- ELF: no optional unit; same refusal as today.

## Work order
1. Change `_runtime_library_for` and its single caller. `grep -n "_runtime_library_for" formal/*.py test_*.py` for any other caller/test and update.
2. Read `test_word_shaped_but_not_exported_links_nothing` (:341). If its program calls a sqlite3 word-shaped name, it now LINKS (that is the feature); change the program to a word-shaped `mojo_*` name that is in no unit namespace and absent from the core map. Find one: `python3 -c "from formal import model as M; import build_config as B; from formal.build import runtime_library; ns=tuple(B.optional_unit_namespace(u) for u in B.optional_unit_names()); m=runtime_library('arm64','macho')['map']; print([n for n,e in M.runtime_abi().items() if e['word'] and n.startswith('mojo_') and not n.startswith(ns) and n not in m][:20])"`. If the list is empty, delete the test, and say in the §3.1 Status that the property it pinned has no remaining witness.
3. Add test `test_optional_unit_links_when_named` is 19c's job; here only confirm with a manual build that `mojo_sqlite3_close(0)` builds (record the `linked_dylibs` list).

## Do NOT
- Do not add unit libraries to images that name no unit symbol (`test_a_program_naming_nothing_links_nothing` must still pass).
- Do not catch the build error of a unit library and fall back to the refusal silently.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_runtime_link.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_link_accounting.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_runtime_header_scan.py
python3 tools/plan_index.py --check
```

## Done when
- [ ] all three files green (or same tally as before for pre-existing reds, recorded)
- [ ] a program calling `mojo_sqlite3_close(0)` builds with TWO libraries in `linked_dylibs`

## If stuck
Write which downstream audit rejected the second library into §3.1 Status and stop.
