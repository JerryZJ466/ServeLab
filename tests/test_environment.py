import platform
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_project_uses_pinned_python() -> None:
    expected = (REPO_ROOT / ".python-version").read_text(encoding="utf-8").strip()

    assert platform.python_version() == expected


def test_phase_a_entrypoints_exist() -> None:
    expected_paths = (
        REPO_ROOT / "docs" / "environment.md",
        REPO_ROOT / "scripts" / "smoke.sh",
        REPO_ROOT / "uv.lock",
    )

    assert all(path.is_file() for path in expected_paths)
