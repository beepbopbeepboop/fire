"""Render a precompiled signature record as Mojo source text.

The record shape is the JSON mapping produced and read by
`mojo/middle/mojoc_artifact.py` (DIAGNOSTICS_mojoc_imports-part2 part 1):
`kind`/`name`/`bracket_params`/`runtime_params`, each parameter being
`{"name", "type", "default"}` with `default` holding the source text (or
None).  This module is the single renderer for those records; the imported-
struct diagnostics call it to show what an artifact declared.

`render_signature` is pure: record in, string out.  Defaults are printed from
their stored source text and are never resolved through the record.  The
motivating case is an implicit conversion default (`Wrapper` from `Int`,
stored as `__init__(Int(4))`) whose `Wrapper.__init__` was never materialized
into the artifact: resolving it would either guess a simplification or raise,
while printing it as written is exactly what the diagnostic must show
(MOCO-4270).
"""

SYNTHETIC_MARKER = "# note - synthetic signature"

_KIND_KEYWORDS = {
    "struct": "struct",
    "trait": "trait",
    "function": "fn",
}


def _param_text(param):
    """Render one `name: Type = default` parameter record."""
    text = param.get("name") or ""
    type_text = (param.get("type") or "").strip()
    if type_text:
        text += ": " + type_text
    default = param.get("default")
    if default is not None:
        # Printed as written: no resolution through the record, no reparsing.
        text += " = " + (default if isinstance(default, str) else str(default))
    return text


def render_signature(record, synthetic=True):
    """Render `record` as a Mojo declaration line.

    Bracket params come first, then runtime params, each as
    `name: Type = default`.  When `synthetic` is true (the record came from a
    `.mojoc` artifact rather than source) the line ends with
    `SYNTHETIC_MARKER`.
    """
    kind = record.get("kind") or "struct"
    keyword = _KIND_KEYWORDS.get(kind, kind)
    text = keyword + " " + (record.get("name") or "")

    bracket = record.get("bracket_params") or []
    if bracket:
        text += "[" + ", ".join(_param_text(p) for p in bracket) + "]"

    runtime = record.get("runtime_params") or []
    if runtime:
        text += "(" + ", ".join(_param_text(p) for p in runtime) + ")"

    if synthetic:
        text += "  " + SYNTHETIC_MARKER
    return text
