param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "Programs\LAKIS")
)

$ErrorActionPreference = "Stop"
$patchRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$payloadRoot = Join-Path $patchRoot "payload"
$manifestPath = Join-Path $patchRoot "patch-manifest.json"
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
$installRootPath = [System.IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
$versionPath = Join-Path $installRootPath "VERSION"

if (-not (Test-Path -LiteralPath $versionPath -PathType Leaf)) {
    throw "LAKIS 설치 경로가 아닙니다: $installRootPath"
}
$installedVersion = (Get-Content -Raw -LiteralPath $versionPath).Trim()
if ($installedVersion -notin @([string]$manifest.from_version, [string]$manifest.version)) {
    throw "이 패치는 LAKIS $($manifest.from_version) 전용입니다. 현재 버전: $installedVersion"
}

$running = @(Get-Process -Name "LAKIS","LAKIS_Desktop","LAKIS_Patcher","LAKIS_Updater" -ErrorAction SilentlyContinue)
if ($running.Count -gt 0) {
    throw "LAKIS와 관련 창을 모두 종료한 뒤 다시 실행해 주세요."
}

$backupRoot = Join-Path $installRootPath (".lakis\offline-backups\{0}-{1}" -f $manifest.version, (Get-Date -Format "yyyyMMdd-HHmmss"))
$replaced = [System.Collections.Generic.List[object]]::new()
$created = [System.Collections.Generic.List[string]]::new()

try {
    foreach ($item in $manifest.files) {
        $relative = ([string]$item.path).Replace('/', '\')
        if ([System.IO.Path]::IsPathRooted($relative) -or $relative.Split('\') -contains '..') {
            throw "안전하지 않은 패치 경로: $relative"
        }
        $source = [System.IO.Path]::GetFullPath((Join-Path $payloadRoot $relative))
        $target = [System.IO.Path]::GetFullPath((Join-Path $installRootPath $relative))
        if (-not $target.StartsWith($installRootPath + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "설치 경로 밖의 대상이 감지되었습니다: $relative"
        }
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "패치 파일 누락: $relative"
        }
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash
        if ($hash -ne ([string]$item.sha256).ToUpperInvariant()) {
            throw "패치 파일 해시 불일치: $relative"
        }

        if (Test-Path -LiteralPath $target -PathType Leaf) {
            $backup = Join-Path $backupRoot $relative
            New-Item -ItemType Directory -Force -Path (Split-Path $backup) | Out-Null
            Copy-Item -LiteralPath $target -Destination $backup -Force
            $replaced.Add([pscustomobject]@{ Target = $target; Backup = $backup })
        } else {
            $created.Add($target)
        }

        New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
        $temporary = $target + ".lakis-new"
        Copy-Item -LiteralPath $source -Destination $temporary -Force
        Move-Item -LiteralPath $temporary -Destination $target -Force
    }
    Set-Content -LiteralPath $versionPath -Value ([string]$manifest.version) -Encoding ASCII
    Write-Host "LAKIS $($manifest.version) 오프라인 패치 완료" -ForegroundColor Green
    Write-Host "백업: $backupRoot"
}
catch {
    foreach ($target in $created) {
        if (Test-Path -LiteralPath $target -PathType Leaf) { Remove-Item -LiteralPath $target -Force }
    }
    foreach ($entry in $replaced) {
        if (Test-Path -LiteralPath $entry.Backup -PathType Leaf) {
            New-Item -ItemType Directory -Force -Path (Split-Path $entry.Target) | Out-Null
            Copy-Item -LiteralPath $entry.Backup -Destination $entry.Target -Force
        }
    }
    throw "패치 적용에 실패하여 변경된 파일을 복원했습니다. $($_.Exception.Message)"
}

