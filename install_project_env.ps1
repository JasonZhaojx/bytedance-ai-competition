param(
  [string]$Python = "",
  [string]$VenvPath = ".venv",
  [switch]$NoVenv,
  [switch]$Yes,
  [switch]$Dev,
  [switch]$Optional,
  [switch]$SkipPipUpgrade,
  [switch]$SkipPlaywright,
  [switch]$SkipCrawl4AI
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$RuntimePackages = @(
  "requests",
  "openai",
  "duckduckgo-search",
  "trafilatura",
  "beautifulsoup4",
  "lxml",
  "playwright",
  "crawl4ai",
  "python-dotenv",
  "tqdm",
  "pydantic",
  "python-dateutil"
)

$DevPackages = @(
  "pytest",
  "pytest-asyncio",
  "black",
  "flake8",
  "mypy"
)

$OptionalPackages = @(
  "langchain-openai"
)

function Write-Title {
  param([string]$Text)
  Write-Host ""
  Write-Host "== $Text ==" -ForegroundColor Cyan
}

function Show-InstallLogo {
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

function Read-YesNo {
  param(
    [string]$Prompt,
    [bool]$Default = $true
  )
  if ($Yes) {
    return $Default
  }
  $suffix = if ($Default) { "Y/n" } else { "y/N" }
  while ($true) {
    $answer = Read-Host "$Prompt [$suffix]"
    if ([string]::IsNullOrWhiteSpace($answer)) {
      return $Default
    }
    switch ($answer.Trim().ToLowerInvariant()) {
      "y" { return $true }
      "yes" { return $true }
      "是" { return $true }
      "n" { return $false }
      "no" { return $false }
      "否" { return $false }
      default { Write-Host "请回答 y/n 或 是/否。" -ForegroundColor Yellow }
    }
  }
}

function Invoke-Step {
  param(
    [string]$Title,
    [string]$File,
    [string[]]$Arguments,
    [bool]$Required = $true
  )
  Write-Title $Title
  Write-Host "> $File $($Arguments -join ' ')" -ForegroundColor DarkGray
  & $File @Arguments
  $code = if ($null -eq $LASTEXITCODE) { 0 } else { $LASTEXITCODE }
  if ($code -ne 0) {
    $message = "$Title 执行失败，退出码 $code。"
    if ($Required) {
      throw $message
    }
    Write-Warning $message
  }
}

function ConvertTo-FullPath {
  param([string]$PathText)
  if ([System.IO.Path]::IsPathRooted($PathText)) {
    return [System.IO.Path]::GetFullPath($PathText)
  }
  return [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $PathText))
}

function Test-PythonExecutable {
  param(
    [string]$PathText,
    [string]$Source
  )
  if ([string]::IsNullOrWhiteSpace($PathText)) {
    return $null
  }
  $candidate = $PathText.Trim('"')
  if (-not (Test-Path -LiteralPath $candidate)) {
    return $null
  }
  try {
    $probe = @(
      "import platform, sys",
      "print(sys.executable)",
      "print(platform.python_version())"
    ) -join "; "
    $output = @(& $candidate -c $probe 2>$null)
    if ($LASTEXITCODE -ne 0 -or $output.Count -lt 2) {
      return $null
    }
    $exe = [string]$output[0]
    $versionText = [string]$output[1]
    $version = $null
    [void][version]::TryParse($versionText, [ref]$version)
    return New-Object PSObject -Property @{
      Path = $exe
      VersionText = $versionText
      Version = $version
      Source = $Source
    }
  } catch {
    return $null
  }
}

function Add-PythonCandidate {
  param(
    [System.Collections.ArrayList]$Candidates,
    [hashtable]$Seen,
    [string]$PathText,
    [string]$Source
  )
  $info = Test-PythonExecutable -PathText $PathText -Source $Source
  if ($null -eq $info) {
    return
  }
  $key = $info.Path.ToLowerInvariant()
  if (-not $Seen.ContainsKey($key)) {
    $Seen[$key] = $true
    [void]$Candidates.Add($info)
  }
}

function Find-PythonCandidates {
  $candidates = New-Object System.Collections.ArrayList
  $seen = @{}

  foreach ($name in @("python", "python3")) {
    foreach ($cmd in @(Get-Command $name -ErrorAction SilentlyContinue)) {
      Add-PythonCandidate -Candidates $candidates -Seen $seen -PathText $cmd.Source -Source "PATH 命令: $name"
    }
  }

  foreach ($path in @(& where.exe python 2>$null)) {
    Add-PythonCandidate -Candidates $candidates -Seen $seen -PathText $path -Source "where python"
  }
  foreach ($path in @(& where.exe python3 2>$null)) {
    Add-PythonCandidate -Candidates $candidates -Seen $seen -PathText $path -Source "where python3"
  }

  $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
  if ($pyLauncher) {
    try {
      foreach ($line in @(& $pyLauncher.Source -0p 2>$null)) {
        if ($line -match "([A-Za-z]:\\.*python(?:\.exe)?)\s*$") {
          Add-PythonCandidate -Candidates $candidates -Seen $seen -PathText $Matches[1] -Source "py 启动器"
        }
      }
    } catch {
      Write-Host "检测到 py launcher，但它没有报告可用的 Python。" -ForegroundColor DarkGray
    }
  }

  $programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
  $patterns = @(
    (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
    (Join-Path $ProjectRoot "venv\Scripts\python.exe"),
    "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe",
    "$env:ProgramFiles\Python*\python.exe",
    "$programFilesX86\Python*\python.exe",
    "$env:USERPROFILE\anaconda3\python.exe",
    "$env:USERPROFILE\miniconda3\python.exe",
    "$env:USERPROFILE\mambaforge\python.exe",
    "$env:USERPROFILE\anaconda3\envs\*\python.exe",
    "$env:USERPROFILE\miniconda3\envs\*\python.exe",
    "C:\ProgramData\Anaconda3\python.exe",
    "C:\ProgramData\Miniconda3\python.exe",
    "C:\ProgramData\Anaconda3\envs\*\python.exe",
    "C:\ProgramData\Miniconda3\envs\*\python.exe"
  )

  foreach ($drive in @("C", "D", "E", "F")) {
    $patterns += @(
      "$drive`:\Python*\python.exe",
      "$drive`:\anaconda\python.exe",
      "$drive`:\Anaconda3\python.exe",
      "$drive`:\miniconda3\python.exe",
      "$drive`:\Miniconda3\python.exe",
      "$drive`:\anaconda\envs\*\python.exe",
      "$drive`:\Anaconda3\envs\*\python.exe",
      "$drive`:\miniconda3\envs\*\python.exe",
      "$drive`:\Miniconda3\envs\*\python.exe"
    )
  }

  foreach ($pattern in $patterns) {
    if ([string]::IsNullOrWhiteSpace($pattern)) {
      continue
    }
    foreach ($file in @(Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue | Where-Object { -not $_.PSIsContainer })) {
      Add-PythonCandidate -Candidates $candidates -Seen $seen -PathText $file.FullName -Source "常见路径"
    }
  }

  return @($candidates | Sort-Object @{ Expression = { $_.Version }; Descending = $true }, Path)
}

function Select-Python {
  if (-not [string]::IsNullOrWhiteSpace($Python)) {
    $info = Test-PythonExecutable -PathText $Python -Source "命令参数"
    if ($null -eq $info) {
      throw "-Python 指定的 Python 路径不可用：$Python"
    }
    return $info
  }

  Write-Title "搜索 Python 解释器"
  $candidates = @(Find-PythonCandidates)
  if ($candidates.Count -eq 0) {
    Write-Host "没有自动检测到可用的 Python 解释器。" -ForegroundColor Yellow
    $custom = Read-Host "请输入 python.exe 的完整路径"
    $info = Test-PythonExecutable -PathText $custom -Source "手动输入"
    if ($null -eq $info) {
      throw "手动输入的 Python 路径不可用：$custom"
    }
    return $info
  }

  for ($i = 0; $i -lt $candidates.Count; $i++) {
    $item = $candidates[$i]
    Write-Host ("[{0}] Python {1}  {2}  ({3})" -f ($i + 1), $item.VersionText, $item.Path, $item.Source)
  }
  Write-Host "[C] 手动输入路径"

  if ($Yes) {
    Write-Host "已传入 -Yes，自动选择列表中的第一个解释器。" -ForegroundColor DarkGray
    return $candidates[0]
  }

  while ($true) {
    $choice = Read-Host "请选择 Python"
    if ($choice.Trim().ToLowerInvariant() -eq "c") {
      $custom = Read-Host "请输入 python.exe 的完整路径"
      $info = Test-PythonExecutable -PathText $custom -Source "手动输入"
      if ($null -ne $info) {
        return $info
      }
      Write-Host "这个 Python 路径不可用。" -ForegroundColor Yellow
      continue
    }
    $index = 0
    if ([int]::TryParse($choice, [ref]$index) -and $index -ge 1 -and $index -le $candidates.Count) {
      return $candidates[$index - 1]
    }
    Write-Host "请输入列表中的编号，或输入 C 手动填写路径。" -ForegroundColor Yellow
  }
}

function Get-VenvPythonPath {
  param([string]$VenvRoot)
  return Join-Path $VenvRoot "Scripts\python.exe"
}

function Initialize-PythonTarget {
  param([object]$SelectedPython)
  $createVenv = -not $NoVenv
  if (-not $Yes -and -not $NoVenv) {
    $createVenv = Read-YesNo "是否在 '$VenvPath' 创建或复用独立虚拟环境？" $true
  }
  if (-not $createVenv) {
    return $SelectedPython.Path
  }

  $venvRoot = ConvertTo-FullPath $VenvPath
  $venvPython = Get-VenvPythonPath $venvRoot
  if (-not (Test-Path -LiteralPath $venvPython)) {
    Invoke-Step -Title "创建虚拟环境" -File $SelectedPython.Path -Arguments @("-m", "venv", $venvRoot)
  } else {
    Write-Host "复用已有虚拟环境：$venvRoot" -ForegroundColor DarkGray
  }
  return $venvPython
}

function Get-PythonScriptsDir {
  param([string]$PythonPath)
  $code = "import sysconfig; print(sysconfig.get_path('scripts') or '')"
  $output = & $PythonPath -c $code
  if ($LASTEXITCODE -eq 0 -and $output.Count -gt 0) {
    return [string]$output[0]
  }
  return Split-Path -Parent $PythonPath
}

function Find-EnvCli {
  param(
    [string]$PythonPath,
    [string]$Name
  )
  $scripts = Get-PythonScriptsDir -PythonPath $PythonPath
  foreach ($suffix in @(".exe", ".cmd", ".bat", "")) {
    $path = Join-Path $scripts "$Name$suffix"
    if (Test-Path -LiteralPath $path) {
      return $path
    }
  }
  $cmd = Get-Command $Name -ErrorAction SilentlyContinue
  if ($cmd) {
    return $cmd.Source
  }
  return $null
}

function Install-Packages {
  param([string]$PythonPath)
  if (-not $SkipPipUpgrade) {
    Invoke-Step -Title "升级 pip 基础工具" -File $PythonPath -Arguments @("-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel")
  }

  $runtimeArgs = @("-m", "pip", "install", "--upgrade") + $RuntimePackages
  Invoke-Step -Title "安装项目运行依赖" -File $PythonPath -Arguments $runtimeArgs

  $installDev = $Dev
  if (-not $Yes -and -not $Dev) {
    $installDev = Read-YesNo "是否安装开发和测试依赖？" $false
  }
  if ($installDev) {
    $devArgs = @("-m", "pip", "install", "--upgrade") + $DevPackages
    Invoke-Step -Title "安装开发和测试依赖" -File $PythonPath -Arguments $devArgs
  }

  $installOptional = $Optional
  if (-not $Yes -and -not $Optional) {
    $installOptional = Read-YesNo "是否安装可选增强依赖？" $false
  }
  if ($installOptional) {
    foreach ($package in $OptionalPackages) {
      Invoke-Step -Title "安装可选依赖：$package" -File $PythonPath -Arguments @("-m", "pip", "install", "--upgrade", $package) -Required $false
    }
  }
}

function Initialize-Playwright {
  param([string]$PythonPath)
  if ($SkipPlaywright) {
    return
  }
  if (Read-YesNo "是否初始化 Playwright 的 Chromium 浏览器？" $true) {
    Invoke-Step -Title "安装 Playwright Chromium 浏览器" -File $PythonPath -Arguments @("-m", "playwright", "install", "chromium") -Required $false
  }
}

function Initialize-Crawl4AI {
  param([string]$PythonPath)
  if ($SkipCrawl4AI) {
    return
  }
  if (-not (Read-YesNo "是否初始化 Crawl4AI 浏览器和运行环境？" $true)) {
    return
  }

  $setup = Find-EnvCli -PythonPath $PythonPath -Name "crawl4ai-setup"
  if ($setup) {
    Invoke-Step -Title "运行 crawl4ai-setup" -File $setup -Arguments @() -Required $false
  } else {
    Write-Warning "没有找到 crawl4ai-setup，将回退到 Playwright Chromium 初始化。"
    Invoke-Step -Title "回退安装 Playwright Chromium 浏览器" -File $PythonPath -Arguments @("-m", "playwright", "install", "chromium") -Required $false
  }

  $doctor = Find-EnvCli -PythonPath $PythonPath -Name "crawl4ai-doctor"
  if ($doctor -and (Read-YesNo "是否运行 crawl4ai-doctor 环境诊断？" $false)) {
    Invoke-Step -Title "运行 crawl4ai-doctor" -File $doctor -Arguments @() -Required $false
  }
}

function Verify-Imports {
  param([string]$PythonPath)
  $code = @"
import importlib
mods = [
    ("requests", "requests"),
    ("openai", "openai"),
    ("duckduckgo-search", "duckduckgo_search"),
    ("trafilatura", "trafilatura"),
    ("beautifulsoup4", "bs4"),
    ("lxml", "lxml"),
    ("playwright", "playwright"),
    ("crawl4ai", "crawl4ai"),
    ("python-dotenv", "dotenv"),
    ("tqdm", "tqdm"),
    ("pydantic", "pydantic"),
    ("python-dateutil", "dateutil"),
]
missing = []
for package, module in mods:
    try:
        importlib.import_module(module)
    except Exception as exc:
        missing.append(f"{package} ({exc.__class__.__name__}: {exc})")
if missing:
    print("以下依赖缺失或导入异常:")
    for item in missing:
        print(" - " + item)
    raise SystemExit(1)
print("核心依赖导入检查通过。")
"@
  Invoke-Step -Title "验证核心依赖导入" -File $PythonPath -Arguments @("-c", $code) -Required $false
}

function Write-LocalEnvConfig {
  param([string]$PythonPath)
  $pythonFullPath = [System.IO.Path]::GetFullPath($PythonPath)
  $configPath = Join-Path $ProjectRoot ".local_env.bat"
  $pythonPathFile = Join-Path $ProjectRoot ".local_python_path.txt"
  $venvRoot = ConvertTo-FullPath $VenvPath
  $venvPython = Get-VenvPythonPath $venvRoot
  $venvValue = ""
  if ((Test-Path -LiteralPath $venvPython) -and ($pythonFullPath -ieq [System.IO.Path]::GetFullPath($venvPython))) {
    $venvValue = $venvRoot
  }

  $lines = @(
    "@echo off",
    "set `"COMPETITOR_AI_PROJECT_ROOT=$ProjectRoot`"",
    "set `"COMPETITOR_AI_PYTHON=$pythonFullPath`"",
    "set `"COMPETITOR_AI_VENV=$venvValue`""
  )
  $localEncoding = [System.Text.Encoding]::Default
  [System.IO.File]::WriteAllLines($configPath, $lines, $localEncoding)
  [System.IO.File]::WriteAllText($pythonPathFile, $pythonFullPath, $localEncoding)
  Write-Host "本地环境配置已写入：$configPath" -ForegroundColor Green
  Write-Host "本地 Python 路径已写入：$pythonPathFile" -ForegroundColor Green
}

try {
  Show-InstallLogo
  Write-Title "项目 Python 环境安装向导"
  Write-Host "项目目录：$ProjectRoot"

  $selected = Select-Python
  Write-Host ("已选择：Python {0}，路径：{1}" -f $selected.VersionText, $selected.Path) -ForegroundColor Green
  if ($selected.Version -and $selected.Version -lt [version]"3.10") {
    Write-Warning "建议使用 Python 3.10 或更高版本。当前选择版本：$($selected.VersionText)"
  }

  $targetPython = Initialize-PythonTarget -SelectedPython $selected
  Write-Host "安装目标解释器：$targetPython" -ForegroundColor Green

  Install-Packages -PythonPath $targetPython
  Initialize-Playwright -PythonPath $targetPython
  Initialize-Crawl4AI -PythonPath $targetPython
  Verify-Imports -PythonPath $targetPython
  Write-LocalEnvConfig -PythonPath $targetPython

  Write-Title "安装完成"
  Write-Host "本项目使用的 Python：$targetPython" -ForegroundColor Green
  $finalVenvRoot = ConvertTo-FullPath $VenvPath
  $finalVenvPython = Get-VenvPythonPath $finalVenvRoot
  if ((Test-Path -LiteralPath $finalVenvPython) -and ([System.IO.Path]::GetFullPath($targetPython) -ieq [System.IO.Path]::GetFullPath($finalVenvPython))) {
    $activate = Join-Path $finalVenvRoot "Scripts\Activate.ps1"
    if (Test-Path -LiteralPath $activate) {
      Write-Host "激活环境命令："
      Write-Host "  . `"$activate`"" -ForegroundColor Cyan
    }
  }
} catch {
  Write-Host ""
  Write-Host "安装已停止：$($_.Exception.Message)" -ForegroundColor Red
  exit 1
}
