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

$generator = Read-RepoFile "installer\New-UpdateManifest.ps1"
$layoutGenerator = Read-RepoFile "installer\New-ReleaseLayout.ps1"
$nodePackages = Read-RepoFile "resources\PRODUCTION_NODE_PACKAGES.txt"
Require ($generator.Contains("lakis-tag-hash-")) "Manifest hashes must come from published tagged bytes."
Require ($generator.Contains("LICENSE.md")) "Existing users must receive the LAKIS licence."
Require ($generator.Contains("THIRD_PARTY_NOTICES.md")) "Existing users must receive third-party notices."
Require (-not $generator.Contains('path = "ComfyUI/models/')) "Legacy updaters reject model paths; models must not be in the manifest."
Require (-not $generator.Contains('Add-UpdateFile "ComfyUI/custom_nodes/ComfyUI-LAKIS-Light-Control')) "Next manifest generator must not distribute retired Light Control."
Require ($generator.Contains("ComfyUI/custom_nodes/ComfyUI-LAKIS-Light-Control/__init__.py")) "Next manifest must explicitly remove retired Light Control."
Require (-not $generator.Contains("DSINE")) "Next manifest generator must not include DSINE."
Require ($nodePackages.Contains("ComfyUI-LAKIS-Local-Inpaint")) "Manifest generator must include the public Local Inpaint V2 custom node."
Require ($nodePackages.Contains("ComfyUI-Anima-LLLite")) "Manifest generator must include the Local Inpaint runtime node package."
Require (-not $generator.Contains('ComfyUI/LAKIS_DEV/external_ui/')) "Public update files must target the production LAKIS runtime directory."
Require ($generator.Contains("forbiddenProductPathPattern")) "Manifest generator must enforce the DEKIS/LUKIS product-boundary guard."
Require ($generator.Contains("LAKIS_LUKE")) "Manifest generator must block private LUKIS runtime paths."
Require ($generator.Contains("LUKE_VERSION")) "Manifest generator must block private LUKIS version files."
Require ($layoutGenerator.Contains('product = "LAKIS"')) "Release layout must identify the public product."
Require ($layoutGenerator.Contains('size = [int64]$_.Length')) "Release layout must use byte-size comparison."
Require ($layoutGenerator.Contains("LAKIS_RepairPack.zip")) "Release layout generator must produce the automatic RepairPack."
Require ($layoutGenerator.Contains("ComfyUI/(models|user|input|output)")) "Release layout generator must exclude user-owned trees."
Require ($generator.Contains('Add-UpdateFile "ComfyUI/LAKIS/STOP_AUTOMATION"')) "Every update must restore the generation safety marker."
Require (-not $generator.Contains("'ComfyUI/LAKIS/STOP_AUTOMATION',")) "The generation safety marker must never be deleted."

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
    "7-Zip"
)) {
    Require ($thirdPartyNotices.Contains($noticeName)) "Third-party notice is missing: $noticeName"
}
Require ($thirdPartyNotices.Contains("bd43b7cffe1ed1153d9c41e7beb2f18cb1273eafbaa3af3edd6a173dc90a006e")) "Official Anima base provenance hash must remain documented."
Require ($thirdPartyNotices.Contains("cd2a512003e2f9f3cd3c32a9c3573f820bb28c940f73c57b1ddaa983d9223eba")) "Qwen encoder provenance hash must remain documented."
Require ($thirdPartyNotices.Contains("1b55e40bdb1d0e5a78cb498f245fccfdaae97823265db957d2aabdcf4cd3caf1")) "Anima Turbo LoRA provenance hash must remain documented."

