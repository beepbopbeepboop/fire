import os,subprocess,sys
import test_ab_shim as T
root=os.getcwd(); name=sys.argv[1]
f=os.path.join(root,"_abt_"+name+".mojo"); open(f,"w").write(T.BUILTIN_TESTS[name])
ci=f[:-5]+".ci"
for env in [{},{"MOJO_NO_SHIM":"1","MOJO_HOME":root}]:
    e=dict(os.environ);e.update(env)
    if os.path.exists(ci):os.remove(ci)
    subprocess.run((["./mojoc","--dump",f] if env else ["python3","mojo.py","--dump",f]),cwd=root,env=e,capture_output=True)
    open(f"_{name}.{'nc' if env else 'py'}","w").write(open(ci).read() if os.path.exists(ci) else "")
os.remove(f)
subprocess.run(["diff","-u",f"_{name}.py",f"_{name}.nc"])
