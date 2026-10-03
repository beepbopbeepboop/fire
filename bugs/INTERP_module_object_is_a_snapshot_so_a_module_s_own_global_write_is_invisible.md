# INTERP: `mod.G` is a SNAPSHOT of the module's scope, so a write the module's own `global` statement made is invisible through it

**Area:** the Mojo interpreter (`myinterpreter.py`), not the formal backends.
Found 2026-10-03 while fixing the compiled half of the same defect — see
"What this masked" below, which is why it is filed rather than left.

**Status: root cause located, one function, not fixed here.**

## What I ran

```
$ cat i_lib.mojo
G = 5

def setg(v: Int):
    global G
    G = v

def get_it() -> Int:
    global G
    return G

$ cat i_prog.mojo
import i_lib
def main(n):
    i_lib.setg(9)
    a: Int = i_lib.get_it()
    print(a)
    b: Int = i_lib.G
    print(b)
    return 0

$ python3 fire.py run .tmp/w2/i_prog.mojo
9
5                       # expected 9

$ cp i_lib.mojo i_lib.py; cp i_prog.mojo i_prog.py
$ python3 -c "import i_prog; i_prog.main(0)"
9
9                       # the same text as CPython
```

The two reads disagree with each other in one program: `i_lib.get_it()` — a
function of the module, reading the module's own `G` — answers 9, and
`i_lib.G` — an attribute read of the same module — answers 5, which is the
value `G` had before `setg` ran.

**It is not the dotted read.** The same program with everything in ONE file
prints 9 and 9:

```
G = 5
def setg(v: Int): global G; G = v
def main(n):
    setg(9)
    print(get_it())    # 9
    print(G)           # 9
```

So the interpreter's own module-level global handling is right; what is wrong is
the object an `import` binds.

## The cause, to the line

`myinterpreter.py::_load_mojo_sibling_module`, the last six lines:

```python
        mod_interp = Interpreter(filename=found, argv=self.argv)
        mod_interp._mojo_module_cache = cache  # shared, so cycles hit the guard above
        for stmt in mod_stmts:
            mod_interp.execute(stmt)
        namespace = types.SimpleNamespace(**mod_interp.scope.vars)
        cache[found] = namespace
        return namespace
```

`SimpleNamespace(**mod_interp.scope.vars)` COPIES the module's top-level
bindings at the moment the module body finishes. Everything the module's
functions subsequently do to its own globals — the only writer of a `global`
name, by the language's own rule — lands in `mod_interp.scope`, which is still
alive and still the thing the module's functions read. So there are two homes
for `G`: the live scope (9, what `i_lib.get_it()` reads) and the snapshot the
module object was built from (5, what `i_lib.G` reads).

**The snapshot is also why the write looks like it did nothing.** `global G`
in `setg` assigns into `mod_interp.scope`; `SimpleNamespace` is not that
object, so nothing about the write is visible outside it. There is no
diagnostic and no error — the value the module reports about itself and the
value another module reads are simply two different numbers.

**What is needed is a LIVE view, not a dict copy.** The module object should
resolve `mod.X` against the module interpreter's own scope, so a write is
visible the moment it happens and in both directions (`mod.X = …` writing into
the module's globals is CPython's rule too, and today it writes a fourth home:
an attribute on the snapshot, which no function ever reads). A small class with
`__getattr__`/`__setattr__`/`__dir__` delegating to `scope.vars` is the shape;
`_AutoStubNamespace` in the same function is the precedent for a module object
that is not a plain `SimpleNamespace`, and `hasattr`/`getattr` in
`_eval_member_of` already work against anything.

Two things to keep while doing it, because both are load-bearing today:

  * the module object must keep the module `Interpreter` alive (a closure over
    `scope.vars` does, and `scope.vars` is the dict the functions mutate);
  * `cache[found] = types.SimpleNamespace()` is the CYCLE GUARD, set BEFORE the
    module body runs (`myinterpreter.py:2897` area) precisely so a package that
    imports itself terminates. A live view has to be installed in that slot too,
    not only at the end.

## What this masked

`bugs/FORMAL_module_state_no_storage.md` §(2) claimed a folded module-level name
crosses a dylib boundary safely because "the module-level sequence is its only
writer" — and that claim was FALSE for a name a function writes through `global`,
which is why `formal/build.py::_module_constants` was publishing one:

```
# mylib.mojo:  G = 5  /  def get(): global G; return G  /  def setg(v): global G; G = v
# prog.mojo:    mylib.setg(9); mylib.get()  -> 9   (the slot, correct)
#               mylib.G                  -> 5   (the manifest; CPython says 9)
```

Both engines answered 5 for the cross-module read — so the interpreter agreed
with the backend, and any test comparing the two would have seen them agree.
The compiled half is fixed (`work/formal8-7-r2`, "a module global the module
itself writes is not a constant across a dylib boundary"), and the interpreter
is still wrong.

**This is the general shape, and it is worth stating once:** wherever a module's
state has two homes, the reference engine and the backends have to agree about
WHICH home is the truth, or agreement between them proves nothing. Here they
agreed on the wrong one.

## Exact next step

1. Replace `types.SimpleNamespace(**mod_interp.scope.vars)` with a live module
   object delegating to `mod_interp.scope.vars`, and install the same object in
   the cycle-guard slot before the module body runs.
2. Add a row to `test_interp_oracle.py` — the suite that runs each program
   through both `python3 fire.py run` and `python3` on the SAME text and requires
   identical stdout and exit code. A bug the interpreter and the backends SHARE
   is exactly what that suite exists for, and `test_runtime_diff.py` structurally
   cannot see this one.
3. Check the two paths that already rely on `SimpleNamespace` being a plain
   object: `_bind_dotted_import` tests `isinstance(nxt, types.SimpleNamespace)`
   when it walks a dotted chain, so the new class either subclasses
   `SimpleNamespace` or `isinstance` there is widened.