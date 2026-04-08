#!/usr/bin/env pwsh
<#
.SYNOPSIS
    清理测试数据并运行全量测试

.DESCRIPTION
    1. 清理所有测试数据（知识库、配置、临时文件）
    2. 运行全量 pytest 测试
    3. 可选择是否保留测试数据（用于调试）

.EXAMPLE
    .\run_full_test.ps1
    清理数据并运行测试

.EXAMPLE
    .\run_full_test.ps1 -KeepData
    保留测试数据，仅运行测试

.EXAMPLE
    .\run_full_test.ps1 -CleanOnly
    仅清理数据，不运行测试
#>

param(
    [switch]$KeepData,      # 保留测试数据（用于调试）
    [switch]$CleanOnly,     # 仅清理，不运行测试
    [switch]$Verbose        # 显示详细输出
)

$ErrorActionPreference = "Stop"

# 颜色输出函数
function Write-Info($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Success($msg) { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warning($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Error($msg) { Write-Host "[ERR] $msg" -ForegroundColor Red }

# ==================== 清理函数 ====================

function Clean-TestData {
    Write-Info "开始清理测试数据..."
    
    $cleaned = @()
    
    # 1. 清理默认知识库
    $kbPaths = @(
        "$env:USERPROFILE\.zettelkasten",
        "$env:USERPROFILE\.zettelkasten-work",
        "$env:USERPROFILE\.zettelkasten-personal", 
        "$env:USERPROFILE\.zettelkasten-test",
        "$env:USERPROFILE\.zettelkasten-study"
    )
    
    foreach ($path in $kbPaths) {
        if (Test-Path $path) {
            try {
                Remove-Item -Recurse -Force $path -ErrorAction SilentlyContinue
                $cleaned += $path
                if ($Verbose) { Write-Success "删除: $path" }
            } catch {
                Write-Warning "无法删除: $path"
            }
        }
    }
    
    # 2. 清理全局配置
    $globalConfig = "$env:USERPROFILE\.zk_config.json"
    if (Test-Path $globalConfig) {
        Remove-Item -Force $globalConfig -ErrorAction SilentlyContinue
        $cleaned += $globalConfig
        if ($Verbose) { Write-Success "删除: $globalConfig" }
    }
    
    # 3. 清理旧版本配置（如果有）
    $oldConfig = "$env:USERPROFILE\.zk.json"
    if (Test-Path $oldConfig) {
        Remove-Item -Force $oldConfig -ErrorAction SilentlyContinue
        $cleaned += $oldConfig
    }
    
    # 4. 清理临时目录（超过1天的 zk 测试目录）
    $tempDirs = Get-ChildItem -Path $env:TEMP -Filter "zk_*" -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.CreationTime -lt (Get-Date).AddDays(-1) }
    
    foreach ($dir in $tempDirs) {
        try {
            Remove-Item -Recurse -Force $dir.FullName -ErrorAction SilentlyContinue
            $cleaned += $dir.FullName
            if ($Verbose) { Write-Success "删除临时目录: $($dir.Name)" }
        } catch {
            Write-Warning "无法删除临时目录: $($dir.Name)"
        }
    }
    
    if ($cleaned.Count -eq 0) {
        Write-Info "没有找到需要清理的测试数据"
    } else {
        Write-Success "已清理 $($cleaned.Count) 个项目"
    }
}

# ==================== 验证清理 ====================

function Test-Clean {
    $remaining = @()
    
    $paths = @(
        "$env:USERPROFILE\.zettelkasten",
        "$env:USERPROFILE\.zk_config.json"
    )
    
    foreach ($path in $paths) {
        if (Test-Path $path) {
            $remaining += $path
        }
    }
    
    if ($remaining.Count -gt 0) {
        Write-Warning "以下文件/目录仍然存在："
        $remaining | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow }
        return $false
    }
    
    return $true
}

# ==================== 运行测试 ====================

function Run-Tests {
    Write-Info "开始运行全量测试..."
    Write-Host ""
    
    $startTime = Get-Date
    
    # 构建 pytest 参数
    $pytestArgs = @(
        "tests/",
        "-v",
        "--tb=short"
    )
    
    if ($Verbose) {
        $pytestArgs += "--capture=no"  # 显示所有输出
    }
    
    try {
        uv run pytest @pytestArgs
        $exitCode = $LASTEXITCODE
    } catch {
        Write-Error "测试执行失败: $_"
        $exitCode = 1
    }
    
    $duration = (Get-Date) - $startTime
    
    Write-Host ""
    Write-Info "测试耗时: $($duration.ToString('hh\:mm\:ss'))"
    
    return $exitCode
}

# ==================== 主流程 ====================

Write-Host ""
Write-Host "========================================" -ForegroundColor Blue
Write-Host "  JFox 全量测试脚本" -ForegroundColor Blue
Write-Host "========================================" -ForegroundColor Blue
Write-Host ""

# 检查是否在正确目录
if (-not (Test-Path "pyproject.toml")) {
    Write-Error "请在项目根目录运行此脚本"
    exit 1
}

# 步骤 1: 清理数据（除非指定 -KeepData）
if (-not $KeepData) {
    Clean-TestData
    
    # 验证清理
    if (-not (Test-Clean)) {
        Write-Warning "清理不完全，但继续运行测试..."
    }
} else {
    Write-Info "跳过清理（-KeepData 模式）"
}

# 如果仅清理，退出
if ($CleanOnly) {
    Write-Success "清理完成"
    exit 0
}

# 步骤 2: 运行测试
$exitCode = Run-Tests

# 步骤 3: 结果输出
Write-Host ""
if ($exitCode -eq 0) {
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  所有测试通过！" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
} else {
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "  测试失败 (退出码: $exitCode)" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    
    if (-not $KeepData) {
        Write-Host ""
        Write-Info "提示：使用 .\run_full_test.ps1 -KeepData 可以保留数据用于调试"
    }
}

exit $exitCode
