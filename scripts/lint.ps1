[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$RepositoryRoot = Split-Path -Parent $PSScriptRoot

Push-Location (Join-Path $RepositoryRoot 'backend')
try {
    uv sync --locked
    uv run ruff format --check .
    uv run ruff check .
    uv run mypy src tests
}
finally {
    Pop-Location
}

Push-Location (Join-Path $RepositoryRoot 'frontend')
try {
    pnpm install --frozen-lockfile
    pnpm lint
    pnpm typecheck
    pnpm exec prettier --check .
}
finally {
    Pop-Location
}

