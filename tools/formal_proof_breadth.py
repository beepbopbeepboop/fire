#!/usr/bin/env python3
"""How much of THIS REPOSITORY's own source can the formal path PROVE, and
what stops each function that cannot be.

    python3 tools/formal_proof_breadth.py                 # the census, both arches
    python3 tools/formal_proof_breadth.py --arch arm64 -j 2
    python3 tools/formal_proof_breadth.py --list          # the workload, no builds

WHY THIS TOOL EXISTS, and why it is not `tools/formal_sweep.py`
-----------------------------------------------------------------
The sweep answers "does this FILE build", and it deliberately builds
`--no-prove`:

    Proof generation and Lean typechecking are a separate, much narrower
    capability with their own coverage (and their own failures, several of them
    about function *shapes* rather than about anything the code generator could
    lower) — they are exercised by test_formal.py / `make check-formal`, not by
    this sweep. With proofs on, a single unmodellable shape anywhere in a file
    fails the whole file and masks which codegen gaps are real.

That sentence is the whole reason this tool exists, and it has a second half
nobody had measured. `test_formal.py` runs `formal/examples/*.mojo` — 49
hand-written two-to-five-line programs written *for* this backend. It is the
right gate and it is not a census: it says nothing about the ~300 `.py` files
this repository is actually made of, because a whole file is the wrong unit.
A repository file is 500-15000 lines, most of it `import os` (which this
backend answers "host module"), so a per-FILE verdict on the repo's own source
measures the import graph and nothing else. The unit that has never been
measured is the FUNCTION — the unit a proof is actually about, since
`arm64_proof_gen`'s `eval_eq_mojo` states a semantic model for the entry and
everything reachable from it and compares it against the machine code the
backend emitted for exactly those functions.

So this tool takes ~60 FUNCTIONS, each as its own whole program, and puts each
one through `formal.build.compile_formal(prove=True, check=True)` — the same
call `fire.py build --formal` makes, through the same
`formal/lean.py::run_lean` bounds — on BOTH architectures.

THE WORKLOAD, and why it is not random
--------------------------------------
Two sources, because either alone is a biased sample:

  * `formal/examples/*.mojo`, verbatim. 15 of them, chosen by a fixed stride
    over the sorted stems so the choice is reproducible rather than the ones
    that already pass. (Every one of the 49 is already in `test_formal.py`;
    they are here as the baseline the repo's own functions are read against.)
  * FUNCTIONS EXTRACTED FROM THIS REPOSITORY'S OWN `*.py`, each emitted as a
    standalone module together with the module-level definitions it transitively
    needs, plus a `main` that calls it. 45 of them, round-robin across files in
    sorted path order (one per file, then a second per file, …) so the sample
    spans the tree instead of concentrating in whichever file sorts first.

Selection is by NAME DISCIPLINE, not by construct: a candidate is eligible when
every free name it reads is either a parameter, a local, a builtin, or a
module-level definition of the same file (which is then pulled in transitively,
whole, unchanged). A function that reaches for `os` is not eligible — that is
`not-answerable/host-import` in the sweep's vocabulary and measuring it again
here would only dilute the classes this census is about. Parameters annotated
with anything other than `int` are excluded, because the synthesised `main`
calls the function with the startup stub's integer and a mismatch there would
make the census report a CALL-SITE refusal as if it were a statement about the
function. Nothing is filtered by whether the backend can lower it: which is the
thing being measured.

TWO PHASES, because a Lean run costs 100x a codegen run
------------------------------------------------------
Phase A builds each program with `prove=True, check=False`: the codegen runs and
the proof GENERATOR runs, and the two failures that can be told apart without a
tactician are separated (`codegen-refused` = the source is refused;
`proof-refused` = the machine code built and the generator could not state
anything about it). Phase B runs the Lean check only where phase A produced a
proof. That is the difference between paying for Lean on every item and paying
for it only where there is something to check, and it is also what makes the
`proof_sorries` hole census (`formal.lean.proof_census`) meaningful: it is
measured per proof, from Lean's own "uses sorry" warnings, which is the only
sound count.

CLASSES — and why each is a different kind of fact
--------------------------------------------------
  pass                built, proof emitted, Lean accepted it, ZERO holes. This
                      is a proof about the real spec: `eval_eq_mojo` is the
                      function's own semantics read off its AST, compared
                      against the emitted machine code, so a wrong `mojo`
                      model does not go green here.
  admitted            built, proof emitted, Lean accepted it, and it admits a
                      `sorry` (or the file's `@admitted` host contracts are in
                      it). Counted, never counted as a pass.
  lean-rejected       the proof did not typecheck. The detail is Lean's own
                      message, which is the finding.
  bound-exceeded      `run_lean` killed it. NOT a verdict on the proof — the
                      same distinction `formal/lean.py` insists on, and the
                      reason a breach is never cached.
  codegen-refused     the backend refused a construct in the source. A fact
                      about the code generator, not about the proof layer; it
                      is counted because a caller of this census needs to know
                      how much of the corpus never reaches the proof layer at
                      all.
  proof-refused       codegen produced an image and the proof generator
                      REFUSED: `NotImplementedError` from the generator, whose
                      29 raise sites are all deliberate ("the model has no
                      domain for this"), never an accident.
  proof-crash         the generator RAISED something else. A bug, like
                      `build-crash`, and in the proof layer rather than the
                      code generator.
  build-crash         the backend RAISED instead of refusing — a bug in the
                      compiler's plumbing, reported as its own class because it
                      is neither a capability gap nor a verdict.

Exit status is 0 for a completed census. A finding is the output, not a failure
of this tool: `tools/formal_sweep.py` exits 1 because it gates a corpus, and
this does not gate anything. A non-zero exit means the census itself did not
finish (see EXIT STATUS).
"""
import argparse
import ast
import collections
import concurrent.futures
import json
import os
import signal
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