$canonicalCopyright = "2026 Luke Jeong. All rights reserved."
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
$rcWorkflow = Read-RepoFile ".github\workflows\prepare-private-rc.yml"
$releaseBuild = Read-RepoFile "installer\build_safe_installer.ps1"
$devBuild = Read-RepoFile "installer\build_dev_launcher.ps1"
$productBoundary = Read-RepoFile "installer\Test-PublicProductBoundary.ps1"
Require (-not $releaseBuild.Contains("New-ReleaseIntegrity.ps1")) "Public build must not use the retired embedded-SHA startup integrity chain."
Require (-not $releaseBuild.Contains("LAKIS.ReleaseIntegritySha256")) "Public Launcher must not embed the retired integrity-manifest SHA."
Require ($devBuild.Contains("System.IO.Compression.dll")) "DEV Launcher build must reference System.IO.Compression.dll."
Require ($devBuild.Contains("System.IO.Compression.FileSystem.dll")) "DEV Launcher build must reference System.IO.Compression.FileSystem.dll."
Require ($rcWorkflow.Contains("New-ReleaseLayout.ps1")) "Private RC workflow must generate release-layout.json and the RepairPack after the exact binaries are built."
Require ($rcWorkflow.Contains("LAKIS_RepairPack.zip")) "Private RC artifact set must include the automatic RepairPack."
Require ($workflow.Contains("release-layout.json#release-layout.json")) "Public release must upload release-layout.json."
Require ($workflow.Contains("LAKIS_RepairPack.zip#LAKIS_RepairPack.zip")) "Public release must upload the RepairPack."
foreach ($requiredPublicBinary in @("LAKIS.exe", "LAKIS_Patcher.exe", "LAKIS_Updater.exe", "LAKIS_Desktop.exe", "LAKIS_Model_Importer.exe", "Uninstall_LAKIS.exe", "LAKIS_Setup.exe")) {
    Require ($productBoundary.Contains('"' + $requiredPublicBinary + '"')) "Public product-boundary scan is missing binary: $requiredPublicBinary"
}
Require ($productBoundary.Contains('Get-ChildItem -LiteralPath $dist -File -Filter "*.exe"')) "Product-boundary scan must inspect every EXE in dist."
foreach ($forbiddenBuildToken in @("/define:LAKIS_DEV", "/define:LAKIS_LUKE", "LAKIS_DEV.exe", "LAKIS_DEV_Desktop.exe", "LUKIS_Desktop.exe", "Start_LUKIS_Mobile.cmd")) {
    Require (-not $releaseBuild.Contains($forbiddenBuildToken)) "Public release build must not compile or stage private/development output: $forbiddenBuildToken"
}
Require ($workflow.Contains("LAKIS_Model_Importer.exe#LAKIS_Model_Importer.exe")) "Model Importer release asset is missing."
Require ($workflow.Contains("LAKIS_Updater.exe#LAKIS_Updater.exe")) "Fallback Updater release asset is missing."
foreach ($forbiddenAsset in @("LAKIS_DEV.exe", "LAKIS_DEV_Desktop.exe", "LUKIS_Desktop.exe", "Start_LUKIS_Mobile.cmd")) {
    Require (-not $workflow.Contains($forbiddenAsset)) "Public release workflow must not upload private/development asset: $forbiddenAsset"
}
Require ($rcWorkflow.Contains("build_safe_installer.ps1")) "Private RC workflow must build the candidate artifact set."
Require ($rcWorkflow.Contains("actions/upload-artifact@v4")) "Private RC workflow must preserve the exact built artifact set."
Require ($rcWorkflow.Contains("Test-ThreePartyAuditGate.ps1 -Version")) "Private RC build must require three-party source audit PASS."
Require ($rcWorkflow.Contains("Candidate ref must be a full 40-character commit SHA.")) "Private RC build must be pinned to an exact candidate commit SHA."
Require ($workflow.Contains("Candidate ref must be a full 40-character commit SHA.")) "Public publish must be pinned to an exact approved candidate commit SHA."
Require ($workflow.Contains("actions/download-artifact@v4")) "Public publish must download the exact private RC artifact set."
Require ($workflow.Contains("run-id: `${{ inputs.rc_run_id }}")) "Public publish must bind to an explicit private RC workflow run."
Require (-not $workflow.Contains("build_safe_installer.ps1")) "Public publish must not rebuild artifacts after Private RC approval."
Require ($workflow.Contains("Test-ReleaseApprovalGate.ps1 -Version")) "Public publish must enforce Private RC and explicit owner approval."
Require ($workflow.Contains('buildRecord.source_commit -ne $resolvedCandidate')) "Public publish must bind the Private RC source commit to candidate_ref."
Require (-not [regex]::IsMatch($workflow, '(?m)^\\s*push:\\s*$')) "Public release workflow must not auto-publish from a tag push; approval must happen first."
Require ($workflow.Contains("Release tag does not point to the approved candidate ref.")) "Public release workflow must bind the release tag to the approved candidate ref."
Require ($workflow.Contains("-VerifyRemote -Passes 3")) "Release workflow must remotely verify every file three times."
Require ($workflow.Contains("gh release create `$env:RELEASE_TAG --target `$env:CANDIDATE_REF --draft")) "Release assets must be staged from the approved candidate ref."
Require ($workflow.Contains("-DraftReleaseTag `$env:RELEASE_TAG")) "Draft release assets must be authenticated and hash-verified before publish."
Require ($workflow.Contains("Test-ThreePartyAuditGate.ps1 -Version")) "Public release workflow must re-check the GPT/DeepSeek/Codex three-party audit gate."
Require ($workflow.Contains("Test-InstallerDataSafety.ps1 -InstallerPath (Join-Path `$dist")) "Downloaded Setup artifact must pass the destructive-install regression test."
Require ($workflow.Contains("Test-PublicProductBoundary.ps1 -DistDirectory `$dist")) "Downloaded public artifacts must pass the LAKIS/DEKIS product-boundary scan before upload."
Require ($workflow.Contains("publishedResponse.TrimStart([char]0xFEFF) | ConvertFrom-Json")) "Release identity guard must parse the text/plain GitHub manifest and strip its BOM."
Require ($workflow.Contains('try { $releaseJson = gh release view')) "Missing releases must be handled without terminating the publish job."
$approvalIndex = $workflow.IndexOf("Test-ReleaseApprovalGate.ps1 -Version", [System.StringComparison]::Ordinal)
$draftCreateIndex = $workflow.IndexOf("gh release create `$env:RELEASE_TAG", [System.StringComparison]::Ordinal)
$draftVerifyIndex = $workflow.IndexOf("-DraftReleaseTag `$env:RELEASE_TAG", [System.StringComparison]::Ordinal)
$releasePublishIndex = $workflow.IndexOf("Publish the fully verified release", [System.StringComparison]::Ordinal)
$publishIndex = $workflow.IndexOf("Publish only the verified manifest", [System.StringComparison]::Ordinal)
Require ($approvalIndex -ge 0 -and $draftCreateIndex -gt $approvalIndex -and $draftVerifyIndex -gt $draftCreateIndex -and $releasePublishIndex -gt $draftVerifyIndex -and $publishIndex -gt $releasePublishIndex) "Approval, draft staging, remote verification, release publication, and manifest publication are out of order."

