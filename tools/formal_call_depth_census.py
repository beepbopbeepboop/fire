#!/usr/bin/env python3
"""How deep is an ACYCLIC call chain in this corpus, against what the stack floor affords.

    python3 tools/formal_call_depth_census.py [--top N]

The measurement `bugs/FORMAL_stack_floor_does_not_guard_an_acyclic_chain.md`
names as its step 1 — "measure first: the maximum call-graph DEPTH over
`formal/`, `std/` and the repo's own files, and the depth at which a frame chain
exceeds `STACK_FLOOR_BUDGET_BYTES`. If no corpus file is within an order of
magnitude of the budget, this document is a stated limit with no work behind it"
— done WITHOUT a sweep.

**Why not the sweep.** A sweep answers "does this FILE build", and this question
is not about a build: a file refused for a host import, a `__mlir_op`, or a
dylib export still has a call graph, and its depth is the number. Worse, a sweep
cannot answer it at all for the file that matters most — the deepest image in the
corpus is very likely one that does NOT build, so a sweep would report the
opposite of the truth about the risk. The same reasoning, and the same
instrument shape, as `tools/formal_frame_field_census.py`.

**The graph is `model.call_graph_edges`, the guard's own edge rule.** One
implementation, or the measurement would be of a different graph than the one the
guard reasons about — which is the failure this file exists to rule out rather
than to commit.

**Per image, not per corpus.** A formal build compiles one module to one image,
so the stack a call chain walks is the stack of ITS OWN image's frames; a depth
summed over every file in the tree would be a number about no program at all.
Each file is therefore measured on its own, with the function table the EMITTER
sees — top-level `def`s plus every struct method lifted to `Struct_method`, which
is what `formal/build.py` hands the backend.

**The depth is an UPPER BOUND** (`model.call_graph_depth` says why), in the same
direction as the sweep's `FILES BLOCKED`: a simple path visits at most each
strongly-connected component's SIZE, and a component that is a clique rather than
a small cycle is what would make the bound loose. The edges are themselves a
superset (`model.call_graph_edges`), so the static figure is an upper bound on the
static figure, which is an upper bound on what any one execution actually walks.

**The `unguard` column is the RESIDUAL the rule leaves, computed with the rule's
own predicate** — `model.stack_floor_guarded_names`, not a copy of it, so this
cannot measure a different residual than the one the guard has. The per-export
contract proof declines to emit a contract for an export whose body contains ANY
conditional branch, so the guard can go in every body that already has one and
in no other: the residual is a chain of bodies with no branch at all, and that
chain's depth is the number the widening cannot reach. Over this corpus it is
**7 frames at the deepest, a median of 3**, against the 60 arm64 affords — so
the residual is a bounded 7 rather than an unbounded "finite".

**The budget is read, not typed in.** `formal/arm64_codegen.py::_SCRATCH` and
`formal/x86_64_codegen.py::_BLOB_BYTES` are the per-prologue subtractions, and
they are why the two architectures differ by an order of magnitude: arm64
subtracts 128 KiB a frame and traps at 59, x86-64 subtracts 16 KiB and traps at
471.
"""
import argparse
import copy
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import fire_compiler as F
import formal.model as M

SKIP_DIRS = {".git", ".tmp", "build", "__pycache__", "cas", "node_modules"}


def frame_bytes():
    """`{backend: bytes one prologue subtracts}`, read from the two emitters.

    Read rather than typed so that the number this census compares a depth
    against cannot drift away from the one the guard uses: `formal/
    arm64_codegen.py::_emit_prologue` subtracts `_SCRATCH` and x86-64's
    subtracts `_BLOB_BYTES`, and those two constants are why arm64 traps at 59
    frames and x86-64 at 471.
    """
    import formal.arm64_codegen as A
    import formal.x86_64_codegen as X
    return {"arm64": A._SCRATCH, "x86_64": X._BLOB_BYTES}


def function_table(stmts):
    """The functions the EMITTER sees for one parsed module.

    `formal/build.py` lifts every struct method into the function table under
    `model.method_function_name` before codegen runs, and a lifted `self.ping()`
    call carries the lifted NAME — so a graph built from the module's top-level
    `def`s alone has `ping` on one side and `R_ping` on the other and finds no
    edge. The same lift and the same rename, applied here rather than invented,
    for the same reason `_STACK_FLOOR_PROBES` in `test_formal_run.py` does it.
    """
    structs = {st.name: st for st in stmts if isinstance(st, F.StructDef)}
    fns = [st for st in stmts if isinstance(st, F.FunctionDef)]
    for st in structs.values():
        for method in M.struct_methods(st):
            lifted = copy.deepcopy(method)
            lifted.name = M.method_function_name(st.name, method.name)
            fns.append(lifted)
    return fns, structs


