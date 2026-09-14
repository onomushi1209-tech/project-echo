"""Executable dependency contracts; scan imports without importing sources."""

import ast
from importlib.util import resolve_name
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "echo"


def _import_targets(node, package):
    if isinstance(node, ast.Import):
        return [name.name for name in node.names]
    if isinstance(node, ast.ImportFrom):
        base = resolve_name("." * node.level + (node.module or ""), package) if node.level else (node.module or "")
        return [base] + [base + "." + name.name for name in node.names]
    return []


def test_stage_modules_respect_dependency_boundaries():
    for package in ("core", "trend", "research", "scoring", "content", "compliance", "review", "brains"):
        forbidden = ("echo.verticals",)
        if package == "research":
            forbidden += ("echo.source",)
        for path in (ROOT / package).rglob("*.py"):
            path_forbidden = forbidden + (("echo.source",) if path.name == "real_research_brain.py" else ())
            import_package = "echo." + ".".join(path.parent.relative_to(ROOT).parts)
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                for name in _import_targets(node, import_package):
                    assert not any(name == prefix or name.startswith(prefix + ".") for prefix in path_forbidden), (path, node.lineno, name)


def test_boundary_scan_resolves_relative_and_package_imports():
    for statement in ("from ..source import reliability", "from .. import source", "from echo import source"):
        node = ast.parse(statement).body[0]
        assert any(name == "echo.source" or name.startswith("echo.source.")
                   for name in _import_targets(node, "echo.research"))


def test_source_reliability_public_api_delegates_to_shared_primitive():
    from echo.core.reliability import TIER_SCORES, reliability_score
    from echo.source.reliability import TIER_SCORES as old_scores, reliability_score as old_score
    from echo.models.enums import ReliabilityTier
    assert old_score is reliability_score
    assert old_scores is TIER_SCORES
    assert [old_score(tier) for tier in ReliabilityTier] == [1.0, 0.7, 0.4]
