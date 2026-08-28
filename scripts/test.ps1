[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$RepositoryRoot = Split-Path -Parent $PSScriptRoot

Push-Location (Join-Path $RepositoryRoot 'backend')
try {
    uv sync --locked
    uv run pytest
}
finally {
    Pop-Location
}

Push-Location (Join-Path $RepositoryRoot 'frontend')
try {
    pnpm install --frozen-lockfile
    pnpm test
    pnpm build
}
finally {
    Pop-Location
}

