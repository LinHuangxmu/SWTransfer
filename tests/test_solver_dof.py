"""SolidWorks solver-DOF parsing and precedence tests.

The COM call itself is Windows/SolidWorks-only, so these tests exercise the
JSON-safe adapter and the build-time classifier with representative tuples.
The real CAD regression still needs a SolidWorks fixture.
"""

import numpy as np

from sw2robot.exporter.model import (
    Component,
    _native_motion_groups,
    _normalize_expanded_carriage_motion,
    _normalize_expanded_rail_carriage_parent_map,
    _auto_parallel_carriage_mimic,
    _rename_solver_query,
    _solver_joint,
    _solver_active_axes,
    _solver_state_from_tuple,
    _attach_component_solver_evidence,
    _transform_rec,
    _auto_parent_map,
    classify_edge_auto,
)
from sw2robot.exporter.state import MateEdge, SolverDOFState


def _raw(*, rotation=False, translation=False, remaining=0):
    return [
        remaining,
        1 if rotation else 0,
        [1.0, 2.0, 3.0] if rotation else None,
        1 if rotation else 0,
        [0.0, 0.0, 1.0] if rotation else None,
        0, None, 0, None,
        1 if translation else 0,
        [1.0, 0.0, 0.0] if translation else None,
        0, None,
    ]


def test_solver_rotation_beats_geometry_classifier():
    state = _solver_state_from_tuple(
        _raw(rotation=True), parent_name="frame", child_name="arm",
        child_origin=[10.0, 20.0, 30.0])
    rec = {
        "types": ["CONCENTRIC", "CONCENTRIC"],
        "axis": (np.zeros(3), np.array([1.0, 0.0, 0.0])),
        "mates": [], "solver_dof": state,
    }
    jt, axis, note = classify_edge_auto(rec)
    assert jt == "revolute"
    assert np.allclose(axis[0], [1.0, 2.0, 3.0])
    assert np.allclose(axis[1], [0.0, 0.0, 1.0])
    assert "solidworks solver" in note


def test_solver_translation_uses_child_origin_for_joint_point():
    state = _solver_state_from_tuple(
        _raw(translation=True), parent_name="frame", child_name="carriage",
        child_origin=[0.0, 0.0, 0.25])
    jt, axis, note = _solver_joint({"solver_dof": state, "mates": []})
    assert jt == "prismatic"
    assert np.allclose(axis[0], [0.0, 0.0, 0.25])
    assert np.allclose(axis[1], [1.0, 0.0, 0.0])


def test_solver_fully_constrained_falls_back_for_closed_loop():
    state = _solver_state_from_tuple(_raw(), child_origin=[0, 0, 0])
    # A zero-DOF component can be globally constrained by another branch of a
    # closed loop.  It must therefore not be promoted to a fixed joint before
    # the existing mate-geometry classifier gets a chance to recover the
    # intended hinge.
    rec = {
        "types": ["CONCENTRIC"],
        "axis": (np.zeros(3), np.array([0.0, 0.0, 1.0])),
        "mates": [],
        "solver_dof": state,
    }
    assert _solver_joint(rec) is None
    jt, axis, note = classify_edge_auto(rec)
    assert jt == "revolute"
    assert np.allclose(axis[1], [0.0, 0.0, 1.0])
    assert "solidworks solver" not in (note or "")


def test_solver_zero_dof_tree_edge_is_fixed():
    state = _solver_state_from_tuple(_raw(), child_origin=[0, 0, 0])
    state["tree_edge"] = True
    rec = {
        "types": ["CONCENTRIC"],
        "axis": (np.zeros(3), np.array([0.0, 0.0, 1.0])),
        "mates": [],
        "solver_dof": state,
    }
    jt, axis, note = classify_edge_auto(rec)
    assert jt == "fixed"
    assert axis is None
    assert "no remaining DOF" in note


def test_nonclassic_remaining_count_falls_back():
    state = _solver_state_from_tuple(
        _raw(rotation=True, remaining=1), child_origin=[0, 0, 0])
    rec = {
        "types": ["CONCENTRIC"],
        "axis": (np.zeros(3), np.array([0.0, 0.0, 1.0])),
        "mates": [], "solver_dof": state,
    }
    assert _solver_joint(rec) is None
    assert classify_edge_auto(rec)[0] == "revolute"


