"""The proof-gap ledger for scaffold `sorry` holes.

Scaffold holes live ONLY in `lib/Scaffold.lean` and are counted by
`test_formal_proof_gaps.py` using `formal.lean::library_census`. Every
`by sorry` in `Scaffold` must appear in `SCAFFOLD_HOLES`, and holes in any
other library module are not permitted.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Hole:
    step: str      # e.g. "step-03c"
    reason: str    # one line: what is unproved and why it is believed true
    kind: str      # "scaffold" | "control" | "placeholder"
    #   scaffold    a real statement whose proof is open
    #   control     a canary for the census itself
    #   placeholder a hole whose STATEMENT is not written yet (it states `True`);
    #               exempt from the vacuity check, and only while the design step
    #               that will state it is open (the reason names it)


SCAFFOLD_HOLES: dict[str, Hole] = {
    "scaffold_canary": Hole(
        "step-01a",
        "census positive control; delete when the first real scaffold lands",
        "control",
    ),
    "peephole_x86_imm_zero_flags": Hole(
        "step-04d",
        "add r,0/sub r,0 flags: cf/of_ false, zf/sf from r (x86_flags_add/x86_flags_sub)",
        "scaffold",
    ),
    "peephole_arm64_str_pair": Hole(
        "step-03d",
        "two identical STR Xt,[Xn,#imm] deleted",
        "scaffold",
    ),
    "peephole_arm64_ldr_pair": Hole(
        "step-03d",
        "two identical LDR Xt,[Xn,#imm] with Xt!=Xn deleted",
        "scaffold",
    ),
    "peephole_arm64_store_load": Hole(
        "step-03c",
        "STR followed by LDR of same location deleted",
        "scaffold",
    ),
    "scaffold_cell_writeback_one_exit": Hole(
        "step-18d",
        "by-reference one-field mutator write-back (single exit): depth bound as hypothesis, obligation to prove",
        "placeholder",
    ),
    "scaffold_cell_writeback_multi_exit": Hole(
        "step-18d",
        "by-reference one-field mutator write-back (multiple exits): per-exit obligation scaffolded",
        "placeholder",
    ),
    "peephole_x86_store_load_disp8": Hole(
        "step-04b",
        "x86 `mov [b+d8],r ; mov r,[b+d8]` equals the store alone (no SIB, no RIP-relative)",
        "scaffold",
    ),

    "peephole_x86_mov_self_rev": Hole(
        "step-04a",
        "x86 `mov r,r` spelled 48 8b c0 is a no-op (mirror of the proved peephole_x86_mov_self)",
        "scaffold",
    ),
}


def diff_holes(census: dict[str, tuple], ledger: dict[str, Hole]) -> list[str]:
    """Compare library_census output against the ledger.

    `census` is `stem -> (n_sorries, (names...))` as returned by
    `formal.lean::library_census`. Returns human-readable problems; empty
    list means the census matches the ledger.
    """
    problems = []

    # Get Scaffold's sorry'd declarations
    scaffold_census = census.get("Scaffold")
    scaffold_names = set()
    if scaffold_census is not None:
        _n, names = scaffold_census
        scaffold_names = set(names)

    ledger_names = set(ledger.keys())

    # (a) Scaffold's sorry'd declarations == ledger keys, both directions
    for name in sorted(scaffold_names - ledger_names):
        problems.append(
            f"unledgered hole in Scaffold: {name!r} (in census but not in SCAFFOLD_HOLES)"
        )
    for name in sorted(ledger_names - scaffold_names):
        problems.append(
            f"stale ledger row: {name!r} in SCAFFOLD_HOLES but not reported by census in Scaffold"
        )

    # (b) every OTHER library module has 0 sorries
    for stem, cens in census.items():
        if stem == "Scaffold":
            continue
        n_sorries, names = cens
        if n_sorries != 0 or names:
            problems.append(
                f"hole in non-Scaffold module {stem!r}: {names} ({n_sorries} sorries)"
            )

    # (c) every ledger step names an existing bugs/plan/step-*.md (prefix match on the id)
    import os

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    plan_dir = os.path.join(repo_root, "bugs", "plan")
    for name, hole in ledger.items():
        step_id = hole.step  # e.g. "step-01a"
        # Look for any file starting with step_id
        found = False
        if os.path.isdir(plan_dir):
            for fname in os.listdir(plan_dir):
                if fname.startswith(step_id + "-") or fname == step_id + ".md" or fname.startswith(step_id + "."):
                    found = True
                    break
        if not found:
            problems.append(
                f"ledger row {name!r} has step {hole.step!r} with no matching bugs/plan/step-*.md"
            )

    return problems
