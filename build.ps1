$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ProductName = "CloudLight Overwatch YouTube Watcher"
$DistRoot = Join-Path $ProjectRoot "dist"
$ProductDir = Join-Path $DistRoot $ProductName
$ZipPath = Join-Path $DistRoot "CloudLight-Overwatch-YouTube-Watcher.zip"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "未找到 .venv。请先运行：python -m venv .venv"
}

& $Python -m pip install -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple -r (Join-Path $ProjectRoot "requirements-dev.txt")

if (Test-Path -LiteralPath $ProductDir) {
    $ResolvedDist = (Resolve-Path -LiteralPath $DistRoot).Path
    $ResolvedProduct = (Resolve-Path -LiteralPath $ProductDir).Path
    if (-not $ResolvedProduct.StartsWith($ResolvedDist + [IO.Path]::DirectorySeparatorChar)) {
        throw "拒绝清理 dist 目录之外的路径：$ResolvedProduct"
    }
    Remove-Item -LiteralPath $ProductDir -Recurse -Force
}
if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}

$IconPath = Join-Path $ProjectRoot "assets\app-icon.ico"
$IconArgs = @()
if (Test-Path -LiteralPath $IconPath) {
    $IconArgs = @("--icon", $IconPath)
}

& $Python -m PyInstaller `
    (Join-Path $ProjectRoot "src\main.py") `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name $ProductName `
    --distpath $DistRoot `
    --workpath (Join-Path $ProjectRoot "build") `
    --specpath $ProjectRoot `
    --add-data "$(Join-Path $ProjectRoot 'assets');assets" `
    --collect-all yt_dlp `
    @IconArgs

Copy-Item -LiteralPath (Join-Path $ProjectRoot "config.json") -Destination (Join-Path $ProductDir "config.json") -Force
New-Item -ItemType Directory -Path (Join-Path $ProductDir "profiles") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $ProductDir "logs") -Force | Out-Null
Compress-Archive -LiteralPath $ProductDir -DestinationPath $ZipPath -CompressionLevel Optimal

Write-Host "EXE: $(Join-Path $ProductDir ($ProductName + '.exe'))"
Write-Host "ZIP: $ZipPath"