# Directories that hold no function worth proving. `formal/examples` is here
# because it is sampled as whole FILES by its own rule; `lib` is Lean; `output`
# is build products; the rest are trees this repository generates into.
SKIP_DIRS = {".git", ".tmp", "__pycache__", "cas", "output", "lib", "build",
             ".pixi", "docs", "node_modules"}

# The builtins a synthesised `main` is allowed to have in reach, and nothing
# else. A free name outside this set and outside the file's own definitions
# disqualifies the candidate — which is what keeps `import os` (a fact about the
# HOST, already counted 241 times in `formal/examples`' sweep) out of a census
# about the proof layer.
BUILTIN_NAMES = {
    "True", "False", "None", "abs", "all", "any", "bin", "bool", "chr",
    "divmod", "enumerate", "float", "hex", "int", "len", "list", "max",
    "min", "oct", "ord", "pow", "print", "property", "range", "repr",
    "reversed", "round", "sorted", "staticmethod", "classmethod", "str",
    "sum", "tuple",
}

MAX_STMTS = 14          # a "small-to-medium function", in top-level statements
MAX_EMITTED_LINES = 140  # the function plus its transitive definitions
EXAMPLE_STRIDE_TARGET = 15
REPO_FUNCTION_TARGET = 45


# ── What one verdict is ──────────────────────────────────────────────────────
# A named type, not a tuple, for the reason `tools/formal_sweep.py` names its
# `Verdict`: `ok` alone was never enough to report on, and every reader here
# needs to know which of "the backend refused", "the generator refused" and "I
# never got an answer" it is looking at.
#
# **`cached` is a FACT ABOUT THE MEASUREMENT, and it is here because a replayed
# verdict used to read as a fresh one.** `formal.lean.check_proof_cached`
# answers `True` for "this exact proof text has been checked before" in about a
# tenth of a second, and this census used to discard that flag and report the
# row as `pass` with `wall_s: 0.1`. That is how
# `bugs/sweeps/proof_breadth_2026-10-03.jsonl` came to record
# `formal/examples/either.mojo` as a pass when the file had never been checked
# on that date — and a proof regression the size of
# `FORMAL_a_generated_proof_over_leans_memory_ceiling_is_rejected.md`'s was
# recorded as coverage. "The corpus still measures this construct" is the claim
# `tools/formal_fuzz.py`'s `KNOWN_DIVERGENCES` discipline rests on, and a
# replayed verdict does not support it.
#
# It is a field rather than a distinct `cls` on purpose: `pass`/`admitted` say
# what the PROOF is and every reader here aggregates on that, while "was this
# row measured or replayed" is a second axis of the same row. The report prints
# the replayed count per architecture so the summary cannot be read as a fresh
# measurement without the ledger being opened.
Verdict = collections.namedtuple(
    "Verdict", "ident arch cls detail phase wall_s n_sorries proof_lines "
               "cached")


def _first_line(text, limit=300):
    """The message a reader needs, on one line.

    Refusals in this backend are a paragraph by design — they name the
    construct, the file, the reason and often the fix — and a census that
    printed all of it per item would be unreadable. The CAUSE is kept whole in
    `detail`; only the display is cut, and only at a line break.
    """
    if not text:
        return ""
    line = ""
    for part in str(text).splitlines():
        if line:
            break
        line = part.strip()
    line = " ".join(line.split())
    return line[:limit]


# ── Phase A input: the workload ──────────────────────────────────────────────
Workload = collections.namedtuple("Workload", "ident origin source detail weight")


def _span(node, lines):
    return "\n".join(lines[node.lineno - 1:node.end_lineno])


class _Binder(ast.NodeVisitor):
    """Names a function BINDS: parameters, assignments, targets, nested defs.

    `global`/`nonlocal` mark the candidate ineligible rather than being handled,
    because a function whose meaning depends on a module-level MUTABLE binding
    is not a self-contained program, and emitting it without the mutation would
    be measuring something the source does not say.
    """

    def __init__(self):
        self.bound = set()
        self.bad = None

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.bound.add(node.id)
        self.generic_visit(node)

    def visit_arg(self, node):
        self.bound.add(node.arg)

    def visit_alias(self, node):
        if node.asname:
            self.bound.add(node.asname)

    def visit_ExceptHandler(self, node):
        if node.name:
            self.bound.add(node.name)
        self.generic_visit(node)

    def visit_Global(self, node):
        self.bad = f"`global {'/'.join(node.names)}` binds a module mutable"

    def visit_Nonlocal(self, node):
        self.bad = f"`nonlocal {'/'.join(node.names)}` binds an enclosing frame"

    def visit_FunctionDef(self, node):
        self.bound.add(node.name)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self.bound.add(node.name)
        self.generic_visit(node)


