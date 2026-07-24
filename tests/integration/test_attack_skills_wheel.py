from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path


def test_installed_wheel_loads_all_packaged_attack_skills(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    dist_dir = tmp_path / "dist"
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(dist_dir)],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )

    wheel = next(dist_dir.glob("adaptive_synth_eval-*.whl"))
    install_root = tmp_path / "installed"
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(install_root)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(install_root)
    check = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; "
                "import adaptive_synth_eval; "
                "from adaptive_synth_eval.adversarial_response_engine.skills.registry "
                "import get_builtin_registry; "
                f"root = Path({str(install_root)!r}).resolve(); "
                "assert Path(adaptive_synth_eval.__file__).resolve().is_relative_to(root); "
                "skills = get_builtin_registry().skills; "
                "assert len(skills) == 11; "
                "assert all(skill.package_digest for skill in skills)"
            ),
        ],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0
