"""Every documented ``pip install`` of this package actually installs it.

The defect (#744): ``pyproject.toml`` versions the SDK ``0.1.1-preview.N``, which PEP 440 normalises
to ``0.1.1rcN`` — a pre-release. ``pip`` excludes pre-releases unless asked, and **every** release on
PyPI is one (100 releases, zero stable, for all four packages). So the documented
``pip install bella-baxter`` resolved no version at all — not an older one, none — and the Ansible
collection, which is the deploy-time integration, could not be installed as written.

Why a test rather than a careful sweep. The instruction appears in 34 places across 19 files: eight
markdown docs, three example playbooks, and — the ones that matter most — the **runtime error
messages** in seven Ansible plugins. When a user hits the missing dependency, Ansible tells them
``Install it with: pip install --pre bella-baxter``; before this it told them to run the command that
had just failed to work. A user following an error message into a loop is the worst version of this
bug, and it is the version a doc review is least likely to catch.

Why the rule is not a shared constant. Most occurrences live in Ansible ``DOCUMENTATION`` blocks,
which are static YAML strings — they cannot interpolate a Python constant, so a shared literal would
cover the seven error messages and leave twenty-seven copies looking centralised while drifting. A
guard covers all of them regardless of file type. Same reasoning as the console's glossary lint,
which polices a catalogue it likewise cannot centralise.

WHEN A STABLE RELEASE SHIPS, THIS TEST IS THE THING THAT TELLS YOU TO UNDO THE WORKAROUND. ``--pre``
is correct only while no stable version exists; afterwards it is actively harmful, because it would
pull an rc over the stable. Flip ``PRERELEASE_ONLY`` to ``False`` and the guard inverts, failing on
any surviving ``--pre``.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

#: While true, ``--pre`` is required. Flip when a stable ``0.1.x`` is published — see the docstring.
PRERELEASE_ONLY = True

PACKAGES = "bella-baxter(?:-django|-flask|-fastapi)?"

#: A bare install of a pre-release-only package: no ``--pre``, and no exact ``==`` pin (an exact
#: pre-release pin resolves fine, which is why the reproduction steps in the bug reports still work).
BARE_INSTALL = re.compile(rf"\bpip3?\s+install\s+(?!--pre\b)(?!-)({PACKAGES})(?![-\w=])")

WITH_PRE = re.compile(rf"\bpip3?\s+install\s+--pre\s+({PACKAGES})(?![-\w])")

#: Bug reports describe the broken command on purpose and must keep doing so.
EXCLUDED = ("docs/issues/", "node_modules/", ".venv", "/obj/", "/bin/", ".claude/")


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".git").exists():
            return parent
    pytest.skip("not inside a git checkout")


def tracked_files() -> list[Path]:
    root = repo_root()
    listing = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.splitlines()

    return [
        root / f
        for f in listing
        if f and not any(x in f for x in EXCLUDED) and (root / f).is_file()
    ]


def offenders(pattern: re.Pattern[str]) -> list[str]:
    found: list[str] = []
    for path in tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                found.append(f"{path.relative_to(repo_root())}:{number}  {line.strip()}")
    return found


@pytest.mark.skipif(not PRERELEASE_ONLY, reason="a stable release exists")
def test_no_documented_install_omits_pre() -> None:
    bare = offenders(BARE_INSTALL)

    assert not bare, (
        "These tell a user to run a command that installs NOTHING: every release of these packages "
        "on PyPI is a pre-release, and pip skips pre-releases unless asked. Use "
        "`pip install --pre <package>`.\n\n" + "\n".join(bare)
    )


@pytest.mark.skipif(PRERELEASE_ONLY, reason="no stable release yet — --pre is still required")
def test_pre_is_removed_once_a_stable_release_exists() -> None:
    stale = offenders(WITH_PRE)

    assert not stale, (
        "A stable release exists, so `--pre` is now harmful: it pulls a release candidate over the "
        "stable version. Remove it from these.\n\n" + "\n".join(stale)
    )


def test_the_ansible_plugins_do_not_send_a_blocked_user_in_a_circle() -> None:
    """The error a user sees when the package is missing must name a command that works."""
    plugins = repo_root() / "apps/sdk/ansible/plugins"
    checked = 0

    for path in sorted(plugins.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "Install it with" not in text:
            continue
        checked += 1
        assert not BARE_INSTALL.search(text), (
            f"{path.relative_to(repo_root())} tells a blocked user to run an install that resolves "
            "no version — the message exists to unblock them and instead repeats their failure."
        )

    assert checked >= 7, f"expected the seven plugins to carry an install hint, found {checked}"
