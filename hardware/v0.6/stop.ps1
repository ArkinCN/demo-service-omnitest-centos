[CmdletBinding()]
param([Parameter(Mandatory=$true)][ValidatePattern('^[a-zA-Z0-9_-]{1,100}$')][string]$RunId,[string]$ConfigPath='', [string]$RunDirectory='', [ValidateRange(0,120)][int]$WaitSeconds=30)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
try{
    if($RunDirectory){$directory=[IO.Path]::GetFullPath($RunDirectory);if((Split-Path $directory -Leaf) -cne $RunId){throw 'RunDirectory leaf must match RunId.'}}
    else{
    if(!$ConfigPath){$ConfigPath=Join-Path $PSScriptRoot 'config\experiment.json'}
    # Stop depends only on the output path, so editing wiring flags never blocks cleanup.
    $resolved=(Resolve-Path -LiteralPath $ConfigPath).Path;$cfg=Get-Content -LiteralPath $resolved -Raw -Encoding UTF8|ConvertFrom-Json
    $root=if([IO.Path]::IsPathRooted($cfg.output.root)){[IO.Path]::GetFullPath($cfg.output.root)}else{[IO.Path]::GetFullPath((Join-Path (Split-Path $resolved -Parent) $cfg.output.root))};$directory=Join-Path $root $RunId
    }
    if(!(Test-Path -LiteralPath $directory -PathType Container)){throw 'Unknown runId.'}
    $summaryPath=Join-Path $directory 'summary.json'
    if(!(Test-Path -LiteralPath $summaryPath)){[IO.File]::WriteAllText((Join-Path $directory 'stop.request'),[DateTimeOffset]::UtcNow.ToString('o'))}
    $clock=[Diagnostics.Stopwatch]::StartNew();while(!(Test-Path -LiteralPath $summaryPath) -and $clock.Elapsed.TotalSeconds -lt $WaitSeconds){Start-Sleep -Milliseconds 100}
    if(Test-Path -LiteralPath $summaryPath){$summary=Get-Content -LiteralPath $summaryPath -Raw -Encoding UTF8|ConvertFrom-Json;[ordered]@{schemaVersion='1.0';action='stop';status='finished';runId=$RunId;summary=$summary}|ConvertTo-Json -Depth 12 -Compress;if($summary.failed){exit 1}}
    else{[ordered]@{schemaVersion='1.0';action='stop';status='requested_unconfirmed';runId=$RunId;physicalState='unknown until cleanup ACK; never infer stop from process exit';summaryPath=$summaryPath}|ConvertTo-Json -Compress;exit 2}
}catch{[Console]::Error.WriteLine($_.Exception.Message);exit 1}
