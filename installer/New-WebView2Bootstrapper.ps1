param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$output = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $output | Out-Null
$path = Join-Path $output 'MicrosoftEdgeWebview2Setup.exe'
# Resolve the official link once at build time. End-user CMD installation uses
# this resolved URL plus the reviewed SHA/size, never unverified latest bytes.
$response = Invoke-WebRequest -UseBasicParsing 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $path -PassThru
$url = [string]$response.BaseResponse.ResponseUri.AbsoluteUri
if (-not $url.StartsWith('https://') -or $url -eq 'https://go.microsoft.com/fwlink/p/?LinkId=2124703') {
    throw 'WebView2 bootstrapper did not resolve to a fixed HTTPS download URL.'
}
$signature = Get-AuthenticodeSignature -LiteralPath $path
if ($signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate -or
    $signature.SignerCertificate.GetNameInfo([Security.Cryptography.X509Certificates.X509NameType]::SimpleName,$false) -cne 'Microsoft Corporation') {
    throw 'WebView2 bootstrapper Microsoft Authenticode validation failed.'
}
$record = [ordered]@{
    name='MicrosoftEdgeWebview2Setup.exe'
    url=$url
    sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
    bytes=(Get-Item -LiteralPath $path).Length
}
[IO.File]::WriteAllText((Join-Path $output 'webview2-bootstrapper.json'),($record | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
Write-Output 'WEBVIEW2_BOOTSTRAPPER_PINNED_MICROSOFT_SIGNATURE_PASS'
