"""The window must not replace tkinter's own methods. That crashes on startup."""

import ast
import re
import sys
from pathlib import Path


def _app_methods() -> set[str]:
    tree = ast.parse(Path("music_id_tagger/gui.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "App":
            return {item.name for item in node.body if isinstance(item, ast.FunctionDef)}
    raise AssertionError("nincs App")


def _misc_methods() -> set[str]:
    root = Path(sys.base_prefix)
    found = list(root.glob("lib/python*/tkinter/__init__.py")) + list(root.glob("**/tkinter/__init__.py"))
    if not found:
        found = list(Path("/usr").glob("lib/python*/tkinter/__init__.py"))
    assert found, "nincs tkinter forrás"
    text = found[0].read_text(encoding="utf-8")
    match = re.search(r"\nclass Misc:\n(?P<body>.*?)(?:\nclass |\Z)", text, re.S)
    assert match
    names = set(re.findall(r"^\s{4}def ([A-Za-z_][A-Za-z0-9_]*)\(", match.group("body"), re.M))
    names.discard("__init__")
    assert "_options" in names
    return names


def test_app_does_not_override_tkinter_internals():
    methods = _app_methods()
    overlap = methods & _misc_methods()
    assert not overlap
    assert "_options" not in methods
    assert "_search_options" in methods
