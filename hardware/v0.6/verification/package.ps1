param([string]$Destination='')
$ErrorActionPreference='Stop'
$base=Split-Path $PSScriptRoot -Parent
if(!$Destination){$Destination=Join-Path (Split-Path $base -Parent) 'dist\usb-fan-experiment-v0.4-20261005.zip'}
if(Test-Path -LiteralPath $Destination){throw 'Package exists; never overwrite a published package.'}
$stage=Join-Path $PSScriptRoot ('package_'+(Get-Date -Format 'yyyyMMdd_HHmmss_fff'))
[void](New-Item -ItemType Directory -Path $stage)
foreach($part in @('README.md','src','schemas','firmware','docs','run-experiment.ps1','start.ps1','stop.ps1','start.cmd','stop.cmd','check-dependencies.ps1','check-dependencies.cmd')){Copy-Item -LiteralPath (Join-Path $base $part) -Destination $stage -Recurse}
[void](New-Item -ItemType Directory -Path (Join-Path $stage 'config'))
foreach($part in @('experiment.json','acceptance.json')){Copy-Item -LiteralPath (Join-Path $base ('config\'+$part)) -Destination (Join-Path $stage 'config')}
[void](New-Item -ItemType Directory -Path (Join-Path $stage 'verification'))
foreach($part in @('run-tests.ps1','fix-regressions.ps1','ProtocolTests.cs','VERIFICATION.md')){Copy-Item -LiteralPath (Join-Path $PSScriptRoot $part) -Destination (Join-Path $stage 'verification')}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'hardware-interface-evidence') -Destination (Join-Path $stage 'verification') -Recurse
if(Test-Path -LiteralPath (Join-Path $base 'examples')){Copy-Item -LiteralPath (Join-Path $base 'examples') -Destination $stage -Recurse}
$files=@(Get-ChildItem -LiteralPath $stage -Recurse -File|Sort-Object FullName|ForEach-Object{[ordered]@{path=$_.FullName.Substring($stage.Length+1).Replace('\','/');bytes=$_.Length;sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}})
[ordered]@{schemaVersion='1.0';packageVersion='v0.4-20261005';createdUtc=[DateTimeOffset]::UtcNow.ToString('o');algorithm='SHA256';scope='all payload files except this manifest itself';files=$files}|ConvertTo-Json -Depth 10|Set-Content -LiteralPath (Join-Path $stage 'manifest.sha256.json') -Encoding UTF8
[void](New-Item -ItemType Directory -Path (Split-Path $Destination -Parent) -Force)
Compress-Archive -LiteralPath (Get-ChildItem -LiteralPath $stage).FullName -DestinationPath $Destination
[ordered]@{path=$Destination;bytes=(Get-Item -LiteralPath $Destination).Length;sha256=(Get-FileHash -LiteralPath $Destination).Hash.ToLowerInvariant();payloadCount=$files.Count}|ConvertTo-Json -Compress