class _Loader(ast.NodeVisitor):
    """Names a function READS, at any nesting depth, minus the nested scopes'
    own bindings.

    A nested `def`/`lambda`/`class` body is walked for its loads but its own
    parameter names are added to the bound set first — a closure reading an
    enclosing parameter is a read of that parameter's name, which the outer
    binder has already bound, and treating it as free is what would make every
    closure look like it needs a module global.
    """

    def __init__(self):
        self.loads = set()

    def _scope(self, node):
        for arg in list(node.args.posonlyargs) + list(node.args.args) + \
                list(node.args.kwonlyargs):
            self.bound.discard(arg.arg)
        if node.args.vararg:
            self.bound.discard(node.args.vararg.arg)
        if node.args.kwarg:
            self.bound.discard(node.args.kwarg.arg)
        self.bound.discard(node.name)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load):
            self.loads.add(node.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        for dec in node.decorator_list:
            self.visit(dec)
        # The SIGNATURE is read too — a default value is an expression and an
        # ANNOTATION names a type the emitted module may not carry. Walking the
        # body alone made `def f(x) -> CallExpr:` a body with no free names at
        # all, which is how `mojo/middle/methods_shared.py:23` entered the
        # sample with a return type nothing in the module defines.
        for d in list(node.args.defaults) + [k for k in node.args.kw_defaults
                                             if k is not None]:
            self.visit(d)
        for arg in (list(node.args.posonlyargs) + list(node.args.args)
                    + list(node.args.kwonlyargs)):
            if arg.annotation is not None:
                self.visit(arg.annotation)
        if node.returns is not None:
            self.visit(node.returns)
        self._scope(node)
        for st in node.body:
            self.visit(st)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node):
        self._scope_lambda(node)
        self.visit(node.body)

    def _scope_lambda(self, node):
        for arg in list(node.args.posonlyargs) + list(node.args.args) + \
                list(node.args.kwonlyargs):
            self.bound.discard(arg.arg)

    def visit_ClassDef(self, node):
        self.bound.discard(node.name)
        for st in node.body:
            self.visit(st)

    def visit_Import(self, node):
        self.loads.add("__import__")

    def visit_ImportFrom(self, node):
        self.loads.add("__import__")


def _free_names(fn, bound):
    bound = set(bound)
    loader = _Loader()
    loader.bound = bound
    for st in fn.body:
        loader.visit(st)
    return loader.loads - bound


def _class_free_names(cls) -> set:
    """The names a class reads that it does not bind — bases included.

    A BASE is a read. `class TestFailure(Exception)` is emitted verbatim, so the
    module the sample hands the backend needs `Exception` to be defined in it,
    and this backend has no representation for an exception class either way.
    An earlier version of this skipped the bases on the reasoning that
    `class A(B)` binds `A` and so does not need `B` — which is about the class's
    own NAME, and said nothing about what the body inherits from. Measured on
    `test_formal_dylib.py:105 read_uleb`, whose helper `TestFailure` is exactly
    that: the sample carried an item whose emitted module named a class it did
    not define.
    """
    binder = _Binder()
    binder.bound.add(cls.name)
    loader = _Loader()
    loader.bound = binder.bound
    for base in cls.bases:
        loader.visit(base)
    for kw in cls.keywords:               # metaclass=…, and any future keyword
        loader.visit(kw.value)
    for st in cls.body:
        if isinstance(st, ast.FunctionDef):
            # `self`/`cls` are the implicit first parameter every method reads.
            loader.bound.add("self")
            loader.bound.add("cls")
        loader.visit(st)
    return loader.loads - binder.bound


def _const_free_names(node) -> set:
    """The names a module-level `X = …` / `X: T = …` reads beyond its bindings.

    A constant is emitted verbatim, so the names its right-hand side reads are
    part of the module the sample hands the backend. The ANNOTATION counts:
    `X: CallExpr = …` names a type exactly as `def f() -> CallExpr` does.
    """
    loader = _Loader()
    loader.bound = set()
    values = ([node.value] if isinstance(node, ast.Assign)
              else [getattr(node, "value", None)])
    for v in values:
        if v is not None:
            loader.visit(v)
    ann = getattr(node, "annotation", None)
    if ann is not None:
        loader.visit(ann)
    return loader.loads - loader.bound


def _module_defs(tree):
    """`{name: node}` for the module-level definitions a candidate may pull in."""
    out = {}
    for st in tree.body:
        if isinstance(st, ast.FunctionDef):
            if st.name != "main":
                out[st.name] = st
        elif isinstance(st, ast.ClassDef):
            out[st.name] = st
        elif isinstance(st, ast.Assign):
            for target in st.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = st
        elif isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
            out[st.target.id] = st
    return out


