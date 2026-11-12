# Execute com PowerShell 5.1+; nenhum Python precisa ser instalado no host.
# O parser próprio preserva os argumentos --input/--job do contrato da CLI.
$ErrorActionPreference = 'Stop'
$boxArguments = @($args)
$boxRoot = $PSScriptRoot
$previousEncoding = [Console]::OutputEncoding
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$previousRoot = $env:WHISPER_BOX_HOST_ROOT
$env:WHISPER_BOX_HOST_ROOT = $boxRoot
$composeArguments = @('compose', '--project-directory', $boxRoot, '-f', (Join-Path $boxRoot 'compose.yaml'))
$exitCode = 1

function Write-BoxError([string] $code, [string] $message) {
    @{ error = @{ code = $code; message = $message } } | ConvertTo-Json -Compress
}

function Invoke-BoxCli([string[]] $toolArguments) {
    $jsonLines = @(& docker @composeArguments @toolArguments)
    $script:exitCode = $LASTEXITCODE
    if ($jsonLines.Count -eq 0) {
        Write-BoxError 'docker_error' 'Sem resposta do container. Verifique Docker Desktop e execute prepare.'
        if ($script:exitCode -eq 0) { $script:exitCode = 1 }
    } else {
        $jsonLines | Write-Output
    }
}

try {
    if ($boxArguments.Count -eq 0) {
        Write-BoxError 'invalid_arguments' 'Use prepare, start, stop, submit, status, wait, result ou logs.'
        $exitCode = 3
    } else {
        $command = $boxArguments[0]
        $rest = @($boxArguments | Select-Object -Skip 1)
        switch ($command) {
            'prepare' {
                & docker @composeArguments build worker | ForEach-Object { [Console]::Error.WriteLine($_) }
                if ($LASTEXITCODE -eq 0) {
                    & docker @composeArguments --profile setup run --rm --no-deps -T prepare
                }
                $exitCode = $LASTEXITCODE
            }
            'start' {
                & docker @composeArguments up -d --no-build --pull never --wait --wait-timeout 90 worker | ForEach-Object { [Console]::Error.WriteLine($_) }
                $exitCode = $LASTEXITCODE
                if ($exitCode -eq 0) { '{"status":"ready"}' }
            }
            'stop' {
                & docker @composeArguments stop worker | ForEach-Object { [Console]::Error.WriteLine($_) }
                $exitCode = $LASTEXITCODE
                if ($exitCode -eq 0) { '{"status":"stopped"}' }
            }
            'logs' {
                & docker @composeArguments logs --tail 50 worker
                $exitCode = $LASTEXITCODE
            }
            'submit' {
                $inputIndex = [Array]::IndexOf($rest, '--input')
                if ($inputIndex -lt 0 -or $inputIndex + 1 -ge $rest.Count) {
                    Write-BoxError 'invalid_arguments' 'Informe --input com o caminho da gravacao.'
                    $exitCode = 3
                    break
                }
                if (-not (Test-Path -LiteralPath $rest[$inputIndex + 1] -PathType Leaf)) {
                    Write-BoxError 'input_not_found' 'Informe um arquivo de midia existente.'
                    $exitCode = 3
                    break
                }
                $inputPath = (Resolve-Path -LiteralPath $rest[$inputIndex + 1]).Path
                $extension = [System.IO.Path]::GetExtension($inputPath)
                $containerPath = '/source/recording' + $extension
                $rest[$inputIndex + 1] = $containerPath
                $mount = $inputPath + ':' + $containerPath + ':ro'
                Invoke-BoxCli (@('--profile', 'tools', 'run', '--rm', '--no-deps', '-T', '--volume', $mount, 'cli', 'submit') + $rest)
            }
            { $_ -in 'status', 'wait', 'result' } {
                Invoke-BoxCli (@('--profile', 'tools', 'run', '--rm', '--no-deps', '-T', 'cli', $command) + $rest)
            }
            default {
                Write-BoxError 'invalid_arguments' 'Comando desconhecido.'
                $exitCode = 3
            }
        }
        if ($exitCode -ne 0 -and $command -in 'start', 'prepare', 'stop') {
            Write-BoxError 'docker_error' 'Falha no Docker. Consulte stderr, verifique Docker Desktop e execute prepare antes de start.'
        }
    }
} catch {
    Write-BoxError 'operational_error' 'Nao foi possivel executar o comando. Verifique o caminho, Docker Desktop e a preparacao inicial.'
    $exitCode = 1
} finally {
    $env:WHISPER_BOX_HOST_ROOT = $previousRoot
    [Console]::OutputEncoding = $previousEncoding
}
exit $exitCode
