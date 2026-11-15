"""Precompiled .mojoc signature artifacts.

One JSON artifact per package carrying top-level struct/function/trait
signatures (bracket params, runtime params, default source text, and a
trait's required methods) so an importer can read them when the package
sources are absent. Part 1 stores/reads records; conformance checking of an
imported record lives in `mojo/middle/mojoc_conformance.py`, and rendering a
record as signature text is part 2/3.
"""

import json
import os

import fire_compiler


def _param_record(name, type_text, default_text):
    return {
        "name": name,
        "type": type_text or "",
        "default": default_text,
    }


def _function_bracket_params(fn):
    names = list(getattr(fn, "comptime_params", []) or [])
    defaults = getattr(fn, "comptime_param_defaults", {}) or {}
    ann = getattr(fn, "comptime_param_annotations", {}) or {}
    out = []
    for n in names:
        # comptime defaults are AST nodes; source text not preserved on fn.
        # Best-effort: if already a string, keep it, else None.
        d = defaults.get(n)
        if d is None:
            dt = None
        elif isinstance(d, str):
            dt = d
        else:
            # No stable source text on the node in general; keep None.
            dt = None
        out.append(_param_record(n, ann.get(n, ""), dt))
    return out


def _function_runtime_params(fn):
    params = getattr(fn, "params", []) or []
    param_defaults = getattr(fn, "param_defaults", {}) or {}
    out = []
    for p in params:
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            name, typ = p[0], p[1]
        elif isinstance(p, (list, tuple)) and len(p) == 1:
            name, typ = p[0], ""
        else:
            name, typ = str(p), ""
        d = param_defaults.get(name)
        if d is None:
            dt = None
        elif isinstance(d, str):
            dt = d
        else:
            dt = None
        out.append(_param_record(name, typ or "", dt))
    return out


def _struct_record(sd):
    binfo = list(getattr(sd, "bracket_param_info", []) or [])
    if binfo:
        bracket = [_param_record(n, t, d) for (n, t, d) in binfo]
    else:
        # Fallback from bracket_types / type_param_names (no defaults text).
        btypes = {n: t for (n, t) in (getattr(sd, "bracket_types", []) or [])}
        names = list(getattr(sd, "type_param_names", []) or []) or list(btypes.keys())
        bracket = [_param_record(n, btypes.get(n, ""), None) for n in names]
    return {
        "kind": "struct",
        "name": sd.name,
        "bracket_params": bracket,
        "runtime_params": [],
    }


def _function_record(fn):
    ret = fn.return_type if isinstance(fn.return_type, str) else None
    return {
        "kind": "function",
        "name": fn.name,
        "bracket_params": _function_bracket_params(fn),
        "runtime_params": _function_runtime_params(fn),
        "ret": ret,
    }


def _read_and_parse(path):
    with open(path) as f:
        src = f.read()
    mod = fire_compiler.Parser(fire_compiler.py_tokenize(src)).with_filename(path).parse_module()
    return src, mod


def _trait_record(name, source):
    """A trait record with the requirement signatures a bound check needs.

    The method list is `elaborate.extract_trait`'s — the same extraction the
    source path's conformance checker uses — so a record and a live module
    answer the requirement question identically."""
    import elaborate
    methods = elaborate.extract_trait(source, name) or []
    return {
        "kind": "trait",
        "name": name,
        "bracket_params": [],
        "runtime_params": [],
        "methods": [{"name": n, "params": list(p or []), "ret": r}
                    for (n, p, r) in methods],
    }


def _located(rec, path, node):
    """Stamp a record with where its declaration sat in the source: the file,
    and the 1-based line and column (the parser's column is 0-based). The
    diagnostics point their notes here once the source itself is deleted."""
    rec["file"] = os.path.abspath(path)
    rec["line"] = getattr(node, "line", 0) or 1
    rec["col"] = (getattr(node, "col", 0) or 0) + 1
    return rec


def extract_package_signatures(pkg_dir):
    """Return {"structs": {name: record}, "functions": {name: record}} for a pkg."""
    structs = {}
    funcs = {}
    if not os.path.isdir(pkg_dir):
        return {"structs": structs, "functions": funcs}
    # Collect from all .mojo files in the package directory (non-recursive
    # sufficient for this part; __init__ and sibling modules).
    for fn in sorted(os.listdir(pkg_dir)):
        if not fn.endswith('.mojo'):
            continue
        path = os.path.join(pkg_dir, fn)
        try:
            src, mod = _read_and_parse(path)
        except Exception:
            continue
        for s in mod:
            if isinstance(s, fire_compiler.StructDef):
                structs[s.name] = _located(_struct_record(s), path, s)
            elif isinstance(s, fire_compiler.FunctionDef):
                funcs[s.name] = _located(_function_record(s), path, s)
            elif isinstance(s, fire_compiler.TraitDef):
                # Traits appear as bracket-parameter bounds; their required
                # method signatures are what an import-time conformance check
                # must compare against, so record them with the trait.
                structs.setdefault(s.name, _located(_trait_record(s.name, src), path, s))
    return {"structs": structs, "functions": funcs}


def _package_sources(pkg_dir):
    """{file name: source text} of the package's top-level .mojo files. Carried
    so an importer whose package sources are gone can still re-read the
    declarations (traits, where clauses, defaults) the signature records do not
    keep, to render synthetic-signature diagnostics."""
    out = {}
    if os.path.isdir(pkg_dir):
        for fn in sorted(os.listdir(pkg_dir)):
            if fn.endswith('.mojo'):
                try:
                    with open(os.path.join(pkg_dir, fn), encoding='utf-8') as f:
                        out[fn] = f.read()
                except OSError:
                    pass
    return out


def write_artifact(pkg_dir, out_path):
    recs = extract_package_signatures(pkg_dir)
    pkg_name = os.path.basename(os.path.normpath(pkg_dir))
    data = {"package": pkg_name, "structs": recs["structs"], "functions": recs["functions"],
            "sources": _package_sources(pkg_dir)}
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(data, f, sort_keys=True)
    return data


def load_artifact(path):
    with open(path) as f:
        return json.load(f)


def _find_mojoc_in_dirs(pkg_name, search_dirs):
    for d in search_dirs or []:
        cand = os.path.join(d, pkg_name + ".mojoc")
        if os.path.isfile(cand):
            return cand
    return None


def resolve_import(pkg_name, symbol, search_dirs):
    """Resolve `from pkg_name import symbol` from a .mojoc in search_dirs."""
    path = _find_mojoc_in_dirs(pkg_name, search_dirs)
    if path is None:
        return None
    art = load_artifact(path)
    if symbol in art.get("structs", {}):
        return art["structs"][symbol]
    if symbol in art.get("functions", {}):
        return art["functions"][symbol]
    return None


def mojoc_import_roots(search_dirs):
    """Return list of (pkg_name, artifact_path) for *.mojoc files in search_dirs."""
    out = []
    for d in search_dirs or []:
        try:
            for fn in os.listdir(d):
                if fn.endswith('.mojoc'):
                    out.append((fn[:-6], os.path.join(d, fn)))
        except Exception:
            pass
    return out
