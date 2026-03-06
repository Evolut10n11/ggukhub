param(
    [string]$Root = "C:\Users\rodionov.ip\Desktop\git"
)

$ErrorActionPreference = "Stop"

$repos = @(
    @{
        Name = "pydantic-ai"
        Url = "https://gitea.green-garden.ru/ai-department/pydantic-ai.git"
    },
    @{
        Name = "pydantic-ai-langfuse-extras"
        Url = "https://gitea.green-garden.ru/ai-department/pydantic-ai-langfuse-extras.git"
    }
)

New-Item -ItemType Directory -Force -Path $Root | Out-Null

foreach ($repo in $repos) {
    $path = Join-Path $Root $repo.Name
    if (Test-Path $path) {
        Write-Host "Updating $($repo.Name) in $path"
        git -C $path fetch --all --prune
        git -C $path pull --ff-only
    }
    else {
        Write-Host "Cloning $($repo.Name) into $path"
        git clone $repo.Url $path
    }
}

Write-Host "Done."

