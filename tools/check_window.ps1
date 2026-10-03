# Did the packaged app actually open its window?
#
#     powershell -ExecutionPolicy Bypass -File tools\check_window.ps1 `
#         -Exe C:\path\to\awrbc\awrbc.exe
#
# This exists because judging it by eye got it wrong three times in a row, and
# a release went out broken on the strength of one of those judgements:
#
#   - "the process is still running" means nothing. A failure shows a modal
#     message box, and a process sitting on one looks exactly like a healthy
#     one.
#   - MainWindowTitle means nothing either: report() titles the error box with
#     the application's own name, so both read "Advance Wars 1+2 map tool".
#   - Counting msedgewebview2.exe processes is worse than nothing. They are not
#     children of this app, and any browser on the machine has some - which is
#     how a working build got called broken.
#
# The window *class* is what separates them. A Win32 message box is #32770.
# pywebview's host window is a WindowsForms10.Window.
param(
  [Parameter(Mandatory = $true)][string]$Exe,
  [int]$WaitSeconds = 12
)

Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class AwrbcWin {
  public delegate bool Proc(IntPtr h, IntPtr p);
  [DllImport("user32.dll")] public static extern bool EnumWindows(Proc f, IntPtr p);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr h, Proc f, IntPtr p);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
}
"@

if (-not (Test-Path $Exe)) { Write-Output "no such file: $Exe"; exit 2 }

$proc = Start-Process -FilePath $Exe -PassThru
Start-Sleep -Seconds $WaitSeconds

$windows = New-Object System.Collections.ArrayList
$onTop = [AwrbcWin+Proc]{
  param($h, $l)
  $owner = 0
  [void][AwrbcWin]::GetWindowThreadProcessId($h, [ref]$owner)
  if ($owner -eq $proc.Id -and [AwrbcWin]::IsWindowVisible($h)) {
    $c = New-Object System.Text.StringBuilder 256
    [void][AwrbcWin]::GetClassName($h, $c, 256)
    [void]$windows.Add(@{ Handle = $h; Class = $c.ToString() })
  }
  return $true
}
[void][AwrbcWin]::EnumWindows($onTop, [IntPtr]::Zero)

$dialogs = @($windows | Where-Object { $_.Class -eq '#32770' })

Write-Output "exe      : $Exe"
Write-Output "pid      : $($proc.Id)   exited: $($proc.HasExited)"
foreach ($w in $windows) { Write-Output "window   : $($w.Class)" }

if ($dialogs.Count -gt 0) {
  Write-Output 'verdict  : FAILED - it is showing an error dialog'
  Write-Output ''
  foreach ($d in $dialogs) {
    $readKid = [AwrbcWin+Proc]{
      param($h, $l)
      $t = New-Object System.Text.StringBuilder 8192
      [void][AwrbcWin]::GetWindowTextW($h, $t, 8192)
      if ($t.Length -gt 20) { Write-Output $t.ToString() }
      return $true
    }
    [void][AwrbcWin]::EnumChildWindows($d.Handle, $readKid, [IntPtr]::Zero)
  }
  $code = 1
} elseif ($windows.Count -gt 0) {
  Write-Output 'verdict  : WINDOW OPENED'
  $code = 0
} elseif ($proc.HasExited) {
  # The dependable signal. A blocked build exits 1 every time, while whether
  # it manages to put a message box on screen first varies run to run for
  # reasons I could not pin down - so the exit code decides, not the dialog.
  Write-Output "verdict  : FAILED - exited with $($proc.ExitCode) and no window"
  if ($proc.ExitCode -eq 1) {
    Write-Output '           Run it by hand to see the message, or check for'
    Write-Output '           a zone mark:'
    Write-Output "           Get-ChildItem -Recurse '<folder>' | ForEach-Object {"
    Write-Output '             Get-Item $_.FullName -Stream Zone.Identifier -EA SilentlyContinue }'
  }
  $code = 1
} else {
  Write-Output 'verdict  : still running with no window - give it longer with'
  Write-Output '           -WaitSeconds, or it is wedged'
  $code = 1
}

# Only this process, never every awrbc on the machine: one of those killed a
# dialog somebody was still reading.
if (-not $proc.HasExited) {
  Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}
exit $code
