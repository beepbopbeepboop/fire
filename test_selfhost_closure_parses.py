import os
import sys

import cas
import fire_compiler as fc
import gimple_codegen as gc


def _parse_source(src, filename="<input>"):
    toks = fc.py_tokenize(src)
    p = gc.Parser(toks)
    # parse_module returns a list of statements in this tree
    p.parse_module()


def main():
    failures = []

    # Controls from bugs/CODEGEN_dict_slot_reads_refuse_compiler_sources-part3.md
    try:
        _parse_source("trait Marked:\n    pass\n", "<trait-control>")
        # verify it declares a trait (StructDef/TraitDef) not an assignment?
        toks = fc.py_tokenize("trait Marked:\n    pass\n")
        m = gc.Parser(toks).parse_module()
        node = m[0] if isinstance(m, list) and m else m
        if type(node).__name__ != "TraitDef":
            failures.append(f"<trait-control>:1:1: expected TraitDef, got {type(node).__name__}")
    except SyntaxError as e:
        failures.append(f"<trait-control>:{getattr(e,'lineno','?')}:{getattr(e,'offset','?')}: {e.msg if hasattr(e,'msg') else e}")

    try:
        _parse_source("lambda fn=fn, st=st: fn\n", "<lambda-control>")
    except SyntaxError as e:
        failures.append(f"<lambda-control>:{getattr(e,'lineno','?')}:{getattr(e,'offset','?')}: {e.msg if hasattr(e,'msg') else e}")

    here = os.path.dirname(os.path.abspath(__file__))
    for name in cas.selfhost_inputs():
        if not name.endswith(".py"):
            continue
        path = os.path.join(here, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()
            _parse_source(src, path)
        except SyntaxError as e:
            failures.append(
                f"{name}:{getattr(e,'lineno','?')}:{getattr(e,'offset','?')}: {e.msg if hasattr(e,'msg') else e}"
            )
        except Exception as e:
            failures.append(f"{name}:?:?: unexpected {type(e).__name__}: {e}")

    if failures:
        for f in failures:
            print(f)
        print(f"{len(failures)} failure(s)", file=sys.stderr)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
