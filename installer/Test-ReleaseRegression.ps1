param(
    [string]$ExpectedVersion = ""
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($ExpectedVersion)) {
    $ExpectedVersion = (Get-Content -Raw -LiteralPath (Join-Path $repo "VERSION")).Trim()
}

function Require([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "RELEASE REGRESSION GATE FAILED: $Message" }
}

function Read-RepoFile([string]$RelativePath) {
    $path = Join-Path $repo $RelativePath
    Require (Test-Path -LiteralPath $path -PathType Leaf) "Missing required file: $RelativePath"
    return Get-Content -Raw -LiteralPath $path
}

$version = (Read-RepoFile "VERSION").Trim()
Require ($version -eq $ExpectedVersion) "VERSION is '$version', expected '$ExpectedVersion'."

$updater = Read-RepoFile "installer\LAKIS_Updater.cs"
Require ($updater.Contains("attempt <= 3")) "Updater must retry each verified file three times."
Require ($updater.Contains("lakis_update=")) "Updater downloads must use a unique cache-busting URL."
Require ($updater.Contains("no-cache, no-store, must-revalidate")) "Updater must bypass HTTP caches."
Require ($updater.Contains("파일 검증 실패(3회 재시도)")) "Updater must report exhausted checksum retries."

$generator = Read-RepoFile "installer\New-UpdateManifest.ps1"
Require ($generator.Contains("lakis-tag-hash-")) "Manifest hashes must come from published tagged bytes."
Require ($generator.Contains("LICENSE.md")) "Existing users must receive the LAKIS licence."
Require ($generator.Contains("THIRD_PARTY_NOTICES.md")) "Existing users must receive third-party notices."
Require ($generator.Contains("ComfyUI-LAKIS-Light-Control")) "Existing users must receive the DSINE-free Light Control stub."
Require (-not $generator.Contains('path = "ComfyUI/models/')) "Legacy updaters reject model paths; models must not be in the manifest."

$thirdPartyNotices = Read-RepoFile "THIRD_PARTY_NOTICES.md"
foreach ($noticeName in @(
    "ComfyUI-Lora-Manager",
    "ComfyUI_bsk_UI",
    "RealESRGAN_x4plus_anime_6B.pth",
    "2x-AnimeSharpV4_Fast_RCAN_PU.safetensors",
    "anima_baseV10.safetensors",
    "anima-turbo-lora-v0.2.safetensors",
    "qwen_3_06b_base.safetensors",
    "qwen_image_vae.safetensors",
    "sam3.1_multiplex_fp16.safetensors",
    "7-Zip",
    "DSINE"
)) {
    Require ($thirdPartyNotices.Contains($noticeName)) "Third-party notice is missing: $noticeName"
}
Require ($thirdPartyNotices.Contains("bd43b7cffe1ed1153d9c41e7beb2f18cb1273eafbaa3af3edd6a173dc90a006e")) "Official Anima base provenance hash must remain documented."
Require ($thirdPartyNotices.Contains("cd2a512003e2f9f3cd3c32a9c3573f820bb28c940f73c57b1ddaa983d9223eba")) "Qwen encoder provenance hash must remain documented."
Require ($thirdPartyNotices.Contains("1b55e40bdb1d0e5a78cb498f245fccfdaae97823265db957d2aabdcf4cd3caf1")) "Anima Turbo LoRA provenance hash must remain documented."

$canonicalCopyright = "© 2026 Luke Jeong. All rights reserved."
foreach ($copyrightSource in @(
    "installer\Setup_LAKIS_Safe.cs",
    "installer\LAKIS_Updater.cs",
    "installer\LAKIS_Launcher.cs",
    "installer\LAKIS_Uninstaller.cs",
    "src\external_ui\index.html"
)) {
    Require ((Read-RepoFile $copyrightSource).Contains($canonicalCopyright)) "Copyright notice is inconsistent: $copyrightSource"
}

$manifestTest = Read-RepoFile "installer\Test-UpdateManifest.ps1"
Require ($manifestTest.Contains("[ValidateRange(1, 10)][int]`$Passes")) "Manifest preflight must support repeated verification."
Require ($manifestTest.Contains("Cache-Control")) "Manifest preflight must bypass caches."

