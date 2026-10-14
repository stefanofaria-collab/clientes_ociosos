$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " CLIENTES OCIOSOS - VERSAO 2.2.0" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
if (-not (Test-Path '.env')) {
    Copy-Item '.env.example' '.env'
    Write-Host 'Primeira instalacao: arquivo .env criado. Confira a conexao MySQL e o SMTP.' -ForegroundColor Yellow
}
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    py -3 -m venv .venv
}
& '.venv\Scripts\python.exe' -m pip install -q -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Erro ao instalar dependencias.' }
Write-Host 'Acesse http://127.0.0.1:8515 (ou a porta do seu .env)' -ForegroundColor Green
& '.venv\Scripts\python.exe' run.py
