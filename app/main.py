"""API sem login + UI e agendador diário para Clientes Ociosos."""
import logging
import re
import threading
from contextlib import asynccontextmanager
from datetime import datetime, time as dt_time
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, JSONResponse
from pydantic import BaseModel, Field
from app import settings as s, service, storage, email_policy

logging.basicConfig(level=logging.INFO)
log=logging.getLogger(__name__)
shutdown_signal=threading.Event()
worker_thread=None


class RecipientRule(BaseModel):
    email: str
    dias: int = Field(ge=1, le=365)


class SettingsInput(BaseModel):
    regras_destinatarios: list[RecipientRule] = Field(max_length=30)
    habilitado: bool



def automatic_job():
    try:
        result=service.run_monitoring()
        log.info('Rotina Clientes Ociosos: %s', result['status'])
    except Exception:
        log.exception('Erro na rotina automática')


def scheduler_loop():
    """Confere a cada minuto; alterações nas configurações valem sem reinício.
    Execução diária após ALERT_HOUR, com retentativa de erro no máximo a cada hora.
    """
    from datetime import datetime as dt
    while not shutdown_signal.is_set():
        try:
            # Sem credenciais não realiza consultas e evita repetir o traceback a cada minuto.
            if not s.DEMO and not s.MYSQL_CONFIGURADO:
                shutdown_signal.wait(60)
                continue
            cfg=storage.config()
            current=service.now()
            if current.time().replace(tzinfo=None)>=dt_time(s.ALERT_HOUR,s.ALERT_MINUTE):
                last=storage.last_run_today(current.date().isoformat(),cfg['versao'])
                can_run=last is None
                if last and last['resultado']=='erro':
                    prev=dt.fromisoformat(last['executado_em'])
                    can_run=(current-prev).total_seconds()>=3600
                if can_run: automatic_job()
        except Exception:
            log.exception('Falha no agendador')
        shutdown_signal.wait(60)


@asynccontextmanager
async def lifespan(app):
    global worker_thread
    storage.init()
    shutdown_signal.clear()
    worker_thread=threading.Thread(target=scheduler_loop,daemon=True,name='clientes-ociosos-daily')
    worker_thread.start()
    log.info('Clientes Ociosos iniciado: %s', 'demo' if s.DEMO else 'mysql')
    if not s.DEMO and not s.MYSQL_CONFIGURADO:
        log.error('MySQL não configurado. Localize o .env do ClickDados e ajuste CLICKDADOS_ENV_PATH. Monitoramento suspenso até reiniciar com as credenciais.')
    elif s.CLICKDADOS_ENV_WARNING:
        log.warning('%s Fonte: %s', s.CLICKDADOS_ENV_WARNING, s.CLICKDADOS_ENV_SOURCE)
    try: yield
    finally:
        shutdown_signal.set()
        worker_thread.join(timeout=3)


app=FastAPI(title='Clientes Ociosos',version='2.2.0',lifespan=lifespan,
            docs_url=None,redoc_url=None,openapi_url=None)
STATIC=Path(__file__).resolve().parent/'static'


@app.middleware('http')
async def block_cross_origin_writes(request: Request, call_next):
    # Sem login, impede que sites terceiros acionem os botões do app via navegador.
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        origin = request.headers.get('origin')
        if origin:
            parsed = urlsplit(origin)
            same_origin = (parsed.scheme in ('http', 'https') and
                           parsed.netloc.lower() == request.headers.get('host', '').lower())
            if not same_origin:
                return JSONResponse(status_code=403, content={'detail': 'Origem não permitida.'})
    response = await call_next(request)
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/health')
def health():
    return {'status':'ok' if s.DEMO or s.MYSQL_CONFIGURADO else 'configuracao_pendente',
            'data_source':'demo' if s.DEMO else 'mysql',
            'mysql_configurado':s.MYSQL_CONFIGURADO}


@app.get('/')
def index():
    return FileResponse(STATIC/'index.html')


@app.get('/static/{filename}')
def static(filename:str):
    if filename not in ('main.js','style.css','favicon.svg','favicon.png','favicon.ico'):raise HTTPException(404)
    return FileResponse(STATIC/filename)