$workflow = Read-RepoFile ".github\workflows\publish-installer.yml"
Require ($workflow.Contains("LAKIS_Model_Importer.exe#LAKIS_Model_Importer.exe")) "Model Importer release asset is missing."
Require ($workflow.Contains("LAKIS_Updater.exe#LAKIS_Updater.exe")) "Fallback Updater release asset is missing."
Require ($workflow.Contains("-VerifyRemote -Passes 3")) "Release workflow must remotely verify every file three times."
Require ($workflow.Contains("gh release create `$env:RELEASE_TAG --draft")) "Release assets must be staged in a draft release."
Require ($workflow.Contains("-DraftReleaseTag `$env:RELEASE_TAG")) "Draft release assets must be authenticated and hash-verified before publish."
Require ($workflow.Contains("Test-InstallerDataSafety.ps1 -InstallerPath `$env:LAKIS_INSTALLER_OUTPUT")) "Built Setup artifact must pass the destructive-install regression test."
Require ($workflow.Contains("publishedResponse.TrimStart([char]0xFEFF) | ConvertFrom-Json")) "Release identity guard must parse the text/plain GitHub manifest and strip its BOM."
$verifyIndex = $workflow.IndexOf("-VerifyRemote -Passes 3", [System.StringComparison]::Ordinal)
$releasePublishIndex = $workflow.IndexOf("Publish the fully verified release", [System.StringComparison]::Ordinal)
$publishIndex = $workflow.IndexOf("Publish only the verified manifest", [System.StringComparison]::Ordinal)
Require ($verifyIndex -ge 0 -and $releasePublishIndex -gt $verifyIndex -and $publishIndex -gt $releasePublishIndex) "Draft verification, release publication, and manifest publication are out of order."

$setup = Read-RepoFile "installer\Setup_LAKIS_Safe.cs"
foreach ($needle in @(
    ('private const string Revision = "v' + $ExpectedVersion + '"'),
    'LAKIS_Model_Importer.exe',
    'THIRD_PARTY_NOTICES.md',
    'ComfyUI-LAKIS-Light-Control',
    'LAKIS_runtime_api_v7.1.json',
    'RealESRGAN_x4plus_anime_6B.pth'
)) {
    Require ($setup.Contains($needle)) "Installer/repair invariant is missing: $needle"
}
Require ($setup.Contains("if(IsExistingInstallation(target))throw new InvalidOperationException")) "New install must reject an existing LAKIS installation."
Require ($setup.Contains("if(HasDirectoryEntries(target))throw new InvalidOperationException")) "New install must reject every non-empty destination."
Require ($setup.Contains("circlestone-labs/Anima/resolve/e26179e4b23bcb3a9e91b4ad2961a76ab9644d43/split_files/text_encoders/qwen_3_06b_base.safetensors")) "Qwen encoder must come from the pinned official Anima source."
Require ($setup.Contains("circlestone-labs/Anima/resolve/457fbf842cb86e96af72c65bdd13e3f1c448de84/split_files/diffusion_models/anima-base-v1.0.safetensors")) "Anima base must come from the pinned official source."
Require (-not $setup.Contains("Aitrepreneur/FLX")) "The unlicensed FLX mirror must not remain in the installer."
Require (-not $setup.Contains("p101111/anima")) "The unlicensed Anima mirror must not remain in the installer."

$externalLauncher = Read-RepoFile "src\external_ui\launch_lakis.py"
$externalServer = Read-RepoFile "src\external_ui\serve_ui.py"
$desktopLauncher = Read-RepoFile "installer\LAKIS_Launcher.cs"
Require ($externalLauncher.Contains('"--port", "0"')) "External UI must use an OS-assigned per-launch port."
Require ($externalLauncher.Contains("wait_ui_bridge_ready")) "External UI must complete the identity handshake before opening Desktop."
Require (-not $externalLauncher.Contains("responds(UI_URL)")) "Launcher must never reuse an arbitrary process on the legacy shared UI port."
Require ($externalLauncher.Contains('"LAKIS_COMFYUI_PORT_IN_USE_FAILED"')) "Launcher must fail closed when another backend already owns port 8189."
Require (-not $externalLauncher.Contains('"existing" if responds(COMFY_URL)')) "Launcher must never reuse an arbitrary ComfyUI backend."
Require ($externalServer.Contains("/api/launcher-identity")) "External UI identity endpoint is missing."
Require ($externalServer.Contains("server.server_address[1]")) "External UI must report its actual OS-assigned port."
Require ($desktopLauncher.Contains("WaitForLauncherReady")) "Desktop launcher must wait for its own Python launcher state."
Require (-not $desktopLauncher.Contains("UiResponds()")) "Desktop launcher must not accept an unrelated service on port 8766."