def measure(path):
    """`(depth, n_functions, n_edges, unguarded_depth)` for one module, or
    None if it will not parse."""
    try:
        with open(path) as fh:
            stmts = F.Parser(F.py_tokenize(fh.read())).parse_module()
    except Exception:
        return None
    fns, structs = function_table(stmts)
    if not fns:
        return None
    edges = M.call_graph_edges(fns, structs)
    inside = sum(len(v) for v in edges.values())
    # The residual `stack_floor_guarded_names` leaves, which is what this column
    # has always meant: the same graph with every GUARDED caller's edges removed,
    # so what is left is a chain of bodies the guard does not reach.
    # `M.body_has_conditional_branch` is the rule's OWN predicate and not a second
    # copy of it — a census that re-spelled the rule would measure a different
    # residual than the one the rule has.
    #
    # **It is asked of the MODULE-DYLIB rule, deliberately** (`every_function`
    # left False), and that is the honest reading of what is left: a PROGRAM image
    # guards every prologue, so its residual is 0 by construction, and a census
    # that reported 0 for it would be reporting the flag rather than the corpus.
    # What this column still measures is the rule a module dylib is emitted with,
    # where every function may be an export with a proved per-export contract —
    # see `model.stack_floor_guarded_names` for why that image cannot take the
    # third rule.
    guarded = M.stack_floor_guarded_names(fns, structs)
    slim = {name: {c for c in callees if c not in guarded}
            for name, callees in edges.items() if name not in guarded}
    return M.call_graph_depth(edges), len(fns), inside, M.call_graph_depth(slim)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, default=25,
                    help="how many of the deepest images to print")
    args = ap.parse_args()

    from module_loader import STDLIB_PATH
    roots = [(HERE, "repository"), (os.path.join(STDLIB_PATH, "std"), "stdlib")]

    frames = frame_bytes()
    print("stack floor: budget %d bytes; a frame is %s"
          % (M.STACK_FLOOR_BUDGET_BYTES,
             ", ".join("%s %d KiB" % (b, f // 1024)
                       for b, f in sorted(frames.items()))))
    budget_depth = {b: M.STACK_FLOOR_BUDGET_BYTES // f
                    for b, f in frames.items()}
    print("depth the budget affords (no tail frame, no spill): %s"
          % ", ".join("%s %d" % (b, d) for b, d in sorted(budget_depth.items())))
    print()

    rows = []
    scanned = parsed = 0
    for root, label in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in sorted(filenames):
                if not fn.endswith((".mojo", ".py")):
                    continue
                scanned += 1
                path = os.path.join(dirpath, fn)
                got = measure(path)
                if got is None:
                    continue
                parsed += 1
                rows.append((got[0], got[1], got[2], got[3], label,
                             os.path.relpath(path, HERE)))
    rows.sort(reverse=True)
    print("scanned %d files, measured %d (the rest do not parse as a module)"
          % (scanned, parsed))
    if not rows:
        return 0
    worst = rows[0][0]
    worst_straight = max(r[3] for r in rows)
    print("deepest image: %d frames" % worst)
    for backend, d in sorted(budget_depth.items()):
        ratio = ("%.1fx the budget" % (worst / d) if worst else "0")
        print("  %-6s traps at %3d frames; deepest measured is %d = %s"
              % (backend, d, worst, ratio))
    print("deepest chain the guard does NOT reach (bodies with no branch, and "
          "no cycle): %d frames" % worst_straight)
    print()
    print("%-5s %-5s %-6s %-8s %s" % ("depth", "fns", "edges", "unguard", "image"))
    for depth, nfn, nedge, slim, label, rel in rows[:args.top]:
        flag = ""
        for backend, d in budget_depth.items():
            if depth >= d:
                flag = "  <-- AT/OVER the %s budget" % backend
        print("%-5d %-5d %-6d %-8d [%s] %s%s"
              % (depth, nfn, nedge, slim, label, rel, flag))
    by_label = {}
    for depth, _n, _e, _s, label, _r in rows:
        by_label.setdefault(label, []).append(depth)
    print()
    for label, depths in sorted(by_label.items()):
        depths.sort()
        half = len(depths) // 2
        print("%-12s %d images; median depth %d, p90 %d, max %d"
              % (label, len(depths), depths[half],
                 depths[int(len(depths) * 0.9)], depths[-1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
