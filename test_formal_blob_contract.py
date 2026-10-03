#!/usr/bin/env python3
"""test_formal_blob_contract.py — the MODULE-OWNED BLOB declaration is honest.

`formal/imports.py`'s `HOST_OWNED_BLOBS` is the one place this tree says what
the words of another module's pointer mean: `listdir` and `walk` hand back a
block whose word 0 is the entry COUNT and whose words `1 + i` are `malloc`'d
names the module's own release frees. It is a DECLARATION rather than something
derived, and `HOST_OWNED_BLOBS`'s own comment gives the reason — `str_alloc`
also returns a `malloc`'d block and the caller owns every word of that one, so
what separates the two is who frees the words, and a callee's own body does not
say.

A declaration that drifts from the module it describes is worse than no
declaration: the refusal it produces (`model.owned_blob_store_refusal`) would
refuse a store that is fine, or — the direction that matters — let a store
through that the module's `free` then walks as a pointer. So every claim the
table makes is checked against the module's SOURCE here, and the end-to-end half
— that the contract reaches a manifest and an importer refuses by name — is
`test_formal_os.py`'s `blob` group, which builds the real `os` dylib.

    python3 test_formal_blob_contract.py [-v]
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HOSTMODS = os.path.join(HERE, "formal", "hostmods")

sys.path.insert(0, HERE)
from formal.imports import HOST_OWNED_BLOBS, host_owned_blob  # noqa: E402


def module_source(module):
    """The file that defines `module`, or None when there is none.

    A host module is a path, not a name: `os` is `os/__init__.mojo`,
    `os.path` is `os/path/__init__.mojo`, and everything else is
    `<name>.mojo`. That is `formal/imports.py`'s `_HOSTMODS_ROOT` layout, and a
    table entry pointing at a module with no source is the first thing this
    file has to be able to say.
    """
    parts = module.split(".")
    cand = os.path.join(HOSTMODS, *parts) + ".mojo"
    if os.path.isfile(cand):
        return cand
    pkg = os.path.join(HOSTMODS, *parts, "__init__.mojo")
    return pkg if os.path.isfile(pkg) else None


def read(path):
    with open(path) as f:
        return f.read()


def def_body(text, name):
    """The source of `def name(...)`'s body, indented, or None.

    A text scan and not a parse, and the reason is stated in each check: what
    is being verified is a SHAPE the source spells (`free(names[1 + i])` under a
    loop bounded by `names[0]`), and a shape in the source is what a reader
    checks it against. Parsing to answer it would make the drift test itself
    depend on the parser under test, which is the wrong direction for a test
    whose subject is a hand-written declaration.
    """
    m = re.search(r"^def\s+%s\s*\(" % re.escape(name), text, re.M)
    if not m:
        return None
    lines = text[m.start():].split("\n")
    body = []
    for line in lines[1:]:
        if line and not line[0].isspace() and not line.startswith(")"):
            break
        body.append(line)
    return "\n".join(body)


def check(verbose):
    failures = []
    passed = 0

    def want(ok, detail):
        nonlocal passed
        if ok:
            passed += 1
            if verbose:
                print(f"  ok   {detail}")
        else:
            failures.append(detail)

    if not HOST_OWNED_BLOBS:
        failures.append("HOST_OWNED_BLOBS is empty: the convention is declared "
                        "nowhere, so nothing refuses a store into one")
        return passed, failures

    sources = {}
    for key, contract in sorted(HOST_OWNED_BLOBS.items()):
        module, _, name = key.rpartition(".")
        src = sources.get(module)
        if src is None:
            path = module_source(module)
            if path is None:
                failures.append(f"{key}: no host module source for `{module}` "
                                f"(looked for {module}.mojo and "
                                f"{module}/__init__.mojo under formal/hostmods)")
                continue
            src = sources[module] = read(path)
        body = def_body(src, name)
        want(body is not None,
             f"{key} is a function {module} declares ({'found' if body else 'MISSING'})")
        if body is None:
            continue

        count = contract.get("count_word", 0)
        base = contract.get("entry_base", 1)
        param = contract.get("param")
        returns = bool(contract.get("returns"))

        # The LAYOUT, read off the release the contract names. This is the claim
        # that decides whether a store is safe, so it is the claim checked
        # against the module rather than against the other entries.
        release = (contract.get("release") or "").rpartition(".")[2]
        rel_body = def_body(src, release) if release else None
        rel_param = re.search(r"^def\s+%s\s*\(\s*([A-Za-z_]\w*)" % re.escape(release),
                              src, re.M) if release else None
        if rel_body and rel_param:
            p = rel_param.group(1)
            frees_entries = re.search(r"free\(\s*%s\[\s*%d\s*\+" % (re.escape(p), base),
                                      rel_body) is not None
            bounded_by_count = re.search(r"<\s*%s\[\s*%d\s*\]" % (re.escape(p), count),
                                         rel_body) is not None
            want(frees_entries and bounded_by_count,
                 f"{key}: {release} frees {p}[{base} + i] under a loop bounded by "
                 f"{p}[{count}] "
                 f"(frees entries: {frees_entries}, bounded by the count: "
                 f"{bounded_by_count})")
        else:
            want(False, f"{key}: the release it names ({contract.get('release')!r}) "
                        f"is not a function of {module} this test can read")

        if returns:
            # A producer hands back an ALLOCATION, which is the whole difference
            # between a blob that outlives the call and a frame that does not.
            mallocs = re.search(r"\bmalloc\s*\(", body) is not None
            want(mallocs,
                 f"{key}: allocates the block it returns (malloc in its own body: "
                 f"{mallocs})")
        if isinstance(param, int):
            # `re.search`, not `re.match`: with MULTILINE `^` matches at every
            # line start, but `re.match` still only TRIES position 0 — so the
            # first version of this found no parameter list at all and reported
            # every annotated pointer as unannotated.
            params = re.search(r"^def\s+%s\s*\((.*?)\)" % re.escape(name), src,
                               re.M | re.S)
            args = [a.strip() for a in (params.group(1).split(",")
                                        if params else []) if a.strip()]
            ok = param < len(args)
            ann = args[param] if ok else ""
            pointer = ann.startswith("Pointer[") or "Pointer[" in ann
            want(ok and pointer,
                 f"{key}: parameter {param} of {name} is the blob and is "
                 f"annotated a pointer ({ann!r})")

        # `host_owned_blob` is the only accessor anything reads, so it is what
        # has to agree with the table: exact match, `{}` for anything else, and
        # a whole key rather than a prefix (a prefix match would claim
        # `os.listdir_len` for a caller who wrote `listdir`).
        want(host_owned_blob(key) == contract,
             f"{key}: host_owned_blob(key) is the entry itself")
        bare = name
        want(host_owned_blob(f"{module}.{bare}_nope") == {},
             f"{key}: host_owned_blob does not answer for {module}.{bare}_nope")

    return passed, failures


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    passed, failures = check(args.verbose)
    for detail in failures:
        print(f"  FAIL  {detail}")
    print(f"\nformal blob contract: PASS={passed} FAIL={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())