def test_solver_state_survives_mate_edge_serialization():
    payload = _solver_state_from_tuple(_raw(rotation=True),
                                      child_origin=[1, 2, 3])
    payload["tree_edge"] = True
    state = SolverDOFState(**payload)
    edge = MateEdge(a="a", b="b", types=[], solver_dof=state)
    dumped = edge.model_dump()
    assert dumped["solver_dof"]["rotations"][0]["status"] == 1
    assert dumped["solver_dof"]["child_origin"] == [1.0, 2.0, 3.0]
    assert dumped["solver_dof"]["tree_edge"] is True


def test_solver_geometry_transforms_with_expanded_subassembly():
    state = _solver_state_from_tuple(
        _raw(rotation=True), child_origin=[1.0, 0.0, 0.0])
    T = np.eye(4)
    T[:3, 3] = [10.0, 0.0, 0.0]
    out = _transform_rec({"types": [], "axis": None, "mates": [],
                          "solver_dof": state}, T)
    assert np.allclose(out["solver_dof"]["child_origin"], [11, 0, 0])
    assert np.allclose(out["solver_dof"]["rotations"][0]["point"],
                       [11, 2, 3])


def test_component_dof_return_code_is_not_a_dof_count():
    """The first COM result is a status/result code, not a DOF count."""
    from sw2robot.exporter.model import _solver_dof_tuple

    class FixedComponent:
        def IsFixed(self):
            return True

        def GetRemainingDOFs(self):
            # SolidWorks 2025 observed result for a fixed component.
            return (2, 0, None, 0, None, 0, None, 0, None,
                    0, None, 0, None)

    raw = _solver_dof_tuple(FixedComponent())
    assert raw[0] == 2
    assert all(raw[i] == 0 for i in (1, 3, 5, 7, 9, 11))


def test_solver_status_two_is_not_an_active_freedom():
    # SolidWorks uses status 1 for the usable axis slots; status 2 is observed
    # on constrained/unsupported slots and must not create a robot joint.
    state = _solver_state_from_tuple(
        _raw(translation=False, remaining=0), child_origin=[0, 0, 0])
    state["translations"][0]["status"] = 2
    rec = {"solver_dof": state, "mates": [], "types": []}
    assert _solver_joint(rec) is None


def test_native_motion_group_merges_rigidly_tied_carriage_pieces():
    a = _solver_state_from_tuple(
        _raw(translation=True), parent_name="rail", child_name="carriage_a")
    a["tree_edge"] = True
    b = _solver_state_from_tuple(
        _raw(translation=True), parent_name="rail", child_name="carriage_b")
    b["tree_edge"] = True
    tie = _solver_state_from_tuple(
        _raw(), parent_name="carriage_a", child_name="carriage_b")
    tie["tree_edge"] = False
    adjacency = {
        frozenset(("rail", "carriage_a")): {"solver_dof": a},
        frozenset(("rail", "carriage_b")): {"solver_dof": b},
        frozenset(("carriage_a", "carriage_b")): {"solver_dof": tie},
    }
    component_to_group, groups, ties, loops = _native_motion_groups(adjacency)
    assert component_to_group["carriage_a"] == component_to_group["carriage_b"]
    assert sorted(next(g for g in groups.values() if "carriage_a" in g)) == [
        "carriage_a", "carriage_b"]
    assert frozenset(("carriage_a", "carriage_b")) in ties
    assert not loops


def test_native_motion_group_does_not_merge_different_axes():
    a = _solver_state_from_tuple(
        _raw(translation=True), parent_name="rail", child_name="a")
    a["tree_edge"] = True
    b = _solver_state_from_tuple(
        _raw(translation=True), parent_name="rail", child_name="b")
    b["translations"][0]["direction"] = [0.0, 1.0, 0.0]
    b["tree_edge"] = True
    tie = _solver_state_from_tuple(_raw(), parent_name="a", child_name="b")
    tie["tree_edge"] = False
    adjacency = {
        frozenset(("rail", "a")): {"solver_dof": a},
        frozenset(("rail", "b")): {"solver_dof": b},
        frozenset(("a", "b")): {"solver_dof": tie},
    }
    component_to_group, _groups, ties, _loops = _native_motion_groups(adjacency)
    assert component_to_group["a"] != component_to_group["b"]
    assert not ties


