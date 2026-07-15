# 洛克王国繁育规划器 - 本地服务器启动脚本
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "洛克王国繁育规划器 - 本地服务器" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "正在启动本地HTTP服务器..." -ForegroundColor Yellow
Write-Host "服务器将运行在: http://localhost:8000" -ForegroundColor Green
Write-Host ""
Write-Host "请在浏览器中打开以下地址:" -ForegroundColor White
Write-Host "http://localhost:8000/roco_shiny_breeding_planner.html" -ForegroundColor Cyan
Write-Host ""
Write-Host "按 Ctrl+C 停止服务器" -ForegroundColor Gray
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 切换到脚本所在目录
Set-Location -Path $PSScriptRoot

# 尝试使用Python
try {
    Write-Host "尝试使用Python启动服务器..." -ForegroundColor Yellow
    python -m http.server 8000
    exit
} catch {
    Write-Host "Python不可用，尝试使用PowerShell内置功能..." -ForegroundColor Gray
}

# 如果Python不可用，使用简单的PowerShell服务器
Write-Host "使用PowerShell内置HTTP服务器..." -ForegroundColor Yellow

$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://localhost:8000/")
$listener.Start()

Write-Host "服务器已启动！按 Ctrl+C 停止" -ForegroundColor Green

try {
    while ($listener.IsListening) {
        $context = $listener.GetContext()
        $request = $context.Request
        $response = $context.Response
        $url = $request.Url.LocalPath
        
        # 默认文件
        if ($url -eq "/") {
            $url = "/roco_shiny_breeding_planner.html"
        }
        
        $path = Join-Path -Path $PSScriptRoot -ChildPath $url.TrimStart("/")
        
        if (Test-Path -Path $path -PathType Leaf) {
            $content = [System.IO.File]::ReadAllBytes($path)
            $extension = [System.IO.Path]::GetExtension($path)
            
            # 设置Content-Type
            switch ($extension) {
                ".html" { $response.ContentType = "text/html; charset=utf-8" }
                ".css"  { $response.ContentType = "text/css; charset=utf-8" }
                ".js"   { $response.ContentType = "application/javascript; charset=utf-8" }
                ".json" { $response.ContentType = "application/json; charset=utf-8" }
                ".png"  { $response.ContentType = "image/png" }
                ".jpg"  { $response.ContentType = "image/jpeg" }
                ".gif"  { $response.ContentType = "image/gif" }
                ".svg"  { $response.ContentType = "image/svg+xml" }
                default { $response.ContentType = "application/octet-stream" }
            }
            
            $response.ContentLength64 = $content.Length
            $response.OutputStream.Write($content, 0, $content.Length)
        } else {
            $response.StatusCode = 404
            $message = [System.Text.Encoding]::UTF8.GetBytes("404 - File not found")
            $response.ContentLength64 = $message.Length
            $response.OutputStream.Write($message, 0, $message.Length)
        }
        
        $response.Close()
    }
} finally {
    $listener.Stop()
    Write-Host ""
    Write-Host "服务器已停止" -ForegroundColor Gray
}
