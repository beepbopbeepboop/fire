import os, subprocess, sys
import test_ab_native as T
root = os.getcwd(); only = sys.argv[1:]
ident=diff=crash=0
for name, src in sorted(T.BUILTIN_TESTS.items()):
    if only and name not in only: continue
    f = os.path.join(root, "_abt_"+name+".mojo"); open(f,"w").write(src); ci = f[:-5]+".ci"
    def dump(native, env):
        e = dict(os.environ); e.update(env)
        if os.path.exists(ci): os.remove(ci)
        subprocess.run((["./mojoc","--dump",f] if native else ["python3","fire.py","--dump",f]), cwd=root, env=e, capture_output=True)
        return open(ci,"rb").read() if os.path.exists(ci) else None
    py = dump(False, {}); nc = dump(True, {"MOJO_HOME":root})
    if os.path.exists(ci): os.remove(ci)
    os.remove(f)
    if nc is None: crash+=1; print("CRASH",name)
    elif py==nc: ident+=1
    else: diff+=1; print("DIFF ",name,len(py) if py else 0,len(nc))
print(f"\n{ident} IDENTICAL, {diff} DIFF, {crash} CRASH")
