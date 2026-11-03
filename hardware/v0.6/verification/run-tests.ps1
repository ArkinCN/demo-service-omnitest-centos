$ErrorActionPreference='Stop'
$base=Split-Path $PSScriptRoot -Parent
$evidence=Join-Path $PSScriptRoot ('evidence_'+(Get-Date -Format 'yyyyMMdd_HHmmss_fff'))
[void](New-Item -ItemType Directory -Path $evidence)
function Assert([bool]$Value,[string]$Message){if(!$Value){throw $Message}}
Add-Type -Path @((Join-Path $base 'src\FanTransport.cs'),(Join-Path $base 'src\ScopeVisa.cs'),(Join-Path $PSScriptRoot 'ProtocolTests.cs'))
$results=New-Object 'Collections.Generic.List[string]'
foreach($r in [ProtocolTests]::Run()){$results.Add($r)}
Import-Module (Join-Path $base 'src\Runtime.psm1') -Force
$cfg=Get-Content -LiteralPath (Join-Path $base 'config\experiment.json') -Raw|ConvertFrom-Json
$cfg.experiment.cycles=1;$cfg.experiment.holdSeconds=0.1;$cfg.experiment.settleSeconds=0;$cfg.scope.enabled=$false;$cfg.serial.port='COM9999';$cfg.output.root='runs'
$config=Join-Path $evidence 'test-config.json';$cfg|ConvertTo-Json -Depth 16|Set-Content -LiteralPath $config -Encoding UTF8
[void](Read-ExperimentConfig $config)
$cfg.serial.wiringConfirmed='false';$cfg|ConvertTo-Json -Depth 16|Set-Content -LiteralPath $config -Encoding UTF8;$rejected=$false;try{Read-ExperimentConfig $config}catch{$rejected=$true};Assert $rejected 'String boolean must not bypass wiring gate.';$results.Add('PASS runtime rejects string boolean wiring gate')
$cfg.serial.wiringConfirmed=$true;$cfg|ConvertTo-Json -Depth 16|Set-Content -LiteralPath $config -Encoding UTF8
function Run-Case([string]$Id,[switch]$Failure){
    $args=@('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+(Join-Path $base 'run-experiment.ps1')+'"'),'-ConfigPath',('"'+$config+'"'),'-RunId',$Id,'-Simulation');if($Failure){$args+='-SimulateCleanupFailure'}
    $p=Start-Process -FilePath powershell.exe -ArgumentList $args -WindowStyle Hidden -PassThru -Wait -RedirectStandardOutput (Join-Path $evidence "$Id.stdout.jsonl") -RedirectStandardError (Join-Path $evidence "$Id.stderr.log")
    return $p.ExitCode
}
$code=Run-Case 'finite';Assert ($code -eq 0) 'Finite run exit code failed.'
$dir=Join-Path $evidence 'runs\finite';$s=Get-Content -LiteralPath (Join-Path $dir 'summary.json') -Raw|ConvertFrom-Json;$rows=@(Import-Csv -LiteralPath (Join-Path $dir 'commands.csv'))
Assert (($rows|Where-Object command -like 'SET *').command -join ',' -ceq 'SET 30,SET 50,SET 70,SET 100,SET 0') 'Sequence incorrect.';Assert ($s.completedCycles -eq 1 -and $s.captureCount -eq 0 -and !$s.failed -and $s.simulation) 'Finite summary incorrect.'
$lines=@(Get-Content -LiteralPath (Join-Path $evidence 'finite.stdout.jsonl'));$seq=0;foreach($line in $lines){$e=$line|ConvertFrom-Json;$seq++;Assert ($e.sequence -eq $seq -and $e.schemaVersion -ceq '1.0' -and $e.runId -ceq 'finite') 'stdout contains non-event or discontinuous sequence.'};Assert ($lines.Count -gt 10) 'No events.';$results.Add('PASS actual runner finite sequence/cleanup and stdout JSONL')
$before=(Get-FileHash -LiteralPath (Join-Path $dir 'summary.json')).Hash;$code=Run-Case 'finite';Assert ($code -ne 0 -and (Get-FileHash -LiteralPath (Join-Path $dir 'summary.json')).Hash -ceq $before) 'Duplicate run overwrote summary.';$results.Add('PASS duplicate RunId cannot overwrite previous run')
$code=Run-Case 'cleanup_failure' -Failure;$s=Get-Content -LiteralPath (Join-Path $evidence 'runs\cleanup_failure\summary.json') -Raw|ConvertFrom-Json;Assert ($code -eq 1 -and $s.failed -and $s.cleanup -ceq 'failed_physical_state_unknown') 'Failed cleanup falsely reported success.';$results.Add('PASS cleanup failure -> exit 1 and unknown physical state')
$cfg.experiment.cycles=0;$cfg.experiment.holdSeconds=0.5;$cfg|ConvertTo-Json -Depth 16|Set-Content -LiteralPath $config -Encoding UTF8
$start=& (Join-Path $base 'start.ps1') -ConfigPath $config -RunId 'continuous' -Simulation|ConvertFrom-Json
$watch=[Diagnostics.Stopwatch]::StartNew();$eventPath=$start.eventsPath
do{Start-Sleep -Milliseconds 100;$ready=$false;if(Test-Path -LiteralPath $eventPath){$ready=([IO.File]::ReadAllText($eventPath).Contains('step_started'))}}while(!$ready -and $watch.Elapsed.TotalSeconds -lt 10)
Assert $ready 'Async runner never became ready.'
$code=Run-Case 'competing';$s=Get-Content -LiteralPath (Join-Path $evidence 'runs\competing\summary.json') -Raw|ConvertFrom-Json;Assert ($code -eq 1 -and $s.failureMessage -like '*owns this serial port*' -and !(Test-Path -LiteralPath (Join-Path $evidence 'runs\competing\commands.csv'))) 'Serial mutex did not reject second run.';$results.Add('PASS concurrent run rejected before any serial command')
$stop=& (Join-Path $base 'stop.ps1') -ConfigPath $config -RunId 'continuous' -WaitSeconds 10|ConvertFrom-Json
Assert ($stop.status -ceq 'finished' -and $stop.summary.state -ceq 'stopped' -and $stop.summary.cleanup -ceq 'pwm_zero_acknowledged_physical_stop_unverified' -and !$stop.summary.failed) 'Async stop did not ACK zero.';$results.Add('PASS asynchronous start -> stop request -> zero ACK -> stopped summary')
# Invoke the real waveform estimator with synthetic square waves. No instrument data claimed.
Import-Module (Join-Path $base 'src\ScopeCapture.psm1') -Force -DisableNameChecking
$module=Get-Module ScopeCapture;$values=New-Object double[] 1200;for($i=0;$i -lt 1200;$i++){$values[$i]=if(($i%40) -lt 12){5.0}else{0.0}}
$m=& $module {param($v) Get-WaveMetrics $v 0.000001 $true} $values
Assert ([Math]::Abs($m.frequencyHz-25000) -lt 1 -and [Math]::Abs($m.dutyPercent-30) -lt 0.1) 'Synthetic PWM metric failed.';$results.Add('PASS real waveform estimator: synthetic 25kHz 30% input')
$results|Set-Content -LiteralPath (Join-Path $evidence 'results.txt') -Encoding UTF8
$results;"Evidence: $evidence";'SIMULATION ONLY: no serial/VISA device opened; no physical-stop or measured-RPM claim.'
