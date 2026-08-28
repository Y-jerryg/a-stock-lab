[CmdletBinding()]
param(
    [string]$RevisionMessage
)

$ErrorActionPreference = 'Stop'
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
Push-Location (Join-Path $RepositoryRoot 'backend')

try {
    if ($RevisionMessage) {
        uv run alembic revision --autogenerate -m $RevisionMessage
    }
    else {
        uv run alembic upgrade head
    }
}
finally {
    Pop-Location
}

