from . import *

# # ── The module BODY: the top-level statements that are not declarations ──
# ── The module BODY: the top-level statements that are not declarations ──
#
# Everything above decides what a module-level NAME means. This decides which
# top-level STATEMENTS have to run, and it is the answer to the question the
# whole `formal` entry-point path turns on: `_extract_functions` in
# `formal/build.py` picks `FunctionDef`s out of the module statement list and
# lowers nothing else, so before this existed a file whose body was
#
#     import sys
#     sys.exit(3)
#
# built, linked, passed the bind audit and computed NOTHING — exit 0 where the
# source says 3 — and the coverage sweep counted it a pass. That is the
# worst outcome this project has (a false pass), and it was silent because
# nothing asked.
#
# So the module body is classified here, ONCE, in the model both backends and
# both front ends share, and the classification is by KIND rather than by
# inspection:
#
#   * a DECLARATION — `def`, `struct`, `trait`, `import`, `from … import`,
#     and a module-level `comptime` binding (a compile-time binding, not a
#     runtime store) — is not body. Each has its own lowering or its own
#     refusal already.
#   * a module DOCSTRING — a bare string `ExprStmt` — is not body. Python
#     stores it in `__doc__` and runs nothing; `model._UNRESOLVED_NAME_ALLOWED`
#     already answers a read of `__doc__` from a Python-level value, so there
#     is nothing to execute and nothing to lose. The test is
#     `is_docstring_statement`, and it is NAMED rather than inlined here because
#     the TEXT ENCODING scan asks the same question — a docstring's bytes are not
#     a string value — and two answers to "is a bare string statement a value"
#     is how 229 files came to be refused over six lines of em-dash prose.
#   * `pass` at file level is not body: it is the statement that does nothing.
#   * a module-level BINDING whose value FOLDS to a literal, bound once, is not
#     body either — and this is the exemption `collect_module_symbols` already
#     computes, read as a lookup rather than as a second analysis. The
#     substitution (`build.py:_substitute_module_constants`) puts the literal
#     at every read site inside the unit, which is exactly what executing the
#     store would have achieved for a name nothing else can see. Anything ELSE
#     at file level — a call, an `if`, a `for`, a binding of a value the folder
#     cannot fold — IS body, because its effect is not observable anywhere else
#     and dropping it is a wrong answer rather than a harmless one.
#
# A `ComptimeVarStmt` is a DECLARATION here, deliberately and against the
# measurement: 539 of the module-level statements in this repository and the
# stdlib are `comptime X = …` bindings, and `refuse_module_level_mlir_templates`
# / `collect_module_symbols` already own every one of them. Counting them as
# body would put 88 stdlib modules into "this module has a body" for a
# construct that has no runtime store at all, which is the same category of
# error as calling a comment a statement.
_MODULE_BODY_DECLARATIONS = ("ImportStmt", "FromImportStmt", "FunctionDef",
                             "StructDef", "TraitDef", "ComptimeVarStmt")

# The binding forms. A `VarDecl` with no value (`x: Int`) is a DECLARATION of a
# name with no store, which `collect_module_symbols` already records as
# `declared`; it is listed here so it is classified as body and then refused by
# the ordinary name rules rather than being quietly skipped.
_MODULE_BODY_BINDINGS = ("AssignStmt", "VarDecl", "AugAssignStmt",
                         "MultiAssignStmt")

# The name the module body is compiled under. Lives HERE, beside the rule that
# decides which statements are body, because the two backends' entry selection
# (`entry_function`) has to recognise it and build.py has to create it: three
# places agreeing on one spelling by convention is three places that can
# disagree.
#
# A dunder-adjacent spelling, and the reason is load-bearing: it must not
# collide with a name the source can write (a module is free to define
# `def module_body()`, and then the emitter's `self._functions` table would
# keep only the last of the two), and `doc/ABI.md`'s export rule excludes a
# leading `_`, so a function of this name can never be published as a module's
# API either. It is NOT `main` and must not be: a module that declares its own
# `def main` has that called by its body or not at all, and the startup stub
# branches to `functions[0]`, which is this one.
MODULE_BODY_NAME = "__module_body__"

# The attribute `_module_body_function` stamps the wrapper it builds, and the one
# reader of it. A TAG rather than the NAME because the name is not a reliable
# key: a library is compiled from SEVERAL sources, each of which may have a body,
# and `formal/build.py::compile_formal_dylib` renames the second and later of one
# name apart (`__module_body____ov2`) because the emitters key their function
# tables by name. Matching the name would find one of N bodies in a library built
# from N files with one, and the load-time initializer array would then run one
# file's top level and silently drop the rest — which is the silent no-op this
# mechanism exists to end, reintroduced one level down.
MODULE_BODY_TAG = "_module_body"


def module_body_functions(functions: list) -> list:
    """The module-body wrappers in `functions`, in the order given.

    The list and not the first one, for the reason `MODULE_BODY_TAG` gives: a
    library can be compiled from several sources and each may carry a body, and
    every one of them is code the source says runs when the module is imported.
    The consumers are the two object writers' load-time initializer arrays (one
    pointer each, in this order) and `formal/build.py`'s "does this library have a
    body at all", which is a question about the list being non-empty.
    """
    return [f for f in (functions or [])
            if getattr(f, MODULE_BODY_TAG, False) is True]


def entry_arity(fn) -> int:
    """How many parameters a function DECLARES.

    One reader for the four places that need it and cannot each have their own:
    `formal/build.py` (to widen the startup stub's argument values before the
    image exists), `formal/arm64_proof_gen.py` and `formal/x86_64_proof_gen.py`
    (for `mojo`'s binders, the AST bridge's argument list and the run tests) --
    and it counts the SOURCE's parameters, which is what `_gen_go` builds the
    model's signature from, so the model's arity and the theorem's cannot
    disagree.
    """
    return len([p for p in (getattr(fn, "params", None) or []) if p])


def entry_arg_values(values, arity: int = 1) -> list:
    """The entry function's ARGUMENT values, as a list of ints.

    The formal entry convention used to be "one argument, in x0", and
    `fire --formal -n <int>` still says so: `values` is one integer.  But a
    `def main(n: Int, m: Int)` is a legal program on both architectures — the
    startup stub simply left `m` in whatever the process started with, i.e.
    `0` — and the PROOF side has to know what it was, or a run test claims the
    machine returned the model of inputs the binary never received.

    So the value list is widened here, once, for every consumer: the startup
    stub emits one materializer per value, and both proof generators read the
    same list out of `info["entry_args"]`.

    Two properties are deliberate:

    * **`values` is still a scalar in every existing call**, so an entry of
      one argument gets `[v]` and every generated byte is unchanged.  The
      widening only happens where a program asked for it.
    * **Short is padded with `0`, never with a repeat of `values[0]`.**  `0` is
      what both architectures' `init` constructors leave in the unused argument
      registers (`Arm64State.init` sets `x1 := 0`, `X86State.init` sets
      `rsi := 0`) and it is what a process' own registers hold at `_start`, so
      padding here agrees with the binary whether or not the startup stub emits
      a materializer for the argument it was not told about.
    """
    if isinstance(values, bool) or not isinstance(values, (list, tuple)):
        out = [int(values)]
    else:
        out = [int(v) for v in values]
        if not out:
            out = [0]
    if arity is not None and arity > len(out):
        out = out + [0] * (arity - len(out))
    return out


def entry_function(functions: list):
    """The function the startup stub branches to, and the order to emit in.

    One rule, asked by both backends, because the two used to each spell it out
    (`main` first, else the list as given) and a rule written twice is a rule
    that will be written two ways. The rule:

      1. the MODULE BODY first, when the module has one. The module's own
         top-level statements are the program's own code and run before
         anything else — that is what CPython does, and it is the whole of
         `FORMAL_toplevel_statements_dropped`;
      2. then a declared `main`, which is an ordinary function the body may
         call and which used to be the entry;
      3. then everything else, in source order.

    A body-less module therefore behaves exactly as it did before this rule
    existed, which is why every file in the formal suites is unaffected: they
    are all `def f(): …` with nothing at file level.

    Returns the ordered list; `functions[0]` is the entry. `emit_startup=False`
    callers (the dylib path) do not reorder, because a library has no entry and
    the order is then only the emission order."""
    body = [f for f in functions if getattr(f, "name", None) == MODULE_BODY_NAME]
    if not body:
        body = [f for f in functions if getattr(f, "name", None) == "main"]
    else:
        # A module body AND a declared `main`: the body is still first, and
        # `main` second. The body calls `main` if the source says so.
        body = body + [f for f in functions
                       if getattr(f, "name", None) == "main"]
    # By IDENTITY, not by `not in`: `F.FunctionDef` is a dataclass, so `in`
    # compares by VALUE, and two functions that happen to be spelled the same
    # way — `def f(): return 0` twice, which Mojo overloads and this tree
    # does contain — would make the second one compare equal to the first and
    # be dropped from `rest`. That is a silently missing function, which is
    # the failure this whole module exists to remove.
    taken = {id(f) for f in body}
    rest = [f for f in functions if id(f) not in taken]
    return body + rest if body else functions


def module_body(stmts: list, symbols: dict = None) -> list:
    """The top-level statements of `stmts` that HAVE TO RUN, in source order.

    The counterpart of `_extract_functions`, and the answer to what it drops.
    Empty for a module that is only declarations and foldable constants — the
    overwhelming majority of this repository, and every file the existing
    formal suites build — so a caller that lowers this into a function changes
    nothing for them.

    `symbols` is `collect_module_symbols(stmts)`'s table, which the caller
    already has (and publishes) on every path that asks this question, so the
    foldable-constant exemption is a LOOKUP in a table already built rather than
    a second fold of the same expressions.

    A module-level store is left out when the IMAGE already holds its value, and
    there are two ways that can be so: the value FOLDS and is substituted at each
    read (`X = 5`), or the name is a `__DATA` SLOT whose initializer the linker
    lays out before the program starts (`X = [1, 2, 3]`, which is storage-shaped
    rather than foldable). Both exemptions ask the same question — "would
    dropping this store change the program's answer?" — and a store that passes
    either one is the image's business, not the body's. See
    `_is_image_initialized` for the second, and for the entry point that a
    leftover store silently changes."""

    def _is_folded_constant(stmt) -> bool:
        name = _module_binding_name(stmt)
        if name is None:
            return False
        sym = (symbols or {}).get(name)
        if sym is None or sym.literal is None:
            return False
        # `site == "assigned"` is the table's own word for "bound once at
        # module level to a value that folds", which is the only case where the
        # store itself has no effect the substitution would miss. A name bound
        # twice, or by an augmented assignment, is body: the ORDER of the
        # stores is the program, and `site` is `rebound` for exactly that.
        return sym.site == "assigned" and sym.line == (getattr(stmt, "line", 0)
                                                       or 0)

    def _is_image_initialized(stmt) -> bool:
        """A module-level store the IMAGE already contains.

        The same question `_is_folded_constant` asks — "does this store have an
        effect the program would miss if the store were not emitted?" — with the
        other of the two answers, and it is the answer that became reachable when
        module globals got storage. A module-level name whose value is a
        CONTAINER literal is a `__DATA` slot whose words are laid out by the
        linker before the program starts (`collect_global_slots` gives every
        such name a slot, precisely because a container is not a foldable
        value). The store is therefore not a statement the body has to run: the
        value is in the image.

        Measured, and the failure this exemption prevents is not a missing value
        but a program that computes the right answer somewhere nobody looks.
        `NUMS = [10, 20, 30]` above a `def main` left the binding in the body,
        so `entry_function` chose the MODULE BODY as the entry (rule 1 is "the
        body first"), `main` was never called, and the image materialised the
        list on its own stack, discarded it and exited 0 — printing nothing,
        silently, on both architectures. The same source under
        `NUMS = [10, 20, 30]` and a body that does nothing else has no other
        statement to run, so the body was pure loss.

        Asked from the STATEMENT, with the very predicate `collect_global_slots`
        keys its second rule on, so "which names have a slot" and "which stores
        the image already holds" cannot disagree. Which of the several stores to
        one name is which does not matter: `collect_global_slots` keeps the LAST
        binding as the initializer, so an earlier store of a container literal is
        overwritten before anything can read it and dropping it changes nothing.
        """
        name = _module_binding_name(stmt)
        if name is None:
            return False
        return _is_static_container(getattr(stmt, "value", None))

    def _is_real_store(stmt) -> bool:
        return not (_is_folded_constant(stmt) or _is_image_initialized(stmt))

    out = []
    for stmt in stmts or []:
        kind = type(stmt).__name__
        if kind in _MODULE_BODY_DECLARATIONS:
            continue
        if is_docstring_statement(stmt):
            continue                    # a bare string statement is not body
        if kind == "PassStmt":
            continue                    # the statement that does nothing
        if kind in _MODULE_BODY_BINDINGS and not _is_real_store(stmt):
            continue
        out.append(stmt)
    # A store the image already holds that the body REBINDS is not redundant,
    # and exempting it is how a correct program gets a wrong answer.
    #
    # `total = 0` at file level folds, so the store is normally left out and
    # the literal is substituted at each read. But if the body then writes the
    # name — `for i in range(5): total = total + i` — the substitution does
    # NOT fire inside the body (the body binds the name, which is what
    # `_substitute_module_constants` checks), so the read at the top of the
    # loop has no store to read: the allocator gave the name a register and
    # nothing ever wrote it, and the program printed 10 on the same source
    # where CPython says 10. Measured, both backends, and the identical
    # program inside a `def` is right — the difference is exactly the missing
    # store. `NUMS = [10, 20, 30]` under a body that writes `NUMS` is the same
    # shape with the slot as the module's home rather than a register.
    #
    # The condition is asked with the register allocator's OWN walk
    # (`bound_names_in_order`), not a second one: the exemption has to agree
    # with the pass that decides which names have a register, or "is this name
    # in the body" has two answers and the wrong one is the one that decides
    # whether a store is emitted.
    rebound = set()
    if out:
        from mojo.middle.boundnames import bound_names_in_order
        try:
            rebound = {n for n in bound_names_in_order(out, [])
                       if isinstance(n, str)}
        except Exception:
            rebound = set()
    if not rebound:
        return out
    kept = {id(s) for s in out}
    final = []
    for stmt in stmts or []:
        exempt = (type(stmt).__name__ in _MODULE_BODY_BINDINGS
                  and not _is_real_store(stmt))
        if exempt and _module_binding_name(stmt) in rebound:
            final.append(stmt)          # the store the body needs
        elif exempt:
            continue                    # in the image; no store to emit
        elif id(stmt) in kept:
            final.append(stmt)
    return final


# The statements whose presence in a `try`'s handler arm costs the image
# nothing, and the ONE list they are asked from.
#
# A handler arm is not EMITTED on this path — `formal/arm64_codegen.py`'s
# `_emit_try` and `formal/x86_64_codegen.py`'s skip the arms outright, and
# `RaiseStmt` flushes the pending `finally` clauses and then `exit(1)`s, so
# there is no edge from a raise site into an arm and no edge out of one — which
# makes the four statements below the four whose absence changes nothing:
#
#   * `pass` — there is nothing to drop;
#   * `raise` — the arm cannot run, and a `raise` here would have left the
#     process, so dropping it changes no answer the image gives;
#   * `continue`, `break` — control transfers out of an arm the image never
#     enters.
#
# Anything ELSE in an arm is a store, a call or a statement the program wrote
# and the image does not contain, which is why `refuse_dropped_handler_arm` is
# asked about it rather than about the arm's mere existence: `except: pass` is
# the commonest shape in the corpus and must keep building.
_HANDLER_ARM_NO_EFFECT = ("PassStmt", "RaiseStmt", "ContinueStmt", "BreakStmt")


def unemitted_handler_arm(fn):
    """The first handler arm of `fn` whose body is not in the image, or None.

    `(handler, statement)` for the statement that made the arm worth refusing,
    so the message can point at a line the reader wrote rather than at the arm.
    `None` is the answer for every function without one — which is the answer
    for the overwhelming majority, and the reason this is a walk and not a
    per-`try` flag threaded through the emitters.
    """
    for node in iter_nodes(getattr(fn, "body", None)):
        if not isinstance(node, F.TryStmt):
            continue
        for handler in (getattr(node, "handlers", None) or []):
            for stmt in (getattr(handler, "body", None) or []):
                if type(stmt).__name__ not in _HANDLER_ARM_NO_EFFECT:
                    return (handler, stmt, node)
    return None


def _emitted_nodes(node):
    """`iter_nodes` minus every `handlers` list, whatever node it hangs off.

    A `handlers` list is never emitted — both `_emit_try`s skip the arms — so a
    walk that descends into one finds statements the image does not contain and
    reasons about a program nobody wrote. That is the whole difference from
    `iter_nodes`, and it is why this is a function rather than a filter: the
    arms are the one subtree whose absence is load-bearing.
    """
    if isinstance(node, (list, tuple)):
        for x in node:
            yield from _emitted_nodes(x)
        return
    if not hasattr(node, "__dataclass_fields__"):
        return
    yield node
    for name in _node_field_names(node):
        if name == "handlers" and isinstance(node, F.TryStmt):
            continue
        yield from _emitted_nodes(getattr(node, name))


def _emitted_regions(try_stmt) -> tuple:
    """The three statement lists of a `TryStmt` that reach the image.

    `body`, `else_body`, `finally_body` — everything but `handlers`, which is
    the arm the emitters skip. A `raise` in any of the three leaves the image
    the same way, so all three are one question; `else_body` counts because it
    is emitted inline on the success path and a `raise` in it is just as
    terminal.
    """
    return (getattr(try_stmt, "body", None),
            getattr(try_stmt, "else_body", None),
            getattr(try_stmt, "finally_body", None))


def _call_keys(node, bound_modules=None) -> tuple:
    """The distinct callee KEYS of an emitted subtree.

    `(kind, name, module)`: `("plain", "boom", "")` for `boom(…)`,
    `("method", "get", "")` for `x.get(…)`, `("method", "boom", "h2")` for
    `h2.boom(…)`, `("plain", "boom", "h2")` for `boom(…)` in a unit that wrote
    `from h2 import boom`. Deduplicated because the question is "can this region
    reach a raise", not "how many times". A callee that is neither shape gets
    `("other", "", "")`, and `external_call[…]` gets none at all: it is a C
    symbol by construction, it returns, and there is no frame of ours for it to
    raise into.

    **The third element is what makes an imported callee resolvable, and it is
    here rather than in `RaiseGraph` because the AST is where the two spellings
    differ.** `x.get(…)` and `h2.boom(…)` are the same node shape — a
    `MemberExpr` callee — and the receiver is the ONLY thing that tells a
    method on a value from a function on a module. `bound_modules` is
    `{bare name: module}` for the unit's own `from mod import f` statements,
    which `import_bindings` reads and which is the other half: `boom(…)` in a
    unit that wrote `from h2 import boom` names a bare callee, so without the
    binding it is the same unresolved name as `dict.get`.

    Both are EMPTY/None by default so that a caller with no unit in hand — the
    `RaiseGraph` constructor's own per-function walk — gets the conservative
    answer it always got.
    """
    out = set()
    for n in _emitted_nodes(node):
        if not isinstance(n, F.CallExpr):
            continue
        func = getattr(n, "func", None)
        if is_external_call_template(func):
            continue
        if isinstance(func, F.IdentExpr):
            out.add(("plain", func.name,
                     (bound_modules or {}).get(func.name, "")))
        elif isinstance(func, F.MemberExpr):
            # The receiver decides. A `MemberExpr` whose object is a plain name
            # is a MODULE call when that name is a module this unit imported and
            # a METHOD call otherwise, and the two need different answers — so
            # the qualifier is carried and `RaiseGraph` asks the published
            # module table with it rather than guessing here.
            obj = getattr(func, "obj", None)
            qualifier = ""
            if isinstance(obj, F.IdentExpr):
                qualifier = obj.name if (bound_modules or {}).get(
                    obj.name, "") else ""
            out.add(("method", func.member, qualifier))
        else:
            out.add(("other", "", ""))
    return tuple(sorted(out))


class RaiseGraph:
    """Which calls in one image can reach a `raise`, resolved as far as it goes.

    **A `raise` is not an exception on this path, it is `exit(1)`.**
    `_emit_diverge` flushes the pending `finally` clauses and then traps, from
    WHATEVER function contains the statement — so no frame anywhere can catch
    one, not even across a call into a linked library, whose own `raise` exits
    that library's process just the same. That single fact is what this whole
    class exists to propagate: which of an image's functions can end the
    process, so that a `try` with arms can be told before it is emitted that
    its arms are unreachable.

    The set is a fixed point over the image's own call graph rather than one
    sweep, because `a()` calling `b()` calling `raise` is the ordinary shape and
    a single pass would miss it; a cycle cannot hide a raise behind itself,
    because membership only ever grows.

    **A callee this pass cannot see is NOT counted as raising**, and that is a
    measured decision rather than the safe-looking one. A bare name with no
    definition in this unit and no C prototype, a method name nothing here
    declares (`dict.get`, `Path.is_file`, a hostmod entry point), and a callee
    that is an expression rather than a name are all UNKNOWN, and an unknown
    callee inside a `try` with arms is exactly where the conservative answer
    would refuse. Measured over this repository's 479 `.py`/`.mojo` files by
    asking this question and nothing else (parse-only, no codegen): the definite
    answer is 14 files, the unknown answer is 82 — a five-fold over-refusal of
    the whole corpus, nearly all of it `try: … except OSError:` around I/O this
    path cannot raise from, bought against a POSSIBILITY rather than a fact.

    **"Cannot see" no longer includes a module this image COMPILES.** That
    branch of the unknown answer was measured on a `RaiseGraph` built from one
    unit, and an imported callee was in it — so the 82 was not all host
    modules and builtins, and the part that was a resolvable module was a WRONG
    answer rather than a shrug. `publish_module_raisers` records each compiled
    module's raisers and `_callee_raises` asks it, so the unknown tier is now
    exactly what it says it is: a host module, a `--link-dylib` library, or a
    builtin method — none of which this pass can read the body of.

    **What the residual is NOT is a call into another image.** That was the
    largest part of it, and it is now answered: a module this build links is
    source on disk and `module_statements` already parses it, so the FUNCTION
    question is the published per-module table and the METHOD question — the
    one dispatch reaches by NAME alone — is `formal/imports.py`'s
    `CrossModuleRaises` over the separated sets `module_raising_names` keeps.
    Three spellings of "a function of another module" were being read as
    something local — `mod.f(…)` as a method call, a from-imported name as a
    bare name, and a linked struct's method as a method declared here — and each
    was therefore decided by whatever THIS image happened to declare. The corpus
    cost of answering them is measured at zero files (every file whose answer
    moved is already refused for an unresolvable import, which outranks this
    check), and the residual is the rest.

    The rule the pair of them obeys is unchanged and is what the second half of
    the 82 still rests on: **refuse on a FACT, and say so where the fact is
    missing.** The expression tier (`("other", "")`) is the one whose answer
    changed with this fix: it used to be `False`, i.e. "cannot raise", which is
    the one direction a refusal must never be wrong in. It is now `True` —
    unknown, so refuse — and the cost is measured at the files it now refuses
    rather than the files it used to let through.
    """

    def __init__(self, functions, externs=(), bound_modules=None,
                 cross=None):
        """`bound_modules` is this unit's import table (see `_call_keys`), and
        `cross` is `formal/imports.py`'s `CrossModuleRaises` — the two
        cross-module readers, or None/empty when this build has no cross-module
        table to ask.

        They answer the two questions about a callee in ANOTHER image that this
        class used to answer `False` for without being able to place it: a
        FUNCTION of another module — `mod.f(…)` and `from lib import f`, which
        before were read as a METHOD call and a bare name of this image and so
        decided by whatever THIS unit happened to declare — is answered by the
        published per-module table (`publish_module_raisers`), and a METHOD of a
        linked struct is answered by `cross.method(…)`, out of the separated
        method sets that keep an exported function called `read_file` from
        raising the question for every `x.read(…)`. `None` for both keeps every
        in-file answer byte for byte what it was.
        """
        self._cross = cross
        by_name = {}
        for fn in functions or ():
            name = getattr(fn, "name", None)
            if isinstance(name, str):
                by_name.setdefault(name, fn)
        self.externs = frozenset(externs or ())
        self.defined = frozenset(by_name)
        # `{bare name: module}` for the unit's own `from mod import f`
        # statements. Kept because the EDGE pass needs it too: `boom(…)` in a
        # unit that wrote `from h2 import boom` is a call into another module,
        # and without this it is indistinguishable from a free name.
        self.bound_modules = dict(bound_modules or {})
        # Method dispatch on this path is BY NAME — a call site carries no
        # receiver type — so `x.f(…)` is answered by every method of that name
        # in THIS image, which is the same over-approximation the dispatch itself
        # makes. `cross.method(…)` extends that one rule across the boundary
        # rather than adding a second, looser one, and it is asked per call site
        # by `_callee_raises` rather than folded into `raising_methods`: this
        # image's table is a fixed point over functions, and a cross-module
        # method is not a function of this image that can be marked.
        self.methods = frozenset(
            name.partition("_")[2] for name in by_name
            if name.partition("_")[2])
        edges, lexical = {}, set()
        for name, fn in by_name.items():
            plain, method, other = set(), set(), False
            for kind, callee, module in _call_keys(getattr(fn, "body", None),
                                                   self.bound_modules):
                if module:
                    # A call into ANOTHER module of this image. It cannot be an
                    # edge to one of this unit's functions, and it is answered
                    # by the published per-module table at ASK time rather than
                    # here — a module's raisers are not known until it has been
                    # compiled, which happens after this graph is built. So it
                    # contributes no edge and is not `other` either: it is a
                    # question with an answer, asked elsewhere.
                    continue
                if kind == "plain":
                    plain.add(callee)
                elif kind == "method":
                    method.add(callee)
                else:
                    other = True
            # A method name resolves to every lifted name `<Struct>_<method>`,
            # and a callee that is an EXPRESSION rather than a name is as
            # unresolved here as it is in the emitter until the link resolves it
            # — so `other` seeds the unknown set for this function, not just for
            # the region. A `mod.f(…)` is NOT `other`: it is answered by the
            # published table and `_calls_raising_export` below, which is a
            # fact rather than a shrug.
            edges[name] = plain | {n for n in by_name
                                   if n.partition("_")[2] in method}
            if other:
                edges[name] |= {_UNRESOLVED}
            if any(isinstance(n, F.RaiseStmt)
                   for n in _emitted_nodes(getattr(fn, "body", None))):
                lexical.add(name)
        # A function that calls INTO another image's raising function ends the
        # process just as surely as one that calls a raising function of its own,
        # so the cross-module answer enters the same fixed point rather than
        # being consulted only at the `try`. These are definite answers — the
        # callee's own module published them — so they belong here, and
        # `_UNRESOLVED` is deliberately not how they arrive: that sentinel is
        # excluded from propagation on purpose (an unplaceable callee is not
        # evidence), and a published answer IS evidence.
        for name, fn in by_name.items():
            if self._calls_raising_export(fn):
                lexical.add(name)
        self.raising = set(lexical)
        changed = True
        while changed:
            changed = False
            for name, callees in edges.items():
                if name in self.raising:
                    continue
                # Only DEFINITE reachability propagates here. `_UNRESOLVED` in
                # `callees` says "some callee this pass cannot see", which is
                # not by itself evidence that this function raises; the
                # image-wide question is `may_reach_raise`'s, asked per call
                # site, where the reader's own spelling is in hand.
                if callees & self.raising:
                    self.raising.add(name)
                    changed = True
        self.raising_methods = frozenset(
            attr for attr in self.methods
            if any(other.partition("_")[2] == attr and other in self.raising
                   for other in by_name))
        self.any_raising = bool(self.raising)

    def _calls_raising_export(self, fn) -> bool:
        """Does `fn` call a function or method of ANOTHER image that raises?

        The FUNCTION half asks the cross-module table for a module-qualified
        key: `cross` when this graph has one (it recurses through the
        imports' own imports, with a cycle guard), else the published
        per-module table (populated for this unit's direct imports before the
        graph is built). The METHOD half is `cross` for a key with no module,
        because a call on a VALUE carries no receiver type and the receiver
        may be a struct of a module this image links. Both are facts about
        another image rather than this one, which is what separates them from
        the edge set.
        """
        for kind, callee, module in _call_keys(getattr(fn, "body", None),
                                               self.bound_modules):
            if module:
                if self._cross is not None:
                    if self._cross.function(module, callee):
                        return True
                else:
                    raisers = module_raisers(module)
                    if raisers is not None and callee in raisers:
                        return True
            elif kind == "method" and self._cross is not None:
                if self._cross.method(callee):
                    return True
        return False

    def _callee_raises(self, kind, name, module="") -> bool:
        """Can this callee end the process? `False` for everything unresolved.

        **`module` is the third term and it is what makes that 82 smaller.**
        A callee this image COMPILED is not unresolved: `publish_module_raisers`
        recorded which of its functions reach a `raise` when it was built, so
        `try: h2.boom()` and `try: boom()` (after `from h2 import boom`) are
        both answerable. The three outcomes are kept distinct on purpose:

          * a module this image compiled, with `name` in its raisers — a FACT,
            and the refusal names the callee;
          * a module this image compiled, with `name` NOT in them — also a fact,
            and `False`, which is what stops every call into a compiled module
            from becoming a possibility again;
          * a module it did not compile (a host module, a `--link-dylib`
            library, a builtin method) — still `False`, still the residual.

        So the third case is the doc's residual and the first two are what it
        said had to be built; the measurement to watch is the third falling
        towards 0 while the certain tier is unchanged.

        **`("other", "")` is the one tier that is NOT a fact and NOT a residual
        of the above.** It is a callee that is an EXPRESSION rather than a name
        — `f(…)` where `f` is a local holding a function value, `self.callbacks[k]()`,
        a `__getitem__`-dispatched call. `_call_keys` cannot see a binding, but
        the image can: this function's local `f` holds a function VALUE, and
        that value may be this image's own raiser. The class's own refusal
        (`call_result_frame_struct`) exists precisely because calling one is
        ordinary on this path. So `("other", "")` is the one case where the
        answer is not "cannot raise" but "unknown", and unknown is the one
        direction a refusal must never be wrong in: a `try` whose body calls
        `handlers[i](x)` where `handlers` is a list of this image's functions
        is a program whose arm is unreachable, and it builds. It therefore
        answers `True` here, which is what makes the `try` refuse.
        """
        if module:
            raisers = module_raisers(module)
            if raisers is None:
                return False
            return name in raisers
        if kind == "plain":
            if name in self.externs:
                return False
            return name in self.defined and name in self.raising
        if kind == "method":
            if name in self.raising_methods:
                return True
            # An imported struct's method of this name. Dispatch is by name, so
            # `b.get(…)` is the same question whichever image declared `get`,
            # and answering it from this image's table alone is what let a `try`
            # around a raising method of a LINKED struct build, print nothing
            # and exit 1 where CPython catches and continues.
            return bool(self._cross is not None and self._cross.method(name))
        # A callee that is an EXPRESSION rather than a name: unknown, so refuse.
        return True

    def may_reach_raise(self, node) -> tuple:
        """`(kind, name, module)` for a callee in `node` that can end the process,
        else None.

        The first one found, in the region's own order, so the message can name
        the call the reader wrote rather than the callee set.
        """
        for key in _call_keys(node, self.bound_modules):
            if self._callee_raises(*key):
                return key
        return None


#: The sentinel an unresolved callee contributes to the edge set. A string a
#: program cannot spell as a function name, so it cannot collide with one.
_UNRESOLVED = "\x00unresolved\x00"


#: `{module identity: {function name that can end the process}}`, for the units
#: of ONE image. See `publish_module_raisers` for why this is published rather
#: than threaded, and why it REPLACES per module where
#: `publish_non_ascii_strings` accumulates.
_MODULE_RAISERS: dict = {}


def publish_module_raisers(module: str, names) -> None:
    """Record that `names` in the module addressed as `module` can end the process.

    **This is the doc's step 1, and the reason it has to be a PUBLISHED table
    is that the answer is not available where it is asked.** `RaiseGraph` is
    built in `formal/build.py::_prepare_functions` from ONE unit's function
    list, and the imported units have been compiled and thrown away by then —
    each `build_module_dylib` is a nested `_prepare_functions` that publishes
    ITS module's globals over ours on the way out (see the order note above
    `check_module_symbols` in `build.py`, which is why those two tables are
    re-published rather than published once). So a `try: mod.boom()` in the
    entry unit, where `mod.boom` raises in a library, was unanswerable and
    answered `False`.

    **That `False` was a wrong answer and not a shrug.** Measured on both
    architectures, `h2.mojo` with `def boom(): raise ValueError(…))` imported by
    an entry whose `main` is

        try:
            boom()
        except:
            pass
        printf("caught\\n")

    BUILT, printed nothing and exited 1, where CPython prints `caught` and exits
    0 — the whole-program class `uncatchable_raise` exists to refuse, reached
    through the one door its own call graph cannot see. So this table is what
    turns that build into a refusal that names the callee.

    **REPLACES per module, ACCUMULATES across modules, and the two directions
    are the same argument as `publish_non_ascii_strings` made.** A unit's own
    answer is a fact about that unit and a second answer for the same module in
    one image would be a conflict rather than a union — so a module's entry is
    replaced. But which modules EXIST in an image is the union over its units,
    exactly as the non-ASCII literal list is: `h2` compiled first and `main`
    second is the ordinary order, and `main` must be able to ask about `h2`.
    `clear_module_raisers` makes that union per-IMAGE rather than per-process,
    for `clear_non_ascii_strings`'s reason.

    **`module` is the dotted identity an importer spells** (`own_module_identity`
    in `formal/imports.py`), not a source path, because the call site carries
    the dotted name and nothing else.
    """
    if not module:
        return
    _MODULE_RAISERS[str(module)] = frozenset(str(n) for n in (names or ()))


def module_raisers(module: str):
    """The raising names of the module addressed as `module`, or None.

    **None and an EMPTY set are different answers and must stay different.**
    None means "this image never compiled a module by that name", which is the
    residual — the callee is unresolved and nothing is known. An empty set means
    "it was compiled, and none of its functions can raise", which is a fact and
    the cheap one: it is what lets an ordinary `try: mod.helper()` around a
    module that raises nothing keep building, instead of every call into a
    compiled module becoming a possibility again.
    """
    return _MODULE_RAISERS.get(str(module)) if module else None


def clear_module_raisers() -> None:
    """Start a NEW IMAGE's set of compiled modules over.

    The counterpart of `clear_non_ascii_strings`, and it exists for the same
    reason: a test that builds two programs in one process must not have the
    second one refuse a `try` because of a module only the first compiled. The
    one caller that is not a test is `formal/build.py`'s `compile_formal`, at
    the top of the image.
    """
    global _MODULE_RAISERS
    _MODULE_RAISERS = {}


def uncatchable_raise(fn, graph=None) -> tuple:
    """The first `raise` a `try` in `fn` cannot deliver to any of its arms.

    `(raise_stmt_or_None, try_stmt, handler, callee)` — the first arm is named
    because the message is about the arm the reader wrote, the same reason
    `unemitted_handler_arm` returns the handler beside the statement. The
    statement is `None` and the `callee` key is set when the raise is reached
    THROUGH a call rather than written inside the `try`, which is the shape
    almost every instance of this has. That key is `RaiseGraph.may_reach_raise`'s
    own: `(kind, name, module)`, where a non-empty `module` is a call into
    ANOTHER image.

    **This is the other half of `unemitted_handler_arm`, and it is about
    CONTROL FLOW rather than about an arm's body.** That check asks whether an
    arm holds a statement whose absence would be visible; it says nothing about
    what happens to the `raise` that was supposed to REACH the arm, so
    `except: pass` passed it — correctly, since there is nothing in the arm to
    drop — and the program still came out wrong. Measured on both
    architectures:

        class MyErr(ValueError): ...
        def boom():
            raise MyErr("the message")
        def main(n):
            try:
                boom()
            except:
                pass
            print("caught")
            return 0

    built, exited 1, and printed NOTHING; CPython prints `caught` and exits 0.
    The arms are not the loss — an empty arm loses nothing — the loss is that
    the `raise` ends the process where CPython runs the arm and CONTINUES, so
    every statement after the `try` is unreachable in the image and reachable in
    the program. That is the wrong-but-exit-0 artifact CLAUDE.md names as the
    failure this backend exists to make impossible, wearing an exit status of 1.

    Note where the `raise` is: in ANOTHER FUNCTION. That is why this asks
    `RaiseGraph` and not a lexical walk — `try: boom()` contains no `raise` at
    all, and a walk would have called this program fine. A try with NO arms is
    not asked about, and neither is a raise outside any try, because there
    `_emit_diverge` is exactly CPython's answer for an exception nothing catches
    (status 1). The refusal is about the one shape where this path silently
    computes something else.
    """
    for node in iter_nodes(getattr(fn, "body", None)):
        if not isinstance(node, F.TryStmt):
            continue
        handlers = getattr(node, "handlers", None) or []
        if not handlers:
            continue
        for region in _emitted_regions(node):
            for inner in _emitted_nodes(region):
                if isinstance(inner, F.RaiseStmt):
                    return (inner, node, handlers[0], None)
            if graph is not None:
                hit = graph.may_reach_raise(region)
                if hit is not None:
                    return (None, node, handlers[0], hit)
    return None



def exception_type_spelling(handler) -> str:
    """`ValueError`, `(TypeError, KeyError)`, `except:`, `except E as e`.

    The arm's own catch clause, as the reader wrote it, because the refusal is
    about ONE arm and a message that named only the `try` would send the reader
    looking through the arms for the one at fault. A parser that produces a bare
    string for one name and a LIST of them for the tuple form is why this is a
    function: `except (A, B) as e` spelled with the parentheses and the `as` is
    two attributes and one line.
    """
    exc = getattr(handler, "exc_type", None)
    if not exc:
        head = "a bare `except:`"
    elif isinstance(exc, (list, tuple)):
        head = "`(" + ", ".join(str(e) for e in exc) + ")`"
    else:
        head = f"`{exc}`"
    alias = getattr(handler, "name", None)
    return f"{head} as {alias}" if alias else head


def refuse_dropped_handler_arm(fn, found) -> str:
    """Why this `try`'s handler arm is not in the image, in the reader's terms.

    `found` is `unemitted_handler_arm`'s `(handler, statement, try_stmt)`.

    The refusal exists because the alternative was SILENCE, and this file has
    been shown what that costs: a handler body can store, call and print, and
    with nothing to say so the program built, ran, and was not the program that
    was written — `except ValueError: printf("HANDLER RAN")` printed nothing and
    exited 0, with no diagnostic on either stream. That is the failure class
    CLAUDE.md names ("a wrong-but-exit-0 artifact that every other check is
    structurally blind to"), and 921 arms in this repository's own 400 files
    have a body.

    So this refuses the arm BY NAME and says what the path actually does, which
    is the only sentence that is true of both the language and the image: the
    arm is not dead (CPython enters it whenever the body raises) and it is not
    unreachable either (this backend has no unwinder), it is NOT OURS. The three
    ways out are all named, because they are different edits:

      * move the body into the `try` or after it, when it is really cleanup for
        the success path — which is what most `except: log-and-carry-on` arms
        are, and what a `finally` expresses;
      * `raise` at the end of the arm, when the program means to fail: `raise`
        IS emitted (it flushes the pending `finally` clauses and exits), so an
        arm that only re-raises changes no answer;
      * return the value the program wants on failure, in the arm's own `return`
        — but note that a `return` is an effect too, so it is refused as well.
        This is deliberate: a program whose answer DEPENDS on which arm ran is a
        program this path cannot compute, and saying so is the point.
    """
    handler, stmt, _try = found
    line = getattr(stmt, "line", 0) or 0
    where = f"line {line}: " if line else ""
    return (
        f"{where}{exception_type_spelling(handler)} is a handler arm with a body "
        f"this path cannot put in the image, so it is refused rather than "
        f"dropped: `formal` has no exception unwinder, so no edge runs from a "
        f"raise site into an arm — a `raise` flushes the enclosing `finally` "
        f"clauses and exits the process — and every statement in this arm "
        f"(`{type(stmt).__name__}`) would be absent from the program that runs. "
        f"Its effects would be silently missing: the image would build, exit 0, "
        f"and not be the program you wrote, which is the one failure a value "
        f"this compiler cannot detect on its own. An arm whose body is `pass`, "
        f"`raise`, `continue` or `break` still builds — nothing is lost by "
        f"leaving it out. Otherwise: move the work into the `try` body or after "
        f"the statement (a `finally` if it is cleanup for the success path), or "
        f"end the arm with `raise` if the program is meant to fail there.")


def refuse_uncatchable_raise(found) -> str:
    """Why this `raise` cannot be caught by the arm written above it.

    `found` is `uncatchable_raise`'s `(raise_stmt, try_stmt, handler, callee)`.
    The last element names the CALL when the raise is reached through one,
    because "this `try` cannot catch its own exceptions" sends the reader
    looking at the arms while the thing that ends the process is a function two
    frames away.

    **It reuses the arm refusal's own facts rather than stating new ones**,
    because there is one reason here and not two: this path has no exception
    unwinder, so no edge runs from a raise site into an arm. `refuse_dropped_
    handler_arm` says that when the arm holds a statement whose absence is
    visible; this says it when the arm holds nothing and the `raise` still goes
    past it — which is the shape `except: pass` is, and the commonest one in the
    corpus (`_HANDLER_ARM_NO_EFFECT`'s comment says so and is right about the
    ARM, which loses nothing, while saying nothing about the control flow that
    follows).

    The symptom is a build that succeeds and a program that is not the one
    written, and the exit status makes it worse rather than better: CPython
    enters the arm and continues, so the statements after the `try` are part of
    the program's answer; here the `raise` leaves the image with status 1 and
    those statements are not in it at all. The two halves of the old behaviour —
    the arm skipped, the raise terminal — were each defensible alone. Together
    they are a `try` that catches nothing and a program that stops where CPython
    does not.

    The ways out are the three that are true of this path, and the first is the
    one most of these programs want: **nothing in the `try` can raise**, so drop
    the `except` and keep the `try` for its `finally` — which IS emitted, on
    every path out including the one that raises.
    """
    stmt, _try, handler, callee = found
    line = getattr(stmt, "line", 0) or 0
    where = f"line {line}: " if line else ""
    if stmt is not None:
        how = "this `raise` is inside the `try`"
    else:
        kind, name, module = (callee + ("",))[:3] if callee else ("", "", "")
        if module:
            # The imported spelling, and it is named in full because the reader
            # wrote it: `h2.boom()` and `boom()` after `from h2 import boom`
            # are the same function reached two ways, and the message has to
            # say which one this call site used so the reader knows which file
            # to look in.
            how = f"the `try` body calls `{module}.{name}(…)`"
        elif kind == "plain":
            how = f"the `try` body calls `{name}(…)`"
        elif kind == "method":
            how = f"the `try` body calls the method `{name}(…)`"
        else:
            how = ("the `try` body calls something this pass cannot resolve to a "
                   "definition")
        how += ", which can end the process"
    return (
        f"{where}{how}, and the arm written as "
        f"{exception_type_spelling(handler)} cannot catch it, so the `try` is "
        f"refused rather than silently ignored: `formal` has no exception "
        f"unwinder, so no edge runs from a raise site into an arm. A `raise` "
        f"here flushes the enclosing `finally` clauses and exits the process "
        f"with status 1, which is what CPython does for an exception nothing "
        f"catches — but CPython DOES catch this one and goes on to the "
        f"statements after the `try`, so the image would build, print nothing "
        f"and exit 1 where the program prints its answer and exits 0. Nothing "
        f"is lost by leaving the ARM out (an arm of `pass`, `raise`, `continue` "
        f"or `break` is not refused for its body), and that is exactly why this "
        f"shape was missed: the arm loses nothing, the control flow after it "
        f"loses everything. If nothing in the `try` can raise, drop the arm and "
        f"keep the `finally`, which is emitted on every path. If the program "
        f"means to fail here, let the `raise` stand on its own outside any "
        f"`try` — that is emitted and is CPython's own answer.")


def call_result_frame_struct(call, functions: dict, decls: dict):
    """The struct whose VALUE `call` evaluates to, when it is decidable, else None.

    The one question a comparison rewrite asks about an operand that is a CALL
    rather than a name, and it is asked the way `_rhs_pointee` asks the same
    question about a pointer: from the CALLEE's own declaration, read out of this
    image's function table. A call to something this image does not contain
    answers None rather than guessing, which is the same conservative direction
    every other type question on this path takes.

    Three conditions, each load-bearing:

      * the callee is a bare name in `functions` — a lifted method call
        (`A_m`), a dotted call (`mod.f`) and an `external_call` all name
        something whose return type is not stated here, and a receiver's own
        declared type is a different question with a different answer;
      * the declared return type's BASE name (`annotation_base_name`, which
        reads `CStringSlice[ImmutOrigin[origin_of(self)]]` as `CStringSlice` and
        an unannotated callee as nothing at all) names a struct of THIS image;
      * that struct is one this path represents as a FRAME or as a single word
        (`struct_is_framed` / `struct_is_one_word`), because the caller passes
        the value straight to a method whose first parameter is a receiver and
        the two representations are not interchangeable.

    `None` is a refusal and never a zero: an unknown callee is a real function
    whose return type this image does not state, and treating it as "not a
    struct" would leave the caller with the address compare it is trying to
    replace.
    """
    if not isinstance(call, F.CallExpr) or not isinstance(call.func,
                                                        F.IdentExpr):
        return None
    callee = (functions or {}).get(call.func.name)
    ann = getattr(callee, "return_type", None) if callee is not None else None
    if not ann:
        return None
    base = annotation_base_name(ann)
    st = (decls or {}).get(base) if base else None
    if st is None:
        return None
    if struct_is_framed(st) or struct_fits_one_word(st):
        return st
    return None


def module_body_refusal(stmt):
    """Why a top-level statement cannot be lowered as the module body, or None.

    The entry point runs the body as a function, so a statement that means
    something only at file level — a bare `return`, a `global`/`nonlocal` that
    names a scope which does not exist, a `yield`/`await` that would make the
    module a generator or a coroutine — has no meaning inside one, and the
    wrapper function must refuse it BEFORE it is wrapped.

    None for everything else, and that is most things: an ordinary statement
    wrapped in a function is an ordinary statement, and the backends already
    lower it or already refuse it, by name, from inside a function body. This
    function is asked only about the handful of shapes whose MEANING changes
    with the wrapping, because a refusal that says "unsupported statement" and
    not WHICH sends the reader to the file rather than to the line."""
    kind = type(stmt).__name__
    line = getattr(stmt, "line", 0) or 0
    where = f"line {line}: " if line else ""
    if kind == "ReturnStmt":
        return (f"{where}a `return` at file level returns from nothing: this "
                f"path runs a module's top-level statements as the body of a "
                f"synthetic function, so a `return` here would return from "
                f"that function rather than from a function the source wrote. "
                f"Move it inside a `def`")
    if kind in ("GlobalStmt", "NonlocalStmt"):
        return (f"{where}a `{kind[:-4].lower()}` declaration at file level "
                f"names a scope that does not exist — the module's own "
                f"top-level statements are not a scope a `global` can refer "
                f"to, and the synthetic function they run in has a real local "
                f"frame instead. Move it inside a `def`")
    if kind in ("BreakStmt", "ContinueStmt"):
        return (f"{where}a `{kind[:-5].lower()}` at file level has no loop to "
                f"be in: the module's top-level statements run straight "
                f"through. Move it inside a `def`")
    for node in iter_nodes(stmt):
        nk = type(node).__name__
        if nk in ("YieldExpr", "YieldFromExpr"):
            return (f"{where}a `yield` at file level makes the MODULE a "
                    f"generator, and there is nothing on this path that "
                    f"iterates a module: the top-level statements are lowered "
                    f"as one function's body, so the `yield` would leave its "
                    f"value in a register the program never reads. Put the "
                    f"`yield` in a `def` and call that")
        if nk == "AwaitExpr":
            return (f"{where}an `await` at file level makes the MODULE a "
                    f"coroutine, and this path has no event loop to await on: "
                    f"the top-level statements are lowered as one function's "
                    f"body, where `await` is the identity, so the program "
                    f"would run the awaitable and throw the result away. Put "
                    f"the `await` in an `async def`")
    return None


def yield_bearing_functions(functions) -> list:
    """Every function in `functions` whose OWN body holds a `yield`.

    A list rather than a yes/no because the reader's question is "which
    function", and a message that named only the first would leave the same
    file refused for the second the moment the first was fixed.

    The SCOPE question is not re-answered here: it is `FunctionDef.is_generator`
    as the front end set it (`fire_compiler.py`'s `_scan_yield_bearing`, which
    stops at a nested `def`, a lambda and a comprehension because those are
    Python's own scope boundaries). A second walk with a second rule would be a
    second answer to "whose `yield` is this", and the two would disagree on
    exactly the case that is hardest to see — a `yield` inside an inner `def`
    belonging to the outer one.

    Nested definitions are included, each reported as the function that OWNS its
    `yield`, which is the front end's answer for the same reason. Asked before
    `formal/build.py`'s `_flatten_closures` renames a nested `def` to its lifted
    symbol, so the name in a refusal is the name the reader wrote.

    A generator EXPRESSION is not here and never can be: the parser represents
    `(x for x in xs)` as a `Comprehension` with `kind == "generator"`, not as a
    function, and it lowers (`formal/build.py` builds `fire_compiler.py`'s
    `genexp_body` statement list for it). Only a `def` that says `yield` is a
    generator function, and only that is refused.
    """
    out: list = []
    for fn in (functions or []):
        if getattr(fn, "is_generator", False):
            out.append(fn)
        for node in iter_nodes(getattr(fn, "body", None)):
            if (isinstance(node, F.FunctionDef)
                    and getattr(node, "is_generator", False)):
                out.append(node)
    return out


def generator_function_refusal(functions) -> str:
    """Why a generator function is not in the image, or None when there is none.

    `None` is the answer for every unit without one, which is the answer for the
    overwhelming majority — this is a scan over the module's own functions, not
    a per-function flag threaded through two emitters.

    THE ALTERNATIVE WAS THE WORST FAILURE ON THIS PATH, and it is measured
    rather than argued. Both emitters lowered a `yield` to its value evaluated
    in place and dropped it (`formal/arm64_codegen.py` and
    `formal/x86_64_codegen.py`, "Generator lowered as a plain function: yield e
    leaves e in X0 / RAX"), so a generator function became an ordinary function
    whose body runs to completion at the CALL and returns whatever its last
    statement computed:

        def gen():                     CPython            this path
            yield 1                     <generator>        runs the body
            return 5                    object             returns 5
        printf("%d", gen())             TypeError-ish      "5"

    and iterating one read the returned word as a container header:

        for v in gen():                1, then a          SIGSEGV
            ...                         StopIteration      (measured, both
                                                            backends)

    A wrong-but-exit-0 artifact is what CLAUDE.md calls the failure every other
    check is structurally blind to, and this one faulted instead: two of three
    shapes below died on SIGSEGV with empty stdout and no diagnostic on either
    stream, and the third printed a number CPython cannot print.

    So the refusal names the construct, says what CPython does, says what this
    path would have done instead, and names a spelling that works — because a
    reader told only "not supported" has no next edit. A generator EXPRESSION is
    that spelling and it really does lower here, so the sentence offers it; the
    list-and-append rewrite is the other, for when the laziness is the point.
    """
    gens = yield_bearing_functions(functions)
    if not gens:
        return None
    names = ", ".join(f"`{g.name}`" for g in gens[:4])
    if len(gens) > 4:
        names += f" and {len(gens) - 4} more"
    where = ""
    line = getattr(gens[0], "line", 0) or 0
    if line:
        where = f"line {line}: "
    head = names if len(gens) > 1 else f"`{gens[0].name}`"
    return (
        f"{where}{head} {'are' if len(gens) > 1 else 'is'} a GENERATOR FUNCTION "
        f"— a `def` whose body holds a `yield`. CPython makes calling it produce "
        f"a generator object and runs NONE of the body until something iterates "
        f"that object, one value per `next()`. This path has no value to hold a "
        f"generator and no way to resume a body part-way through, so a `yield` "
        f"lowers to its value evaluated in place and discarded: calling "
        f"`{gens[0].name}(…)` runs the whole body at once and returns whatever "
        f"its last statement computed, and a `for x in {gens[0].name}(…)` then "
        f"reads that word as a container header — measured, the program died on "
        f"SIGSEGV on both backends. Build the values into a list instead "
        f"(`xs = []` and `xs.append(…)` in a loop, then iterate `xs`), or use a "
        f"generator EXPRESSION — `(x * 2 for x in xs)` — which is a different "
        f"construct, is not a `def`, and does lower here.")


def folded_literal_node(folded, template):
    """An AST literal node carrying `folded`, keeping the ORIGINAL's spelling.

    Same line/col as the value it replaces, so a diagnostic raised at a read
    site after the substitution still points at the read, not at the
    module-level line the value came from.

    Public because TWO places build a literal from a folded value and they must
    build the SAME literal: this module, for a module-level constant, and
    `formal/build.py:_fold_target_queries`, for a target query rewritten in a
    function body. A `BoolLiteral` in one and an `IntLiteral` of 0/1 in the
    other would be two answers to one question, and the difference is invisible
    until a `comptime if` takes the wrong branch."""
    line = getattr(template, "line", 0) or 0
    col = getattr(template, "col", 0) or 0
    if isinstance(folded, str):
        return F.StringLiteral(value=folded, line=line, col=col, is_bytes=False)
    if isinstance(folded, bool):
        # A BoolLiteral, not an IntLiteral of 0/1: a `comptime if` over this
        # binding must take the branch the source wrote, and only a
        # `BoolLiteral` is what `eval_const_bool` reads as True/False rather
        # than as a number. The literal folder returns 1/0 for a `BoolLiteral`
        # and so never reaches here, so this arm is the target-query folder's
        # alone.
        return F.BoolLiteral(value=folded, line=line, col=col)
    return F.IntLiteral(value=folded, line=line, col=col, raw="")


def import_bindings(stmt) -> list:
    """`[(local name, module as spelled, name defined there)]` for one import.

    THE reader of what an import binds in this file, and the three pieces are
    all of them load-bearing somewhere:

      * the LOCAL name, which is what every read and every call site spells —
        `from m import f as g` binds `g`, and a compiler that resolves `g` by
        itself produces a BL against a symbol nothing defines;
      * the MODULE AS SPELLED, because that is the key the linked library's
        manifest is filed under. `model.dylib_export_module` falls back to
        `abi_module_name(spelling)`, so `os.path`, `._syscalls` and
        `.._syscalls` each reach the one library that was built for them —
        including the relative spellings, whose manifests are keyed by the dot
        flattened (`__syscalls`);
      * the DEFINING name, which is only ever different from the local one when
        there is an `as`, and which is the name the export table is keyed by.

    A module binding (`import m`, `import m as n`) has no function to define,
    so its "defined name" is the module name itself: `n.f` is spelled
    `n.f` and reaches `f` of the module, which is `dylib_export_lookup`'s
    question and not this one's. `import a.b` binds `a`, which is why the
    bound name is the FIRST dotted component.

    One STATEMENT, and a list. `formal/imports.py`'s `imported_bindings` is the
    per-FILE table built by folding this over a module's top level, and the two
    are named apart because a reader inside that one calls this one and the
    return shapes are a list of triples and a dict of pairs.
    """
    kind = type(stmt).__name__
    if kind == "ImportStmt":
        mod = getattr(stmt, "module", None) or getattr(stmt, "name", None)
        out = []
        for part in str(mod or "").split(","):
            part = part.strip()
            if not part:
                continue
            out.append((part.split(".")[0], part, part))
            # `import a.b` binds `a`, and `a.b` is a module the dylib resolver
            # owns; the alias `as` form binds the alias. The parser records the
            # `as` name in `alias` (there is no `asname`), and it is None when
            # the import has no `as`, so the guard keeps the base binding alone.
            alias = getattr(stmt, "alias", None)
            if alias:
                out.append((alias, part, part))
        return out
    if kind == "FromImportStmt":
        mod = getattr(stmt, "module", None) or getattr(stmt, "name", None)
        out = []
        for pair in (getattr(stmt, "names", None) or []):
            if isinstance(pair, (tuple, list)):
                orig = pair[0]
                alias = pair[1] if len(pair) > 1 else None
            else:
                orig, alias = pair, None
            if not isinstance(orig, str):
                continue
            out.append((alias or orig, str(mod), orig))
        return out
    return []


def _imported_names(stmt) -> list:
    """`[(bound name, module, name defined there)]` for one module-level import.

    The third element is `import_bindings`' own DEFINING name, kept rather than
    dropped: it is the key the linked library's export table uses, so a
    diagnostic that asks whether the module publishes this name has to ask it
    about that one and not about the local spelling. `GlobalSymbol.defining`
    says why that matters.
    """
    return list(import_bindings(stmt))


def imported_module_bindings(stmts) -> dict:
    """`{name this unit binds: module it came from}` over `stmts`' imports.

    THE reader of "which module does a bare call in this unit reach", asked by
    `RaiseGraph` so that `f(…)` in a unit which wrote `from m import f` is a call
    into a KNOWN module rather than a free name — the bare half of what makes an
    imported callee resolvable, and the half that costs nothing because it is a
    fact about this unit's own statements. The dotted half (`m.f(…)`) needs no
    binding at all: the qualifier is in the AST.

    **A name bound twice keeps its FIRST module**, matching `dylib_syms`'s
    `setdefault` precedence, so the call graph and the emitted call resolve
    through the same choice. A name bound twice from DIFFERENT modules is a
    shadowing the language forbids anyway, and answering either one is not an
    improvement over answering the same one the linker will.
    """
    out: dict = {}
    for stmt in (stmts or ()):
        # Three, not two: `_imported_names` keeps the DEFINING name beside the
        # local one and this table is keyed by the LOCAL spelling, so the third
        # is not wanted here. It was unpacked as two, which is a `ValueError` on
        # every module-level import — measured as seven rows of
        # `test_formal_unicode.py` red with `too many values to unpack`, and
        # invisible in every suite whose programs import nothing.
        for _bound, _module, _defining in _imported_names(stmt):
            out.setdefault(_bound, _module)
    return out


# The dunders and module attributes a bare read may legitimately name. Small on
# purpose: this list exists so that the X19 fall-through can be DELETED, and
# every entry on it is a place where the fall-through survives as an accepted
# answer. A name belongs here only because something ELSE on the path already
# gives it a value — a backend special case, or a Python-level value that is
# the same in every program. `None`/`True`/`False` are deliberately NOT here:
# both backends already materialize them before `_load_var` is reached, so
# listing them would be a second place that decides the same thing.
_UNRESOLVED_NAME_ALLOWED = frozenset({
    # Python's singletons. BOTH backends materialise them in `_emit_expr`
    # before `_load_var` is reached (`arm64_codegen.py:2073`,
    # `x86_64_codegen.py:3183`), so they are placed with no local — and they
    # are on the list rather than handled here because a diagnostic that
    # re-derives their value would be a second answer to a question both
    # backends have already answered. `True`/`False` normally parse as
    # `BoolLiteral`; they are named because `is`/`is not` and a `comptime`
    # fold can both produce a bare `IdentExpr` for them.
    "None", "True", "False",
    # Module attributes, which are strings by the language and identical in
    # every program this path can compile.
    "__name__", "__file__", "__doc__", "__debug__", "__package__",
    "__spec__", "__loader__", "__builtins__", "__path__", "__all__",
    "__version__", "__author__", "__license__",
})


# The decorators that select a LOWERING MODE or a CALLING CONVENTION rather
# than wrapping a function, and so are not applied by any executor: there is no
# user-level function of that name to call, and dropping one is not a wrong
# answer. `@inline`/`@always_inline`/`@unroll` are inlining hints, `@staticmethod`
# /`@classmethod`/`@property` select how a method binds its receiver, `@comptime`
# and the trait names (`Copyable`, `Movable`, `Hashable`, `Sized`, `AnyType`,
# `Boolable`, `Stringable`, `Intable`, `KeyElement`, `Writable`, `Comparable`,
# `Hashable`, `EqualityComparable`, `Absable`, `Powable`, `Rounded`) declare
# conformance, and `@export`/`@parameter`/`@fieldwise_init`/`@debug_assert` are
# front-end spellings of things the Mojo parser itself handles.
#
# ONE list for two consumers rather than two lists, which is the whole reason it
# is here: `myinterpreter.py::_COMPILE_TIME_DECORATORS` is the interpreter's
# copy (it uses the set to DECIDE not to apply), and the formal path needs it to
# decide not to REFUSE. Two lists that answer the same question \u2014 "is this
# decorator a wrapper or a hint?" \u2014 is how a name ends up applied on one path
# and refused on the other, which is a construct whose behaviour depends on which
# front end compiled it.
#
# Measured for its size, because it is what makes
# `unapplied_decorator_refusal` SAFE rather than a sweep regression: of the 610
# stdlib modules in this repository's own stdlib, 202 carry a decorated `def`,
# and `@inline`+`@always_inline` alone are 2269 of the 2367 decorator spellings
# in them. A refusal asked of every decorated def would take 202 modules whose
# only use of a decorator is a hint this backend has no use for.
COMPILE_TIME_DECORATOR_NAMES = frozenset({
    "always_inline", "inline", "unroll",
    "staticmethod", "classmethod", "property",
    "comptime", "export", "parameter", "fieldwise_init",
    "debug_assert", "noncapturing", "no_inline",
    # Trait conformance and the abstract base capabilities.
    "Copyable", "Movable", "ImplicitlyCopyable", "ExplicitlyCopyable",
    "AnyType", "Defaultable", "Boolable", "Sized", "Stringable", "Intable",
    "Hashable", "Comparable", "EqualityComparable", "KeyElement",
    "CollectionElement", "Indexer", "Absable", "Powable", "Rounded",
    "Writable", "Destructible", "Key",
    # The compiler's own spelling for "this attribute is not materializable".
    "__allow_legacy_any_origin_fields",
    "__allow_legacy_custom_self_type",
    "__unsafe_nested_origins_read_only",
})


def nonlocal_write_refusal(functions) -> str:
    """Why a `nonlocal` that ASSIGNS is refused, or None when there is none.

    Both emitters reach the statement as `unsupported statement NonlocalStmt on
    the formal <arch> path`, which names the AST node and nothing else — and the
    only thing that differs between the two is which machine refused. So the
    construct is named here, once, and asked from the shared pipeline.

    Only a `nonlocal` that WRITES is refused. A `nonlocal` that merely reads
    resolves to the by-value capture parameter `_flatten_closures` prepended,
    which is the right answer for a read \u2014 nothing can observe that the copy
    differs, because nothing else reads the cell. A WRITE is different in the
    way that matters: the enclosing frame holds its own copy of the name, the
    lifted function holds the parameter, and an assignment through `nonlocal`
    would change only the second. So the program would build, run, and answer the
    enclosing frame's old value: the wrong number, with exit 0. That is the
    failure class this whole file's refusals exist to prevent.

    A write is decided by asking whether the declaration's names are STORED in
    the function that declares them, **at or AFTER the declaration**, not by
    whether the enclosing frame has an assignment: `nonlocal c` followed by
    `c = c + 1` inside the nested function is the case, and a `nonlocal` with no
    assignment after it is the read-only spelling that must keep building.

    **The "after the declaration" half is what makes the read-only case
    answerable, and it is the same fact the branch that added the emitters'
    `NonlocalStmt` arm wrote as "ask each frame about its own writes".** By the
    time this runs, `_extract_functions` has already lifted the nested `def`'s
    body into its caller, so the frame reads as one statement list in which the
    ENCLOSING function's own initializers come FIRST and the declaration
    follows them. Those initializers are not writes through the `nonlocal` — they
    are the cell's first value, and no later reader of the lifted copy can see
    them change. Measured on both architectures: `outer` writes `c` twice and
    `get` only READS it through `nonlocal`, and counting the enclosing frame's
    writes refused that program where CPython answers 8.

    **The reader is `callee_is_a_bound_value`, and it was `_names_bound_in` until
    2026-10-05 — which does not exist in this file and never did.**
    `_names_bound_in` is `formal/build.py`'s, and a `nonlocal` that WRITES
    reached this line and raised `NameError: name '_names_bound_in' is not
    defined`, so the whole refusal was unreachable and the construct left the
    build as a Python traceback through `fire.py` rather than as a diagnostic.
    Measured on both architectures:

        def main(n: Int) -> Int:
            def bump():
                nonlocal x
                x = x + 1
                return x
            var x = 0
            bump()
            print(x)
            return 0

        build: name '_names_bound_in' is not defined
        Traceback (most recent call last):
          File "fire.py", line 413, in _formal_executable
          …
          File "formal/model.py", line 41587, in nonlocal_write_refusal
            stored = _names_bound_in(fn) | {
        NameError: name '_names_bound_in' is not defined

    `callee_is_a_bound_value` is the reader THIS FILE already has for "is this
    name a local of this frame", and its own docstring is the argument for
    using it rather than adding a walk: "asking a second walk 'does this body
    bind this name' would be a second answer to a question `_collect_var_names`
    has already answered for the register file, and the two would disagree on
    exactly the shapes that disagree". What is asked here is the narrower
    question the sentence above is about — is the name STORED — and it is
    `assignment_target_names` over `iter_statement_nodes(..., enter_nested_defs=
    False)`, which is the reader `formal/model.py` already has for one
    assignment's targets and the walk that reaches them. **The frame boundary is
    what makes the read-only case answerable at all**, and it is why the two
    programs below come out differently:

        def main():                    def main():
            var c = 5                      var x = 0
            def read():                   def bump():
                nonlocal c                     nonlocal x
                return c                        x = x + 1
            print(read())                     return x
            return 0                     bump(); print(x)
                                        return 0

    The first has no store of `c` in the frame that declares the `nonlocal` and
    must keep building (CPython prints 5); the second has one and is refused.
    A reader that asked the ENCLOSING function — which is what `iter_nodes` does,
    because it descends into a nested `def`'s body — cannot tell them apart: both
    names are locals of `main`. Nor can one that counts the WHOLE flattened
    frame, which is what the `_extract_functions` lifting above makes the only
    frame there is: the third program, `outer` writing `c` twice and `get`
    reading it through `nonlocal`, is the same shape as the first with the
    enclosing frame's initializers in front.
    """
    for fn in (functions or []):
        frame = list(iter_statement_nodes(getattr(fn, "body", None) or [],
                                         enter_nested_defs=False))
        if not any(type(node).__name__ == "NonlocalStmt" for node in frame):
            continue
        for i, node in enumerate(frame):
            if type(node).__name__ != "NonlocalStmt":
                continue
            names = list(getattr(node, "names", None) or ())
            if not names:
                continue
            # `frame[i:]` and not `frame`: see the docstring's "at or AFTER the
            # declaration". A store before the declaration belongs to the frame
            # the nested `def` was lifted INTO, and it is not a write through
            # the cell.
            stored = {name for later in frame[i:]
                      for name in assignment_target_names(later)}
            written = [n for n in names if n in stored]
            if not written:
                continue
            where = ""
            line = getattr(node, "line", 0) or 0
            if line:
                where = f"line {line}: "
            spelled = ", ".join(f"`{n}`" for n in written)
            return (
                f"{where}this `nonlocal` writes {spelled}, and a captured name "
                f"has no shared cell for a write to reach: this path captures by "
                f"VALUE \u2014 `formal/build.py`'s `_flatten_closures` prepends each "
                f"captured name to the lifted function as an ordinary leading "
                f"PARAMETER, so `{fn.name}` keeps its own copy and the nested "
                f"function a second one. Assigning through `nonlocal` would change "
                f"only the second, and the program would build, run and answer "
                f"{fn.name}'s old value, which is a wrong answer with exit 0 "
                f"rather than an error. A `nonlocal` that only READS is not "
                f"refused \u2014 the read resolves to the parameter, which is what it "
                f"is for \u2014 so the working spellings are to return the value "
                f"(`return c`) and to pass it back as an argument, or to make the "
                f"state a value the caller owns: build a list, append to it, and "
                f"return it")
    return None


def unapplied_decorator_refusal(functions) -> str:
    """Why a `@decorator` on a `def` of this unit is refused, or None.

    The narrowest form of the question that is still sound, and the measurement
    that fixes its boundary is in `formal/build.py` at the call site: both
    emitters ignore `FunctionDef.decorators` entirely, so a decoration is never
    applied and `g` is emitted as the UNDECORATED body. Measured, on both
    backends, before this check:

        def other(x): return x + 100
        def deco(f):
            print("deco ran")
            return other
        @deco
        def g(x): return x * 2
        print(g(3))

    printed `6` and never printed `deco ran`, where CPython prints `103` and
    prints it. The decorator's own `print` is a statement with an observable
    effect that is silently absent, which is the same class as
    `refuse_dropped_handler_arm` and the one CLAUDE.md calls the failure every
    other check is structurally blind to.

    **TWO exclusions, and both are measurements rather than taste.**

    `COMPILE_TIME_DECORATOR_NAMES` \u2014 `@inline`, `@always_inline`,
    `@staticmethod`, `@classmethod`, `@comptime`, `@unroll`, the trait
    conformance names. These select a lowering mode or a calling convention and
    there is no user-level function to call, so dropping them is not a wrong
    answer. They are 2137 of the 2268 decorator spellings in this repository's
    own 610 stdlib modules, which is why the check cannot be "refuse every
    decorated def": measured, that would take 202 modules whose only use of a
    decorator is a hint this backend does not need.

    A decorator that is NOT a `def` of this unit. `@doc_hidden` imported from a
    module is the common spelling and its body is not in this image, so nothing
    here can say whether dropping it loses an effect \u2014 the honest report for
    that case is this same message with the narrower claim, and refusing it would
    be refusing on a guess. What IS decidable, and is what this asks, is the
    case where the decorated function's replacement is IN the image: a decorator
    defined here has a body the image contains and nothing calls.

    So the needle is a decorator name that is a `def` of this unit. Measured
    over this repository's own 610 stdlib modules, the population is ZERO: no
    module defines a decorator and uses it (`std/documentation/documentation.mojo`
    matched a line-by-line scan and does not \u2014 its `@doc_hidden` is inside the
    `doc_hidden` function's own docstring, in a markdown fence, and is not a
    decorator at all). So this refusal costs the formal sweep no file here, and
    what it removes is a class of WRONG builds rather than a class of builds.
    """
    defined = {getattr(f, "name", None) for f in (functions or [])}
    for fn in (functions or []):
        for deco in (getattr(fn, "decorators", None) or []):
            name = _decorator_name(deco)
            if not name or name in COMPILE_TIME_DECORATOR_NAMES:
                continue
            if name not in defined:
                # Not a function of this unit: its body is not in this image, so
                # whether dropping it loses an effect is not decidable here.
                continue
            if _decorator_is_identity(functions, name):
                # `return f`, provably and by the narrowest test that is still a
                # proof: the whole body is one `return` of its own first
                # parameter. Dropping that changes nothing \u2014 the image is the
                # same image \u2014 so refusing it would refuse a program whose
                # answers are already right, and the rows that pin that are the
                # `a_decorator_that_returns_its_argument` and
                # `two_decorators_that_both_return_their_argument` cases in
                # `test_formal_closures.py`.
                continue
            return (
                f"`@{name}` on `{fn.name}` is a decorator this path does not "
                f"APPLY, and `{name}` is defined in this unit \u2014 its body is in "
                f"the image and nothing calls it. CPython runs it and rebinds "
                f"`{fn.name}` to whatever it returns, bottom-up, so the decorated "
                f"name reaches the WRAPPING function; here the decorated name is "
                f"emitted as the original body, so the program's answer is the "
                f"UNDECORATED one and every effect in `{name}` is silently "
                f"absent \u2014 a `print` in a decorator never runs. That is a "
                f"wrong answer with exit 0, not an error, which is why it is "
                f"refused rather than run. Applying it is `{fn.name} = {name}"
                f"({fn.name})` after the definition, which needs a module-level "
                f"name bound to a value, and on this path a name resolves to a "
                f"symbol rather than to storage \u2014 so a decoration that CHANGES "
                f"the function has no representation here. A decorator that "
                f"returns its argument unchanged (`return f`) is what still "
                f"builds, because the image it produces is the image without the "
                f"decoration. To wrap the body, write the wrapper's effect into "
                f"`{fn.name}` itself")
    return None


def _decorator_is_identity(functions, name: str) -> bool:
    """True when `name` is a `def` whose whole body is `return <its parameter>`.

    The one shape of decorator whose ABSENCE is provably not a wrong answer: the
    image is the same image with or without it, because the value it would
    produce is the value that is already there. Deliberately the narrowest test
    that is still a proof rather than a heuristic \u2014 exactly one `ReturnStmt`,
    whose value is a bare read of the FIRST parameter. A decorator with a
    statement before the return is NOT identity even if it ends in `return f`,
    because the statement is an effect that would be dropped, and a decorator
    returning a CALL (`return wrap(f)`) is not identity because the value it
    produces is not the parameter.
    """
    for f in (functions or []):
        if getattr(f, "name", None) != name:
            continue
        body = [s for s in (getattr(f, "body", None) or [])
                if type(s).__name__ != "Pass"]
        if len(body) != 1 or type(body[0]).__name__ != "ReturnStmt":
            return False
        params = [p[0] if isinstance(p, (tuple, list)) and p else p
                  for p in (getattr(f, "params", None) or ())]
        value = getattr(body[0], "value", None)
        return (bool(params) and isinstance(value, F.IdentExpr)
                and value.name == params[0])
    return False


def _decorator_name(deco) -> str:
    """The bare name a `@decorator` names, from all three spellings.

    A bare `@deco` arrives as a string; `@deco(x)` arrives as a `CallExpr`
    (the parser stopped discarding the argument list in 2026-09-27) and
    contributes only its callee, which is enough for a name comparison; an
    `@IdentExpr` arrives for the dataclass-transform rewrites. One reader
    because a decorator refused under one spelling and lowered under another
    would be a construct that works or does not depending on punctuation.
    """
    if isinstance(deco, str):
        return deco
    if isinstance(deco, F.IdentExpr):
        return deco.name
    if isinstance(deco, F.CallExpr) and isinstance(deco.func, F.IdentExpr):
        return deco.func.name
    return ""


def free_names_in_lambda(lam) -> set:
    """Every bare name `lam`'s own body reads, its parameters included.

    ONE walk, because the question it answers is asked from two places that
    must not disagree: `formal/build.py`'s `_lift_lambdas` subtracts the
    lambda's own parameters to decide whether the lambda CAPTURES its enclosing
    scope, and the compiled path's `mojo/middle/lambdareduce.py::free_names`
    needs the same set for the same lambda. Two readers of one tree is two
    chances for one of them to see a name the other does not, and a name missed
    here is a capture that lifts into a body with no home for it \u2014 the
    refusal that costs is the emitter's "'m' has no home", which is a sentence
    about the register allocator where the reader wrote a closure.

    Deliberately a WHOLE-TREE walk and not the enclosing scope's view: the
    reader is handed the lambda alone, so it answers "which names does this
    body read" and the caller decides which of those are free. The alternative
    \u2014 threading the enclosing function's locals into every call \u2014 is what
    `lambdareduce.free_names` does for the compiled path and it cannot be
    copied here, because the formal lift runs per-lambda and has no view of the
    body the lambda appears in.

    A read is an `IdentExpr` anywhere in the subtree, INCLUDING a nested
    lambda's body, because a nested lambda is not a scope this path can lift
    separately: `lambdareduce._referenced_names` descends for the same reason.
    A callee NAME is still a read (`f(x)` reads `f`), which is why the caller
    has to subtract the parameters itself rather than trust this to exclude
    them.
    """
    out: set = set()

    def rec(node):
        if node is None or isinstance(node, (str, int, float, bool, bytes)):
            return
        if isinstance(node, F.IdentExpr):
            out.add(node.name)
            return
        if isinstance(node, (list, tuple)):
            for x in node:
                rec(x)
            return
        for name in getattr(node, "__dataclass_fields__", {}):
            rec(getattr(node, name))

    rec(getattr(lam, "body", None))
    for _pname, pdefault in (getattr(lam, "params", None) or []):
        rec(pdefault)
    return out


def capturing_lambda_refusal(free, base: str) -> str:
    """Why a lambda that reads its enclosing scope is refused, in its own terms.

    `free` is `free_names_in_lambda`'s answer minus the lambda's own parameters:
    the names the body reads that the enclosing function, not the lambda, holds.
    `base` is the name the lambda would have been lifted under, which is the
    caller's local (`f` for `f = lambda …`, the enclosing function's name for one
    written at a call site) and is quoted so a reader can find the line.

    The lift is to a module-level function of the lambda's OWN declared
    parameters, so a free name has nowhere to go in the lifted body. That is not
    a gap in the register allocator and this path does not have the machinery to
    close it for a lambda: a nested `def` gets an environment \u2014 the by-value
    capture parameters `_flatten_closures` prepends, from `discover_closures`'s
    closure map \u2014 and `discover_closures` does not record lambdas, so a lambda
    never participates in it. The compiled path answers the common shape of this
    by BETA-REDUCTION instead (`mojo/middle/lambdareduce.py`: a lambda bound to
    a local and called through that name in the same function is inlined at the
    call site, which is safe only when the local is assigned the lambda exactly
    once, never rebound, and every other mention of its name is a call's callee).
    Handing the lambda to another function is not that shape \u2014 there is no local
    to reduce through \u2014 so the remedy named here is the one that holds for every
    spelling: pass the value as an ARGUMENT and make it a parameter.
    """
    names = ", ".join(f"`{n}`" for n in sorted(free))
    return (
        f"the lambda assigned to {base!r} reads {names} from the scope it is "
        f"written in, and a lambda has no environment to be given them: this "
        f"path lifts a lambda to a module-level function of its OWN declared "
        f"parameters, so a name that is not one of those has nowhere to live in "
        f"the lifted body. A nested `def` is not affected \u2014 it is captured by "
        f"VALUE (`formal/build.py`'s `_flatten_closures` prepends the captured "
        f"names as leading parameters), which is why a closure written as `def "
        f"inner(): return m` builds and this does not. Pass the value instead: "
        f"`lambda v: v * m` becomes `lambda v, m: v * m` and the caller passes "
        f"`m` as a second argument")


def name_resolves_without_a_local(name: str) -> bool:
    """True when a bare read of `name` has a value with no local to hold it.

    The complete list, and it is short. Anything not on it and not a parameter,
    not a local of the reading function and not a folded module constant is a
    name the build cannot place, and `_load_var` refuses it — which is the
    whole point: the arm64 X19 fall-through and the x86-64 zero fall-through
    were the two architectures' answers to a question neither of them had."""
    return name in _UNRESOLVED_NAME_ALLOWED


def is_type_name(name: str) -> bool:
    """True when `name` spells a TYPE on this path — not a value.

    The union of the four tables that already know type names, and the union is
    the point: each answers a different question, so a name in only one of them
    is still a type.

      * `POINTEE_WIDTHS` — types with a known width, and the only table
        `NoneType` is in;
      * `INT_TYPE_CTORS` / `IDENTITY_TYPE_CTORS` — what a bare call `T(x)`
        means, read through `type_constructor_kind`;
      * `UNREPRESENTABLE_TYPE_CTORS` — real types this path cannot build a
        value of (`DType`, `Optional`, `SIMD`, …), which is a statement about
        the VALUE and not about whether the name is a type;
      * `Self`, which is a type and appears in no table.

    A struct this unit compiles is deliberately NOT here: `check_module_symbols`
    already places those names, and its own docstring says why — "a struct is
    not a value and has no register" — which is the same fact stated for the
    case that reaches it.

    Read this only to decide which WORD a refusal uses. It must never be used to
    answer "can this name be read", because the answer to that is always no, and
    `name_resolves_without_a_local` is the list of the ones that can."""
    if name == "Self":
        return True
    if name in POINTEE_WIDTHS or name in UNREPRESENTABLE_TYPE_CTORS:
        return True
    return type_constructor_kind(name) is not None


def type_as_value_refusal(name: str, fn_name: str) -> str:
    """A TYPE read where a value is required.

    `unresolved_name_refusal` enumerates the four places a NAME can live on this
    path — a register, a spill slot, a receiver field's frame, a folded
    module-level constant. That enumeration is right for a value and it is
    wrong here in a way worth naming: a type is in none of the four because a
    type is not a value and never was. The reader is sent to the register
    allocator for a fact about the language.

    The measured cost of that: `check_module_symbols` over the 664 stdlib
    `.mojo` files reported 93 files as "'<name>' has no home", and 52 of those
    names are types — `NoneType`, `DType`, `Int`, `Self`, `String`, `Byte`,
    `UInt8`, `UInt64`. The other 41 are unchanged and correct: they name values
    (`debug_assert`, `rebind`, `__is_run_in_comptime_interpreter`, …) that
    really are read where there is no storage, and for those the storage
    enumeration is the right story. `std/sys/_assembly.mojo:94`'s
    `comptime if result_type == NoneType:` is one of the 52.

    A COMPARISON of two types is the common shape, and it is the one this
    message is really about: `t == NoneType` with `t` a `comptime` type
    parameter compares two types, which needs a type to BE a value — a tag per
    type, interned, and the SAME on both sides of a dylib boundary, so it
    cannot be a per-unit small integer. That is reflection-table work and it
    belongs to whoever owns the type table; this message says so rather than
    implying the reader could fix it by naming a variable differently.

    What a caller CAN do is branch on something the one-word model can
    distinguish, and the message says that too, because a refusal with no
    repair is the other half of a useless diagnostic.
    """
    return type_as_value_fact(name, fn_name)


def type_as_value_fact(name: str, fn_name: str = "") -> str:
    """The type-is-not-a-value SENTENCE, on its own.

    Split from `type_as_value_refusal` because a name can be a type AND have a
    more specific story — a module symbol imported from another module, whose
    message `tools/formal_sweep.py` parses — and in that case the two facts are
    both true and both worth saying. `fn_name` is optional here because this
    half is also appended to a message that already carries it."""
    who = f"{fn_name}: " if fn_name else ""
    return (f"{who}{name!r} is a TYPE, and a type is not a value on this path: "
            f"a value here is one 64-bit word, and a type is not one thing a "
            f"word can hold. So there is no register, spill slot, frame field "
            f"or folded constant this could live in — the question those four "
            f"places answer is the wrong question for a type. Comparing a "
            f"`comptime` type parameter against a type name (`t == {name}`), "
            f"testing one with `is`, or passing one as an argument all need "
            f"types to be values: an interned tag per type, identical on both "
            f"sides of a dylib boundary, which is reflection-table work this "
            f"path does not have. Branch on something the word model can tell "
            f"apart — a flag or an extra parameter the caller passes, a "
            f"separate function per case, or a property of the value itself "
            f"rather than of its type.")


def comptime_fold_refusal(name: str) -> str:
    """The refusal for a `comptime NAME = …` whose value is not a constant.

    ARCH-FREE and shared, which is the whole point: arm64 carried the text
    inline and x86-64 had no version of it at all, so one construct came back
    with two different messages from the two architectures that are supposed to
    be one language implementation. x86-64's was worse than merely different —
    it refused the *statement shape* one layer up, so a program whose only
    problem was a `len()` over a runtime parameter was told it used a statement
    this path does not support, and a reader went looking for that statement.

    Saying what is actually wrong is also what makes it actionable, which the
    shape-based text was not: the initializer is not a compile-time constant,
    and the two repairs are to make it one (a literal, or an expression over
    literals and other `comptime` names) or to stop asking for it at compile
    time (an ordinary `var`, read at run time)."""
    return (
        f"comptime {name} = ... does not fold to a compile-time constant on "
        f"this path, so there is no value to materialize at the reads that "
        f"follow. A `comptime` binding is compile-time state, which is why it "
        f"cannot be a value that only exists while the function runs — an "
        f"initializer over a parameter, or over anything computed, is not "
        f"knowable here. Make the initializer a literal (or an expression of "
        f"literals and other `comptime` names), or bind it with an ordinary "
        f"`var` and read it at run time")


def export_rule_for(name: str, module: str, link_line=None,
                    source: str = None) -> tuple:
    """`(rule, declared)` for `name` as `module`'s SOURCE states it.

    The one reader of `reflect.export_exclusions` for a REFUSAL, so that a
    message about "the export rule" can name the rule that actually applied
    instead of enumerating the four candidates — and can say, for the case that
    is not an exclusion at all, that the module declares no such name.

    The source comes from either
      * `source`, a path (the `check_library_free_calls` site has it as the key
        of the `library_free` table it is walking); or
      * `link_line`, the raw manifest list a build carries, whose entries record
        the defining module's own `source` (`write_dylib_manifest`). `module` is
        matched against each entry's `module`, which is the spelled module name
        the diagnostic itself uses.

    Returns `(rule, declared)`:
      * `(EXCL_*, True)`  — the module declares `name` and the rule excluded it;
      * `(None, False)`   — the module declares no function or struct by that
        name at all (the `now` in `runtime/stdlib_wrapper.mojo`, and an alias
        spelled as its target's name);
      * `(None, True)`    — declared and NOT excluded, which cannot be why a call
        reached a refusal (see `(None, None)` in the caller);
      * `(None, None)`    — no source could be read, so nothing is claimed.
    """
    text = None
    if source:
        try:
            with open(source, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            text = None
    if text is None and link_line:
        for d in link_line:
            if (d.get("module") or "") != (module or ""):
                continue
            path = d.get("source")
            if not path:
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except OSError:
                text = None
            break
    if text is None:
        return None, None
    import reflect                                   # lazy — pulls the backend
    try:
        parsed = reflect.Parser(reflect.py_tokenize(text)).parse_module()
        excluded = reflect.export_exclusions(text, parsed)
    except Exception:                                # noqa: BLE001
        return None, None
    if name in excluded:
        return excluded[name], True
    declared = any(
        isinstance(s, (reflect.FunctionDef, reflect.StructDef))
        and getattr(s, "name", None) == name for s in parsed)
    return None, declared


#: The one-line gloss of each export rule the refusal names, keyed by
#: `reflect`'s own constant (read lazily, because `reflect` pulls the backend).
def _export_rule_why() -> dict:
    import reflect
    return {
        reflect.EXCL_PRIVATE:
            "a name with a leading `_` is private — the source saying it is not "
            "for another module",
        reflect.EXCL_GENERIC:
            "a generic template is not one symbol but one per instantiation, "
            "and each instantiation is the boundary symbol — "
            "`formal/monomorph.py` compiles one into the defining module's "
            "library when an importer asks for it, and a bare call asks for "
            "none",
        reflect.EXCL_OVERLOADED:
            "an overload has no single symbol, and one trie entry cannot be two "
            "instantiations",
        reflect.EXCL_CLIB:
            "a C library name like `exit` or `write` is provided by libSystem "
            "(right for a call, wrongly named as this module's own definition)",
    }


def _generic_inference_tail(name: str) -> str:
    """The bare-call half of `imported_callee_refusal`, shared by its generic
    branch and its unqualified fallback so the two cannot say it differently."""
    return (
        f"A generic template's instantiations ARE compiled into that module's "
        f"library when an importer asks for them (`formal/monomorph.py`), so "
        f"this call is one that asked for none — it names no type argument, or "
        f"names one that is a value rather than a type, or spells the template "
        f"as `module.{name}`. **If the call names no type argument at all, the "
        f"SOURCE is right and this path is short**: Mojo infers a template "
        f"call's type arguments, so `{name}(…)` with no bracket is correct "
        f"code — the stdlib's own `FormatStruct(writer, \"Allocation\")` is "
        f"spelled that way — and this path does not infer them yet. Its demand "
        f"pipeline reads type arguments off an explicit bracket, so a bare call "
        f"arrives here with no instantiation to bind; the inference, the 123 "
        f"measured files it is worth, and the shape of the missing piece are "
        f"in bugs/formal/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_"
        f"inferrable.md. So write the operation in this module, or call a "
        f"public function that does it — which is the same program with a "
        f"definition this image can bind. Spelling it `{name}[<a type>](…)` "
        f"will carry the instantiation, and is a workaround for this gap rather "
        f"than a correction to your code")


def imported_callee_refusal(name: str, sym, fn_name: str,
                            rule: str = None, declared=None) -> str:
    """The diagnostic for a CALL to a name the defining module does not export.

    `rule` is the ONE rule `doc/ABI.md`'s export rule applied to this name,
    computed by the caller from the DEFINING MODULE's own source
    (`formal/build.py::export_rule_for`) because that is the only place the rule
    can be stated truthfully. It is one of `reflect.EXCL_PRIVATE`/`_GENERIC`/
    `_OVERLOADED`/`_CLIB`, or `reflect.EXCL_ABSENT` when the module declares no
    name under this spelling at all — which is the fifth answer and is NOT an
    exclusion. When it is None (a caller with no link line or no readable
    source, and the module-level-store path in `formal/imports.py`) the sentence
    falls back to enumerating the four candidate rules, which is what it did
    before the rule could be read. The measured case for `EXCL_ABSENT` is
    `runtime/stdlib_wrapper.mojo`'s `from time import now`: every one of the
    four enumerated rules was false about `formal/hostmods/time.mojo`, which
    declares no `now` at all.

    Distinct from `module_global_refusal` because the two are different facts,
    and the generic one is FALSE about this one. `f[x](...)` roots at a name,
    `check_module_symbols` sees a bare `IdentExpr` that is not a local, and the
    imported case answered "a module-level name is not exported as a word —
    there is no storage for it" about what is a call: a call needs a SYMBOL, and
    the question is whether the library has one, not whether a value has a home.
    A reader sent by the old wording to look for storage finds a `_`-prefixed
    generic with no storage question at all.

    What it says instead is the reason the export set excludes the name, which
    is `reflect.collect_exports_src`'s rule and is the same rule the dylib
    build's own `no_public_api_reason` reports by: a leading `_`, a generic
    template (each instantiation is its own symbol, compiled into the defining
    module's library on demand — `formal/monomorph.py`), an overload (no one
    symbol denotes it) or a C library name. `_get_kgen_string` in
    `std/sys/_assembly.mojo` is the first two at once, and it is the terminal
    construct for nineteen swept files.

    **It names the ONE rule that applied when `rule`/`declared` are passed in**,
    and it is `export_rule_for` above that computes them from the defining
    module's own source. The fallback below (no source readable) still
    enumerates the four, but every caller that has the source passes the answer,
    so a reader of the export-gate row gets "it is a generic template" rather
    than four candidates — and the file whose name the module does not declare
    at all (`runtime/stdlib_wrapper.mojo`'s `from time import now`) gets
    `declared=False` and the sentence that says so.

    **The generic clause is no longer a claim that this path cannot do the
    thing** — it can, and it did so the moment it was asked, so saying so here
    would be false in the direction this document opens with.  What is left is
    narrower and is what the sentence now says: the call that arrives here has
    NOT been resolved to an instantiation, and the three ways that happens are
    all in `formal/monomorph.py::demands` — a BARE call names no type argument
    at all, an argument that is a VALUE rather than a type (`Pair[t]()` with
    `var t = Float64` above it) has no concrete spelling to mangle, and a
    DOTTED application `mod.G[T]()` is refused by
    `comptime.specialization_name` by design.  All three are listed with the
    exact next step in `bugs/formal/FORMAL_generic_monomorph_scope.md`, which is the
    single home for what the mechanism does not cover.

    **And the last sentence says the BARE case is CORRECT SOURCE, because it
    was telling a reader to edit working stdlib.** In Mojo a template call's type
    arguments are inferred: `FormatStruct(writer, "Allocation")` with no bracket
    is the spelling the stdlib uses, and the previous wording — "spell it as
    `name[<a type>](…)` and the library will carry the instantiation" — asked
    exactly that file to be changed for a gap in this path. That is the
    `refuse_without:` defect in its purest form: a repair that is wrong about
    correct code. So the sentence now names what is missing (the inference),
    points at the measured 123 files and the inference's shape
    (`bugs/formal/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`),
    and says the bracket is a WORKAROUND rather than the fix.
    """
    who = f"{fn_name}: " if fn_name else ""
    mod = getattr(sym, "module", None)
    # The rule that ACTUALLY applied, when the defining module's source was read
    # (`export_rule_for`) — one sentence instead of four candidates, so a reader
    # is not sent to look for an underscore, a bracket, a second definition and
    # a C name in a file that has none of them.
    if rule is not None:
        why = _export_rule_why().get(rule) or f"it is excluded as `{rule}`"
        import reflect
        if rule == reflect.EXCL_GENERIC:
            # The generic rule carries the whole explanation the fallback used to
            # carry, because it is the ONE rule whose "why" a reader acts on:
            # the bare spelling is CORRECT source and the missing piece is the
            # inference. `test_formal_monomorph.py` pins every clause of it.
            return (f"{who}`{name}` is called, and it is imported from `{mod}`, "
                    f"so the call has to bind a symbol `{mod}` exports. That "
                    f"module does not export it, and the reason is `doc/ABI.md`'s "
                    f"export rule applied to the DECLARATION: {why}. A generic "
                    f"template's instantiations ARE compiled into that module's "
                    f"library when an importer asks for them "
                    f"(`formal/monomorph.py`), so this call is one that asked "
                    f"for none — it names no type argument, or names one that is "
                    f"a value rather than a type, or spells the template as "
                    f"`module.{name}`. **If the call names no type argument at "
                    f"all, the SOURCE is right and this path is short**: Mojo "
                    f"infers a template call's type arguments, so `{name}(…)` "
                    f"with no bracket is correct code — the stdlib's own "
                    f"`FormatStruct(writer, \"Allocation\")` is spelled that way "
                    f"— and this path does not infer them yet. Its demand "
                    f"pipeline reads type arguments off an explicit bracket, so "
                    f"a bare call arrives here with no instantiation to bind; "
                    f"the inference, the 123 measured files it is worth, and the "
                    f"shape of the missing piece are in "
                    f"bugs/formal/FORMAL_a_bare_call_to_a_template_whose_type_"
                    f"arguments_are_inferrable.md. So write the operation in this "
                    f"module, or call a public function that does it — which is "
                    f"the same program with a definition this image can bind. "
                    f"Spelling it `{name}[<a type>](…)` will carry the "
                    f"instantiation, and is a workaround for this gap rather "
                    f"than a correction to your code")
        return (f"{who}`{name}` is called, and it is imported from `{mod}`, so "
                f"the call has to bind a symbol `{mod}` exports. That module "
                f"does not export it, and the reason is `doc/ABI.md`'s export "
                f"rule applied to the DECLARATION: {why}. The exclusion is "
                f"measured and settled in bugs/formal/FORMAL_known_limits.md §1.1, and "
                f"the generic case in §1.2.")
    # …and the case that is NOT an exclusion at all: the module's own source
    # declares no such name. `runtime/stdlib_wrapper.mojo`'s `from time import
    # now` is this, and the old four-candidate sentence sent the reader to look
    # for an underscore, a bracket, a second definition and a libSystem name in
    # `formal/hostmods/time.mojo`, which has none of them.
    if declared is False:
        return (f"{who}`{name}` is called, and it is imported from `{mod}`, so "
                f"the call has to bind a symbol `{mod}` exports. **`{mod}` "
                f"declares no function or struct named `{name}` at all**, so "
                f"`doc/ABI.md`'s export rule (a leading `_`, a generic template, "
                f"an overload, a C library name) is not the reason and none of "
                f"its four clauses applies. The name is coming from somewhere "
                f"other than `{mod}`'s own source — an alias or a re-export "
                f"spelled in the importer, or a misspelling — so check the "
                f"spelling and what `{mod}` actually declares before changing "
                f"the call.")
    return (f"{who}`{name}` is called, and it is imported from `{mod}`, so the "
            f"call has to bind a symbol `{mod}` exports. That module does not "
            f"export it, and the reason is `doc/ABI.md`'s export rule rather "
            f"than anything about this call: a name with a leading `_` is "
            f"private, a generic template is not one symbol but one per "
            f"instantiation (`_get_kgen_string[asm]()` is the measured case — "
            f"both at once), an overload has no single symbol, and a C library "
            f"name like `exit` or `write` is provided by libSystem. The "
            f"exclusion is measured and settled in "
            f"bugs/formal/FORMAL_known_limits.md §1.1, and the generic case in §1.2. "
            + _generic_inference_tail(name))
    if clause is not None:
        return head + (
            f"That module does not export it, and the reason is `doc/ABI.md`'s "
            f"export rule rather than anything about this call: {clause}. The "
            f"exclusion is measured and settled in "
            f"bugs/formal/FORMAL_known_limits.md §1.1.")
    return head + (
        f"That module does not export it, and the reason is `doc/ABI.md`'s "
        f"export rule rather than anything about this call: a name with a "
        f"leading `_` is private, a generic template is not one symbol but one "
        f"per instantiation (`_get_kgen_string[asm]()` is the measured case — "
        f"both at once), an overload has no single symbol, and a C library "
        f"name like `exit` or `write` is provided by libSystem. The exclusion "
        f"is measured and settled in bugs/formal/FORMAL_known_limits.md §1.1, and the "
        f"generic case in §1.2. " + _generic_inference_tail(name))


def module_attribute_refusal(spelling: str, module: str, leaf: str,
                             fn_name: str, published, variables=(),
                             containers=()) -> str:
    """The diagnostic for reading `module.leaf` as a VALUE.

    A DIFFERENT fact from `module_global_refusal`'s "imported" arm, and the
    difference is the whole of this function. That arm is raised about a BARE
    name — `from sys import argv`, then `argv` — and it says "this name's value
    is a real global with nowhere to live". It is true there, because `argv`
    genuinely is a global of `sys`.

    Here the name being refused is a MODULE (`sys`), and a module is not a
    global, not a variable, and not a value with nowhere to live: it is the
    library on the link line, and the thing being read is its ATTRIBUTE `argv`.
    Saying "there is no storage for a variable called `sys`" is a claim about a
    variable that does not exist, and it sends the reader to look for storage for
    the one name in the program that needs none — measured, this is what
    `t_argv.mojo`, `mojo.mojo`, `tools/ab_filelist.py`, `tools/audit_determinism.py`,
    `tools/ci_line.py` and `tools/detach.py` were each refused with, on both
    architectures, all six of them naming `sys`.

    So the sentence is about the ATTRIBUTE and it says what the boundary can
    publish, which is the same fact `dylib_extern_symbol` states for a dotted
    CALL: a dylib exports functions (as symbols) and module-level names the
    build FOLDED TO A LITERAL (as values, because a literal needs no storage to
    cross). `sys.argv` is neither — it is a list, and §(4) of
    `bugs/formal/FORMAL_module_state_no_storage.md` records that the command line is
    gone before the first statement runs, so there is nothing in it either.

    **`variables` is the half that keeps the sentence true.** "A list, an
    object or a stream has no representation as a word" is FALSE about a name
    like `G` in `mylib.G` where `mylib` declares `G = 5` and also writes it
    through `global` — an `Int` crosses fine, and what stops it is that its
    value is not the same in both modules. So a leaf the module publishes as a
    VARIABLE gets its own sentence, naming the reason and the repair: the
    module's own accessor is the spelling, and that one WORKS (measured both
    architectures — `mylib.setg(9)` then `mylib.get()` answers 9, where
    `mylib.G` used to answer the folded 5). A refusal whose stated reason is
    false about the name it names sends the reader after a capability the name
    does not need, which is the defect this function was written to remove.

    **`containers` is the second half of the same repair, and it exists because
    the variable arm was reached with a name it is false about.** A module-level
    `TABLE = [10,20,30]` that nothing writes has a `__DATA` slot — the blob is
    static data — and used to be published in the same list as `G`, so
    `mylib.TABLE` was refused for "that module's own functions write it through
    `global`" in a module that writes nothing at all (measured, both
    architectures). It is a CONSTANT: the build knows its value, and what does
    not cross is the ADDRESS, because `doc/ABI.md`'s export rule publishes
    functions and folded words and a blob is neither. So it gets its own
    sentence too, and the repair is an accessor that hands back an element —
    the same spelling that works for a variable, and for the same reason: the
    accessor is code, and code is what a dylib exports.

    `published` is the list of what the module DOES publish, so a reader can see
    in one line whether the name they wrote is one of the module's own or a
    capability it does not have. That is `dylib_extern_symbol`'s own device,
    reused rather than reinvented.

    **And it is what makes the LAST arm possible, which is the third instance of
    the disease this function was written to remove.** With the published set in
    hand, "`{module}` publishes no `{leaf}`" is a question this function can
    answer, and until 2026-10-04 it did not — every name that was not a
    published variable and not a published container fell into one arm that
    said "`{leaf}` is one: a list, an object or a stream". That is FALSE of most
    of what reaches it. Measured, `formal/hostmods/sys.mojo` declares NONE of
    `argv`, `stderr`, `stdout`, `path`, `modules` or `executable` — its own
    module docstring lists them as deliberately absent, and the doc's §(4)
    records why — so all six were refused with a claim about a value on the
    other side of the boundary that was not there. `sys.executable` is the
    sharpest instance: a PATH is a `char *`, which is one folded word and is
    exactly what the message two clauses earlier says crosses, and the reason
    that name is missing is a SOURCE (`_NSGetExecutablePath` is refused by name
    on this path, and the `__file__` route would put one build's `-o` into a
    content-addressed dylib's cache key) rather than a representation. So the
    arm now asks the published set first, and keeps the VARIABLE sentence for
    the names it is true of — which is the discipline this function's own
    docstring states for the two arms above it, applied to the third."""
    who = f"{fn_name}: " if fn_name else ""
    shown = ", ".join(sorted(published)[:8])
    if len(published) > 8:
        shown += ", …"
    if not shown:
        shown = ("nothing under a name a caller can bind — every name it "
                 "publishes is re-exported, and the modules it re-exports from "
                 "publish none of this one")
    if leaf in set(variables or ()):
        return (f"{who}{spelling} reads {leaf!r}, which is a module-level name "
                f"of `{module}` that `{module}`'s OWN functions write through "
                f"`global`, so its value is not known when the library was built "
                f"and cannot be recorded the way a value the build knows is. It "
                f"is a VARIABLE and not a constant even though `{module}` also "
                f"declares it at module level: a name whose one value the build "
                f"knows crosses the boundary by substitution, because there is "
                f"exactly one of it in a whole program, and this one has a second "
                f"writer — so the importer would materialize the value `{module}` "
                f"STARTED at. What `{module}` publishes: {shown} — give the "
                f"module an accessor (`def get_{leaf}(): global {leaf}; return "
                f"{leaf}`) and call that, which reads the same slot and lowers "
                f"today. `bugs/formal/FORMAL_module_state_no_storage.md` §(2) records "
                f"what it would take to publish the slot itself rather than a "
                f"function that reads it")
    if leaf in set(containers or ()):
        return (f"{who}{spelling} reads {leaf!r}, which is a module-level "
                f"CONSTANT of `{module}` — its only writer is its own "
                f"module-level statement, so there is exactly one value of it in "
                f"a whole program — whose value is laid out in `{module}`'s own "
                f"`__DATA` as a run of words. What does not cross is the "
                f"ADDRESS: a dylib publishes its functions (as symbols, so "
                f"`{module}.fn(...)` lowers) and its module-level names the "
                f"build FOLDED TO A LITERAL (as values, so `{module}.K = 1` "
                f"lowers), and a container is neither — it is a block of static "
                f"data at an address chosen when the library was linked, which "
                f"this image cannot have known. So this is a missing "
                f"capability and not a missing value, and the spelling that "
                f"works today is an accessor that hands back what you need out "
                f"of it: `def {leaf}_at(i: Int) -> Int: return "
                f"{leaf}[i]` in `{module}`, called as `{module}.{leaf}_at(0)`. "
                f"What `{module}` publishes: {shown}. "
                f"`bugs/formal/FORMAL_module_state_no_storage.md` §(2) records what "
                f"publishing the blob itself would take")
    if leaf not in set(published or ()):
        return (f"{who}{spelling} reads {leaf!r} out of the imported module "
                f"`{module}`, and a module is not a value this path can place: "
                f"there is no register, frame slot or `__DATA` word for it "
                f"because it is not one — it is the library on this link line, "
                f"and what a dylib publishes is its FUNCTIONS (as symbols, so "
                f"`{module}.fn(...)` lowers) and its module-level names the "
                f"build FOLDED TO A LITERAL (as values, so `{module}.K = 1` "
                f"lowers — there is exactly one value of a folded module-level "
                f"name in a whole program, so the importer materializes the "
                f"same one). `{module}` publishes no {leaf!r}, so there is "
                f"nothing on the other side of the boundary to read — which is "
                f"a DIFFERENT fact from \"it is there and cannot cross\", and "
                f"the two have different repairs: a name the module's own "
                f"functions write through `global` gets the sentence above, "
                f"which names an accessor that works today, and a name it "
                f"declares as a container gets the one above that, which names "
                f"an element accessor. What `{module}` publishes: {shown}. "
                f"`formal/hostmods/sys.mojo`'s own module docstring says which "
                f"of those names it deliberately does not declare and why "
                f"(`argv`, `stderr`, `stdout`, `modules`, `path`), and "
                f"`bugs/formal/FORMAL_module_state_no_storage.md` §(2) and §(4) "
                f"record what would have to be true to close the boundary for "
                f"the ones CPython has and this path does not")
    return (f"{who}{spelling} reads {leaf!r} out of the imported module "
            f"`{module}`, and a module is not a value this path can place: "
            f"there is no register, frame slot or `__DATA` word for it because "
            f"it is not one — it is the library on this link line, and what a "
            f"dylib publishes is its FUNCTIONS (as symbols, so "
            f"`{module}.fn(...)` lowers) and its module-level names the build "
            f"FOLDED TO A LITERAL (as values, so `{module}.K = 1` lowers — "
            f"there is exactly one value of a folded module-level name in a "
            f"whole program, so the importer materializes the same one). What "
            f"it cannot publish is a VARIABLE, and `{leaf}` is one: a list, an "
            f"object or a stream has no representation as a word on the other "
            f"side of the boundary, because every value a formal program can "
            f"name lives in a function's own stack scratch, which is reclaimed "
            f"when the function returns. What `{module}` publishes: {shown}. "
            f"`bugs/formal/FORMAL_module_state_no_storage.md` records the design and "
            f"what would have to be true to close it, and §(2) is this shape")


def module_global_refusal(name: str, sym, fn_name: str, variables=None,
                          containers=None) -> str:
    """The one-line diagnostic for a module-level name this path cannot read.

    Says which of the four kinds it is and what would have to be true, because
    the four have four different repairs and the previous answer — a register —
    named none of them."""
    who = f"{fn_name}: " if fn_name else ""
    if sym is None:
        return (f"{who}{name!r} is not a local of this function, a parameter "
                f"of it, or a module-level name of this module. This path "
                f"places a name in exactly those three ways, and a name in "
                f"none of them has no address to read: the backend used to "
                f"fall back to a register, which is how the same program "
                f"returned 10 on arm64 and 0 on x86-64 where the source says "
                f"5. Bind it in this function, pass it in, or declare it at "
                f"module level with a value the build can see")
    site = getattr(sym, "site", "assigned")
    if site == "imported":
        mod = getattr(sym, "module", None)
        # The module is spelled in BACKTICKS, not in single quotes, and that is
        # not a style preference. `tools/formal_sweep.py` reads a quoted
        # identifier, asks whether the swept file imports it, and files the
        # verdict as `not-answerable/unresolved-import` when it does — so a
        # single-quoted module name here reclassified thirteen stdlib files
        # from `codegen/dependency` (an accurate "the backend refused a
        # construct in a module this file imports") into "imports a module
        # that is neither host nor in this backend's module set", which is
        # false: the module resolves, and a construct inside it does not
        # lower. The sweep's own comment says the house style — "a codegen
        # diagnostic quotes nothing of this shape (`self.<field>` is in
        # backticks)" — and this is the case that makes it load-bearing.
        #
        # What a dylib DOES publish, because the sentence has to be true as
        # well as discouraging and the previous one named a repair that does
        # not lower: its FUNCTIONS, as symbols, and its module-level names the
        # build FOLDED TO A LITERAL, as values — a literal needs no storage to
        # cross the boundary (there is exactly one value of a folded
        # module-level name in a whole program), so the importer materializes
        # the same one in its own image. A name that reached this refusal is
        # therefore not one of those: it is a real variable, a list, an object,
        # or a function used as a value. Saying so is what makes the remaining
        # sentence a repair rather than a deflection.
        #
        # `variables` and `containers` are what keep that last sentence from
        # being false about a name it names, and the arm had neither before:
        # `from lookups import TABLE`, where `lookups` declares
        # `TABLE = [10,20,30]` and writes nothing, was refused as "this name's
        # value is a real global with nowhere to live" (measured, both
        # architectures). It has a home — the defining library lays the blob out
        # in its `__DATA` — and it is a CONSTANT, so the two facts worth saying
        # are "nothing writes it" and "the ADDRESS is what does not cross". The
        # dotted spelling of the same read has said both since
        # `module_attribute_refusal` grew its arms, and a refusal must not be
        # true for `mod.TABLE` and false for `from mod import TABLE`.
        if name in set(variables or ()):
            return (f"{who}{name!r} is imported from `{mod}`, and it is a name "
                    f"`{mod}`'s OWN functions write through `global`, so its "
                    f"value is not the same in both modules and cannot be "
                    f"recorded the way a value the build knows is. It is a "
                    f"VARIABLE and not a constant even though `{mod}` also "
                    f"declares it at module level: a name whose one value the "
                    f"build knows crosses the boundary by substitution, because "
                    f"there is exactly one of it in a whole program, and this "
                    f"one has a second writer — so the importer would "
                    f"materialize the value `{mod}` STARTED at. Give `{mod}` an "
                    f"accessor (`def get_{name}(): global {name}; return {name}`) "
                    f"and call that, which reads the same slot and lowers today")
        if name in set(containers or ()):
            return (f"{who}{name!r} is imported from `{mod}`, where it is a "
                    f"module-level CONSTANT whose only writer is its own "
                    f"module-level statement — its value is laid out in "
                    f"`{mod}`'s `__DATA` as a run of words, and there is exactly "
                    f"one of it in a whole program. What does not cross is the "
                    f"ADDRESS: a dylib publishes functions and folded literals, "
                    f"and a block of static data is neither, because its address "
                    f"is chosen when the library is linked and this image cannot "
                    f"have known it. So this is a missing capability and not a "
                    f"missing value: give `{mod}` an accessor that hands back "
                    f"what you need out of it (`def {name}_at(i: Int) -> Int: "
                    f"return {name}[i]`) and call that, which is code, and code "
                    f"is what a dylib exports")
        return (f"{who}{name!r} is imported from `{mod}`, and it is a "
                f"module-level name of another module. This path compiles an "
                f"import into a dylib, and a dylib publishes FUNCTIONS and "
                f"folded CONSTANTS — a name whose value the build knows "
                f"(`{mod}.K = 1`, `{mod}.S = \"x\"`, a `comptime` constant) "
                f"lowers, and a call `{mod}.fn(...)` lowers. What it cannot "
                f"publish is a VARIABLE: there is no storage for one here, "
                f"because every value a formal program can name lives in a "
                f"function's own stack scratch, which is reclaimed when the "
                f"function returns — and a list, a stream object or a function "
                f"used as a value is one of those, not a constant. So this "
                f"name's value is a real global with nowhere to live, which is "
                f"a property of the value model rather than of this call: "
                f"`{mod}.fn(...)` where `{mod}` publishes that function as a "
                f"function is the same program with a representation. "
                f"bugs/formal/FORMAL_module_state_no_storage.md records the design "
                f"and what would have to be true to close it")
    if site == "declared":
        return (f"{who}{name!r} is declared at module level with no value "
                f"(`{name}: T`), so nothing ever writes it and no value "
                f"exists to read. This path has no module-global storage for "
                f"one to be written to. Assign it at module level with a "
                f"literal, or pass it in")
    if site == "comptime":
        return (f"{who}{name!r} is a `comptime` binding declared at module "
                f"level, and it does not fold to a compile-time constant on "
                f"this path. A function's own `comptime NAME = ...` is a "
                f"compile-time value the backend can materialize at its read, "
                f"but a MODULE-level one is not in scope in any function, so "
                f"there is no binding for the read to consult — and a name "
                f"with no binding is not answered from a register. Make the "
                f"value a literal, or move the `comptime` declaration into "
                f"the function that reads it")
    return (f"{who}{name!r} is bound at module level, and this path has no "
            f"module-global storage for it: a formal value lives in a "
            f"function's own stack scratch, and that scratch is reclaimed "
            f"when the function returns, so a name that outlives every frame "
            f"has nowhere to live. A module-level name whose value the build "
            f"can FOLD is substituted at every read and needs no storage — "
            f"this one is not literal-only, so its value is not known before "
            f"the program runs. Make the module-level binding a literal (or "
            f"literal-only arithmetic on literals), or move the computation "
            f"into a function and pass the result in")




# ── MODULE-GLOBAL STORAGE: the `__DATA` slots ─────────────────────────────
#
# A module-level name that some function WRITES (via `global NAME`) needs a
# location that outlives every frame, because the writer and the reader are
# different functions and only one of them is on the stack at a time. That
# location is a `__DATA` slot: eight bytes, one per written name, carrying the
# module-level sequence's final value as its static initializer.
#
# Everything about the LAYOUT is here rather than in either backend, for the
# reason the rest of this file exists: the two architectures must not be able to
# disagree about WHICH names have a slot or WHERE one is, because the bytes the
# linker writes into `__DATA` and the address a backend loads from are two halves
# of one fact. A backend that computed the offset itself would agree with the
# linker only by coincidence — the class of bug this file was written to stop
# (arm64 reading X19 where x86-64 read 0, for one program and one name).
#
# ONE WORD PER SLOT, and that is the value model rather than a simplification.
# A formal value is one 64-bit word, so a slot is one word: an int, a bool, or a
# pointer to a container blob that ALSO lives in `__DATA`. What it cannot hold
# is a pointer into a frame, because a frame is reclaimed when its function
# returns — which is why `collect_global_slots` accepts a module-level container
# literal (its blob is built once, statically, and has the lifetime a global
# needs) and `global_value_refusal` is where a value that does not fit is said.


GLOBAL_SLOT_BYTES = 8
"""Bytes per module-global slot. One word, because a formal value is one word.

Not 4 and not 16: the value model decides it, and the value model is also why a
container global needs a BLOB beside the slot rather than more words here."""


#: How many words `__DATA` reserves AFTER the slots for the BACKEND's own
#: bookkeeping: the initializer flag, the stack floor, the cached `RLIMIT_STACK`
#: and the 16-byte `getrlimit` scratch (two words). **One number, and four places
#: have to agree about it** — the allocation in `build_data_image`, the three
#: `GlobalDataImage.stack_*_offset` properties, and `build_data_image`'s
#: `tail_base`.
#:
#: It was a literal in the allocation and a different literal in the tail
#: layout, and the disagreement was invisible until both were five and two: a
#: module-global container's own words started inside the reserved area, so the
#: floor, the cached limit and the scratch were a container's elements. arm64's
#: guard writes 16 bytes of `RLIMIT_STACK` into the scratch once per process, on
#: a path nothing else writes, and measured on `L = [1, 2]` with
#: `print("v:", L[0])` the image built, printed nothing and exited 1 — on both
#: architectures, with nothing refused. An `int` or a `str` global was
#: unaffected, because their slot words are not in the tail.
GLOBAL_RESERVED_WORDS = 5


class GlobalSlot:
    """One module-level name's `__DATA` slot.

    `index` is the slot's ordinal in the image's slot table. The linker places it
    at `GLOBAL_SLOT_BYTES * index` into `__DATA` and a backend loads from that
    same address, so the two agree by construction rather than by both being
    right — `build_data_image` below is where the offset becomes bytes, and both
    sides read their number from here.

    `init` is the static initializer, one of

      * `("int", n)`    — a literal integer, already a signed 64-bit word
      * `("blob", shape, w)` — the address of a container blob `w` of that
        shape, also in `__DATA`
      * `("str", text)` — the address of NUL-terminated `text`, also in `__DATA`
      * `("frame", struct, w)` — the address of a FRAME of `struct`'s fields,
        `w` being one word per slot in `struct_frame_slots` order, also in
        `__DATA`. `module_frame_slot_initializer` is what produces it, and the
        lifetime reason it exists is that a frame's bytes belong to whoever
        built it: a module-level `X = Struct(...)` compiled any other way puts
        the address of the MODULE BODY's own block in the slot, and that block
        is reclaimed the moment the body returns. So the frame is built in the
        image, where it lives as long as the process does.
      * `("unknown", _)`— no initializer the build can compute; see below

    The three address forms carry an ADDRESS, and an address written into a data
    segment has to be REBASED by the dynamic linker, because the image is mapped
    at a slide: measured on this tree, the same string label is linked at
    0x100000398 and runs at 0x104da4398. `build_data_image` returns the fixup
    list beside the bytes so each linker emits a relocation for exactly the
    address words and not for the integers beside them; `is_address` is the
    classification of which words those are.

    `filled_by_body` is the third source of a slot's value, and the one this
    capability had no word for: the MODULE BODY stores the name
    (`G = compute()` at file level), so the slot is written by the module's own
    top-level statements before anything reads it. It is a FACT about where the
    value comes from rather than about what it is, so it is a flag beside `init`
    rather than a fourth `init` kind — `build_data_image` still lays the word out
    as zeros (nothing static to write), and `static_initializer_refusal_reason`
    is what must NOT refuse, because an unwritten slot here is not an
    uninitialized one: the body writes it first.

    The flag is set for a slot whose value is ALREADY in the image too, when the
    body also rebinds the name — `G = [1, 2]` then a top-level `G = [3, 4]` has
    both — so it answers "does the body write this", and the initializer is
    whatever the image holds before the first such write.

    `body_site` is the `BodyStoreSite` `module_body_store_sites` recorded for it,
    and it is what `module_slot_readable_in` turns into a verdict about a read at
    a particular place. `None` for a slot the body does not fill, and for a body
    store this build could not place in the body's statement list at all — which
    `module_slot_readable_in` then refuses rather than assumes, because the
    conservative answer there is the one that cannot be a wrong number.

    `mutable` is the question a manifest asks and a slot otherwise could not
    answer: **is there a writer besides the module-level binding?** True for a name
    a function writes through `global` and for a name the MODULE BODY stores, false
    for a name whose only writer is its own module-level statement. It is carried
    here for the reason the other fields are — `collect_global_slots` is the only
    function with the unit's statements AND its bodies in hand, so it is the only
    place the two can be compared, and every later reader (`write_dylib_manifest`'s
    `variables`/`containers` split, and through them the refusal that names the
    shape) has neither.

    **A `__DATA` slot is NOT the same fact as `mutable`, and reading it as one is
    what produced a false refusal.** `NUMS = [10,20,30]` gets a slot because its
    value is a container blob the linker places — nothing writes it, so it is a
    CONSTANT with a home — and the manifest published it in the same list as `G`
    in `G = 5` plus `def bump(): global G`. Both have a slot; only one has a second
    writer, and the sentence about the second ("that module's own functions write
    it through `global`") is then false of the first. Measured on both
    architectures before the split: `from lookups import TABLE` where `lookups`
    declares `TABLE = [10,20,30]` and writes nothing was refused as "a module-level
    name … that `lookups`'s OWN functions write through `global`".

    `kind` is the `ValueKinds` kind the slot's value has, and `is_dict` is the
    one distinction that kind cannot carry, for the slots whose initializer does
    not state them: a slot the MODULE BODY fills is `("unknown", …)`, so the
    only thing that says what lands in it is the call the store makes, and that
    call's declared return type says it. Both are carried on the slot rather
    than derived at each read because `global_slot_kind` and
    `global_slot_is_dict` have no access to the unit's functions — and because
    "what does this name hold" must be ONE answer whether the value folded, was
    laid out in `__DATA`, or is computed by the module's own top-level
    statements. `is_dict` is a separate field and not a kind for a reason the
    field's own reader states: every container on this path is one word and one
    kind, so a `kind` that said "dict" would have to lie about the other three
    container types to say it.
    """

    __slots__ = ("name", "index", "init", "site", "filled_by_body", "body_site",
                 "kind", "is_dict", "mutable", "entry_literal")

    def __init__(self, name: str, index: int, init, site=None,
                 filled_by_body=False, body_site=None, kind=None,
                 is_dict=False, mutable=False, entry_literal=None):
        self.name = name
        self.index = index
        self.init = init
        self.site = site
        self.filled_by_body = filled_by_body
        self.body_site = body_site
        self.kind = kind
        self.is_dict = is_dict
        self.mutable = mutable
        # The container literal a FUNCTION's entry may assume for this name, or
        # None. Set for a static-container slot that no statement writes AND
        # that no statement uses in a position that could mutate it in place —
        # see `_module_container_entry_literals`, which is where those two
        # questions are answered together because it is the only place with the
        # unit's statements AND its function bodies in hand. Read by
        # `module_entry_literal_facts`; None for every other slot, which is the
        # safe direction.
        self.entry_literal = entry_literal

    @property
    def is_address(self) -> bool:
        """True when this slot's initializer is an ADDRESS, not a value.

        The classification the linker needs about a slot: Mach-O answers it with
        a dyld rebase opcode and ELF with an `R_X86_64_RELATIVE`, and both are
        correct only for the words this property selects.

        `("frame", …)` is on it — a slot pointing at a struct frame in `__DATA`
        carries an address exactly as `("blob", …)` does — but the property is
        NOT the mechanism, and saying otherwise would send a reader looking for a
        relocation emitted from here. The relocation comes from
        `build_data_image`'s `fixups` list, which each address-valued kind
        appends to (`build_data_image`'s `("blob", "frame")` branch is one
        append for both), and which both emitters walk in `_emit_global_init`.
        So the two kinds cannot disagree about which words need one: there is
        one append, not two predicates."""
        return self.init[0] in ("blob", "str", "frame")

    def __repr__(self):
        return (f"GlobalSlot({self.name!r}, index={self.index}, "
                f"init={self.init!r})")


class GlobalDataImage:
    """The whole data image for one unit, plus where its fixups go.

    `blob` is the bytes, laid out slot-first, then the container blobs the
    address-valued slots point at, and `fixups` is `[(offset, target)]` — for
    each address-valued slot word, the offset WITHIN `blob` of the thing it
    points at. Both are expressed as OFFSETS rather than addresses precisely
    because the linker knows the segment's base address and the backend does not
    need it: one number, added to a base each side already has, instead of two
    independently-computed absolutes that can disagree.

    `string_cells` is the OTHER kind of address-valued word, and it is a
    different list rather than a second entry in `fixups` because its target is
    not in this image at all. A word holding a string is a pointer to
    NUL-terminated bytes, and on this path those bytes are the INTERNED literal
    — one copy per distinct literal, in `__TEXT`, shared by every expression
    that spells the string. So a `string_cells` entry is `(offset, text)`: the
    offset of the word to write, and the string whose interned address belongs
    in it. Only the CODE can carry that out, because only the codegen interns;
    a linker writing the file's initial bytes has nothing to point at and does
    not need to, since the initializer overwrites the word before any read can
    reach it (`initialization_is_lazy` is what makes the overwrite ordered
    before the first read, and the flag is set last).

    Why interned and not a copy in `__DATA`, which would have been the easier
    layout: because a copy is a DIFFERENT string with the same bytes, and this
    value model compares strings by address. Measured on the tree this replaces:
    a dict literal with a string key is found by a raw 64-bit compare against
    the interned literal (`arm64_codegen._emit_dict_lookup_addr`), and two
    separate lists of `"a"` compare EQUAL because both elements are the one
    interned literal. A `__DATA` copy would make `D["a"]` miss and
    `L[0] == M[0]` false, so it is not a smaller version of this feature; it is
    a set of wrong answers wearing one.

    `init_flag_offset` is the word that says "this unit's globals have been
    filled in", and it is PART of the image rather than a module-level name: it
    is the backend's own bookkeeping, it has no source spelling a program could
    collide with, and it has to exist in a dylib as much as in an executable.
    See `initialization_is_lazy` for why the filling is deferred at all."""

    __slots__ = ("blob", "fixups", "init_flag_offset", "string_cells")

    def __init__(self, blob: bytes, fixups: list, init_flag_offset: int = 0,
                 string_cells: list = ()):
        self.blob = blob
        self.fixups = fixups
        self.init_flag_offset = init_flag_offset
        self.string_cells = list(string_cells)

    def __len__(self):
        return len(self.blob)

    @property
    def stack_floor_offset(self) -> int:
        """The word AFTER the initializer flag: where this image's stack floor
        is written, and whether one is.

        A PROPERTY rather than a fifth field, because a field would be a second
        thing to keep equal to `init_flag_offset + GLOBAL_SLOT_BYTES` and the
        bug this whole change is about is two answers to one question about an
        image's layout.

        **Nothing writes it yet.** The word exists, it is in every image, and it
        reads as zero; `STACK_FLOOR_BUDGET_BYTES` below is the policy the writer
        will use. It is here, and not later with the writer, because the word has
        to exist in an image with no module globals at all — which is what
        `deep(N)`, the reproducer of the frame-size bug, compiles to.
        """
        return self.init_flag_offset + GLOBAL_SLOT_BYTES

    @property
    def stack_limit_offset(self) -> int:
        """The word after the floor: where this image CACHES `RLIMIT_STACK`.

        A third reserved word, and the reason it is needed is a measurement: the
        floor could not stay a compile-time constant, because a budget larger
        than the process's real stack is a guard that never fires — the same
        binary at the same depth gives `exit 2` under the default `ulimit -s
        8176` and `exit 139` (a SIGSEGV with no output) under `ulimit -s 2048`.
        So the guard reads the limit at run time, and reading it is a CALL, so
        it is made once per process rather than once per call — which needs a
        word to remember the answer in, and `__DATA` is the only place in the
        image that outlives the frame that read it.

        Zero means "not read yet", which is safe rather than a hole for the same
        reason the floor's zero is: the `CBNZ` tests it BEFORE the `getrlimit`,
        so the first guarded prologue does the read and no later one repeats it,
        and a program that somehow reaches the guard with the word still zero
        reads it rather than proceeding.
        """
        return self.init_flag_offset + 2 * GLOBAL_SLOT_BYTES

    @property
    def stack_scratch_offset(self) -> int:
        """The word after the cached limit: 16 bytes of `__DATA` the guard lends
        to `getrlimit`.

        **A `__DATA` word and not 16 bytes of stack, and the measurement is why.**
        The guard's `getrlimit(RLIMIT_STACK, &rlim)` needs a 16-byte destination,
        and the two obvious homes for it both corrupt the program:

          * **the frame.** Emitted before `sub sp, #_SCRATCH`, a `sub sp, #16` /
            `add sp, #16` pair around the call leaves SP 16 bytes lower across an
            extern call, and the C library reads SP-relative state across that
            boundary — measured as a hang or a SIGSEGV on *every* program,
            including `def helper(x): return x + 1` with a `main` that calls it,
            with no recursion and no output. Reusing the caller's red zone at
            `[sp, #16)` is worse: those are the caller's own frame, and
            overwriting them hangs immediately.
          * **the frame's blob region.** The original placement, after
            `sub sp, #_SCRATCH`, where `[sp, #0..#16)` is where a RECEIVER FRAME
            lives (`struct_constructor_sites`) — a store there corrupts the
            struct the call was handed.

        `__DATA` is writable, already addressed by the ADRP/ADD pair two
        instructions earlier, and cannot be aliased by anything: it outlives every
        frame and the only writer is this guard, on a path the `CBNZ`/`JNE` above
        runs once per process.

        Two words rather than one, because `struct rlimit` is two `rlim_t` and
        only `rlim_cur` (the first) is read — but the C library writes both, and a
        16-byte store into the last word of the image would be a write past it.
        """
        return self.init_flag_offset + 3 * GLOBAL_SLOT_BYTES


    def __bool__(self):
        return bool(self.blob)


# THE STACK-FLOOR BUDGET, and why it is a constant at all.
#
# Every function on this path subtracts a FIXED frame from the stack pointer
# (arm64: `_SCRATCH`, 128 KiB; x86-64: `_BLOB_BYTES` plus the computed locals)
# and nothing compares the result against a floor, so the reachable recursion
# depth is the stack size divided by the frame size and crossing it is a
# SIGSEGV — no output, no message, no status a caller can read. Measured on this
# tree (2026-10-02, `ulimit -s` 8176 KiB, `RLIMIT_STACK` 8372224), same
# three-line `deep`: arm64 answers at 61 and dies with exit -11 at 62; x86-64
# answers at 450 and dies at 500. So the usable stack below the startup stub's SP
# is between 7.63 and 7.75 MiB, against a limit of 7.98 MiB.
#
# A guard compares SP against `SP_at_entry - BUDGET`, and `SP_at_entry` is a
# run-time fact (which is why the floor is a word and not an address), but
# BUDGET is a POLICY number: how much of the process's stack this compiler is
# willing to promise before it refuses instead of dying. It has to be BELOW the
# real floor to be worth having — a budget above it fires after the kernel has
# already killed the process — and it costs depth when it is below: at 128 KiB a
# frame, 256 KiB of margin is two levels of recursion on arm64.
#
# 7.5 MiB is that trade made explicitly: under the measured usable floor by
# 128–256 KiB (one to two arm64 frames), and 480 KiB under the process limit.
# The failure mode of being wrong is stated here because it is the whole risk:
# a BUDGET that overestimates the real stack (a thread stack rather than the
# main one, or a host with a smaller `ulimit -s`) leaves the guard silent and the
# program dies as it does today — no worse than the defect being fixed — while a
# BUDGET that underestimates costs depth, which is a refusal and never a crash.
#
# **The depth this affords is PER-ARCHITECTURE, and that is the budget's shape
# rather than a defect of the guard.** The budget is in BYTES because the thing
# it bounds — the stack a runaway recursion may spend before it is refused — is
# in bytes, and it is the SAME stack on both machines. But the frames are not
# the same size: arm64's is `ARM64_CONTAINER_BUDGET` (128 KiB) and x86-64's is
# `X86_64_CONTAINER_BUDGET` (16 KiB), so the one budget is 60 frames of arm64
# and 480 of x86-64 — 8x, the frame ratio spelled out. A DEPTH budget instead
# would either refuse x86-64 8x earlier than it needs to, or (if sized for
# x86-64's depth) let arm64 spend 60 MiB of a 7.5 MiB stack and crash exactly as
# it did before the guard existed. `stack_floor_depth(arch)` is the one place
# the per-architecture figure is computed; a harness that compares the two
# machines' recursion depth is measuring this budget, not the compiler.
STACK_FLOOR_BUDGET_BYTES = 7 * 1024 * 1024 + 512 * 1024


def stack_floor_depth(arch: str) -> int:
    """The recursion depth `STACK_FLOOR_BUDGET_BYTES` affords on `arch`.

    One budget in BYTES, two frame sizes, so the depth is per-architecture and
    this is the single place it is derived: arm64's frame is
    `ARM64_CONTAINER_BUDGET` (128 KiB) and x86-64's is `X86_64_CONTAINER_BUDGET`
    (16 KiB), giving 60 and 480 — the 8x that is exactly the frame ratio, and a
    property of the byte policy rather than of the guard. The MEASURED edge is
    one or two frames below the quotient (the real frame is at least the budget,
    and the 256 KiB margin is a level), which is why `tools/formal_fuzz.py`
    counts a one-machine `trapped` pair apart from a parity finding.
    """
    arch = str(arch).replace("-", "_")
    frame = (ARM64_CONTAINER_BUDGET if arch in ("arm64", "aarch64")
             else X86_64_CONTAINER_BUDGET)
    return STACK_FLOOR_BUDGET_BYTES // frame


# THE PART OF THE PROCESS'S STACK THIS COMPILER LEAVES ALONE, and the reason
# the guard above has to read the limit at RUN time rather than trust this
# constant.
#
# `STACK_FLOOR_BUDGET_BYTES` says how much stack this compiler is willing to
# spend. It cannot say how much there IS, because that is `RLIMIT_STACK` — a
# fact about the process the kernel established, which a caller may have
# lowered before exec and which nothing in the source mentions. Measured on this
# tree with a 128 KiB-frame C probe, so the frame is the only variable
# (`tools/formal_recursion_depth.py` measures the same thing on the images):
#
#     ulimit -s   rlim_cur    deepest frame set    unusable
#       1024 KiB   1048576         786432         262144
#       2048 KiB   2097152        1835008         262144
#       4096 KiB   4194304        3932160         262144
#       8176 KiB   8372224        8126464         245760
#      16384 KiB  16777216       16515072         262144
#      32768 KiB  33554432       33292288         262144
#
# **256 KiB, and it does not scale.** That is the guard page, the kernel's own
# bookkeeping and the startup stub's frame — a fixed cost, which is why the
# RATIO of usable stack to limit runs from 0.75 at 1 MiB to 0.99 at 32 MiB while
# the DIFFERENCE stays flat. A margin written as a fraction of the limit would
# be wrong at one end or the other, and this constant is what says so.
STACK_FLOOR_MARGIN_BYTES = 256 * 1024


# `RLIMIT_STACK`, the `getrlimit(2)` SELECTOR whose soft limit is how much stack
# the process may use. It is 3 on Darwin (`sys/resource.h`) and on Linux
# (`RLIMIT_STACK` in `bits/resource.h`), and those are the two targets this path
# emits for; a third would need its own value here rather than a silent reuse of
# this one.
#
# **In the model, not in either backend**, because both backends' guards now read
# the limit and a literal in each file is two copies of one answer — which is how
# they came to disagree about the arm64 threshold once already (see
# `stack_floor_guarded_names` for the rule that is genuinely per-backend, which is
# a different thing: WHICH prologues carry the guard, not what they compare).
RLIMIT_STACK = 3


# THE SMALLEST BUDGET THE GUARD WILL USE, and why the arithmetic above needs one.
#
# A process whose limit is BELOW the margin has by definition less usable stack
# than the margin reserves, so `limit - margin` is negative; an unsigned subtract
# wraps it to a huge positive, the floor word is stored far ABOVE the stack
# pointer, and the guard's "SP >= floor" is then trivially true forever — a guard
# that is silent, which is the crash this mechanism exists to replace. Measured
# reachable rather than theoretical: macOS's own default stack for a non-main
# thread is 512 KiB, which is the margin itself, so a thread's recursion lands
# inside this case on a stock host.
#
# **TWO arm64 frames, and the second one is load-bearing.** The guard runs before
# the frame reservation (`stack_floor_budget_for_limit`'s frame term below), so a budget of a single
# frame would put the floor exactly at the current SP, where `SP >= floor` is true
# by construction and the guard never fires — the silent-crash failure mode this
# whole mechanism exists to prevent, reached by the clamp meant to prevent it.
# Two frames always leaves at least one frame of depth to recurse into.
STACK_FLOOR_MIN_BUDGET_BYTES = 2 * ARM64_CONTAINER_BUDGET


def stack_floor_budget_for_limit(limit_bytes: int,
                                 frame_bytes: int = None) -> int:
    """The budget the guard uses on a process whose stack limit is `limit_bytes`.

    The run-time half of the policy above, and the reason the guard could not be
    a constant: **a budget larger than the process's real stack is a guard that
    never fires**, and what it leaves behind is the silent SIGSEGV the guard was
    written to replace. Measured, same binary, same program, same depth, with
    `STACK_FLOOR_BUDGET_BYTES` used verbatim as it was before this existed:

        ulimit -s 8176 (the default here)   exit 2    the guard fires
        ulimit -s 2048                      exit 139  SIGSEGV, no output
        ulimit -s 1024                      exit 139  SIGSEGV, no output
        ulimit -s 512                       exit 139  SIGSEGV, no output

    So the answer is `min(BUDGET, limit - MARGIN - frame)` and every term is the
    conservative direction: the budget never exceeds what the policy is willing
    to spend, it never claims more of the stack than the kernel leaves usable,
    and it never claims a whole frame the first call has not taken yet. That last
    term is the one that was missing, and it is now INSIDE the budget both
    emitters charge directly — `floor = SP - budget`, with no second frame
    subtraction anywhere.

    `frame_bytes` defaults to the largest frame either backend emits
    (`ARM64_CONTAINER_BUDGET`), which is the conservative choice for a caller
    with no particular function in mind — a smaller frame would buy one more
    level of depth on a host with stack to spare, and the guard's own docstring
    is where that trade is argued.

    **An integer in, an integer out, with no syscall in here**, because the
    emitter cannot call `getrlimit` — its whole job is to emit instructions, and
    reading the limit IS a call, emitted where the guard is emitted. What the
    emitter does with the answer is `arm64_codegen._emit_stack_floor_guard`'s
    business; keeping the arithmetic here is what lets a test pin the relation
    between a limit, a margin and a budget without a process, and
    `getrlimit(RLIMIT_STACK)` on the BUILD host is not the limit of the process
    that will RUN the image.
    """
    frame = (ARM64_CONTAINER_BUDGET if frame_bytes is None
             else int(frame_bytes))
    usable = int(limit_bytes) - STACK_FLOOR_MARGIN_BYTES - frame
    if usable < STACK_FLOOR_MIN_BUDGET_BYTES:
        usable = STACK_FLOOR_MIN_BUDGET_BYTES
    return min(STACK_FLOOR_BUDGET_BYTES, usable)


# **THERE IS NO `stack_floor_charge` ANY MORE, AND THAT IS THE CORRECTION RATHER
# THAN A TIDY-UP.** A function of that name once answered `budget - frame`, and
# it was removed because it was UNCALLED and WRONG if called: the frame term
# moved INTO the budget (`stack_floor_budget_for_limit` computes
# `limit - MARGIN - frame` above), so both emitters now charge the budget
# DIRECTLY — `arm64_codegen._emit_stack_floor_guard`'s `floor = SP - budget` and
# `x86_64_codegen._emit_stack_floor_init`'s `budget = limit - (MARGIN + frame)`.
# Routing them through a helper that subtracted the frame AGAIN would have put
# the floor one frame lower and let the guard fire one frame LATE — the
# `budget + frame` column of the four-limit measurement, which is the crash
# direction. The measurement itself lives at
# `_emit_stack_floor_guard`'s sibling `_emit_stack_floor_init`: over
# `ulimit -s` 8176/4096/2048/1024 KiB the deepest depth that answers is one less
# than `budget / frame`, and every row where a `budget - frame` charge was used
# was a depth CPython answers and this path stopped answering.

def stack_trap_message() -> str:
    """The ONE text a stack overflow writes to fd 2 before it stops the program.

    For BOTH backends, for the reason every other `*_message` in this file is
    shared: two architectures naming one limit differently is how a reader ends
    up looking for a construct one of them invented. The siblings are
    `list_append_overflow_message`, `dict_store_overflow_message` and
    `int_parse_trap_message`, and this is the fourth member of that family —
    **the one that was missing**, because the stack-floor trap was the only
    bounded stop on this path that said nothing at all:

        $ python3 fire.py build --formal --no-prove -n 5000 -o deep deep.mojo
        $ ./deep; echo "exit $?"
        exit 2

    A status, no output on either stream, and nothing to say which of the
    program's bounds it hit. Every other bound on this path names itself.

    **It takes no arguments, and that is a decision rather than an omission.**
    The text is an interned literal in `__TEXT` — this path has no `printf`, so
    every number in it is spelled in at BUILD time, which is exactly what
    `list_append_overflow_message`'s capacity and `int_parse_trap_message`'s
    base are. So it cannot quote the process's `RLIMIT_STACK`, which is a run-time
    fact and is the number a reader who lowered `ulimit -s` most wants to see.

    What it does instead is name the RULE those two numbers come out of, which
    is strictly more useful than either number alone: the budget is
    `min(STACK_FLOOR_BUDGET_BYTES, your limit - STACK_FLOOR_MARGIN_BYTES)`, so a
    reader holding their own `ulimit -s` computes their own depth in one step.
    A message that quoted a number the reader cannot check would be worse than
    one that names the arithmetic.

    Three things are named, and they are the three a reader needs in order to
    act:

      * **the depth is not the limit.** What fires is `budget / frame_bytes`,
        and the frame is a property of the FUNCTION, so the same recursion is
        refused at depth 59 on arm64 and 471 on x86-64 purely because of the two
        frame sizes (measured: `tools/formal_recursion_depth.py`). A message
        saying only "too much recursion" sends the reader to their recursion
        when the answer is their frame layout;
      * **the budget, the margin, and that the budget is the SMALLER of the two**
        — which is what tells a reader that a smaller stack refuses sooner
        rather than failing to refuse at all;
      * **what to do** — CPython's remedy for a deep recursion is
        `sys.setrecursionlimit`, and `formal/hostmods/sys.mojo`'s
        `setrecursionlimit` says in its own docstring that it changes nothing,
        so a program that follows CPython's advice verbatim gets no warning
        until it stops. Saying so is the difference between a diagnostic and a
        dead end.
    """
    return (f"RecursionError: this program's call stack went past the stack "
            f"budget of {STACK_FLOOR_BUDGET_BYTES} bytes, which is the smaller "
            f"of that number and this process's own stack limit less "
            f"{STACK_FLOOR_MARGIN_BYTES} bytes of reserve — so a process with "
            f"a smaller stack refuses SOONER, and never later than this. "
            f"CPython raises RecursionError for a recursion this deep, and "
            f"sys.setrecursionlimit cannot help here: this target has no "
            f"interpreter stack to raise a limit on, and it compiles the limit "
            f"you ask for without changing anything. The depth that fits is "
            f"the budget divided by one call frame; a frame is "
            f"{ARM64_CONTAINER_BUDGET} bytes on arm64 and "
            f"{X86_64_CONTAINER_BUDGET} on x86-64 plus whatever the function "
            f"spills, so the same recursion is refused at a different depth on "
            f"each and a function with many locals is refused sooner. Rewrite "
            f"the recursion as a loop, or split it so that no chain of calls is "
            f"this deep.\n")


# THE STATUS A STACK OVERFLOW LEAVES, beside the one a shift leaves. The
# argument for a second number and against reusing `SHIFT_TRAP_STATUS` is the
# argument every status on this path makes: "this program could not be answered"
# is one answer, and a caller that has to tell a stack overflow from a negative
# shift amount is being handed a distinction nobody downstream wanted. But they
# are not the same event, and the diagnostic value of naming which one happened
# is real: an overflow is a statement about the program RECURING and an operand
# being a negative amount is a statement about one line. 1 is taken by the
# divide-by-zero arm of each backend's shift/div emitter (`SHIFT_TRAP_STATUS`),
# so this is 2, and both backends read the constant rather than the literal —
# the same reason that one is a constant.
STACK_TRAP_STATUS = 2


def stack_floor_address(base: int, table: dict = None) -> int:
    """Where this unit's stack-floor WORD is, as an absolute address.

    The one computation of it, for both backends and for every prologue in the
    image, because the failure this guards against has a second copy of this
    answer in it: `GlobalDataImage.stack_floor_offset` already refuses to be a
    second field kept equal to `init_flag_offset + GLOBAL_SLOT_BYTES`, and a
    backend that added `init_flag_offset + 16` here would be the third answer
    to one question about an image's layout. The offset is read out of the image
    the linker is writing, not recomputed from the table, so the code cannot
    address a word the bytes do not contain.

    `table` defaults to the published slot table; both callers pass
    `module_slots()` explicitly today, and the default exists so a caller that
    has not published yet gets the empty-table image (two reserved words) rather
    than a `None`.
    """
    return base + build_data_image(
        module_slots() if table is None else table, base).stack_floor_offset


def stack_limit_address(base: int, table: dict = None) -> int:
    """Where this unit's CACHED STACK LIMIT word is, as an absolute address.

    The word AFTER the floor, and a separate question from it, which is why it is
    a second function and not `stack_floor_address(...) + 8`: the floor is
    derived (SP minus a budget) and the limit is read (`getrlimit`), they are
    written at different moments by different instructions, and a backend that
    spelled the second as an offset from the first would be relying on the two
    staying adjacent in `__DATA` — which is `GlobalDataImage`'s layout to decide
    and this file's to name.

    The offset is read out of the IMAGE rather than recomputed, for the same
    reason `stack_floor_address` does it: a word the bytes do not contain is
    addressable and that is the worst way for a guard to be wrong.
    """
    return base + build_data_image(
        module_slots() if table is None else table, base).stack_limit_offset


def stack_scratch_address(base: int, table: dict = None) -> int:
    """Where this unit's 16-byte `getrlimit` scratch is, as an absolute address.

    The word after the cached limit, and `GlobalDataImage.stack_scratch_offset`
    is where the reason it is `__DATA` and not the stack is written down — the
    short version is that all three stack answers corrupt the program, and the
    measurements are on that property's docstring. It is a separate function for
    the same reason `stack_limit_address` is: three words with three different
    writers, and an offset spelled as `previous + 8` three times is three
    chances to be wrong about a layout this file decides.
    """
    return base + build_data_image(
        module_slots() if table is None else table, base).stack_scratch_offset



def call_graph_edges(functions, structs: dict = None) -> dict:
    """`{caller: {callee, …}}` for one image's functions, as the emitter sees them.

    The one place an edge is added, so the stack-floor guard's rule
    (`stack_floor_guarded_names`) and the depth census that measures whether that
    rule leaves a hole (`tools/formal_call_depth_census.py`) cannot come apart on
    what a call is — the same reason `call_callee_name` is one function rather
    than one copy per backend.

    **The edges are a SUPERSET of the calls the emitter makes, deliberately,
    since a missed edge means a missed cycle and an unguarded recursion.**
    `call_callee_name` answers the two spellings that name a function of this
    image by a bare name, and a `recv.m(x)` callee contributes `Struct_m` for
    EVERY struct in the image that declares an `m` — which is the symbol the
    method-call rewriting emits, and over-approximating the owner is the safe
    direction because it can only add an edge. A call out of the image (a dylib
    symbol, an extern) is not an edge: nothing in this image calls back into it,
    so it cannot close a cycle here.

    Callees that are not functions of this image are absent from the values
    rather than present-and-empty, which is what lets the census distinguish "no
    edge" from "an edge out of the image".
    """
    method_owners: dict = {}
    for st in (structs or {}).values():
        for m in struct_methods(st):
            method_owners.setdefault(m.name, []).append(st.name)
    edges: dict = {f.name: set() for f in functions}
    for f in functions:
        body = getattr(f, "body", None)
        if body is None:
            # A StructDef, or anything else that is not a function. Both
            # backends pass their `_functions` table, which is FunctionDefs
            # only, so this is the guard against a caller that hands over the
            # module's whole statement list — and skipping is the right answer
            # rather than an error, because a struct has no calls of its own.
            continue
        for node in iter_nodes(body):
            if not isinstance(node, F.CallExpr):
                continue
            callee = call_callee_name(node.func)
            if callee is not None:
                edges[f.name].add(callee)
                continue
            func = node.func
            if isinstance(func, F.SubscriptExpr):
                func = func.obj
            if not isinstance(func, F.MemberExpr):
                continue
            for owner in method_owners.get(func.member, ()):
                edges[f.name].add(f"{owner}_{func.member}")
    return edges


def call_graph_depth(edges: dict) -> int:
    """An UPPER BOUND on the number of distinct functions a call chain can have
    live at once, in `edges`.

    The question `bugs/formal/FORMAL_stack_floor_does_not_guard_an_acyclic_chain.md`
    asks and the guard does not answer: unbounded depth needs a CYCLE, so the
    guard is emitted on the cycles only, but "finite" is not "small" and a DAG
    sixty levels deep spends the same stack as a recursion sixty deep.

    **The depth the budget affords is PER ARCHITECTURE, because the budget is
    bytes and the frame is not.** `STACK_FLOOR_BUDGET_BYTES` is one 7.5 MiB
    constant on both machines, but `(BUDGET - frame) // frame` — the depth the
    guard's direct `budget` charge admits — is 59 on arm64 against a 128 KiB frame
    (`ARM64_CONTAINER_BUDGET`) and 479 on x86-64 against a 16 KiB one
    (`X86_64_CONTAINER_BUDGET`) before the function's own spills, which is why
    the measured x86-64 edge is 471 and not 479 (`tools/formal_recursion_depth.py`,
    measured, not estimated). So the same recursion is refused at a different
    depth on each machine by design: 59 is the ARM64 figure, and a reader on
    x86-64 must not take it as a fact about x86-64. The budget docstring above
    and `stack_trap_message` say the same thing where an operator meets it.

    **An upper bound, and the same direction as the sweep's `FILES BLOCKED`.**
    The exact figure is the longest SIMPLE path, which is NP-hard in general, so
    this takes the bound a linear-time decomposition gives: collapse each
    strongly-connected component to a node weighted by its SIZE, and take the
    longest weighted path in the condensation. A simple path enters a component
    once (the condensation is acyclic, so it cannot leave and come back) and
    visits at most `size` distinct members inside it, so that sum bounds it —
    and it is reached only when a component is a clique-like blob, which the
    measured images are not.

    Two iterative DFS passes (Kosaraju) rather than one recursive Tarjan: a
    45-file closure has call chains deeper than Python's own recursion limit,
    and a measurement that raises `RecursionError` on the graph it exists to
    measure is not a measurement.
    """
    nodes = set(edges) | {n for callees in edges.values() for n in callees}
    if not nodes:
        return 0
    # Kosaraju pass 1: finish order, on the forward graph.
    order: list = []
    seen: set = set()
    for root in sorted(nodes):
        if root in seen:
            continue
        seen.add(root)
        stack = [(root, iter(sorted(edges.get(root, ()))))]
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append((nxt, iter(sorted(edges.get(nxt, ())))))
                    advanced = True
                    break
            if not advanced:
                order.append(node)
                stack.pop()
    # Pass 2: components, on the reverse graph, in decreasing finish order.
    rev: dict = {}
    for caller, callees in edges.items():
        for callee in callees:
            rev.setdefault(callee, set()).add(caller)
    comp_of: dict = {}
    comps: list = []
    for root in reversed(order):
        if root in comp_of:
            continue
        cid = len(comps)
        members = []
        stack = [root]
        comp_of[root] = cid
        while stack:
            node = stack.pop()
            members.append(node)
            for prev in sorted(rev.get(node, ())):
                if prev not in comp_of:
                    comp_of[prev] = cid
                    stack.append(prev)
        comps.append(members)
    # The condensation, and the longest weighted path over it.  A component
    # containing a cycle is where the guard already fires, so it is counted at
    # its SIZE and no further: the bound is about the acyclic tail.  Kosaraju's
    # second pass emits the components in TOPOLOGICAL order of the
    # condensation, so walking the list backwards is a valid relaxation order
    # and the DP needs no recursion of its own — which matters, because a deep
    # chain is exactly the shape this is measured on.
    succ: dict = {}
    for caller, callees in edges.items():
        src = comp_of[caller]
        for callee in callees:
            dst = comp_of.get(callee)
            if dst is not None and dst != src:
                succ.setdefault(src, set()).add(dst)
    best = [1] * len(comps)
    depth = 1
    for cid in range(len(comps) - 1, -1, -1):
        own = len(comps[cid])
        m = own
        for nxt in succ.get(cid, ()):
            m = max(m, own + best[nxt])
        best[cid] = m
        depth = max(depth, m)
    return depth


def body_has_conditional_branch(fn) -> bool:
    """Does this body's SOURCE contain a construct that ALWAYS lowers to a
    conditional branch?

    **The predicate exists for one argument and the argument is a DIRECTION.**
    `stack_floor_guarded_names` widens the stack-floor guard from the call-graph
    cycles to every function whose body already branches, and the price is the
    per-export contract proof: `arm64_proof_gen._dylib_contract_proof` returns
    `""` — no contract — for an export whose body contains ANY conditional
    branch, so the guard's own `cbnz`/`b.hs` costs a contract only in a body that
    had one to lose. For that to be an argument rather than a hope, this
    predicate must never answer True for a body the EMITTER lays out
    straight-line — over-counting would take a contract away from an export that
    has one. So:

      * counted: `if`, `while`, `for`, `assert`, `try`, `match`, and a
        comprehension with a condition. Each of these lowers to a compare and a
        branch on BOTH backends with no purity gate in front of it —
        `_emit_if` and `_emit_loop` always emit one, and `_emit_compr_gen`'s
        condition arm always emits a `cbz`;
      * NOT counted: a ternary (`a if c else b`) and a short-circuit chain
        (`a and b`). Both backends have a BRANCHLESS lowering chosen by a
        purity predicate, so a body whose only branch is one of them can still be
        straight-line in the image;
      * NOT descended: a nested `def`. Its branches are in ITS prologue, not this
        one's — the same rule `ValueKinds._scan` follows for the same reason.

    Under-counting is the safe direction and is where the residual lives:
    `tools/formal_call_depth_census.py`'s `unguard` column is what this
    predicate's complement leaves unguarded, measured over the corpus. (It was
    written `no-brch`, which is a name the census does not print — the column is
    `unguard`, and it is the DEPTH of the deepest chain through unguarded
    bodies rather than a per-image flag. Fixed 2026-10-05, with the residual
    re-measured the same day: **7 frames**, unchanged, which is what
    `stack_floor_guarded_names`'s own paragraph above states.)
    """
    body = getattr(fn, "body", None)
    if body is None:
        return False
    return _has_branch_node(body)


def _has_branch_node(node) -> bool:
    """`_has_branch_node` over a statement list, without a nested `def`'s body.

    An explicit walk rather than `iter_nodes` for the one reason the docstring
    above gives: `iter_nodes` descends a nested `FunctionDef` because a nested
    def is just another dataclass node in the tree, and its branches are not in
    this function's emitted code.
    """
    if isinstance(node, (list, tuple)):
        return any(_has_branch_node(x) for x in node)
    if isinstance(node, F.FunctionDef):
        return False
    if isinstance(node, (F.IfStmt, F.WhileStmt, F.ForStmt, F.AssertStmt,
                         F.TryStmt, F.MatchStmt)):
        return True
    if isinstance(node, F.Comprehension):
        for gen in (getattr(node, "generators", None) or []):
            if getattr(gen, "conditions", None):
                return True
    if not hasattr(node, "__dataclass_fields__"):
        return False
    return any(_has_branch_node(getattr(node, name))
               for name in _node_field_names(node))


def stack_floor_guarded_names(functions, structs: dict = None,
                              every_function: bool = False) -> set:
    """The functions of one image whose prologue carries the stack-floor guard.

    Three rules, and only the third is new:

      * **`every_function`** — the whole image. This is the rule for an image
        that has a STARTUP STUB and therefore no exports, and it exists because
        the guard's floor is written by the FIRST guarded function to run
        (`CBNZ X16, done` in the sequence below): a guard that only some
        prologues carry is a guard whose floor is set by whichever of those
        prologues the program happens to reach FIRST, so a chain of unguarded
        functions below that one is below a floor that was already too deep to
        catch anything. Measured on the shape — 600 straight-line functions in a
        chain from a straight-line `main`, so no cycle and no branch anywhere —
        arm64 answers `exit 139`: a SIGSEGV with no output and no status, which
        is the defect this whole mechanism exists to replace. With `main` in the
        set the chain traps at the budget instead.

        The one thing that made this not obvious is that guarding `main` ALONE
        does not close it: the check runs once, at main's prologue, where the
        stack is one frame deep. It is the whole SET that has to be guarded, and
        the whole set is affordable here for the reason the per-export contract
        argument gives — a program image has no exports, so no export loses a
        contract. That is why this is a parameter and not the rule: a MODULE
        DYLIB, where every function may be an export with a proved contract, must
        keep the two rules below.

      * **on a call-graph CYCLE.** Unbounded call depth is a cycle: a chain of
        distinct functions has a finite depth, and it is the return to a function
        already on the stack that makes the depth a function of the PROGRAM
        rather than of its shape. So a cycle's members are where a runaway
        recursion is stopped, and a program that recurses cannot get past one.

      * **or the body already contains a conditional branch**
        (`body_has_conditional_branch`). This was NOT in the rule that landed
        with the guard, and it is the measured answer to the question
        `bugs/formal/FORMAL_stack_floor_does_not_guard_an_acyclic_chain.md` spent its
        life asking. Every formal prologue subtracts a fixed 128 KiB frame on
        arm64 (16 KiB on x86-64), so the depth at which the stack runs out is a
        constant — 60 frames against `STACK_FLOOR_BUDGET_BYTES` on arm64 — and
        the cycle rule left a DAG of DISTINCT functions free to walk straight
        past it. Measured over this repository and the stdlib with
        `python3 tools/formal_call_depth_census.py` (12 s, no build): the
        deepest single image is **89 frames** (`formal/arm64_codegen.py`, and
        **78** for `x86_64_codegen.py`), which is 1.5x what the arm64 budget
        affords. So this is not a stated limit with no work behind it; it is
        one the corpus is already inside.

        **Those figures were 76 and 69 (1.3x) until 2026-10-05, and the number
        is a MEASUREMENT of the tree rather than a property of the rule** — the
        repository has grown from 413 to 474 images since, and the two deepest
        are still the two this backend's own codegen lives in. It is written
        here with the command that produces it for that reason: a figure quoted
        without one cannot be re-measured by the next reader, and a stale one is
        indistinguishable from a true one until something goes wrong.

    **And the second rule costs nothing the first one was careful not to.** The
    per-export contract proof (`arm64_proof_gen._dylib_contract_proof`) declines
    to emit a contract for an export whose body contains ANY conditional branch —
    `Refine.Block.step` is one function of one state, and a conditional branch
    does not have one. So a body that already branches has no contract to lose,
    and a body that does not is left exactly as it was. "Every function" would
    trade proved contracts for nothing; "every function that already has a
    branch" does not, and `body_has_conditional_branch` is written to that
    direction.

    **What the widening does not reach**, measured rather than argued: a chain
    of bodies that have no branch at all. The census's `unguard` column is that
    chain's depth, and its maximum over the same corpus is **7 frames** — a
    median of 3, against the 60 the arm64 budget affords (59 measured, one frame
    spent by the caller). So the residual is a bounded 7 rather than an
    unbounded "finite", and it is bounded by a module's size rather than by the
    guard. 600 straight-line functions in a chain still walk off the end of the
    stack; that is what `test_formal_run.py`'s
    `guard_a_straight_line_chain_is_left_alone` row says out loud, and closing
    it is `lib/Refine.lean` — a `Block` per arm with a join — not an emitter.

    The edges are `call_graph_edges`, and its docstring carries why they are a
    superset and why a call out of the image is not an edge. `call_graph_depth`
    is what measured the two numbers above, on the same edges, so the
    measurement and the rule cannot come apart.
    """
    edges = call_graph_edges(functions, structs)
    by_name = {f.name: f for f in functions}

    def reaches_self(start: str) -> bool:
        seen, stack = set(), [start]
        while stack:
            cur = stack.pop()
            for nxt in edges.get(cur, ()):
                if nxt == start:
                    return True
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return False

    if every_function:
        return set(by_name)
    return {name for name in by_name
            if reaches_self(name) or body_has_conditional_branch(by_name[name])}



# THE GUARD'S SHAPE, decided once so that neither backend can spell it twice.
#
# **Which prologues get it** is `stack_floor_guarded_names` above, and that is
# the only decision here that is not the sequence: the sequence is the same in
# every prologue it appears in, and a prologue it does not appear in is
# unchanged code.
#
# Both prologues subtract a fixed frame and then do this, and the order is
# load-bearing on both machines:
#
#     <floor> = the word at `stack_floor_address(...)`
#     if <floor> == 0:  <floor> = SP - BUDGET ; store it back
#     compare SP against <floor> and EXIT(STACK_TRAP_STATUS) if SP is below it
#
# Four decisions, each of which had more than one available answer:
#
# * **The floor is stored LAZILY, in every prologue, and not from the
#   executable's entry stub.** A stub would do it once per process for an
#   executable, and a dylib has no entry stub (`emit_startup=False`), so that
#   answer is one mechanism for one container kind and a hole in the other —
#   the shape `initialization_is_lazy` below already refuses for the same
#   reason. The store is a `cbnz`/`jne` over four instructions and runs once
#   per process; the alternative saves those four instructions per call and
#   costs a second code path that a library image cannot take.
# * **Zero means "not stored yet", and that is SAFE, not a hole.** The compare
#   is an UNSIGNED lower test, and a stack pointer is never below zero, so an
#   unset floor cannot fire — the guard is silent rather than wrong, which is
#   exactly today's behaviour and the state the word starts in. This is why the
#   floor needs no initialization ORDER relative to the first prologue: the
#   store and the compare are in the same prologue, store first.
# * **The budget is subtracted from the SP the frame subtraction LEFT**, not
#   from the caller's SP. The difference is this function's own frame, which is
#   charged against the budget rather than added to it, and that is the
#   conservative direction.
# * **The compare reads SP into a scratch register first on arm64** rather than
#   using `CMP SP, Xm`. Both spell the same instruction to the hardware, and the
#   model now reads both correctly — `arm64_reg_or_sp` gives an `Rn` of 31 the
#   meaning A64 gives it in the forms that HAVE that encoding, so the register
#   `CMP` (`SUBS XZR, Rn, Rm`) is `cmp sp, floor` and `ADD Xd, SP, #imm` is the
#   sp-based add. The two-instruction spelling is kept because it predates that
#   and because it names two ordinary registers either way, which is the cheaper
#   thing to have a proof about; it is a choice, not a workaround.


# WHY THE INITIALIZER IS LAZY, and why it is not the startup stub.
#
# The obvious place to fill an address-valued slot is the executable's startup
# stub, which runs before `main` and is free to emit as much setup as it likes.
# That works — it is the first thing this did, and it is verified — but it does
# not work for a DYLIB, and a dylib is half of where module state lives: a
# module compiled into a library has `emit_startup=False` precisely because a
# library has no entry point, so a stub that runs once per process does not
# exist for it to run in. Two answers (a stub in one container kind, a refusal in
# the other) is the shape this codebase treats as a bug, so there is ONE:
# a function that touches a global checks a flag word and runs the initializer if
# the flag is clear.
#
# It is correct for the reason the rest of this backend's model is correct: a
# formal program is single-threaded (coroutines lower as plain functions, see
# `arm64_codegen.compile`), so "check the flag, then fill" cannot interleave.
# And it costs one load and one branch in each function that reads a global,
# which is the same order as the access itself.


def function_touches_globals(fn) -> bool:
    """True when `fn` reads or writes any module global.

    Asked per function, and the answer decides whether the lazy-init prologue is
    emitted at all: a function that cannot observe a global cannot need its
    value filled in, and paying a branch there would be a cost on every call for
    nothing."""
    table = module_slots()
    if not table:
        return False
    for node in iter_nodes(getattr(fn, "body", None) or []):
        if isinstance(node, F.IdentExpr) and node.name in table:
            return True
    return False


def functions_writing_globals(functions) -> dict:
    """`{name: [functions that write it]}` for every `global NAME` in the module.

    The DECLARATION is what makes a write a write: a function body that assigns
    a name it has not declared global binds a LOCAL of that name, which shadows
    the module's — the rule the folding path above already depends on. So this
    reads `GlobalStmt` and not the assignment targets, and the difference is the
    whole of the answer. A module with `G = 5` and a function that assigns `G`
    locally is a READ-ONLY global and is still folded; the same module with
    `global G` above that assignment has a real slot.

    The whole body is walked rather than the top-level statements because
    `global G` inside an `if` is still a declaration for the rest of the
    function, and a `try` around the declaration is not a reason to call the
    name local. Mojo's own rule is the same: `global` is a compile-time
    declaration of the name's scope, not a runtime statement."""
    out = {}
    for fn in (functions or []):
        for node in iter_nodes(getattr(fn, "body", None) or []):
            if not isinstance(node, F.GlobalStmt):
                continue
            for name in (node.names or []):
                out.setdefault(name, []).append(fn)
    return out


def module_body_store_names(functions) -> set:
    """The names the MODULE BODY assigns — which are the MODULE's own writes.

    The counterpart of `functions_writing_globals`, and the same fact read from
    the other end. `G = compute()` at file level is a store of `G`, and the
    only function that runs it is the synthetic one the module's top level is
    compiled as (`_module_body_function`), so `G` is written by exactly one
    function in the image and that function is the ENTRY.

    This is why the module body cannot be scoped like an ordinary function.
    Read as one, `G` is a local of `__module_body__`, so `module_slot_for` sends
    its reads and writes to a register — and a register dies with the body,
    which is the whole of `bugs/formal/FORMAL_module_state_no_storage.md`'s subject: the
    module's own value computed somewhere nobody can read it. The name needs the
    module's `__DATA` slot for the same reason a name written through
    `global G` inside a function needs one, and it needs it for the same
    reason: **the writer and the reader are different functions and only one of
    them is on the stack at a time.**

    Asked with the SAME walk the register allocator uses (`bound_names_in_order`),
    so "which names the body binds" has one answer here and in both emitters.
    It is deliberately NOT filtered to names with a slot: that filter is
    `global_names_bound_in`'s, and it is what leaves a body-local with no module
    home — a `for` target, a `with` alias, an ordinary temporary of a top-level
    statement — in a register, where it belongs.
    """
    bodies = [f for f in (functions or [])
              if getattr(f, "name", None) == MODULE_BODY_NAME]
    if not bodies:
        return set()
    from mojo.middle.boundnames import bound_names_in_order
    out = set()
    for fn in bodies:
        try:
            out |= {n for n in bound_names_in_order(
                getattr(fn, "body", None) or [], []) if isinstance(n, str)}
        except Exception:
            continue
    return out


def module_body_store_sites(functions) -> dict:
    """`{name: BodyStoreSite}` — what the module body can reach before a store.

    The ORDER facts that decide whether a body-filled slot's value is there yet
    when a read happens, and they are order facts plus a transitive closure
    rather than a whole-program analysis because of one measured property of
    this path: **the module body IS the entry** (`entry_function` rule 1), so
    nothing in the image runs before the module's first statement, and the only
    thing that can put a function onto the stack is a CALL the body makes.

    So "is this read premature" is "can this reader run before the store", and
    the body is a straight line of statements, which makes it two closures of
    the same call graph:

      * `earlier` — every function this unit defines reachable from a call in a
        statement ABOVE the store. A reader in that set can run before the slot
        holds anything, whatever order the rest of the body is in.
      * `self_reaches` — the same closure from the store statement's OWN value.
        `G = compute()` runs `compute` before the store completes, so a
        `compute` that reads `G` is the same hazard one statement higher, and a
        direct-callee check misses it.

    `opaque_above` / `opaque_self` are the two shapes no closure can answer: a
    call through a value rather than through a function of this unit, or through
    one rooted at a name this unit binds (`S.helper()`, `h.method()`). Both may
    be this unit's own code, so both are treated as reaching everything — the
    conservative direction, and the only one that can produce a refusal rather
    than a wrong number.

    Why a closure and not "the first call in the body": the first call is almost
    always the store of ANOTHER computed global, and refusing every reader below
    it would refuse `NUMS = make()` followed by `NAME = greet()` with both read
    from `main` — a correct program whose readers `main` reaches from nothing
    the body calls before the assignment. A reader's NAME is the question, and a
    closure answers it.

    `_call_reach` splits a call three ways, and the split is what keeps the other
    image out of this: `REPO = os.path.dirname(HERE)` roots at `os`, which is
    another IMAGE, and code in another image has no symbol for this unit's
    `__DATA` slot — so it cannot read the value however deep the chain goes, and
    a call like that must not make every later reader look premature."""
    bodies = [f for f in (functions or [])
              if getattr(f, "name", None) == MODULE_BODY_NAME]
    if not bodies:
        return {}
    from mojo.middle.boundnames import bound_names_in_order
    # `{name: [FunctionDef]}` for a unit's own definitions, because Mojo
    # overloads are ordinary (`def reversed[...]` appears eight times in
    # std/builtin/reversed.mojo) and a closure has to follow the same name-keyed
    # question `entry_function` and `_check_frame_escapes` already ask: every
    # definition of one name is reachable from a call to it.
    by_name: dict = {}
    for fn in (functions or []):
        nm = getattr(fn, "name", None)
        if nm:
            by_name.setdefault(nm, []).append(fn)
    # Every name this unit BINDS, so a call's base can be told from a module's.
    unit_bound = set()
    for fn in (functions or []):
        params = [p[0] if isinstance(p, (list, tuple)) else getattr(p, "name", None)
                  for p in (getattr(fn, "params", None) or [])]
        unit_bound |= {p for p in params if isinstance(p, str)}
        try:
            unit_bound |= {n for n in bound_names_in_order(
                getattr(fn, "body", None) or [], []) if isinstance(n, str)}
        except Exception:
            continue

    def calls_of(fn) -> set:
        out = set()
        for node in iter_nodes(getattr(fn, "body", None) or []):
            if isinstance(node, F.CallExpr) and isinstance(node.func,
                                                           F.IdentExpr):
                out.add(node.func.name)
        return out

    def _call_reach(call) -> str:
        """Can this call reach a function of THIS unit, so could it read us?

        `"follow"` — a bare-name callee, which the closures walk, and which is
        harmless when this unit defines no such name (a builtin or an unbound
        symbol, and neither can read this unit's slot).

        `"safe"` — a dotted callee rooted at a name this unit does NOT bind, i.e.
        another image's namespace. Nothing over there has a symbol for this
        unit's slot.

        `"opaque"` — a dotted callee rooted at a name this unit binds (a struct's
        static method, a local receiver), or a callee this path cannot decompose
        at all (a subscript, a call result). Both may be this unit's own code.
        """
        func = getattr(call, "func", None)
        if isinstance(func, F.IdentExpr):
            return "follow"
        if isinstance(func, F.MemberExpr):
            node = func
            while isinstance(node, F.MemberExpr):
                node = getattr(node, "obj", None)
            if isinstance(node, F.IdentExpr):
                return "opaque" if node.name in unit_bound else "safe"
        return "opaque"

    def _split(stmt):
        """`(callee names, opaque?)` for one body statement."""
        follow, opaque = set(), False
        for node in iter_nodes(stmt):
            if not isinstance(node, F.CallExpr):
                continue
            reach = _call_reach(node)
            if reach == "follow":
                follow.add(node.func.name)
            elif reach == "opaque":
                opaque = True
        return follow, opaque

    def _closure(frontier):
        """Every name reachable from `frontier` in this unit's call graph."""
        reaches, frontier = set(), set(frontier)
        while frontier:
            nxt = frontier - reaches
            if not nxt:
                break
            reaches |= nxt
            frontier = set()
            for callee in nxt:
                for target in by_name.get(callee, ()):
                    frontier |= calls_of(target)
        return reaches

    out: dict = {}
    for fn in bodies:
        stmts = list(getattr(fn, "body", None) or [])
        calls = [_split(s) for s in stmts]
        # Running union of the calls above each statement, so `earlier` is a
        # lookup rather than a re-walk per name. Two module-level computed
        # globals in one file is the ordinary case and there can be a handful.
        above_calls, above_opaque = set(), False
        running_calls, running_opaque = set(), False
        for i, (follow, opaque) in enumerate(calls):
            above_calls, above_opaque = set(running_calls), running_opaque
            running_calls |= follow
            running_opaque = running_opaque or opaque
            name = _module_binding_name(stmts[i])
            if name is None or name in out:
                continue
            follow_here, opaque_here = follow, opaque
            out[name] = BodyStoreSite(
                i, _closure(above_calls), above_opaque,
                _closure(follow_here), opaque_here)
    return out


class BodyStoreSite:
    """What the module body can reach before it stores one name.

    Five fields, and the only reader is `module_slot_readable_in` — kept
    together in a record rather than a tuple because "a reader in this set" and
    "this call cannot be followed" are the two halves of one question and a
    caller that had to remember which is which is a caller that will eventually
    read only one."""

    __slots__ = ("store_at", "earlier", "opaque_above", "self_reaches",
                 "opaque_self")

    def __init__(self, store_at: int, earlier: set, opaque_above: bool,
                 self_reaches: set, opaque_self: bool):
        self.store_at = store_at
        self.earlier = earlier
        self.opaque_above = opaque_above
        self.self_reaches = self_reaches
        self.opaque_self = opaque_self


def global_names_bound_in(fn) -> set:
    """The names `fn` declares `global`, which are therefore NOT its locals.

    Read by both backends' local collection. A `global G` name must not be given
    a register or a spill slot in the declaring function: the register would be
    a SECOND home for a word that already has one in `__DATA`, and the read would
    pick whichever the emitter consulted first. That is not a theoretical
    disagreement — it is the exact shape of the X19/zero fall-through this file
    exists to prevent, reintroduced through the allocator instead of the
    emitter.

    **The MODULE BODY is the second spelling of the same declaration**, and it is
    here for the reason `module_body_store_names` gives: a file-level
    `G = compute()` is a write of `G` by the MODULE, so `G` is not a local of
    `__module_body__` — its home is the module's `__DATA`, exactly as a
    `global G` inside a function has. Gated on the name HAVING a slot, which is
    what keeps a body-local with no module home (a `for` target, a `with` alias,
    an ordinary temporary of a top-level statement) out of this and in a
    register."""
    out = {n for n in functions_writing_globals([fn])}
    if getattr(fn, "name", None) == MODULE_BODY_NAME:
        out |= {n for n in module_body_store_names([fn])
                if module_slot(n) is not None}
    return out


def module_slot_for(name: str, local_names):
    """The `__DATA` slot a bare `name` reads or writes in ONE function, or None.

    The scoping decision, in one place because both backends have to make it and
    a rule written twice is a rule that will be written two ways. `local_names`
    is the emitting function's local set — `_collect_var_names` is the shared
    allocation order, so the register allocator and this cannot disagree.

    CPython's rule for a bare name inside a function:

      * bound in THIS function, with no `global` → a local, full stop;
      * declared `global` here → the module's storage;
      * neither → a free variable, so it resolves in module scope and reads the
        module's storage.

    The middle case is the one that has to get both ends right, and keying on
    either end alone gets one of them wrong:

        G = 5

        def bump_local():
            G = G + 1        # NO `global` — a LOCAL; the module stays 5

        def read_only():
            return G         # no assignment anywhere — the MODULE's 5

        def set_it():
            global G
            G = 100

    Gating on "does the name have a slot" sends `bump_local`'s read and write to
    `__DATA`, and the module's 5 becomes 6. Gating on "did this function declare
    it `global`" sends `read_only`'s read to a dead register, and the build
    refuses with "has no home". So the gate is the local set, and `local_names`
    already excludes the declared globals, which answers both ends at once.

    THE THIRD CASE IS NOT A GAP, and it is the one a reader is most likely to
    try to "fix" by making the read module-scoped:

        G = 5
        def bump():
            G = G + 1        # the right-hand G is a LOCAL read

    Python decides a name's scope at COMPILE time from the whole body, so `G` is
    local throughout `bump` and the right-hand read raises `UnboundLocalError` —
    it does NOT read the module's 5. Verified against CPython:

        $ python3 -c 'G = 5
        > def bump():
        >     G = G + 1
        > bump()'
        UnboundLocalError: cannot access local variable 'G' where it is not
        associated with a value

    So this function returning a slot for that read — had nothing refused the
    program first — would compute a 6 CPython never produces. `read_before_store`
    is what refuses it, and it is the general rule rather than a special case
    here; `test_formal_globals.py` pins that it fires for this shape on both
    architectures, because the read name is a real module global and the
    alternative was a live `__DATA` load rather than a dead register.

    (The Mojo interpreter disagrees here — `fire.py run` prints 6. The images'
    contract is CPython's semantics, and a program CPython raises on has no
    reference answer to be lowered to.)"""
    if name in local_names:
        return None
    return module_slot(name)


def module_global_method_refusal(obj, method: str, local_names,
                                 fn_name=None) -> str | None:
    """Why `NAME.method(...)` on a module-level name cannot be lowered, or None.

    The call lowering decides `recv.m(...)` is a METHOD call rather than a
    dotted EXTERN call in `_is_value_receiver`, which answers for a local, a
    string literal, a frame slot and a call result. A module global is none of
    those: its value is in the image's `__DATA` and its name is not one of the
    function's own register/spill homes, so the receiver test answered False
    and the chain fell through to `_callee_symbol`. That flattened `H.append`
    to a dotted name, the extern path emitted a call to a symbol no library
    defines, and the build failed four stages later with the LINK AUDIT's
    sentence — "the image would bind `H.append` and nothing provides it" —
    which is a true statement about the link line and a false one about the
    program.

    Measured, both architectures, on the program below: `G = G + 1` through
    `global G`, `NUMS[1] = 99` and `len(NUMS)` all build and answer, and
    `H.append(v)` is refused as the dangling symbol. CPython answers `p=4 q=4`.

        G = 0
        H = [1, 2, 3]

        def push(v):
            global H
            H.append(v)
            return len(H)

    This is the REFUSAL half of the choice: the construct has no lowering (a
    module-level list whose blob is static data would need an in-place append
    through the slot, a capability change with its own re-sweep), and a
    sentence naming the construct is worth more than one naming the linker. It
    is asked at the same point in both emitters, from this one reader, so the
    two architectures cannot describe one call differently.

    A LOCAL is not this: `local_names` is the same scoping decision
    `module_slot_for` makes, so `self.m(...)`, a parameter and a name bound in
    the function all answer None here and keep their own paths.
    """
    name = getattr(obj, "name", None)
    if not isinstance(obj, F.IdentExpr) or not name:
        return None
    if name in set(local_names or ()):
        return None
    if module_slot_for(name, local_names) is None:
        return None
    who = f"{fn_name}: " if fn_name else ""
    kind = global_slot_kind(name)
    if kind == STR_KIND:
        what = "a module-level STRING"
    elif isinstance(kind, str) and kind.startswith(LIST_PREFIX):
        what = "a module-level CONTAINER"
    else:
        what = "a module-level name"
    return (f"{who}{name!r} is {what} of this module, so its value lives in "
            f"the image's `__DATA` and not in this function's frame. A METHOD "
            f"call on a module global is not lowered on this path: "
            f"`{name}.{method}(...)` has no receiver in a frame and no symbol "
            f"in any library, so the call would be emitted against a symbol "
            f"spelled `{name}.{method}`. What DOES lower on a module global is "
            f"a plain read/write of a word, and for a container a subscript "
            f"(`{name}[i]`, `{name}[i] = v`) and `len({name})`. Give the "
            f"module an accessor (`def {name}_{method}(...): global {name}; "
            f"{name}.{method}(...)`) and call that: the body of an accessor "
            f"reaches the slot the ordinary way, and the call reaches code, "
            f"which is what a caller can bind")


def _module_container_entry_literals(stmts, functions, candidates: dict) -> dict:
    """`{name: literal-node}` for the module containers a function entry may assume.

    `candidates` is `{name: (initializer statement, literal node)}` — the
    static-container slots `collect_global_slots` found. A name is dropped when
    it occurs ANYWHERE in the unit other than as its own initializer's TARGET or
    as the ITERABLE of a `for`, because those two are the only positions in which
    a container is neither stored nor passed where a callee could change it.

    This is the half `mutable`/`filled_by_body` do not cover: both key on a
    STORE, and a container changes in place without one — `XS.append(1)`,
    `helper(XS)` for a helper that mutates, `XS[i] = v`. The store spellings that
    this path lowers (`XS[0] = 9` at module level, or under `global XS`) are
    already `mutable`/`filled_by_body`, so this catches the RESIDUAL, the
    method-call spelling the bind audit refuses later: with the fact seated
    first, `XS = [] / XS.append(1) / for q in XS` reported "`q` is read before
    anything stores it", a sentence FALSE about a program CPython runs and less
    useful than the real finding (`XS.append` has no provider).

    Conservative in the direction that only ever WITHHOLDS a fact, because a
    false refusal is the error this analysis must not make: a name used only as
    a `for` iterable is seated, and any other mention (`len(XS)`, `print(XS)`,
    `XS + ys`) withholds it rather than reason about whether that particular use
    mutates. One walk over the module's own statements and every function body,
    through `iter_nodes_with_parent`, because the position is the whole question
    and a bare `iter_nodes` cannot see it.
    """
    safe = {name: lit for name, (_stmt, lit) in candidates.items()}
    if not safe:
        return {}
    seen: set = set()

    def note(node, parent) -> None:
        if not isinstance(node, F.IdentExpr) or node.name not in safe:
            return
        if node.name in seen:
            return
        _stmt, literal = candidates[node.name]
        if getattr(parent, "target", None) is node \
                and getattr(parent, "value", None) is literal:
            return
        if isinstance(parent, F.ForStmt) \
                and getattr(parent, "iterable", None) is node:
            return
        seen.add(node.name)
        del safe[node.name]

    for node, parent in iter_nodes_with_parent(stmts or []):
        note(node, parent)
    for fn in (functions or []):
        for node, parent in iter_nodes_with_parent(getattr(fn, "body", None) or []):
            note(node, parent)
    return safe


def collect_global_slots(stmts: list, functions: list, int_names=(),
                         string_names=(), dict_names=(),
                         frame_slots: dict = None) -> dict:
    """`{name: GlobalSlot}` for every module-level name that needs STORAGE.

    The question is one — "can the build FOLD this name, or does something in
    this image change it while the program runs?" — with three answers, and the
    storage table is what serves the last two:

      * **a function WRITES it.** `global G; G = G + 1` changes G's value while
        the program runs, so there is no one value to substitute at the reads.
        This was the case the folding path was already correct to refuse, and it
        was refused by NAME rather than by a mechanism. Measured before this
        existed: `G = 5` with `bump()` called twice printed `G=5` where CPython
        prints `G=7` — a silently wrong answer, because the read was the folded
        5 and the write went into a register nothing else named.
      * **its value is a CONTAINER literal, or a repetition of one.** `[1,2,3]`
        is not a value the substitution path can express at all — there is no
        literal to put at the read — but it IS static data: the blob is a flat
        run of words whose first word is the count, so the linker can place it in
        `__DATA` and the slot can hold its address. `NUMS = [10,20,30]` read from
        a function is the case `bugs/formal/FORMAL_module_state_no_storage.md` §1
        measured as the first one, and it builds and runs correctly now.
        `[0] * 624` is the same value as the written-out literal, and
        `_is_static_container` asks the same question of it — see
        `_repeated_container` for why missing that spelling was a silent wrong
        image rather than a refusal.
      * **the MODULE BODY writes it.** `G = compute()` at file level is the
        module's own top-level statement, compiled as the synthetic
        `__module_body__` and run before anything else — so it is a store, not
        an image initializer, and the slot it needs is filled by that store. This
        is the third of the doc's "three things a slot cannot be" that turned out
        to be two: a value computed before the program runs has no STATIC
        initializer, but it does have a module-level statement that computes it,
        and that statement is already the entry point.
      * **the IMAGE holds a FRAME of its own** — `frame_slots`, which
        `prepare_module_frame_slots` decided and handed over rather than this
        function re-deriving. That is the fourth bullet and it is NOT a third
        "where the value comes from": the frame is static data like the
        container blob above, so the slot is written by `build_data_image` like
        any other address and `filled_by_body` is FALSE. Passing the table in is
        what keeps one decision: that function also removed the module body's
        store, and a name this function decided to fill by the body while that
        one had decided the image held it would be a slot with two owners.

    Anything else is still folded and still needs no storage: an int, a bool or a
    string whose value is a literal, with nothing writing it. A name in NEITHER
    set is not in the table, and `module_global_refusal` is what says why.

    **All three buckets are in the table, so the table alone does not say which
    is which**, and the second of them is the one that is easy to get wrong: the
    container-literal bucket has a slot for a reason that has nothing to do with a
    writer (the blob is static data the linker places), so reading "has a slot" as
    "is a variable" makes a constant a variable. `GlobalSlot.mutable` is the
    distinction, set here because this is the only function holding both the
    statements and the bodies.

    Reads the module's own statement list for the INITIALIZER and the function
    bodies for the WRITES, because the two live in different places: the value is
    stated once, at module level, and the writes are stated inside the bodies.

    `int_names` / `string_names` are `formal.types`' annotation vocabularies,
    taken from the caller for the reason `declared_type_kind` takes them from the
    caller: the two backends must not answer "what does this annotation mean"
    from two private lists, and a default of empty leaves the answer the
    conservative one rather than a guess. `dict_names` is the third member of the
    same vocabulary, and the reason it is a separate argument is
    `_body_store_shape`: a KIND cannot say "dict" (every container is one word
    here, and `declared_type_kind` answers all four with the bare list prefix),
    while a SUBSCRIPT has to. They are read for exactly one name: a slot the
    module body fills by a call.

    ORDER is the order the names are first declared at module level, so the
    layout is a function of the source rather than of dictionary iteration and
    two builds of the same file produce the same image."""
    written = functions_writing_globals(functions)
    body_written = module_body_store_names(functions)
    body_sites = module_body_store_sites(functions)
    rets = function_return_types(functions)
    # `{name: [FunctionDef]}` for the definitions of a name, because the
    # ELEMENT question `_body_store_shape` asks is a question about every
    # definition of the callee and not about the last one — `std/builtin/reversed`
    # is defined eight times over and Mojo overloads are ordinary. Same name-keyed
    # shape `module_body_store_sites` builds, for the same reason.
    by_name: dict = {}
    for fn in (functions or []):
        nm = getattr(fn, "name", None)
        if nm:
            by_name.setdefault(nm, []).append(fn)
    frame_slots = frame_slots or {}
    finals: dict = {}
    order: list = []
    for stmt in (stmts or []):
        if isinstance(stmt, (F.ImportStmt, F.FromImportStmt)):
            continue
        name = _module_binding_name(stmt)
        if name is None:
            continue
        value = getattr(stmt, "value", None)
        is_frame = name in frame_slots
        filled_by_body = (name in body_written and not is_frame
                          and not _is_static_container(value))
        if name not in written and not filled_by_body \
                and not is_frame and not _is_static_container(value):
            continue
        if name not in finals:
            order.append(name)
        finals[name] = stmt
    # The container literals a FUNCTION's entry may assume: the static-container
    # slots, minus every name any statement uses in a position that could mutate
    # the value in place. One computation for the whole unit and read back per
    # slot, because `_module_container_entry_literals` is the only place with the
    # statements and the bodies in hand — see its own docstring.
    entry_containers = _module_container_entry_literals(
        stmts, functions,
        {name: (finals[name], getattr(finals[name], "value", None))
         for name in order
         if _is_static_container(getattr(finals[name], "value", None))})
    slots = {}
    for index, name in enumerate(order):
        stmt = finals[name]
        value = getattr(stmt, "value", None)
        kind, is_dict = _body_store_shape(value, by_name, rets, int_names,
                                          string_names, dict_names)
        frame = frame_slots.get(name)
        init = (("frame", frame[0], frame[1]) if frame is not None
                else _static_initializer(value))
        slots[name] = GlobalSlot(name, index, init,
                                 site=stmt,
                                 filled_by_body=name in body_written
                                 and frame is None,
                                 body_site=body_sites.get(name),
                                 kind=kind, is_dict=is_dict,
                                 mutable=(name in written
                                          or name in body_written),
                                 entry_literal=entry_containers.get(name))
    return slots


def _body_store_shape(value, by_name: dict, rets: dict, int_names, string_names,
                      dict_names):
    """`(kind, is_dict)` for a module-level CALL's value, from its CALLEE.

    The third source of a value's shape, beside a folded literal and a container
    literal, and it completes the set: a name bound at module level to
    `compute()` is stored by the module body, and the only thing that says what
    lands in the slot is the call — so the call's DECLARED return type says it,
    which is the same evidence `declared_type_kind` reads everywhere else and the
    same discipline: a callee this unit does not define, or one with no
    annotation, claims nothing.

    A `List[Int]` answer is the bare `LIST_PREFIX` rather than `list:<elem>`
    unless the callee's own RETURNS pin an element, which is the one upgrade
    `declared_type_kind` cannot make (it maps a blob annotation to a blob without
    reading its element, because an annotation is a statement about a TYPE and
    the element question is asked of a value). Both backends have always
    answered that question the other way round — `_callee_kind` takes the
    annotation for a scalar and the RETURN STATEMENTS for everything else — so
    `def make() -> List[Int]: return [3, 14, 0]` has been `list:int` for a LOCAL
    bound from it since before a module-level slot could exist at all, and
    `print(l[0])` lowering while `print(L[0])` was refused is what that costs.
    `_callee_blob_elem_kind` is the same question asked of the same evidence for
    the one spelling that had no `ValueKinds`, and unanimity over every
    definition of the callee is what keeps it from being a guess.

    `is_dict` is the half a kind cannot carry, and it is asked SEPARATELY rather
    than by widening the kind vocabulary because the four container annotations
    are one representation: `List[Int]`, `Tuple[Int, Int]`, `Set[Int]` and
    `Dict[String, Int]` are all a bare `char *`-shaped word, so a kind that
    said "dict" would be a lie about the other three. What says it is the
    annotation's BASE NAME, through the one `formal.types` vocabulary both
    backends share (`DICT_TYPE_NAMES`), which is the same evidence
    `global_slot_is_dict` reads off a dict LITERAL's initializer. A callee that
    declares NOTHING claims nothing here either, so the dict-vs-sequence question
    stays refused rather than guessed for the same reason the kind does.

    Asked only of a bare `CallExpr` to a name. Anything else — a binop, a
    subscript, a dotted call into another image — claims nothing rather than
    being guessed at, for the reason every other kind hook in this file
    underwrites deliberately."""
    if not isinstance(value, F.CallExpr) or not isinstance(value.func,
                                                           F.IdentExpr):
        return None, False
    callee = value.func.name
    ann = rets.get(callee)
    if not ann:
        return None, False
    base = annotation_base_name(ann)
    kind = declared_type_kind(ann, int_names, string_names, None)
    if kind == list_kind(None):
        elem = _callee_blob_elem_kind(by_name.get(callee), int_names,
                                      string_names)
        if elem is not None:
            kind = list_kind(elem)
    return kind, (base is not None and base in dict_names)


def _callee_blob_elem_kind(candidates, int_names, string_names):
    """The element kind the callee's own `return` statements state, or None.

    `ValueKinds.return_kind` for a callee of this unit, read WITHOUT the
    `func_kind` hook, and that omission is the safety argument rather than a
    shortcut: the hook resolves a call in a return position by recursing into the
    callee, so a no-hook reading of `def a() -> List[Int]: return b()` is a word
    where a hooked one would be `list:str`. Undecidable is the direction that
    refuses, and a bare `LIST_PREFIX` is exactly the answer a container of
    unstated elements already gets — so the one shape this gets less precise
    about is the one that was already refused.

    UNANIMITY over every definition of the name, or nothing, for the rule every
    flow-insensitive map in this file uses: a definition whose returns do not
    classify as a list at all disagrees with the others about what the call
    produces, and a module-level `L = make()` has to be one word for the whole
    program. `list_elem_kind` of a bare prefix is None, so a callee that agrees
    its elements are unstated also claims nothing, rather than claiming the bare
    prefix as if it were an element."""
    elems = set()
    for fn in (candidates or ()):
        kind = ValueKinds(fn, int_names=int_names,
                          string_names=string_names).return_kind
        if not is_list_kind(kind):
            return None
        elems.add(list_elem_kind(kind))
    return elems.pop() if len(elems) == 1 else None


def _is_container_literal(value) -> bool:
    """True for a container literal, which is a blob rather than a foldable value.

    A `dict` counts: its blob is `[npairs][k0][v0]…`, the same flat-word shape a
    list's is (`arm64_codegen._emit_dict`), so it is storage-shaped too. Whether
    this particular literal's ELEMENTS are static is a separate question, asked
    by `_static_container_words` — this only asks whether the shape is one a
    `__DATA` slot can point at."""
    return isinstance(value, (F.ListExpr, F.TupleExpr, F.SetExpr, F.DictExpr))


def _repeated_container(value):
    """`(container, count)` for a container REPETITION `[e0, e1] * N`, or None.

    `[0] * 4` IS `[0, 0, 0, 0]`: the repetition evaluates to a fresh container
    of `N` copies, and a module-level binding to one is the same static data a
    written-out literal is. That is the spelling this exists for — a 624-word
    table is `[0] * 624` and not 624 commas in the source — and the failure of
    not recognising it is a SILENT one rather than a refusal: with the
    repetition unclassified, `collect_global_slots` gave it no slot and
    `module_body` kept the store, so `__module_body__` became the entry point,
    `main` was never called, and the image printed nothing and exited 0. That is
    the same failure `_is_image_initialized`'s docstring records for `NUMS =
    [10, 20, 30]`, one spelling over.

    Either operand order is accepted, because `4 * [0]` is the same container.
    `N` must be a word this can read (an int literal, or a unary sign of one),
    and a count or element this cannot compute answers None — the caller's
    fallbacks then refuse rather than guess, which is deliberately NOT a partial
    expansion."""
    if not isinstance(value, F.BinaryOp) or value.op != "*":
        return None
    for container, count in ((value.left, value.right),
                             (value.right, value.left)):
        if isinstance(container, (F.ListExpr, F.TupleExpr, F.SetExpr)):
            n = _static_word(count)
            if isinstance(n, int) and n >= 0:
                return container, n
    return None


def _is_static_container(value) -> bool:
    """True for a value the linker can place as a container blob in `__DATA`.

    A container literal (`_is_container_literal`) OR a repetition of one
    (`_repeated_container`), which is the wider question the module-slot and
    module-body paths have to ask: both are storage-shaped data and neither is a
    value the substitution path can fold. Kept beside `_is_container_literal`
    rather than widening it, because that predicate has a second reader —
    `ValueKinds._value_kind`, where "is a container" decides whether an
    unclassified local keeps its blob kind or falls to the word default — and a
    repetition local is bound by a `BinaryOp` that `kind_of` already answers, so
    widening it there would change a local's classification for no reason."""
    return _is_container_literal(value) or _repeated_container(value) is not None


# The names a `None` VALUE is spelled with, read as a bare name because that is
# how Python's parser leaves it: `None` in a container literal arrives as
# `IdentExpr("None")`, not as `F.NoneLiteral`, and `_static_word` had no arm for
# either — so a module-level table whose first element is `None` was reported as
# having an element "computed by a call". `NoneType` is here because it is the
# same value under its type name and a corpus that writes `NoneType` writes the
# same program; `Ellipsis` is deliberately NOT, because this path has no word for
# it and `...` as a container element should keep being refused.
_NONE_SPELLINGS = frozenset(("None", "NoneType"))


def _static_initializer(value):
    """The `init` tuple for a module-level binding's value, or `("unknown", _)`.

    Deliberately exhaustive over what a `__DATA` word can hold and honest about
    the rest. A value that lands on `("unknown", …)` gets a slot with no
    initializer, and `check_module_symbols` refuses to READ it by name — because
    a zero there would be a plausible-looking wrong number rather than a
    refusal, and this backend's whole discipline is that the second is the
    honest answer."""
    blob = _static_container_words(value)
    if blob is not None:
        return ("blob", _container_shape(value), blob)
    if isinstance(value, F.StringLiteral) and not getattr(value, "is_bytes", 0):
        return ("str", value.value)
    if isinstance(value, F.BoolLiteral):
        return ("int", 1 if value.value else 0)
    if isinstance(value, F.IntLiteral):
        n = _int_literal_value(value)
        if n is not None:
            return ("int", n)
    if isinstance(value, F.UnaryOp) and value.op in ("-", "+"):
        n = _static_word(value.operand)
        if n is not None:
            return ("int", -n if value.op == "-" else n)
    return ("unknown", None)




# ── A MODULE-LEVEL STRUCT VALUE, AS STATIC STORAGE ───────────────────────
#
# `X = Struct(...)` at file level is the one module-level binding whose value
# does not FIT IN A WORD, and the module body is what makes it awkward: the body
# compiles to `__module_body__`, a function, so the construction reserves a block
# in THAT activation and the value is the address of that block — so the store
# `X = <address>` leaves in `__DATA` is an address into a frame the body has
# already returned from by the time anything reads it. The read is therefore a
# dereference of reclaimed stack.
#
# The obvious repair is to teach the holder analysis that such a slot holds a
# frame address, and it is WRONG: the analysis would be right about the layout
# and wrong about the lifetime, so the refusal it currently raises would become a
# SIGSEGV. The repair that works is to move the STORAGE, not the analysis: build
# the frame in `__DATA`, where it lives as long as the process does, and let the
# slot hold its address like any other address-valued slot.
#
# So this section is about WHEN the frame can be written into the image at all.
# `module_frame_slot_initializer` decides it; `build_data_image` lays the words
# out; `prepare_module_frame_slots` removes the module body's now-redundant store.

def module_frame_slot_initializer(value, structs_by_name: dict):
    """`(struct name, [word, …])` for a module-level STRUCT CONSTRUCTION, or None.

    The frame `X = S()` needs in `__DATA`, one word per slot in
    `struct_frame_slots` order, or None when the value cannot be written before
    the program runs — in which case nothing changes and the old store-the-frame-
    address path (and its refusal) stands.

    **Four requirements, and each is a way the value could differ between the
    module body and a reader, which is the whole question.** A frame slot is
    read by functions the body never called, so a word that depended on the body
    would be a word that is not there.

      * the value is a construction of a struct this unit DECLARES, and that
        struct is FRAMED (more than one field, receiver by reference). A
        one-field struct's receiver IS its field, so its module-level value is a
        word and belongs to `("int", …)`-shaped handling, not to a frame; and a
        struct from another module is compiled over there, so its field layout is
        not a fact this unit holds.
      * the construction takes NO arguments. `S(3)`'s frame depends on `3`, which
        is a word this image can compute — but the shape that decides it is
        `__init__`'s parameter list and this path does not evaluate a call at
        image-build time. Zero arguments is the case where the frame is fully
        determined by the field initializers, which is the case
        `ModuleLoader()` and `Pair()` are.
      * every slot's initializer is a WORD this build can compute: the
        class-level default, else the value `__init__` assigns, else zero. A
        field assigned by a CALL (`self.items = load()`) has no word before the
        program runs, so the frame does not either — that is `("unknown", …)`
        again, and it is refused by the reader that already refuses it.
      * a field `__init__` assigns MORE THAN ONCE must assign the same word both
        times, or there is no single value to write. Unanimity rather than
        "the last one", because `__init__` is straight-line but this is the
        same discipline `struct_init_field_types` applies to the type.

    `_static_word` is the word vocabulary, and it is the SAME one
    `_lay_out_blob_words` consumes — which is why a frame is laid out by the
    blob writer rather than by a second implementation of "these words, in the
    trailing area, with the string and nested-blob fixups". One implementation
    of the word kinds is the point; a second copy is a refusal lifted on a word
    that is not the word the code reads.
    """
    if not isinstance(value, F.CallExpr):
        return None
    callee = call_callee_name(value.func)
    # `args` and `kwargs` are `CallExpr`'s two argument lists, and a
    # zero-argument construction is the only one whose frame this can write.
    if callee is None or value.args or value.kwargs:
        return None
    struct = (structs_by_name or {}).get(callee)
    if struct is None or not struct_is_framed(struct):
        return None
    assigned = _init_field_assignments(struct)
    words = []
    for name in struct_frame_slots(struct):
        nodes = list(assigned.get(name) or ())
        if not nodes:
            kind, payload = struct_field_default(struct, name,
                                                 structs_by_name)
            if kind == DEFAULT_OPAQUE:
                return None
            # `(DEFAULT_NONE, None)` is a fresh word of zeros and
            # `("int"/"string", x)` is the literal the class body wrote — both
            # are already words, which is why they are appended rather than
            # re-derived from the AST node this branch never looks at.
            if kind == DEFAULT_NONE:
                words.append(0)
            elif kind == DEFAULT_STRING:
                words.append(payload)
            else:
                words.append(int(payload))
            continue
        resolved = []
        for node in nodes:
            word = _static_word(node)
            if word is None:
                return None
            resolved.append(word)
        if any(w != resolved[0] for w in resolved[1:]):
            return None
        words.append(resolved[0])
    return (callee, words)


def prepare_module_frame_slots(stmts: list, functions: list,
                               structs_by_name: dict) -> dict:
    """`{name: (struct, [word, …])}` — the module-level values the IMAGE holds.

    And it REMOVES the module body's store of each one, which is the other half
    of the same decision and the half that makes the slot safe: the body would
    otherwise reserve a block in its own activation and store that address over
    the static one, which is exactly the lifetime defect the static frame
    removes. A name whose value the image already holds is not computed by the
    body, and the body is the only function whose top-level statement is that
    assignment.

    **Why the removal happens HERE and not at the module body, which is built
    much earlier.** The table it needs is `functions_writing_globals(functions)`,
    and the list it must ask is the FINAL one — a `global X` inside a lifted
    lambda or a flattened closure declares X a module global just as one inside a
    top-level function does, and a table built from the pre-rewrite list would not
    know. A frame slot that some function ASSIGNS is not a frame slot at all: the
    store would put whatever that function computed — an int, a container address,
    a fresh block address — into a word every reader dereferences as `struct`'s
    fields. So this runs after every rewrite, and the module body is edited in
    place rather than re-derived, because `module_body_store_sites`' `store_at` is
    a STATEMENT NUMBER and the sites are computed from the same `functions` a few
    lines later: dropping the statement here is what keeps that number the number
    the reader is looking at.

    **A body with nothing left to run is not a body, and this removes it.** Not a
    cosmetic step: `entry_function`'s rule 1 is "the module body first", so a body
    that exists but computes nothing is still the entry and `main` is never
    called. That is exactly the defect `module_body`'s `_is_image_initialized`
    exemption was written for, measured on `NUMS = [10, 20, 30]` above a `def
    main` — the image built, printed nothing and exited 0. There is no statement
    to exempt here because the body was already compiled, so the exemption is
    applied where the statement is: the statement goes, and a body that has only
    its synthesized `return 0` left goes with it. Removed from `functions` rather
    than left in the list, so `entry_function` falls through to `main` exactly as
    it does for a module that never had a body. Only when something else is left
    to be the entry — otherwise the list is empty and there is no image at all,
    which is `_extract_functions`' `synthetic` case and not this one's.

    Returns the table rather than publishing it, because `collect_global_slots`
    is the one that turns it into slots and there is nothing here that needs to
    survive the call.
    """
    written = functions_writing_globals(functions)
    bodies = [f for f in (functions or [])
              if getattr(f, "name", None) == MODULE_BODY_NAME]
    if not bodies:
        return {}
    out = {}
    for stmt in (stmts or []):
        if isinstance(stmt, (F.ImportStmt, F.FromImportStmt)):
            continue
        name = _module_binding_name(stmt)
        if name is None or name in written:
            continue
        frame = module_frame_slot_initializer(getattr(stmt, "value", None),
                                              structs_by_name)
        if frame is not None:
            out[name] = frame
    if not out:
        return {}
    for fn in bodies:
        fn.body = [s for s in (getattr(fn, "body", None) or [])
                   if _module_binding_name(s) not in out]
    # The ENTRY, for the reason the docstring gives. `_module_body_function`
    # appends exactly one `return 0` to whatever body it was given, and a
    # file-level `return` is refused before it gets there
    # (`_refuse_unlowerable_module_body`), so a body whose only remaining
    # statement is a `return` is one the image holds entirely. In place, so
    # `entry_function` sees the same list this pipeline returns — and guarded on
    # there being something else to be the entry, because a list with nothing in
    # it is not a program.
    emptied = [fn for fn in bodies
               if all(isinstance(s, F.ReturnStmt) for s in (fn.body or []))]
    if emptied and len(functions) > len(emptied):
        functions[:] = [f for f in functions
                        if not any(f is e for e in emptied)]
    return out


def _int_literal_value(node):
    """The int an `IntLiteral` carries, or None if it is not one."""
    try:
        return int(node.value)
    except (TypeError, ValueError):
        return None


def _container_shape(value) -> str:
    """`"dict"` or `"sequence"`, the two blob layouts there are.

    One word, because the two are the whole of what a subscript of the container
    has to know: `[count][e0][e1]…` against `[npairs][k0][v0]…`, and a pair blob
    indexed by a key is a SCAN (`arm64_codegen._emit_dict_lookup_addr`) while a
    sequence's is an address computation. Carried in the slot's initializer
    rather than re-derived at each use, because a use site has only the NAME and
    the name's value is what says which of the two it is — and getting it wrong
    is not a refusal: a pair blob indexed with a key as if it were an element
    offset reads a word at a nonsense address."""
    return "dict" if isinstance(value, F.DictExpr) else "sequence"


class StaticNestedBlob:
    """The words of a NESTED container literal, standing in for one outer word.

    One word holds a pointer to a blob, so `L = [[1, 2], [3]]` is a blob of two
    words and each of those words is a pointer to a blob of its own. `int` and
    `str` were the two word kinds a flat run carried and this is the third: a
    word whose content is another `words` list, which `build_data_image` lays
    out as its own blob in the same trailing area and points at with one more
    entry in the same `fixups` list the outer blob already used.

    A class rather than a bare nested list, because `int` and `str` are the other
    two word kinds and the three are told apart by their type in exactly one
    place (`_lay_out_blob_words`). A nested list would then be indistinguishable
    from a word the build cannot compute — which is the answer that has to stay
    reachable, and which `("unknown", …)` is how the refusal says so."""

    __slots__ = ("words",)

    def __init__(self, words):
        self.words = words

    def __repr__(self):
        return f"StaticNestedBlob({self.words!r})"


def _static_container_words(value):
    """The blob words a module-level container literal is, or None if not one.

    A container on this path is a flat blob of 8-byte words whose FIRST word is
    the count (`[count][e0][e1]…`; `[npairs][k0][v0]…` for a dict — see
    `arm64_codegen._emit_list` / `_emit_dict`, and `x86_64_codegen`'s twins for
    the same layout). So a module-level container literal whose elements are all
    INTEGERS is a byte string the linker can place in `__DATA` directly, and the
    slot holds its address: the blob then has STATIC STORAGE DURATION, which is
    exactly what a frame blob does not have and exactly what a global needs.

    A REPETITION of a container (`[e0, e1] * N`) is the same static data — it is
    the element list written `N` times and nothing about it is computed at run
    time — so it is expanded here rather than left to the caller. That is the
    spelling a table too long to write out uses, and `_repeated_container` is the
    one place that decides when the count and elements are all readable.

    A word may be a STRING rather than an int, and that is the whole of the
    second kind: a string on this path is a `char *`, so a string element is a
    word holding a pointer, and the pointer is filled in from code at first call
    (`GlobalDataImage.string_cells` for why the target is the interned literal
    and not a copy here). A dict is a DIFFERENT shape from a list — pairs, not
    elements — so its keys and values are read with their own accessor and
    interleaved, and asking one for the other is a silent wrong answer.

    A word may also be a `StaticNestedBlob`, which is this same function applied
    one level down: a nested container element IS a word — a pointer to a blob —
    and what was missing was never a word to put there but the second level of
    fixups, which `build_data_image` now lays out beside the first. The recursion
    terminates on the shape of the SOURCE rather than on a depth argument, since
    a literal cannot contain itself.

    Anything else is refused rather than half-done: an element computed by a call
    is a word this cannot compute, and a container that is not all-words has no
    initializer to write into the slot. That is said by name from
    `static_initializer_refusal_reason`.

    **The reporter is read from `_MISSING_REPORTER`, and it has to be read.** The
    two arms below append the element they could not answer to a local named
    `missing`, which was this function's own parameter until the walk was
    refactored into a `ContextVar` so the recursion needs no out-parameter \u2014 and
    the parameter went while the two uses stayed. So a container literal with an
    element `_static_word` cannot answer raised `NameError: name 'missing' is not
    defined` out of the compiler, in BOTH the dict and the list arm, which is
    the worst of the two answers `container_element_without_a_word` exists to
    avoid: a diagnostic that cannot be built instead of a refusal. It was
    unreachable in every suite that ran, because the one caller that can reach it
    (`container_element_without_a_word`) was only added with the `ContextVar`.
    Read the context variable here, once, and both arms are the reporter's own
    shape again: `None` when nobody is listening, which is every call on the hot
    path, and the list a listener set when one is.
    """
    missing = _MISSING_REPORTER.get()
    repeated = _repeated_container(value)
    if repeated is not None:
        # `[e0, e1] * N` is the element LIST repeated, not one element: `[1, 2]
        # * 3` is `[1, 2, 1, 2, 1, 2]`. One `_static_word` call PER COPY, so a
        # nested container element is laid out as `count` separate blobs rather
        # than one shared by every pointer — a subscript store into one element
        # must not change the others.
        container, count = repeated
        elements = list(container.elements or [])
        words = [len(elements) * count]
        for _ in range(count):
            for el in elements:
                word = _static_word(el)
                if word is None:
                    return None
                words.append(word)
        return words
    if isinstance(value, F.DictExpr):
        words = []
        pairs = [p for p in (value.pairs or []) if len(p) >= 2]
        words.append(len(pairs))
        for pair in pairs:
            for cell in pair[:2]:
                word = _static_word(cell)
                if word is None:
                    if missing is not None:
                        missing.append(cell)
                    return None
                words.append(word)
        return words
    if not isinstance(value, (F.ListExpr, F.TupleExpr, F.SetExpr)):
        return None
    elements = list(value.elements or [])
    words = [len(elements)]
    for el in elements:
        word = _static_word(el)
        if word is None:
            if missing is not None:
                missing.append(el)
            return None
        words.append(word)
    return words


# The element `_static_container_words` could not answer, when somebody is
# listening. A context variable rather than an argument because the walk is
# recursive (a nested container is this same function one level down) and an
# out-parameter would have to be threaded through every level to say the same
# thing; `None` when nobody is, which is every call on the hot path.
_MISSING_REPORTER = ContextVar("formal_missing_element", default=None)


def container_element_without_a_word(value):
    """The element of a container literal `_static_word` cannot answer, or None.

    **This exists because the refusal it feeds named a CALL for every shape that
    reached it, and two of the three that still reach it have no call in them.**
    Measured on this tree, both architectures, before `_static_word` learned to
    fold: `TBL = [1 + 2, 3]`, `TBL = [7 // 2, 3]`, `TBL = [K, 3]` and
    `TBL = [1.5, 2]` were each refused as *"one of its elements is computed by a
    call"* — four programs with no call anywhere in them, and the first of those
    is arithmetic on two integer literals. Those four build now; what is left is a
    call (`[f(), 1]`), a name the build cannot fold (`[os.pi, 1]`, `[K, 1]` where
    `K` is imported rather than declared), and a value outside one 64-bit word
    (`[2 ** 64, 1]`), and only the first of the three is a call.

    So the walk is asked WHICH element it could not answer rather than only
    whether it could answer all of them, and the message quotes it. The reporter
    is a `ContextVar` so the recursion needs no extra argument and so a nested
    container's own missing element — the one a reader has to be sent to — wins
    over its parent's, which is what the inner walk reports last.
    """
    missing = []
    token = _MISSING_REPORTER.set(missing)
    try:
        _static_container_words(value)
    finally:
        _MISSING_REPORTER.reset(token)
    return missing[-1] if missing else None


def _static_word(node):
    """The word a container ELEMENT (or a unary sign of one) is, else None.

    An `int` for a number, the `str` itself for a string, a `StaticNestedBlob`
    for a container literal. The three are told apart by their type rather than
    by a tag because a formal value is one word and a word holds one of them;
    `int` is never a `str` here, so the test is exact. A bytes literal is
    deliberately NOT a string element: it is a numeric buffer rather than text,
    and nothing in this path reads one out of a container as a NUL-terminated
    string.

    **`None` is the fourth, and it is the word 0.** Both emitters already lower
    a `None` to zero — `arm64_codegen._emit_expr`'s `F.NoneLiteral` arm is
    `movz xd #0` and `x86_64_codegen`'s twin is the same constant — and the two
    SPELLINGS of it are the same word and are accepted as the same word
    everywhere else that reads one (`struct_init_shapes`'s own note says so:
    "`None` as a bare name, which is how Python's parser leaves it, and
    `NoneLiteral`, are the same word"). So a container literal holding `None` has
    a word for that element like any other.

    It did not, and the cost was a misdiagnosis rather than a gap: measured on
    this tree, `TBL = [(None, 7), (3, 9)]` read by a function was refused as
    **"one of its elements is computed by a call"** — about a literal, with no
    call anywhere in it — and the same refusal is what
    `tools/formal_proof_breadth.py`'s census records for
    `formal/arm64_proof_gen.py`'s `_STEP_CONDS` (50 entries, the first of them
    `(None, 0xd65f03c0)`) and for `gimple_codegen.py`'s `_SELFHOST_SIGS`. The
    element `_static_word` could not answer for was `None`, and the reason
    string picked by `static_initializer_refusal_reason` was the closest of its
    four rather than the right one.

    **THE SAME MISDIAGNOSIS, THREE ARMS FURTHER OUT, and this arm is the one that
    cost a corpus its `__DATA`.** Measured on this tree, every one of these was
    refused with that same sentence about a call, and none of them has a call in
    it:

        K = 5
        TBL = [1 + 2, K]      # arithmetic on two literals, and a constant
        TBL = [7 // 2, 3]     # a floor division of two literals
        TBL = [2 ** 10, 3]    # a power of two literals
        TBL = [1 << 4, 3]     # a shift of two literals
        TBL = [1.5, 2]        # a float LITERAL

    Every one of those is a word the build KNOWS, and the local spelling of each
    already works — `var xs = [1 + 2, 3]` builds, runs and answers `3 3` on both
    architectures — because a frame blob is built by INSTRUCTIONS that compute
    the element, and only the `__DATA` initializer has to compute it at BUILD
    time. So the gap was never a capability: it was this function asking four
    questions about a node's SHAPE (is it a literal? is it a sign? is it a
    container?) where the tree already has one folder that answers the fifth
    question — what does this expression COME TO — and whose answer is the same
    arithmetic the emitter emits.

    Three arms, each asking one existing reader rather than writing arithmetic
    here:

      * **an expression** → `fold_module_int_expr`, which is the folder both
        backends' module-constant path and `mojo/middle/comptime.py` already
        agree with, range-checked here against `_FOLD_INT_MIN`/`_FOLD_INT_MAX`
        because THAT is the caller's half of the contract (`fold_module_value`
        makes the same check for a whole module-level initializer). A folded
        value outside one word is refused rather than truncated: a `__DATA` word
        that is not a value the source has is the plausible wrong number this
        backend refuses everywhere else, and `2 ** 64` is exactly that.
      * **a float literal** → `float_literal_bits`, the one reader of a literal's
        IEEE-754 pattern both backends ask, as a SIGNED word: `_lay_out_blob_words`
        writes an int with `signed=True`, so an unsigned pattern above `2**63`
        would raise out of `to_bytes` — a compiler crash rather than a refusal —
        and the signed reading of the same 64 bits is the value a register
        holds.
      * **a name** → `module_constant_literal`, the read both backends and the
        substitution pass ask for a module-level constant's folded value. It is
        asked for the name alone, which is why a name this unit does not fold
        (`math.pi`, a `from … import K` alias) still answers None and keeps the
        refusal: the fold is the build's, not a guess.
    """
    if isinstance(node, F.StringLiteral) and not getattr(node, "is_bytes", 0):
        return node.value
    if isinstance(node, F.BoolLiteral):
        return 1 if node.value else 0
    if isinstance(node, F.IntLiteral):
        return _int_literal_value(node)
    if isinstance(node, F.NoneLiteral):
        return 0
    if isinstance(node, F.IdentExpr) and node.name in _NONE_SPELLINGS:
        return 0
    if isinstance(node, F.UnaryOp) and node.op in ("-", "+"):
        n = _static_word(node.operand)
        if isinstance(n, (str, StaticNestedBlob)):
            return None
        return None if n is None else (-n if node.op == "-" else n)
    if _is_static_container(node):
        words = _static_container_words(node)
        return None if words is None else StaticNestedBlob(words)
    # The three arms below are the CHANGE, and each is one existing reader. They
    # come after the arms above so every element that already had a word keeps
    # the word it had — in particular a unary sign of a string or a container,
    # which the arm above answers and the int-only folder would not.
    return _static_folded_word(node)


def _static_folded_word(node, bound=()):
    """The word a `__DATA` element is, for the three shapes `_static_word`'s own
    arms do not cover: an ARITHMETIC EXPRESSION over words, a FLOAT literal, and a
    NAME this unit folds.

    None means "the build does not know this", which is a refusal and not a zero
    — the same distinction `fold_literal_expr` draws, and the reason nothing here
    invents a value.

    `bound` is the names this walk has already read, and it exists for one shape:
    a module constant bound to another module constant (`A = B`) is one hop, and
    `A = B; B = A` is a cycle a fold must refuse rather than chase. The value
    comes from `GlobalSymbol.literal`, which is the FOLDED NODE
    (`IntLiteral` / `StringLiteral` / `BoolLiteral`) `collect_module_symbols`
    already built in source order — so a name is answered from the build's own
    decision about that name, not from a second fold here.
    """
    if isinstance(node, F.FloatLiteral):
        # `float_literal_bits` is unsigned and `_lay_out_blob_words` writes an int
        # with `signed=True`, so the pattern is read as the SIGNED word: the same
        # 64 bits, and the value a register holds after a 64-bit load.
        bits = float_literal_bits(node.value)
        return bits - (1 << 64) if bits >= (1 << 63) else bits
    if isinstance(node, F.IdentExpr):
        if node.name in bound:
            return None                    # `A = B; B = A` — a cycle, not a value
        sym = module_symbol(node.name)
        literal = getattr(sym, "literal", None) if sym is not None else None
        if literal is None:
            return None                    # not folded: no word to put in the blob
        return _static_folded_word(literal, bound + (node.name,))
    return _folded_data_word(node)


def _folded_data_word(node):
    """What an expression of LITERALS comes to, as a word, or None.

    **The composition `fold_module_int_expr`'s own `operand` helper already
    spells, applied to the node ITSELF rather than to each of its operands** —
    which is the whole gap: `fold_module_int_expr` answers a `BinaryOp` or a
    `UnaryOp` and returns None for a bare `IntLiteral`, so a name's folded
    literal (`GlobalSymbol.literal`, always a literal NODE) came out as no value
    at all. `fold_literal_expr` first, then the wider folder, is that
    composition and nothing else: two readers because they answer two questions,
    both of them the tree's own, and neither of them rewritten here.

    The range check is `fold_module_value`'s, made here because this is the caller
    half of its contract: a folded value that is not one 64-bit word has no
    representation in `__DATA`, and writing its low bits would be a plausible
    number rather than this value. `2 ** 64` is exactly that case.
    """
    value = fold_literal_expr(node)
    if value is None:
        value = fold_module_int_expr(node)
    if isinstance(value, str):
        return value
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return value if _FOLD_INT_MIN <= value <= _FOLD_INT_MAX else None


def static_initializer_refusal_reason(slot) -> str:
    """Why this slot has no initializer the build can compute, or None.

    A slot can always EXIST — the storage is the easy half — but a slot with no
    initializer would read as zero, and zero is a plausible-looking wrong answer
    rather than a refusal. So this names which of the shapes landed on
    `("unknown", …)`, because they have different repairs: a value computed by a
    call needs the module-level sequence that would fill it, a name imported
    from another module needs that module's storage, and a container with an
    element computed by a call needs a value before the program runs.

    **A slot the MODULE BODY fills is the one `("unknown", …)` shape that is not
    a refusal**, and it is checked here rather than at the three callers so the
    two cannot disagree. `G = compute()` has no static initializer because the
    value is not known before the program runs — but the statement that computes
    it IS the module's top level, and that runs first (`module_body_store_names`).
    The zero an unwritten slot gives is therefore not what any read can see, in
    exactly the way it is not what any read can see for a slot that does have an
    initializer. Refusing here would be refusing a value the image computes
    before its first read, which is the case `bugs/formal/FORMAL_module_state_no_storage.md`
    §"the exact next step" item 1 is about.
    """
    if slot is None or slot.init[0] != "unknown":
        return None
    if slot.filled_by_body:
        return None
    node = getattr(slot.site, "value", None)
    if isinstance(node, (F.ListExpr, F.TupleExpr, F.SetExpr, F.DictExpr)):
        return "computed_element"
    if isinstance(node, F.CallExpr):
        return "computed"
    if isinstance(node, (F.ImportStmt, F.FromImportStmt)):
        return "imported"
    return "unknown"


def module_slot_readable_in(slot, fn) -> bool:
    """Can `fn` read this slot, or would the read see a value nobody wrote?

    Only a slot the MODULE BODY fills can be unreadable here, and the reason is
    the one thing about the body that is easy to get wrong: it is the ENTRY, so
    a function cannot run before the module's first statement — but a CALL the
    body makes can, and then the function's read of the slot sees the zero an
    unwritten slot gives. Zero is a plausible number, so this is a refusal and
    not a default.

    Both halves are order facts about the body's own statement list plus a
    transitive closure over this unit's own functions, which is why this is a
    predicate rather than a whole-program analysis (`module_body_store_sites`):

      * a read from another function is premature exactly when the module body
        can reach THAT function before the store of this name — above it, or
        through the store's own value, which runs before the store completes;
      * a read from the body itself is `read_before_store`'s question and is
        left to it. It already refuses it, with a message that quotes CPython's
        `NameError`, and a second opinion here would be two rules about one
        program.

    Only a slot with NO static initializer is asked at all. A slot the image
    already holds — a container literal, a folded literal — has its value before
    the body runs, so no order can make a read of it premature, and asking would
    refuse `NUMS = [1, 2]` read by a function the body calls first, which is a
    real program with a real answer.

    A slot with NO recorded site is refused rather than assumed, because a
    body-written name this build could not place in the body's statements is
    exactly the case where "assume it is fine" is a guess."""
    if slot is None or not slot.filled_by_body or slot.init[0] != "unknown":
        return True
    if getattr(fn, "name", None) == MODULE_BODY_NAME:
        return True
    if slot.body_site is None:
        return False
    site = slot.body_site
    name = getattr(fn, "name", None)
    if site.opaque_above or site.opaque_self:
        return False
    return name not in site.earlier and name not in site.self_reaches


def module_slot_unreadable_refusal(slot, fn) -> str:
    """The refusal for a read that would see a `__DATA` slot before it is filled.

    Names WHICH of the three ways the read got here ahead of the store, because
    they have three different fixes, and says what the read would see instead —
    "0" is not a diagnosis, since a program that prints 0 here is
    indistinguishable from one that computed 0."""
    who = f"{getattr(fn, 'name', None) or ''}: "
    head = (f"{who}{slot.name!r} is one of the module-global slots in this "
            f"image's `__DATA`, and it has no static initializer: the value is "
            f"computed by the module's own top-level statements, which this "
            f"path compiles into the synthetic function the startup stub enters. "
            f"That function is the entry, so nothing runs before its first "
            f"statement — but this read is reached before the store of "
            f"{slot.name!r} completes, so the load would read the zero an "
            f"unwritten slot gives. ")
    site = slot.body_site
    who_reads = f"Function {getattr(fn, 'name', None)!r} is"
    if site is None:
        why = ("This build could not place the module-level assignment in the "
               "module body's own statement list, so it cannot say what runs "
               "before it. ")
    elif site.opaque_above:
        why = (f"A statement above the assignment that fills {slot.name!r} calls "
               f"something this path cannot follow — through a value rather "
               f"than through a function of this unit — so it cannot show that "
               f"{who_reads} reading it runs after the store. ")
    elif site.opaque_self:
        why = (f"The store of {slot.name!r} is a statement whose value calls "
               f"something this path cannot follow, so it cannot show that "
               f"{who_reads.lower()} reading it runs after the store. ")
    elif getattr(fn, "name", None) in site.earlier:
        why = (f"{who_reads} reachable above the assignment at statement "
               f"{site.store_at + 1} that fills {slot.name!r} — something the "
               f"module body calls first is a path to it, and that call runs "
               f"before the store. A module-level global cannot be read by a "
               f"function the body reaches above its own assignment. ")
    else:
        why = (f"{who_reads} reachable from the store of {slot.name!r} itself, "
               f"which is what computes the value — so the call runs before "
               f"the slot holds it. A module-level assignment cannot read, or "
               f"call something that reads, the name it assigns. ")
    return head + why + ("Make the value a literal and the build folds it at "
                          "every read instead. bugs/formal/FORMAL_module_state_no_storage.md"
                          " records the design")


def _computed_element_clause(slot) -> str:
    """The `computed_element` half of `global_value_refusal`, naming the ELEMENT.

    **This sentence used to say "computed by a CALL" for every shape that reached
    it, and it was false of most of them.** Measured on this tree, both
    architectures, `TBL = [1 + 2, 3]` — arithmetic on two integer literals — was
    refused with it, and so were `[7 // 2, 3]`, `[2 ** 10, 3]`, `[1 << 4, 3]`,
    `[K, 3]` for a module constant `K = 5`, and `[1.5, 2]`: six programs, no call
    in any of them. That was the same misdiagnosis `static_initializer_refusal_
    reason` records for `None` in 2026-10-04, one level out, and the fix is the
    same one — `_static_word` now folds what the tree's own folders can answer, so
    those six build.

    What is left is three shapes with three different reasons, and a reader sent
    after "a call" for the second or third is sent after nothing:

      * a CALL — its result is not known before the program runs, and no
        arrangement of `__DATA` changes that;
      * a NAME the build cannot fold — `os.pi`, or a constant imported from
        another module. It is a value the program has and this path cannot see;
      * a value outside one 64-bit word — `2 ** 64`. It is a value the source
        does not have, and writing its low bits would be a plausible number rather
        than this one.

    So the clause asks `container_element_without_a_word` which element it was and
    quotes it, and the three cases get their own sentence. The lead — a container
    is a run of words, so an element that is not a word has nothing to put in the
    blob — is kept because it is true of all three and is what makes the missing
    thing storage rather than arithmetic.
    """
    lead = ("a container is laid out here as a run of words — so an element that "
            "is not a word has nothing to put in the blob. An int element, a "
            "string element, a float element and a NESTED container of those all "
            "do (the string as a pointer the initializer fills in, the nested "
            "container as a blob of its own with one more fixup for the word that "
            "points at it), and so does an element the build can FOLD — "
            "`1 + 2`, `7 // 2`, `2 ** 10`, `1 << 4`, or a module-level constant "
            "this unit folds — because those are the same arithmetic the "
            "instructions would emit, computed here instead")
    value = getattr(getattr(slot, "site", None), "value", None)
    element = container_element_without_a_word(value) if value is not None else None
    if element is None:
        # The walk said no without saying which element, which means the shape is
        # not one it walked at all — a container it does not recognise. Say the
        # one thing that is true rather than naming an element it cannot name.
        return (f"this build cannot compute its initializer from the source. "
                f"{lead}, and what this one spells has no word in it")
    spelled = expr_spelling(element)
    if isinstance(element, F.CallExpr):
        return (f"its element `{spelled}` is computed by a CALL, and a call's "
                f"result is not known before the program runs. {lead}; no "
                f"arrangement of `__DATA` changes that")
    if isinstance(element, (F.IdentExpr, F.MemberExpr)):
        return (f"its element `{spelled}` is a NAME this build cannot fold — a "
                f"value the program has and this path cannot see, which is a "
                f"different missing thing from a call: an imported constant, a "
                f"module attribute, or a name bound to something other than a "
                f"literal. {lead}")
    return (f"its element `{spelled}` is an EXPRESSION and this build computes no "
            f"word for it, which is one of three things and the element says "
            f"which: a value outside the 64-bit range one word holds, an "
            f"arithmetic with no value at all (`1 // 0`), or one that is not a "
            f"number (a string, whose element would have to be the address of an "
            f"interned literal this initializer does not hold). The build refuses "
            f"rather than writing the low bits of something it cannot compute, "
            f"which would be a plausible number rather than this one. {lead}")


def global_value_refusal(name: str, fn_name: str, why: str,
                         slot=None) -> str:
    """The refusal for a module-level value this path cannot give an initializer.

    Reached only for a name that HAS a `__DATA` slot — so the message says the
    storage is there, because that is the fact that changed and the fact a reader
    needs. The previous wording claimed every module-level name had nowhere to
    live, which was true of none of them: `G = 5` with `global G` in one function
    now has exactly the storage it needs, and a reader sent to look for a data
    section that already exists would not find the thing that actually blocks
    their program.

    **Why the name has a slot is read off the slot and not assumed**, because
    there are two reasons and only one of them is a writer — and this sentence
    was the second false diagnostic `GlobalSlot.mutable`'s own comment records
    having already been fixed once, in the MANIFEST, while the refusal kept it.
    Measured on this tree: `TBL = [(None, 7), (3, 9)]` read by a function was
    refused with "it is one of the module-global slots in this image's `__DATA`,
    because a function writes it through `global TBL`" — and no function writes
    `TBL`, in this program or in any other. The slot is there because its value
    is a CONTAINER BLOB the linker places, which makes the name a CONSTANT with
    a home; saying "a function writes it" sends a reader looking for a writer
    that does not exist, and away from the element of the literal that is not a
    word. `collect_global_slots` is the only function that holds both the
    statements and the bodies, which is why `mutable` is a field on the slot
    rather than something derived here."""
    who = f"{fn_name}: " if fn_name else ""
    detail = {
        "computed_element": _computed_element_clause(slot),
        "computed": (
            "its module-level value is computed by a call, and a call's result "
            "is not known before the program runs. The storage is there and is "
            "the right storage; what is missing is the module-level sequence "
            "that would fill it, which is a separate capability — "
            "FORMAL_toplevel_statements_dropped"),
        "imported": (
            "the name is imported from another module, so its value lives in "
            "that module's dylib. A slot in THIS image cannot hold it; what a "
            "cross-module global needs is the other module's slot exported as a "
            "symbol, which this path does not do yet — "
            "bugs/formal/FORMAL_module_state_no_storage.md"),
        "unknown": (
            "the build cannot compute it from the module-level statement, and "
            "a value it cannot compute has no initializer to write into the "
            "slot"),
    }.get(why, "")
    if slot is not None and not getattr(slot, "mutable", False):
        why_has_a_slot = (
            f"because its value is static DATA this image holds, a container "
            f"blob whose first word is the count, so the slot holds its "
            f"address and nothing writes it: {name!r} is a CONSTANT with a "
            f"home and not a variable")
    elif getattr(slot, "filled_by_body", False):
        why_has_a_slot = (
            f"because the module's own top-level statements store it, which "
            f"this path compiles into the synthetic function the startup stub "
            f"enters and that function is the entry, so the store runs before "
            f"anything reads the slot")
    else:
        why_has_a_slot = (
            f"because a function writes it through `global {name}`")
    return (f"{who}{name!r} has storage here — it is one of the module-global "
            f"slots in this image's `__DATA`, {why_has_a_slot} — but that "
            f"storage has no initializer: {detail}. A slot is eight bytes of "
            f"static storage, so its value has to be known before the program "
            f"runs; one that is not would read as the zero an unwritten slot "
            f"gives, which is a plausible wrong number rather than a refusal")


def build_data_image(table: dict, base: int) -> GlobalDataImage:
    """The `__DATA` bytes for a slot table, and the fixups that go with them.

    `base` is the address the image's data segment will be MAPPED at — the
    Mach-O and ELF constants, which differ. It is a REQUIRED argument rather
    than an offset-relative default, and the reason is a bug this signature is
    shaped to make impossible: both linkers' relocation machinery ADDS the load
    slide to whatever the file already holds (dyld's REBASE opcodes, and
    `R_X86_64_RELATIVE`'s addend). So a slot word must contain the link-time
    ADDRESS. An earlier version wrote the bare offset, which is off by the base
    — and it failed as a SEGFAULT on the first read of a container global rather
    than as anything that named the missing base, which is the worst way for it
    to fail.

    Layout, in this order and for a reason: every SLOT first, in `index` order,
    so a backend that computes `GLOBAL_SLOT_BYTES * slot.index` addresses the
    right word whatever else the module has; then the two RESERVED words (the
    initializer flag and the stack floor, below); then the container blobs and
    struct FRAMES the address-valued slots point at, each 8-byte aligned so a
    word of one is a word at the address the slot holds.

    **The image is never empty, and that is a change of policy rather than an
    oversight** (`model.STACK_FLOOR_BUDGET_BYTES`, whose guard reads the word
    below).
    The two reserved words are the backend's own bookkeeping rather than any
    program's storage, so they exist whether or not the module declares a
    global — which means `has_globals` is true of every image and `__DATA` is
    emitted unconditionally in both containers. The alternative was a program
    with no module globals having no `__DATA` at all, which is exactly the
    reproducer of the stack-floor bug (`deep` has no globals), so the word the
    fix needs would not exist in the image that needs it.

    A slot's own word is `base + offset-of-what-it-points-at`, and the fixup
    records where that word is so the codegen can emit one store. A STRING word
    — a slot bound to a string, or an element of a container literal — is the
    other kind: its target is the interned literal in `__TEXT`, which is not in
    this image, so it goes in `string_cells` for the code to fill and its eight
    bytes here are left zero."""
    # The initializer flag occupies the word immediately after the slots, so it
    # is at a fixed offset from the slot table and both backends and the linker
    # can name it without another table. The stack floor is the word after
    # that (`GlobalDataImage.stack_floor_offset`), and both are emitted even
    # with no slots at all — hence `flag_offset` is 0 for an empty table rather
    # than a `None` that every reader would have to test for.
    count = max(s.index for s in table.values()) + 1 if table else 0
    flag_offset = count * GLOBAL_SLOT_BYTES
    # `GLOBAL_RESERVED_WORDS` reserved words, not two: the initializer flag, the
    # stack floor, the cached `RLIMIT_STACK`, and the 16-byte scratch `getrlimit`
    # writes into.
    # The third is there because the floor's budget is read from the process at
    # run time (measured: a constant budget larger than the real stack is a guard
    # that never fires — same binary, same depth, `exit 2` at the default
    # `ulimit -s` and `exit 139` at `ulimit -s 2048`), reading it is a call, and
    # a call is made once per process only because there is a word to remember
    # the answer in. The fourth and fifth are that call's 16-byte destination,
    # which cannot be stack: `GlobalDataImage.stack_scratch_offset` has the
    # measurement for all three alternatives.
    blob = bytearray(flag_offset + GLOBAL_RESERVED_WORDS * GLOBAL_SLOT_BYTES)
    fixups = []
    string_cells = []
    # The trailing area starts after the RESERVED words, so a slot's address
    # never depends on how many trailing items there are — and so a container's
    # own words cannot land inside the area `getrlimit` writes into. It is
    # `GLOBAL_RESERVED_WORDS` and not a literal precisely because the allocation
    # above and this line were two literals, and the tail was the one that lost.
    tail_base = flag_offset + GLOBAL_RESERVED_WORDS * GLOBAL_SLOT_BYTES
    tail = bytearray()
    for slot in sorted(table.values(), key=lambda s: s.index):
        kind = slot.init[0]
        at = slot.index * GLOBAL_SLOT_BYTES
        if kind == "int":
            blob[at:at + GLOBAL_SLOT_BYTES] = int(slot.init[1]).to_bytes(
                GLOBAL_SLOT_BYTES, "little", signed=True)
        elif kind == "str":
            # NOT a copy of the bytes here. The word is a `char *` and the only
            # `char *` to these bytes on this path is the interned literal, so
            # copying would make a second, different string with the same
            # content — which is invisible to `printf` and fatal to every
            # address comparison. See `GlobalDataImage.string_cells`.
            string_cells.append((at, slot.init[1]))
        elif kind in ("blob", "frame"):
            # ONE branch, because a slot pointing at a container blob and a slot
            # pointing at a STRUCT FRAME are the same arrangement of bytes: a run
            # of 8-byte words in the trailing area, the slot holding its
            # link-time address, and a rebase relocation on that word. The frame
            # case is new and the difference between them is only WHAT the words
            # are — a blob's first word is a count and a frame's slot `k` is field
            # `k` — and that difference is in `module_frame_slot_initializer`,
            # which produced the list. Laying them out twice would be two
            # implementations of "a run of words plus its fixups", which is the
            # shape of bug the nested-blob paragraph below is about.
            while len(tail) % GLOBAL_SLOT_BYTES:
                tail.append(0)
            offset = tail_base + len(tail)
            _lay_out_blob_words(slot.init[2], tail, fixups, string_cells,
                                tail_base)
            blob[at:at + GLOBAL_SLOT_BYTES] = (base + offset).to_bytes(
                GLOBAL_SLOT_BYTES, "little", signed=True)
            fixups.append((at, offset))
        # `("unknown", …)` writes eight zero bytes, and the read is refused by
        # name before anything can observe the zero.
    # The flag starts CLEAR: zero means "not yet filled in". So does the floor:
    # it is the backend's own word, nothing writes it yet, and a reader that
    # finds it clear must treat the floor as UNKNOWN rather than as zero —
    # which is the safe direction for the guard this word exists for, because a
    # zero floor compares as "nothing is below the stack pointer" and so never
    # fires (`model.STACK_FLOOR_BUDGET_BYTES`).
    return GlobalDataImage(bytes(blob) + bytes(tail), fixups, flag_offset,
                           string_cells)


def _lay_out_blob_words(words, tail, fixups, string_cells, tail_base) -> None:
    """Append one run of `__DATA` words to `tail`, and record what it needs.

    A container BLOB and a STRUCT FRAME both arrive here, and for the reason
    `build_data_image`'s `("blob", "frame")` branch gives: both are a run of
    8-byte words the trailing area holds and the slot points at, so the word
    kinds below are the kinds either of them is made of. `module_frame_slot_
    initializer` is what decides which list a frame contributes.

    The three word kinds, and each one's reason for being here:

      * an `int` — its own eight little-endian bytes, and nothing else. A blob
        that is all integers needs no fixup at all, which is why the flat case
        needed nothing from the initializer to be right.
      * a `str` — eight ZERO bytes plus a `string_cells` entry, because the only
        `char *` to these bytes on this path is the interned literal in `__TEXT`,
        which is not in this image and which only the CODE can name
        (`GlobalDataImage.string_cells`). The zero is overwritten before any read
        can reach it: `initialization_is_lazy` is what makes the overwrite
        ordered before the first read, and the flag is set last.
      * a `StaticNestedBlob` — a reserved word of its own, and one more entry in
        the same `fixups` list the outer blob already used.

    **A blob's own words have to be CONTIGUOUS, and that is the whole of what is
    easy to get wrong here.** Element `i` of a blob is the word at `8 * (i + 1)`,
    so anything laid out between two of this blob's words shifts every later
    element. Writing an inner blob out as its element word is reached interleaves
    it, and `[[1, 2], [3, 4]][1][0]` then read the first inner blob's COUNT (2)
    where element 1's pointer belongs, indexed 0 into it, and answered 2 from a
    green build on both architectures — a wrong number that is also a plausible
    one. Hence a WORKLIST rather than a recursion: one pass lays out every word
    of one blob and queues its nested blobs, and the next pass lays out those.
    A recursion that re-scans the shared queue is not a shorter way to write the
    same thing, it is an infinite loop.

    `tail_base` is the offset within the data image at which `tail` starts, so
    every offset recorded here is in the same coordinates `fixups` and
    `string_cells` have always used. It is passed rather than recomputed because
    the queue has no other place to learn it from, and two places computing one
    number is the shape of bug this file's layout comments are about.

    Every appended chunk is a multiple of `GLOBAL_SLOT_BYTES`, so the alignment
    loop only ever fires on the first blob; it is kept because `tail` starts empty
    and its first blob still has to be word-aligned for the loaders to agree.
    """
    # `(offset of the word that points at this blob, the blob's words)`, and
    # `None` for the outermost one, whose pointer word is the SLOT rather than a
    # word of this run.
    pending = [(None, words)]
    at = 0
    while at < len(pending):
        at_pointer, blob_words = pending[at]
        at += 1
        if at_pointer is not None:
            fixups.append((at_pointer, tail_base + len(tail)))
        for word in blob_words:
            while len(tail) % GLOBAL_SLOT_BYTES:
                tail.append(0)
            at_word = tail_base + len(tail)
            if isinstance(word, StaticNestedBlob):
                tail.extend(b"\x00" * GLOBAL_SLOT_BYTES)
                pending.append((at_word, word.words))
                continue
            if isinstance(word, str):
                tail.extend(b"\x00" * GLOBAL_SLOT_BYTES)
                string_cells.append((at_word, word))
                continue
            tail.extend(int(word).to_bytes(GLOBAL_SLOT_BYTES, "little",
                                           signed=True))


# Published for the same reason `_MODULE_SYMBOLS` is: the consumers are a
# per-function read inside a backend and the linker, and neither has the module
# statements in hand. `None` before a publish, and every consumer treats that as
# "this unit has no globals", so a dylib build cannot read the executable's slots.
_MODULE_SLOTS: dict = {}


def publish_global_slots(table: dict) -> None:
    """Install `table` as the current unit's `__DATA` slot table.

    Replaces, never merges, for the reason `publish_module_symbols` does: two
    units compiled in one process must not accumulate each other's slots, and a
    merged table would silently give one module's name the other's address."""
    global _MODULE_SLOTS
    _MODULE_SLOTS = dict(table or {})


def module_slots() -> dict:
    """The published `{name: GlobalSlot}` table. Empty before a publish."""
    return _MODULE_SLOTS


def module_slot(name: str):
    """The `GlobalSlot` for a written module-level `name`, or None."""
    return _MODULE_SLOTS.get(name)


def global_slot_kind(name: str):
    """The `ValueKinds` kind a module global's SLOT says its value is, or None.

    The value model's answer to "what does this name hold", asked of a name the
    function being emitted does not bind. A local gets its kind from the
    assignment it is bound by; a module global's only statement about its value
    is the module-level binding, and the slot table is where that binding's
    shape ended up — so the two tables are asked the same question and cannot
    disagree.

    A DICT is `LIST_PREFIX` because `F.DictExpr` already classifies that way
    everywhere else (`ValueKinds.kind_of`), and this path's dict is a pair blob
    with a count in its first word, which is all `len` needs. The dict-vs-
    sequence distinction that a SUBSCRIPT needs is not a kind question and is
    `global_slot_is_dict`'s.

    A blob's kind carries its ELEMENT kind, read from the initializer that
    stated it (`container_literal_elem_kind`), and that is the same answer
    `ValueKinds.kind_of` gives the same literal bound to a local — so
    `D = {"a": 10}` at module level and `d = {"a": 10}` inside a function are
    one question with one answer, and `print(d["a"])` stops being a refusal in
    one spelling only. The slot's own `site` is the initializer statement, which
    is what makes the read a question about the source rather than about the
    words the linker happened to lay out.

    ONLY a slot whose initializer is a literal says this. A blob written by a
    function (`global L; L[0] = 5` on a list of strings) has an initializer
    that states no element kind, and `container_literal_elem_kind` answers None
    for it, which leaves the bare `LIST_PREFIX` — an honest "a container, and
    nothing here says what is in it" rather than a claim about a word that is
    written at run time.

    A slot the MODULE BODY fills is the third source and answers from the CALL
    the store makes (`_body_store_shape`), so `len(G)` and `print()` on a
    computed global are the same question with the same answer as the same
    expression bound to a local. Before, this returned None for such a slot
    because `("unknown", …)` states no kind — and a `None` here is not a missing
    optimization, it is `len()` refusing a length the image has."""
    slot = module_slot(name)
    if slot is None:
        return None
    if slot.init[0] == "str":
        return STR_KIND
    if slot.init[0] == "blob":
        elem = container_literal_elem_kind(getattr(slot.site, "value", None))
        return list_kind(elem)
    return slot.kind


def module_entry_literal_facts() -> dict:
    """`{name: literal node}` a FUNCTION's entry may treat as already known.

    The one reader of "which module-level names are constants whose value a
    function body may assume at its first instruction", and the evidence is two
    PUBLISHED tables rather than a re-walk:

      * `module_symbols()`' folded literal for a name with no `__DATA` slot —
        the int/str constant `_substitute_module_constants` puts at a read, so a
        function's entry may assume the same value;
      * a `module_slots()` entry whose `init` is a container `blob`, that no
        function writes and the module body does not fill (`mutable` and
        `filled_by_body` both false), whose `entry_literal` the slot carries —
        and that field is None unless every mention of the name in the unit is
        its own initializer or a `for` iterable, which is what rules out an
        in-place mutation (`XS.append(1)`, `f(XS)`). See
        `_module_container_entry_literals`.

    A name that fails either test is ABSENT, and absence is the answer that
    keeps the previous behaviour: a name a function writes through `global` has
    a value that changes while the program runs (`_module_constant_sites`'
    docstring records the measured `G=5` where CPython says `G=7`), and a name
    the module body fills is not there yet when the body's first statement runs.
    A name bound more than once at module level is the LAST binding, which is
    the value that holds when the first function runs (`collect_module_symbols`
    folds the last one exactly).

    Consumed by `read_before_store`'s `entry_facts`, which seeds the preheader
    walk at the function entry — so a `for` over a module-level literal
    sequence is decided by the same predicate a function-local literal is
    (`_for_emptiness`). It is deliberately NOT `_module_constant_sites`: that
    table excludes a container constant because a blob has no literal to put at
    a READ, and this asks the weaker question "what is the value", which a blob
    answers. See
    `bugs/formal/FORMAL_a_for_range_target_may_be_read_when_the_range_is_empty.md`."""
    slots = module_slots()
    out: dict = {}
    for name, sym in module_symbols().items():
        literal = getattr(sym, "literal", None)
        if literal is not None and name not in slots:
            out[name] = literal
    for name, slot in slots.items():
        if getattr(slot, "mutable", True) \
                or getattr(slot, "filled_by_body", False):
            continue
        value = getattr(slot, "entry_literal", None)
        if _is_container_literal(value):
            out[name] = value
    return out


def module_slot_frame_struct(name: str):
    """The struct whose FRAME module global `name`'s slot word points at, or None.

    The question a holder asks about a name it did not see bound: `G` in
    `def f(): return G.a` is a frame address, and the only thing in the image
    that says so is the slot's own `("frame", struct, words)` initializer. It is
    a read of the SLOT rather than a second classification of the module-level
    statement, for the reason every other reader in this section is: a slot table
    built from the pre-rewrite list would not know, and a recognition of "is this
    a struct construction" written a second time would be free to disagree with
    the one that decided the words.

    None for every other slot, and the None is what the caller must keep
    answering: a slot with no frame in it is an ordinary word, and a holder
    analysis that treated it as an address would read a frame out of it."""
    slot = module_slot(name)
    if slot is not None and slot.init[0] == "frame":
        return slot.init[1]
    return None


def module_frame_slot_holders(fn, structs_by_name: dict) -> dict:
    """`{name: struct}` — the module globals `fn` reads that hold a FRAME.

    Per function rather than per image, and that is what makes it seedable: the
    holder tables say which of THIS function's names hold a frame address, so a
    name the function never mentions must not be added — not because saying so
    would be wrong (it is true of the name) but because a holder the function
    does not use is still read by `_frame_return_status` and by the rebind
    checks, which ask what the function DOES with its names.

    The read test is the bare-name walk `function_touches_globals` uses, and the
    struct is read with `module_slot_frame_struct` rather than by a second
    `init[0] == "frame"` here: both questions are "does this body mention a
    module global" and "does that slot hold a frame", and two answers to either
    would be free to differ from the ones the rest of this section already
    gives.
    """
    table = module_slots()
    if not table:
        return {}
    out = {}
    for node in iter_nodes(getattr(fn, "body", None) or []):
        if not isinstance(node, F.IdentExpr) or node.name not in table:
            continue
        name = module_slot_frame_struct(node.name)
        if name is not None and name in (structs_by_name or {}):
            out[node.name] = structs_by_name[name]
    return out


def global_slot_is_dict(name: str) -> bool:
    """True when module global `name` holds a DICT pair-blob.

    A use site has only the name, and the name's value is what says whether
    `D[k]` is a key SCAN or an element address computation — so a backend that
    cannot answer this emits a pair blob indexed by an element offset, which is
    a load from a nonsense address rather than a refusal. Measured, both
    architectures, on `D = {"a": 1}` read as `D["a"]`: the string literal's
    interned address became the index, the bounds check failed and the image
    exited 1.

    Asked from the slot's own initializer, which is where the shape is recorded,
    so the answer cannot disagree with the bytes the linker laid out — and from
    the CALLEE for the slots the initializer says nothing about, which is the
    same question asked of a different piece of evidence rather than a second
    rule. `D = mk()` where `def mk() -> Dict[String, Int]` is the measured case
    on this tree: a `__DATA` slot the module BODY fills, whose `("unknown", …)`
    initializer names no layout, so the subscript was emitted as a SEQUENCE one
    and the image exited 1 on both architectures with a green build. A kind
    cannot carry the answer (all four container annotations are one word here —
    see `_body_store_shape`), which is why this is a field of its own and not a
    fifth `ValueKinds` constant."""
    slot = module_slot(name)
    return slot is not None and (
        slot.is_dict
        or (slot.init[0] == "blob" and slot.init[1] == "dict"))


def global_slot_is_string(name: str) -> bool:
    """True when module global `name` holds a `char *` to interned bytes.

    The other half of `global_slot_is_dict`, and for the same reason: a name
    classified as a plain word is an INT on this path, so `print` renders its
    address as a number and a `==` compares two addresses. Both were right for a
    LOCAL bound to a string literal because `_note_binding` saw the literal; a
    module global's literal is in the module's statement list, not in the
    function being emitted.

    Asked as the KIND rather than as a second predicate over `init`, so the two
    readers of a slot cannot answer "what does this name hold" differently: for
    the literal spellings `global_slot_kind` returns `STR_KIND` exactly when
    `init[0] == "str"`, and for the one spelling it did not cover — a slot the
    module body fills from a callee declared `-> String` — it is the answer."""
    return string_operand_is_string(global_slot_kind(name))


def global_slot_bytes(table: dict, base: int) -> bytes:
    """The whole data image as bytes. `build_data_image` is the real reader;
    this is the same bytes for a caller that has no use for the fixup list."""
    return build_data_image(table, base).blob


def unresolved_name_refusal(name: str, fn_name: str, why: str) -> str:
    """The diagnostic for a name the build cannot place at all.

    `why` is the evidence the build had, passed in rather than recomputed so
    the message cannot claim a reason the caller did not check."""
    who = f"{fn_name}: " if fn_name else ""
    return (f"{who}{name!r} has no home: {why}. This path places a name in a "
            f"register or a spill slot allocated for THIS function, a "
            f"receiver field's frame, or a module-level constant the build "
            f"folded — and a name in none of them is refused rather than read "
            f"out of whatever register the allocator left behind, which is "
            f"how one program returned 10 on arm64 and 0 on x86-64 where the "
            f"source says 5")


def publish_pre_lift_defs(table: dict) -> None:
    """Install `{pre-lift name: LiftedDef}` for the closure lift just performed.

    Published for the same reason and with the same REPLACE-never-merge shape as
    `publish_module_symbols`: the consumer is a per-function walk inside
    `check_module_symbols` with no closure table in hand, and two units compiled
    in one process must not accumulate each other's lifts."""
    global _PRE_LIFT_DEFS
    _PRE_LIFT_DEFS = dict(table or {})


def pre_lift_defs() -> dict:
    """The published `{pre-lift name: LiftedDef}` table. Empty before a publish."""
    return _PRE_LIFT_DEFS


def pre_lift_def(name: str):
    """The `LiftedDef` a lift RENAMED to something else, or None.

    None is the answer for every ordinary name, which is the point: this table
    holds exactly the names the lift took away, so a read this returns None for
    is a read the lift did not touch and `check_module_symbols` asks its other
    tables as it did before."""
    return _PRE_LIFT_DEFS.get(name)


class LiftedDef:
    """One nested `def`, in its PRE-LIFT spelling and its post-lift facts.

    Four attributes because four questions are asked about the same rename, and
    one attribute per question is why none of them has to be recomputed from the
    AST after `_flatten_closures` has stripped the `def` that carried them:
    `name` is the spelling SOURCE still uses, `lifted_name` is the symbol the
    build emitted, `outer_name` is the function the `def` was nested in, and
    `captures` is what makes the value of a lifted closure different from the
    value of a plain function.

    `__slots__` for the reason every table on this path uses it: a module body
    with a thousand nested `def`s builds a thousand of these, and the
    compiled path stores an element of a tuple-typed list, so an instance with a
    `__dict__` is both more memory and a shape the self-hosted backend cannot
    lower."""

    __slots__ = ("name", "lifted_name", "outer_name", "captures")

    def __init__(self, name, lifted_name, outer_name, captures=()):
        self.name = name
        self.lifted_name = lifted_name
        self.outer_name = outer_name
        self.captures = tuple(captures or ())

    def __repr__(self):
        return (f"LiftedDef({self.name!r} -> {self.lifted_name!r}, "
                f"in {self.outer_name!r}, captures={list(self.captures)!r})")


# The pre-lift spellings the closure lift took away, installed by
# `publish_pre_lift_defs`. Published rather than threaded for the same reason
# `_MODULE_SYMBOLS` is, and DELETED-from-nothing: a name is in it only if the
# lift renamed it, so a name in here is a name the build emitted under a
# different spelling — which no other table here can recognise, because by this
# point `_callee_defs(functions)` holds `make_add` and the source says `add`.
_PRE_LIFT_DEFS: dict = {}


def lifted_closure_value_refusal(name: str, fn_name: str, lifted_name: str,
                                 outer_name: str, captures) -> str:
    """Why a nested `def` cannot be handed BACK to its caller, in its own words.

    ``def make(n): def add(x): return x + n; return add`` — the sentence this
    replaces is `unresolved_name_refusal`'s, which says the name has no home and
    then lists where a name could live: a register, a spill slot, a receiver
    field's frame, a folded module constant. **Every item of that list is
    irrelevant to this program**, and the first two are the ones that send the
    reader to look for a register-allocation bug in a file whose problem is a
    construct: `add` never wanted a register, and the allocator never refused it
    one.

    The reason it reached that sentence at all is an ORDER, and it is worth
    naming because it is the whole defect. `_flatten_closures` renames the
    nested `def` to `make_add` and strips it from the enclosing body before
    anything asks whether the name is a function. So the read of `add` is
    answered by no table in the build: it is not a parameter, not a local, not a
    struct, not a folded module constant, and — the actual gap — not a function
    either, because the function is now called something else. What the read IS
    is a function, and the two facts a reader needs are which symbol the build
    emitted and what makes its value different from a plain function's.

    That last part is why the refusal is not "a function is not a value" — a
    plain function's value IS a code address here, materialized by each
    backend's `_load_var` and branched through by its `_emit_call`, so that
    sentence is false about the general case and `function_value_refusal` is
    dead code kept only for the wording. A lifted closure is the one function
    whose value is NOT its address: the lift prepends its captures as
    parameters, so the word would have to carry an environment as well as a
    code address, and the capture ABI this path implements is a CALL-SITE rewrite
    in the scope that DEFINES the closure — `add(n, x)`, not a value passed
    around. There is no call site at `return add`, so materializing the address
    would print a number nobody wrote and, called back through, drop the capture.

    So the message names the rename, the symbol, the captures, and the repair
    (return the RESULT, or keep the call in the scope that defines the `def`),
    which is what a reader has to act on."""
    who = f"{fn_name}: " if fn_name else ""
    caps = ", ".join(repr(c) for c in (captures or ()))
    if caps:
        why_caps = (f"a lifted function's value is not its address: the lift "
                    f"prepends its captures ({caps}) as parameters, so a word "
                    f"holding {lifted_name!r} would have to carry an "
                    f"environment as well as a code address — and the capture "
                    f"ABI this path implements is a CALL-SITE rewrite in the "
                    f"scope that defines the closure, so there is nothing to "
                    f"pass the captures at here")
        repair = ("Return the results the `def` produces, or keep the call in "
                  "the function that defines it")
    else:
        why_caps = (f"even with nothing captured, a word holding "
                    f"{lifted_name!r} is a bare address that the return "
                    f"path cannot vouch for: {outer_name or 'the enclosing ' + repr(outer_name)}"
                    f" hands a caller a word whose calling convention is the "
                    f"lift's, and the caller's declaration cannot say so")
        repair = ("Return the results the `def` produces, or keep the call in "
                  "the function that defines it")
    return (f"{who}{name!r} is a nested `def`, and the build emitted it as "
            f"{lifted_name!r}: the lift renames a nested function to a "
            f"module-level symbol and strips it from this body, so the read "
            f"below is in its PRE-LIFT spelling and no table in the build "
            f"holds that spelling — this is a rename the reader has not been "
            f"told about, not a name the allocator lost. Handing it back is "
            f"refused for a second reason: {why_caps}. {repair}")


def function_value_refusal(name: str, fn_name: str) -> str:
    """Why a FUNCTION NAME cannot be read as a value, in its own words.

    `def dbl(x): …` followed by `call2(dbl, 5)` — or by `var g = dbl` — reaches
    the name as an ordinary read, and the read finds no home for it because a
    function is not a local, a receiver field, or a folded module constant. The
    refusal that stood there was `unresolved_name_refusal`'s, whose `why` clause
    is *"the register allocator collected no home for it, so the emitter and the
    allocation walk disagree about this function's locals"*.

    **Every clause of that is false, and it is false in the direction that costs
    a reader the most.** The emitter and the allocation walk agree perfectly:
    both of them know `dbl` is not a local, which is why neither gave it one.
    What is true is that a first-class function has no representation on this
    path at all \u2014 one word is a value and a function is a code address, so there
    is nothing for the word to hold (`pointer_value_model` is what says what a
    word can and cannot denote). Measured on this tree, both spellings above
    were refused with the allocator sentence.

    So the message says what the construct is, which is the same repair
    `UNIMPLEMENTED_BUILTINS` and `FRAME_IDENTITY_CALLS` are: name the thing
    instead of the machinery that failed to hold it.

    **This function was defined TWICE in this module** — an earlier copy of it
    sat ~1700 lines up with its own wording ("is a function of this module read
    as a VALUE"), and Python's rebinding made that one dead, so two sentences
    for this refusal existed and only the second was ever spoken.  The dead copy
    is deleted and the one measurement only it recorded is kept here: the shape
    `workgroup_function[tile_size](offset)` in
    `std/algorithm/backend/tile.mojo`, where the callee is a PARAMETER of
    declared type `Some[Static1DTileUnitFunc]` and the brackets are a
    specialization of a function TYPE.  `specialization_call_refusal` refuses
    that call too, and is right to, but it answers a question about BRACKETS
    while the wall behind it is that the callee is a value at all — measured,
    both architectures: passing a function as an argument lands here, before any
    bracket is reached.  `test_formal_external_call.py`'s
    `no_module_level_name_is_bound_twice` is what keeps this file to one
    definition per name.
    """
    who = f"{fn_name}: " if fn_name else ""
    return (f"{who}{name!r} is a FUNCTION, and a function is not a value on "
            f"this path: it has no representation here \u2014 a value is one 64-bit "
            f"word and a function is a code address, so there is nothing for "
            f"that word to hold, and passing one as an argument, storing one in "
            f"a container, or returning one is refused rather than answered "
            f"with a number that means nothing. `formal/hostmods/` has no "
            f"module that hands back a callable for the same reason "
            f"(`bugs/formal/FORMAL_functools_is_unbuildable_as_a_host_module.md`). Call "
            f"it directly, or move the work into a `def` and pass its results")


def member_chain_text(expr) -> str:
    """`a.b.c` for a MemberExpr chain, spelled the way the source spells it.

    The read of the base for a diagnostic. `_member_slot_key` (per backend)
    answers the same question for the ACCESS path and returns None when the
    root is not a plain name — which is exactly the case a refusal is about,
    so the two cannot be one function.

    THE member-chain spelling, and the reason there is one: three refusals in
    two files used to spell this three ways, and a diagnostic that can print
    `a.b` and `a.b.…` and `a.b?` for the same source is a diagnostic a reader
    has to learn three conventions to read.  `formal/build.py` was the third
    copy; it now calls this."""
    parts = []
    node = expr
    while isinstance(node, F.MemberExpr):
        parts.append(node.member)
        node = node.obj
    parts.append(node.name if isinstance(node, F.IdentExpr) else "…")
    parts.reverse()
    return ".".join(parts)


def receiver_shape_text(expr) -> str:
    """The receiver EXPRESSION, spelled the way the source spells it.

    The sibling of `member_chain_text` for the shapes that function cannot
    print: a subscript (`messages[i]`), a call result (`make_x()`), a parenthesised
    or otherwise parenthesised expression. `member_chain_text` renders those as
    `…`, which is right for an access PATH and useless for a sentence about the
    source — and a refusal whose whole job is to show the reader the expression
    they wrote cannot be the one that cannot print it.
    """
    if isinstance(expr, F.SubscriptExpr):
        base = receiver_shape_text(expr.obj)
        idx = expr.index
        if isinstance(idx, (F.TupleExpr, F.ListExpr)):
            inner = ", ".join(receiver_shape_text(e) for e in idx.elements)
            return f"{base}[{inner}]"
        return f"{base}[{receiver_shape_text(idx)}]"
    if isinstance(expr, F.CallExpr):
        args = ", ".join(receiver_shape_text(a) for a in expr.args)
        return f"{receiver_shape_text(expr.func)}({args})"
    if isinstance(expr, F.MemberExpr):
        return member_chain_text(expr)
    if isinstance(expr, F.IdentExpr):
        return expr.name
    # A LITERAL, spelled as the source spells it. Without this a subscript
    # prints its index as the node's class name — `bs[IntLiteral].get()` for
    # `bs[0].get()` — which is a message about the compiler's data model in a
    # sentence whose whole job is to quote the reader's own code back.
    #
    # A STRING keeps its quotes, for the same reason and because the case is
    # measured: `not_a_code_address_refusal` is handed this text so the reader is
    # shown the read they wrote, and a source that says `d["a"]` is not shown by
    # `d[a]` — the bracket is then a variable subscript, which is a DIFFERENT
    # program, and this function's own docstring claims it is "spelled the way
    # the source spells it". The quotes go on as the source most often spells
    # them (a `"` in the text forces the `'`) because a refusal cannot report
    # which quote character was used: the parser keeps the token without it.
    if isinstance(expr, F.StringLiteral):
        value = getattr(expr, "value", None)
        if not value:
            return '""'
        quote = "'" if '"' in value else '"'
        return f"{quote}{value}{quote}"
    for cls, attr in ((F.IntLiteral, "raw"), (F.FloatLiteral, "raw"),
                      (F.BoolLiteral, "value"),
                      (F.NoneLiteral, None)):
        if isinstance(expr, cls):
            if attr is None:
                return "None"
            value = getattr(expr, attr, None)
            return str(value) if value not in (None, "") else "0"
    return type(expr).__name__


# Why an ESTABLISHED receiver type still cannot be passed as a receiver here,
# one sentence each.  Keyed by the `why` `_call_receiver_verdict` returns, and
# a table rather than an `if` chain because every one of these is a refusal a
# reader has to act on, and the action is different in each case: two of them
# want a different METHOD, one wants a different STRUCT, one is a value-model
# question shared with every other multi-field receiver, and one is a property
# of the program rather than of the backend.
CALL_RECEIVER_WHY = {
    "construction":
        "a CONSTRUCTION is not a value this path can pass as a receiver: the "
        "struct is named, and the fields a one-word struct's receiver IS live "
        "in a frame, which only a construction that PLACES one brings up — a "
        "struct of plain words has no frame to take the address of, so the word "
        "the callee would read is not a number the source wrote",
    "construction_frame":
        "a construction IS placed and its frame is brought up before the "
        "method reads it, and the bring-up RUNS the constructors it can — but "
        "this one it cannot account for: {reason}. So the frame the callee "
        "would read is not the frame the source describes, which is the one "
        "outcome this path may not produce. Assign the field after binding the "
        "construction to a local, which is the same program with the stores "
        "written where they are written",
    "frame":
        "a struct of {n} fields has its receiver as the ADDRESS of a frame "
        "rather than as a word, and this call site has no frame to take the "
        "address of — that is a change to the value model the two backends "
        "AND the Lean proof share, and it is refused everywhere else for the "
        "same reason",
    "undeclared":
        "the struct's own DECLARATION does not declare a method of that name, "
        "and lifting to the struct that does declare it would call a "
        "different function than the source names",
    "ambiguous":
        "the struct declares that method more than once, and nothing in the "
        "call says which of the declarations was meant",
    "derived":
        "a struct of this unit DERIVES from it and declares the method too, "
        "so the declaration names the base's method while the value may be "
        "the derived one",
    "receiverless":
        "the method takes no receiver — a `@staticmethod` — and this path "
        "binds one by position, so the call would carry none. That is fine "
        "for a receiver that is a NAME, and not for one that is a CALL: "
        "passing no receiver means the call is never EVALUATED, and dropping "
        "it would remove its effect from the program — which is a silent "
        "wrong answer rather than a refusal",
    "other module":
        "this module declares no struct of that name. A method of a struct "
        "another module declares is a symbol in THAT module's library, and "
        "this unit neither imports it nor compiles it, so there is nothing "
        "here for the call to bind — the receiver's type is written down and "
        "the CALLEE is what is missing",
}


def subscript_receiver_method_refusal(member: str, receiver_text: str,
                                     owners: dict, fn_name: str,
                                     established: tuple = None) -> str:
    """A method called on a receiver whose STRUCT cannot be used — refused by
    name here rather than emitted as a dangling call.

    `recv.m(a)` is lifted to `Struct_m(recv, a)` whenever `recv` is a bare name,
    because then dispatch is BY NAME: `owners` says which struct declares `m`,
    and a name two structs declare is ambiguous and is not lifted at all. A
    receiver that is anything else — `bs[0].get()`, `cells[i].scaled(k)`,
    `make_x().n` — has no such table entry, so the lift does not happen and the
    dotted spelling falls through to the ordinary call path, which emits a call
    against a symbol spelled after the METHOD NAME.

    That is the failure this refusal exists for, and it is worse than a wrong
    number because it is usually silent: the symbol either binds nothing, and
    `_audit_bound_symbols` reports it at the LINK LINE (\"the image would bind 1
    symbol(s) that nothing provides: get\" — a diagnosis about where the symbol
    should have come from, for a defect in how the call was written), or it
    collides with a real symbol — a C library function, a gimple runtime entry
    point — and the image binds THAT and computes a plausible wrong answer with
    nothing anywhere reporting a failure. The link audit catching the first case
    is luck, not design.

    So the message names the construct and the missing fact rather than the
    symptom, and says what would establish it: the receiver's type. It does NOT
    claim the receiver's type cannot be known — for `bs[0]` where `bs` is a list
    literal of `Box()`, it is statically obvious and inferring it is real work
    this function is not (it needs one \"what struct is this expression\"
    predicate shared with `frame_opaque_position_refusal`, so the two cannot
    disagree about when a receiver's type is known). Until that predicate
    exists, this is the honest answer: refused, naming what is missing.

    `owners` is asked only to establish that `member` IS a method of a struct in
    this module — without that, every dotted call whose receiver is not a plain
    name would be refused here, including `mod.f()` across a dylib boundary and
    the `external_call` templates, both of which are correct and have their own
    answers. **An AMBIGUOUS name is therefore a decline, not a sentence**, and the
    analysis's own `frame_opaque_position_refusal` answers that one instead —
    which is the right order, because with two structs declaring `m` even a
    receiver with a known type would not settle the callee. Measured, the two
    halves of that question on the same shape: `mk().take(r)` with `take`
    declared once is refused here, and with `take` declared by `A` and `B` it is
    refused there (`test_formal_run.py`'s
    `byref_refuse_an_opaque_position_as_opaque` and
    `…_when_the_method_name_is_ambiguous`).

    It now answers for a CALL RESULT as well as a subscript, since 2026-10-03;
    `formal/build.py`'s `_receiver_shape_refusal` asks it of both, and the two
    spellings of either shape (`recv.m(x)` and `recv.m[T](x)`) get this one
    sentence.

    **`established` is `(struct, why)` and it is what keeps this sentence
    honest on a receiver whose type IS known.**  Until 2026-10-04 the type was
    read only from a binding, an element table or a subscript, so "what is
    missing is the receiver's TYPE" was true of every case that reached here.
    `formal/build.py::_call_receiver_verdict` now reads a CALL's declared
    return type as well, and two of the shapes it declines are declined for a
    reason that has nothing to do with the type — a construction whose frame is
    never built, and a struct whose receiver is a frame address.  For those,
    printing the old sentence would send a reader to declare a type the source
    already declares, which is the "false about the file" outcome this file's
    own header calls worse than no message.  So `why` selects one sentence from
    `CALL_RECEIVER_WHY` — which lives HERE rather than in the build pass that
    produces the keys, because this is the layer that turns a key into English
    and the two must not be able to disagree about which keys exist.
    """
    who = f"{fn_name}: " if fn_name else ""
    owner = owners.get(member)
    if established and established[1] is not None:
        why = established[1]
        named = (established[2] if len(established) > 2
                 else getattr(established[0], "name", str(established[0])))
        # `reason` is the FOURTH element and only the `construction_frame` row
        # uses it: that refusal has to name WHICH fact about the bring-up is
        # incomplete (a nested struct's `__init__`, a chain deeper than the
        # layout places) while the sentence above it still has to say the
        # struct's own NAME, which is the third. Two slots, two facts, and
        # neither is spelled twice.
        detail = CALL_RECEIVER_WHY[why].format(
            n=struct_field_count(established[0]) if why == "frame" else 0,
            base=named,
            reason=established[3] if len(established) > 3 else "").rstrip()
        return (f"{who}`{receiver_text}.{member}(…)` cannot be lowered: "
                f"`{receiver_text}` is a `{named}`, and that IS established — "
                f"this is not a missing-type refusal. What this path cannot do "
                f"is use it as the receiver here, because {detail}.")
    return (f"{who}`{receiver_text}.{member}(…)` cannot be lowered: dispatch "
            f"here is BY NAME, so a method call is lifted to "
            f"`{owner}_{member}(receiver, …)` from the name alone — and "
            f"`{receiver_text}` is not a bare name, so there is no name to lift "
            f"from. What is missing is the receiver's TYPE: this path has no "
            f"inference that answers \"which struct does `{receiver_text}` "
            f"hold?\", and dispatch is by name rather than by type, so the "
            f"callee cannot be named. Declaring it is the same program with an "
            f"answer — give the receiver a local of a declared struct type, or "
            f"bind it to one (`var x = T()`, `def f(v: T)`) so the lift has a "
            f"name to work from. A caller-spelled subscript receiver is a "
            f"narrower question than it looks: where the source states the "
            f"element type — a list literal of `T()`, or a parameter declared "
            f"`List[T]` — `receiver_struct` answers it and the lift runs "
            f"(`formal/build.py::_subscript_receiver_target`). It is only the "
            f"element type nothing in the source names that reaches this "
            f"refusal.")


def subscript_chain_text(expr) -> str:
    """`q[0]`, `REGISTRY[s.name]`, spelled the way the source spells it.

    A separate function from `member_chain_text` rather than a branch of it, for
    the reason that function's docstring gives: the diagnostic is read by
    someone looking for the source they wrote, and `q.?` is not it.

    Which is a thing that was got wrong here and is worth recording: the first
    version printed `str(index)`, and a MemberExpr index has no `__str__`, so
    `REGISTRY[s.name] = spec` was reported as

        is stored through "REGISTRY[MemberExpr(obj=IdentExpr(name='s', line=255, ..."

    which is the AST.  A reader sent to a repr has to go and find the source to
    work out what the compiler was looking at, which is the whole cost the
    spelling exists to remove.  `expr_spelling` is the one spelling function
    and this delegates to it, so a shape neither of them has a short name for
    degrades to the same honest placeholder rather than to a repr.

    HERE and not in `formal/build.py` because `expr_spelling` lives here, and a
    spelling function that reaches back up into the build pass for its own
    subscript case is the duplication this consolidation removed."""
    base = expr.obj if isinstance(expr, F.SubscriptExpr) else expr
    idx = expr.index if isinstance(expr, F.SubscriptExpr) else None
    if isinstance(idx, (F.TupleExpr, F.ListExpr)):
        inner = ", ".join(expr_spelling(e) for e in (idx.elements or []))
    elif isinstance(idx, F.IntLiteral) and getattr(idx, "raw", None) == "":
        # A PLACEHOLDER index, and the source had no 0 there: the parser keeps
        # `IntLiteral(value=0, raw='')` for a subscript whose contents it does
        # not keep in `index` — an empty `x[]`, a star-unpacked `Tuple[*Ts]`,
        # and a keyword-attribute subscript (see `_parse_subscript`'s three
        # `raw=''` constructions). Spelling it `Tuple[0]` states that the file
        # contains a 0, which is the kind of false claim this function exists to
        # avoid, so it is spelled as the placeholder it is — the same `{…}`
        # convention a dict display already uses here.
        inner = "…"
    else:
        inner = expr_spelling(idx)
    if isinstance(base, F.IdentExpr):
        return f"{base.name}[{inner}]"
    if isinstance(base, F.MemberExpr):
        return f"{member_chain_text(base)}[{inner}]"
    return f"[{inner}]"


def expr_spelling(node) -> str:
    """The source's own spelling of an expression, as far as a name needs one.

    A refusal that quotes `CallExpr` where the source wrote `mid(1)` sends the
    reader to the AST to find the call, which is the opposite of what a
    diagnostic quoting a call site is for.  A shape with no short spelling is
    named by its type, which is at least a true statement and is obviously a
    placeholder to anyone who reads it.

    Lives here, beside `member_chain_text` rather than in `formal/build.py`,
    because the model now needs it for a refusal of its own
    (`struct_field_assigned_type` has to name the value it could not type) and
    a model function must not reach up into the build pass for a string."""
    if isinstance(node, F.IdentExpr):
        return node.name
    if isinstance(node, F.CallExpr):
        # The callee is spelled by the same two helpers as any other position,
        # so `TypeList.reduce[Self._mapper]()` and `Intrinsics.read[0]()` come
        # out as themselves. Restricting this arm to a bare `IdentExpr` callee
        # printed `CallExpr` — a bare placeholder, in a diagnostic whose whole
        # job is to name the thing — for every specialization in the new-modular
        # stdlib (`_integral_type_of[Self.dtype]()`, 100+ of them).
        return (f"{expr_spelling(node.func)}"
                f"({', '.join(expr_spelling(a) for a in (node.args or []))})")
    if isinstance(node, F.UnaryOp):
        # `-1` is an IntLiteral inside a UnaryOp, and `type(node).__name__` is
        # what the fallback below said about it — "UnaryOp" in a sentence about
        # a class attribute whose value the reader is being sent to look at.
        word = "not " if node.op == "not" else node.op
        return f"{word}{expr_spelling(node.operand)}"
    if isinstance(node, F.MemberExpr):
        return member_chain_text(node)
    if isinstance(node, F.SubscriptExpr):
        # `f[1]`, through the one function that spells a subscript — the same
        # reason `member_chain_text` exists. Without it a diagnostic about a
        # comptime specialization prints `SubscriptExpr(r, 1)`, which is the AST
        # and not the source, and the reader has to go and find the call.
        return subscript_chain_text(node)
    if isinstance(node, F.SliceExpr):
        # `a[0:2]`, because a slice is an ELEMENT of a comprehension often
        # enough to reach `comprehension_element_blob_refusal`, and quoting
        # `SliceExpr` there named the AST rather than the reader's own line —
        # the same reason the Comprehension arm below exists. Omitted bounds
        # print empty, which is how the source spells them.
        def _bound(v):
            return "" if v is None else expr_spelling(v)
        inner = f"{_bound(node.start)}:{_bound(node.stop)}"
        if node.step is not None:
            inner += f":{expr_spelling(node.step)}"
        return f"{expr_spelling(node.obj)}[{inner}]"
    if isinstance(node, (F.ListExpr, F.TupleExpr)):
        inner = ", ".join(expr_spelling(e) for e in (node.elements or []))
        return (f"[{inner}]" if isinstance(node, F.ListExpr)
                else f"({inner})")
    if isinstance(node, F.SetExpr):
        # `{1, 2}` and not `SetExpr`.  An arm the build pass's older copy carried
        # and this one did not, so it is spelled here rather than kept as a second
        # implementation of the function — a set literal in a refusal about a
        # stored or assigned value is a set literal the reader can find in their
        # own file.
        return f"{{{', '.join(expr_spelling(e) for e in (node.elements or []))}}}"
    if isinstance(node, F.BinaryOp):
        # `a + b` and not `BinaryOp`, for the reason the build pass's copy spelled
        # out before it was deleted: a message that read `G is read in bump() at
        # BinaryOp` is a true statement, a placeholder, and useless, because the
        # reader's question is WHICH read.  Every refusal that quotes a value goes
        # through this one function, so the fix belongs here rather than in each
        # caller — and here is also the only place it can live now that there is
        # one function.
        return (f"{expr_spelling(node.left)} {node.op} "
                f"{expr_spelling(node.right)}")
    if isinstance(node, F.StringLiteral) and isinstance(node.value, str):
        # QUOTED, and that is the whole of this arm: the `("value", "name")`
        # loop below prints `str("a")`, which is `a` — a bare name the file does
        # not contain, where the source wrote `"a"`. A diagnostic that
        # reproduces the file with a token missing sends the reader looking for
        # an identifier, and this function's contract is that its output is the
        # source's own spelling. `repr` is the closest available rendering for
        # the general case (it is what the source would have to write for the
        # same characters) and `b'…'` is kept for the bytes form so a bytes
        # literal is not quoted as text.
        if getattr(node, "is_bytes", False):
            return "b" + repr(node.value.encode("utf-8", "surrogateescape"))
        return repr(node.value)
    if isinstance(node, F.DictExpr):
        return "{…}"
    if isinstance(node, F.Comprehension):
        # `[<element> for …]` / `{<k>: <v> for …}`, because a comprehension is
        # the ELEMENT of a comprehension often enough to matter — the nested
        # case is what `comprehension_element_blob_refusal` fires on, and a
        # diagnostic that quoted `Comprehension` there named the AST rather
        # than the line the reader has open.
        kind = {"dict": "{…}", "set": "{…}"}.get(getattr(node, "kind", None),
                                                 "[…]")
        return f"{kind} for …"
    if isinstance(node, F.SliceExpr):
        # `a[0:2]` and not `SliceExpr`, for the same reason the Comprehension
        # arm above exists: a slice IS a comprehension element often enough to
        # matter, and `comprehension_element_blob_refusal` fires on the one whose
        # base carries a scratch address. `SliceExpr` names the AST and sends the
        # reader looking for it rather than at the line. An omitted bound is left
        # blank (`a[1:]`), which is how the source spells it.
        bounds = ["" if b is None else expr_spelling(b)
                  for b in (node.start, node.stop, node.step)]
        body = (f"{bounds[0]}:{bounds[1]}:{bounds[2]}" if bounds[2]
                else f"{bounds[0]}:{bounds[1]}")
        return f"{expr_spelling(node.obj)}[{body}]"
    for attr in ("value", "name"):
        v = getattr(node, attr, None)
        if isinstance(v, (str, int, float, bool)):
            return str(v)
    return type(node).__name__


# One clause, shared by the two refusals that describe the same defect from two
# places: `field_access_refusal` below, which is raised by an emitter that has
# only a slot key, and `undeclared_linked_struct_refusal` after it, which is
# raised by the build pass where the type IS known and can name the library.
# Written once because it is a WARNING rather than a diagnosis — both sentences
# are advice about what not to do, and a fix that corrected one of them and not
# the other would leave a program that re-declares the struct looking like a
# program that fixed its bug.
RE_DECLARE_IS_A_DIFFERENT_TYPE = (
    "Do not re-declare the struct here — that is a different type with the "
    "same name, and the layout the library's methods use would not be it")


def field_access_refusal(name: str, fn_name: str, root: str,
                         holder: bool) -> str:
    """The diagnostic for `root.field` where nothing says what `root` holds.

    A different question from `unresolved_name_refusal` and a different wrong
    answer, which is why it gets its own words. `b.z = 1` with `b` a plain
    parameter is a field STORE with no home: arm64's `_store_var` used to fall
    through to `mov x19, src` and the store landed in the register the NEXT
    function reads as its first parameter — wave 5's rule at its most literal,
    a missing branch here is a dropped store, not a wrong value. x86-64's
    `_load_var` read an immediate zero for the same program. Both were silent
    and both were wrong, and a case that checked only a return value never
    noticed.

    `holder` says whether the build DID recognise `root` as a frame receiver —
    when it did, a disagreement is a bug in the frame analysis and the message
    says so; when it did not, the honest statement is that this path has no
    type inference, so a name this image cannot classify cannot be classified.

    **What this function deliberately does NOT say.** It is raised from an
    emitter's slot-allocator fall-through, and an emitter is handed a SLOT KEY
    and nothing else: it cannot see how `root` was bound, only whether the frame
    analysis recognised it. The first version of this message asserted "`root` is
    bound here as a parameter", which is a claim about the caller's source that
    the raiser had no way to know and which was false about a real program —
    `var b = Bag(); b.n = 4` against a `--link-dylib` library whose source was
    no longer readable, where the binding is a construction and the struct is
    declared in a file this build does not have. So the
    message states what the raiser knows — the base is not classified, and a
    field needs a classification to be lowered — and the REPAIRS are the two
    that are actually available, which is the other half of the same finding:
    "bind the base from a constructor THIS MODULE declares" is
    impossible to follow for a struct this module does not and cannot declare,
    and suggesting the reader declare it here would be worse than useless — it
    would be a DIFFERENT type with the same name, and the frame the library's
    methods are called on would not be it. That other half now has its own
    message, `undeclared_linked_struct_refusal`, raised by the build pass where
    the construction is and the library is known; this one is what is left when
    the base is not a construction this pass can see the type of."""
    who = f"{fn_name}: " if fn_name else ""
    if holder:
        return (f"{who}{name!r} is a field of {root!r}, which the build "
                f"DOES recognise as a frame receiver, so a field access on it "
                f"should be a load from `[base, #8k]`. It reached the ordinary "
                f"local path instead, which means the frame analysis and the "
                f"emitter disagree about this function's receivers — a "
                f"compiler bug rather than a limit of the path, and refused "
                f"rather than emitted so it cannot be a silent wrong store")
    return (f"{who}{name!r} is a field access through {root!r}, and this "
            f"path has no way to say what {root!r} holds. A field is lowered "
            f"three ways and which one applies is decided by the BINDING of "
            f"the base, not by a type: a one-field struct's receiver IS its "
            f"field, a multi-field struct's receiver is the address of a "
            f"frame, and an ordinary word is an integer — and nothing this "
            f"image can see about {root!r}'s binding establishes which, so a "
            f"store to the field with no home lands in a register the next "
            f"function reads as its first parameter. Bind the base from a "
            f"constructor whose declaration THIS IMAGE can see (`x = S()`): an "
            f"`import` brings the declaration with it, and a `--link-dylib` "
            f"library brings one when the source it was built from is still "
            f"readable. {RE_DECLARE_IS_A_DIFFERENT_TYPE}")


def undeclared_linked_struct_refusal(struct_name: str, owners: list,
                                     recorded_source: str = None) -> str:
    """`S()` where S is a linked library's struct and this image has no S.

    The build-pass half of `field_access_refusal`'s finding, and the half that
    can NAME the library: an emitter's slot-allocator fall-through is handed a
    slot key and nothing else, so its message can only say "this path has no
    way to say what the base holds" — which is true and sends the reader after a
    type inference this backend does not have, when the actual fact is one hop
    away and checkable (`bugs/formal/FORMAL_field_access_refusal_names_the_wrong_
    module.md`). This one is raised where the construction `S()` itself is, and
    it reports what is actually missing: a DECLARATION, whose field list and
    frame layout are read from the module's source.

    Three facts in the text, each of which the reader can check:

      * a library on this link line DOES have the struct — `owners` is derived
        from that library's own `kind: "method"` exports, so "nothing defines
        this name" is not what is wrong, and the bind audit's message says the
        opposite;
      * what is missing is the declaration, and `recorded_source` is where the
        manifest says it was read from, so "the source is gone" is a fact with a
        path in it rather than a guess;
      * the two repairs are the two that exist, and neither of them is
        "declare it here" — a struct re-declared in the importing file is a
        DIFFERENT type with the same name, whose layout is not the one the
        library's methods were compiled against. That clause is shared with
        `field_access_refusal` rather than written twice.
    """
    libs = []
    for o in owners or ():
        if o["library"] not in libs:
            libs.append(o["library"])
    module = ""
    for o in owners or ():
        if o.get("module"):
            module = o["module"]
            break
    one = libs[0] if len(libs) == 1 else (f"{len(libs)} libraries on this "
                                          f"link line")
    where = ""
    if recorded_source:
        where = (f" The manifest records that source as {recorded_source!r}, "
                 f"which this build cannot read.")
    repair = (f"`from {module} import {struct_name}`" if module
              else f"an import that brings `{struct_name}`'s declaration")
    return (f"{struct_name}() constructs a struct this image has no "
            f"DECLARATION for: `{struct_name}` is not declared in this file, "
            f"and no module this file imports declares it. A linked library "
            f"does provide its methods — {one} exports "
            f"{owners[0]['signature']} — so this is not a name nothing "
            f"defines; what is missing is the type, and a field list and a "
            f"frame layout are read from the module's source rather than from "
            f"the symbol table.{where} Two repairs, and only two: rebuild the "
            f"library where this build can read the module's source, so its "
            f"manifest records a path this build can open; or link the module "
            f"by IMPORT ({repair}), which brings the declaration with it. "
            f"{RE_DECLARE_IS_A_DIFFERENT_TYPE}")


def member_base_node(expr):
    """The innermost node of a `a.b.c` chain: the BASE, as an expression.

    The emitter needs the node rather than the text because the base is
    EMITTED before the refusal that follows it — see `member_access_refusal`
    for why that ordering is the whole point."""
    node = expr
    while isinstance(node, F.MemberExpr):
        node = node.obj
    return node


def member_base_text(expr) -> str:
    """The BASE of a `a.b.c` chain, spelled the way the source spells it.

    `member_chain_text` is the sibling that spells the whole PATH, and it
    renders a base it cannot name as `…` — which is right for a path (`….x` says
    "a field, somewhere") and useless in a sentence about the reader's own code,
    because `field_access_refusal`'s whole subject IS the base: it says what
    this path cannot say about it.

    **`spelled`, not `receiver_shape_text`**, and the two disagreed about the
    same base in one sentence when this was first written — `g(...).x` is a field
    access through `g()` — because each has its own partial table for the shapes
    a chain's root can be. `spelled` is the one that spells an arbitrary
    expression (it is what the access itself is spelled with), so spelling the
    base the same way is what makes the two halves of the sentence agree."""
    return spelled(member_base_node(expr))


def member_access_refusal(expr, fn_name, frame_holders) -> str:
    """`field_access_refusal` for a MemberExpr, with the base spelled out.

    **One function for the five sites that raise it**, which is the whole point
    of this existing: the two backends' member fall-throughs each spelled the
    chain themselves, in the same three lines, with `chain.split(".", 1)[0]` for
    the root — so a base that is not a plain name (`a[0].x`, `g().x`, `C.A.x`)
    printed `…` as BOTH the access and its base, and a reader could not tell
    which expression the refusal was about. The ACCESS is `spelled(expr)` and the
    BASE is `member_base_text(expr)`, the two spellings this module already has,
    and they agree with what the old code produced for every chain rooted at a
    name — so the messages every existing case pins (`is a field access through
    'b'`) are unchanged, and a deep chain keeps every hop (`h.f.g`, not `h.g`).

    `frame_holders` is the CALLER's frame-holder set, which is per-emission and
    is the only thing that decides `holder` in the underlying message: a build
    that DID recognise the root as a frame receiver and then refused is a
    disagreement between two analyses, and that is a different sentence from
    "this path cannot classify it".

    **The caller emits the base FIRST, and that ordering is load-bearing.**
    Emitting a base is how a base that is itself unanswerable says so:
    `p.value().b` reaches this through a call the emitter would refuse with a
    POINTER message ("a STRUCT, and a struct's value on this path is a frame
    ADDRESS"), and emitting the base first is what surfaces that instead of this
    one. It is also what the code did before the refusals existed — arm64's arm
    evaluated the base "for its side effects" and then answered 0, so the base's
    refusal came out of that evaluation — and dropping the evaluation when the
    refusal was added replaced a specific message with a generic one. So
    `member_base_node` is what each site emits, and this function is what it
    raises once the base has had its say."""
    return field_access_refusal(
        spelled(expr), fn_name or "<module>", member_base_text(expr),
        member_base_text(expr) in (frame_holders or ()))


def aug_assign_target_refusal(got: str) -> str:
    """The fallback for an augmented-assignment target that is not a NAME, a
    member of a receiver, or a subscript — ONE sentence for both backends.

    A `MemberExpr` target that is not a frame slot of this function is a
    DIFFERENT question and has its own refusal, the one above: the real premise
    there is the binding of the base, and this message would say "not a plain
    name" about an expression that is not the problem. So the two are kept apart
    on purpose, and this one is only reachable for a node type with no lowering
    at all.

    Both backends reach it, and they used to spell it differently — arm64 "must
    be a plain name", x86-64 "must be a plain name on the formal x86-64 path" —
    which is the same class of defect
    `bugs/formal/FORMAL_the_two_backends_refuse_different_constructs_in_the_same_
    function.md` is about: one construct, two sentences, and a reader has to
    guess which machine wrote it. The architecture is not named, for the reason
    `member_access_refusal` does not name one either: the two backends are ONE
    language implementation and a message that says which of them refused is a
    difference in this function rather than in the backend.

    `got` is the node's class name, and it is in the message because "this path
    cannot lower that" without saying WHAT is the sentence every reader has to
    go read the source for.
    """
    return (
        f"an augmented assignment target on this path must be a plain name, a "
        f"field of a receiver this function holds, or a subscript (got {got}); "
        f"a member whose receiver is not a frame slot of this function is "
        f"refused by `field_access_refusal` instead, because the question there "
        f"is the binding of the base rather than the shape of the target")




# ── A member read through a LITERAL base: no storage, so no field ────────────
#
# The one member base that needs no classification to rule out, and the two
# recognisers that rule it out. `formal/build.py` refuses the access in the
# SHARED pass and each backend's emitter refuses it again at the arm that used
# to read 0, so a construct that arrives by a route the build pass does not
# model is still stopped rather than answered; see
# `FORMAL_an_attribute_read_through_an_unclassified_base_reads_zero`
# for the measurement that made this a refusal on both architectures.


#: Every literal node class, in ONE tuple, so the two recognisers below and
#: every future reader agree on what "a literal" is. `StringLiteral` is in it
#: and is the one member of the list whose attribute reads are NOT all
#: AttributeErrors — `"ab".upper` is a bound method — which is why the message
#: has an arm of its own rather than one sentence for the whole family.
LITERAL_NODES = (F.IntLiteral, F.FloatLiteral, F.ImagLiteral, F.StringLiteral,
                 F.TstringLiteral, F.BoolLiteral, F.EllipsisLiteral,
                 F.NoneLiteral, F.DottedLiteral)


def is_literal_base(expr) -> bool:
    """True when `expr` is a literal, i.e. a base with no binding at all.

    The narrowest possible answer to "what does this base hold", and the reason
    it is worth its own recogniser: every OTHER unclassified base is genuinely
    ambiguous here (a one-field struct's receiver IS its field, a multi-field
    struct's receiver is a frame address, an ordinary word is an integer), so
    the emitters cannot refuse those without refusing real programs. A literal
    is not ambiguous — it is the base's own value, in the register or the
    `__TEXT` slot it is spelled into — so there is no program this refusal
    costs. Measured over the 610-file Mojo stdlib and this tree's own 118
    `.mojo` files: exactly ONE value-position member read through a literal,
    `std/_gpu/globals.mojo:111`'s `"nvvm.maxntid".value`, against 185 string
    and 20 integer METHOD calls on a literal, which are calls and are not this
    function's business (`_call_receivers`)."""
    return isinstance(expr, LITERAL_NODES)


def literal_base_member_refusal(base, member, fn_name) -> str:
    """Why `<literal>.<member>` cannot be answered: two sentences, one per kind.

    **The two arms are the whole of this function**, because "a literal has no
    fields" is true and useless on its own: for a string literal the read is a
    BOUND METHOD, which exists and is a real Python value this path has no
    representation for, and for a number it is either an AttributeError or one
    of the number's own properties (`(7).real`, `(7).denominator`,
    `(7).bit_length`) — which are properties OF THE VALUE and not fields of an
    object, and which this path lowers in neither direction. Measured on this
    tree before the refusal: `(7).foo` and `C.A.value` both printed `0` on
    arm64 while CPython raises `AttributeError` for both, and `f = "ab".upper`
    printed `(null)`.

    Shared because both backends read it, and because the alternative is what
    this replaced: x86-64's emitter arm and arm64's said the same thing about
    the same program in different words, and one of them said nothing at all.

    **The chain is spelled HERE rather than passed in**, because the only base
    this is ever called for is a literal, and the spelling of a literal is
    exact: `member_chain_text` renders any base it cannot name as `…`, so the
    caller's version of this sentence said `….foo` about `7.foo` — a message
    that names neither the number nor the field it is about."""
    who = f"{fn_name}: " if fn_name else ""
    chain = f"{spelled(base)}.{member}"
    if isinstance(base, (F.StringLiteral, F.TstringLiteral)):
        return (
            f"{who}{chain} is a METHOD REFERENCE on {spelled(base)} — "
            f"{member!r} bound to a string — and a value-position method "
            f"reference is a bound method, and a method is not a word: there is "
            f"no slot to read it out of and nothing to store it in, so this path "
            f"has no representation for it. Call it "
            f"({spelled(base)}.{member}(...)), which is a receiver and a call "
            f"— the method path, which decides what it can lower and refuses "
            f"the rest — or write the operation out where it was used"
        )
    return (
        f"{who}{chain} reads {member!r} through {spelled(base)}, which is a "
        f"LITERAL: there is no object behind it, no storage and no fields, so "
        f"there is no word here to read. Python's answer for a member a number "
        f"does not have is an AttributeError, and the members it does have "
        f"({spelled(base)}.real, {spelled(base)}.denominator, "
        f"{spelled(base)}.bit_length, …) are properties OF THE VALUE rather "
        f"than fields of an object, which this path lowers in neither "
        f"direction — it has no attribute lowering for a number at all. This "
        f"used to answer the word 0, which is a plausible-looking number and "
        f"not the program's: put the value in a name and read the attribute "
        f"from there, which is the same program where the attribute is a "
        f"named thing rather than a silent zero"
    )




# ── How a call's arguments bind: the ONE shape, read by everything ─────────
#
# `FunctionDef.params` is a flat `[(name, type)]` list in which a variadic
# parameter is spelled with its star — `*args` and `**kwargs` — and
# `kwonly` lists the names after a bare `*`. That is the whole of the shape
# and the parser has always recorded it; nothing CONSUMED it, which is how
# `f(1, 2, r)` against `def f(x, *rest)` was read as three fixed parameters:
# `params` had two entries, `rest` was parameter index 1, and index 2 had no
# parameter at all. The refusal below is what the flat list is now read
# through, and it is deliberately ONE function with ONE output so there is no
# second spelling of "which argument lands on which parameter" to drift.


class ParamShape:
    """`def f(a, b, *rest, **kw, only=1)` as a binding shape.

    `fixed` is `[(name, type)]` in DECLARATION order; `vararg`/`kwarg` are the
    starred names or None, and `vararg_at`/`kwarg_at` are where each sat in
    the raw `params` list — which is what decides the position of everything
    after them, because a parameter written after `*rest` is KEYWORD-ONLY in
    the language and must not be reachable by position. `kwonly` is the parser's
    own record of the names after a bare `*`, which is the other spelling of
    the same fact.

    `positional` is the answer the callers actually want: the fixed parameters
    an ARGUMENT INDEX can land on, in index order. `has_default`/`defaults` are
    the callee's own, so a caller can fill a gap without a second mechanism.
    """

    __slots__ = ("fixed", "vararg", "kwarg", "vararg_at", "kwarg_at", "kwonly",
                 "has_default", "defaults", "at")

    def __init__(self, fixed, vararg, kwarg, kwonly, has_default, defaults,
                 vararg_at=None, kwarg_at=None, at_by_name=None):
        self.fixed = fixed
        self.vararg = vararg
        self.kwarg = kwarg
        self.vararg_at = vararg_at
        self.kwarg_at = kwarg_at
        self.kwonly = list(kwonly)
        self.has_default = has_default
        self.defaults = defaults
        # {name: index in the raw `params` list}, which is what separates a
        # positionally-bindable parameter from one written after a `*`.
        self.at = dict(at_by_name or {})

    @property
    def names(self):
        return [n for n, _t in self.fixed]

    @property
    def variadic(self) -> bool:
        return self.vararg is not None or self.kwarg is not None

    @property
    def positional(self):
        """`[name]` — the fixed parameters an argument INDEX lands on.

        Excludes every name written after the `*` (`kwonly` and anything at or
        past `vararg_at`), because in the language those are keyword-only: a
        positional argument that would land on one is a TypeError, and binding
        it anyway is a wrong answer rather than a missing one."""
        limit = self.vararg_at if self.vararg_at is not None else 1 << 30
        out = []
        for n in self.names:
            if n in self.kwonly:
                continue
            at = self.at.get(n)
            if at is not None and at > limit:
                continue
            out.append(n)
        return out

    def index_of(self, name: str):
        """The parameter index a keyword `name` binds to, or None.

        A starred name answers for its bare spelling too, which is what
        `pname.lstrip("*") == k` in the two backends did by hand and is the one
        thing here both are now reading."""
        for i, pname in enumerate(self.names):
            if pname == name or pname.lstrip("*") == name:
                return i
        return None


def function_param_shape(fn) -> ParamShape:
    """`fn`'s parameter list as a `ParamShape`. The single reader of the star.

    Reads `params` and `kwonly` and nothing else, so a default-argument callee
    (`param_has_default`/`param_defaults`, which the parser has always filled)
    is reported through the SAME shape as a variadic one rather than through a
    parallel table."""
    fixed, vararg, kwarg = [], None, None
    vararg_at = kwarg_at = None
    at_by_name = {}
    for i, p in enumerate(getattr(fn, "params", None) or []):
        if not (isinstance(p, (tuple, list)) and p and isinstance(p[0], str)):
            continue
        pname = p[0]
        ptype = p[1] if len(p) > 1 else None
        if pname.startswith("**"):
            kwarg = pname[2:] or None
            kwarg_at = i
        elif pname.startswith("*"):
            vararg = pname[1:] or None
            vararg_at = i
        else:
            fixed.append((pname, ptype))
            at_by_name[pname] = i
    return ParamShape(
        fixed, vararg, kwarg,
        getattr(fn, "kwonly", None) or (),
        dict(getattr(fn, "param_has_default", None) or {}),
        dict(getattr(fn, "param_defaults", None) or {}),
        vararg_at, kwarg_at, at_by_name)


def bind_call_arguments(name: str, fn, args: list, kwargs: list,
                        mappings=None) -> tuple:
    """`(slots, dropped, error)` — a call's arguments in positional form.

    THE one implementation of "which argument lands on which parameter", for
    both backends. It existed twice, once per file, and the two copies had
    drifted into a real hole: each returned `list(e.args)` unexamined whenever
    the call had no keyword arguments, so the arity check only ever ran on a
    call with keywords. `f(1, 2, r)` against `def f(x, *rest)` therefore passed
    three arguments into a one-parameter function with no diagnostic at all.

    `dropped` is the arguments that have NO register home — the positional tail
    a variadic callee's `*name` would receive, and any keyword a `**kwargs`
    would swallow. They are not discarded here: CPython evaluates EVERY argument
    expression before the call, so a dropped argument's SIDE EFFECT is
    observable even when the callee never reads its variadic parameter, and the
    emitter runs each of these for effect. This is the fix for a real
    wrong-but-exit-0 answer: `def f(x, *rest): return x` called as
    `f(1, g())`, where `g` prints, printed only `1` — `g` was never run —
    against CPython's `g-called / 1`. The old docstring here claimed the drop
    was "exactly what the language observes when the callee's body never reads
    its variadic parameter", and that was FALSE about the side effect; a body
    that READS the parameter is refused earlier (`formal/build.py::
    _refuse_variadic_reads`), so the value is unobservable but the evaluation is
    not.

    Three rules, and they are the language's:

      * an argument INDEX lands on `shape.positional`, in order. A parameter
        written after a `*` is keyword-only and is not in that list, so a
        positional argument that would reach one is "too many positional
        arguments" — which is what Python says, and which this used to accept
        silently;
      * a parameter with a DEFAULT fills its own gap from the callee's own
        table (`param_defaults`), and one without is a "missing required
        argument". Every omitted parameter that has a default is FILLED, not
        trimmed: the callee's prologue gives each of its parameters a register
        home, a parameter the body only reads is never assigned, and a home
        nothing wrote is whatever the caller left in that register. That was a
        real wrong answer, measured on the pre-change tree for
        `def f(x, y=10): return x + y` with `f(1) + f(1, 2)`: **76 on arm64
        and 68 on x86-64** where the source says 14, because `y` was read out
        of X20/R14 in both and the two disagreed about what was in it. The old
        comment here said "trailing optional parameters the caller omitted are
        dropped — the callee's prologue only consumes the registers actually
        passed", and the second half of that is the bug: it consumes ALL of
        them, it just only WRITES the ones it is passed;
      * everything from the variadic parameter's position onwards belongs to
        `*name` / `**name`, and there is no register for it. It is dropped from
        `slots` and returned in `dropped` so the emitter can still EVALUATE it:
        the callee's body cannot read the value (`formal/build.py::
        _refuse_variadic_reads` refuses a body that does), but CPython runs the
        expression, so its side effect has to happen. So the drop is not a gap
        in this function: it is the placement decision, and the evaluation is
        put back at the call site rather than lost."""
    shape = function_param_shape(fn)
    positional = shape.positional
    # A `**` SPREAD is folded in before the arity is counted, for the reason
    # `_unspread_keyword_mappings` gives: the spread arrives in `args`, so
    # counting it as a positional both invented an argument (and, with one fewer
    # keyword, reported `multiple values for argument` about a duplicate the
    # source does not contain — measured) and put a mapping where a value
    # belonged.
    args, kwargs, spread_refusal = _unspread_keyword_mappings(
        list(args or []), list(kwargs or []), f"call {name}()", mappings)
    if spread_refusal is not None:
        return None, [], spread_refusal
    slots: list = list(args or [])
    dropped: list = []
    if len(slots) > len(positional):
        if not shape.variadic:
            return None, [], (f"call {name}(): too many positional arguments "
                              f"({len(slots)} for {len(positional)} "
                              f"parameter(s)"
                              + (f"; the parameters are {positional}"
                                 if positional else ")"))
        # A variadic callee: the arguments past the fixed ones are `*name`'s
        # and have no register home. Kept in `dropped`, in SOURCE ORDER, so the
        # emitter evaluates them for their side effects. See the docstring.
        dropped.extend(slots[len(positional):])
        slots = slots[:len(positional)]
    slots.extend([None] * (len(positional) - len(slots)))
    for k, v in kwargs:
        idx = shape.index_of(k)
        if idx is None or shape.names[idx] not in positional:
            if shape.kwarg is not None:
                # `**kwargs` swallows it; no register to put it in, but the
                # VALUE is still evaluated by CPython, so it is kept in
                # `dropped` for the same reason as the positional tail.
                dropped.append(v)
                continue
            return None, [], f"call {name}(): unexpected keyword argument {k!r}"
        if idx < len(args):
            return None, [], (f"call {name}(): multiple values for argument "
                              f"{k!r}")
        if slots[idx] is not None:
            return None, [], (f"call {name}(): multiple values for argument "
                              f"{k!r}")
        slots[idx] = v
    slots, err = _fill_gaps(name, shape, positional, slots)
    return slots, dropped, err


def _fill_gaps(name: str, shape, positional: list, slots: list) -> tuple:
    """Fill every unfilled slot from the callee's own defaults, or say which.

    NO trailing trim, which is the whole fix.  An omitted parameter with a
    default is PASSED, because the callee gave it a register home whether or
    not the caller mentions it; and an omitted parameter WITHOUT a default is
    a "missing required argument" rather than a home the callee reads
    uninitialised.  The old shape trimmed to the last supplied slot, which
    meant both of those were wrong.  See `bind_call_arguments`'s docstring for
    the measurement."""
    for i, s in enumerate(slots):
        if s is not None:
            continue
        pname = positional[i]
        if shape.has_default.get(pname):
            slots[i] = shape.defaults[pname]
        else:
            return None, (f"call {name}(): missing required argument "
                          f"{pname!r}")
    return slots, None


def try_handler_refusal(fn_name: str, stmt, handlers: list) -> str:
    """The diagnostic for a `try` that HAS handlers.

    A `try` with no handlers is a cleanup scope and is lowered: `finally` runs
    on the fall-through, on a return and on a raise, which is what
    `_emit_try`'s pending-finally stack is for. An `except` arm is the other
    thing entirely and there is no answer for it here, because **this image has
    no unwinder**: `raise` lowers to an exit (`arm64_codegen.py::_emit_stmt`'s
    `RaiseStmt` arm and `x86_64_codegen.py`'s twin both evaluate the exception
    expression for its side effects and then leave the process), so there is no
    edge from a raise site to a handler and no way for a handler to be reached.

    Measured, both architectures, and the point is that the program BUILDS:
    `class MyErr(ValueError)` + `raise MyErr("m")` inside a `try:`/`except:` was
    assembled, ran, and exited 1 having printed nothing where CPython prints
    `caught` and exits 0. `otool -tvV` shows why: the `except` arm's code is not
    emitted at all, the call to the raising function is followed by the code
    AFTER the `try` as if the call had returned normally, and the raise itself
    is `mov w0, #1 ; svc #0x80`. The same is true of a base this image
    DECLARES (`class MyBase` / `class MyErr(MyBase)`), which is why the reason
    below names the runtime and not the base: it is the handler that cannot
    run, not a class that cannot be built. The construction half is fine — that
    class builds and runs — so a refusal naming bases would be refusing the
    wrong half.

    The project's own rule for this is stated in `formal/hostmods/os` and
    `formal/hostmods/time`: *a failure is a status, not an exception*, and this
    is where that rule is enforced rather than merely written down. Zero of the
    664 stdlib files contain a `try` at all, so nothing that builds today stops
    building."""
    first = handlers[0]
    exc = first.exc_type if first is not None else None
    caught = "a bare `except:`" if not isinstance(exc, str) or not exc \
        else f"`except {exc}`"
    n = len(handlers)
    arms = "arm" if n == 1 else "arms"
    return (f"{fn_name}: the `try` on line {getattr(stmt, 'line', 0) or 0} "
            f"has {n} except {arms} ({caught}), and this image has no "
            f"unwinder: a `raise` here is an EXIT — the exception expression is "
            f"evaluated for its side effects and the process then leaves with "
            f"status 1 — so no handler can be reached and the code after the "
            f"`try` would run as if the body had returned normally. Measured on "
            f"both architectures: such a program builds, prints nothing and "
            f"exits 1 where CPython enters the handler. Refused rather than "
            f"emitted, because a program that runs and is not the program "
            f"written is the outcome this path treats as its worst. Report a "
            f"failure as a status: return a value, raise nothing, and let the "
            f"caller decide. `finally` needs no runtime and is still lowered.")


def variadic_read_refusal(fn_name: str, name: str, is_kwarg: bool,
                          call_note: str) -> str:
    """The diagnostic for a body that READS its variadic parameter.

    A variadic parameter is where the ABI is missing, and it is missing in one
    place: a formal value is one 64-bit word, so the arguments past the fixed
    ones have nowhere to be packed. The callee's caller-side already does the
    only correct thing available — it passes the fixed arguments, drops the
    rest, and (since 2026-10-10) still EVALUATES the dropped ones for their
    side effects, because `bind_call_arguments` returns them and the emitters
    run them — so a body that never reads the variadic parameter is exact, and
    it is the READ that has no answer. Measured before this check existed, on
    both architectures: `def f(*rest): return rest[2]` called as `f(1, 2, r)`
    built and died with SIGSEGV, because `rest` had no home and the index read
    through it. That is the wrong answer's other face, and both are the same
    absence."""
    kind = "**" if is_kwarg else "*"
    return (f"{fn_name}: the body reads {name!r}, its {kind}-parameter, and "
            f"this path has no variadic ABI. A formal value is one 64-bit "
            f"word, so the arguments a caller passes past the fixed ones "
            f"({call_note}) have nowhere to be packed — a tuple of them is a "
            f"container, and a container on this path is a frame-allocated "
            f"blob in the frame of the function that built it, which the "
            f"caller is not. Passing a variable number of arguments is a "
            f"change to the calling convention both backends AND the Lean "
            f"proof share. Take the arguments as named parameters, or read "
            f"them from a list the caller passes")




# ── `with`: the context-manager protocol, and the only shape of it this path can


#    honour ────────────────────────────────────────────────────────────────────
#
# `with EXPR as TARGET:` is not "evaluate, bind, run the body".  In CPython it is
# `mgr = EXPR; TARGET = type(mgr).__enter__(mgr); <body>; type(mgr).__exit__(…)`,
# and the two calls are the whole point: a `contextlib.redirect_stdout` that does
# not redirect, a `TemporaryDirectory` that does not remove, and a
# `contextlib.closing` that never closes all look like working programs, print
# their results, and exit 0.  This path used to lower the first line and drop the
# other two — the emitters' own docstrings said so ("with-items without a
# context-manager protocol … an `as` alias is bound to the expression result
# itself") — which made every one of those a wrong-but-exit-0 answer with
# nothing on the link line to catch it.
#
# The fix is not a wider value: a context manager here has to be a value this
# path can dispatch two methods on, and the only such value is a FRAME ADDRESS
# (the by-reference receiver, `struct_is_framed`).  So the protocol is lowered
# for a framed struct that declares both `__enter__` and `__exit__`, and every
# other `with` is refused by name — which is what CPython itself does with one
# that has neither (AttributeError), stated here as a refusal because this
# backend has no unwinder to raise it through.

CONTEXT_ENTER = "__enter__"
CONTEXT_EXIT = "__exit__"


def struct_is_context_manager(struct_def) -> bool:
    """True when `struct_def` is a context manager this path can enter and exit.

    Three conditions, each of which is a separate capability rather than a
    detail:

      * it declares BOTH dunders.  `__enter__` alone binds the alias and leaves
        the way out with nothing to call, which is the silent half this whole
        family exists to stop; `__exit__` alone has no way to produce the value
        the alias names.
      * its receiver is a FRAME (`struct_is_framed`).  A one-field struct's
        receiver IS its field — there is no address to call a method on, and no
        place to keep a second thing — so a one-field class cannot be a context
        manager here however the two dunders are written.  This is the price of
        the one-word value model and it is stated rather than hidden: CPython's
        own `TemporaryDirectory` and `nullcontext` both keep more than one
        attribute, so the honest mirror of either is representable.
      * `__enter__` takes no argument other than the receiver and RETURNS a
        value.  `__exit__` takes the receiver alone, CPython's own
        `(self, exc_type, exc_val, tb)`, or the variadic spelling
        `(self, *exc)` — and each wider spelling is accepted ONLY when the
        method never reads the words it would receive
        (`context_exit_ignores_its_exception_words` /
        `context_exit_variadic_ignores`).  Those three words are a
        question about the unwinder this path does not have (see
        `refuse_dropped_handler_arm`): there is nothing to pass them, and a
        `__exit__` that acted on them could not act on a value this path
        invented.  A `__exit__` that IGNORES them is the cleanup-only shape every
        temporary-directory and redirect class writes, and it lowers with the
        receiver plus three words it never looks at.
      * `__exit__` does not RETURN a value CPython would read as SUPPRESSING the
        exception (`context_exit_returns_truthy`).  The same missing unwinder,
        seen from the other side: a `raise` in the body exits the process, so a
        `__exit__` whose value says "carry on" produces a program that runs the
        cleanup and then leaves anyway — the one divergence in this family that
        is a wrong ANSWER rather than a refusal, and measured on both
        architectures before the condition was added.
    """
    if struct_def is None or not struct_is_framed(struct_def):
        return False
    methods = {getattr(m, "name", None): m for m in struct_methods(struct_def)}
    enter = methods.get(CONTEXT_ENTER)
    if enter is None or _dunder_receiver_params(enter) != 1:
        return False
    exit_ = methods.get(CONTEXT_EXIT)
    if exit_ is None:
        return False
    params = _dunder_receiver_params(exit_)
    # `__exit__` may take CPython's own three exception words — but only when it
    # does not READ them.  The words have nowhere to come from (there is no
    # unwinder), so passing a made-up value to a method that looks at it would be
    # a lie; a method that ignores them is the cleanup-only shape and lowers
    # with the receiver alone plus three words it never looks at.  See
    # `context_exit_ignores_its_exception_words`.  The variadic spelling of the
    # same shape, `__exit__(self, *exc)` with `exc` unread, is the second half of
    # that predicate (`context_exit_variadic_ignores`) and is called with the
    # receiver alone, which binds it to the empty tuple.
    if params == -1:
        if not context_exit_variadic_ignores(exit_):
            return False
    elif params == 4:
        if not context_exit_ignores_its_exception_words(exit_):
            return False
    elif params != 1:
        return False
    return not context_exit_returns_truthy(exit_)


#: "this operand is not a constant", which is NOT `None`: the `None` LITERAL is a
#: real scalar (`None < 1` is a `TypeError` in CPython, so a comparison of it must
#: be declined rather than answered), and a reader that could not tell the two
#: apart would either answer a comparison of `None` or decline one without it.
_UNKNOWN_CONSTANT = object()


def _constant_scalar(node):
    """The Python scalar `node` denotes when it is a constant, else `_UNKNOWN_CONSTANT`.

    The VALUE reader `_literal_return_truthiness` needs for a chained comparison
    (`a < b < c`), which compares values rather than truthinesses.  It is the
    three word folders plus exactly one thing they do not carry — a FLOAT, which
    no folder reads because a float is not a word — and it keeps `None` as a real
    scalar so a `None` operand reaches Python's own `TypeError` and is declined.
    """
    if isinstance(node, F.FloatLiteral):
        try:
            return float(node.value)
        except (TypeError, ValueError):
            return _UNKNOWN_CONSTANT
    if is_none_expr(node):
        return None
    value = fold_literal_expr(node)
    if value is None:
        value = fold_module_int_expr(node)
    if value is None:
        value = fold_module_select_expr(node)
    if value is None:
        return _UNKNOWN_CONSTANT
    return value


def _literal_return_truthiness(node):
    """CPython's truthiness of a `return`'s value when the build can DECIDE it, else None.

    The one reader `context_exit_returns_truthy` asks, and it exists because
    "which constants can this build decide" is not the same question for a
    TRUTHINESS as it is for a WORD — so this is where the build's constant
    folders are COMPOSED and the one place the answer is a truthiness rather
    than a word:

      * a FLOAT literal is read from its own value, because `fold_literal_expr`
        is the word reader and has no float arm on purpose — that folder is also
        the struct-field, class-constant and default-parameter reader, where a
        float is not an integer word.  `fold_module_value` is the one that turns
        a float literal into a word, by `int(...)`, and that truncation is
        exactly what must NOT be used here: `int(0.5)` is 0 while CPython reads
        the returned 0.5 as TRUE, so a gate built on it would answer the wrong
        way for every fraction.  A unary `+`/`-` over one follows it (`-0.5` is
        a `UnaryOp`, `-0.0` is falsy in CPython).
      * `len(<string literal>)` is a constant length, and its truthiness is "the
        text is non-empty" — which is the same answer for every encoding this
        path interns, because only an EMPTY text has zero bytes.
      * everything else is the three folders `fold_module_value` already
        composes: `fold_literal_expr` (literals and arithmetic, including
        `len(<display>)`), `fold_module_select_expr` (a comparison, `and`/`or`/
        `not`, `a if c else b`) and `fold_module_int_expr` (bitwise and shift).
        A folded int's truthiness is `!= 0` and a folded string's is non-empty,
        which is CPython's rule.

    **The three folders are asked rather than restated, and that is the fix.** A
    previous version folded only `fold_literal_expr`, so a truthy return built
    out of a COMPARISON (`return 1 < 2`), a boolean (`return 1 and 2`), a
    bitwise op (`return 1 | 2`), a select (`return 1 if 1 else 0`) or
    `len("abc")` was not seen as truthy at all, and the suppression it names was
    dropped — measured on both architectures, the same `enter / body / exit`,
    exit 1, no `after` wrong answer as `return True`, reached through a constant
    the build could read perfectly well.  Composing the folders the module-level
    reader already trusts keeps the two from drifting and is why this is not a
    second operator table.

    `None` means "not decided", which every caller reads as "leave the return
    where it was": this gate is deliberately one-sided — only a return it can
    read as truthy is refused, because refusing every computed return would
    refuse `nullcontext` — and asking more of the folders can only move a
    constant from the undecided side to the decided one, never the reverse.
    """
    if isinstance(node, F.FloatLiteral):
        try:
            return float(node.value) != 0.0
        except (TypeError, ValueError):
            return None
    if isinstance(node, F.UnaryOp) and node.op in ("+", "-"):
        return _literal_return_truthiness(node.operand)
    # `len(<string literal>)`: a constant length, and `fold_literal_expr`'s own
    # `len` arm reads a DISPLAY (`len([x, y])` is 2 whatever the elements are)
    # rather than a string's byte count, so the string case is answered here.
    # Only the EMPTINESS matters for a truthiness and that is encoding-free.
    if isinstance(node, F.CallExpr) and isinstance(node.func, F.IdentExpr) \
            and node.func.name == "len" and not (node.kwargs or []) \
            and len(node.args or []) == 1:
        arg = node.args[0]
        if isinstance(arg, F.StringLiteral) \
                and not getattr(arg, "is_bytes", False) \
                and isinstance(arg.value, str):
            return F.decoded_literal(arg) != ""
    # A constant ELEMENT of a constant display — `(1, 2)[0]`, `[1, 2][1]` — and
    # only over a display: the element's value is the only thing asked of it, and
    # a name's or a call's is not knowable here.  A starred element makes the
    # positions unknowable, so it refuses; an out-of-range index is CPython's own
    # run-time error and not a value, so it leaves the return undecided.
    if isinstance(node, F.SubscriptExpr) \
            and isinstance(node.obj, (F.TupleExpr, F.ListExpr)):
        index = fold_literal_expr(node.index)
        if isinstance(index, int) and not isinstance(index, bool):
            elements = list(getattr(node.obj, "elements", None) or ())
            if not any(isinstance(e, F.UnaryOp) and e.op == "*"
                       for e in elements):
                try:
                    return _literal_return_truthiness(elements[index])
                except IndexError:
                    return None
    # The two arithmetic operators no folder carries: `/` (whose Python answer is
    # a FLOAT, so it is not a word) and `%`.  Both are folded here and only here,
    # because the question is the RESULT's truthiness and not its value, and that
    # is one-sided in the safe direction: `a % b` is zero exactly when `b`
    # divides `a`, which is the same fact for Python's floored `%` and the
    # machine's word, and `a / b` is truthy whenever `a` is — so a constant this
    # arm reads as truthy is one CPython suppresses, and refusing it is the
    # answer; a constant it cannot read is left where it was.  A zero divisor is
    # CPython's own run-time error and not a value, so it leaves the return
    # undecided rather than inventing one.
    if isinstance(node, F.BinaryOp) and node.op in ("/", "%"):
        a = fold_literal_expr(node.left)
        b = fold_literal_expr(node.right)
        if isinstance(a, int) and not isinstance(a, bool) \
                and isinstance(b, int) and not isinstance(b, bool):
            try:
                quotient = (a / b) if node.op == "/" else (a % b)
            except (ZeroDivisionError, OverflowError, ValueError):
                return None
            return quotient != 0
    value = fold_literal_expr(node)
    if value is None:
        value = fold_module_select_expr(node)
    if value is None:
        value = fold_module_int_expr(node)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value != ""
    # The shapes the int/str folders decline, and they are declined for a reason
    # that is about a WORD rather than about the truthiness this gate asks: a
    # branch that is a FLOAT, a CONDITION that is a float or a string (the
    # module-level folder is deliberately int-only there, because a `char *` is
    # non-null for the empty string on the machine), or an operand that is a
    # CONTAINER.  Each is decided here by recursing on the operand whose
    # truthiness decides the result, so no operator table is restated — the
    # recursion is the same reader, one level down.
    if isinstance(node, F.UnaryOp) and node.op == "not":
        inner = _literal_return_truthiness(node.operand)
        return None if inner is None else (not inner)
    if isinstance(node, F.BinaryOp) and node.op in ("and", "or"):
        left = _literal_return_truthiness(node.left)
        if left is None:
            return None
        # CPython's short circuit: `a and b` is `a` when `a` is falsy and `b`
        # when `a` is truthy; `a or b` is the mirror.  The left operand decides
        # the answer outright in one of the two cases and is the reason the
        # right operand is only asked for when it is the one that is returned.
        if node.op == "or":
            return True if left else _literal_return_truthiness(node.right)
        return _literal_return_truthiness(node.right) if left else False
    if isinstance(node, F.TernaryExpr):
        cond = _literal_return_truthiness(node.condition)
        if cond is None:
            return None
        return _literal_return_truthiness(node.then_val if cond else node.else_val)
    # A container display is truthy exactly when it is non-empty, whatever its
    # elements are, so its ARITY is the whole question — and a starred element
    # (`[*a]`) or a `**` spread (`{**a}`) makes the arity unknowable.
    if isinstance(node, (F.ListExpr, F.TupleExpr, F.SetExpr)):
        elements = list(getattr(node, "elements", None) or ())
        if any(isinstance(e, F.UnaryOp) and e.op == "*" for e in elements):
            return None
        return len(elements) > 0
    if isinstance(node, F.DictExpr):
        pairs = list(getattr(node, "pairs", None) or ())
        if any(isinstance(k, F.UnaryOp) and k.op == "**" for k, _v in pairs):
            return None
        return len(pairs) > 0
    # `a < b < c` is `a < b and b < c`, and it is its own node rather than two
    # `BinaryOp`s, so it needs the VALUE reader above.  An operand that is not a
    # constant, an operator the table does not know, or Python's own `TypeError`
    # (a `None` operand) all decline rather than guess.
    if isinstance(node, F.CompareChain):
        for at, op in enumerate(node.ops):
            left = _constant_scalar(node.operands[at])
            right = _constant_scalar(node.operands[at + 1])
            if left is _UNKNOWN_CONSTANT or right is _UNKNOWN_CONSTANT:
                return None
            compare = _FOLD_COMPARE.get(op)
            if compare is None:
                return None
            try:
                if not compare(left, right):
                    return False
            except TypeError:
                return None
        return True
    return None


def context_exit_returns_truthy(method) -> bool:
    """True when some `return` in `__exit__` folds to a value CPython reads as TRUE.

    **`__exit__`'s RETURN VALUE is half the protocol and this path drops it.**
    CPython suppresses the exception in flight when `__exit__` returns something
    true, and `raise` here leaves the process after flushing the enclosing
    `finally` clauses (`_emit_raise`'s `_flush_pending_finally` then
    `_emit_exit`), so there is nothing left to resume into.  Measured, both
    architectures, on the shape every hand-written suppressor is written in:

        class Suppressor:
            def __enter__(self): print('enter'); return self.tag
            def __exit__(self):  print('exit'); return True
        def main(n):
            with Suppressor() as v:
                print('body', v)
                raise ValueError('m')
            print('after')
            return 0

    CPython prints `enter / body 7 / exit / after` and exits 0.  This path
    printed `enter / body 7 / exit` and exited 1 — the cleanup ran, so nothing
    looks broken, and `after` is simply never reached.  That is the worst shape a
    wrong answer takes on this path: the visible half is right.

    **The test is FOLDABILITY, deliberately, and the direction is one-sided.**
    `_literal_return_truthiness` answers a `return` whose value the build can
    decide — `return True`, `return 1`, `return 2` are all suppressions; a bare
    `return`, `return False`, `return None` and `return 0` are all not — and
    answers None for anything computed.  **The test is the returned value's
    TRUTHINESS and neither its type nor its word**: CPython reads any true return
    as a suppression, so a non-empty string literal (`return "yes"`) and a
    non-zero float literal (`return 0.5`) both suppress exactly as `return 1`
    does and are both refused here, where earlier wordings of this function
    checked `isinstance(value, int)` and let the first through.  Both are
    measured on both architectures — the image built, printed
    `enter / body 7 / exit` and exited 1 where CPython exits 0, the same wrong
    answer as the `return True` case above.  `return ""`, `return 0.0`, `return
    0`, `return False` and `return None` are all falsy in CPython and all still
    lower.  **The word reader is deliberately not reused for the float**:
    `fold_literal_expr` has no float arm, and `fold_module_value`'s truncation
    (`int(0.5)` is 0) would answer the truthiness the wrong way, which is why
    `_literal_return_truthiness` reads a float's own value.  **A return need
    not be a single literal to be decided**: a COMPARISON, `and`/`or`/`not`, a
    bitwise op, a select or `len(<string literal>)` over constants all fold, so
    `return 1 < 2` / `return 1 and 2` / `return 1 | 2` / `return len("abc")` are
    refused with the literal ones (measured on both architectures; before the
    composition these built and dropped the suppression, the same wrong answer).
    **What stays uncounted is a return that depends on a RUN-TIME value** — the
    remaining limit is cross-FIELD flow (`nullcontext` returns
    `self.exit_result`, and whether that is true depends on a constructor
    argument this function cannot see), and it is the same limit `_expr_is_fd`
    states for a descriptor in a field.  A narrower gate that refused every
    return that is not a single literal would refuse
    `formal/hostmods/contextlib.mojo`'s own `nullcontext`, whose three CPython
    pairs live in `test_formal_core_hostmods.py`'s `ctx` group — refusing a host
    module the corpus depends on to catch a case the corpus does not write is
    the wrong trade, and this says so instead of hiding it.
    """
    for node in iter_nodes(getattr(method, "body", None) or ()):
        if not isinstance(node, F.ReturnStmt):
            continue
        # `_literal_return_truthiness` is the ONE reader of "what would CPython
        # read this return as", so the test is the value's TRUTHINESS rather
        # than its type or its word: it composes the build's three constant
        # folders and answers an int, a `bool` or a STRING for every shape they
        # can decide — a literal, arithmetic, a comparison, `and`/`or`/`not`, a
        # select, a bitwise op or `len(<string literal>)` — and a float from its
        # own value.  Python `None` means "not decided" — a bare `return` and a
        # return that depends on a run-time value both — and is falsy here, the
        # refusal-to-decide direction this gate is deliberately one-sided in.
        if _literal_return_truthiness(getattr(node, "value", None)):
            return True
    return False


def _exit_return_folds_truthy(value_node) -> bool:
    """True when `__exit__`'s `return <value_node>` folds to a value CPython reads as TRUE.

    **CPython's test is truthiness, and truthiness is not "a non-zero `int`".**
    `__exit__` suppresses the exception in flight when it returns something
    true, and a non-empty string (`return "x"`) and a non-zero float
    (`return 1.5`) suppress exactly as `return 1` does. Both fold here —
    `fold_literal_expr` answers a string literal, and both emitters read a
    `FloatLiteral` as `int(expr.value)`, so the build knows the word — which
    means a gate keyed on `int` alone let them through, and the program built
    and then dropped the suppression on the floor: the same wrong answer as
    `return True`, in a spelling the earlier gate missed.

    A `None` fold — anything computed — is NOT counted. That is the remaining
    limit `context_exit_returns_truthy` states: cross-field flow (`nullcontext`
    returns `self.exit_result`), which is deliberately still answered rather
    than refused.
    """
    if isinstance(value_node, F.FloatLiteral):
        try:
            return float(value_node.value) != 0.0
        except (TypeError, ValueError):
            return False
    value = fold_literal_expr(value_node)
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value != ""
    return False


def _dunder_receiver_params(method) -> int:
    """How many parameters a method declares, receiver included; -1 if variadic.

    `*args`/`**kwargs` cannot be counted from the tree and are -1, which fails
    every comparison here — a variadic context-manager method is refused rather
    than assumed, for the same reason a variadic call is
    (`refuse_variadic_parameter_read`) — **except** for the one variadic shape a
    context manager really writes, which `context_exit_variadic_ignores` decides
    and `__exit__`'s gate lets through.

    **The star is read from the parameter LIST, not from an attribute.**  This
    used to ask `getattr(method, "vararg", None)`, and no `FunctionDef` on this
    front end has that attribute — the parser keeps the star IN the name it
    appends to `params` (`("*args", …)` / `("**kwargs", …)`,
    `fire_compiler.py::_parse_funcdef`).  So `def __exit__(self, *args)` came
    out as arity 2, was refused with a message about "1 parameters after the
    receiver", and the variadic branch below was dead.  `function_param_shape`
    is the one reader of that list for the whole file, so the two cannot drift.
    """
    shape = function_param_shape(method)
    if shape.variadic:
        return -1
    return len(shape.fixed)


def _param_names(params) -> list:
    """The NAME of each parameter, in order — `(name, annotation)` tuples on
    this front end, with `getattr(p, "name", p)` as the fallback for a node
    shape that carries the name itself.  `None` for an entry nothing names."""
    out = []
    for p in (params or ()):
        if isinstance(p, (list, tuple)):
            out.append(p[0] if p and isinstance(p[0], str) else None)
        else:
            name = getattr(p, "name", None)
            out.append(name if isinstance(name, str) else None)
    return out


def context_exit_ignores_its_exception_words(method) -> bool:
    """True when a FOUR-parameter `__exit__` never reads its last three words.

    CPython's own signature is `__exit__(self, exc_type, exc_val, tb)`, and the
    backend has no unwinder to supply them — but the common cleanup-only manager
    (every temporary-directory and redirect class in the wild) ignores them
    entirely, and for that shape the signature is not a question about the
    unwinder at all.  This is the predicate that tells the two apart.

    **Non-use, and not "returns falsy".**  `context_exit_returns_truthy` decides
    the return half, which is a suppression this path cannot perform; this
    decides the ARGUMENT half, which is whether the values this path would pass
    are ever looked at.  A method that ignores them cannot be acted on by them,
    so passing the receiver plus three zeros is faithful; a method that reads any
    one of them would be acting on a lie and stays refused.  The three names are
    read from the method's own parameters, so a manager that spells them
    `(self, kind, value, backtrace)` is accepted on exactly the same evidence.

    The check is over the whole method body through `iter_nodes`, so a read in a
    nested `def`, in a closure, or through `getattr`-free attribute access
    (`exc_type.__name__`) is an occurrence of the name and refuses.  A name that
    appears only as an assignment TARGET is also an occurrence, which is the
    conservative direction: it is not a read, and refusing it costs a shape no
    real context manager writes.
    """
    shape = function_param_shape(method)
    if shape.variadic or len(shape.fixed) != 4:
        return False
    names = set(_param_names(list(getattr(method, "params", None) or [])[1:]))
    if len(names) != 3 or None in names:
        return False
    return not _body_reads_any_name(method, names)


def _body_reads_any_name(method, names) -> bool:
    """Whether any of `names` occurs as an identifier in `method`'s body.

    The shared half of the two ignoring predicates below — the four-fixed-word
    shape and the variadic one — so a name read inside a nested `def`, a
    closure, or as an assignment TARGET is one occurrence either way (the
    conservative direction `context_exit_ignores_its_exception_words` states).
    """
    for node in iter_nodes(getattr(method, "body", None) or ()):
        if isinstance(node, F.IdentExpr) and getattr(node, "name", None) in names:
            return True
    return False


def context_exit_variadic_ignores(method) -> bool:
    """True when `__exit__(self, *exc)` never reads its catch-all.

    **The variadic spelling of the same ignoring shape
    `context_exit_ignores_its_exception_words` accepts**, and it is the one
    `with` signature this path used to refuse for a reason that stopped being
    true.  CPython calls `__exit__(type, value, tb)` POSITIONALLY, so a method
    that catches them catches them in `*exc`:

        class TempDir:
            def __enter__(self): ...
            def __exit__(self, *exc): self.close()      # ignores the triple

    On a normal exit CPython binds `exc = (None, None, None)`; this path calls
    the method with the receiver alone, so `exc` binds the empty tuple.  A body
    that never looks at `exc` cannot tell the two apart, which is exactly the
    evidence the four-word predicate uses — so the two are one question and this
    is its second spelling rather than a second rule.

    **Two clauses are structural rather than about reading, and both are the
    call shape.**  A *positional* catch-all is required: `def __exit__(self,
    **kw)` is not a context manager in CPython either (three positional
    arguments against a keyword-only signature is a `TypeError`), so a `kwarg`
    with no `vararg` is refused.  And the receiver must be the ONLY fixed
    parameter: `def __exit__(self, exc_type, *rest)` would leave `exc_type`
    unbound on the receiver-only call this path makes, so it stays refused even
    though `rest` is ignored — a value the method could read would be the
    caller's leftover, which is the failure this whole family refuses.
    """
    shape = function_param_shape(method)
    if shape.vararg is None or len(shape.fixed) != 1:
        return False
    names = {n for n in (shape.vararg, shape.kwarg) if n}
    return not _body_reads_any_name(method, names)


def context_exit_arity(struct_def) -> int:
    """How many arguments `__exit__` takes, receiver included: 1 or 4.

    The ONE reader of "what does the exit call pass", for the lowering that
    builds the call (`formal/build.py::_one_with_item`).  It answers from the
    same `_dunder_receiver_params` the gate does, so the call and the gate cannot
    disagree; a receiver-only `__exit__` is 1, CPython's own three-word spelling
    is 4, and the variadic shape (`(self, *exc)`, `_dunder_receiver_params` -1)
    is 1 — it catches the words in an empty tuple the body never reads.  A struct
    that is not a context manager this path lowers gets the receiver-only
    answer, which is the shape the resource arm (`open`) uses and the only one
    its `close` builtin takes.
    """
    for m in struct_methods(struct_def):
        if getattr(m, "name", None) == CONTEXT_EXIT:
            return 4 if _dunder_receiver_params(m) > 1 else 1
    return 1


def with_alias_struct(struct_def, structs_by_name):
    """The struct a `with ... as NAME` alias holds, or None if the source names none.

    The alias names `__enter__`'s RESULT, not the context — CPython's
    `TARGET = type(mgr).__enter__(mgr)` — so the struct it holds is the one that
    result is DECLARED to be, and a manager that annotates `__enter__` has
    written it down.  Publishing it is what lets a method call through the alias
    whose NAME a second struct of this image also declares lift from the alias's
    own type instead of being refused, which is the SAME evidence a field access
    reads through `struct_field_declared_type` and a parameter through
    `parameter_declared_structs`: a type the source wrote, rather than a guess by
    name.

    `__enter__` returning a plain word (`return self.tag`) or carrying no
    return annotation is None, and that is the honest answer: nothing in the
    source says which struct the alias holds, so dispatch stays by name and the
    ambiguous case stays refused (`formal/build.py::_lift_one_word_field_method`
    declines a name two structs declare).  A result whose annotation names a
    type THIS unit does not declare is None for the same reason — the struct is
    in another module and there is nothing here to lift to.

    One reader, asked by the ONE lowering that decides the alias's binding
    (`formal/build.py::_one_with_item`), and it answers from `annotation_base_name`
    so a spelling the rest of this file already accepts (`Res`, `Self`,
    `Optional[Res]`'s base) means here what it means everywhere else.
    """
    enter = next((m for m in struct_methods(struct_def)
                  if getattr(m, "name", None) == CONTEXT_ENTER), None)
    if enter is None:
        return None
    base = annotation_base_name(getattr(enter, "return_type", None),
                                self_type=getattr(struct_def, "name", None))
    if not base:
        return None
    return (structs_by_name or {}).get(base)


def with_alias_bare_name(item):
    """The BARE NAME a `with` item's `as` clause binds, or None if it is not one.

    **The rule is `str.isidentifier()`, and it is here because the AST cannot
    tell the shapes apart.**  `fire_compiler::_parse_with` parses every alias
    target — `as x`, `as (a, b)`, `as obj.attr`, `as holder[0]` — with
    `_parse_unpack_target` and stores the result as a bare STRING in
    `WithItem.alias`, so `'(a, b)'` and `'obj.attr'` arrive as strings that are
    not names.  `build.py::_with_protocol` used to accept any string, which made
    a `VarDecl` for a variable literally called `(a, b)`: the three shapes BUILT,
    ran the body, and exited 0 with nothing bound, and `refuse_unlowerable_with_
    alias` — written for exactly this — could not fire, for the reason its own
    message gives ("the shape is not in the AST this function is handed").

    The shape IS recoverable from the string, and this is the one reader of it:
    a bare name is an identifier and nothing else is, so one predicate separates
    all four spellings without the parser changing and without the self-hosted
    front end (which BOXES the alias as an `IdentExpr`, hence the second
    spelling below) having to agree about a representation it does not share.

    A keyword is excluded as well as a non-identifier, because `str.isidentifier`
    says `class` is one and `with C() as class:` is not a program — the parser
    rejects it, so a build that reached here with one has a front end that does
    not, and binding it would be answering a program nobody wrote.
    """
    alias = getattr(item, "alias", None)
    name = alias if isinstance(alias, str) else getattr(alias, "name", None)
    if not isinstance(name, str):
        return None
    if not name.isidentifier() or keyword.iskeyword(name):
        return None
    return name


def with_expr_struct(expr, structs_by_name: dict, functions: dict = None,
                     bound: dict = None, fn=None, owner=None, elems=None):
    """The struct a `with` item's EXPRESSION holds, or None if undecidable.

    Two sources, in this order, and the order is a fact about what each can
    answer rather than a preference:

      * a CONSTRUCTION the source wrote, spelled `S(...)` or `mod.S(...)` — read
        here, because `mod.S(...)` names a struct through an IMPORT ALIAS, which
        is a spelling `receiver_struct`'s field row does not have (that row needs
        a single-field chain rooted at a local).  `tempfile.TemporaryDirectory` is
        224 `with` sites in this repository's own corpus and every one of them is
        this spelling, so it cannot be left to the reader below.
      * everything `model.receiver_struct` answers for a field access — a bare
        NAME bound from a construction, a name bound from a CALL to a function of
        this unit whose declared return type names a struct, a FIELD whose
        declared type names one, a declared parameter, a method call's own `-> T`,
        a list element.

    **The second source is the point, and it is a DELEGATION rather than a new
    inference.**  "What struct does this receiver name" already has exactly one
    reader in this file, and a `with` asks it the same question a field access
    does — with more at stake, because the answer picks which `__enter__` runs.
    Two readers would be two answers, and the pair that disagree is exactly how
    the two architectures used to answer `with` differently.  So `with` is a
    CONSUMER of that reader, and this function's construction arm is the one
    thing it adds.

    `one_field=False` waives `receiver_struct`'s one-field gate, which is the
    gate that says "this is a value, not a name" — and a context manager is a
    name: `struct_is_context_manager` then requires the struct to be FRAMED, so
    a one-field struct is still refused, with the one-field sentence, by the
    caller.  That gate and this one ask different questions and both are applied.

    The narrowing that remains is deliberate.  A context manager is entered
    through its type, so "what type is this value" has to be answered by a fact
    rather than a guess, and both sources are facts about the SOURCE: a
    constructor it wrote, a binding it made, or a type it DECLARED.  What is not
    here is a callee from another module or a dylib, a name bound to two
    different structs, and a binding made in a nested `def` — each would need
    evidence this image does not have, and each guess is a program that enters
    the wrong `__enter__`.

    `bound`, `fn`, `owner` and `elems` default to None, which for
    `receiver_struct` means "no evidence in hand from the caller" and not
    "nothing is a receiver" — a caller with nothing gets the construction arm
    alone, which is the whole of what this function did before 2026-10-05.
    """
    if isinstance(expr, tuple):        # a parenthesised expression
        expr = expr[0] if expr else None
    callee = getattr(expr, "func", None)
    if callee is not None:
        # `mod.S(...)` is a `MemberExpr`, whose `member` is a plain string — the
        # same two spellings `_with_item_alias_name` has to ask about, and read
        # here rather than through a helper so this function answers for the AST
        # it is handed.  `mod.S(...)` resolves through the same table as
        # `S(...)` on purpose: a context manager published by a host module
        # (`tempfile.TemporaryDirectory`) is a struct of THIS image too, because
        # `formal/build.py` compiles the imported module's own declarations into
        # `structs_by_name` before this runs.
        name = getattr(callee, "name", None) or getattr(callee, "member", None)
        if isinstance(name, str) and name:
            st = structs_by_name.get(name)
            if st is not None:
                return st
    if fn is None and bound is None and owner is None:
        # No caller evidence at all: the construction arm is all there is, and
        # asking `receiver_struct` with nothing would be a reader run for its
        # own sake.
        return None
    return receiver_struct(expr, fn, structs_by_name, owner=owner, bound=bound,
                           elems=elems, functions=functions, one_field=False)


def with_context_manager_defect(struct_def) -> str:
    """Why `struct_def` is not a context manager this path can enter and exit.

    **Every sentence here has to be TRUE about the struct, and one of them was
    not until 2026-10-05.**  `refuse_unlowerable_with` used to answer any framed
    struct that was not enterable with "it declares no `__enter__`", asked as
    `_declares(struct, CONTEXT_ENTER)` — a PRESENCE test.  So a struct declaring
    BOTH dunders whose `__exit__` is written CPython's way,
    `(self, exc_type, exc_val, tb)`, was told it had no `__enter__` — false about
    a class that has one, and a fix that sends the reader to add a dunder they
    already have.  That spelling is what every context manager in the wild
    writes, so this sentence was the FIRST one a reader of real code met.

    Four shapes, and they are four different edits:

      * a dunder ABSENT — the fix is a method in the struct.
      * a dunder whose receiver-parameter count is not 1 — the fix is that
        signature, and the sentence has to say which dunder, because
        `__enter__(self, x)` and `__exit__(self, a, b, c)` are different problems
        with different reasons.
      * a dunder VARIADIC — refused rather than assumed, because `*args` cannot
        be counted from the tree, exactly as a variadic CALL is
        (`refuse_variadic_parameter_read`).
      * an `__exit__` that RETURNS a value CPython reads as suppressing the
        exception (`context_exit_returns_truthy`) — the fix is that return value,
        and it is the only one of the four that was a wrong ANSWER rather than a
        refusal, so it is the one with the longest explanation.

    The counts are read with `_dunder_receiver_params`, the same predicate
    `struct_is_context_manager` gates on, so the sentence and the decision
    cannot come apart: a struct this function says is fine is one the gate lets
    through, and vice versa.  It takes a struct that IS framed — the caller has
    already said so, and "it is a struct of ONE field" is a different sentence
    with a different fix.
    """
    methods = {getattr(m, "name", None): m for m in struct_methods(struct_def)}
    missing = [name for name in (CONTEXT_ENTER, CONTEXT_EXIT)
               if name not in methods]
    if missing:
        return ("it declares no "
                + " and no ".join(missing)
                + ", so there is nothing to enter and nothing to call on the "
                  "way out")
    for name in (CONTEXT_ENTER, CONTEXT_EXIT):
        params = _dunder_receiver_params(methods[name])
        if params == 1:
            continue
        if params < 0:
            if name == CONTEXT_EXIT and context_exit_variadic_ignores(
                    methods[name]):
                # The gate accepts this shape, so reaching here is impossible —
                # kept so the sentence and the decision cannot come apart if
                # `struct_is_context_manager` is ever reordered.
                continue
            if name == CONTEXT_EXIT:
                shape = function_param_shape(methods[name])
                if shape.vararg and len(shape.fixed) == 1:
                    return (
                        f"it declares both dunders, but its `{CONTEXT_EXIT}` "
                        f"takes CPython's three exception words through a "
                        f"variadic `*{shape.vararg}` and READS it. Those three "
                        f"words are a question about an UNWINDER this backend "
                        f"does not have: there is no exception value, no "
                        f"traceback and no type word to pass, so any value this "
                        f"path supplied would be a lie the method then acted on. "
                        f"Drop the reads (or the catch-all): a `{CONTEXT_EXIT}` "
                        f"that IGNORES it is the cleanup-only shape, it is what "
                        f"`formal/hostmods/tempfile.mojo`'s `TemporaryDirectory` "
                        f"declares, and it lowers")
            return (f"it declares both dunders, but its `{name}` is variadic "
                    f"(`*args`/`**kwargs`), which cannot be counted from the "
                    f"tree — so this path refuses it rather than assume it "
                    f"takes the receiver and nothing else")
        if name == CONTEXT_EXIT and params == 4:
            # CPython's own signature, and it is refused ONLY because the method
            # READS one of the three words.  The gate accepts this arity when the
            # words are ignored (`context_exit_ignores_its_exception_words`), so
            # reaching here means at least one of them is used — and a value this
            # path invented for it would be a lie, which is the whole reason the
            # three words are a question about the missing unwinder rather than a
            # parameter-count rule.
            return (
                f"it declares both dunders, but its `{CONTEXT_EXIT}` takes "
                f"CPython's three exception words and READS them. Those three "
                f"words are a question about an UNWINDER this backend does not "
                f"have: there is no exception value, no traceback and no type "
                f"word to pass, so any value this path supplied would be a lie "
                f"the method then acted on. Drop the reads (or the parameters): a "
                f"`{CONTEXT_EXIT}` that IGNORES them is the cleanup-only shape, "
                f"it is what `formal/hostmods/tempfile.mojo`'s "
                f"`TemporaryDirectory` declares, and it lowers")
        if name == CONTEXT_EXIT:
            return (
                f"it declares both dunders, but its `{CONTEXT_EXIT}` takes "
                f"{params - 1} parameters after the receiver — CPython's own "
                f"signature is `{CONTEXT_EXIT}(self, exc_type, exc_val, tb)` — "
                f"and this path calls it with the receiver alone. Those three "
                f"words are a question about an UNWINDER this backend does not "
                f"have: there is nothing to pass them, and CPython also uses "
                f"`{CONTEXT_EXIT}`'s return value to SUPPRESS the exception in "
                f"flight, which is that same missing runtime seen from the "
                f"other side. Drop the exception arguments: a `{CONTEXT_EXIT}` "
                f"that ignores them is the cleanup-only shape, it is what "
                f"`formal/hostmods/tempfile.mojo`'s `TemporaryDirectory` "
                f"declares, and it lowers")
        return (f"it declares both dunders, but its `{name}` takes {params - 1} "
                f"parameters after the receiver and this path calls it with "
                f"the receiver alone — the protocol's `__enter__` receives the "
                f"context manager and nothing else, so the word a second "
                f"parameter names would be an uninitialised register")
    # Both dunders are present with one receiver parameter each, so the shapes
    # are right and the remaining reason is what `__exit__` RETURNS.  Asked here
    # rather than inside the loop because the loop `continue`s past both names
    # when they are well-shaped, and putting the arm between the two `continue`s
    # would make it reachable for `__enter__`'s arity as well.
    if context_exit_returns_truthy(methods[CONTEXT_EXIT]):
        return (f"it declares both dunders in the shape this path calls, but "
                f"its `{CONTEXT_EXIT}` returns a value CPython reads as "
                f"SUPPRESSING the exception in flight, and this path has no "
                f"unwinder to suppress it with: a `raise` in the body runs this "
                f"cleanup and then leaves the process, so the statements after "
                f"the block never run and the status is 1 where CPython "
                f"continues — the cleanup prints every line CPython printed, "
                f"which is what makes it hard to see. Return a falsy value "
                f"(`False`, `0`, `None`) or nothing: a cleanup-only "
                f"`{CONTEXT_EXIT}` lowers, and that is what "
                f"`formal/hostmods/tempfile.mojo`'s `TemporaryDirectory` "
                f"declares")
    # Unreachable while `struct_is_context_manager` is the gate — both dunders
    # present with one receiver parameter each and no truthy return IS that
    # predicate's answer.  Kept rather than `raise`d because a reader who
    # changes the gate should read a sentence here rather than an IndexError
    # from three lines away.
    return "it declares both dunders in the shape this path calls and returns " \
           "nothing CPython would read as a suppression, so the reason is not " \
           "in the struct — that is a compiler bug, not a program to fix"


def refuse_unlowerable_with(fn, where, expr, struct, structs_by_name) -> str:
    """Why this `with` cannot be the context-manager protocol, in reader's terms.

    The three shapes this message has to tell apart, because they are three
    different edits and a reader who cannot tell them apart looks for the wrong
    one:

      * the expression CONSTRUCTS a struct that is not enterable — not framed
        (the one-word value model), or framed without both dunders in the shape
        the protocol calls.  The fix is in the struct, and
        `with_context_manager_defect` says which half and why.
      * the expression constructs a struct that IS enterable but this image does
        not compile — which cannot happen here and is not given an arm, because
        an arm that is never reached is a sentence a future reader has to check.
      * the expression is not a construction at all, so nothing says what type it
        is.  The fix is in the spelling: bind the context manager in a `var`
        this build can see the type of, or construct it here.  A call to a
        RESOURCE builtin (`RESOURCE_CONTEXT_MANAGERS`, i.e. `open`) is the one
        non-construction that IS answerable, and `resource_context_manager_exit`
        answers it before this function is asked — so a reader who lands here
        for `with open(…)` is reading a message from a build that predates that
        table.

    The sentence that matters most is the last one: what this path used to do
    instead.  A `with` lowered as "evaluate, bind, run the body" is a program
    that builds, runs, prints its results and exits 0 while skipping the call
    that is the entire contract — the failure CLAUDE.md calls the one no check
    on this path can see.
    """
    # The `with` ITEM is what carries the line, and it is what the reader's
    # editor jumps to; the statement's own line is the same line here and would
    # be one hop away when they ever differ.
    line = getattr(where, "line", 0) or 0
    head = f"line {line}: " if line else ""
    # `expr_spelling`, not a private spelling helper: a diagnostic about a `with`
    # that printed `CallExpr` would send the reader to the AST, which is the
    # opposite of what quoting the call site is for.
    spelled = expr_spelling(expr)
    detail = ("this build cannot answer what type it is, because it is not a "
              "construction of a struct this image compiles"
              if struct is None else
              ("it is a struct of ONE field, so its receiver IS that field and "
               "there is no address to call a method on"
               if not struct_is_framed(struct) else
               with_context_manager_defect(struct)))
    return (
        f"{head}{fn.name}: `with {spelled} as …` is CPython's CONTEXT-MANAGER "
        f"PROTOCOL — `type(mgr).__enter__` binds the name, and "
        f"`type(mgr).__exit__` runs on the way out — and this path cannot "
        f"honour it here: {detail}. A formal value is one 64-bit word, so the "
        f"only value this path can enter and exit is a FRAMED struct that "
        f"declares both dunders (`struct_is_context_manager`), whose receiver is "
        f"the frame's address. Binding the name to the expression's own value "
        f"and running the body — which is what this path used to do — builds a "
        f"program that exits 0 having skipped the call that IS the contract: "
        f"CPython raises AttributeError on a word, a redirect that does not "
        f"redirect prints the program's own output and looks right, and a "
        f"temporary directory is left on disk. What the value has to be is a "
        f"struct of more than one field declaring `{CONTEXT_ENTER}` and "
        f"`{CONTEXT_EXIT}` in the shape this path calls, or a resource this "
        f"image already has a value for (`open`), and the `with` has to "
        f"construct one of those rather than name something untyped; a `with` "
        f"whose context is a plain value cannot be made faithful here."
    )


def refuse_unlowerable_with_alias(fn, where) -> str:
    """Why this `with` item's ALIAS cannot be bound, in reader's terms.

    Its own message, and the reason is that the one above became false for the
    cases that reach this.  It describes the CONTEXT EXPRESSION — a struct that
    is not framed, a struct with no `__enter__`, an expression this build
    cannot type — and `with EXPR as (a, b)` has none of those problems: the
    context is fine and the TARGET is the shape.  Reusing the expression's
    message for it sent the reader to the wrong half of their own line, and
    saying "this build cannot answer what type it is" about an `open(…)` whose
    type this module now knows is the same defect one level along.

    It opens with the protocol sentence `refuse_unlowerable_with` opens with,
    and that is deliberate rather than decorative: `tools/formal_sweep_causes.py`
    keys its `with` row on that clause, so a file refused for the alias shape is
    counted in the same row as one refused for the context — which is what a
    reader deciding where to start needs — while the sentence that says WHY
    differs.

    ONE sentence for both spellings (`as (a, b)` and `as obj.attr`), because
    there is a sentence that is true of both: neither names somewhere this path
    can put a word.  Saying which is which would need a discriminator between a
    tuple node and a member node on a front end where the alias is a bare STRING
    (`fire_compiler` parses all three spellings to a string, so the shape is not
    in the AST this function is handed), and a message that guesses between two
    shapes it cannot see is the failure this repository keeps deleting.

    **This refusal was DEAD CODE until 2026-10-05, and the reason is the second
    half of the paragraph above read as an excuse.**  `build.py::_with_protocol`
    asked `isinstance(alias, str)` — which every alias spelling answers — and so
    bound `VarDecl('(a, b)', …)`: `with Ctx() as (a, b):` built, ran the body,
    printed it and exited 0 with nothing bound, on both architectures, with
    nothing anywhere in the tree to see it.  `with_alias_bare_name` above is the
    reader that separates the four spellings, and it is a predicate on the STRING
    rather than a change to `fire_compiler`: the shape is recoverable, but
    recovering it in the parser would be a change to the shared AST that every
    other front end in this repository also parses, for one back end's rules.
    `test_formal_with.py`'s three alias rows are the measurement, and the
    subscript spelling is there because it is the third shape and a reader who
    has been refused twice tries the third thing they can think of.
    """
    line = getattr(where, "line", 0) or 0
    head = f"line {line}: " if line else ""
    return (
        f"{head}{fn.name}: `with … as …` is CPython's CONTEXT-MANAGER "
        f"PROTOCOL — `type(mgr).__enter__` binds the name — and this `as` "
        f"clause names somewhere this path cannot put the word `__enter__` "
        f"returns: a formal value is one 64-bit word, and a destructuring "
        f"target or a store into `obj.attr` is not a place one word goes. "
        f"Refused rather than bound to the whole value: the `as` clause is the "
        f"reader's own source, and dropping it leaves a program that runs the "
        f"body with the name unset."
    )


def dotted_struct_construction(func, structs: dict, import_aliases: dict) -> bool:
    """True when `mod.S(...)` constructs a struct this image knows — not an extern call.

    A dotted call has three readings and the emitters used to know two of them:
    `recv.m(...)` is a method call on a value, and `mod.f(...)` is a call across
    a module boundary.  The third is a CONSTRUCTION of a struct that the module
    publishes, and it has to be read as one because the dylib exports a struct's
    METHODS and not its constructor (`_formal_exports`: a frame-returning
    function is not exportable and a struct's fields are laid out by whoever
    builds the object), so `mod.S(...)` is lowered inline by the caller exactly
    as a bare `S(...)` is.

    Left on the extern path it became `BL mod.S` — a flat symbol no library
    defines — and the failure arrived as a link-time "the image would bind 1
    symbol(s) that nothing provides", which names a missing provider rather than
    the reading that was wrong.

    Two conditions, and the first is what keeps this from swallowing a method
    call: the BASE has to be a name this unit imported as a module
    (`import_aliases` is `{local name: (module, defining name)}`, the same table
    the dotted-callee arm of both emitters already consults), so `recv.m(...)`
    on a local, on a field, on a string literal or on a frame slot is not
    touched here — those are decided by position and by receiver shape, and they
    are decided earlier.
    """
    if not isinstance(func, F.MemberExpr):
        return False
    member = getattr(func, "member", None)
    if not isinstance(member, str) or member not in (structs or {}):
        return False
    base = getattr(func, "obj", None)
    return isinstance(base, F.IdentExpr) and base.name in (import_aliases or {})


def context_enter_returns_receiver(struct_def) -> bool:
    """True when this struct's `__enter__` hands its own receiver back.

    The `with` alias is bound to `__enter__`'s RESULT, so the alias is the struct
    exactly when `__enter__` returns the receiver — `def __enter__(self): return
    self`, the spelling whose whole purpose is to let the body call the manager's
    own methods.  `formal/build.py::_one_with_item` publishes the alias's struct
    from this predicate, so a method called through the alias dispatches to the
    manager the `with` actually entered rather than being refused by name.

    **Every return must yield the receiver, and there must be one.**  A path that
    returns a word (`return self.tag`, the `Ctx` fixture) makes the alias a word
    on that path, and naming the struct from the other paths would lift a method
    call to a struct the alias may not hold.  A method that falls off its end has
    no return at all and is the same hazard, so it answers False.

    The receiver name comes from `method_receiver_name`, so a manager that spells
    its receiver `this` is accepted on the same evidence as one that spells it
    `self`.  A parenthesised `return (self)` is the same node after the front end
    folds the parentheses, so it needs no separate arm.
    """
    enter = None
    for m in struct_methods(struct_def):
        if getattr(m, "name", None) == CONTEXT_ENTER:
            enter = m
            break
    if enter is None:
        return False
    recv = method_receiver_name(enter)
    if not isinstance(recv, str):
        return False
    returns = [n for n in iter_nodes(getattr(enter, "body", None) or ())
               if isinstance(n, F.ReturnStmt)]
    if not returns:
        return False
    for node in returns:
        value = getattr(node, "value", None)
        if not (isinstance(value, F.IdentExpr)
                and getattr(value, "name", None) == recv):
            return False
    return True


def context_exit_suppression_at_site(struct_def, expr):
    """The FIELD `__exit__` returns that THIS construction site makes truthy, or None.

    `context_exit_returns_truthy` decides the case where `__exit__`'s return
    VALUE is a literal, at the DECLARATION.  This is the other half of the same
    wrong answer, and it is the case that gate cannot see: `__exit__` returns a
    FIELD, so whether CPython would suppress depends on the value the field was
    given at the site that CONSTRUCTED the manager — `nullcontext` returns its
    own `exit_result`, and the doc's `Suppressor` returns `self.quiet`.  The
    declaration alone cannot answer it; the construction site can, when the
    argument is a foldable value.

    **What is read, and why that is the whole of it.**  The manager is built by
    an expression this build already recognises as a CONSTRUCTION — `S(...)` or
    `mod.S(...)`, the same spelling `with_expr_struct` resolves through — and the
    argument the field takes is the positional argument at the field's
    declaration slot, or the keyword naming it.  Only the IMPLICIT field-init
    constructor is read: a struct that declares `__init__` binds its parameters
    to fields in a body this reader does not follow, and following it would be
    the cross-FIELD flow `context_exit_returns_truthy`'s docstring names as the
    remaining limit.  A struct without `__init__` has no such gap — position `i`
    of the argument list IS field `i`.

    **A `None` means "not decided" and is read as "leave it alone"**, exactly as
    `_literal_return_truthiness`'s is: a non-construction expression, a computed
    argument, a field with no argument at this site (its default stands), and a
    truthiness none of the folded kinds answers all return None and the program
    is built as before.  The direction is the ONE-SIDED one the gate above is
    deliberately in: only a provably-true value is reported.

    The caller pairs this with "the body can actually RAISE", because a truthy
    `__exit__` is only consulted when the body leaves by an exception; on the
    fall-through path CPython discards the return value too, so refusing a
    non-raising body would refuse a program that is already correct.
    """
    if struct_def is None or expr is None:
        return None
    methods = {getattr(m, "name", None): m for m in struct_methods(struct_def)}
    exit_ = methods.get(CONTEXT_EXIT)
    if exit_ is None or "__init__" in methods:
        return None
    callee = getattr(expr, "func", None)
    if callee is None:
        return None
    # The construction has to NAME the struct.  `with make_suppressor() as v:`
    # is a call to a function whose declared return type happens to be this
    # struct, and its arguments are the function's, not the fields' — reading
    # them by position would invent a field value the source never wrote.
    spelled = getattr(callee, "name", None) or getattr(callee, "member", None)
    if not isinstance(spelled, str) or spelled != getattr(struct_def, "name", None):
        return None
    fields = struct_field_names(struct_def)
    args = list(getattr(expr, "args", None) or [])
    kwargs = list(getattr(expr, "kwargs", None) or [])
    exit_params = _param_names(getattr(exit_, "params", None))
    self_name = exit_params[0] if exit_params else None
    if self_name is None:
        return None
    for node in iter_nodes(getattr(exit_, "body", None) or ()):
        if not isinstance(node, F.ReturnStmt):
            continue
        value = getattr(node, "value", None)
        if not (isinstance(value, F.MemberExpr)
                and isinstance(value.obj, F.IdentExpr)
                and value.obj.name == self_name):
            continue
        name = value.member
        if name not in fields:
            continue
        argument = _constructor_argument_for(fields, name, args, kwargs)
        # `_literal_return_truthiness` is the ONE reader of "what would CPython
        # read this as", float arm included, so the site-level and the
        # declaration-level gates cannot disagree about what "true" means.
        if argument is not None and _literal_return_truthiness(argument):
            return name
    return None


def is_list_expr(e) -> bool:
    """True when `e` builds a LIST literal or a list comprehension.

    The third of the container-constructor predicates beside `is_dict_expr`,
    `is_set_expr` and `is_tuple_expr`, and the one the value model never needed
    until `==`/`!=` between two containers was lowered: a list, a set and a
    tuple all classify as `list:<elem>` (`is_set_expr`'s docstring says why), so
    nothing but a predicate of this shape can say which of the three an
    expression builds — and CPython's `==` differs between them (`[1] == (1,)`
    is False while `[1] == [1]` is True, and a set is order-independent where
    both others are not).

    `is_tuple_expr` is its twin and carries the measurement for the same
    conflation; this is the LIST half. A list comprehension is a
    `Comprehension` whose `kind` is `"list"` (or absent, the parser's default),
    exactly as the other three spellings are `"set"`/`"dict"`/`"tuple"`.
    """
    import fire_compiler as F
    if isinstance(e, F.ListExpr):
        return True
    return (isinstance(e, F.Comprehension)
            and getattr(e, "kind", "list") == "list")


def comprehension_element_not_sized(node_text: str) -> str:
    """The compiler-internal refusal for an element blob the per-iteration
    region was not sized for.

    `blob_bytes_reserved` sizes the region and the emitters that build the blob
    record what they actually reserved, and those are two readers of ONE
    layout. A program that got an answer from one and not the other would get
    the aliasing bug the region exists to remove — every element of the result
    pointing at one object — so the disagreement is stopped here instead.
    Reaching it is a compiler bug rather than a program error, and the sentence
    says so rather than blaming the source."""
    return (f"a comprehension's element (`{node_text}`) reserved a container "
            f"that the per-iteration element region was not sized for. The "
            f"region's size and the blob's own reservation are two readers of "
            f"one blob layout (`model.blob_bytes_reserved` and the emitter's "
            f"record of what it reserved), and this build got different "
            f"answers from them — which is a compiler bug, not a program error")


def _constructor_argument_for(fields, name, args, kwargs):
    """The argument this construction gives field `name`, or None.

    Keyword first — a construction may spell the field either way, and the
    keyword is the one spelling that cannot be confused with a different field —
    then the positional argument at the field's declaration slot.  An argument
    list shorter than the slot is a field taking its DEFAULT, which this reader
    does not fold and reports as not-decided.
    """
    for entry in kwargs:
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            continue
        if entry[0] == name:
            return entry[1]
    try:
        index = fields.index(name)
    except ValueError:
        return None
    if index < len(args):
        return args[index]
    return None


