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

    # (c) every ledger step names a step id that is either retired or still
    #     live in `bugs/plan/`. The step files were the work orders for this
    #     plan and are deleted with it; a ledger row whose step id names no
    #     retired step is a stale row and must be deleted with its hole.
    RETIRED_STEPS = frozenset({
        "step-00a", "step-00b", "step-00c", "step-00d", "step-00e",
        "step-00f", "step-00g", "step-01a", "step-01b", "step-02",
        "step-03a", "step-03b", "step-03c", "step-03d",
        "step-04a", "step-04b", "step-04c", "step-04d",
        "step-05a", "step-05b",
        "step-06a", "step-06b", "step-06c", "step-06d",
        "step-07a", "step-07b",
        "step-08a", "step-08b", "step-08c", "step-08d",
        "step-09", "step-10", "step-11a", "step-11b", "step-11c",
        "step-12a", "step-12b", "step-12c",
        "step-13a", "step-13b", "step-13c", "step-13d", "step-13e",
        "step-14a", "step-14b", "step-14c", "step-14d", "step-14e",
        "step-15a", "step-15b", "step-15c", "step-15d", "step-15e",
        "step-16a", "step-16b", "step-16c", "step-16d", "step-16e",
        "step-16f", "step-17",
        "step-18a", "step-18b", "step-18c", "step-18d",
        "step-19a", "step-19b", "step-19c", "step-20",
        "step-22", "step-23", "step-23a", "step-23b", "step-23c",
        "step-23d", "step-23e", "step-24", "step-25", "step-26",
        "step-27a", "step-27b", "step-27c", "step-28",
    })
    for name, hole in ledger.items():
        if hole.step not in RETIRED_STEPS:
            problems.append(
                f"ledger row {name!r} has step {hole.step!r} that is neither "
                f"retired nor a live bugs/plan/step-*.md"
            )

    return problems
