# Ensaio de integracao. Dados e relatorio ficam em logs/, fora do Git.
$ErrorActionPreference = 'Stop'
$inputArguments = @($args)
if ($inputArguments.Count -ne 2 -or $inputArguments[0] -ne '--input') {
    throw 'Use smoke.ps1 --input CAMINHO_DA_GRAVACAO'
}
$projectRoot = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $projectRoot 'whisper-box.ps1'
$logs = Join-Path $projectRoot 'logs'
$fixtures = Join-Path $logs 'fixtures'
New-Item -ItemType Directory -Force -Path $fixtures | Out-Null
$results = New-Object System.Collections.Generic.List[object]

function Invoke-Box([string[]] $arguments, [int[]] $allowed = @(0)) {
    $output = @(& powershell -NoProfile -ExecutionPolicy Bypass -File $runner @arguments)
    $code = $LASTEXITCODE
    if ($code -notin $allowed) { throw ('Comando falhou: ' + $arguments[0] + ', codigo=' + $code + ', resposta=' + ($output -join '')) }
    if ($output.Count -ne 1) { throw 'stdout deve conter exatamente uma linha JSON.' }
    $response = $output[0] | ConvertFrom-Json
    return @{ code = $code; body = $response }
}

function Await-Job([string] $jobId, [int] $totalSeconds = 1800) {
    $deadline = [DateTime]::UtcNow.AddSeconds($totalSeconds)
    do {
        $response = Invoke-Box @('wait', '--job', $jobId, '--timeout', '30') @(0, 1, 2)
        if ([DateTime]::UtcNow -gt $deadline) { throw 'Prazo total do ensaio excedido; o trabalho continua no worker.' }
    } while ($response.code -eq 2)
    return $response
}

Push-Location $projectRoot
try {
    Invoke-Box @('start') | Out-Null
    $real = Invoke-Box @('submit', '--input', $inputArguments[1])
    $duplicate = Invoke-Box @('submit', '--input', $inputArguments[1])
    if (-not $duplicate.body.reused -or $duplicate.body.job_id -ne $real.body.job_id) { throw 'Deduplicacao incorreta.' }
    $completed = Await-Job $real.body.job_id
    if ($completed.code -ne 0) { throw 'A gravacao real falhou.' }
    foreach ($property in $completed.body.files.PSObject.Properties) {
        if (-not (Test-Path -LiteralPath $property.Value)) { throw 'Caminho de saida inacessivel pelo Windows.' }
    }
    $metadata = Get-Content -Raw -Encoding UTF8 $completed.body.files.metadata | ConvertFrom-Json
    if ($metadata.segments -le 0) { throw 'A gravacao real nao produziu segmentos.' }
    $results.Add(@{ case = 'real-recording'; job_id = $real.body.job_id; metadata = $metadata })

    # Sem inferencia: apenas gera fixtures, com limites do container auxiliar.
    & docker compose --profile tools run --rm --no-deps -T --volume ($fixtures + ':/fixtures') --entrypoint python cli /app/tests/make_fixtures.py /fixtures
    if ($LASTEXITCODE -ne 0) { throw 'Falha na geracao de fixtures.' }
    foreach ($file in Get-ChildItem -LiteralPath $fixtures -File) {
        $submission = Invoke-Box @('submit', '--input', $file.FullName)
        $result = Await-Job $submission.body.job_id
        if ($file.Name -eq 'invalido.mp4') {
            if ($result.code -ne 1 -or $result.body.error.code -ne 'invalid_media') { throw 'Midia invalida deveria falhar.' }
            $results.Add(@{ case = $file.Name; job_id = $submission.body.job_id; status = 'expected_failure' })
        } else {
            if ($result.code -ne 0) { throw ('Falha no formato ' + $file.Extension) }
            $metadata = Get-Content -Raw -Encoding UTF8 $result.body.files.metadata | ConvertFrom-Json
            if (-not $metadata.no_speech) { throw 'Silencio deveria gerar zero segmentos.' }
            $results.Add(@{ case = $file.Name; job_id = $submission.body.job_id; metadata = $metadata })
        }
    }
    $report = @{ timestamp = [DateTime]::UtcNow.ToString('o'); results = @($results.ToArray()) }
    $report | ConvertTo-Json -Depth 10 | Set-Content -Encoding UTF8 (Join-Path $logs 'smoke-result.json')
    Write-Output ('Ensaio aprovado: ' + $results.Count + ' casos; relatorio local em logs/smoke-result.json.')
} finally {
    Pop-Location
}