def test_component_snapshot_attaches_to_matching_axis_edges():
    rail = Component("rail", "rail", "rail.SLDPRT", False,
                     np.eye(4), True, 0)
    carriage = Component("carriage", "carriage", "carriage.SLDPRT", False,
                         np.eye(4), False, 1)
    carriage.solver_dof = _solver_state_from_tuple(
        _raw(translation=True), child_name="carriage",
        child_origin=[0, 0, 0])
    adjacency = {
        frozenset(("rail", "carriage")): {
            "types": ["CONCENTRIC"],
            "axis": (np.zeros(3), np.array([1., 0., 0.])),
            "mates": [],
        }
    }
    n = _attach_component_solver_evidence(
        [rail, carriage], adjacency,
        {frozenset(("rail", "carriage"))})
    assert n == 1
    state = adjacency[next(iter(adjacency))]["solver_dof"]
    assert state["queried_child"] == "carriage"
    assert state["tree_edge"] is True
    assert _solver_active_axes(state)[0]["type"] == "prismatic"


def test_expanded_solver_query_names_follow_instance_prefix():
    state = _solver_state_from_tuple(
        _raw(translation=True), parent_name="rail", child_name="carriage")
    out = _rename_solver_query(
        state, {"rail": "module/rail", "carriage": "module/carriage"})
    assert out["queried_parent"] == "module/rail"
    assert out["queried_child"] == "module/carriage"


def test_native_tied_carriages_emit_one_prismatic_joint():
    def state(translation, child, tree):
        out = _solver_state_from_tuple(
            _raw(translation=translation), child_name=child)
        out["tree_edge"] = tree
        return out

    comps = [Component(n, n, None, False, np.eye(4), False, None)
             for n in ("base", "rail", "carriage_a", "carriage_b")]
    adjacency = {
        frozenset(("base", "rail")): {
            "types": [], "axis": None, "mates": [],
            "solver_dof": state(False, "rail", True)},
        frozenset(("rail", "carriage_a")): {
            "types": [], "axis": None, "mates": [],
            "solver_dof": state(True, "carriage_a", True)},
        frozenset(("rail", "carriage_b")): {
            "types": [], "axis": None, "mates": [],
            "solver_dof": state(True, "carriage_b", True)},
        frozenset(("carriage_a", "carriage_b")): {
            "types": [], "axis": None, "mates": [],
            "solver_dof": state(False, "carriage_b", False)},
    }
    parent, info = _auto_parent_map(comps, adjacency, comps[0])
    movable = [key for key, rec in info.items()
               if rec["type"] == "prismatic"]
    assert len(movable) == 1
    assert parent["carriage_a"] == "rail"
    assert parent["carriage_b"] == "carriage_a"
    assert info[("carriage_b", "carriage_a")]["type"] == "fixed"


def test_native_dof_beats_limit_mate_nominal_type():
    state = _solver_state_from_tuple(
        _raw(translation=True), parent_name="rail", child_name="slide")
    rec = {
        "solver_dof": state,
        "limit_joint": {
            "type": "revolute",
            "axis": (np.zeros(3), np.array([0.0, 0.0, 1.0])),
            "lower": -1.0,
            "upper": 1.0,
        },
        "mates": [], "types": [],
    }
    jt, _axis, note = classify_edge_auto(rec)
    assert jt == "prismatic"
    assert "solidworks solver" in note


def test_limit_mate_is_fallback_when_native_solver_is_absent():
    rec = {
        "limit_joint": {
            "type": "prismatic",
            "axis": (np.zeros(3), np.array([0.0, 0.0, 1.0])),
            "lower": -1.0,
            "upper": 1.0,
        },
        "mates": [], "types": [],
    }
    jt, _axis, note = classify_edge_auto(rec)
    assert jt == "prismatic"
    assert "fallback" in note