@app.get('/favicon.ico')
def browser_favicon():
    return FileResponse(STATIC/'favicon.ico', media_type='image/x-icon')


@app.get('/api/conexao')
def connection_config():
    # Não revela valores do host, usuário ou senha, somente a origem do arquivo.
    return {'mysql_configurado':s.MYSQL_CONFIGURADO,
            'modo_demo':s.DEMO,
            'arquivo_clickdados':s.CLICKDADOS_ENV_SOURCE or s.configured_path,
            'aviso':s.CLICKDADOS_ENV_WARNING}


@app.get('/api/configuracoes')
def get_settings():
    cfg=storage.config()
    return {**cfg,'horario_execucao':f'{s.ALERT_HOUR:02d}:{s.ALERT_MINUTE:02d}',
            'smtp_configurado':bool(s.SMTP_HOST and s.SMTP_FROM and (not s.SMTP_USER or s.SMTP_PASS)),
            'demo':s.DEMO,
            'dominios_internos':list(s.INTERNAL_EMAIL_DOMAINS)}


@app.put('/api/configuracoes')
def save_settings(body:SettingsInput):
    rules=[]
    unique=set()
    for item in body.regras_destinatarios:
        address=item.email.strip().lower()
        if not re.fullmatch(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,63}',address):
            raise HTTPException(422,detail=f'E-mail inválido: {item.email[:100]}')
        if address in unique:
            raise HTTPException(422,detail=f'E-mail duplicado: {address}. Defina apenas um prazo por destinatário.')
        try:
            email_policy.validate_internal_email(address)
        except ValueError as exc:
            raise HTTPException(422,detail=str(exc))
        unique.add(address)
        rules.append({'email':address,'dias':item.dias})
    if body.habilitado and not rules:
        raise HTTPException(422,detail='Cadastre pelo menos um destinatário para ativar alertas.')
    cfg=storage.set_config(rules,body.habilitado)
    return {'mensagem':'Configurações salvas. Cada destinatário receberá alertas no seu prazo.',**cfg}


@app.get('/api/dashboard')
def dashboard():
    try:
        cfg=storage.config()
        data=service.clients()
        stats,distribution=service.current_summary(data,cfg['regras_destinatarios'])
        storage.save_snapshot(service.now().date(),stats,distribution,
                              service.now().isoformat(timespec='seconds'))
        return {'data':stats,'distribuicao':distribution,
                'coletado_em':service.now().isoformat(timespec='seconds'),
                'fonte':'demo' if s.DEMO else 'mysql',
                'dias_alerta':cfg['dias_alerta'],
                'limites_alerta':sorted(set(x['dias'] for x in cfg['regras_destinatarios'])),
                'regras_destinatarios':cfg['regras_destinatarios'],
                'alertas_ativos':cfg['habilitado'] and not s.DEMO,
                'destinatarios':cfg['destinatarios'],
                'horario_execucao':f'{s.ALERT_HOUR:02d}:{s.ALERT_MINUTE:02d}'}
    except Exception:
        log.exception('Falha ao buscar dashboard')
        raise HTTPException(503,detail='Falha ao consultar MySQL. Verifique a conexão ClickDados.')


@app.get('/api/historico')
def history():
    return {'itens':storage.history(45)}


def filtered(q='',de=None,ate=None):
    data=service.clients()
    if q.strip():
        term=q.strip().casefold()
        data=[i for i in data if term in str(i['id']).casefold() or term in i['razao_social'].casefold()]
    if de is not None:
        data=[i for i in data if i['dias_ultimo_acesso'] is not None and i['dias_ultimo_acesso']>=de]
    if ate is not None:
        data=[i for i in data if i['dias_ultimo_acesso'] is not None and i['dias_ultimo_acesso']<=ate]
    return sorted(data,key=lambda i:(i['dias_ultimo_acesso'] is None,-(i['dias_ultimo_acesso'] or 0),i['id']))


