[CmdletBinding()]
param([string]$ConfigPath='', [ValidatePattern('^[a-zA-Z0-9_-]{1,100}$')][string]$RunId='', [switch]$Simulation)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
if(!$ConfigPath){$ConfigPath=Join-Path $PSScriptRoot 'config\experiment.json'}
$temp='';$code=1
try {
    $resolved=(Resolve-Path -LiteralPath $ConfigPath).Path
    $cfg=Get-Content -LiteralPath $resolved -Raw -Encoding UTF8 | ConvertFrom-Json
    $cfg.scope.enabled=$false
    $temp=Join-Path (Split-Path $resolved -Parent) ('fan-mode-'+[Guid]::NewGuid().ToString('N')+'.json')
    $cfg|ConvertTo-Json -Depth 16|Set-Content -LiteralPath $temp -Encoding UTF8
    $engine=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $argsList=@('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'run-experiment.ps1'),'-ConfigPath',$temp)
    if($RunId){$argsList+=@('-RunId',$RunId)}
    if($Simulation){$argsList+='-Simulation'}
    & $engine @argsList
    $code=$LASTEXITCODE
} catch {[Console]::Error.WriteLine($_.Exception.Message);$code=1}
finally {if($temp -and (Test-Path -LiteralPath $temp)){try{[IO.File]::Delete($temp)}catch{[Console]::Error.WriteLine($_.Exception.Message);$code=1}}}
exit $code
