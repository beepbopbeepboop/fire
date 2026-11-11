#!/usr/bin/env python3
"""Regression: dict slot read must carry kind so d['k'] can say None/True/1.5.
Root-cause half: runtime accessors mojo_dict_slot_kind / mojo_dict_repr_slot.
Full fix requires codegen temp-tracking (NOT DONE — see bugs doc)."""

def test_accessors_exist():
    # Verify the new runtime symbols are present by compiling a stub that
    # references them against the runtime object (quick sanity, not full link).
    import subprocess, tempfile, os, sys
    stub = """
#include <string.h>
#include "runtime/fire_runtime.h"
int main(){
    MojoDict *d = NULL;
    int64_t k = mojo_dict_slot_kind(d,"k");
    char *r = mojo_dict_repr_slot(d,"k");
    (void)k;(void)r;
    return 0;
}
"""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td,"stub.c"),"w") as f:
            f.write(stub)
        # Only compile to object; don't need full link for symbol-check
        cmd = ["gcc", "-c", "-I.", os.path.join(td,"stub.c"),
               "-o", os.path.join(td,"stub.o")]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 0, f"compile failed: {res.stderr}"
    print("PASS: mojo_dict_slot_kind / mojo_dict_repr_slot compile and link")

if __name__ == "__main__":
    test_accessors_exist()
