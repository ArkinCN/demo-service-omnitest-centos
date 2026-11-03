Set-StrictMode -Version Latest

function Assert-Boolean($Value,[string]$Name) { if($Value -isnot [bool]){throw "$Name must be JSON true or false."} }
function Assert-Number($Value,[string]$Name) {
    if($Value -isnot [int] -and $Value -isnot [long] -and $Value -isnot [double] -and $Value -isnot [decimal]){throw "$Name must be a JSON number."}
    if([double]::IsNaN([double]$Value) -or [double]::IsInfinity([double]$Value)){throw "$Name must be finite."}
}

function Read-ExperimentConfig([string]$Path) {
    $resolved=(Resolve-Path -LiteralPath $Path).Path
    $cfg=Get-Content -LiteralPath $resolved -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($cfg.schemaVersion -cne '1.0') { throw 'Unsupported config schemaVersion.' }
    Assert-Boolean $cfg.serial.wiringConfirmed 'serial.wiringConfirmed'; Assert-Number $cfg.serial.baud 'serial.baud'
    foreach($key in 'cycles','holdSeconds','settleSeconds'){Assert-Number $cfg.experiment.$key "experiment.$key"}
    if($null -eq $cfg.experiment.dutiesPercent -or $cfg.experiment.dutiesPercent -isnot [Array] -or $cfg.experiment.dutiesPercent.Count -eq 0){throw 'dutiesPercent must be a nonempty JSON array.'}
    foreach($d in $cfg.experiment.dutiesPercent){Assert-Number $d 'dutiesPercent item'}
    Assert-Boolean $cfg.scope.enabled 'scope.enabled'
    if($cfg.output.root -isnot [string] -or !$cfg.output.root){throw 'output.root must be a nonempty path.'}
    if ($cfg.serial.port -notmatch '^COM[1-9][0-9]*$' -or $cfg.serial.baud -ne 115200 -or $cfg.serial.expectedIdentity -cne 'READY UNO_FAN_V2 25000') { throw 'Only the verified UNO_FAN_V2 115200 transport is supported.' }
    if (!$cfg.serial.wiringConfirmed) { throw 'Confirm physical wiring in config before opening serial.' }
    if ($cfg.experiment.cycles -lt 0 -or $cfg.experiment.cycles -ne [int]$cfg.experiment.cycles -or $cfg.experiment.cycles -gt 1000000) { throw 'cycles must be an integer 0..1000000; 0 means continuous.' }
    if ($cfg.experiment.holdSeconds -lt 0.1 -or $cfg.experiment.holdSeconds -gt 3600 -or $cfg.experiment.settleSeconds -lt 0 -or $cfg.experiment.settleSeconds -ge $cfg.experiment.holdSeconds) { throw 'Invalid hold or settle timing.' }
    if (@($cfg.experiment.dutiesPercent).Count -eq 0) { throw 'Duty sequence is empty.' }
    foreach($d in $cfg.experiment.dutiesPercent) { if ($d -lt 0 -or $d -gt 100 -or $d -ne [int]$d) { throw 'Duty values must be integer percentages 0..100.' } }
    if ($cfg.scope.enabled) {
        foreach($key in 'inputImpedanceOhm','pwmTimebaseSecondsPerDiv','triggerLevelV'){Assert-Number $cfg.scope.$key "scope.$key"}
        if (!$cfg.scope.resource -or !$cfg.scope.expectedIdentity -or $cfg.scope.inputImpedanceOhm -ne 1000000) { throw 'Scope resource, identity and fixed 1MOhm setting are required.' }
        if ($cfg.scope.pwmTimebaseSecondsPerDiv -le 0 -or $cfg.scope.pwmTimebaseSecondsPerDiv -gt 0.00005) { throw 'PWM capture timebase must retain 25kHz detail.' }
        $seen=@(); foreach($role in 'current','voltage','pwm') {
            $ch=$cfg.scope.channels.$role
            foreach($key in 'channel','probeRatio','scaleVoltsPerDiv','offsetV'){Assert-Number $ch.$key "$role.$key"};Assert-Boolean $ch.physicalProbeRatioConfirmed "$role.physicalProbeRatioConfirmed"
            if ($ch.channel -lt 1 -or $ch.channel -gt 4 -or $ch.channel -ne [int]$ch.channel -or $seen -contains $ch.channel) { throw 'Channel mapping must contain unique channel numbers 1..4.' }; $seen+=$ch.channel
            if ($ch.coupling -cne 'DC' -or $ch.probeRatio -notin @(1,10,100) -or $ch.scaleVoltsPerDiv -le 0) { throw 'Invalid channel coupling/probe ratio/scale.' }
        }
        if ($cfg.scope.channels.current.probeRatio -ne 1) { throw 'Current clamp raw voltage requires scope probeRatio 1.' }
        $cc=$cfg.scope.currentConversion
        foreach($key in 'enabled','lowRangeConfirmed','zeroConfirmed','singleConductorConfirmed'){Assert-Boolean $cc.$key "currentConversion.$key"}
        foreach($key in 'gainAmpsPerVolt','turns','minimumSpecifiedCurrentA'){Assert-Number $cc.$key "currentConversion.$key"}
        if ($cc.enabled -and (!$cc.lowRangeConfirmed -or !$cc.zeroConfirmed -or !$cc.singleConductorConfirmed -or $cc.turns -lt 1 -or $cc.turns -ne [int]$cc.turns -or $cc.gainAmpsPerVolt -le 0)) { throw 'Current conversion requires valid turns/gain and range/zero/single-conductor confirmation.' }
        $t=$cfg.scope.tach
        foreach($key in 'enabled','wiringConfirmed','physicalProbeRatioConfirmed'){Assert-Boolean $t.$key "tach.$key"}
        if ($t.enabled) {
            foreach($key in 'channel','supplyVoltageV','outputVoltageV','probeRatio','timebaseSecondsPerDiv','scaleVoltsPerDiv','triggerLevelV'){Assert-Number $t.$key "tach.$key"}
            if($t.channel -ne [int]$t.channel -or $t.supplyVoltageV -le 0){throw 'Tach channel must be integer and supplyVoltageV must be positive.'}
            if($null -ne $t.pulsesPerRevolution){Assert-Number $t.pulsesPerRevolution 'tach.pulsesPerRevolution'}
            if ($t.channel -lt 1 -or $t.channel -gt 4 -or $seen -contains $t.channel -or !$t.wiringConfirmed -or !$t.physicalProbeRatioConfirmed -or !$t.sensorModel -or !$t.signalWire -or !$t.outputType -or $null -eq $t.supplyVoltageV -or $null -eq $t.outputVoltageV -or $t.outputVoltageV -le 0 -or $t.probeRatio -notin @(1,10,100) -or $t.scaleVoltsPerDiv -le 0 -or $null -eq $t.triggerLevelV -or $t.timebaseSecondsPerDiv -lt 0.01 -or $t.timebaseSecondsPerDiv -gt 0.1) { throw 'Tach requires verified sensor wiring/output/probe settings and an independent 10..100ms/div capture.' }
            if ($null -ne $t.pulsesPerRevolution -and ($t.pulsesPerRevolution -le 0 -or $t.pulsesPerRevolution -ne [int]$t.pulsesPerRevolution)) { throw 'PPR must be positive integer or null (frequency only).' }
        }
    }
    $root=if([IO.Path]::IsPathRooted($cfg.output.root)){[IO.Path]::GetFullPath($cfg.output.root)}else{[IO.Path]::GetFullPath((Join-Path (Split-Path $resolved -Parent) $cfg.output.root))}
    [pscustomobject]@{ Config=$cfg; Path=$resolved; OutputRoot=$root }
}

