NAMES: list = []

def fill(v):
    global NAMES
    NAMES = [str(x) for x in v]

def touch():
    import cyc_b
    return cyc_b.show()
