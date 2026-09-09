param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Repository = "Jeong-Luke/LAKIS",
    [string]$DistDirectory = "",
    [string]$OutputPath = "",
    [switch]$UseLocalWorkingTreeHashes
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$workspace = (Resolve-Path (Join-Path $repo "..\..")).Path
$dist = if ([string]::IsNullOrWhiteSpace($DistDirectory)) {
    Join-Path $workspace "dist"
} else {
    [System.IO.Path]::GetFullPath($DistDirectory)
}
$tag = "v$Version"
$releaseBase = "https://github.com/$Repository/releases/download/$tag"
$rawBase = "https://raw.githubusercontent.com/$Repository/$tag"

$files = [System.Collections.Generic.List[object]]::new()
function Add-UpdateFile([string]$InstallPath, [string]$SourcePath, [string]$Url) {
    if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
        throw "Update source is missing: $SourcePath"
    }
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $SourcePath).Hash
    # GitHub serves repository text with the line endings stored in Git. A
    # Windows working tree can contain CRLF bytes for the same LF-tagged file,
    # so release manifests must hash the published bytes by default.
    if (-not $UseLocalWorkingTreeHashes -and $Url.StartsWith($rawBase, [System.StringComparison]::OrdinalIgnoreCase)) {
        $temporary = Join-Path ([System.IO.Path]::GetTempPath()) ("lakis-tag-hash-" + [guid]::NewGuid().ToString("N"))
        try {
            Invoke-WebRequest -UseBasicParsing -Headers @{ "User-Agent" = "LAKIS-Manifest/$Version" } `
                -Uri ($Url + "?manifest=" + [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()) -OutFile $temporary
            $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $temporary).Hash
        }
        finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force } }
    }
    $files.Add([ordered]@{
        path = $InstallPath.Replace('\', '/')
        url = $Url
        sha256 = $hash
    })
}

foreach ($name in @(
    "LAKIS.exe", "LAKIS_Patcher.exe", "LAKIS_Updater.exe", "LAKIS_Desktop.exe", "LAKIS_Model_Importer.exe", "Uninstall_LAKIS.exe",
    "Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll", "WebView2Loader.dll"
)) {
    Add-UpdateFile $name (Join-Path $dist $name) "$releaseBase/$name"
}

# Legal notices are application-owned release files. Existing installations
# must receive the same notices as clean installs.
foreach ($name in @("LICENSE.md", "THIRD_PARTY_NOTICES.md")) {
    Add-UpdateFile $name (Join-Path $repo $name) "$rawBase/$name"
}
$licenceRoot = Join-Path $repo "third_party_licenses"
Get-ChildItem -LiteralPath $licenceRoot -File -Recurse |
    Sort-Object FullName |
    ForEach-Object {
        $relative = $_.FullName.Substring($licenceRoot.Length).TrimStart('\').Replace('\', '/')
        Add-UpdateFile "third_party_licenses/$relative" $_.FullName "$rawBase/third_party_licenses/$relative"
    }

# Never put a model path in the update manifest. Updaters shipped with 7.2.2
# and 7.2.3 correctly protect the whole ComfyUI/models tree and would reject
# the update before the new patcher could replace them. The UI downloads
# the permissively licensed RealESRGAN default on selection and verifies its
# pinned SHA-256 instead.

# The entire external UI is an atomic runtime component. Selecting individual
# files caused workflow_bridge.py to remain on an older release.
$externalRoot = Join-Path $repo "src\external_ui"
Get-ChildItem -LiteralPath $externalRoot -File -Recurse |
    Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and $_.Extension -ne '.pyc' } |
    Sort-Object FullName |
    ForEach-Object {
        $relative = $_.FullName.Substring($externalRoot.Length).TrimStart('\').Replace('\', '/')
        Add-UpdateFile "ComfyUI/LAKIS/external_ui/$relative" $_.FullName "$rawBase/src/external_ui/$relative"
    }
Add-UpdateFile "ComfyUI/LAKIS/STOP_AUTOMATION" `
    (Join-Path $repo "resources\STOP_AUTOMATION") "$rawBase/resources/STOP_AUTOMATION"

# Ship the DSINE-free lighting stub to existing users as well as clean
# installs. The directory is LAKIS-owned; cached third-party weights and all
# other user/custom-node data remain untouched.
$lightControlRoot = Join-Path $repo "src\custom_nodes\ComfyUI-LAKIS-Light-Control"
Get-ChildItem -LiteralPath $lightControlRoot -File -Recurse |
    Where-Object {
        $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and
        $_.Extension -ne '.pyc' -and
        $_.Name -ne 'TEST_NOTES.txt'
    } |
    Sort-Object FullName |
    ForEach-Object {
        $relative = $_.FullName.Substring($lightControlRoot.Length).TrimStart('\').Replace('\', '/')
        Add-UpdateFile "ComfyUI/custom_nodes/ComfyUI-LAKIS-Light-Control/$relative" $_.FullName `
            "$rawBase/src/custom_nodes/ComfyUI-LAKIS-Light-Control/$relative"
    }

# LAKIS_SCOPE is an independent LAKIS-owned custom node. Existing users need
# the complete package; user models and third-party custom nodes are untouched.
$scopeRoot = Join-Path $repo "src\custom_nodes\ComfyUI-LAKIS-Fast-Refiner"
Get-ChildItem -LiteralPath $scopeRoot -File -Recurse |
    Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and $_.Extension -ne '.pyc' } |
    Sort-Object FullName |
    ForEach-Object {
        $relative = $_.FullName.Substring($scopeRoot.Length).TrimStart('\').Replace('\', '/')
        Add-UpdateFile "ComfyUI/custom_nodes/ComfyUI-LAKIS-Fast-Refiner/$relative" $_.FullName `
            "$rawBase/src/custom_nodes/ComfyUI-LAKIS-Fast-Refiner/$relative"
    }

# Update complete LAKIS node packages so existing installations receive the
# same source, licence, notice and documentation files as clean installs.
foreach ($nodeName in @(
    "ComfyUI-KR-Camera-Control",
    "ComfyUI-KR-Camera-PromptStudio-Bridge",
    "ComfyUI-LAKIS-Detail"
)) {
    $nodeRoot = Join-Path $repo "src\custom_nodes\$nodeName"
    Get-ChildItem -LiteralPath $nodeRoot -File -Recurse |
        Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and $_.Extension -ne '.pyc' } |
        Sort-Object FullName |
        ForEach-Object {
            $relative = $_.FullName.Substring($nodeRoot.Length).TrimStart('\').Replace('\', '/')
            Add-UpdateFile "ComfyUI/custom_nodes/$nodeName/$relative" $_.FullName `
                "$rawBase/src/custom_nodes/$nodeName/$relative"
        }
}

# The installed Spectrum package already retains its upstream MIT LICENSE.
# Deliver LAKIS's prominent modification notice beside the patched files.
Add-UpdateFile "ComfyUI/custom_nodes/comfyui-spectrum-ksampler/LAKIS_MODIFICATIONS.md" `
    (Join-Path $repo "patches\ComfyUI-Spectrum-KSampler\NOTICE.md") `
    "$rawBase/patches/ComfyUI-Spectrum-KSampler/NOTICE.md"

# This is application-owned and safe to update. The editable workflow under
# ComfyUI/user is deliberately excluded because it contains user changes.
foreach ($runtimeName in @(
    "LAKIS_runtime_api_v7.1.json",
    "LAKIS_runtime_visual_v7.3.json",
    "LAKIS_custom_v7.3_editable.json"
)) {
    Add-UpdateFile "ComfyUI/LAKIS/workflows/$runtimeName" `
        (Join-Path $repo "workflows\$runtimeName") "$rawBase/workflows/$runtimeName"
}

$releaseNotesBase64 = "TEFLSVMgU3R1ZGlvIHY3LjMuNCDrsLDtj6wg7JmE66OMCuydtOyghCDrsoTsoIQ6IHY3LjMuMwrstZzsi6Ag67KE7KCEOiB2Ny4zLjQK67Cw7Y+sIOyLnOqwgTogMjAyNuuFhCA57JuUIDnsnbwg7Jik7ZuEIDEx7IucIDXrtoQoS1NUKQoK7KO87JqUIOyXheuNsOydtO2KuDoKCuyDiOuhnOyatCDigJhMQUtJUyDstZzsoIHtmZTigJkg66qo65OcIOy2lOqwgApMQUtJUyDstZzsoIHtmZTrpbwg7Zmc7ISx7ZmU7ZWcIOyDge2DnOyXkOyEnCBERVRBSUwg66qo65Oc66W8IOyCrOyaqe2VmOuptCDsnpDssrQg6rCc67Cc7ZWcIOyWvOq1tMK364iIIOuztOyglSDquLDriqUg4oCYTEFLSVNfREVUQUlM4oCZ6rO8IOyXheyKpOy8gOydvCDquLDriqUg4oCYTEFLSVNfU0NPUEXigJnqsIAg7KCB7Jqp65Cp64uI64ukLiDstZzsoIHtmZTrpbwg64GE66m0IOq4sOyhtCBGQVNUIOuwjyDroIjqsbDsi5wgREVUQUlMIOuwqeyLneydtCDqt7jrjIDroZwg7Jyg7KeA65Cp64uI64ukLgoK64uk7J24IOydtOuvuOyngCDsspjrpqwg6rCc7ISgCuuRkCDrqoUg7J207IOB7J2YIOyduOusvOydtCDrk7HsnqXtlZjripQg7J2066+47KeA7JeQ7IScIOyWvOq1tCDrs7TsoJUg7JiB7Jet7J20IOyEnOuhnCDqsrnsuZjsp4Ag7JWK64+E66GdIOyymOumrCDrsKnsi53snYQg6rCc7ISg7ZaI7Iq164uI64ukLiDsnbjrrLzrs4Qg7Ja86rW0IOyYgeyXreydhCDrtoTrpqztlbQg67aI7ZWE7JqU7ZWcIOykkeuztSDsspjrpqzsmYAg7LqQ66at7YSwIOqwhCDtirnsp5Ug7Zi87ZWp7J2EIOykhOyYgOyKteuLiOuLpC4KCkxBS0lTX1NDT1BFIOyDneyEsSDsoJXssrQg7Jik7J24IOusuOygnCDsiJjsoJUK7JeF7Iqk7LyA7J28IOyXsOyCsCDspJEg7KeE7ZaJIOygleuztOqwgCDsnqDsi5wg7ZGc7Iuc65CY7KeAIOyViuuKlCDsg4HtmansnYQg7Iuk7KCcIOyYpOulmOuhnCDsnpjrqrsg7YyQ64uo7ZWY642YIOusuOygnOulvCDsiJjsoJXtlojsirXri4jri6QuIOydtOygnCBDb21meVVJIOyLpO2WiSDtgZDsmYAg7J6R7JeFIOydtOugpeydhCDri6Tsi5wg7ZmV7J247ZWY7JesIOyekeyXheydtCDsp4Ttlokg7KSR7J2066m0IOyDneyEseydhCDspJHri6jtlZjsp4Ag7JWK6rOgIOqzhOyGjSDquLDri6Trpr3ri4jri6QuCgrsg53shLEg7JWI7KCV7ISx6rO8IOuplOuqqOumrCDsspjrpqwg6rCc7ISgCuuFuOuTnCDsi6Ttlokg7KSRIOqwleygnCDrqZTrqqjrpqwg7KCV66as6rCAIOuwnOyDne2VmOyngCDslYrrj4TroZ0g7KCV66asIOyLnOygkOydhCDsobDsoJXtlojsirXri4jri6QuIFZSQU0g6rK96rOEIOynhOuLqOqzvCDsmKTrpZgg67O06rOgIOygleuztOuPhCDrs7TqsJXtlZjsl6wg66y47KCcIOuwnOyDnSDsnITsuZjrpbwg642U7JqxIOygle2Zle2VmOqyjCDtmZXsnbjtlaAg7IiYIOyeiOyKteuLiOuLpC4KCuyduO2EsO2OmOydtOyKpCDrsI8g7JuM7YGs7ZSM66GcIOqwnOyEoApMQUtJUyDstZzsoIHtmZQg7Iqk7JyE7LmYLCDqtazrj4Qg7ISk7KCVIOuFuOu4jCDrsI8g7ZSE66Gs7ZSE7Yq4IOyeheugpey5uOuzhCBPTi9PRkYg7Iqk7JyE7LmY6rCAIOygleyDgeyggeycvOuhnCDsnpHrj5ntlZjrj4TroZ0g7IiY7KCV7ZaI7Iq164uI64ukLgoK65287J207ISg7IqkIOuwjyDsoIDsnpHqtowg6rOg7KeAIOuztOqwlQpMQUtJU19ERVRBSUzqs7wg7Y+s7ZWo65CcIOy7pOyKpO2FgCDrhbjrk5wg67CPIOyngeygkSDsnZjsobTshLHsnZgg65287J207ISg7IqkIOusuOyEnOulvCDrs7TqsJXtlojsirXri4jri6QuCgrigLsg7LKY66asIOyLnOqwhOqzvCDrqZTrqqjrpqwg7IKs7Jqp65+J7J2AIOq3uOuemO2Uvey5tOuTnCwg7ZW07IOB64+ELCDssrTtgaztj6zsnbjtirgsIExvUkEg6rWs7ISxIOuwjyDsnbTrr7jsp4Ag7IaNIOyduOusvCDsiJjsl5Ag65Sw6528IOuLrOudvOyniCDsiJgg7J6I7Iq164uI64ukLgoK7Jik66WY7L2U65Oc67OEIOybkOyduOqzvCDrjIDsspgg67Cp67KV7J2AIOyVhOuemCDrp4Htgazsl5DshJwg7ZmV7J247ZWgIOyImCDsnojsirXri4jri6QuCmh0dHBzOi8vZ2l0aHViLmNvbS9KZW9uZy1MdWtlL0xBS0lTL2Jsb2IvbWFpbi9FUlJPUl9DT0RFUy5tZAoK6rOg7LOQ7KeA7KeAIOyViuuKlCDsmKTrpZjqsIAg67Cc7IOd7ZWY66m0IOyYpOulmOywveydmCDigJjsmKTrpZgg7KCV67O0IOuzteyCrO2VmOq4sOKAmeulvCDriITrpbgg7ZuEIOuzteyCrOuQnCDrgrTsmqnsnYQg7KCE64us7ZW0IOyjvOyEuOyalC4KCuq4sOyhtCDsgqzsmqnsnpDripQg7Iuk7ZaJIOykkSDrgpjtg4DrgpjripQg7JeF642w7J207Yq4IO2ZleyduCDssL3sl5DshJwg4oCY7JeF642w7J207Yq44oCZ66W8IOuIhOultOyLnOuptCDrkKnri4jri6QgOik="
$releaseNotesBase64 = "TEFLSVMgU3R1ZGlvIHY3LjMuNSDquLTquIkg7Yyo7LmYCgrqtazrj4Qg7ISk7KCVIOyggOyepSDrsI8g67O17JuQIOyImOyglQrsubTrqZTrnbwg7KKM7ZGc7JmAIOq1rOuPhCDshKTsoJUgT04vT0ZGIOyDge2DnOqwgCDsl4XrjbDsnbTtirgg65iQ64qUIOyerOyLnOyekSDtm4Qg7LSI6riw7ZmU65CY642YIOusuOygnOulvCDsiJjsoJXtlojsirXri4jri6QuIOy6lOuyhOyKpCwg7ZygLCDtgqTrs7Trk5wsIOyKrOudvOydtOuNlCwg7Iir7J6QIOyeheugpSwg7ZSE66as7IWL6rO8IOy0iOq4sO2ZlCDsobDsnpHsnbQg66qo65GQIOyggOyepeuQqeuLiOuLpC4KCkxBS0lTIERFVEFJTCDrsLDsp4Ag7IiY7KCVCkxBS0lTIOy1nOygge2ZlOulvCDsvKAgREVUQUlMIOqysOqzvOqwgCBGQVNU66GcIOyemOuquyDtkZzsi5zrkJjrjZgg66y47KCc66W8IOyImOygle2WiOyKteuLiOuLpC4g7IOd7ISxIOykkSwg7JmE66OMIO2bhCwg7J2066ClIOydtOuvuOyngCDsnqzshKDtg50g7IucIOuqqOuRkCBMQUtJUyBERVRBSUzroZwg7ZGc7Iuc65Cp64uI64ukLgoK7IKs7Jqp7J6QIOuqqOuNuCwgTG9SQSwg7ZSE66Gc7ZSE7Yq4LCDsm4ztgaztlIzroZwg67CPIOyDneyEsSDsnbTrr7jsp4DripQg7JeF642w7J207Yq4IOyLnCDrs7TsobTrkKnri4jri6Qu"
$releaseNotes = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($releaseNotesBase64)).Replace("\n", [Environment]::NewLine)
$manifest = [ordered]@{
    version = $Version
    release_notes = $releaseNotes
    files = $files
    delete = @()
}
$output = if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    Join-Path $repo "manifests\update-latest.json"
} else {
    [System.IO.Path]::GetFullPath($OutputPath)
}
$outputDirectory = Split-Path -Parent $output
if (-not [string]::IsNullOrWhiteSpace($outputDirectory)) {
    New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $output -Encoding utf8
Write-Output "MANIFEST=$output"
Write-Output "FILES=$($files.Count)"
