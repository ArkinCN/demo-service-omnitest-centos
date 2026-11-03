[CmdletBinding()]
param([string]$ConfigPath='',[ValidatePattern('^[a-zA-Z0-9_-]{1,100}$')][string]$RunId='', [ValidatePattern('^[a-f0-9]{32}$')][string]$ClaimToken='', [switch]$Simulation, [switch]$SimulateCleanupFailure)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot 'src\Runtime.psm1') -Force
if(!$ConfigPath){$ConfigPath=Join-Path $PSScriptRoot 'config\experiment.json'}
$fan=$null;$scope=$null;$mutex=$null;$owns=$false;$runOwned=$false;$directory='';$sequence=0;$state='starting';$cycle=0;$complete=0;$captures=0;$failed=$false;$errorMessage='';$cleanup='not_attempted';$cancelled=$false;$started=[DateTimeOffset]::UtcNow.ToString('o');$stopFile=''
function Emit([string]$Type,[object]$Data){$script:sequence++;Write-RunEvent $RunId $directory $script:sequence $Type $script:state $Data}
function Stop-Requested { return ((Test-Path -LiteralPath $stopFile) -or [FanCycle.CancelSignal]::Requested) }
function Log-Command([object]$Duty,[string]$Command,[string]$Ack,[string]$Status){[pscustomobject]@{timestampUtc=[DateTimeOffset]::UtcNow.ToString('o');cycle=$cycle;dutyPercent=$Duty;command=$Command;ack=$Ack;status=$Status}|Export-Csv -LiteralPath (Join-Path $directory 'commands.csv') -NoTypeInformation -Encoding UTF8 -Append;Emit 'command_ack' ([ordered]@{cycle=$cycle;dutyPercent=$Duty;command=$Command;ack=$Ack;meaning='controller_report; physical RPM and stop not measured'})}
try {
    $loaded=Read-ExperimentConfig $ConfigPath;$cfg=$loaded.Config
    if(!$RunId){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss_fff')+'_'+[Guid]::NewGuid().ToString('N').Substring(0,8)}
    $directory=Join-Path $loaded.OutputRoot $RunId
    [void](New-Item -ItemType Directory -Path $directory -Force);$stopFile=Join-Path $directory 'stop.request'
    $claimPath=Join-Path $directory 'run.claim'
    if($ClaimToken){if([IO.File]::ReadAllText($claimPath) -cne $ClaimToken){throw 'Run claim token mismatch.'}}
    else{$claim=[IO.File]::Open($claimPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);$claim.Dispose()}
    $marker=[IO.File]::Open((Join-Path $directory 'runner.started'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);$marker.Dispose();$runOwned=$true
    if(!$ClaimToken){$cfg|ConvertTo-Json -Depth 16|Set-Content -LiteralPath (Join-Path $directory 'config.snapshot.json') -Encoding UTF8}
    if(!('FanCycle.FanSession' -as [type])){
        $sources=@((Join-Path $PSScriptRoot 'src\FanTransport.cs'),(Join-Path $PSScriptRoot 'src\ScopeVisa.cs'))
        if($Simulation){$sources+=Join-Path $PSScriptRoot 'verification\ProtocolTests.cs'}
        Add-Type -Path $sources
    }
    [FanCycle.CancelSignal]::Install()
    Emit 'run_started' ([ordered]@{simulation=[bool]$Simulation;processId=$PID;directory=$directory;requestedCycles=$cfg.experiment.cycles;holdSeconds=$cfg.experiment.holdSeconds;dutiesPercent=$cfg.experiment.dutiesPercent;configPath=$loaded.Path})
    $mutex=New-Object Threading.Mutex($false,('Local\UNO_FAN_V2_'+$cfg.serial.port.ToUpperInvariant()))
    try{$owns=$mutex.WaitOne(0)}catch [Threading.AbandonedMutexException]{$owns=$true}
    if(!$owns){throw 'Another experiment owns this serial port.'}
    if(Stop-Requested){$cancelled=$true}else{
        if($Simulation){
            $wire=New-Object FakeWire;$wire.Feed("READY UNO_FAN_V2 25000`n");$wire.AutoAck=$true;$wire.CleanupFails=[bool]$SimulateCleanupFailure
            $fan=New-Object FanCycle.FanSession($wire)
        }else{$fan=New-Object FanCycle.FanSession((New-Object FanCycle.SerialWire($cfg.serial.port)))}
        $fan.Identify(8000);Emit 'controller_identified' @{identity=$cfg.serial.expectedIdentity;port=$cfg.serial.port;openingPortResetsUno=$true}
        Log-Command $null 'STATUS' ($fan.Command('STATUS',2000)) 'board_report'
        if($cfg.scope.enabled -and !$Simulation){
            if(!('FanCycle.ScopeVisa' -as [type])){Add-Type -Path (Join-Path $PSScriptRoot 'src\ScopeVisa.cs')}
            Import-Module (Join-Path $PSScriptRoot 'src\ScopeCapture.psm1') -Force -DisableNameChecking
            $scope=New-Object FanCycle.ScopeVisa($cfg.scope.resource)
            $settings=Initialize-FanScope $scope $cfg.scope;$settings|ConvertTo-Json -Depth 12|Set-Content -LiteralPath (Join-Path $directory 'scope-settings.json') -Encoding UTF8;Emit 'scope_configured' $settings
        }
        if($Simulation -and $cfg.scope.enabled){Emit 'simulation_notice' @{scope='disabled in simulation; no waveforms/metrics claimed'}}
        $state='running'
        while(($cfg.experiment.cycles -eq 0 -or $cycle -lt $cfg.experiment.cycles) -and !(Stop-Requested)){
            $cycle++;$cycleDone=$true
            foreach($d in $cfg.experiment.dutiesPercent){
                if(Stop-Requested){$cycleDone=$false;break}
                $duty=[int]$d;$ack=$fan.Command("SET $duty",2000);$hold=[Diagnostics.Stopwatch]::StartNew();Log-Command $duty "SET $duty" $ack 'acknowledged'
                Emit 'step_started' @{cycle=$cycle;dutyPercent=$duty;targetHoldSeconds=$cfg.experiment.holdSeconds}
                while($hold.Elapsed.TotalSeconds -lt $cfg.experiment.settleSeconds -and !(Stop-Requested)){Start-Sleep -Milliseconds 50}
                if(Stop-Requested){$cycleDone=$false;break}
                if($scope){$result=@(Save-FanScopeCapture $scope $cfg.scope $directory $cycle $duty);foreach($capture in $result){$captures++;Emit 'capture_completed' $capture}}
                if($hold.Elapsed.TotalSeconds -gt $cfg.experiment.holdSeconds){Emit 'timing_overrun' @{cycle=$cycle;dutyPercent=$duty;elapsedSeconds=$hold.Elapsed.TotalSeconds;reason='capture exceeded target dwell'}}
                while($hold.Elapsed.TotalSeconds -lt $cfg.experiment.holdSeconds -and !(Stop-Requested)){Start-Sleep -Milliseconds 50}
                if(Stop-Requested){$cycleDone=$false;break}
                $ack=$fan.Command('STATUS',2000);if($ack -cne "OK DUTY $duty"){throw "Unexpected board status: $ack"};Log-Command $duty 'STATUS' $ack 'board_report'
                Emit 'step_completed' @{cycle=$cycle;dutyPercent=$duty;actualHoldSeconds=$hold.Elapsed.TotalSeconds}
            }
            if($cycleDone){$complete++;Emit 'cycle_completed' @{cycle=$cycle;completedCycles=$complete}}
        }
        $cancelled=Stop-Requested
    }
}catch{$failed=$true;$errorMessage=$_.Exception.Message;[Console]::Error.WriteLine($errorMessage);if($runOwned){try{Emit 'run_error' @{message=$errorMessage}}catch{[Console]::Error.WriteLine('Could not persist run_error event.')}}}
finally {
    $state='stopping'
    if($fan -and $fan.Identified){
        try{$ack=$fan.Command('SET 0',2000);$cleanup='pwm_zero_acknowledged_physical_stop_unverified';try{Log-Command 0 'SET 0' $ack $cleanup}catch{$failed=$true;[Console]::Error.WriteLine($_.Exception.Message)}}
        catch{$failed=$true;$cleanup='failed_physical_state_unknown';[Console]::Error.WriteLine('SET 0 failed; disconnect fan 5V power: '+$_.Exception.Message)}
    }else{$cleanup='no_identified_controller_no_zero_command';if($fan){$failed=$true}}
    if($scope){try{$scope.Dispose()}catch{$failed=$true;[Console]::Error.WriteLine($_.Exception.Message)}}
    if($fan){try{$fan.Dispose()}catch{$failed=$true;[Console]::Error.WriteLine($_.Exception.Message)}}
    if($owns){$mutex.ReleaseMutex()};if($mutex){$mutex.Dispose()};if('FanCycle.CancelSignal' -as [type]){[FanCycle.CancelSignal]::Remove()}
    $state=if($failed){'failed'}elseif($cancelled){'stopped'}else{'completed'}
    if($runOwned){
        $summary=[ordered]@{schemaVersion='1.0';runId=$RunId;state=$state;simulation=[bool]$Simulation;terminalPublished=$false;startedUtc=$started;endedUtc=[DateTimeOffset]::UtcNow.ToString('o');completedCycles=$complete;activeCycle=$cycle;captureCount=$captures;cancelled=$cancelled;failed=$failed;failureMessage=$errorMessage;cleanup=$cleanup;physicalStopVerified=$false;exitCode=$(if($failed){1}else{0});eventsPath=(Join-Path $directory 'events.jsonl');commandsPath=(Join-Path $directory 'commands.csv')}
        try{
            Emit 'run_finished' $summary
        }catch{
            $failed=$true;[Console]::Error.WriteLine('Could not persist terminal event: '+$_.Exception.Message)
            $summary.failed=$true;$summary.state='failed';$summary.exitCode=1;$summary.failureMessage='Could not persist final event/results.'
        }
        # One atomic terminal publication, after all required event work; never revise a published success.
        $summary.terminalPublished=$true;$summaryPath=Join-Path $directory 'summary.json';$tempPath=$summaryPath+'.tmp'
        try{$summary|ConvertTo-Json -Depth 12|Set-Content -LiteralPath $tempPath -Encoding UTF8;[IO.File]::Move($tempPath,$summaryPath)}
        catch{$failed=$true;[Console]::Error.WriteLine('Terminal summary was not published: '+$_.Exception.Message)}
    }
}
if($failed){exit 1};exit 0
