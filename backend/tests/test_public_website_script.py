"""Verify PC publishing control flow without opening tunnels or changing GitHub."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows desktop entry point")


@pytest.mark.parametrize(
    "scenario", ["success", "unreachable", "bad_cors", "bad_key_header", "stop"]
)
def test_pc_backend_publishing_checks_before_changing_github(tmp_path: Path, scenario: str) -> None:
    source = Path(__file__).resolve().parents[2] / "scripts/public-website.ps1"
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(source, scripts / source.name)
    commands = tmp_path / "commands.jsonl"
    shim = tmp_path / "fake_cli.py"
    shim.write_text(
        """import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ['PC_TEST_COMMANDS']).open('a') as log:
    log.write(json.dumps(args) + '\\n')
if args[:2] == ['repo', 'view']:
    print('qa-owner/qa-repo')
elif args[:2] == ['api', 'repos/qa-owner/qa-repo/pages']:
    print('https://qa-owner.github.io/qa-repo/')
elif args[:1] == ['inspect']:
    print('2026-09-14T00:00:00Z')
elif args[:1] == ['logs']:
    sys.stderr.write('https://qa-test.trycloudflare.com\\n')
elif 'ps' in args and '-q' in args:
    print('qa-container')
""",
        encoding="utf-8",
    )
    for name in ("gh", "docker"):
        (tmp_path / f"{name}.cmd").write_text(
            f'@"{sys.executable}" "{shim}" %*\n', encoding="utf-8"
        )
    wrapper = tmp_path / "test.ps1"
    wrapper.write_text(
        """function Invoke-RestMethod($Uri, $Headers, $TimeoutSec) {
    if ($Uri -like '*research-availability') { return @{enabled=$true} }
    if ($Uri -like 'https:*' -and $env:PC_TEST_SCENARIO -eq 'unreachable') {
        throw 'Simulated offline tunnel'
    }
    return @{database=@{status='available'}}
}
function Invoke-WebRequest($Uri, $Headers, $TimeoutSec, $Method, [switch]$UseBasicParsing) {
    if ($Headers.Origin -ne 'https://qa-owner.github.io') { throw 'Incorrect origin' }
    if ($Headers['Access-Control-Request-Headers'] -notmatch 'x-openai-api-key') {
        throw 'Key header missing from preflight'
    }
    $allowed = if ($env:PC_TEST_SCENARIO -eq 'bad_cors') { '' } else { $Headers.Origin }
    $allowHeaders = if ($env:PC_TEST_SCENARIO -eq 'bad_key_header') {
        'Content-Type'
    } else { 'Content-Type, X-OpenAI-API-Key' }
    return @{StatusCode=204;Headers=@{
        'Access-Control-Allow-Origin'=$allowed
        'Access-Control-Allow-Headers'=$allowHeaders
        'Access-Control-Allow-Methods'='GET, HEAD, POST, OPTIONS'
    }}
}
function Start-Sleep($Seconds) { }
$action = if ($env:PC_TEST_SCENARIO -eq 'stop') { 'Stop' } else { 'Start' }
& "$PSScriptRoot/scripts/public-website.ps1" -Action $action
exit $LASTEXITCODE
""",
        encoding="utf-8-sig",
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)],
        env={
            **os.environ,
            "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
            "PC_TEST_COMMANDS": str(commands),
            "PC_TEST_SCENARIO": scenario,
        },
        cwd=tmp_path,
        capture_output=True,
        timeout=30,
        check=False,
    )
    calls = [json.loads(line) for line in commands.read_text().splitlines()]
    updates = [call for call in calls if call[:2] == ["variable", "set"]]
    deploys = [call for call in calls if call[:2] == ["workflow", "run"]]
    assert result.returncode == (0 if scenario in {"success", "stop"} else 1), result.stdout
    assert bool(updates) == (scenario == "success")
    assert bool(deploys) == (scenario == "success")
    for call in updates + deploys:
        assert call[call.index("--repo") + 1] == "qa-owner/qa-repo"
    if scenario == "success":
        assert updates[0][-1] == "https://qa-test.trycloudflare.com"
        assert calls.index(updates[0]) < calls.index(deploys[0])
        state = json.loads((tmp_path / "runtime/public-website/state.json").read_text("utf-8-sig"))
        assert state["pages_origin"] == "https://qa-owner.github.io"
        assert state["api_url"] == "https://qa-test.trycloudflare.com"
    else:
        assert not (tmp_path / "runtime/public-website/state.json").exists()
    if scenario == "stop":
        assert len(calls) == 1
        assert calls[0][-3:] == ["stop", "public-tunnel", "public-api"]