$setup = Read-RepoFile "installer\Setup_LAKIS_Safe.cs"
$uninstaller = Read-RepoFile "installer\LAKIS_Uninstaller.cs"
Require ($uninstaller.Contains('string version="' + $ExpectedVersion + '";')) "Uninstaller fallback version must match VERSION."
Require (-not $setup.Contains("ComfyUI-LAKIS-Light-Control")) "Installer must not install retired Light Control."
Require (-not $setup.Contains("DSINE")) "Installer must not install DSINE source or weights."
foreach ($needle in @(
    ('private const string Revision = "v' + $ExpectedVersion + '"'),
    ('private const string ReleaseVersion = "' + $ExpectedVersion + '"'),
    'LAKIS_Model_Importer.exe',
    'THIRD_PARTY_NOTICES.md',
    'LAKIS_runtime_api_v7.4.json',
    'RealESRGAN_x4plus_anime_6B.pth'
)) {
    Require ($setup.Contains($needle)) "Installer/repair invariant is missing: $needle"
}
Require ([regex]::Matches($setup, 'File\.WriteAllText\(Path\.Combine\(target,"VERSION"\),ReleaseVersion\)').Count -eq 2) "Fresh Setup and Repair must both write the candidate ReleaseVersion."
Require (-not [regex]::IsMatch($setup, 'File\.WriteAllText\(Path\.Combine\(target,"VERSION"\),"\d+\.\d+\.\d+"\)')) "Setup/Repair must never hardcode a semantic VERSION string; use ReleaseVersion."
Require ($setup.Contains("if(IsExistingInstallation(target))throw new InvalidOperationException")) "New install must reject an existing LAKIS installation."
Require ($setup.Contains("if(HasDirectoryEntries(target))throw new InvalidOperationException")) "New install must reject every non-empty destination."
Require ($setup.Contains("circlestone-labs/Anima/resolve/e26179e4b23bcb3a9e91b4ad2961a76ab9644d43/split_files/text_encoders/qwen_3_06b_base.safetensors")) "Qwen encoder must come from the pinned official Anima source."
Require ($setup.Contains("circlestone-labs/Anima/resolve/457fbf842cb86e96af72c65bdd13e3f1c448de84/split_files/diffusion_models/anima-base-v1.0.safetensors")) "Anima base must come from the pinned official source."
Require (-not $setup.Contains("Aitrepreneur/FLX")) "The unlicensed FLX mirror must not remain in the installer."
Require (-not $setup.Contains("p101111/anima")) "The unlicensed Anima mirror must not remain in the installer."

