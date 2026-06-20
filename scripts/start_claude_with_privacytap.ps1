[CmdletBinding()]
param(
    [string]$ConfigPath,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$exampleConfig = Join-Path $projectRoot "privacytap.claude.env.example"

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $projectRoot "privacytap.claude.env"
}
elseif (-not [System.IO.Path]::IsPathRooted($ConfigPath)) {
    $ConfigPath = Join-Path $projectRoot $ConfigPath
}

function Read-PrivacyTapConfig {
    param([string]$Path)

    $values = @{}
    foreach ($rawLine in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            continue
        }

        $parts = $line.Split([char[]]"=", 2)
        if ($parts.Count -ne 2) {
            throw "配置行格式错误：$line"
        }

        $name = $parts[0].Trim()
        $value = $parts[1].Trim()
        $values[$name] = $value
    }
    return $values
}

function Test-TcpPort {
    param(
        [string]$HostName,
        [int]$Port
    )

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync($HostName, $Port)
        return $task.Wait(300) -and $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Stop-ProjectPrivacyTap {
    param([string]$Root)

    $escapedRoot = [regex]::Escape($Root)
    $processes = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine -match $escapedRoot -and
            $_.CommandLine -match "privacytap(\.exe)?[\""]?\s+start"
        }

    foreach ($process in $processes) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    Copy-Item -LiteralPath $exampleConfig -Destination $ConfigPath
    Write-Host "已创建配置文件：" -ForegroundColor Yellow
    Write-Host $ConfigPath
    Write-Host "请填写四项配置后，再次运行 start-privacytap-claude.cmd。"
    exit 2
}

$config = Read-PrivacyTapConfig -Path $ConfigPath
$requiredKeys = @(
    "PRIVACYTAP_UPSTREAM_BASE_URL",
    "ANTHROPIC_API_KEY",
    "CLAUDE_MODEL",
    "PRIVACYTAP_OUTPUT_DIR"
)

foreach ($key in $requiredKeys) {
    if (-not $config.ContainsKey($key) -or
        [string]::IsNullOrWhiteSpace($config[$key])) {
        throw "配置缺失：$key"
    }
}

$upstreamBaseUrl = $config["PRIVACYTAP_UPSTREAM_BASE_URL"].TrimEnd("/")
$apiKey = $config["ANTHROPIC_API_KEY"]
$model = $config["CLAUDE_MODEL"]
$outputDir = $config["PRIVACYTAP_OUTPUT_DIR"]

if ($upstreamBaseUrl -match "your-relay" -or
    $apiKey -match "your-api-key" -or
    $model -match "your-supported") {
    throw "配置文件仍包含示例值，请填写真实 Base URL、API Key 和模型名。"
}

$parsedUrl = $null
if (-not [uri]::TryCreate(
        $upstreamBaseUrl,
        [System.UriKind]::Absolute,
        [ref]$parsedUrl
    ) -or $parsedUrl.Scheme -notin @("http", "https")) {
    throw "PRIVACYTAP_UPSTREAM_BASE_URL 必须是有效的 HTTP/HTTPS 地址。"
}

if (-not [System.IO.Path]::IsPathRooted($outputDir)) {
    $outputDir = Join-Path $projectRoot $outputDir
}
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
$outputDir = (Resolve-Path -LiteralPath $outputDir).Path

$privacyTapExe = Join-Path $projectRoot ".venv\Scripts\privacytap.exe"
if (-not (Test-Path -LiteralPath $privacyTapExe)) {
    throw "找不到 $privacyTapExe，请先创建虚拟环境并安装项目。"
}

$claudeCommand = Get-Command claude -ErrorAction SilentlyContinue
if ($null -eq $claudeCommand) {
    throw "找不到 claude 命令，请先安装 Claude Code。"
}

Write-Host ""
Write-Host "PrivacyTap 配置检查通过" -ForegroundColor Green
Write-Host "  上游地址：$upstreamBaseUrl"
Write-Host "  模型名称：$model"
Write-Host "  审计目录：$outputDir"
Write-Host "  API Key：已加载（不会显示）"

if ($CheckOnly) {
    Write-Host "CheckOnly 完成，未启动任何进程。"
    exit 0
}

$proxyPort = 8080
$proxyProcess = $null
$createdProxyPids = @()
$launcherLogDir = Join-Path $outputDir "_launcher"
New-Item -ItemType Directory -Path $launcherLogDir -Force | Out-Null
$stdoutLog = Join-Path $launcherLogDir "privacytap.stdout.log"
$stderrLog = Join-Path $launcherLogDir "privacytap.stderr.log"

try {
    Stop-ProjectPrivacyTap -Root $projectRoot
    Start-Sleep -Milliseconds 500

    if (Test-TcpPort -HostName "127.0.0.1" -Port $proxyPort) {
        throw "端口 8080 已被其他程序占用，请关闭占用程序后重试。"
    }

    $beforePids = @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty ProcessId
    )

    $arguments = @(
        "start",
        "--provider", "anthropic",
        "--upstream-base-url", $upstreamBaseUrl,
        "--archive-dir", "`"$outputDir`""
    )

    $proxyProcess = Start-Process `
        -FilePath $privacyTapExe `
        -ArgumentList $arguments `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru

    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-TcpPort -HostName "127.0.0.1" -Port $proxyPort) {
            break
        }
        if ($proxyProcess.HasExited) {
            break
        }
        Start-Sleep -Milliseconds 250
    }

    if (-not (Test-TcpPort -HostName "127.0.0.1" -Port $proxyPort)) {
        $details = ""
        if (Test-Path -LiteralPath $stderrLog) {
            $details = Get-Content -LiteralPath $stderrLog -Raw
        }
        throw "PrivacyTap 启动失败。错误日志：$stderrLog`n$details"
    }

    $createdProxyPids = @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.ProcessId -notin $beforePids -and
                $_.CommandLine -and
                $_.CommandLine -match "privacytap(\.exe)?[\""]?\s+start"
            } |
            Select-Object -ExpandProperty ProcessId
    )

    Remove-Item Env:ANTHROPIC_AUTH_TOKEN -ErrorAction SilentlyContinue
    $env:ANTHROPIC_BASE_URL = "http://127.0.0.1:8080"
    $env:ANTHROPIC_API_KEY = $apiKey

    Write-Host ""
    Write-Host "PrivacyTap 已启动：http://127.0.0.1:8080" -ForegroundColor Green
    Write-Host "正在启动 Claude Code……" -ForegroundColor Cyan
    Write-Host "退出 Claude 后，脚本会自动关闭本次代理。"
    Write-Host ""

    Push-Location $projectRoot
    try {
        & $claudeCommand.Source `
            --bare `
            --setting-sources "project,local" `
            --model $model
    }
    finally {
        Pop-Location
    }
}
finally {
    foreach ($processId in $createdProxyPids) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $proxyProcess -and -not $proxyProcess.HasExited) {
        Stop-Process -Id $proxyProcess.Id -Force -ErrorAction SilentlyContinue
    }

    $latestTrace = Get-ChildItem `
        -LiteralPath $outputDir `
        -Filter "*_privacy.md" `
        -File `
        -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    Write-Host ""
    Write-Host "PrivacyTap 已停止。"
    if ($null -ne $latestTrace) {
        Write-Host "最新审计记录：" -ForegroundColor Green
        Write-Host $latestTrace.FullName
    }
    else {
        Write-Host "本次未生成审计记录，请确认 Claude 已成功发送消息。" `
            -ForegroundColor Yellow
    }
}
