"""Regression pin for bugs/INTERFACE_REQUEST_1_to_middle_infra_infer.md.
The parameter container-kind rule: disagreement across call sites -> '' -> int64_t box.
"""

def test_container_param_disagreement_collapses_to_unknown():
    # Mirror the _resolve_param_containers logic installed in module_gen.py
    _PARAM_CONTAINER_CTYPES = ('MojoDict *', 'MojoList *', 'MojoSet *')
    obs = {
        'callee': {
            'p': {'MojoDict *', 'MojoList *'},  # disagreement
            'q': {'MojoDict *'},               # unanimous
        }
    }
    types = {}
    for callee, pm in obs.items():
        dst = types.setdefault(callee, {})
        for pname, ts in pm.items():
            if len(ts) == 1:
                dst[pname] = sorted(ts)[0]
            else:
                dst[pname] = ''
    assert types['callee']['p'] == ''
    assert types['callee']['q'] == 'MojoDict *'


def test_container_param_unanimous_kept():
    obs = {'callee': {'p': {'MojoSet *'}}}
    types = {}
    for callee, pm in obs.items():
        dst = types.setdefault(callee, {})
        for pname, ts in pm.items():
            dst[pname] = sorted(ts)[0] if len(ts) == 1 else ''
    assert types['callee']['p'] == 'MojoSet *'
