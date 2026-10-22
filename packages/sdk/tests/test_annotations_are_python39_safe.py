"""A module that writes ``X | None`` in an annotation must defer evaluating annotations (#1484).

``requires-python`` is ``>=3.9``. PEP 604 unions (``int | None``) are only valid at RUNTIME from 3.10, and a
dataclass field annotation is evaluated when the class is created, so ``models.py`` made
``import bella_baxter`` raise ``TypeError`` on 3.9 while every other module was fine (it had the
``from __future__ import annotations`` that defers evaluation).

The real proof is importing the installed package on the minimum Python (``scripts/import_every_module.py``,
run by the ``SDK Python minimum version`` workflow). This test is the fast, any-interpreter version of the same
rule, so the mistake is caught by the unit suite on a developer's 3.12 instead of one CI job later. It reads
the source with ``ast``, so it needs no 3.9 interpreter and no generated client.

Only hand-written code is checked: the generated client (``generated/``) already carries the future import.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

PACKAGES = pathlib.Path(__file__).resolve().parents[2]  # apps/sdk/python/packages


def hand_written_modules() -> list[pathlib.Path]:
    return sorted(
        path
        for path in PACKAGES.glob("*/src/**/*.py")
        if "generated" not in path.relative_to(PACKAGES).parts
    )


def annotation_nodes(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            yield node.annotation
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns is not None:
                yield node.returns
            args = node.args
            for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]:
                if arg is not None and arg.annotation is not None:
                    yield arg.annotation


def uses_pep604_union(annotation: ast.AST) -> bool:
    # A string annotation ("Foo | None") is never evaluated at definition time, so it is safe.
    return any(
        isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr) for sub in ast.walk(annotation)
    )


def defers_annotations(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in tree.body
    )


def test_the_scan_sees_the_hand_written_modules() -> None:
    # A path change that made the glob match nothing would turn the real test below into a pass.
    names = {path.name for path in hand_written_modules()}
    assert {"models.py", "client.py", "e2ee.py"} <= names


@pytest.mark.parametrize("path", hand_written_modules(), ids=lambda p: str(p.relative_to(PACKAGES)))
def test_pep604_annotations_are_deferred(path: pathlib.Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))

    if not any(uses_pep604_union(a) for a in annotation_nodes(tree)):
        return

    assert defers_annotations(tree), (
        f"{path.relative_to(PACKAGES)} writes `X | Y` in an annotation without "
        "`from __future__ import annotations`; that raises TypeError on Python 3.9, which "
        "requires-python still allows. Add the future import (or use Optional[...])."
    )
