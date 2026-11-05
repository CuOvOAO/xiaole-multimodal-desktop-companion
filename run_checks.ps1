$ErrorActionPreference = "Stop"
$Python = "F:\anaconda3\python.exe"
$OldQt = $env:QT_QPA_PLATFORM
$OldPlugins = $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD
$OldEncoding = $env:PYTHONIOENCODING
$OldBytecode = $env:PYTHONDONTWRITEBYTECODE
Push-Location $PSScriptRoot
try {
    $env:QT_QPA_PLATFORM = "offscreen"
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    Write-Host "[1/4] Runtime"
    & $Python -c "import sys,numpy,scipy; print(sys.executable); print('numpy',numpy.__version__,'scipy',scipy.__version__); assert numpy.__version__=='1.24.3'"
    if ($LASTEXITCODE -ne 0) { throw "Runtime check failed" }
    Write-Host "[2/4] Compile"
    $Files = @("main.py", "config.py")
    $Files += (Get-ChildItem . -Filter test*.py).FullName
    $Files += (Get-ChildItem core,ui,tests,tools -Filter *.py -Recurse).FullName
    & $Python -m py_compile @Files
    if ($LASTEXITCODE -ne 0) { throw "Compile failed" }
    Write-Host "[3/4] Offline regression tests"
    & $Python -m pytest tests -q
    if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
    Write-Host "[4/4] Offscreen startup and shutdown"
    & $Python main.py --smoke-test
    if ($LASTEXITCODE -ne 0) { throw "Smoke test failed" }
    Write-Host "All offline checks passed. No online model quality is implied."
} finally {
    $env:QT_QPA_PLATFORM = $OldQt
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = $OldPlugins
    $env:PYTHONIOENCODING = $OldEncoding
    $env:PYTHONDONTWRITEBYTECODE = $OldBytecode
    Pop-Location
}
