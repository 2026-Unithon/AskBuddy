param(
    [string]$Python = "python",
    [switch]$IncludeUnitTests,
    [switch]$IncludeSchemaRebuild
)
$ErrorActionPreference = "Stop"
if (Test-Path -LiteralPath $Python -PathType Leaf) {
    $Python = (Resolve-Path -LiteralPath $Python).Path
}
$containerName = "askbuddy-r-handoff-" + [guid]::NewGuid().ToString("N")
$created = $false
$rPriorPythonUtf8 = $env:PYTHONUTF8
$rPriorPythonEncoding = $env:PYTHONIOENCODING
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
# 전체 schema는 supabase/config.toml의 PG17과 remote baseline의 MAINTAIN 권한을 따른다.
# 기존 경량 R 검증의 PG15 호환성 실행은 유지한다.
$rDatabaseImage = if ($IncludeSchemaRebuild) { 'pgvector/pgvector:pg17' } else { 'postgres:15-alpine' }
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    # 검증 스크립트의 DSN은 이 loopback 포트만 사용한다. 기존 DB/.env를 쓰지 않는다.
    docker run --detach --rm --name $containerName --label askbuddy.test=r-handoff `
        --publish 127.0.0.1:55439:5432 --env POSTGRES_PASSWORD=synthetic-local-test `
        --env POSTGRES_DB=usage_verify $rDatabaseImage
    if ($LASTEXITCODE -ne 0) { throw "Isolated PostgreSQL startup failed" }
    $created = $true
    $ready = $false
    for ($attemptNumber = 0; $attemptNumber -lt 20; $attemptNumber++) {
        docker exec $containerName pg_isready -U postgres -d usage_verify
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw "PostgreSQL did not become ready" }
    foreach ($checkScript in @("verify_r_answer_usage.py", "verify_r_security.py", "verify_r_embedding_usage.py", "verify_w_embedding_service.py", "verify_w_score_migration.py", "verify_r_context_stale.py")) {
        & $Python -B (Join-Path $PSScriptRoot $checkScript)
        if ($LASTEXITCODE -ne 0) { throw "Verification failed: $checkScript" }
    }
    if ($IncludeUnitTests) {
        & $Python -B -m pytest tests -q --tb=short
        if ($LASTEXITCODE -ne 0) { throw "Unit regression failed" }
    }
    if ($IncludeSchemaRebuild) {
        & $Python -B (Join-Path $PSScriptRoot 'verify_r_schema_rebuild.py')
        if ($LASTEXITCODE -ne 0) { throw "Full schema rebuild failed" }
    }
} finally {
    # 이 실행이 만든 무작위 이름의 컨테이너만 정리한다.
    if ($created) {
        docker stop $containerName
        if ($LASTEXITCODE -ne 0) { Write-Warning "Cleanup failed: $containerName" }
    }
    Pop-Location
    $env:PYTHONUTF8 = $rPriorPythonUtf8
    $env:PYTHONIOENCODING = $rPriorPythonEncoding
}
