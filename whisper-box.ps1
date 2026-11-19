# Compatibilidade: chamadores PowerShell existentes continuam funcionando.
# Toda a lógica está em whisper-box.py; este arquivo apenas localiza o Python 3.8+
# e repassa argumentos, stdout JSON, stderr e código de saída.
$ErrorActionPreference = 'Stop'
$boxArguments = @($args)
$runner = Join-Path $PSScriptRoot 'whisper-box.py'
$previousEncoding = [Console]::OutputEncoding
$previousIo = $env:PYTHONIOENCODING
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$env:PYTHONIOENCODING = 'utf-8'
$exitCode = 1

function Find-BoxPython {
    $probe = 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)'
    foreach ($candidate in @('py -3', 'python', 'python3')) {
        $parts = @($candidate -split ' ')
        if (-not (Get-Command $parts[0] -CommandType Application -ErrorAction SilentlyContinue)) { continue }
        $prefix = @($parts | Select-Object -Skip 1)
        $ErrorActionPreference = 'SilentlyContinue'
        & $parts[0] @prefix -c $probe 2>$null | Out-Null
        $found = $LASTEXITCODE -eq 0
        $ErrorActionPreference = 'Stop'
        if ($found) { return , $parts }
    }
    return $null
}

try {
    $python = Find-BoxPython
    if ($null -eq $python) {
        '{"error":{"code":"python_not_found","message":"Instale Python 3.8+ (py, python ou python3 no PATH) ou execute whisper-box.py diretamente."}}'
    } else {
        $prefix = @($python | Select-Object -Skip 1)
        & $python[0] @prefix $runner @boxArguments
        $exitCode = $LASTEXITCODE
    }
} catch {
    '{"error":{"code":"operational_error","message":"Nao foi possivel executar o wrapper Python."}}'
    $exitCode = 1
} finally {
    $env:PYTHONIOENCODING = $previousIo
    [Console]::OutputEncoding = $previousEncoding
}
exit $exitCode
