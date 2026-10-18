# 전연결기(jeonnector) 실행 스크립트 (가상환경 활성화 여부 확인 후 프로그램 실행)
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$ActivateScript = Join-Path $VenvDir "Scripts\Activate.ps1"

if (-not (Test-Path $VenvPython)) {
    Write-Error "가상환경(.venv)을 찾을 수 없습니다: $VenvPython`n먼저 'python -m venv .venv' 및 패키지 설치를 수행해 주세요."
    exit 1
}

# 현재 세션에 프로젝트 가상환경(.venv)이 활성화되어 있는지 확인
$ResolvedVenv = (Resolve-Path $VenvDir).Path
$CurrentVenv = if ($env:VIRTUAL_ENV) {
    try { (Resolve-Path $env:VIRTUAL_ENV).Path } catch { $env:VIRTUAL_ENV }
} else {
    ""
}

if ($CurrentVenv -ne $ResolvedVenv) {
    if (Test-Path $ActivateScript) {
        Write-Host "[전연결기] 가상환경(.venv)을 활성화합니다..." -ForegroundColor Cyan
        . $ActivateScript
    }
}

$SrcPath = Join-Path $ProjectRoot "src"
if ($env:PYTHONPATH) {
    if (-not ($env:PYTHONPATH -split ";" | Where-Object { $_ -eq $SrcPath })) {
        $env:PYTHONPATH = "$SrcPath;$env:PYTHONPATH"
    }
} else {
    $env:PYTHONPATH = $SrcPath
}

& $VenvPython -m jeonnector.main @args
exit $LASTEXITCODE