@app.get('/api/clientes')
def clients(q:str='',de:int|None=Query(None,ge=0),ate:int|None=Query(None,ge=0),
            pagina:int=Query(1,ge=1),limite:int=Query(20,ge=1,le=100)):
    try: items=filtered(q,de,ate)
    except Exception:
        log.exception('Falha ao listar clientes')
        raise HTTPException(503,detail='Fonte MySQL indisponível.')
    return {'total':len(items),'pagina':pagina,'limite':limite,
            'itens':items[(pagina-1)*limite:pagina*limite]}


@app.get('/api/exportar')
def export_data(formato:str=Query('csv',pattern='^(csv|tsv)$'),q:str='',
                de:int|None=Query(None,ge=0),ate:int|None=Query(None,ge=0)):
    try: items=filtered(q,de,ate)
    except Exception:
        log.exception('Falha ao exportar')
        raise HTTPException(503,detail='Fonte MySQL indisponível.')
    sep=';' if formato=='csv' else '\t'
    content=service.export_table(items,sep)
    if formato=='csv':
        filename=f'clientes_ociosos_{service.now().date().isoformat()}.csv'
        return Response(content='\ufeff'+content,media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition':f'attachment; filename="{filename}"',
                                 'Cache-Control':'no-store'})
    return Response(content=content,media_type='text/tab-separated-values; charset=utf-8',
                    headers={'Cache-Control':'no-store'})


@app.get('/api/alertas')
def alerts():
    return {'alertas':storage.recent_alerts(),'execucoes':storage.recent_runs()}


@app.post('/api/atualizar')
def refresh():
    try:
        stats,_=service.snapshot(force=True)
        return {'mensagem':f'Dados atualizados: {stats["total"]} clientes.', 'total':stats['total']}
    except Exception:
        log.exception('Falha em atualização')
        raise HTTPException(503,detail='Falha na consulta MySQL.')


@app.post('/api/monitorar')
def monitor():
    try: return service.run_monitoring()
    except Exception:
        log.exception('Falha ao monitorar')
        raise HTTPException(503,detail='Falha na rotina de monitoramento.')


@app.get('/api/email/previa')
def email_preview():
    try:
        return service.email_preview()
    except ValueError as exc:
        raise HTTPException(422,detail=str(exc))
    except RuntimeError as exc:
        message = str(exc)
        if 'SMTP_' in message or 'demonstração' in message:
            raise HTTPException(503,detail=message)
        log.exception('Erro ao preparar prévia de relatório')
        raise HTTPException(503,detail='Não foi possível preparar o relatório real.')
    except Exception:
        log.exception('Falha ao consultar MySQL na prévia do e-mail')
        raise HTTPException(503,detail='Falha ao consultar MySQL para preparar o relatório.')


@app.post('/api/email/testar')
def mail_test():
    try: return service.test_email()
    except Exception as exc:
        log.exception('Falha no envio manual do relatório real')
        import smtplib
        import socket
        import ssl
        if isinstance(exc, ValueError):
            detail=str(exc)
        elif isinstance(exc, RuntimeError):
            detail=str(exc) if 'SMTP_' in str(exc) or 'demonstração' in str(exc) else 'Configuração SMTP inválida.'
        elif isinstance(exc, smtplib.SMTPAuthenticationError):
            detail='Autenticação SMTP recusada. Confira usuário, senha de aplicativo e permissões SMTP AUTH.'
        elif isinstance(exc, smtplib.SMTPRecipientsRefused):
            detail='Destinatário recusado pelo servidor SMTP.'
        elif isinstance(exc, smtplib.SMTPSenderRefused):
            detail='Remetente SMTP não autorizado para esta conta.'
        elif isinstance(exc, (TimeoutError, ConnectionRefusedError, socket.gaierror)):
            detail='Não foi possível conectar ao servidor SMTP. Confira host, porta, rede e firewall.'
        elif isinstance(exc, ssl.SSLError):
            detail='Falha TLS/SSL. Confira a porta e a opção STARTTLS/SSL.'
        else:
            detail='Falha SMTP. Consulte o terminal do servidor (sem compartilhar credenciais).'
        raise HTTPException(503,detail=detail)
