"""Dump raw SolidWorks IComponent2.GetRemainingDOFs results.

Usage while SolidWorks has the target assembly active:

    .venv\\Scripts\\python.exe tools\\solidworks_dof_probe.py
    .venv\\Scripts\\python.exe tools\\solidworks_dof_probe.py --component Carriage
    .venv\\Scripts\\python.exe tools\\solidworks_dof_probe.py --out dof_probe.json

This is a diagnostic probe. It does not fix components, suppress mates, rebuild,
or save the SolidWorks document.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime


def _value(value):
    """Convert a COM MathPoint/MathVector or sequence to JSON-safe data."""
    if value is None:
        return None
    data = getattr(value, "ArrayData", None)
    if data is None:
        data = value
    try:
        return [float(x) for x in list(data)[:3]]
    except (TypeError, ValueError, AttributeError):
        return repr(value)


def _component_record(component):
    from sw2robot.exporter.model import _solver_dof_tuple, _solver_int
    from sw2robot.exporter.swcom import safe_call, safe_prop

    name = safe_prop(component, "Name2") or "<unnamed>"
    fixed = bool(safe_call(component, "IsFixed"))
    raw = _solver_dof_tuple(component)
    if raw is None:
        return {
            "name": name,
            "fixed": fixed,
            "error": "GetRemainingDOFs returned no typed 13-value tuple",
        }

    return {
        "name": name,
        "fixed": fixed,
        "return_value": _solver_int(raw[0]),
        "R1Status": _solver_int(raw[1]),
        "RPoint1": _value(raw[2]),
        "R1DirStatus": _solver_int(raw[3]),
        "RDir1": _value(raw[4]),
        "R2Status": _solver_int(raw[5]),
        "RPoint2": _value(raw[6]),
        "R2DirStatus": _solver_int(raw[7]),
        "RDir2": _value(raw[8]),
        "L1Status": _solver_int(raw[9]),
        "LDir1": _value(raw[10]),
        "L2Status": _solver_int(raw[11]),
        "LDir2": _value(raw[12]),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--component", help="case-insensitive substring filter")
    ap.add_argument("--out", help="write the JSON report to this path")
    args = ap.parse_args()

    try:
        from sw2robot.exporter.swcom import SolidWorks, as_iface, safe_call, safe_prop

        sw = SolidWorks(attach=True)
    except Exception as exc:
        print("Could not attach to a running SolidWorks instance.", file=sys.stderr)
        print(f"Reason: {exc!r}", file=sys.stderr)
        print("Use the VBA macro, or run the normal extractor against the .SLDASM path.",
              file=sys.stderr)
        return 2

    try:
        doc = safe_prop(sw.app, "ActiveDoc")
        if doc is None:
            print("SolidWorks is running, but there is no active document.", file=sys.stderr)
            return 2

        doc = as_iface(doc, "IModelDoc2")
        doc_type = safe_prop(doc, "GetType")
        raw_components = safe_call(doc, "GetComponents", True)
        if raw_components is None:
            assy = as_iface(doc, "IAssemblyDoc")
            raw_components = safe_call(assy, "GetComponents", True)
        components = [as_iface(c, "IComponent2") for c in list(raw_components or [])]
        components = [c for c in components if c is not None]

        records = []
        for component in components:
            name = safe_prop(component, "Name2") or ""
            if args.component and args.component.lower() not in name.lower():
                continue
            records.append(_component_record(component))

        report = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "active_document": safe_prop(doc, "GetPathName") or safe_prop(doc, "GetTitle"),
            "document_type": doc_type,
            "component_count": len(records),
            "components": records,
        }
        text = json.dumps(report, indent=2, ensure_ascii=True)
        print(text)
        if args.out:
            out = os.path.abspath(args.out)
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
            print(f"\nWrote {out}")
        return 0
    finally:
        sw.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
