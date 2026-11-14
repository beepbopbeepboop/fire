"""Precompiled .mojoc signature artifacts.

One JSON artifact per package carrying top-level struct/function signatures
(bracket params, runtime params, and default source text) so an importer can
read them when the package sources are absent. Part 1 stores/reads records;
printing diagnostics is part 2/3.
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
    return {
        "kind": "function",
        "name": fn.name,
        "bracket_params": _function_bracket_params(fn),
        "runtime_params": _function_runtime_params(fn),
    }


def _parse_file(path):
    with open(path) as f:
        src = f.read()
    return fire_compiler.Parser(fire_compiler.py_tokenize(src)).with_filename(path).parse_module()


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
            mod = _parse_file(path)
        except Exception:
            continue
        for s in mod:
            if isinstance(s, fire_compiler.StructDef):
                structs[s.name] = _struct_record(s)
            elif isinstance(s, fire_compiler.FunctionDef):
                funcs[s.name] = _function_record(s)
            elif isinstance(s, fire_compiler.TraitDef):
                # Traits can appear as type bounds; store minimal record.
                structs.setdefault(s.name, {
                    "kind": "trait",
                    "name": s.name,
                    "bracket_params": [],
                    "runtime_params": [],
                })
    return {"structs": structs, "functions": funcs}


def write_artifact(pkg_dir, out_path):
    recs = extract_package_signatures(pkg_dir)
    pkg_name = os.path.basename(os.path.normpath(pkg_dir))
    data = {"package": pkg_name, "structs": recs["structs"], "functions": recs["functions"]}
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
