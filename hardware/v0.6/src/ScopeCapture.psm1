Set-StrictMode -Version Latest
$script:Culture=[Globalization.CultureInfo]::InvariantCulture
function Number([double]$Value) { $Value.ToString('R',$script:Culture) }
function Read-Number($Scope,[string]$Command) {
    $n=[double]::Parse($Scope.Query($Command),$script:Culture)
    if ([double]::IsNaN($n) -or [double]::IsInfinity($n)) { throw "Non-finite readback: $Command" }; return $n
}
function Check-Number($Scope,[string]$Command,[double]$Expected) {
    $actual=Read-Number $Scope $Command
    if ([Math]::Abs($actual-$Expected) -gt [Math]::Max(1e-9,[Math]::Abs($Expected)*1e-5)) { throw "Scope readback mismatch: $Command expected $Expected got $actual" }; return $actual
}
function Set-Channel($Scope,[int]$Channel,$Settings) {
    $Scope.Write(":CHANnel${Channel}:DISPlay ON"); $Scope.Write(":CHANnel${Channel}:COUPling DC"); $Scope.Write(":CHANnel${Channel}:UNIT VOLT")
    foreach($pair in @(@('PROBe',$Settings.probeRatio),@('SCALe',$Settings.scaleVoltsPerDiv),@('OFFSet',$Settings.offsetV))) { $Scope.Write(":CHANnel${Channel}:$($pair[0]) $(Number $pair[1])") }
    if ($Scope.Query(":CHANnel${Channel}:COUPling?") -cne 'DC' -or $Scope.Query(":CHANnel${Channel}:UNIT?") -cne 'VOLT' -or $Scope.Query(":CHANnel${Channel}:DISPlay?") -cne '1') { throw "Invalid CH$Channel readback." }
    [ordered]@{ channel=$Channel; probeRatio=(Check-Number $Scope ":CHANnel${Channel}:PROBe?" $Settings.probeRatio); scaleVoltsPerDiv=(Check-Number $Scope ":CHANnel${Channel}:SCALe?" $Settings.scaleVoltsPerDiv); offsetV=(Check-Number $Scope ":CHANnel${Channel}:OFFSet?" $Settings.offsetV); coupling='DC'; unit='VOLT'; physicalProbeRatioConfirmed=$Settings.physicalProbeRatioConfirmed }
}
function Set-CaptureProfile($Scope,$Config,[string]$Profile) {
    if ($Profile -eq 'pwm') { $source=$Config.channels.pwm.channel; $time=$Config.pwmTimebaseSecondsPerDiv; $level=$Config.triggerLevelV }
    else { $source=$Config.tach.channel; $time=$Config.tach.timebaseSecondsPerDiv; $level=$Config.tach.triggerLevelV }
    $Scope.Write(":TIMebase:MAIN:SCALe $(Number $time)"); $Scope.Write(':TRIGger:MODE EDGE'); $Scope.Write(":TRIGger:EDGE:SOURce CHANnel$source"); $Scope.Write(":TRIGger:EDGE:LEVel $(Number $level)"); $Scope.Write(':TRIGger:SWEep AUTO')
    [void](Check-Number $Scope ':TIMebase:MAIN:SCALe?' $time)
    if ($Scope.Query(':TRIGger:EDGE:SOURce?') -cne "CHAN$source") { throw 'Trigger source readback mismatch.' }
    [void](Check-Number $Scope ':TRIGger:EDGE:LEVel?' $level)
    $err=$Scope.Query(':SYSTem:ERRor?'); if ($err -notmatch '^0,') { throw "Scope configuration error: $err" }
}
function Initialize-FanScope($Scope,$Config) {
    $id=$Scope.Query('*IDN?'); if ($id -cne $Config.expectedIdentity -or $id -notmatch '^RIGOL TECHNOLOGIES,DS1104Z Plus,DS1ZC[0-9]+,') { throw "Unvalidated scope identity: $id" }
    $settings=[ordered]@{ identity=$id; inputImpedanceOhm=1000000; channels=@{}; configuredUtc=[DateTimeOffset]::UtcNow.ToString('o'); timebaseSecondsPerDiv=$Config.pwmTimebaseSecondsPerDiv }
    $active=@(); foreach($role in 'current','voltage','pwm') { $ch=$Config.channels.$role; $settings.channels[$role]=Set-Channel $Scope $ch.channel $ch; $active+=$ch.channel }
    if ($Config.tach.enabled) { $t=$Config.tach; $s=[pscustomobject]@{probeRatio=$t.probeRatio;scaleVoltsPerDiv=$t.scaleVoltsPerDiv;offsetV=0;physicalProbeRatioConfirmed=$t.physicalProbeRatioConfirmed}; $settings.channels.tach=Set-Channel $Scope $t.channel $s; $active+=$t.channel }
    foreach($ch in 1,2,3,4) { if($active -notcontains $ch){$Scope.Write(":CHANnel${ch}:DISPlay OFF");if($Scope.Query(":CHANnel${ch}:DISPlay?") -cne '0'){throw 'Inactive channel not disabled.'}} }
    Set-CaptureProfile $Scope $Config 'pwm'; $Scope.Write(':RUN'); return $settings
}
function Get-WaveMetrics([double[]]$Values,[double]$Increment,[bool]$Edges) {
    $sum=0.0; $sq=0.0; $min=[double]::PositiveInfinity; $max=[double]::NegativeInfinity
    foreach($v in $Values){$sum+=$v;$sq+=$v*$v;$min=[Math]::Min($min,$v);$max=[Math]::Max($max,$v)}
    $mean=$sum/$Values.Length; $metric=[ordered]@{points=$Values.Length;sampleIntervalS=$Increment;windowS=($Values.Length-1)*$Increment;minimumV=$min;maximumV=$max;meanV=$mean;rmsV=[Math]::Sqrt($sq/$Values.Length);frequencyHz=$null;dutyPercent=$null;edgeStatus='not_requested'}
    if($Edges){
        $metric.edgeStatus='insufficient_amplitude_or_edges'; $rises=New-Object 'Collections.Generic.List[double]'; $falls=New-Object 'Collections.Generic.List[double]'
        if(($max-$min) -ge 0.5){$level=($min+$max)/2; for($i=1;$i -lt $Values.Length;$i++) { $a=$Values[$i-1];$b=$Values[$i]; if(($a -lt $level -and $b -ge $level) -or ($a -ge $level -and $b -lt $level)){ $time=(($i-1)+($level-$a)/($b-$a))*$Increment; if($b -gt $a){$rises.Add($time)}else{$falls.Add($time)} } } }
        if($rises.Count -ge 2){$periodSum=0.0;$highSum=0.0;$periods=0;$lengths=New-Object 'Collections.Generic.List[double]';for($i=0;$i -lt $rises.Count-1;$i++){ $left=$rises[$i];$right=$rises[$i+1];$fall=$null;foreach($f in $falls){if($f -gt $left -and $f -lt $right){$fall=$f;break}};if($null -ne $fall){$periodSum+=$right-$left;$highSum+=$fall-$left;$periods++;$lengths.Add($right-$left)} };if($periods -ge 3 -and $periodSum/$periods/$Increment -ge 20){$meanPeriod=$periodSum/$periods;$stable=$true;foreach($p in $lengths){if([Math]::Abs($p-$meanPeriod)/$meanPeriod -gt 0.2){$stable=$false}};if($stable){$metric.frequencyHz=$periods/$periodSum;$metric.dutyPercent=100*$highSum/$periodSum;$metric.edgeStatus='derived_from_displayed_waveform';$metric.completePeriods=$periods}else{$metric.edgeStatus='unstable_periods'}}else{$metric.edgeStatus='fewer_than_three_periods_or_twenty_samples_per_period'} }
    }; return $metric
}
function Save-ProfileCapture($Scope,$Config,[string]$Directory,[string]$Profile,[int]$Cycle,[int]$Duty) {
    [void](New-Item -ItemType Directory -Path $Directory)
    $start=[DateTimeOffset]::UtcNow.ToString('o'); $metrics=[ordered]@{}; $files=New-Object 'Collections.Generic.List[string]'
    if($Profile -eq 'pwm'){$roles=@('current','voltage','pwm')}else{$roles=@('tach')}
    try {
        $Scope.Write(':STOP');$Scope.Write(':WAVeform:MODE NORM');$Scope.Write(':WAVeform:FORMat ASCii')
        foreach($role in $roles){
            $ch=if($role -eq 'tach'){$Config.tach}else{$Config.channels.$role};$channel=$ch.channel
            $Scope.Write(":WAVeform:SOURce CHANnel$channel");$pre=$Scope.Query(':WAVeform:PREamble?');$f=$pre.Split(',');if($f.Length -ne 10){throw 'Invalid waveform preamble.'}
            $inc=[double]::Parse($f[4],$script:Culture);$origin=[double]::Parse($f[5],$script:Culture);$ref=[double]::Parse($f[6],$script:Culture)
            if($inc -le 0 -or [double]::IsNaN($inc) -or [double]::IsInfinity($inc) -or [double]::IsNaN($origin) -or [double]::IsInfinity($origin) -or [double]::IsNaN($ref) -or [double]::IsInfinity($ref)){throw 'Invalid waveform time coordinates.'}
            if($role -eq 'pwm' -and $inc -gt 0.000002){throw 'PWM export lacks 20 samples per 25kHz period.'}
            $payload=[FanCycle.ScopeVisa]::BlockPayload($Scope.QueryBytes(':WAVeform:DATA?'));$parts=[Text.Encoding]::ASCII.GetString($payload).Trim().Split(',')
            if($parts.Length -ne [int]::Parse($f[2],$script:Culture) -or $parts.Length -lt 2){throw 'Waveform sample count differs from preamble.'}
            $values=New-Object double[] $parts.Length
            $cc=$Config.currentConversion
            $rows=for($i=0;$i -lt $parts.Length;$i++){$v=[double]::Parse($parts[$i],$script:Culture);if([double]::IsNaN($v) -or [double]::IsInfinity($v)){throw 'Invalid waveform voltage.'};$values[$i]=$v;[pscustomobject]@{sample=$i;time_s=($i-$ref)*$inc+$origin;voltage_V=$v;current_A=$(if($role -eq 'current' -and $cc.enabled){$v*$cc.gainAmpsPerVolt/$cc.turns}else{$null})}}
            $csv=Join-Path $Directory "CH${channel}.csv";$rows|Export-Csv -LiteralPath $csv -NoTypeInformation -Encoding UTF8;$files.Add($csv)
            $prePath=Join-Path $Directory "CH${channel}_preamble.txt";[IO.File]::WriteAllText($prePath,$pre);$files.Add($prePath)
            $m=Get-WaveMetrics $values $inc ($role -in @('pwm','tach'));$m.physicalProbeRatioConfirmed=$ch.physicalProbeRatioConfirmed
            if($role -eq 'pwm' -and $Duty -in @(0,100)){$m.frequencyHz=$null;$m.dutyPercent=$null;$m.edgeStatus='constant_output_command_no_frequency_claim'}
            if($role -eq 'pwm' -and $null -ne $m.frequencyHz -and [Math]::Abs($m.frequencyHz-25000) -gt 2500){$m.frequencyHz=$null;$m.dutyPercent=$null;$m.edgeStatus='outside_expected_25kHz_band'}
            if($role -eq 'tach'){$m.clipped=($m.maximumV -ge 4*$ch.scaleVoltsPerDiv*0.99 -or $m.minimumV -le -4*$ch.scaleVoltsPerDiv*0.99);if($m.clipped){$m.frequencyHz=$null;$m.dutyPercent=$null;$m.edgeStatus='display_clipped_invalid_frequency'}}
            if($role -eq 'current' -and $cc.enabled){$m.meanCurrentA=$m.meanV*$cc.gainAmpsPerVolt/$cc.turns;$m.currentConversion='confirmed_gain_and_turns';$m.belowSpecifiedRange=([Math]::Abs($m.meanCurrentA) -lt $cc.minimumSpecifiedCurrentA)}
            if($role -eq 'tach'){$m.rpm=$null;if($null -ne $m.frequencyHz -and $null -ne $Config.tach.pulsesPerRevolution){$m.rpm=60*$m.frequencyHz/$Config.tach.pulsesPerRevolution};$m.pulsesPerRevolution=$Config.tach.pulsesPerRevolution}
            $metrics[$role]=$m
        }
        $bmp=[FanCycle.ScopeVisa]::BlockPayload($Scope.QueryBytes(':DISPlay:DATA? ON,OFF,BMP'));if($bmp.Length -lt 54 -or $bmp[0] -ne 66 -or $bmp[1] -ne 77){throw 'Invalid scope BMP.'};$screen=Join-Path $Directory 'screen.bmp';[IO.File]::WriteAllBytes($screen,$bmp);$files.Add($screen)
        $meta=[ordered]@{schemaVersion='1.0';startedUtc=$start;finishedUtc=[DateTimeOffset]::UtcNow.ToString('o');cycle=$Cycle;commandedPwmPercent=$Duty;profile=$Profile;source='NORM displayed waveforms; short STOP snapshot, not ten-second trend';timebaseSecondsPerDiv=$(if($Profile -eq 'pwm'){$Config.pwmTimebaseSecondsPerDiv}else{$Config.tach.timebaseSecondsPerDiv});metrics=$metrics;artifacts=@($files.ToArray());rpmAvailable=($Profile -eq 'tach' -and $null -ne $metrics.tach.rpm)}
        $metaPath=Join-Path $Directory 'capture.json';$meta.artifacts+=@($metaPath);$meta|ConvertTo-Json -Depth 12|Set-Content -LiteralPath $metaPath -Encoding UTF8;return $meta
    } finally { $Scope.Write(':RUN') }
}
function Save-FanScopeCapture($Scope,$Config,[string]$RunDirectory,[int]$Cycle,[int]$Duty) {
    $tag='cycle{0:D4}_duty{1:D3}_{2}' -f $Cycle,$Duty,(Get-Date -Format 'yyyyMMdd_HHmmss_fff');$base=Join-Path $RunDirectory $tag
    $result=New-Object 'Collections.Generic.List[object]'
    # PWM profile is already active; avoid resetting acquisition immediately before STOP.
    $result.Add((Save-ProfileCapture $Scope $Config (Join-Path $base 'pwm') 'pwm' $Cycle $Duty))
    if($Config.tach.enabled){try{Set-CaptureProfile $Scope $Config 'tach';Start-Sleep -Milliseconds ([int][Math]::Ceiling(12*$Config.tach.timebaseSecondsPerDiv*1000));$result.Add((Save-ProfileCapture $Scope $Config (Join-Path $base 'tach') 'tach' $Cycle $Duty))}finally{Set-CaptureProfile $Scope $Config 'pwm'}}
    return $result.ToArray()
}
Export-ModuleMember -Function Initialize-FanScope,Save-FanScopeCapture
