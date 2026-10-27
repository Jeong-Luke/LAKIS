param([string]$PythonExecutable = "python")
$ErrorActionPreference = "Stop"
$builder = Join-Path $PSScriptRoot "..\build_safe_installer.ps1"
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($builder, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$definition = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -ceq "New-InstallerBuildStage"
}, $true)
$allocate = $definition.Body.GetScriptBlock()
$parent = & $allocate -Parent ([IO.Path]::GetTempPath()) -PythonExecutable $PythonExecutable
$first = & $allocate -Parent $parent -PythonExecutable $PythonExecutable
$sentinel = Join-Path $first "runtime-installer-manifest.json"
[IO.File]::WriteAllText($sentinel, "preserved first build")
$second = & $allocate -Parent $parent -PythonExecutable $PythonExecutable
if ($first -eq $second -or -not [IO.Directory]::Exists($second)) {
    throw "Build stages were not independently allocated."
}
if ([IO.File]::ReadAllText($sentinel) -cne "preserved first build") {
    throw "A previous build was modified."
}
if ([IO.Directory]::GetFileSystemEntries($second).Length -ne 0) {
    throw "The second build directory is not empty."
}
[ordered]@{
    status="REPEATED_INSTALLER_STAGE_ISOLATION_PASS"
    first=$first
    second=$second
    previous_build_preserved=$true
} | ConvertTo-Json
