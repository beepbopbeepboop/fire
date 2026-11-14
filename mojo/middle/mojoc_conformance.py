"""Conformance checking for structs imported from a `.mojoc` artifact.

Part 1 of `bugs/mid/DIAGNOSTICS_mojoc_imports-part1.md`: importing a
precompiled module whose stored signature violates a trait/conformance
constraint must report the ordinary conformance diagnostic, not succeed
silently.

The artifact reader (`mojo/middle/mojoc_artifact.py`) is deliberately a pure
record store — it carries the *stored* signature a source build would have
seen, including each bracket parameter's trait/type text and its default's
source text. This module is the one place that turns such a record into a
check: it reuses `elaborate.check_conformance` (the same check the source path
runs) by reconstructing the artifact's trait declarations as source text and
appending the consumer's own source, so there is no second conformance
implementation and no second diagnostic formatter.

The modular case this reproduces is
`import_mojoc_conformance_error.mojo`, whose package stores

    trait Marked:
        def marked(self):
            ...

    struct Container[T: Marked, H: Helper = default_helper]:
        ...

and whose consumer instantiates `Container[NotMarked]` after the package
sources are deleted. `NotMarked` does not implement `marked`, so the import
must fail with

    error: 'Container' parameter 'T' has 'Marked' type, but value has type 'AnyStruct[NotMarked]'
"""


def _split_bound(bound):
    """`S[A]` -> `S`; `S` -> `S`. The artifact stores the bound as the source
    text the declaration carried, which may itself be a type application."""
    head = (bound or '').split('[', 1)[0].strip()
    return head


def trait_source(record):
    """One trait record rendered as the Mojo declaration it came from."""
    name = record.get('name', '')
    methods = list(record.get('methods') or [])
    lines = [f"trait {name}:"]
    if not methods:
        lines.append("    pass")
    for m in methods:
        mname = m.get('name', '')
        params = ['self']
        for i, t in enumerate(m.get('params') or []):
            params.append(f"_p{i}: {t}" if t else f"_p{i}")
        head = f"    def {mname}({', '.join(params)})"
        ret = m.get('ret')
        if ret:
            head += f" -> {ret}"
        lines.append(head + ":")
        lines.append("        ...")
    return "\n".join(lines)


def traits_source(records):
    """Every trait record in `records` (a name -> record map) as source text.

    Struct/function records are skipped: only a trait declaration can answer
    `elaborate.check_conformance`'s question about a bound."""
    parts = [trait_source(r) for r in (records or {}).values()
             if r.get('kind') == 'trait']
    return "\n\n".join(parts)


def conformance_diagnostic(struct_record, type_args, consumer_src, records,
                           location=''):
    """The modular conformance error for `struct_record[type_args]`, or None.

    `consumer_src` is the importing module's own source (where the concrete
    type arguments are declared), `records` the artifact's whole record map
    (structs and traits), and `location` an optional `file:line:col` prefix.

    Each supplied type argument is checked against the corresponding bracket
    parameter's stored bound. A bound that names no recorded trait is not a
    trait constraint this checker can decide — value parameters and plain
    type-annotation bounds are left accepted, the same "unknown stays
    accepted" rule the source path's bound check follows.
    """
    if not struct_record:
        return None
    struct_name = struct_record.get('name', '')
    bracket = list(struct_record.get('bracket_params') or [])
    for i, arg in enumerate(type_args or []):
        if i >= len(bracket):
            break
        param = bracket[i]
        bound = (param.get('type') or '').strip()
        if not bound:
            continue
        trait = (records or {}).get(_split_bound(bound))
        if not trait or trait.get('kind') != 'trait':
            continue

        import elaborate
        src = traits_source(records)
        if consumer_src:
            src = src + "\n\n" + consumer_src
        try:
            ok, _missing = elaborate.check_conformance(src, arg, bound)
        except Exception:
            # A record this checker cannot render is "unknown", never a
            # violation: the import may not be rejected on a broken artifact.
            continue
        if ok:
            continue
        # Modular prints the offending type argument as a type value
        # (`AnyStruct[NotMarked]`), and its FileCheck line is the acceptance
        # for this import case, so the one formatter spells it the same way.
        return (f"{location}error: '{struct_name}' parameter "
                f"'{param.get('name', '')}' has '{bound}' type, but value has "
                f"type 'AnyStruct[{arg}]'")
    return None
