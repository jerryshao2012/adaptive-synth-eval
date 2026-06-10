import stat

from adaptive_synth_eval.artifacts import run_state


def test_clear_run_directory_removes_read_only_tree(tmp_path):
    run_dir = tmp_path / "run"
    personas_dir = run_dir / "personas"
    personas_dir.mkdir(parents=True)
    marker = personas_dir / "persona.json"
    marker.write_text("{}", encoding="utf-8")

    marker.chmod(stat.S_IREAD)

    run_state.clear_run_directory(run_dir)

    assert not run_dir.exists()


def test_clear_run_directory_retries_transient_permission_error(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    child = run_dir / "personas"
    child.mkdir(parents=True)
    (child / "persona.json").write_text("{}", encoding="utf-8")

    original_rmtree = run_state.shutil.rmtree
    call_count = {"value": 0}

    def flaky_rmtree(path, onerror=None):
        call_count["value"] += 1
        if call_count["value"] == 1:
            raise PermissionError("transient lock")
        return original_rmtree(path, onerror=onerror)

    monkeypatch.setattr(run_state.shutil, "rmtree", flaky_rmtree)
    monkeypatch.setattr(run_state.time, "sleep", lambda _: None)

    run_state.clear_run_directory(run_dir)

    assert call_count["value"] >= 2
    assert not run_dir.exists()
