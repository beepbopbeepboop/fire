from wildcard_shadow_a import shadowed_fn


def relay_fn() -> Int:
    return shadowed_fn()
