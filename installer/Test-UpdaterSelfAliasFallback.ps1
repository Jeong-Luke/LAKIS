param([Parameter(Mandatory=$true)][string]$Patcher,[Parameter(Mandatory=$true)][string]$Updater)
$ErrorActionPreference='Stop'
function Hash([string]$p){(Get-FileHash -Algorithm SHA256 -LiteralPath $p).Hash}
if((Hash $Patcher)-ne(Hash $Updater)){throw 'Candidate Patcher/Updater hashes differ.'}
$candidateHash=Hash $Patcher
$work=Join-Path $env:TEMP ('lakis-self-alias-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force $work|Out-Null
$stubSource=Join-Path $work 'SleepStub.cs';$stub=Join-Path $work 'old.exe'
'using System;using System.Threading;class P{static void Main(){Thread.Sleep(60000);}}'|Set-Content -LiteralPath $stubSource -Encoding ascii
& "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /target:winexe ("/out:"+$stub) $stubSource
if($LASTEXITCODE){throw 'SleepStub compile failed.'}
function Fixture([string]$name){$d=Join-Path $work $name;New-Item -ItemType Directory -Force $d|Out-Null;Copy-Item $Patcher (Join-Path $d 'helper.exe');return $d}
function Run-Success([string]$root,[string[]]$arguments,[string]$target){$p=Start-Process (Join-Path $root 'helper.exe') -ArgumentList $arguments -PassThru;$p.WaitForExit(15000)|Out-Null;if(!$p.HasExited){$p.Kill();throw "$target helper hung"};if((Get-Content -Raw (Join-Path $root 'VERSION')).Trim() -ne '9.9.9'){throw "$target VERSION missing"};if((Hash (Join-Path $root $target)) -ne $candidateHash){throw "$target was not replaced"}}
function Run-Reject([string]$root,[string[]]$arguments){$beforeP=Hash (Join-Path $root 'LAKIS_Patcher.exe');$beforeU=Hash (Join-Path $root 'LAKIS_Updater.exe');$p=Start-Process (Join-Path $root 'helper.exe') -ArgumentList $arguments -PassThru;Start-Sleep -Seconds 2;if($p.HasExited){throw 'Expected fail-closed dialog was not observed.'};$p.Kill();$p.WaitForExit();if(Test-Path (Join-Path $root 'VERSION')){throw 'Rejected case wrote VERSION.'};if((Hash (Join-Path $root 'LAKIS_Patcher.exe')) -ne $beforeP -or (Hash (Join-Path $root 'LAKIS_Updater.exe')) -ne $beforeU){throw 'Rejected case changed aliases.'}}
$results=@()
foreach($alias in @('LAKIS_Patcher.exe','LAKIS_Updater.exe')){$d=Fixture ('explicit-'+$alias);Copy-Item $stub (Join-Path $d 'LAKIS_Patcher.exe');Copy-Item $stub (Join-Path $d 'LAKIS_Updater.exe');Run-Success $d @('--finish-self-update',$d,'9.9.9','0',('--self-name='+$alias)) $alias;$results+="explicit $alias PASS"}
foreach($alias in @('LAKIS_Patcher.exe','LAKIS_Updater.exe')){$d=Fixture ('alive-'+$alias);Copy-Item $stub (Join-Path $d 'LAKIS_Patcher.exe');Copy-Item $stub (Join-Path $d 'LAKIS_Updater.exe');$old=Start-Process (Join-Path $d $alias) -PassThru;Run-Success $d @('--finish-self-update',$d,'9.9.9',[string]$old.Id) $alias;$results+="legacy alive $alias PASS"}
$d=Fixture 'exited-patcher-old';Copy-Item $stub (Join-Path $d 'LAKIS_Patcher.exe');Copy-Item $Patcher (Join-Path $d 'LAKIS_Updater.exe');$old=Start-Process $stub -PassThru;$pidValue=$old.Id;$old.Kill();$old.WaitForExit();Run-Success $d @('--finish-self-update',$d,'9.9.9',[string]$pidValue) 'LAKIS_Patcher.exe';$results+='legacy exited Patcher old PASS'
$d=Fixture 'exited-updater-old';Copy-Item $Patcher (Join-Path $d 'LAKIS_Patcher.exe');Copy-Item $stub (Join-Path $d 'LAKIS_Updater.exe');$old=Start-Process $stub -PassThru;$pidValue=$old.Id;$old.Kill();$old.WaitForExit();Run-Success $d @('--finish-self-update',$d,'9.9.9',[string]$pidValue) 'LAKIS_Updater.exe';$results+='legacy exited Updater old PASS'
$d=Fixture 'both-old';Copy-Item $stub (Join-Path $d 'LAKIS_Patcher.exe');Copy-Item $stub (Join-Path $d 'LAKIS_Updater.exe');Run-Reject $d @('--finish-self-update',$d,'9.9.9','2147483646');$results+='both old reject PASS'
$d=Fixture 'unexpected-path';Copy-Item $stub (Join-Path $d 'LAKIS_Patcher.exe');Copy-Item $stub (Join-Path $d 'LAKIS_Updater.exe');$outside=Start-Process $stub -PassThru;try{Run-Reject $d @('--finish-self-update',$d,'9.9.9',[string]$outside.Id)}finally{if(!$outside.HasExited){$outside.Kill()}};$results+='unexpected path reject PASS'
$results
Remove-Item -LiteralPath $work -Recurse -Force