def test_expanded_linker_motion_moves_to_real_carriage_edge():
    external = _solver_state_from_tuple(
        _raw(translation=True), parent_name="module/x__Carriage_1-1",
        child_name="xz_Linker-1", child_origin=[1, 2, 3])
    internal = _solver_state_from_tuple(
        _raw(), parent_name="module/x__Linear_Rail-1",
        child_name="module/x__Carriage_0-1", child_origin=[1, 2, 3])
    adjacency = {
        frozenset(("module/x__Carriage_1-1", "xz_Linker-1")):
            {"types": [], "mates": [], "solver_dof": external},
        frozenset(("module/x__Linear_Rail-1", "module/x__Carriage_0-1")):
            {"types": [], "mates": [], "solver_dof": internal},
    }
    assert _normalize_expanded_carriage_motion([], adjacency) == 1
    assert len(_solver_active_axes(
        adjacency[frozenset(("module/x__Linear_Rail-1",
                             "module/x__Carriage_0-1"))]["solver_dof"])) == 1
    assert not _solver_active_axes(
        adjacency[frozenset(("module/x__Carriage_1-1", "xz_Linker-1"))]
        ["solver_dof"])
    assert classify_edge_auto(
        adjacency[frozenset(("module/x__Linear_Rail-1",
                             "module/x__Carriage_0-1"))])[0] == "prismatic"
    assert classify_edge_auto(
        adjacency[frozenset(("module/x__Carriage_1-1", "xz_Linker-1"))]
    )[0] == "fixed"


def test_parallel_native_carriages_get_one_to_one_mimic():
    part_carriage = "axis/y__Carriage_0.SLDPRT"
    part_rail = "axis/y__Linear_Rail.SLDPRT"
    names = (
        "module1/y__Linear_Rail-1", "module1/y__Carriage_0-1",
        "module2/y__Linear_Rail-1", "module2/y__Carriage_0-1")
    comps = [Component(names[0], names[0], part_rail, False, np.eye(4),
                       False, None),
             Component(names[1], names[1], part_carriage, False, np.eye(4),
                       False, None),
             Component(names[2], names[2], part_rail, False, np.eye(4),
                       False, None),
             Component(names[3], names[3], part_carriage, False, np.eye(4),
                       False, None)]
    parent_of = {names[1]: names[0], names[3]: names[2]}
    edge_info = {
        (names[1], names[0]): {
            "type": "prismatic", "axis": (np.zeros(3),
                                               np.array([0., 1., 0.])),
            "lower": -0.05, "upper": 0.05, "note": "native"},
        (names[3], names[2]): {
            "type": "prismatic", "axis": (np.zeros(3),
                                               np.array([0., 1., 0.])),
            "lower": -0.05, "upper": 0.05, "note": "native"},
    }
    _auto_parallel_carriage_mimic(comps, parent_of, edge_info)
    assert edge_info[(names[3], names[2])]["mimic"] == {
        "joint": f"{names[0]}__{names[1]}",
        "multiplier": 1.0,
        "offset": 0.0,
    }


def test_linear_guide_parent_direction_is_rail_to_carriage():
    rail = "module/y__Linear_Rail-1"
    carriage = "module/y__Carriage_0-1"
    carriage_1 = "module/y__Carriage_1-1"
    base = "module/y__Base_Profile-1"
    comps = [Component(name, name, None, False, np.eye(4), False, None)
             for name in (base, carriage, rail, carriage_1)]
    # This is the erroneous orientation observed in LiquidHandler: the BFS
    # selected carriage as the parent of the rail, with a downstream carriage
    # stage already attached below it.
    parent_of = {carriage: base, rail: carriage, carriage_1: carriage}
    assert _normalize_expanded_rail_carriage_parent_map(comps, parent_of) == 1
    assert parent_of[rail] == base
    assert parent_of[carriage] == rail
    assert parent_of[carriage_1] == carriage


def test_fixed_y_base_is_grounded_when_support_links_are_children():
    root = "assembly/base"
    ybase = "assembly/y_Axis_Module-1/y__Base_Profile-1"
    rail = "assembly/y_Axis_Module-1/y__Linear_Rail-1"
    c0 = "assembly/y_Axis_Module-1/y__Carriage_0-1"
    c1 = "assembly/y_Axis_Module-1/y__Carriage_1-1"
    linker = "assembly/xy_Linker-1"
    support = "assembly/Axis_Struct_Link_1"
    xbase = "assembly/x_Axis_Module-1/x__Base_Profile-1"
    names = (root, ybase, rail, c0, c1, linker, support, xbase)
    comps = [Component(name, name, None, False, np.eye(4), False, None)
             for name in names]
    parent_of = {
        ybase: xbase,
        rail: ybase,
        c0: rail,
        c1: c0,
        linker: c1,
        support: ybase,
        xbase: root,
    }
    _normalize_expanded_rail_carriage_parent_map(
        comps, parent_of, root=comps[0])
    assert parent_of[ybase] == root
    assert parent_of[rail] == ybase
    assert parent_of[c0] == rail
    assert parent_of[c1] == c0
    assert parent_of[linker] == c1
