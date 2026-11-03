$ErrorActionPreference='Stop'
$base=Split-Path $PSScriptRoot -Parent
$folder=Join-Path $PSScriptRoot ('fixes_'+(Get-Date -Format 'yyyyMMdd_HHmmss_fff'));[void](New-Item -ItemType Directory -Path $folder)
function Assert([bool]$Value,[string]$Message){if(!$Value){throw $Message}}
Import-Module (Join-Path $base 'src\Runtime.psm1') -Force
$cfg=Get-Content -LiteralPath (Join-Path $base 'config\experiment.json') -Raw -Encoding UTF8|ConvertFrom-Json
$cfg.scope.enabled=$false;$cfg.serial.port='COM9998';$cfg.experiment.cycles=0;$cfg.experiment.holdSeconds=0.5;$cfg.experiment.settleSeconds=0;$cfg.output.root='runs'
$path=Join-Path $folder 'config.json';$cfg.experiment.dutiesPercent=$null;$cfg|ConvertTo-Json -Depth 16|Set-Content -LiteralPath $path -Encoding UTF8
$rejected=$false;try{[void](Read-ExperimentConfig $path)}catch{$rejected=$true};Assert $rejected 'Null duty sequence accepted.';'PASS null duty array rejected before opening hardware'
$cfg.experiment.dutiesPercent=@(30,50,70,100)
$unicodeRoot='runs_'+[char]0x4E2D+[char]0x6587;$cfg.output.root=$unicodeRoot
[IO.File]::WriteAllText($path,($cfg|ConvertTo-Json -Depth 16),(New-Object Text.UTF8Encoding($false)))
$loaded=Read-ExperimentConfig $path;Assert ($loaded.OutputRoot.EndsWith($unicodeRoot)) 'No-BOM UTF8 config text corrupted.';'PASS UTF8 config containing Chinese output root round-trips'
$start=& (Join-Path $base 'start.ps1') -ConfigPath $path -RunId 'claimrace' -Simulation|ConvertFrom-Json
$snapshot=Join-Path $start.directory 'config.snapshot.json'
# Immediately race a direct caller against the child; an unowned caller may never publish a summary.
$args=@('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+(Join-Path $base 'run-experiment.ps1')+'"'),'-ConfigPath',('"'+$snapshot+'"'),'-RunId','claimrace','-Simulation')
$p=Start-Process powershell.exe -ArgumentList $args -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput (Join-Path $folder 'race.stdout') -RedirectStandardError (Join-Path $folder 'race.stderr')
Assert ($p.ExitCode -eq 1) 'Direct runner stole start claim.';'PASS direct runner cannot steal a start-owned claim'
$cfg.output.root='changed_root';$cfg.experiment.dutiesPercent=@(100);$cfg|ConvertTo-Json -Depth 16|Set-Content -LiteralPath $path -Encoding UTF8
$watch=[Diagnostics.Stopwatch]::StartNew();do{Start-Sleep -Milliseconds 100;$ready=$false;if(Test-Path -LiteralPath $start.eventsPath){$ready=[IO.File]::ReadAllText($start.eventsPath).Contains('step_started')}}while(!$ready -and $watch.Elapsed.TotalSeconds -lt 10);Assert $ready 'Snapshot child did not start.'
$event=@(Get-Content -LiteralPath $start.eventsPath -Encoding UTF8|ForEach-Object{$_|ConvertFrom-Json}|Where-Object type -eq 'run_started')[0]
Assert (($event.data.dutiesPercent -join ',') -ceq '30,50,70,100' -and $event.data.directory -ceq $start.directory) 'Source config edit changed child root/duties.';'PASS source config changes do not change start snapshot/root'
$stop=& (Join-Path $base 'stop.ps1') -RunId 'claimrace' -RunDirectory $start.directory -WaitSeconds 10|ConvertFrom-Json
Assert ($stop.summary.state -ceq 'stopped' -and $stop.summary.terminalPublished -and !$stop.summary.failed) 'Immutable directory stop failed.'
$final=@(Get-Content -LiteralPath $start.eventsPath -Encoding UTF8|ForEach-Object{$_|ConvertFrom-Json}|Where-Object type -eq 'run_finished')[-1]
Assert (!$final.data.terminalPublished -and (Get-Item -LiteralPath $start.summaryPath).LastWriteTimeUtc -ge (Get-Item -LiteralPath $start.eventsPath).LastWriteTimeUtc) 'Authoritative terminal published before last required event.';'PASS one authoritative terminal summary is published after terminal event work'
$stateFolder=Join-Path $folder 'state_reader';[void](New-Item -ItemType Directory -Path $stateFolder)
Write-RunEvent 'reader' $stateFolder 1 'run_started' 'starting' @{}
$stateFile=Join-Path $stateFolder 'state.json';$stream=[IO.File]::Open($stateFile,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
try{Write-RunEvent 'reader' $stateFolder 2 'step_started' 'running' @{}}finally{$stream.Dispose()}
Write-RunEvent 'reader' $stateFolder 3 'run_finished' 'completed' @{}
Assert ((Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8|ConvertFrom-Json).sequence -eq 3 -and @(Get-Content -LiteralPath (Join-Path $stateFolder 'events.jsonl')).Count -eq 3) 'Derived state lock damaged event stream or recovery.';'PASS locked state reader does not stop run; atomic replace recovers'
Add-Type -Path @((Join-Path $base 'src\FanTransport.cs'),(Join-Path $base 'src\ScopeVisa.cs'),(Join-Path $PSScriptRoot 'ProtocolTests.cs'))
$wire=New-Object LateFrameWire;$session=New-Object FanCycle.FanSession($wire);$rejected=$false;try{$session.Identify(20)}catch{$rejected=$true};Assert ($rejected -and !$session.Identified) 'Late READY frame was accepted.';'PASS READY received after deadline is rejected'
'SIMULATION ONLY: no physical device opened.'
"Evidence: $folder"
