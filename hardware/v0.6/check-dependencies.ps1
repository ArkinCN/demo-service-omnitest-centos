[CmdletBinding()]
param([string]$ConfigPath='')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
try{
    if(!$ConfigPath){$ConfigPath=Join-Path $PSScriptRoot 'config\experiment.json'}
    Import-Module (Join-Path $PSScriptRoot 'src\Runtime.psm1') -Force;$loaded=Read-ExperimentConfig $ConfigPath;$cfg=$loaded.Config
    $missing=New-Object 'Collections.Generic.List[string]';$ports=@([IO.Ports.SerialPort]::GetPortNames())
    if(!$([Environment]::Is64BitProcess)){$missing.Add('64-bit PowerShell required for visa64.dll')}
    if($PSVersionTable.PSVersion.Major -lt 5){$missing.Add('Windows PowerShell 5.1 required')}
    if($ports -notcontains $cfg.serial.port){$missing.Add('Configured serial port absent; confirm COM number and CH340/board driver in Device Manager')}
    if(!('FanDependencies.NativeLoader' -as [type])){
        Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; namespace FanDependencies { public static class NativeLoader { [DllImport("kernel32",CharSet=CharSet.Unicode)] public static extern IntPtr LoadLibrary(string path); [DllImport("kernel32")] public static extern bool FreeLibrary(IntPtr handle); } }'
    }
    $visa=$false;$handle=[FanDependencies.NativeLoader]::LoadLibrary('visa64.dll');if($handle -ne [IntPtr]::Zero){$visa=$true;[void][FanDependencies.NativeLoader]::FreeLibrary($handle)}
    if($cfg.scope.enabled -and !$visa){$missing.Add('NI-VISA 64-bit runtime not loadable; install official NI-VISA outside this package')}
    [ordered]@{schemaVersion='1.0';action='dependency_check';ready=($missing.Count -eq 0);powerShellVersion=$PSVersionTable.PSVersion.ToString();is64Bit=[Environment]::Is64BitProcess;availableSerialPorts=$ports;configuredPort=$cfg.serial.port;visa64Loadable=$visa;missing=@($missing.ToArray());hardwareOpened=$false;note='Presence check only; does not identify board or verify scope/wiring. Arduino compiler needed only for a new unprogrammed UNO.'}|ConvertTo-Json -Depth 6 -Compress
    if($missing.Count -gt 0){exit 1}
}catch{[Console]::Error.WriteLine($_.Exception.Message);[ordered]@{schemaVersion='1.0';action='dependency_check';ready=$false;missing=@($_.Exception.Message);hardwareOpened=$false}|ConvertTo-Json -Compress;exit 1}
