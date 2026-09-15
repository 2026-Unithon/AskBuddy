param(
    [string]$Python = "python",
    [switch]$IncludeUnitTests
)
$ErrorActionPreference = "Stop"
if (Test-Path -LiteralPath $Python -PathType Leaf) {
    $Python = (Resolve-Path -LiteralPath $Python).Path
}
$containerName = "askbuddy-r-handoff-" + [guid]::NewGuid().ToString("N")
$created = $false
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    # 검증 스크립트의 DSN은 이 loopback 포트만 사용한다. 기존 DB/.env를 쓰지 않는다.
    docker run --detach --rm --name $containerName --label askbuddy.test=r-handoff `
        --publish 127.0.0.1:55439:5432 --env POSTGRES_PASSWORD=synthetic-local-test `
        --env POSTGRES_DB=usage_verify postgres:15-alpine
    if ($LASTEXITCODE -ne 0) { throw "Isolated PostgreSQL startup failed" }
    $created = $true
    $ready = $false
    for ($attemptNumber = 0; $attemptNumber -lt 20; $attemptNumber++) {
        docker exec $containerName pg_isready -U postgres -d usage_verify
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw "PostgreSQL did not become ready" }
    foreach ($checkScript in @("verify_r_answer_usage.py", "verify_r_security.py", "verify_r_embedding_usage.py")) {
        & $Python -B (Join-Path $PSScriptRoot $checkScript)
        if ($LASTEXITCODE -ne 0) { throw "Verification failed: $checkScript" }
    }
    if ($IncludeUnitTests) {
        & $Python -B -m pytest tests -q --tb=short
        if ($LASTEXITCODE -ne 0) { throw "Unit regression failed" }
    }
} finally {
    # 이 실행이 만든 무작위 이름의 컨테이너만 정리한다.
    if ($created) {
        docker stop $containerName
        if ($LASTEXITCODE -ne 0) { Write-Warning "Cleanup failed: $containerName" }
    }
    Pop-Location
}
