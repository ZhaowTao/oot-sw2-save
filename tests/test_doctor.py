"""doctor: the checks that tell the four silent failures apart.

Each test builds one of the states that looked identical from inside the game
and asserts that the report names it.
"""

import json
import os
import time

from ootsw2.cli import main
from ootsw2.doctor import FAIL, OK, WARN, examine, exit_code
from ootsw2.savedir import SaveDirectory


def age(path, seconds):
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def quiet(root):
    """Everything in the tree was written an hour ago, so nothing looks live."""
    for parent, _dirs, files in os.walk(root):
        for name in files:
            age(os.path.join(parent, name), 3600)


def mirror(root):
    """Make save.work/ an exact copy of save/."""
    import shutil

    work = root / "save.work"
    for entry in os.listdir(root / "save"):
        source = root / "save" / entry
        target = work / entry
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)


def backup(root):
    target = root.parent / f"{root.name}-save-backup-20261113_000000"
    target.mkdir()
    return target


def health(root):
    """A directory with nothing to report."""
    quiet(root)
    mirror(root)
    backup(root)
    return SaveDirectory(str(root))


def codes(findings):
    return {finding.code for finding in findings}


def levels(findings):
    return {finding.code: finding.level for finding in findings}


# ------------------------------------------------------------------ baseline


def test_a_healthy_directory_reports_nothing(slot_dir):
    findings = examine(health(slot_dir))
    assert exit_code(findings) == 0
    assert all(finding.level == OK for finding in findings), codes(findings)
    assert "work-identical" in codes(findings)
    assert "idle" in codes(findings)
    assert "backup" in codes(findings)


def test_the_engine_log_settles_whether_the_game_is_running(slot_dir, tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    log = logs / f"{slot_dir.name}.log"
    log.write_text("frame 1\n")
    monkeypatch.setattr("ootsw2.doctor._game_log", lambda directory: str(log))
    quiet(slot_dir)
    log.touch()
    findings = examine(SaveDirectory(str(slot_dir)))
    assert levels(findings)["running"] == WARN
    assert "the game is running" in [f.message for f in findings if f.code == "running"][0]


def test_an_old_log_means_the_game_is_not_running(slot_dir, tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    log = logs / f"{slot_dir.name}.log"
    log.write_text("frame 1\n")
    age(log, 600)
    monkeypatch.setattr("ootsw2.doctor._game_log", lambda directory: str(log))
    findings = examine(health(slot_dir))
    assert "idle" in codes(findings)
    assert "running" not in codes(findings)


def test_a_fresh_save_tree_without_a_log_is_a_soft_warning(slot_dir):
    """A tool that just wrote looks like a game that is running; say so gently."""
    for parent, _dirs, files in os.walk(slot_dir):
        for name in files:
            age(os.path.join(parent, name), 1)
    findings = examine(SaveDirectory(str(slot_dir)))
    assert levels(findings)["recent-write"] == WARN
    assert codes(findings).isdisjoint({"running"})


# ------------------------------------------------------- the four failure modes


def test_editing_one_side_of_the_mirror_is_caught(slot_dir):
    quiet(slot_dir)
    mirror(slot_dir)
    backup(slot_dir)
    # A hand edit to save/ only, which is what a naive tool does.
    target = slot_dir / "save" / "slot_02" / "progress.sav"
    data = bytearray(target.read_bytes())
    data[-1] ^= 0xFF
    target.write_bytes(bytes(data))
    findings = examine(SaveDirectory(str(slot_dir)))
    assert levels(findings)["work-differs"] == WARN
    detail = [f for f in findings if f.code == "work-differs"][0].detail
    assert "save.work" in detail


def test_an_empty_work_copy_is_not_called_a_match(slot_dir):
    """save/ has files the work copy does not: that is a difference, not a tie."""
    findings = examine(SaveDirectory(str(slot_dir)))
    assert "work-differs" in codes(findings)


def test_a_restored_tree_reports_the_clock_conflict(slot_dir):
    """Copying a backup back rewrites mtimes; the game reads its own clock."""
    from test_caption import write_caption

    for index in range(6):
        write_caption(slot_dir / "save" / f"slot_{index:02d}" / "caption.sav",
                      when=(2026, 11, 13, 12, 0))
    write_caption(slot_dir / "save" / "slot_02" / "caption.sav",
                  when=(2026, 11, 13, 18, 0), location="Market")
    quiet(slot_dir)
    # slot_05 keeps the newest file time; slot_02 has the newest clock.
    age(slot_dir / "save" / "slot_02" / "progress.sav", 7200)
    findings = examine(SaveDirectory(str(slot_dir)))
    assert levels(findings)["clock-conflict"] == WARN
    detail = [f for f in findings if f.code == "clock-conflict"][0]
    assert "slot_02" in detail.message and "Market" in detail.detail


def test_a_slot_that_does_not_parse_fails(slot_dir):
    quiet(slot_dir)
    mirror(slot_dir)
    backup(slot_dir)
    (slot_dir / "save" / "slot_03" / "progress.sav").write_bytes(b"nope")
    findings = examine(SaveDirectory(str(slot_dir)))
    assert levels(findings)["unreadable"] == FAIL
    assert exit_code(findings) == 2


def test_no_backup_is_a_warning(slot_dir):
    quiet(slot_dir)
    mirror(slot_dir)
    findings = examine(SaveDirectory(str(slot_dir)))
    assert levels(findings)["no-backup"] == WARN
    assert exit_code(findings) == 1


def test_no_slots_fails(tmp_path):
    root = tmp_path / "0400486024DEC000"
    (root / "save").mkdir(parents=True)
    findings = examine(SaveDirectory(str(root)))
    assert findings[0].level == FAIL
    assert findings[0].code == "no-slots"
    assert exit_code(findings) == 2


def test_two_saves_in_the_same_minute_are_not_a_conflict(slot_dir):
    """The clock has minute resolution; a tie is not evidence of a restore."""
    from test_caption import write_caption

    for index in range(6):
        write_caption(slot_dir / "save" / f"slot_{index:02d}" / "caption.sav",
                      when=(2026, 11, 13, 13, 23))
    quiet(slot_dir)
    findings = examine(SaveDirectory(str(slot_dir)))
    assert "clock-agrees" in codes(findings)
    message = [f for f in findings if f.code == "clock-agrees"][0].message
    assert "share 2026-11-13 13:23" in message


# -------------------------------------------------------------------- the CLI


def test_doctor_command_prints_a_report(slot_dir, capsys):
    quiet(slot_dir)
    mirror(slot_dir)
    backup(slot_dir)
    code = main(["doctor", str(slot_dir)])
    out = capsys.readouterr().out
    assert code == 0
    assert "all clear" in out
    assert "the game loads" in out


def test_doctor_command_exit_code_is_the_worst_finding(slot_dir, capsys):
    quiet(slot_dir)
    mirror(slot_dir)
    assert main(["doctor", str(slot_dir)]) == 1  # no backup
    (slot_dir / "save" / "slot_00" / "progress.sav").write_bytes(b"nope")
    assert main(["doctor", str(slot_dir)]) == 2  # unreadable


def test_doctor_json_is_machine_readable(slot_dir, capsys):
    quiet(slot_dir)
    mirror(slot_dir)
    backup(slot_dir)
    assert main(["doctor", str(slot_dir), "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert all(set(row) >= {"level", "code", "message", "detail"} for row in rows)
    assert {row["code"] for row in rows} >= {"idle", "work-identical", "parse", "backup"}
