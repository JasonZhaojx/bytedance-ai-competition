param()

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

function Show-Logo {
  Clear-Host
  $logo = @'
   ____                           _   _ _                  _    ___
  / ___|___  _ __ ___  _ __   ___| |_(_) |_ ___  _ __     / \  |_ _|
 | |   / _ \| '_ ` _ \| '_ \ / _ \ __| | __/ _ \| '__|   / _ \  | |
 | |__| (_) | | | | | | |_) |  __/ |_| | || (_) | |     / ___ \ | |
  \____\___/|_| |_| |_| .__/ \___|\__|_|\__\___/|_|    /_/   \_\___|
                      |_|
'@
  Write-Host $logo -ForegroundColor Yellow
}

function Wait-Return {
  param([string]$Prompt = "按回车键返回菜单")
  [void](Read-Host $Prompt)
}

function Write-LocalPythonConfig {
  param([string]$PythonPath)

  $pythonFullPath = [System.IO.Path]::GetFullPath($PythonPath)
  $configPath = Join-Path $ProjectRoot ".local_env.bat"
  $pythonPathFile = Join-Path $ProjectRoot ".local_python_path.txt"
  $localEncoding = [System.Text.Encoding]::Default
  $lines = @(
    "@echo off",
    "set `"COMPETITOR_AI_PROJECT_ROOT=$ProjectRoot`"",
    "set `"COMPETITOR_AI_PYTHON=$pythonFullPath`"",
    "set `"COMPETITOR_AI_VENV=`""
  )

  [System.IO.File]::WriteAllLines($configPath, $lines, $localEncoding)
  [System.IO.File]::WriteAllText($pythonPathFile, $pythonFullPath, $localEncoding)
  Write-Host "已写入本地环境配置：" -ForegroundColor Green
  Write-Host "  $configPath"
  Write-Host "已保存 Python 路径：" -ForegroundColor Green
  Write-Host "  $pythonFullPath"
}

function Resolve-PythonExecutable {
  param([string]$InputText)

  if ([string]::IsNullOrWhiteSpace($InputText)) {
    return $null
  }

  $candidate = $InputText.Trim().Trim('"')
  try {
    $probe = "import sys; print(sys.executable)"
    $output = @(& $candidate -c $probe 2>$null)
    if ($LASTEXITCODE -ne 0 -or $output.Count -lt 1) {
      return $null
    }
    $resolved = [string]$output[0]
    if (Test-Path -LiteralPath $resolved) {
      return [System.IO.Path]::GetFullPath($resolved)
    }
    return $null
  } catch {
    return $null
  }
}

function Read-ConfiguredPython {
  $pythonPathFile = Join-Path $ProjectRoot ".local_python_path.txt"
  $configPath = Join-Path $ProjectRoot ".local_env.bat"
  $localEncoding = [System.Text.Encoding]::Default

  if (Test-Path -LiteralPath $pythonPathFile) {
    $saved = [System.IO.File]::ReadAllText($pythonPathFile, $localEncoding).Trim()
    if (-not [string]::IsNullOrWhiteSpace($saved)) {
      return $saved
    }
  }

  if (Test-Path -LiteralPath $configPath) {
    foreach ($line in [System.IO.File]::ReadAllLines($configPath, $localEncoding)) {
      if ($line -match '^set "COMPETITOR_AI_PYTHON=(.*)"$') {
        return $Matches[1]
      }
    }
  }

  $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
  if (Test-Path -LiteralPath $venvPython) {
    return $venvPython
  }

  return $null
}

function Invoke-InstallEnv {
  Show-Logo
  Write-Host ""
  Write-Host "正在启动安装向导..."
  Write-Host ""
  & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ProjectRoot "install_project_env.ps1")
  $code = if ($null -eq $LASTEXITCODE) { 0 } else { $LASTEXITCODE }
  Write-Host ""
  if ($code -eq 0) {
    Write-Host "安装完成，本地环境配置已写入 .local_env.bat。" -ForegroundColor Green
  } else {
    Write-Host "安装脚本返回错误，请查看上方日志。" -ForegroundColor Red
  }
  Wait-Return
}

function Set-ExistingPython {
  Show-Logo
  Write-Host ""
  Write-Host "请输入已经安装好依赖环境的 Python 解释器。"
  Write-Host "可以填写 python.exe 完整路径，也可以填写系统命令名：python / python3 / py"
  Write-Host "不要填写额外参数。"
  Write-Host ""

  $inputText = Read-Host "Python 路径或命令"
  $resolved = Resolve-PythonExecutable -InputText $inputText
  if ($null -eq $resolved) {
    Write-Host ""
    Write-Host "无法运行这个 Python 解释器：" -ForegroundColor Red
    Write-Host "  $inputText"
    Write-Host "请确认路径正确，或者输入 python / python3 / py。"
    Wait-Return
    return
  }

  Write-Host ""
  Write-LocalPythonConfig -PythonPath $resolved
  Wait-Return
}

function Start-WebServer {
  $python = Read-ConfiguredPython
  if ([string]::IsNullOrWhiteSpace($python)) {
    Write-Host ""
    Write-Host "未找到本地环境配置 .local_env.bat，也没有发现 .venv。" -ForegroundColor Yellow
    Write-Host "请先选择 [1] 安装/更新 Python 环境，或选择 [3] 指定已有 Python。"
    Wait-Return
    return
  }

  if (-not (Test-Path -LiteralPath $python)) {
    Write-Host ""
    Write-Host "保存的 Python 路径不存在：" -ForegroundColor Red
    Write-Host "  $python"
    Write-Host "请重新选择 [1] 安装/更新 Python 环境，或选择 [3] 指定已有 Python。"
    Wait-Return
    return
  }

  $port = "8000"
  Write-Host ""
  $portInput = Read-Host "请输入服务端口，直接回车使用 8000"
  if (-not [string]::IsNullOrWhiteSpace($portInput)) {
    $port = $portInput.Trim()
  }

  Show-Logo
  Write-Host ""
  Write-Host "使用 Python："
  Write-Host "  $python"
  Write-Host ""
  Write-Host "正在启动 Web 服务器："
  Write-Host "  http://127.0.0.1:$port"
  Write-Host ""
  & $python (Join-Path $ProjectRoot "backend\server.py") $port
  Write-Host ""
  Write-Host "服务器已退出。"
  Wait-Return
}

while ($true) {
  Show-Logo
  Write-Host ""
  Write-Host "[1] 安装/更新 Python 环境"
  Write-Host "[2] 使用本地 Python 启动 Web 服务器"
  Write-Host "[3] 使用我已经装好环境的 Python"
  Write-Host "[4] 退出"
  Write-Host ""

  $choice = Read-Host "请选择操作"
  switch ($choice.Trim()) {
    "1" { Invoke-InstallEnv }
    "2" { Start-WebServer }
    "3" { Set-ExistingPython }
    "4" { exit 0 }
    default {
      Write-Host ""
      Write-Host "输入无效，请重新选择。" -ForegroundColor Yellow
      Wait-Return
    }
  }
}
