# WeGame 置顶(以计划任务的高权限上下文运行, 才能对提权的 WeGame 窗口 SetWindowPos)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class WG {
    [DllImport("user32.dll")] public static extern IntPtr FindWindow(string cls, string title);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr after, int x, int y, int cx, int cy, uint flags);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@
$h = [WG]::FindWindow($null, 'WeGame')
if ($h -ne [IntPtr]::Zero) {
    # SWP_NOMOVE|SWP_NOSIZE|SWP_SHOWWINDOW = 0x0063; HWND_TOPMOST = -1
    [WG]::ShowWindow($h, 9) | Out-Null                    # SW_RESTORE(若被最小化)
    [WG]::SetWindowPos($h, [IntPtr](-1), 0, 0, 0, 0, 0x0063) | Out-Null
}
