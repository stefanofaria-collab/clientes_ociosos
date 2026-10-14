#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -e .env ]]; then cp .env.example .env; echo 'Edite .env e configure a conexao MySQL'; fi
if [[ ! -f .venv/bin/python ]]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -q -r requirements.txt
.venv/bin/python run.py
