"""The console commands sw2robot tells users to run must actually be installed.

``export.py`` prints ``sw2urdf-extract <pkg_dir> --refresh frames --attach`` as
the fast way to re-read coordinate systems, but only ``sw2urdf``,
``sw2robot`` and ``sw2robot-web`` were declared, so that hint failed with
"program not found".
"""

import importlib
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
    "project"]["scripts"]


def test_every_declared_script_resolves_to_a_callable():
    for name, target in SCRIPTS.items():
        module, func = target.split(":")
        assert callable(getattr(importlib.import_module(module), func)), name


def test_commands_named_in_exporter_messages_are_declared():
    src = (REPO_ROOT / "sw2robot" / "exporter" / "export.py").read_text(encoding="utf-8")
    named = set(re.findall(r"\b(sw2urdf(?:-[a-z]+)+)\b", src))
    assert "sw2urdf-extract" in named
    assert named <= set(SCRIPTS), sorted(named - set(SCRIPTS))