$externalLauncher = Read-RepoFile "src\external_ui\launch_lakis.py"
$externalServer = Read-RepoFile "src\external_ui\serve_ui.py"
$workflowBridge = Read-RepoFile "src\external_ui\workflow_bridge.py"
$publicApp = Read-RepoFile "src\external_ui\app.js"
$advancedSettings = Read-RepoFile "src\external_ui\advanced-node-settings.js"
$desktopLauncher = Read-RepoFile "installer\LAKIS_Launcher.cs"

Require (-not $advancedSettings.Contains("LAKIS DEV")) "Public advanced-settings UI must not expose a LAKIS DEV badge."
Require (-not $workflowBridge.Contains('"LAKIS DEV - Turbo Initial"')) "Public workflow bridge must not expose the legacy DEV node title."
Require ($publicApp.Contains('const PROMPT_STORAGE_KEY = "lakis.promptState.v3";')) "Public prompt state must use the LAKIS storage key."
Require ($publicApp.Contains('const LEGACY_DEKIS_PROMPT_STORAGE_KEY = "lakis.dekis.promptState.v1";')) "Legacy DEKIS prompt state must remain migration-only for user data preservation."
Require ([regex]::Matches($publicApp, 'lakis\.dekis\.promptState\.v1').Count -eq 1) "DEKIS prompt-state key must appear only once as a migration constant."

foreach ($runtimeSource in @($externalLauncher, $externalServer, $workflowBridge)) {
    Require ($runtimeSource.Contains('RUNTIME_ROOT.name.casefold() == "lakis_dev"')) "Development mode must require the actual LAKIS_DEV runtime folder."
}
foreach ($publicEnvReset in @(
    'startInfo.EnvironmentVariables["LAKIS_DEVELOPMENT"] = "0"',
    'startInfo.EnvironmentVariables["LAKIS_LUKE"] = "0"',
    'startInfo.EnvironmentVariables["LAKIS_FULL_TURBO_EXPERIMENT"] = "0"',
    'startInfo.EnvironmentVariables["LAKIS_HALF_RES_FAST_EXPERIMENT"] = "0"',
    'startInfo.EnvironmentVariables["LAKIS_LOCAL_INPAINT_V2"] = "1"',
    'startInfo.EnvironmentVariables["LAKIS_COMFY_PORT"] = "8189"',
    'Path.Combine(root, "LAKIS_Desktop.exe")'
)) {
    Require ($desktopLauncher.Contains($publicEnvReset)) "Public launcher must neutralize inherited development/private environment: $publicEnvReset"
}

