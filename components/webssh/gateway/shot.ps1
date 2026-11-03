# shot.ps1 — 台架机远程截图
# Session 0（SSH 服务会话）看不到 Session 1 的桌面，CopyFromScreen 只会拿到黑屏/异常。
# 策略：先试真截屏并做非空判定，失败或全黑则回退到 C:\fc_pull 下最近一张 bmp/png。
$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$mode = 'none'
$bytes = $null

# --- 1) 尝试 CopyFromScreen ---
try {
  Add-Type -AssemblyName System.Windows.Forms, System.Drawing
  $b = [System.Windows.Forms.SystemInformation]::VirtualScreen
  if ($b.Width -gt 0 -and $b.Height -gt 0) {
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.X, $b.Y, 0, 0, $bmp.Size)
    $g.Dispose()
    # 全黑判定：抽样 9 个点，全为黑则认为是 Session 0 空桌面
    $nonBlack = 0
    foreach ($fx in 0.1,0.5,0.9) { foreach ($fy in 0.1,0.5,0.9) {
      $px = $bmp.GetPixel([int]($b.Width*$fx), [int]($b.Height*$fy))
      if ($px.R -gt 8 -or $px.G -gt 8 -or $px.B -gt 8) { $nonBlack++ }
    }}
    if ($nonBlack -gt 0) {
      $ms = New-Object System.IO.MemoryStream
      $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
      $bytes = $ms.ToArray(); $ms.Dispose(); $mode = 'live-screen'
    }
    $bmp.Dispose()
  }
} catch { }

# --- 2) 回退：C:\fc_pull 下最近一张图 ---
if ($null -eq $bytes) {
  $f = Get-ChildItem -Path 'C:\fc_pull' -Include *.bmp,*.png,*.jpg -Recurse -File |
       Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if ($f) { $bytes = [System.IO.File]::ReadAllBytes($f.FullName); $mode = 'fallback-file:' + $f.FullName }
}

if ($null -eq $bytes) { Write-Output 'SHOT_ERR:no-image-available'; exit 1 }
Write-Output ('SHOT_MODE:' + $mode)
Write-Output 'SHOT_B64_BEGIN'
Write-Output ([Convert]::ToBase64String($bytes))
Write-Output 'SHOT_B64_END'