def _eligible(fn, defs, lines):
    """`(emitted_source, dep_names)` for one candidate, or `(None, reason)`.

    The emitted module is the function plus every module-level definition it
    transitively reads, each VERBATIM: this census is about the backend's
    ability to prove the repository's real source, and a paraphrase of it would
    be a measurement of the paraphrase.
    """
    if fn.decorator_list:
        return None, "decorated (the decorator's own semantics are the subject)"
    if fn.name == "main":
        return None, "is the entry"
    if fn.args.vararg or fn.args.kwarg:
        return None, "varargs"
    for arg in list(fn.args.posonlyargs) + list(fn.args.args) + \
            list(fn.args.kwonlyargs):
        if arg.annotation is not None and _ann_text(arg.annotation) != "int":
            return None, (f"parameter {arg.arg} is annotated "
                          f"{_ann_text(arg.annotation)}")
    fabricated = _integer_unusable_in(fn)
    if fabricated:
        return None, ("parameter " + fabricated + " is used as a container, so "
                      "the stub's integer is not the value the source passes")
    if fn.returns is not None and _ann_text(fn.returns) != "int":
        return None, f"return annotation {_ann_text(fn.returns)}"
    if not 2 <= len(fn.body) <= MAX_STMTS:
        return None, f"{len(fn.body)} top-level statements"

    binder = _Binder()
    binder.visit_FunctionDef(fn)
    if binder.bad:
        return None, binder.bad
    bound = set(binder.bound)

    free = _free_names(fn, bound)
    unknown = sorted(n for n in free
                     if n not in defs and n not in BUILTIN_NAMES)
    if unknown:
        return None, "reads " + ", ".join(unknown[:4])

    needed, stack = set(), [n for n in free if n in defs]
    while stack:
        name = stack.pop()
        if name in needed:
            continue
        needed.add(name)
        dep = defs[name]
        if isinstance(dep, ast.FunctionDef):
            if dep.decorator_list:
                return None, f"depends on decorated {name}"
            dep_binder = _Binder()
            dep_binder.visit_FunctionDef(dep)
            if dep_binder.bad:
                return None, f"depends on {name}, which {dep_binder.bad}"
            dep_free = _free_names(dep, set(dep_binder.bound))
            unknown_dep = sorted(n for n in dep_free
                                 if n not in defs and n not in BUILTIN_NAMES)
            if unknown_dep:
                return None, (f"depends on {name}, which reads "
                              + ", ".join(unknown_dep[:4]))
            stack.extend(n for n in dep_free if n in defs)
        elif isinstance(dep, ast.ClassDef):
            # A class is emitted verbatim like a function, so its BODY's reads
            # are as much a part of the module as the function's are. Checking
            # only function dependencies let four items through whose class
            # reads a name the emitted module does not carry (`CallExpr`,
            # `NamedTuple`, `Exception`), which is the same hole one level
            # down and shows up as a `codegen-refused` row about a name rather
            # than about the proof layer.
            cls_free = _class_free_names(dep)
            unknown_cls = sorted(n for n in cls_free
                                 if n not in defs and n not in BUILTIN_NAMES)
            if unknown_cls:
                return None, (f"depends on class {name}, whose body reads "
                              + ", ".join(unknown_cls[:4]))
            stack.extend(n for n in cls_free if n in defs)
        else:
            # A module-level CONSTANT is emitted verbatim like a function, and
            # its right-hand side is an expression: `STDLIB_ROOT =
            # Path(STDLIB_PATH).resolve()` carries two names the emitted module
            # does not define, and the function that reads `STDLIB_ROOT` then
            # brings the hole with it.
            const_free = _const_free_names(dep)
            unknown_const = sorted(n for n in const_free
                                   if n not in defs
                                   and n not in BUILTIN_NAMES)
            if unknown_const:
                return None, (f"depends on {name}, whose value reads "
                              + ", ".join(unknown_const[:4]))
            stack.extend(n for n in const_free if n in defs)
    chunks = [_span(fn, lines)] + [_span(defs[n], lines)
                                  for n in sorted(needed)]
    body = "\n".join(chunks)
    if len(body.splitlines()) > MAX_EMITTED_LINES:
        return None, "closure too large to be a small function"
    return body, sorted(needed)


# The builtins that CONSUME a sequence, so a call naming one is the source
# saying "this parameter is iterable".  `len` is separate because it is the case
# the census's own §3 counted by mistake, and it is spelled in the refusal.
SEQUENCE_CALLS = frozenset({
    "iter", "next", "list", "tuple", "reversed", "sorted", "enumerate", "zip",
    "sum", "min", "max", "any", "all", "set", "dict", "map", "filter",
})


