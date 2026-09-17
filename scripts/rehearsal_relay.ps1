# 通用演练接力脚本（keep5_relay.ps1 泛化版）
# 用法:
#   powershell -File scripts\rehearsal_relay.ps1 -Name keep7r `
#     -Req ".tmp/arcbench-official/arc-bench/webapp/keep/requirements" `
#     -OutputDir ".tmp/rehearsal-keep7r" -Resume -MaxRelaunch 2
# 行为: 等待当前 python 退出 → 检查 completed.json → 未完成则
# --resume 接力（≤MaxRelaunch 次）；exit 0=交付完成即停。
# 日志: .tmp/rehearsal-<Name>.log（stdout+stderr 全量）
param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$Req,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [switch]$Resume,
    [switch]$VerifyOnly,
    [switch]$NoWait,
    [int]$MaxRelaunch = 2,
    [int]$DeadlineMinutes = 480
)
$ErrorActionPreference = "Continue"
Set-Location F:\token-burner
$env:OPENAI_API_KEY = "***REMOVED***"
$env:OPENAI_BASE_URL = "https://api.arc-bench.com/v1"
$env:MODEL = "openai/deepseek-v4-pro"
$env:ARCBENCH_OUTPUT_DIR = "F:\token-burner\$OutputDir"
$env:ARCBENCH_VISION = "on"
$py = "F:\token-burner\.venv\Scripts\python.exe"
$log = "F:\token-burner\.tmp\rehearsal-$Name.log"
$deadline = (Get-Date).AddMinutes($DeadlineMinutes)

function Wait-Idle {
    # 等待没有正在写本演练日志的 python 进程（轮询窗口 60s）。
    # Win32_Process 在受限环境可能挂起/无输出（keep7v 取证）：
    # 最多探测 3 轮，任何异常视为空闲继续。
    for ($i = 0; $i -lt 3; $i++) {
        try {
            $mine = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction Stop |
                Where-Object { $_.CommandLine -like "*$OutputDir*" }
            if (-not $mine) { return }
        } catch { return }
        Start-Sleep -Seconds 60
    }
}

function Test-Completed {
    if ($script:VerifyOnly) {
        $hits = Get-ChildItem "F:\token-burner\$OutputDir\projects\*\sessions\verify_final.json" -ErrorAction SilentlyContinue
        if (-not $hits) { return $false }
        foreach ($h in $hits) {
            try {
                $j = Get-Content $h.FullName -Raw | ConvertFrom-Json
                if ($j.ok) { return $true }
            } catch { }
        }
        return $false
    }
    $hits = Get-ChildItem "F:\token-burner\$OutputDir\projects\*\sessions\completed.json" -ErrorAction SilentlyContinue
    return ($null -ne $hits)
}

Write-Output ("[relay] $Name start " + (Get-Date))
if (-not $NoWait) {
    Wait-Idle
    # 兜底：Wait-Idle 最多等 3 轮探测（Win32_Process 在受限环境可能挂起，
    # keep7v 取证）——任何异常直接视为空闲继续
}
$relaunches = 0
while ((Get-Date) -lt $deadline) {
    if (Test-Completed) {
        Write-Output ("[relay] $Name completed normally " + (Get-Date))
        break
    }
    if ($relaunches -gt $MaxRelaunch) {
        Write-Output ("[relay] $Name 接力次数耗尽（$MaxRelaunch），停机等人 " + (Get-Date))
        break
    }
    if ($VerifyOnly) {
        $py_args = @("scripts/resume_verify.py", "--output-dir", $OutputDir)
    } else {
        $py_args = @("main.py", $Req, "--output-dir", $OutputDir,
            "--type", "web", "--mode", "auto")
        if ($Resume -or $relaunches -ge 1) { $py_args += "--resume" }
    }
    Write-Output ("[relay] $Name 接力 #$($relaunches + 1) (verifyonly=$VerifyOnly) " + (Get-Date))
    & $py @py_args *> $log
    $code = $LASTEXITCODE
    Write-Output ("[relay] $Name exited code=$code " + (Get-Date))
    if ($code -eq 0) { break }   # 交付完成
    $relaunches++
    Start-Sleep -Seconds 30
}
Write-Output ("[relay] $Name end " + (Get-Date))
