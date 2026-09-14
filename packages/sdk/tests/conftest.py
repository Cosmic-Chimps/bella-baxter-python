"""
Make `bella_baxter.e2ee_httpx_transport` importable without running the package's `__init__`.

`bella_baxter/__init__.py` imports `.generated.models.*`, which Kiota produces at build time and
which is not in the tree (`src/bella_baxter/generated/` holds only `kiota-lock.json`). So
`import bella_baxter` fails on a plain checkout, and any unit test of a hand-written module in this
package would need the generator to have run first.

Rather than make a pure-Python unit test depend on codegen, this registers a stand-in package whose
`__path__` points at the real source directory. Submodule imports then resolve normally — including
the relative `from .e2ee import ...` inside the transport — while `__init__.py` never executes.

The narrowness is deliberate: only modules a test imports are loaded, so this cannot mask a missing
generated import in code that genuinely needs one.
"""

from __future__ import annotations

import pathlib
import sys
import types

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "bella_baxter"

if "bella_baxter" not in sys.modules:
    _package = types.ModuleType("bella_baxter")
    _package.__path__ = [str(_SRC)]  # type: ignore[attr-defined]
    sys.modules["bella_baxter"] = _package
