"""Import every module of the INSTALLED ``bella_baxter`` package, hand-written and generated.

Why this exists (#1484): ``pyproject.toml`` declares ``requires-python = ">=3.9"``, but ``models.py`` used
``int | None`` in a dataclass, which Python 3.9 evaluates at class creation and rejects with ``TypeError``.
``import bella_baxter`` failed for every 3.9 user, and nothing noticed: the unit tests register a stand-in
package precisely so ``__init__`` never runs (see ``tests/conftest.py``), and CI only ever ran 3.12.

Run it from OUTSIDE the source tree, with the interpreter the claim is about, against a pip-installed copy::

    pip install --pre apps/sdk/python/packages/sdk
    cd "$(mktemp -d)" && python -I /path/to/import_every_module.py

``-I`` keeps the current directory and ``PYTHONPATH`` off ``sys.path``, so what is imported is the installed
wheel (generated client included) and not the checkout beside it. Exit 1 lists every module that failed.
"""

from __future__ import annotations

import importlib
import pathlib
import sys

import bella_baxter


def main() -> int:
    root = pathlib.Path(bella_baxter.__file__).resolve().parent
    failures: list[tuple[str, str]] = []
    imported = 0

    for path in sorted(root.rglob("*.py")):
        parts = path.relative_to(root.parent).with_suffix("").parts
        name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        try:
            importlib.import_module(name)
            imported += 1
        except Exception as error:  # noqa: BLE001 - report every module, whatever it raised
            failures.append((name, f"{type(error).__name__}: {error}"))

    version = ".".join(map(str, sys.version_info[:3]))
    print(f"python {version}: imported {imported} module(s) of bella_baxter, {len(failures)} failed")
    for name, reason in failures:
        print(f"  FAILED {name}: {reason}")

    # An import that finds no generated client would "pass" on the hand-written modules alone.
    if not any(root.rglob("bella_client.py")):
        print("  FAILED: the generated client (generated/bella_client.py) is not in the installed package")
        return 1

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