Require ($externalLauncher.Contains('"--port", "0"')) "External UI must use an OS-assigned per-launch port."
Require ($externalLauncher.Contains("wait_ui_bridge_ready")) "External UI must complete the identity handshake before opening Desktop."
Require (-not $externalLauncher.Contains("responds(UI_URL)")) "Launcher must never reuse an arbitrary process on the legacy shared UI port."
Require ($externalLauncher.Contains('"LAKIS_COMFYUI_PORT_IN_USE_FAILED"')) "Launcher must fail closed when another backend already owns port 8189."
Require (-not $externalLauncher.Contains('"existing" if responds(COMFY_URL)')) "Launcher must never reuse an arbitrary ComfyUI backend."
Require ($externalServer.Contains("/api/launcher-identity")) "External UI identity endpoint is missing."
Require ($externalServer.Contains("server.server_address[1]")) "External UI must report its actual OS-assigned port."
Require ($desktopLauncher.Contains("WaitForLauncherReady")) "Desktop launcher must wait for its own Python launcher state."
Require (-not $desktopLauncher.Contains("UiResponds()")) "Desktop launcher must not accept an unrelated service on port 8766."
Require ($desktopLauncher.Contains("TryGetReleaseLayout")) "Public Launcher must fetch the version-specific GitHub release layout."
Require ($desktopLauncher.Contains("new FileInfo(path).Length != entry.size")) "Public Launcher must compare managed files by byte size."
Require ($desktopLauncher.Contains("GitHub와 설치 파일의 동일성 검사를 완료하지 못했습니다.")) "Network-failure bypass message is missing."
Require ($desktopLauncher.Contains("동일성 검사 없이 LAKIS를 실행합니다.")) "Network failure must continue without blocking LAKIS."
Require ($desktopLauncher.Contains("ScheduleAutomaticRepair")) "Public Launcher must automatically repair a confirmed version mismatch."
Require ($desktopLauncher.Contains("LAKIS_RepairPack.zip")) "Automatic Repair must use the version-specific RepairPack."
Require ($desktopLauncher.Contains("release-layout-repair.attempt")) "Automatic Repair must prevent retry loops."
Require ($desktopLauncher.Contains("UsesReleaseLayout(root)")) "Pre-v7.5.0 installs must bypass the release-layout contract."
Require ($desktopLauncher.Contains("version >= new Version(7, 5, 0)")) "Release-layout checks must begin at v7.5.0."
Require ($desktopLauncher.Contains("Repair post-check failed")) "Automatic Repair must complete a full post-replacement layout check before restart."
Require ($desktopLauncher.Contains("if((-not [IO.File]::Exists(`$dst))")) "Automatic Repair must replace only missing or size-mismatched files."
Require ($desktopLauncher.Contains("ComfyUI/models/") -and $desktopLauncher.Contains("ComfyUI/user/") -and $desktopLauncher.Contains("ComfyUI/input/") -and $desktopLauncher.Contains("ComfyUI/output/")) "Automatic Repair must protect user-owned trees."
$layoutCheckIndex = $desktopLauncher.IndexOf("TryGetReleaseLayout", [System.StringComparison]::Ordinal)
$updaterLaunchIndex = $desktopLauncher.IndexOf("FileName = updater", [System.StringComparison]::Ordinal)
Require ($layoutCheckIndex -ge 0 -and $updaterLaunchIndex -gt $layoutCheckIndex) "Public Launcher must run version-consistency checking before it can launch Patcher/Updater."
Require ($externalLauncher.Contains("runtime_capability_check")) "Python launcher must verify live ComfyUI runtime capability."
Require ($externalLauncher.Contains("LKS-RUN-1003")) "Runtime capability failure must have a dedicated fail-closed error code."
foreach ($requiredDynamicNode in @("LAKIS_DETAIL", "LAKIS_SCOPE", "LAKIS_VRAM_GATE", "LAKIS_LocalInpaintPrepare", "LAKIS_LocalInpaintComposite")) {
    Require ($externalLauncher.Contains('"' + $requiredDynamicNode + '"')) "Startup capability check is missing required node: $requiredDynamicNode"
}

& (Join-Path $PSScriptRoot "Test-InstallerDataSafety.ps1")
Require ($LASTEXITCODE -eq 0) "Installer behavioral data-safety test failed."
& (Join-Path $PSScriptRoot "Test-RepairDataSafety.ps1")
Require ($LASTEXITCODE -eq 0) "Repair data-preservation audit failed."

