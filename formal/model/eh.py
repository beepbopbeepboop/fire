from . import *
from dataclasses import dataclass


# EH runtime data structures (pure data, consumed by a later step).
# `as e` refused in the first slice.


@dataclass(frozen=True)
class PersonalityArm:
    arm_index: int
    catch_names: tuple
    class_ids: tuple
    binds: str | None


@dataclass(frozen=True)
class LandingPad:
    region_id: int
    line: int
    arms: tuple
    has_finally: bool


@dataclass(frozen=True)
class LandingPadTable:
    function: str
    pads: tuple

    def arm_for(self, region_id, class_id):
        for pad in self.pads:
            if getattr(pad, "region_id", None) == region_id:
                for idx, arm in enumerate(getattr(pad, "arms", ())):
                    cids = getattr(arm, "class_ids", ()) or ()
                    if class_id in cids:
                        return idx
                return None
        return None


def build_landing_pads(fn, structs=None):
    """Build landing pad table for a function. One pad per try with handlers
    (a try with no handlers has no pad: it is a cleanup scope)."""
    from formal import model as M
    import fire_compiler as F

    pads = []
    region_id = 0
    # Walk all TryStmt nodes
    try:
        nodes = list(iter_nodes(getattr(fn, "body", None) or []))
    except Exception:
        nodes = []
    for node in nodes:
        if isinstance(node, F.TryStmt):
            handlers = getattr(node, "handlers", None) or []
            if not handlers:
                continue  # cleanup scope, no pad
            arms = []
            for arm_idx, h in enumerate(handlers):
                # Check for 'as e' binding
                binds = getattr(h, "name", None)
                if binds is not None:
                    raise ValueError(f"except arm {arm_idx} has 'as e' binding ({binds}) not supported")
                exc_type = getattr(h, "exc_type", None)
                # exc_type might be a string name or None for bare except
                if exc_type is None or (isinstance(exc_type, str) and exc_type == ""):
                    catch_names = ("*",)
                elif isinstance(exc_type, str):
                    catch_names = (exc_type,)
                else:
                    # Try to get name
                    catch_names = (getattr(exc_type, "name", None) or str(exc_type),)
                # Get class ids for this arm
                class_ids_list = []
                # Try to use exception_kind_table or exception_kinds
                try:
                    kinds = M.exception_kind_table(structs) if structs is not None else M.exception_kind_table()
                except Exception:
                    try:
                        kinds = M.exception_kinds()
                    except Exception:
                        kinds = {}
                # For each catch name, find which classes it matches
                for cname in catch_names:
                    if cname == "*":
                        # bare except matches everything in kinds
                        for kname, kid in kinds.items():
                            class_ids_list.append(kid)
                        continue
                    # Check handler_arm_matches for all possible flying classes
                    # and also get descendants via handler_arm_kinds
                    try:
                        hks = M.handler_arm_kinds(cname, kinds, structs)
                    except Exception:
                        hks = None
                    if hks is not None:
                        for kid in hks:
                            class_ids_list.append(kid)
                    else:
                        # Try to resolve
                        # Check if this is undecidable
                        try:
                            # Try matching against each known class
                            matched_any = False
                            for fkname in kinds:
                                try:
                                    res = M.handler_arm_matches(cname, fkname, kinds, structs)
                                    if res is True:
                                        class_ids_list.append(kinds[fkname])
                                        matched_any = True
                                    elif res is None:
                                        raise ValueError(f"arm {cname} is undecidable for image")
                                except ValueError:
                                    raise
                                except Exception:
                                    pass
                            if not matched_any and cname in kinds:
                                class_ids_list.append(kinds[cname])
                        except ValueError:
                            raise
                        except Exception:
                            pass
                # Remove duplicates while preserving order
                seen_c = set()
                class_ids_tuple = []
                for cid in class_ids_list:
                    if cid not in seen_c:
                        class_ids_tuple.append(cid)
                        seen_c.add(cid)
                arms.append(PersonalityArm(arm_idx, tuple(catch_names), tuple(class_ids_tuple), binds))
            line_no = getattr(node, "line", 0) or 0
            has_finally = bool(getattr(node, "finally_body", None))
            pads.append(LandingPad(region_id, line_no, tuple(arms), has_finally))
            region_id += 1
    return LandingPadTable(getattr(fn, "name", "<anon>"), tuple(pads))
