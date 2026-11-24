# Um comando para rodar o time de agentes (Windows / PowerShell):  .\rodar.ps1
# Na primeira vez cria o ambiente virtual, instala as dependências e o navegador do Operador de tela.
# Argumentos extras vão para o programa, por exemplo:  .\rodar.ps1 --verificar
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    Write-Host "Criando o ambiente virtual e instalando dependências..."
    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -q -r requirements.txt
    .\.venv\Scripts\python.exe -m playwright install chromium
}
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Criei o arquivo .env. Preencha LLM_API_KEY e LLM_MODEL (e LLM_BASE_URL, se não for a OpenAI) e rode de novo."
    exit 1
}
.\.venv\Scripts\python.exe rodar.py @args