$jsonPaths = @(
    "workflows\LAKIS_runtime_api_v7.4.json",
    "workflows\LAKIS_runtime_visual_v7.4.json",
    "workflows\LAKIS_custom_v7.4_editable.json"
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
    [System.IO.Path]::GetFullPath((Join-Path $repo "..\LAKIS_KREA2_PORTABLE\python_embeded\python.exe")),
    [System.IO.Path]::GetFullPath((Join-Path $repo "..\release\first-user-test\install\python_embeded\python.exe")),
    [System.IO.Path]::GetFullPath((Join-Path $repo "..\..\..\release\first-user-test\install\python_embeded\python.exe")),
    [System.IO.Path]::GetFullPath((Join-Path $repo "..\..\python_embeded\python.exe"))
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
& $python (Join-Path $repo "installer\tests\test_public_product_boundary.py")
Require ($LASTEXITCODE -eq 0) "Public LAKIS / DEKIS/LUKIS product-boundary regression failed."
& $python (Join-Path $repo "installer\tests\test_release_layout.py")
Require ($LASTEXITCODE -eq 0) "Release layout / RepairPack regression failed."
& $python (Join-Path $repo "installer\tests\test_rc_overrides.py")
Require ($LASTEXITCODE -eq 0) "Private RC override contract regression failed."
Push-Location (Join-Path $repo "tools\rc_patcher")
try {
    & $python ".\test_rc_patcher.py"
    Require ($LASTEXITCODE -eq 0) "Tester-only RC patcher regression failed."
} finally { Pop-Location }
& $python (Join-Path $repo "tools\rc_patcher\test_private_rc_server.py")
Require ($LASTEXITCODE -eq 0) "Tester-only Private RC server regression failed."
& $python (Join-Path $repo "installer\tests\test_error_codes.py")
Require ($LASTEXITCODE -eq 0) "Error-code and model-compatibility regression failed."
& $python (Join-Path $repo "installer\tests\test_release_gates.py")
Require ($LASTEXITCODE -eq 0) "Three-party and release-approval fail-closed regression failed."
foreach ($jsonFile in $jsonFiles) {
    & $python -m json.tool $jsonFile 1>$null
    Require ($LASTEXITCODE -eq 0) "Invalid packaged workflow JSON: $jsonFile"
}
foreach ($workflowPath in $jsonPaths) {
    $workflowFile = Join-Path $repo $workflowPath
    $workflowJson = Get-Content -Raw -LiteralPath $workflowFile
    Require ($workflowJson.Contains('LAKIS_LocalInpaintPrepare')) "Local Inpaint prepare node missing: $workflowFile"
    Require ($workflowJson.Contains('LAKIS_LocalInpaintComposite')) "Local Inpaint composite node missing: $workflowFile"
    Require (-not $workflowJson.Contains('DEKIS_LocalInpaint')) "DEKIS node name leaked into public workflow: $workflowFile"
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
    "installer\Test-PublicProductBoundary.ps1",
    "installer\New-ReleaseLayout.ps1",
    "installer\New-ReleaseAuditFingerprint.ps1",
    "installer\Test-ThreePartyAuditGate.ps1",
    "installer\Test-ReleaseApprovalGate.ps1",
    ".github\workflows\prepare-private-rc.yml",
    "THREE_PARTY_AUDIT_POLICY.md",
    "installer\tests\test_installation_isolation.py",
    "installer\tests\test_ui_state_scoping.py",
    "installer\tests\test_public_product_boundary.py",
    "installer\tests\test_release_layout.py",
    "installer\tests\test_rc_overrides.py",
    "installer\tests\test_release_gates.py",
    "tools\rc_patcher\serve_private_rc.py",
    "tools\rc_patcher\test_private_rc_server.py",
    "RELEASE_REGRESSION_CHECKLIST.md"
)) {
    Require (Test-Path -LiteralPath (Join-Path $repo $required) -PathType Leaf) "Missing release component: $required"
}

& $python (Join-Path $repo "installer\tests\test_release_component_contract.py")
Require ($LASTEXITCODE -eq 0) "Recovery release component contract failed."
Write-Output "RELEASE_REGRESSION_GATE_OK version=$ExpectedVersion"
