$studio = 'C:\Users\50174\Documents\deepseek-harness\default-workspace\DropBridgeStudio'
$py = 'C:\Users\50174\AppData\Local\Programs\Python\Python312\pythonw.exe'
$shot = 'C:\Users\50174\AppData\Local\Programs\Python\Python312\python.exe'
Set-Location $studio

foreach ($page in @('transfers','logs','doctor','settings')) {
    Get-Process pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $py } | ForEach-Object { $_.Kill() }
    Start-Sleep -Milliseconds 700
    Start-Process -FilePath $py -ArgumentList '-m','app.main','--page',$page -WorkingDirectory $studio `
        -RedirectStandardOutput "$studio\data\ui-$page.out.log" -RedirectStandardError "$studio\data\ui-$page.err.log"
    Start-Sleep -Seconds 6
    & $shot "tools\shot_window.py" "DropBridge Studio" "data\page-$page.png"
}
Get-Process pythonw -ErrorAction SilentlyContinue | Select-Object Id,MainWindowTitle | Format-Table -AutoSize | Out-String