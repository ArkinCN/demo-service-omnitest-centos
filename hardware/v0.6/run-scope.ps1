[CmdletBinding()]
param([string]$ConfigPath='', [ValidatePattern('^[a-zA-Z0-9_-]{1,100}$')][string]$RunId='')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
Import-Module (Join-Path $PSScriptRoot 'src\Runtime.psm1') -Force
if(!$ConfigPath){$ConfigPath=Join-Path $PSScriptRoot 'config\experiment.json'}
$scope=$null;$temp='';$directory='';$owned=$false;$failed=$false;$message='';$sequence=0;$count=0
function Emit([string]$Type,$Data){$script:sequence++;$eventState=if($Type -eq 'run_finished'){$Data.state}elseif($Type -eq 'run_started'){'starting'}else{'running'};Write-RunEvent $RunId $directory $script:sequence $Type $eventState $Data}
try {
    $resolved=(Resolve-Path -LiteralPath $ConfigPath).Path
    $raw=Get-Content -LiteralPath $resolved -Raw -Encoding UTF8
    $original=$raw|ConvertFrom-Json
    $cfg=$raw|ConvertFrom-Json
    # The shared validator checks serial configuration; scope-only ignores it.
    $cfg.serial=[pscustomobject]@{port='COM1';baud=115200;expectedIdentity='READY UNO_FAN_V2 25000';wiringConfirmed=$true}
    $cfg.scope.enabled=$true
    $temp=Join-Path (Split-Path $resolved -Parent) ('scope-validation-'+[Guid]::NewGuid().ToString('N')+'.json')
    $cfg|ConvertTo-Json -Depth 16|Set-Content -LiteralPath $temp -Encoding UTF8
    $loaded=Read-ExperimentConfig $temp;$cfg=$loaded.Config
    if(!$RunId){$RunId='scope_'+(Get-Date -Format 'yyyyMMdd_HHmmss_fff')+'_'+[Guid]::NewGuid().ToString('N').Substring(0,8)}
    $directory=Join-Path $loaded.OutputRoot $RunId
    [void](New-Item -ItemType Directory -Path $directory -Force)
    $claim=[IO.File]::Open((Join-Path $directory 'run.claim'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);$claim.Dispose();$owned=$true
    $original|ConvertTo-Json -Depth 16|Set-Content -LiteralPath (Join-Path $directory 'config.snapshot.json') -Encoding UTF8
    Emit 'run_started' @{mode='scope_only';fanCommandIssued=$false;directory=$directory;configPath=$resolved}
    if(!('FanCycle.ScopeVisa' -as [type])){Add-Type -Path (Join-Path $PSScriptRoot 'src\ScopeVisa.cs')}
    Import-Module (Join-Path $PSScriptRoot 'src\ScopeCapture.psm1') -Force -DisableNameChecking
    $scope=New-Object FanCycle.ScopeVisa($cfg.scope.resource)
    $settings=Initialize-FanScope $scope $cfg.scope
    $settings|ConvertTo-Json -Depth 12|Set-Content -LiteralPath (Join-Path $directory 'scope-settings.json') -Encoding UTF8
    Emit 'scope_configured' $settings
    Start-Sleep -Milliseconds ([int][Math]::Ceiling($cfg.experiment.settleSeconds*1000))
    # -1 denotes unknown PWM command, preventing a fabricated 0%/100% claim.
    foreach($capture in @(Save-FanScopeCapture $scope $cfg.scope $directory 1 -1)){
        $capture.commandedPwmPercent=$null
        $capture['fanCommandIssued']=$false
        $metaPath=@($capture.artifacts|Where-Object {[IO.Path]::GetFileName($_) -eq 'capture.json'})[0]
        $capture|ConvertTo-Json -Depth 12|Set-Content -LiteralPath $metaPath -Encoding UTF8
        $count++;Emit 'capture_completed' $capture
    }
} catch {$failed=$true;$message=$_.Exception.Message;[Console]::Error.WriteLine($message);if($owned){try{Emit 'run_error' @{message=$message}}catch{[Console]::Error.WriteLine($_.Exception.Message)}}}
finally {
    if($scope){try{$scope.Dispose()}catch{$failed=$true;$message=$_.Exception.Message;[Console]::Error.WriteLine($message)}}
    if($temp -and [IO.File]::Exists($temp)){try{[IO.File]::Delete($temp)}catch{$failed=$true;$message=$_.Exception.Message;[Console]::Error.WriteLine($message)}}
    if($owned){
        $summary=[ordered]@{schemaVersion='1.0';runId=$RunId;mode='scope_only';state=$(if($failed){'failed'}else{'completed'});terminalPublished=$false;failed=$failed;failureMessage=$message;captureCount=$count;fanCommandIssued=$false;exitCode=$(if($failed){1}else{0});directory=$directory;eventsPath=(Join-Path $directory 'events.jsonl')}
        try{Emit 'run_finished' $summary}catch{$failed=$true;$summary.failed=$true;$summary.state='failed';$summary.exitCode=1;$summary.failureMessage=$_.Exception.Message;[Console]::Error.WriteLine($_.Exception.Message)}
        $summary.terminalPublished=$true
        try{$summaryPath=Join-Path $directory 'summary.json';$summary|ConvertTo-Json -Depth 12|Set-Content -LiteralPath ($summaryPath+'.tmp') -Encoding UTF8;[IO.File]::Move(($summaryPath+'.tmp'),$summaryPath)}catch{$failed=$true;[Console]::Error.WriteLine($_.Exception.Message)}
    }
}
if($failed){exit 1};exit 0
