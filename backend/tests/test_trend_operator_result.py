"""The desktop reads an explicit operation report, independent of Process.ExitCode caching."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows operator entry")


@pytest.mark.parametrize("status", ["success", "completed_with_warnings", "failed"])
def test_scan_report_distinguishes_partial_completion(tmp_path: Path, status: str) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    entry = scripts / "trend-radar-action.ps1"
    shutil.copyfile(Path(__file__).resolve().parents[2] / "scripts" / entry.name, entry)
    shim = tmp_path / "fake_docker.py"
    shim.write_text(
        """import json, os, sys
if 'scan' in sys.argv:
    assert '--summary' in sys.argv
    status = os.environ['SCAN_TEST_STATUS']
    sys.stderr.write('INFO: progress continues despite isolated stock errors\\n')
    print(json.dumps({'status': status, 'requested_count': 5562, 'successful_count': 5549,
                      'failed_count': 13, 'candidate_count': 1270}))
    sys.exit(1 if status == 'failed' else 0)
""",
        encoding="utf-8",
    )
    (tmp_path / "docker.cmd").write_text(f'@"{sys.executable}" "{shim}" %*\n', encoding="utf-8")
    report = tmp_path / "result.json"
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(entry),
            "-Action",
            "Scan",
            "-ResultPath",
            str(report),
        ],
        env={
            **os.environ,
            "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
            "SCAN_TEST_STATUS": status,
        },
        cwd=tmp_path,
        capture_output=True,
        timeout=30,
        check=False,
    )
    value = json.loads(report.read_text("utf-8-sig"))
    assert result.returncode == value["exit_code"] == (1 if status == "failed" else 0)
    assert value["state"] == ("completed" if status == "success" else status)
    if status != "failed":
        assert value["scan"]["candidate_count"] == 1270
        assert "扫描完成" in value["message"] and "失败 13 只" in value["message"]