def _integer_unusable_in(fn):
    """The first parameter this function uses as a SEQUENCE, or None.

    **The rule the eligibility test above is missing, and it is the one that
    made three of this census's sixty items statements about the harness.**
    `_entry_call` fills every parameter with the startup stub's integer, which is
    the right value for an arithmetic parameter and the wrong one for a
    container: `mojo/middle/exprtypes.py`'s `_trailing_default_at(dflts, …)`
    takes a list of `(name, default_ast)` pairs and `test_ast_formal.py`'s
    `read_records(vals, …)` takes a list of tokens, so the emitted `main` handed
    each an integer and the build refused with "len() of a value classified as
    'int'" — which §3 of the census then counted as a family of code-generator
    refusals, three times over. The docstring's own stated reason for excluding a
    non-int ANNOTATION is the reason here too ("a mismatch there would make the
    census report a CALL-SITE refusal as if it were a statement about the
    function"), and an unannotated parameter reaches the same place with less
    evidence — so this asks the question the annotation would have answered, and
    only where the answer is decidable from the source alone.

    Four shapes, all of them a way an INT cannot be read, and none of them
    decidable in the other direction:
      * `len(p)` — the refusal this rule was written for;
      * `p[...]` — a subscript is a byte offset into a `char *` or a dict scan,
        and an integer is neither;
      * iteration over `p` — `for … in p`, a comprehension's iterable, `iter(p)`;
      * a METHOD call on `p` — `'strip' is not one of those methods of those
        receivers`, which is what a string or a list argument earns.
    An arithmetic use, a comparison, a call that passes it on: none of those
    constrains what the value IS, so they are left eligible — the rule can only
    REMOVE candidates, and a census whose workload is 21 items smaller is still a
    census of the same thing.
    """
    params = {a.arg for a in list(fn.args.posonlyargs) + list(fn.args.args)
              + list(fn.args.kwonlyargs)}
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                if func.id == "len" and node.args and isinstance(
                        node.args[0], ast.Name) and node.args[0].id in params:
                    return node.args[0].id
                if func.id in SEQUENCE_CALLS and node.args and isinstance(
                        node.args[0], ast.Name) and node.args[0].id in params:
                    return node.args[0].id
            elif isinstance(func, ast.Attribute) and isinstance(
                    func.value, ast.Name) and func.value.id in params:
                return func.value.id
        elif isinstance(node, ast.Subscript) and isinstance(
                node.value, ast.Name) and node.value.id in params:
            return node.value.id
        elif isinstance(node, ast.For) and isinstance(
                node.iter, ast.Name) and node.iter.id in params:
            return node.iter.id
        elif isinstance(node, ast.comprehension) and isinstance(
                node.iter, ast.Name) and node.iter.id in params:
            return node.iter.id
    return None


def _ann_text(node):
    try:
        return ast.unparse(node)
    except Exception:
        return "?"


def _entry_call(fn):
    """`main`'s one line, calling `fn` with the stub's integer.

    One argument per parameter, all the same value. The startup stub hands
    `main` a single integer (`compile_formal`'s `test_input`), so a multi-
    parameter function has to be called with a repetition of it; what matters is
    that the call is a real one of the real arity, because a call that could not
    happen in the source would make every refusal a statement about the harness.
    """
    count = len(list(fn.args.posonlyargs) + list(fn.args.args) +
                list(fn.args.kwonlyargs))
    args = ", ".join(["x"] * count)
    return f"def main(x):\n    return {fn.name}({args})\n"


