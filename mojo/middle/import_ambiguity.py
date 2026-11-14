"""The `import of 'X' is ambiguous` diagnostic, shared by every import scope.

Modular rejects a name that two different `from M import X` statements bind
in one scope. It reports the error at the second import's name, then one note
per conflicting declaration:

    <file>:<line>:<col>: error: import of 'X' is ambiguous
    from M2 import X
                    ^
    <decl file>:<line>:<col>: note: 'X' declared here
    <declaration text>
    ^
    <decl file>:<line>:<col>: note: 'X' also declared here
    <declaration text>
    ^

The declaration text is the source line when the defining module's source is
on disk. When that source is gone (a package precompiled to a `.mojoc`
artifact and deleted) the text is the stored signature rendered by
`mojoc_signature.render_signature`, marked `# note - synthetic signature`.

Two entry points, one message format:

* `check_module_from_imports` for the module scope, where every conflict in
  the file is collected and reported together (modular keeps going after the
  first ambiguity, so the user sees all of them in one run).
* `ambiguous_import_error` for a single conflict found by a caller that has
  its own scope (a function body's pre-scan).
"""

import os
import re

from mojo.middle.types import FromImportStmt


def _names_of(stmt):
    """`(name, alias|None)` pairs of a FromImportStmt, whichever field carries them."""
    out = []
    for _na in (getattr(stmt, 'names', None) or []):
        if isinstance(_na, (tuple, list)):
            out.append((_na[0], _na[1] if len(_na) > 1 else None))
        else:
            out.append((_na, None))
    return out


def _declaration_of(gen, module, name):
    """`(path, line, col, text)` for the top-level declaration of `name` in
    `module`, or None when neither its source nor its artifact is reachable.

    The source is preferred when it exists: its line is printed as written.
    Otherwise a `.mojoc` artifact on the same search path supplies the record,
    and its stored location and rendered signature stand in for the source."""
    src = gen._submodule_source_path(module)
    if src and src.endswith('.mojo') and os.path.isfile(src):
        try:
            with open(src) as f:
                lines = f.readlines()
        except OSError:
            lines = []
        pat = re.compile(r'^\s*(?:def|fn|struct|trait|enum|alias|comptime|var|let)\s+'
                         + re.escape(name) + r'\b')
        for i, ln in enumerate(lines, 1):
            if pat.match(ln):
                return (src, i, 1, ln.rstrip())
    for cand in gen._module_candidate_paths(module) or []:
        if not (cand.endswith('.mojoc') and os.path.isfile(cand)):
            continue
        from mojo.middle import mojoc_artifact
        from mojo.middle.mojoc_signature import render_signature
        try:
            art = mojoc_artifact.load_artifact(cand)
        except (OSError, ValueError):
            continue
        rec = (art.get('structs') or {}).get(name) or (art.get('functions') or {}).get(name)
        if rec is None:
            continue
        return (rec.get('file') or cand, rec.get('line') or 1, rec.get('col') or 1,
                render_signature(rec))
    return None


def _canonical_home(gen, module, name):
    """The module that DEFINES `name`, following re-exports.

    Two spellings of one re-exported symbol are not an ambiguity, so the
    conflict test compares defining modules, not the modules written in the
    import statements. Unresolvable names keep the module as written."""
    for kind in ('fn', 'struct'):
        try:
            home = gen._find_symbol_home_module(module, name, kind)
        except Exception:
            home = None
        if home:
            return home
    return module


def _import_name_col(source_line, name):
    """1-based column of `name` in the `import` clause of `source_line`."""
    if not source_line:
        return 1
    kw = re.search(r'\bimport\b', source_line)
    start = kw.end() if kw else 0
    hit = re.compile(r'\b' + re.escape(name) + r'\b').search(source_line, start)
    return hit.start() + 1 if hit else 1


def _caret(col):
    return ' ' * max(col - 1, 0) + '^'


def ambiguous_import_error(gen, name, first_module, second_module, line, col=None):
    """The full diagnostic for `name` imported from `first_module` and then
    from `second_module`, with the second import at `line` (1-based) of the
    file being compiled."""
    filename = getattr(gen, '_current_filename', '') or ''
    source = getattr(gen, '_source_text', '') or ''
    src_lines = source.splitlines()
    import_text = src_lines[line - 1].rstrip() if 0 < line <= len(src_lines) else ''
    if col is None:
        col = _import_name_col(import_text, name)
    where = f'{filename}:{line}:{col}: ' if filename else f'{line}:{col}: '
    out = [f'{where}error: import of \'{name}\' is ambiguous']
    if import_text:
        out += [import_text, _caret(col)]
    for label, mod in (('declared here', first_module), ('also declared here', second_module)):
        decl = _declaration_of(gen, mod, name)
        if decl is None:
            continue
        path, dline, dcol, text = decl
        out.append(f"{path}:{dline}:{dcol}: note: '{name}' {label}")
        out += [text, _caret(dcol)]
    return '\n'.join(out)


def check_module_from_imports(gen, stmts):
    """Raise the ambiguity diagnostics for every module-scope name that two
    different modules bind through `from M import X`.

    All conflicts are gathered before raising, so one run reports every
    ambiguous name, as modular does. A repeated import from the same module,
    or from a module that re-exports the same definition, is not a conflict."""
    bound = {}      # bound name -> module string of its first import
    errors = []
    for st in stmts or []:
        if not isinstance(st, FromImportStmt) or getattr(st, 'wildcard', False):
            continue
        for name, alias in _names_of(st):
            local = alias if alias else name
            prev = bound.get(local)
            if prev is None:
                bound[local] = st.module
                continue
            if prev == st.module:
                continue
            if _canonical_home(gen, prev, name) == _canonical_home(gen, st.module, name):
                continue
            errors.append(ambiguous_import_error(
                gen, name, prev, st.module, getattr(st, 'line', 0) or 0))
    if errors:
        raise RuntimeError('\n'.join(errors))