function Write-RunEvent {
    param([string]$RunId,[string]$Directory,[int]$Sequence,[string]$Type,[string]$State,[object]$Data)
    $event=[ordered]@{ schemaVersion='1.0'; runId=$RunId; sequence=$Sequence; timestampUtc=[DateTimeOffset]::UtcNow.ToString('o'); type=$Type; state=$State; data=$Data }
    $line=$event | ConvertTo-Json -Depth 16 -Compress
    [IO.File]::AppendAllText((Join-Path $Directory 'events.jsonl'),$line+[Environment]::NewLine,(New-Object Text.UTF8Encoding($false)))
    try{[Console]::Out.WriteLine($line)}catch{[Console]::Error.WriteLine('stdout consumer unavailable; events.jsonl remains authoritative for events.')}
    $statePath=Join-Path $Directory 'state.json'; $tmp=$statePath+'.'+[Guid]::NewGuid().ToString('N')+'.tmp'
    try{
        [IO.File]::WriteAllText($tmp,$line,(New-Object Text.UTF8Encoding($false)))
        $published=$false
        for($attempt=0;$attempt -lt 10;$attempt++){
            try{if([IO.File]::Exists($statePath)){[IO.File]::Replace($tmp,$statePath,[NullString]::Value)}else{[IO.File]::Move($tmp,$statePath)};$published=$true;break}
            catch [IO.IOException]{Start-Sleep -Milliseconds 20}
        }
        if(!$published){[Console]::Error.WriteLine('state.json reader lock prevented update; consume events.jsonl for current state.')}
    }catch{[Console]::Error.WriteLine('Could not update derived state.json: '+$_.Exception.Message)}
    finally{if([IO.File]::Exists($tmp)){try{[IO.File]::Delete($tmp)}catch{[Console]::Error.WriteLine('Derived state temporary file could not be removed.')}}}
}

Export-ModuleMember -Function Read-ExperimentConfig,Write-RunEvent
