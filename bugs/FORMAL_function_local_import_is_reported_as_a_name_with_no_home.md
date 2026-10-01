# FORMAL_function_local_import_is_reported_as_a_name_with_no_home: `import X` inside a function body is not seen as an import at all

**Status: OPEN, one file, and the wrong CLASS as well as the wrong message.**
Found by `construct:type-name-2`'s sweep census on 2026-10-01 (it is 1 of the
2 in-file findings filed under "a TYPE name placed as a value", because the
message it produces is the name-placement one). Not fixed here: it is a
module-resolution question, it is 1 file, and it is not in that claim.

## 1. What I ran and what I saw

`test_runtime_header_scan.py` is the only file in the 623-file x86-64 sweep
whose terminal refusal is a nested import read as a value:

```python
# test_runtime_header_scan.py:67-70
def exports(header):
    import reflect
    return {e['name'] for e in reflect.collect_runtime_exports_h(
        os.path.join(RUNTIME, header))}
```

```
$ python3 fire.py build --formal --no-prove test_runtime_header_scan.py
build: exports: 'reflect' has no home: this module declares no module-level
name by that spelling, and the reading function declares no local or parameter
by it either. This path places a name in a register or a spill slot allocated
for THIS function …
```

Three things are wrong with that, and only the first is about the message:

1. **The message is false about the file.** `reflect` is a module-level name
   **of another module** — that is the fact — and the walk asked the wrong
   question, because the name it never found is the answer. This is the
   `unresolved_name_refusal` sentence in the worst form: a reader sent to the
   register allocator for a fact about the import graph.
2. **The file is in the wrong sweep CLASS.** It is `codegen` (a gap *in this
   file*) where the honest class is the one every other importer of `reflect`
   gets. The rate is computed from this.
3. **The gate that should have fired is documented as top-level only.**
   `formal/imports.py`'s `imported_modules` walks `for st in stmts` and
   explicitly excludes "anything nested inside an `if`/`try` body, which is not
   a top-level statement". A function-local `import` is not top-level either,
   so the same sentence covers it by accident rather than by decision.

## 2. Measured: one line, and it moves the file to the right class

The same file with the `import reflect` hoisted to the top of the module —
a throwaway copy, `.tmp/trhs_toplevel.mojo`, nothing in the repo modified:

```
$ python3 fire.py build --formal --no-prove .tmp/trhs_toplevel.mojo
build: trhs_toplevel.mojo imports 'reflect', which cannot be built either:
fire_compiler.py imports 'importlib', which is a host module (CPython standard
library), which has no Mojo source for this backend to compile
```

So the whole diagnosis is the import, and hoisting the statement changes only
whether the build can SEE it. (In this repository `reflect` resolves to the
repo's own `reflect.py`, which reaches `importlib`; the diagnosis is still a
dependency diagnosis rather than a name-placement one, which is the whole
point.)

**Ceiling: 0 of 1 files reach `pass`; 1 of 1 leaves the `codegen` class.** That
is the honest size of it — and the class change is worth more than the file
count suggests, because `codegen` is the class the headline rate is computed
over (`FORMAL_sweep_work_map_2026-09-30_r2.md` §7 item 3 makes exactly this
argument for the argparse row).

## 3. The exact next step

One of two, and which one is a decision rather than a derivation:

* **Cheap and local.** `formal/imports.py`'s `imported_modules` also collects
  `ImportStmt` / `FromImportStmt` nested inside a `FunctionDef` body, on the
  same reasoning the `if`/`try` exclusion uses — a module the code cannot run
  without IS on the link line, whether the import is written at column 0 or in a
  body. That makes `check_module_symbols`'s dotted-callee gate (case 2 of its
  loop, keyed on `imported_module_names`) see `reflect`, and the emitter
  answers `reflect.collect_runtime_exports_h` from that module's export table —
  or refuses it as a callee with no definition, which is also a true message.
  **Watch the gate's `GATED on the root naming an imported module` comment:**
  widening the list widens what that gate admits, so `xs.append` must still be
  refused. That gate is the only thing keeping the change from being a
  silent-wrong-answer generator.
* **Right, and bigger.** Recognise the shape where it belongs: a nested import
  that resolves to a HOST module is a fact about the TARGET, so it belongs in
  `not-answerable/host-import` beside every top-level one. That is a decision
  about the sweep's class semantics, which is `tools/formal_sweep.py` and its
  owner's — see `FORMAL_dylib_export_gate_ceiling.md` §"For whoever owns the
  sweep's semantics", which makes the same argument for a different class.

The first is an hour and moves the file; the second is the right shape and is
not this worker's to take.

## 4. Reproducing

```
python3 tools/memslot.py --gb 8 --label trhs -- \
    python3 fire.py build --formal --no-prove test_runtime_header_scan.py -o .tmp/trhs.arm64
python3 tools/memslot.py --gb 8 --label trhs2 -- \
    python3 fire.py build --formal --no-prove .tmp/trhs_toplevel.mojo -o .tmp/trhs2.arm64
```