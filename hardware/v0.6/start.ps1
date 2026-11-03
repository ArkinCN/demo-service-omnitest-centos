[CmdletBinding()]
param([string]$ConfigPath='', [ValidatePattern('^[a-zA-Z0-9_-]{1,100}$')][string]$RunId='', [switch]$Simulation)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
try{
    Import-Module (Join-Path $PSScriptRoot 'src\Runtime.psm1') -Force
    if(!$ConfigPath){$ConfigPath=Join-Path $PSScriptRoot 'config\experiment.json'};$loaded=Read-ExperimentConfig $ConfigPath
    if(!$RunId){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss_fff')+'_'+[Guid]::NewGuid().ToString('N').Substring(0,8)}
    $directory=Join-Path $loaded.OutputRoot $RunId;if(Test-Path -LiteralPath $directory){throw 'Run directory already exists.'};[void](New-Item -ItemType Directory -Path $directory)
    $token=[Guid]::NewGuid().ToString('N')
    $claim=[IO.File]::Open((Join-Path $directory 'run.claim'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try{$bytes=[Text.Encoding]::ASCII.GetBytes($token);$claim.Write($bytes,0,$bytes.Length)}finally{$claim.Dispose()}
    # The child reads an immutable snapshot with an absolute root, never the changing user file.
    $loaded.Config.output.root=$loaded.OutputRoot;$snapshot=Join-Path $directory 'config.snapshot.json'
    $loaded.Config|ConvertTo-Json -Depth 16|Set-Content -LiteralPath $snapshot -Encoding UTF8
    $runner=Join-Path $PSScriptRoot 'run-experiment.ps1'
    $command="& '"+$runner.Replace("'","''")+"' -ConfigPath '"+$snapshot.Replace("'","''")+"' -RunId '"+$RunId+"' -ClaimToken '"+$token+"'";if($Simulation){$command+=' -Simulation'}
    $encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
    $exe=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $process=Start-Process -FilePath $exe -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand',$encoded) -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $directory 'stdout.jsonl') -RedirectStandardError (Join-Path $directory 'stderr.log')
    # Returning means launched; caller follows events/state to learn readiness and failure.
    [ordered]@{schemaVersion='1.0';action='start';status='launched';runId=$RunId;processId=$process.Id;directory=$directory;eventsPath=(Join-Path $directory 'events.jsonl');summaryPath=(Join-Path $directory 'summary.json');stopRequestPath=(Join-Path $directory 'stop.request')}|ConvertTo-Json -Compress
}catch{[Console]::Error.WriteLine($_.Exception.Message);exit 1}