def repo_function_workload(limit=REPO_FUNCTION_TARGET, verbose=False):
    """One eligible function per file, then a second, and so on, in path order.

    The one per file is the file's LARGEST eligible function, not its first.
    Round-robin already spreads the sample across the tree; picking the first
    eligible would then spend it on whatever happens to sort first inside each
    file, which in this repository is usually a two-statement accessor. The
    largest eligible one is still a small-to-medium function by construction
    (`MAX_STMTS`) and is where the constructs are.
    """
    files = []
    for root, dirs, names in os.walk(HERE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in sorted(names):
            if name.endswith(".py"):
                files.append(os.path.join(root, name))
    files.sort()
    per_file = []
    skipped = collections.Counter()
    for path in files:
        rel = os.path.relpath(path, HERE)
        if rel == os.path.relpath(__file__, HERE):
            continue
        try:
            with open(path) as f:
                src = f.read()
            tree = ast.parse(src)
        except (OSError, SyntaxError, ValueError):
            continue
        lines = src.splitlines()
        defs = _module_defs(tree)
        found = []
        for st in tree.body:
            if not isinstance(st, ast.FunctionDef):
                continue
            emitted, why = _eligible(st, defs, lines)
            if emitted is None:
                skipped[why.split("(")[0].strip()[:48]] += 1
                continue
            found.append(Workload(
                ident=f"{rel}:{st.lineno}:{st.name}",
                origin="repo",
                source=emitted + "\n" + _entry_call(st),
                detail=f"{len(st.body)} stmts, "
                       f"{len(emitted.splitlines())} lines with closure",
                weight=len(st.body)))
        if found:
            found.sort(key=lambda w: (-w.weight, w.ident))
            per_file.append(found)
    items, round_no = [], 0
    while len(items) < limit:
        added = False
        for found in per_file:
            if round_no < len(found):
                items.append(found[round_no])
                added = True
                if len(items) == limit:
                    break
        if not added:
            break
        round_no += 1
    if verbose:
        for why, n in skipped.most_common(12):
            print(f"  skipped {n:5d}  {why}")
    return items


def example_workload(limit=EXAMPLE_STRIDE_TARGET):
    """A fixed stride over `formal/examples`, so the sample is reproducible."""
    d = os.path.join(HERE, "formal", "examples")
    stems = sorted(f[:-5] for f in os.listdir(d) if f.endswith(".mojo"))
    if not stems:
        return []
    stride = max(1, len(stems) // max(1, limit))
    picked = stems[::stride][:limit]
    out = []
    for stem in picked:
        path = os.path.join(d, stem + ".mojo")
        with open(path) as f:
            src = f.read()
        out.append(Workload(ident=f"examples/{stem}.mojo", origin="example",
                            source=src, detail="whole file, verbatim",
                            weight=len(src.splitlines())))
    return out


def build_workload(repo=REPO_FUNCTION_TARGET, examples=EXAMPLE_STRIDE_TARGET,
                   verbose=False):
    items = example_workload(examples) + repo_function_workload(repo, verbose)
    seen, out = set(), []
    for item in items:
        if item.ident in seen:
            continue
        seen.add(item.ident)
        out.append(item)
    return out


# ── Phase A + B: one item through the real path ───────────────────────────────
# Which of the two halves of `compile_formal` is running. The generator is
# patched (below) rather than the messages being read, because "the model
# refuses a construct" and "the code generator crashed" are reported through
# the same Python exception types and the only reliable way to tell them apart
# is to know which function was on the stack.
_PHASE = threading.local()


def _instrument_generators():
    """Wrap both proof generators so `_PHASE` says which half is running.

    `compile_formal` imports the generator INSIDE itself, so patching the
    module attribute is picked up by the call — no source change to the backend
    and no reliance on a message's wording, which is the only other way to tell
    `arm64_proof_gen._no_value_model`'s deliberate `NotImplementedError` from a
    genuine crash. Idempotent: calling it twice does not double-wrap.
    """
    if getattr(_instrument_generators, "done", False):
        return
    import formal.arm64_proof_gen as APG
    import formal.x86_64_proof_gen as XPG

    def wrap(real):
        def inner(*a, **kw):
            # `generate_entered` is set and NOT cleared here: an exception
            # raised by the generator unwinds through this `finally` on its way
            # out, so a flag restored on the way out would read `False` by the
            # time the handler that needs it runs. It is reset per item, at the
            # top of `run_item`, which is the only place that knows an item
            # started.
            _PHASE.generate_entered = True
            was = getattr(_PHASE, "what", "build")
            _PHASE.what = "generate"
            try:
                return real(*a, **kw)
            finally:
                _PHASE.what = was
        return inner

    APG.generate_arm64_proof = wrap(APG.generate_arm64_proof)
    XPG.generate_x86_64_proof = wrap(XPG.generate_x86_64_proof)
    _instrument_generators.done = True


def run_item(item, arch, timeout, workdir):
    """Build one program with proofs and check it, and classify the outcome.

    The two calls are `formal.build.compile_formal`'s own, in its own order:
    `prove=True` runs the proof generator and writes the `.lean`, and the check
    is `formal.lean.check_proof_cached` — which is what `check=True` calls, and
    which is what runs `lean` through `formal/lean.py::run_lean`'s bounds. The
    one difference is that the wall bound is PASSED rather than defaulted, so
    one slow proof cannot consume the whole census: a census over 120 items
    needs a per-item bound to exist at all, and `bound-exceeded` is a class this
    census is required to report. Lean's CPU bound is left at its own default.

    `prove=True, check=False` in the first call is not a weakening: phase B is
    the check, run from this module rather than from inside `compile_formal`
    only so that the bound above can be stated. Nothing between the two calls
    touches the proof file.
    """
    import formal.build as FB
    from formal.lean import check_proof_cached

    def verdict(cls, detail, phase="build", wall=0.0, n_sorries=None,
                proof_lines=0, cached=False):
        return Verdict(item.ident, arch, cls, _first_line(detail), phase,
                       round(wall, 1), n_sorries, proof_lines, bool(cached))

    src = os.path.join(workdir, "prog.mojo")
    out = os.path.join(workdir, "prog.aout")
    with open(src, "w") as f:
        f.write(item.source)
    _instrument_generators()
    started = time.monotonic()
    _PHASE.what = "build"
    _PHASE.generate_entered = False
    try:
        result = FB.compile_formal(src, output=out, test_input=10,
                                   prove=True, check=False, arch=arch)
    except (FB.CodegenError, FB.FormalBuildError) as e:
        # The two refusal types, and both are refusals: `formal/model.py`'s
        # `CodegenError` is what the function pipeline raises, and
        # `formal/build.py`'s `FormalBuildError` is what an import-closure walk
        # and the container checks raise. They are one class here because the
        # question is the same for both — did a construct in this program stop
        # it — and a caller of the census cannot act on the difference.
        return verdict(_refusal_class(str(e)), e)
    except NotImplementedError as e:
        # The generator's own refusal, and only the generator raises this (29
        # sites in `arm64_proof_gen.py`, none in `formal/build.py`,
        # `formal/model.py` or the x86-64 generator, which CATCHES it instead —
        # see `_no_value_model`'s docstring for what the two architectures do
        # with a refusal). Anything else raised while generating is a crash.
        cls = ("proof-refused" if _PHASE.generate_entered else "build-crash")
        return verdict(cls, e, phase="generate" if _PHASE.generate_entered
                       else "build")
    except Exception as e:                      # noqa: BLE001 — a class here
        # The backend RAISING rather than refusing is a bug in the compiler's
        # plumbing, not a statement about the source — `tools/formal_sweep.py`'s
        # `backend-crash` is the same distinction at the same point.
        import traceback
        cls = "proof-crash" if _PHASE.generate_entered else "build-crash"
        return verdict(cls, f"{type(e).__name__}: {e}\n"
                             f"{traceback.format_exc()[:600]}",
                       phase="generate" if _PHASE.generate_entered
                       else "build")
    phase_a = time.monotonic() - started
    proof_path = result.get("proof_path")
    if not proof_path or not os.path.isfile(proof_path):
        return verdict("proof-refused",
                       "no proof emitted for an image that built",
                       phase="generate", wall=phase_a)
    with open(proof_path) as f:
        proof_lines = sum(1 for _ in f)
    check_started = time.monotonic()
    try:
        ok, detail, cached, n_sorries = check_proof_cached(
            proof_path, repo_root=HERE, timeout=timeout)
    except Exception as e:                      # noqa: BLE001 — a class here
        return verdict("build-crash", f"proof check raised: {e}",
                       phase="check", wall=time.monotonic() - started,
                       proof_lines=proof_lines)
    wall = phase_a + (time.monotonic() - check_started)
    if ok:
        cls = "pass" if not n_sorries else "admitted"
        return verdict(cls, detail, phase="check", wall=wall,
                       n_sorries=n_sorries, proof_lines=proof_lines,
                       cached=cached)
    if _bound_detail(detail):
        return verdict("bound-exceeded", detail, phase="check", wall=wall,
                       n_sorries=n_sorries, proof_lines=proof_lines,
                       cached=cached)
    return verdict("lean-rejected", detail, phase="check", wall=wall,
                   n_sorries=n_sorries, proof_lines=proof_lines,
                   cached=cached)


def _refusal_class(detail):
    """A refusal, split by WHETHER it is about the source or about the target.

    Two classes rather than one because the census's callers need to know which
    of the two they are looking at, and `formal/examples`' sweep already
    established the vocabulary: a program that reaches for a CPython module is
    `not-answerable/host-import`, a fact about the TARGET, while a construct
    this backend cannot lower is a gap in the backend and lives in this file.
    The rule is deliberately coarse — it reads the refusal's own words, which is
    where both facts are stated — and it errs toward `codegen-refused`, which
    is the class a reader must not under-count.
    """
    text = str(detail or "")
    if "host module" in text or "imports '" in text or \
            "unresolved import" in text:
        return "refused-import"
    return "codegen-refused"


def _bound_detail(detail):
    text = str(detail or "")
    return "exceeded" in text and ("wall" in text or "CPU" in text)


# ── Reporting ────────────────────────────────────────────────────────────────
CLASS_ORDER = ["pass", "admitted", "lean-rejected", "bound-exceeded",
               "proof-refused", "proof-crash", "codegen-refused",
               "refused-import", "build-crash"]


def _cause_key(v):
    """The one clause a reader ranks by: the refusal's own subject.

    Full messages stay in the ledger; the ranking is over a normalised head so
    that `... in a while-loop body` and `... in an argument position` do not
    count as two different causes when they are one.
    """
    d = v.detail
    for cut in (" (build:", " -- ", " ("):
        if cut in d:
            d = d.split(cut)[0]
    words = d.split()
    return " ".join(words[:7])


def report(results, arch_list):
    by_arch = collections.defaultdict(list)
    for v in results:
        by_arch[v.arch].append(v)
    lines = []
    for arch in arch_list:
        vs = by_arch.get(arch, [])
        counts = collections.Counter(v.cls for v in vs)
        lines.append(f"== {arch}: {len(vs)} items")
        for cls in CLASS_ORDER:
            if counts.get(cls):
                lines.append(f"   {cls:16s} {counts[cls]:4d}")
        proven = counts["pass"] + counts["admitted"]
        lines.append(f"   {'proved at all':16s} {proven:4d} "
                     f"({100.0 * proven / max(1, len(vs)):.1f}%)")
        replayed = sum(1 for v in vs if v.cached)
        if replayed:
            lines.append(f"   {'of which replayed':16s} {replayed:4d}  "
                         f"(a cached verdict, not a run — see the ledger's "
                         f"`cached` field)")
    lines.append("")
    lines.append("== causes, ranked over every arch")
    causes = collections.defaultdict(lambda: collections.Counter())
    for v in results:
        if v.cls in ("pass",):
            continue
        causes[_cause_key(v)][v.cls] += 1
    ranked = sorted(causes.items(), key=lambda kv: -sum(kv[1].values()))
    for cause, counts in ranked[:40]:
        n = sum(counts.values())
        detail = ", ".join(f"{c}={counts[c]}" for c in CLASS_ORDER
                           if counts.get(c))
        lines.append(f"   {n:4d}  {cause[:96]:96s} [{detail}]")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arch", default="both",
                    choices=["arm64", "x86_64", "both"])
    ap.add_argument("-j", "--jobs", type=int, default=2,
                    help="concurrent items; each one can run a Lean proof, "
                         "so this is a MEMORY decision (one proof measured at "
                         "1.7 GB, Lean's own ceiling for one is 6 GB)")
    ap.add_argument("-t", "--timeout", type=float, default=180.0,
                    help="per-proof WALL bound in seconds (run_lean's own CPU "
                         "bound is unchanged). A breach is reported as "
                         "bound-exceeded and is not a verdict on the proof.")
    ap.add_argument("--repo", type=int, default=REPO_FUNCTION_TARGET)
    ap.add_argument("--examples", type=int, default=EXAMPLE_STRIDE_TARGET)
    ap.add_argument("--ledger", default=None,
                    help="append one JSON line per verdict here (default: "
                         "$TMPDIR/formal_proof_breadth.ledger.jsonl)")
    ap.add_argument("--list", action="store_true",
                    help="print the workload and exit without building")
    ap.add_argument("--show", default=None, metavar="SUBSTR",
                    help="print the emitted source of the workload items whose "
                         "identifier contains SUBSTR, and exit")
    ap.add_argument("--verbose-select", action="store_true",
                    help="report why candidates were skipped")
    args = ap.parse_args(argv)

    items = build_workload(repo=args.repo, examples=args.examples,
                           verbose=args.verbose_select)
    arches = ["arm64", "x86_64"] if args.arch == "both" else [args.arch]
    if args.list:
        for it in items:
            print(f"{it.ident:56s} {it.detail}")
        print(f"{len(items)} items", file=sys.stderr)
        return 0
    if args.show:
        for it in items:
            if args.show in it.ident:
                print(f"===== {it.ident} ({it.detail})")
                print(it.source)
        return 0

    ledger_path = args.ledger or os.path.join(
        tempfile.gettempdir(), "formal_proof_breadth.ledger.jsonl")
    tmp = tempfile.mkdtemp(prefix="formal_proof_breadth_")
    jobs = []
    for arch in arches:
        for i, item in enumerate(items):
            jobs.append((item, arch,
                         os.path.join(tmp, f"{arch}_{i:04d}")))
    results = []
    ledger = open(ledger_path, "a")
    ledger.write(f"# formal_proof_breadth {time.strftime('%F %T')} "
                 f"timeout={args.timeout} arches={','.join(arches)}\n")

    def work(job):
        item, arch, workdir = job
        os.makedirs(workdir, exist_ok=True)
        try:
            return run_item(item, arch, args.timeout, workdir)
        except Exception as e:                  # noqa: BLE001 — a class here
            return Verdict(item.ident, arch, "build-crash",
                           _first_line(f"{type(e).__name__}: {e}"), "harness",
                           0.0, None, 0, False)

    interrupted = {"flag": False}

    def on_signal(signum, _frame):
        # The summary of what DID finish is printed from the drain, so a
        # SIGTERM costs wall time and nothing else. A census whose partial
        # numbers were not printed is a census nobody can read.
        interrupted["flag"] = True

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    started = time.monotonic()
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs)
    try:
        futures = {ex.submit(work, job): job for job in jobs}
        for fut in concurrent.futures.as_completed(futures):
            v = fut.result()
            results.append(v)
            ledger.write(json.dumps(v._asdict()) + "\n")
            ledger.flush()
            if v.cls != "pass":
                print(f"{v.cls:16s} {v.arch:6s} {v.ident}", flush=True)
            elif v.cached:
                # A replayed PASS is the case the `cached` field exists for: it
                # would otherwise be the only row of a run with nothing on the
                # screen, which is exactly how `either.mojo` came to be recorded
                # as covered.
                print(f"{'pass (replayed)':16s} {v.arch:6s} {v.ident} "
                      f"[wall {v.wall_s}s — a cached verdict, not a run]",
                      flush=True)
            if interrupted["flag"]:
                for other in futures:
                    other.cancel()
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    elapsed = time.monotonic() - started
    ledger.close()
    print()
    print(report(results, arches))
    print(f"\n{len(results)}/{len(jobs)} verdicts in {elapsed:.0f}s; "
          f"ledger {ledger_path}")
    if interrupted["flag"] or len(results) != len(jobs):
        print("CENSUS INCOMPLETE — the counts above cover only the verdicts "
              "that finished, and are not a scope.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())