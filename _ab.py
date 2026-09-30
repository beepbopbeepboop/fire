import os, subprocess, sys
import test_ab_native as T
# Writes its transient sources into a private per-process dir under
# <repo>/.tmp/ rather than the repo root, for the reason documented in
# test_ab_native.py: a *_abt_*.mojo sitting in the repo root is enumerated as
# an item by a concurrent `bootstrap-stage*-dumps` fan-out, which then fails
# when this process deletes it (2026-09-29, integrator gate round 6). This
# script had the same shape, so it gets the same fix; the module-name tagging
# and the dead-pid sweep come from T rather than being reimplemented here.
root = os.getcwd(); only = sys.argv[1:]
ident = diff = crash = 0
for name, src in sorted(T.BUILTIN_TESTS.items()):
    if only and name not in only: continue
    f = T._scratch_source(name, src); ci = f[:-5] + ".ci"
    def dump(native, env):
        e = dict(os.environ); e.update(env)
        if os.path.exists(ci): os.remove(ci)
        subprocess.run((["./mojoc", "--dump", f] if native else ["python3", "fire.py", "--dump", f]), cwd=root, env=e, capture_output=True)
        return open(ci, "rb").read() if os.path.exists(ci) else None
    py = dump(False, {}); nc = dump(True, {"MOJO_HOME": root})
    if os.path.exists(ci): os.remove(ci)
    T._remove_if_present(f)
    if nc is None: crash += 1; print("CRASH", name)
    elif py == nc: ident += 1
    else: diff += 1; print("DIFF ", name, len(py) if py else 0, len(nc))
T.cleanup_scratch()
print(f"\n{ident} IDENTICAL, {diff} DIFF, {crash} CRASH")
