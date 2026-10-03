"""Serializable intermediate state (the cached SolidWorks extraction).

`extract` (slow, needs SolidWorks) writes a ``GraphState`` to ``graph.json``
plus the per-component meshes.  Everything after that -- choosing the base,
excluding parts, wiring joints, setting axes/limits/root frame, writing URDF --
operates on this JSON with NO SolidWorks, so iteration is instant.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel


class ComponentState(BaseModel):
    name: str                       # SolidWorks Name2 (e.g. "linkB-2")
    link_name: str                  # URDF-safe
    part_path: str | None = None
    is_subassembly: bool = False
    world: list[float]              # 16 floats, row-major 4x4 (local->world)
    fixed: bool = False
    # screw/bolt/nut/washer/pin -- standard hardware that should weld RIGIDLY to
    # whatever it fastens, never spin on its hole's concentric mate.  Set at
    # build time from the part's library folder + nomenclature (see
    # model.is_fastener_part); persisted so an extract can also pre-tag it.
    is_fastener: bool = False
    dof: int | None = None
    # Component-level snapshot from SolidWorks ``GetRemainingDOFs``.  This is
    # deliberately separate from MateEdge.solver_dof: the API reports motion
    # for a component in the solved assembly, not for one Mate.  Keeping the
    # snapshot lets the build associate a carriage/bearing motion with the
    # correct edge even when the Mate graph is dense or closed.
    solver_dof: dict | None = None
    mesh_file: str | None = None    # relative path, e.g. "meshes/x.3dxml"
    material: str | None = None     # SolidWorks material name (e.g. "ABS")
    density: float | None = None    # kg/m^3 from that material
    # SolidWorks-native mass properties of the PART, in its own (part-local)
    # frame and SI units -- the same frame the mesh is exported in.  Preferred
    # over the mesh-derived estimate at build time (exact CAD geometry +
    # material/override, not a tessellation).  None on older extracts.
    sw_mass: float | None = None              # kg
    sw_com: list[float] | None = None         # centre of mass [x,y,z] (m)
    sw_inertia: list[float] | None = None     # (ixx,ixy,ixz,iyy,iyz,izz) about COM
    # True when the user manually overrode mass properties in SolidWorks (the
    # "Override Mass Properties" dialog): sw_mass is then a deliberate value, not
    # the material/geometry default. False on older extracts.
    sw_mass_overridden: bool = False
    # basename(s) of the part file these mass properties were inherited from
    # because this component is a SolidWorks mirror copy whose per-body
    # materials / mass override did not come across (see exporter.mirror).
    # Provenance for the editor; None on older extracts and on every component
    # whose weight is its own.
    mass_inherited_from: str | None = None
    # per-link target mass (kg): the inertial is rescaled to this exact weight
    # (config `masses:` / the web editor). Mutually exclusive with a density
    # override. None on older extracts / when no target is set.
    mass_target: float | None = None
    # mass-only: keep the part's weight but drop its visual/collision geometry.
    # Valid only on a fixed child -- its inertial is lumped into the fixed parent
    # on export, so the parent's mass/inertia accounts for it without a mesh.
    mass_only: bool = False
    # the SolidWorks configuration this instance references.  Two instances of
    # the SAME part file can reference different configurations with different
    # geometry (length-configured tube), so mesh/mass exports key on
    # (part_path, configuration).  None on older extracts / single-config parts.
    configuration: str | None = None

    def world_matrix(self):
        return np.array(self.world, float).reshape(4, 4)


class MateGeo(BaseModel):
    """One mate occurrence with its full entity geometry (world coords).

    Parallel arrays, one slot per mate entity: ``etypes`` is the SolidWorks
    ``swMateEntityType_e`` (0 point, 1 line, 2 circle, 3 plane, 4 cylinder,
    5 sphere, 7 cone); ``dirs`` is the axis (line/cylinder) or normal (plane),
    zero when meaningless.  GetMates returns each mate once per component, so
    the same physical mate appears ~twice -- consumers dedup geometrically."""
    type: str                       # e.g. "CONCENTRIC"
    etypes: list[int | None] = []
    points: list[list[float]] = []  # world [x,y,z] per entity
    dirs: list[list[float]] = []    # world unit [x,y,z] per entity
    radii: list[float | None] = []
    # full Name2 of each entity's owning component (e.g. "body-1/armA-1");
    # lets a build-time sub-assembly expansion re-attach the mate to the
    # correct CHILD instead of the collapsed instance
    owners: list[str] = []


class SolverAxisState(BaseModel):
    """One axis reported by SolidWorks ``GetRemainingDOFs``.

    SolidWorks returns two possible rotational and two possible linear
    freedoms.  The API is undocumented, so both status fields are persisted
    together with the geometry instead of throwing them away after parsing.
    Points/directions use the assembly/document frame in which the query ran.
    """
    status: int | None = None
    direction_status: int | None = None
    point: list[float] | None = None
    direction: list[float] | None = None


class SolverDOFState(BaseModel):
    """Cached result of a Windows SolidWorks solver query for one edge."""
    remaining_dofs: int | None = None
    rotations: list[SolverAxisState] = []
    translations: list[SolverAxisState] = []
    queried_parent: str | None = None
    queried_child: str | None = None
    # ``GetRemainingDOFs`` returns code 2 for a component that SolidWorks has
    # fixed.  Keep the component flag beside the raw code: a non-fixed,
    # transiently unsolved component can also produce code 2, so the code is
    # not sufficient by itself to classify an edge as fixed.
    child_fixed: bool | None = None
    # assembled child origin, used as the joint point for a pure translation
    # (the SolidWorks API returns a direction but no point for L1/L2)
    child_origin: list[float] | None = None
    # Whether this edge belonged to the provisional parent tree used while the
    # SolidWorks query was made.  A valid zero-DOF result is authoritative for
    # a tree edge (it must be fixed); for a non-tree/closed-loop edge we retain
    # the geometric fallback so an intended hinge can still be represented as
    # a loop closure.  None keeps compatibility with older graph.json files.
    tree_edge: bool | None = None
    valid: bool = False
    note: str | None = None


class MateEdge(BaseModel):
    a: str                          # component Name2
    b: str
    types: list[str]                # e.g. ["CONCENTRIC", "COINCIDENT"]
    axis_point: list[float] | None = None   # world, on the concentric axis
    axis_dir: list[float] | None = None      # world, unit
    # full per-mate geometry (newer extracts; None on graphs from older ones)
    mates: list[MateGeo] | None = None
    # DOF-folder mode: this edge is NOT a 'dof' joint -> weld it fixed at build
    force_fixed: bool = False
    # SolidWorks' own solved DOF result, captured during Windows extraction.
    # None is expected on older graph.json files and on edges for which the
    # undocumented API could not be queried; those use the existing geometry
    # classifier instead.
    solver_dof: SolverDOFState | None = None
    # A LimitDistance/LimitAngle found in a sub-assembly document.  Top-level
    # limit mates are kept in GraphState.limit_joints for compatibility, but
    # internal mates must travel with the edge so expansion can carry them into
    # the parent graph.  The value is a JSON-safe mapping with
    # ``type/ref/axis_point/axis_dir/lower/upper``.
    limit_joint: dict | None = None


class LimitJoint(BaseModel):
    """A SolidWorks LimitDistance/LimitAngle mate = a real slider/hinge.

    These carry the assembly's actual DOFs (the geometric classifier only sees a
    plain DISTANCE/ANGLE constraint and over-fixes them), so the build uses them
    to override the joint type/axis/limits on the ``a``--``b`` edge.  ``lower``/
    ``upper`` are travel relative to the assembled pose (m or rad)."""
    a: str                          # top-level component Name2
    b: str
    type: str                       # "prismatic" | "revolute"
    axis_point: list[float]
    axis_dir: list[float]
    lower: float
    upper: float


class CoordinateSystemState(BaseModel):
    """A named SolidWorks coordinate system in its document frame.

    ``document_from_frame`` is a row-major 4x4 matrix that maps coordinates
    from this named frame into the owning ``.SLDASM`` document frame.  Using
    one direction everywhere makes an instance frame simply
    ``instance.world @ document_from_frame``.
    """
    name: str
    document_from_frame: list[float]
    # For a frame authored in an ASSEMBLY document: the Name2 of the component
    # whose geometry its origin selection belongs to (IEntity.GetComponent), so
    # a frame drawn on a part's vertex hangs off THAT part's link instead of the
    # root.  None when the frame references the assembly's own origin/planes,
    # when the document is a part (the part IS the owner), or on older extracts.
    owner_component: str | None = None

    def document_from_frame_matrix(self):
        return np.array(self.document_from_frame, float).reshape(4, 4)


class ReferenceAxisState(BaseModel):
    """A named SolidWorks reference axis in its document frame.

    SolidWorks exposes a reference axis as two points.  ``document_point`` is
    one point on that line and ``document_direction`` follows the direction
    convention used by the official SolidWorks URDF Exporter.  The collapsed
    exporter currently consumes only the direction, but retaining the point
    keeps the extracted CAD geometry complete for future diagnostics.
    """
    name: str
    document_point: list[float]
    document_direction: list[float]


class SubGraph(BaseModel):
    """Internal structure of ONE sub-assembly part file, in ITS OWN frame.

    Stored once per unique .SLDASM path; every instance of that sub-assembly
    reuses it (compose with the instance transform).  Lets the build phase
    expand sub-assemblies whose internals actually move."""
    components: list[ComponentState] = []
    edges: list[MateEdge] = []
    ground: list[str] = []
    coordinate_systems: list[CoordinateSystemState] = []


class GraphState(BaseModel):
    """The raw CAD graph extracted from the assembly (UI/build independent)."""
    robot_name: str
    source_assembly: str
    components: list[ComponentState] = []
    edges: list[MateEdge] = []
    ground: list[str] = []          # components mated to the assembly itself
    assembly_mesh: str | None = None
    # Named coordinate systems authored directly in the top-level assembly.
    # Their transforms are expressed in that assembly document's frame.
    coordinate_systems: list[CoordinateSystemState] = []
    # Named coordinate systems authored inside PART documents, keyed by part
    # path.  A frame drawn in a .SLDPRT belongs to that part unambiguously, so
    # every instance of the part carries it (transform composed with the
    # instance world).  Empty on graphs from older extracts.
    part_coordinate_systems: dict[str, list[CoordinateSystemState]] = {}
    # Named reference axes authored directly in the top-level assembly.  These
    # correspond to the official SolidWorks URDF Exporter's Reference Joint
    # choices and are intentionally separate from mate-derived joint axes.
    reference_axes: list[ReferenceAxisState] = []
    # Definitive SW2URDF fingerprint: top-level feature name
    # "URDF Export Configuration (vX.Y)". None on older extracts / assemblies
    # not authored with the add-in.
    sw2urdf_marker: str | None = None
    # Raw SW2URDF DataContract XML payload from the marker attribute's
    # "data" parameter. None when unreadable or absent.
    sw2urdf_config_xml: str | None = None
    # part_path -> internals (newer extracts; empty on graphs from older ones)
    subassemblies: dict[str, SubGraph] = {}
    # full nested Name2 ("inst-1/child-2/...") -> row-major 4x4 in the ROOT
    # frame, for EVERY component at every depth.  Flexible sub-assembly
    # instances pose their internals differently per instance; expansion
    # prefers these actual worlds over (instance transform x local layout).
    deep_worlds: dict[str, list[float]] = {}
    # full nested Name2 of components that are HIDDEN in the assembly --
    # SolidWorks renders (and exports) without them, so the build drops them
    hidden: list[str] = []
    # LimitDistance/LimitAngle mates = the assembly's real sliders/hinges; the
    # build promotes these edges to prismatic/revolute (empty on older extracts)
    limit_joints: list[LimitJoint] = []
    # Which CONFIGURATION of the top-level assembly this graph was read from,
    # and every configuration the file offers.  A configuration suppresses
    # components and swaps part variants, so two graphs of one .SLDASM can
    # legitimately differ; recording the choice makes a package say which
    # variant it is, and lets the editor offer the others without SolidWorks.
    # Both empty/None on older extracts.
    configuration: str | None = None
    configurations: list[str] = []

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            return cls.model_validate_json(f.read())
