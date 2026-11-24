#!/usr/bin/env bash
# Um comando para rodar o time de agentes (macOS / Linux):  ./rodar.sh
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -q -r requirements.txt
  .venv/bin/python -m playwright install chromium
fi
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Criei o arquivo .env. Preencha LLM_API_KEY e LLM_MODEL (e LLM_BASE_URL, se não for a OpenAI) e rode de novo."
  exit 1
fi
exec .venv/bin/python rodar.py "$@"