& (Join-Path $PSScriptRoot "Test-InstallerDataSafety.ps1")
Require ($LASTEXITCODE -eq 0) "Installer behavioral data-safety test failed."
& (Join-Path $PSScriptRoot "Test-RepairDataSafety.ps1")
Require ($LASTEXITCODE -eq 0) "Repair data-preservation audit failed."

$jsonPaths = @(
    "workflows\LAKIS_runtime_api_v7.1.json",
    "workflows\LAKIS_runtime_visual_v7.1.json",
    "workflows\LAKIS_custom_v7.1_editable.json"
)
$jsonFiles = @($jsonPaths | ForEach-Object {
    $path = Join-Path $repo $_
    Require (Test-Path -LiteralPath $path -PathType Leaf) "Missing required JSON: $_"
    $path
})
$cameraBridgeRoot = Join-Path $repo "src\custom_nodes\ComfyUI-KR-Camera-PromptStudio-Bridge"
$cameraBridgeJson = @(Get-ChildItem -LiteralPath $cameraBridgeRoot -File -Filter "KR_Camera_Anima_*_ONOFF.json")
Require ($cameraBridgeJson.Count -eq 1) "Expected exactly one packaged KR Camera Anima bridge workflow."
$jsonFiles += $cameraBridgeJson[0].FullName
$bundledPythonCandidates = @(
    [System.IO.Path]::GetFullPath((Join-Path $repo "..\..\python_embeded\python.exe")),
    [System.IO.Path]::GetFullPath((Join-Path $repo "..\first-user-test\install\python_embeded\python.exe"))
)
$bundledPython = $bundledPythonCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
$python = if (-not [string]::IsNullOrWhiteSpace($bundledPython)) {
    $bundledPython
} else {
    (Get-Command python -ErrorAction Stop).Source
}
foreach ($pythonSource in @(
    (Join-Path $repo "src\external_ui\launch_lakis.py"),
    (Join-Path $repo "src\external_ui\serve_ui.py"),
    (Join-Path $repo "src\external_ui\workflow_bridge.py")
)) {
    & $python -m py_compile $pythonSource
    Require ($LASTEXITCODE -eq 0) "Invalid Python launcher/server source: $pythonSource"
}
& $python (Join-Path $repo "installer\tests\test_installation_isolation.py")
Require ($LASTEXITCODE -eq 0) "Cross-install external UI isolation regression failed."
& $python (Join-Path $repo "installer\tests\test_ui_state_scoping.py")
Require ($LASTEXITCODE -eq 0) "Per-install UI-state isolation regression failed."
foreach ($jsonFile in $jsonFiles) {
    & $python -m json.tool $jsonFile 1>$null
    Require ($LASTEXITCODE -eq 0) "Invalid packaged workflow JSON: $jsonFile"
}

foreach ($required in @(
    "LICENSE.md",
    "THIRD_PARTY_NOTICES.md",
    "third_party_licenses\Real-ESRGAN-BSD-3-Clause.txt",
    "third_party_licenses\CircleStone-Labs-Non-Commercial-License-v1.2.md",
    "third_party_licenses\NVIDIA-Open-Model-License-2025-10-24.pdf",
    "third_party_licenses\NVIDIA-Cosmos-NOTICE.txt",
    "src\custom_nodes\ComfyUI-LAKIS-AutoPatch\LICENSE",
    "src\custom_nodes\ComfyUI-KR-Camera-PromptStudio-Bridge\LICENSE",
    "src\external_ui\system-info-dialog.js",
    "src\external_ui\upscaler-license-migration.js",
    "src\external_ui\assets\upscaler\realesrgan-anime-6b-preview.png",
    "src\external_ui\assets\upscaler\animesharp-v4-fast-preview.png",
    "installer\LAKIS_Model_Importer.cs",
    "installer\Test-RepairDataSafety.ps1",
    "installer\tests\test_installation_isolation.py",
    "installer\tests\test_ui_state_scoping.py",
    "RELEASE_REGRESSION_CHECKLIST.md"
)) {
    Require (Test-Path -LiteralPath (Join-Path $repo $required) -PathType Leaf) "Missing release component: $required"
}

Write-Output "RELEASE_REGRESSION_GATE_OK version=$ExpectedVersion"
