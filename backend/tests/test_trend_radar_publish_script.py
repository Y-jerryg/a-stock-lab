"""Exercise the desktop publication entry point using real Windows PowerShell 5.1."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows desktop entry point")


@pytest.mark.parametrize(
    "scenario", ["first", "existing", "query_error", "upload_error", "old_frontend"]
)
def test_publication_native_errors_preserve_expected_control_flow(
    tmp_path: Path, scenario: str
) -> None:
    source = Path(__file__).resolve().parents[2] / "scripts/trend-radar-action.ps1"
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    entry = scripts / source.name
    shutil.copyfile(source, entry)
    public = tmp_path / "runtime/public/trend-radar"
    public.mkdir(parents=True)
    (public / "index.json").write_text(
        json.dumps({"attempts": [{"payload": {"configuration_snapshot": {"rule_version": 2}}}]})
    )
    commands = tmp_path / "commands.jsonl"
    shim = tmp_path / "fake_cli.py"
    shim.write_text(
        """import base64, json, os, sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ['PUBLISH_TEST_COMMANDS']).open('a') as log:
    log.write(json.dumps(args) + '\\n')
case = os.environ['PUBLISH_TEST_SCENARIO']
if args[:2] == ['repo', 'view']:
    print('qa-owner/qa-repo')
elif args[:1] == ['api']:
    version = 1 if case == 'old_frontend' else 2
    print(base64.b64encode(json.dumps({'trend_rule_version':version}).encode()).decode())
elif args[:2] == ['release', 'view']:
    if case != 'existing':
        message = 'HTTP 403: Forbidden' if case == 'query_error' else 'release not found'
        sys.stderr.write(message + '\\n')
        sys.exit(1)
    print('{"tagName":"trend-radar-data"}')
elif args[:2] == ['release', 'upload'] and case == 'upload_error':
    sys.stderr.write('upload failed\\n')
    sys.exit(1)
""",
        encoding="utf-8",
    )
    for name in ("gh", "docker"):
        (tmp_path / f"{name}.cmd").write_text(
            f'@"{sys.executable}" "{shim}" %*\n', encoding="utf-8"
        )
    environment = {
        **os.environ,
        "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
        "PUBLISH_TEST_COMMANDS": str(commands),
        "PUBLISH_TEST_SCENARIO": scenario,
    }
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(entry),
            "-Action",
            "Publish",
        ],
        env=environment,
        cwd=tmp_path,
        capture_output=True,
        timeout=30,
        check=False,
    )
    calls = [json.loads(line) for line in commands.read_text().splitlines()]
    creates = [call for call in calls if call[:2] == ["release", "create"]]
    uploads = [call for call in calls if call[:2] == ["release", "upload"]]
    deploys = [call for call in calls if call[:2] == ["workflow", "run"]]
    assert result.returncode == (0 if scenario in {"first", "existing"} else 1)
    assert bool(creates) == (scenario in {"first", "upload_error"})
    assert bool(uploads) == (scenario not in {"query_error", "old_frontend"})
    assert bool(deploys) == (scenario in {"first", "existing"})
    for call in creates + uploads + deploys:
        assert call[call.index("--repo") + 1] == "qa-owner/qa-repo"
