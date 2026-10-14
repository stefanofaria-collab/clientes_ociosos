# Opção interna: a versão para copiar e colar está na conversa.
# Download.zip deve estar na pasta Clientes Ociosos.
$ErrorActionPreference = 'Stop'
$dest = 'C:\Users\stefano.faria\Desktop\Projetos\clientes_ociosos'
$zip = Join-Path $dest 'Download.zip'
$temp = Join-Path $env:TEMP 'clientes_ociosos_update'
if (-not (Test-Path -LiteralPath $zip)) { throw "ZIP nao encontrado: $zip" }
if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force -Recurse }
try {
    Expand-Archive -LiteralPath $zip -DestinationPath $temp -Force
    $origem = Join-Path $temp 'clientes_ociosos'
    if (-not (Test-Path -LiteralPath (Join-Path $origem 'run.py'))) { throw 'ZIP invalido: run.py ausente.' }
    Get-ChildItem -LiteralPath $origem -Force |
        Where-Object { $_.Name -notin @('.env', '.venv', 'data', 'Download.zip') } |
        ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $dest -Recurse -Force
        }
    if (-not (Test-Path -LiteralPath (Join-Path $dest '.env'))) {
        Copy-Item -LiteralPath (Join-Path $dest '.env.example') -Destination (Join-Path $dest '.env')
    }
    Write-Host 'Clientes Ociosos 2.0.1 atualizado; .env e historico preservados.' -ForegroundColor Green
} finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
