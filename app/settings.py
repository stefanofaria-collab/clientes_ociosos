"""Configuração local + descoberta segura do .env MySQL do ClickDados.

Não imprime credenciais; suporta instalações sob Desktop/Projetos e OneDrive.
"""
import os
from pathlib import Path
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent


def _read_env(path):
    try:
        p = Path(path).expanduser()
        if p.is_file():
            return {str(k).upper(): v for k, v in dotenv_values(p).items() if v is not None}
    except (OSError, ValueError):
        pass
    return {}


LOCAL = _read_env(ROOT / '.env')

# Se o banco já foi configurado neste app, dispensar outros arquivos .env.
DIRECT_MYSQL = {
    key: os.environ.get(key) or LOCAL.get(key, '')
    for key in ('DB_HOST', 'DB_NAME', 'DB_USER', 'DB_PASSWORD')
}


def value(name: str, default: str = '') -> str:
    return os.environ.get(name, LOCAL.get(name.upper(), default))


def _valid_source(data):
    return all(data.get(x) for x in ('DB_HOST', 'DB_NAME', 'DB_USER', 'DB_PASSWORD'))


def _potential_clickdados_paths():
    """Procura somente .env em pastas de projetos, nunca no disco inteiro."""
    base_dirs = [ROOT.parent, ROOT.parent.parent]
    home = Path(os.environ.get('USERPROFILE') or Path.home())
    base_dirs += [home / 'Desktop' / 'Projetos', home / 'OneDrive' / 'Desktop' / 'Projetos']
    one_drive = os.environ.get('OneDrive')
    if one_drive:
        base_dirs.append(Path(one_drive) / 'Desktop' / 'Projetos')
    seen = set()
    for base in base_dirs:
        try:
            base = base.resolve()
            if str(base).casefold() in seen or not base.is_dir():
                continue
            seen.add(str(base).casefold())
            for folder in ('gestao_clientes', 'gestao_comercial', 'clickdados', 'ClickDados'):
                for suffix in ('backend/.env', '.env'):
                    yield base / folder / suffix
            # Outros nomes de pasta de projeto, limitados a um nível.
            for project in base.iterdir():
                if project.is_dir() and any(token in project.name.lower() for token in ('gestao', 'clickdados')):
                    yield project / 'backend' / '.env'
                    yield project / '.env'
        except (OSError, PermissionError):
            continue


configured_path = value('CLICKDADOS_ENV_PATH').strip().strip('"').strip("'")
CLICKDADOS = {}
CLICKDADOS_ENV_SOURCE = ''
CLICKDADOS_ENV_WARNING = ''

if not _valid_source(DIRECT_MYSQL) and configured_path:
    CLICKDADOS = _read_env(configured_path)
    if _valid_source(CLICKDADOS):
        CLICKDADOS_ENV_SOURCE = str(Path(configured_path).expanduser())

# Procurar .env externo apenas quando faltar credencial direta.
if not _valid_source(DIRECT_MYSQL) and not _valid_source(CLICKDADOS):
    for candidate in _potential_clickdados_paths():
        alternative = _read_env(candidate)
        if _valid_source(alternative):
            CLICKDADOS, CLICKDADOS_ENV_SOURCE = alternative, str(candidate)
            if configured_path and Path(configured_path) != candidate:
                CLICKDADOS_ENV_WARNING = 'Caminho CLICKDADOS_ENV_PATH inválido/incompleto; .env do ClickDados localizado automaticamente.'
            break


def setting(name: str, default: str = '') -> str:
    key = name.upper()
    # Valor em branco no .env local não deve ocultar uma credencial existente no ClickDados.
    return (os.environ.get(key) or LOCAL.get(key) or CLICKDADOS.get(key) or default)


def flag(name: str, default=False) -> bool:
    return setting(name, 'true' if default else 'false').lower() in ('1', 'true', 'yes', 'sim')


DB_HOST = setting('DB_HOST')
DB_PORT = int(setting('DB_PORT', '3306'))
DB_NAME = setting('DB_NAME')
DB_USER = setting('DB_USER')
DB_PASSWORD = setting('DB_PASSWORD')
DB_CHARSET = setting('DB_CHARSET', 'utf8mb4')
DB_SSL = flag('DB_SSL')
DB_SSL_CA = setting('DB_SSL_CA')
MYSQL_CONFIGURADO = all([DB_HOST, DB_NAME, DB_USER, DB_PASSWORD])
# Modo demonstração é exclusivo para instalações sem vínculo com o ClickDados.
DEMO = not MYSQL_CONFIGURADO and not configured_path and not CLICKDADOS_ENV_SOURCE
APP_HOST = setting('APP_HOST', '127.0.0.1')
APP_PORT = int(setting('APP_PORT', '8515'))
TZ = setting('TZ', 'America/Sao_Paulo')
SMTP_HOST = setting('SMTP_HOST') or setting('CLICKDADOS_SMTP_HOST')
SMTP_PORT = int(setting('SMTP_PORT', setting('CLICKDADOS_SMTP_PORT', '587')))
SMTP_USER = setting('SMTP_USER') or setting('CLICKDADOS_SMTP_USER')
SMTP_PASS = setting('SMTP_PASS') or setting('CLICKDADOS_SMTP_PASS')
SMTP_FROM = setting('SMTP_FROM') or setting('CLICKDADOS_SMTP_FROM') or SMTP_USER
SMTP_USE_SSL = flag('SMTP_USE_SSL')
SMTP_STARTTLS = flag('SMTP_STARTTLS', True)
# Apenas domínios corporativos explicitamente autorizados recebem e-mails.
INTERNAL_EMAIL_DOMAINS = tuple(dict.fromkeys(
    d.strip().lower().lstrip('@') for d in
    setting('INTERNAL_EMAIL_DOMAINS', 'clickdigital.com.br').replace(';', ',').split(',')
    if d.strip()
)) or ('clickdigital.com.br',)
ALERT_EMAILS = [i.strip() for i in setting('ALERT_EMAILS', 'stefano.faria@clickdigital.com.br').replace(';', ',').split(',') if i.strip()]
ALERTS_ENABLED = flag('ALERTS_ENABLED')
ALERT_HOUR = int(setting('ALERT_HOUR', '8'))
ALERT_MINUTE = int(setting('ALERT_MINUTE', '0'))
STATE_DB_PATH = Path(setting('STATE_DB_PATH', 'data/monitor.sqlite3'))
if not STATE_DB_PATH.is_absolute():
    STATE_DB_PATH = ROOT / STATE_DB_PATH
CACHE_SECONDS = int(setting('CACHE_SECONDS', '300'))
PUBLIC_APP_URL = setting('PUBLIC_APP_URL').strip()
