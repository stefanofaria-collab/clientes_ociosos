"""Coleta, cálculos, e-mails tabulares, exportação e notificações idempotentes."""
import csv
import html
import io
import logging
import smtplib
import ssl
import threading
import time
from datetime import datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo
from app import settings as s, source, storage, email_policy

logger = logging.getLogger(__name__)
_lock = threading.RLock()
_cached = {'timestamp': 0.0, 'day': None, 'clients': None}

FIELDS = [
 ('id','ID da empresa'), ('razao_social','Razão social'), ('nome_plano','Plano'),
 ('duracao','Duração'), ('valor','Valor do plano (R$)'),
 ('nome_usuario','Nome do usuário'), ('telefone','Telefone'),
 ('celular','Celular'), ('email','E-mail'), ('intranet','Intranet')
]


def now():
    return datetime.now(ZoneInfo(s.TZ))


def clients(force=False):
    today=now().date()
    with _lock:
        if (not force and _cached['clients'] is not None and _cached['day']==today
            and time.monotonic()-_cached['timestamp']<s.CACHE_SECONDS):
            return _cached['clients']
        data=source.get_clients(today)
        _cached.update(timestamp=time.monotonic(), day=today, clients=data)
        return data


def summarize(items):
    distribution=[0]*45
    valid=[]; unseen=0
    for item in items:
        days=item['dias_ultimo_acesso']
        if days is None: unseen+=1
        else:
            days=max(0,days)
            valid.append(days)
            if 1<=days<=45: distribution[days-1]+=1
    return dict(total=len(items),media=round(sum(valid)/len(valid),1) if valid else 0,
                sem_acesso=unseen,faixa_30=sum(n>=30 for n in valid),
                faixa_45=sum(n==45 for n in valid),acima_45=sum(n>45 for n in valid),
                acessaram_hoje=sum(n==0 for n in valid)),distribution


def snapshot(force=False):
    data=clients(force)
    stats,dist=summarize(data)
    storage.save_snapshot(now().date(),stats,dist,now().isoformat(timespec='seconds'))
    return stats,dist


def current_summary(data, rules):
    stats, dist=summarize(data)
    thresholds={int(r['dias']) for r in rules}
    first=min(thresholds) if thresholds else 45
    # Um cliente que atinge prazos diferentes no mesmo dia entra uma só vez no card.
    stats['faixa_limite']=sum(c['dias_ultimo_acesso'] in thresholds for c in data)
    stats['acima_limite']=sum(c['dias_ultimo_acesso'] is not None and c['dias_ultimo_acesso']>first for c in data)
    return stats,dist


def row_values(item):
    result=[]
    for field,_ in FIELDS:
        val=item.get(field)
        if field=='valor': val=f'{float(val):.2f}'.replace('.',',') if val is not None and str(val)!='' else ''
        elif val is None: val=''
        else: val=str(val)
        # Evita que strings vindas da base sejam avaliadas como fórmulas em planilhas.
        if field not in ('id','valor') and val.lstrip().startswith(('=','+','-','@','\t','\r','\n')):
            val="'"+val
        result.append(val)
    return result


def export_table(items, delimiter='\t'):
    stream=io.StringIO(newline='')
    writer=csv.writer(stream,delimiter=delimiter,lineterminator='\r\n',quoting=csv.QUOTE_MINIMAL)
    writer.writerow([name for _,name in FIELDS])
    for item in items:
        writer.writerow(row_values(item))
    return stream.getvalue()


def _send(message):
    # ÚNICA saída SMTP do projeto. Não usar endereços da coluna email de clientes.
    # Revalida regras no último ponto antes de abrir uma conexão de rede.
    recipient=email_policy.smtp_envelope_recipient(message)
    if not s.SMTP_HOST or not s.SMTP_FROM:
        raise RuntimeError('Configure SMTP_HOST e SMTP_FROM no .env.')
    if s.SMTP_USER and not s.SMTP_PASS:
        raise RuntimeError('Configure SMTP_PASS no .env.')
    context=ssl.create_default_context()
    if s.SMTP_USE_SSL:
        client=smtplib.SMTP_SSL(s.SMTP_HOST,s.SMTP_PORT,timeout=25,context=context)
    else:
        client=smtplib.SMTP(s.SMTP_HOST,s.SMTP_PORT,timeout=25)
    with client:
        if s.SMTP_STARTTLS and not s.SMTP_USE_SSL:
            client.starttls(context=context)
        if s.SMTP_USER: client.login(s.SMTP_USER,s.SMTP_PASS)
        # Define explicitamente o envelope SMTP: somente um destinatário interno.
        client.send_message(message, to_addrs=[recipient])


def _build_email(subject, plain, recipients, html_content=None):
    msg=EmailMessage()
    msg['Subject']=subject
    msg['From']=s.SMTP_FROM
    msg['To']=', '.join(recipients)
    msg.set_content(plain)
    if html_content: msg.add_alternative(html_content,subtype='html')
    return msg


def _real_report_context():
    """Seleciona a MESMA base e os MESMOS prazos da rotina automática.

    Destinatários são sempre obtidos das regras internas, jamais da coluna
    `email` de uma empresa. Toda a lista é validada antes do primeiro envio.
    """
    if not s.SMTP_HOST or not s.SMTP_FROM:
        raise RuntimeError('Configure SMTP_HOST e SMTP_FROM no .env.')
    if s.SMTP_USER and not s.SMTP_PASS:
        raise RuntimeError('Configure SMTP_PASS no .env.')
    if s.DEMO:
        raise RuntimeError('Envio de relatório real indisponível no modo demonstração. Configure o MySQL.')
    rules = storage.config()['regras_destinatarios']
    if not rules:
        raise ValueError('Cadastre pelo menos um destinatário e salve as configurações.')
    data = clients(force=True)
    contacts = email_policy.customer_contacts(data)
    for rule in rules:
        email_policy.validate_internal_email(rule['email'], contacts)
    candidates_by_days = {
        days: [row for row in data if row['dias_ultimo_acesso'] == days and row['ultimo_acesso']]
        for days in {rule['dias'] for rule in rules}
    }
    return rules, candidates_by_days


def email_preview():
    """Metadados de confirmação sem expor dados de clientes no retorno."""
    with _lock:
        rules, candidates = _real_report_context()
        return {
            'destinatarios': [
                {'email': rule['email'], 'dias': rule['dias'],
                 'clientes': len(candidates[rule['dias']])}
                for rule in rules
            ],
            'mensagem': 'Prévia dos relatórios reais de hoje. Nenhum envio realizado.'
        }


def test_email():
    """Envia o relatório REAL, não a antiga mensagem genérica de teste.

    Utiliza o mesmo template HTML/CSV e critério da rotina diária. Pode
    funcionar com a automação desativada, sem alterar seu log de idempotência.
    Ao clicar novamente, o usuário pode receber outro teste (confirmado na UI).
    """
    with _lock:
        rules, candidates = _real_report_context()
        today = now().date()
        deliveries = []
        for rule in rules:
            recipient, days = rule['email'], rule['dias']
            selected = candidates[days]
            # Mesmo assunto, corpo e CSV que o disparo automático.
            _send(build_digest(selected, today, days, [recipient]))
            deliveries.append({'email': recipient, 'dias': days, 'clientes': len(selected)})
        return {
            'mensagem': (f'Relatório real com tabela e CSV aceito pelo SMTP para '
                         f'{len(deliveries)} destinatário(s). A rotina automática não foi marcada como enviada.'),
            'destinatarios': [x['email'] for x in deliveries],
            'detalhes': deliveries,
        }


def build_digest(candidates, date, days, recipients):
    date_str=date.strftime('%d/%m/%Y')
    title=f'[Clientes Ociosos] {len(candidates)} cliente(s) completaram {days} dias sem acesso — {date_str}'
    plain=[f'CLIENTES OCIOSOS | {date_str}',
           f'{len(candidates)} cliente(s) completaram exatamente {days} dias sem acesso ao GestãoClick.',
           '', 'Segue a relação com informações de contato e link da intranet (CSV também anexo).',
           '', export_table(candidates, '\t'),
           'Ação sugerida: acompanhamento comercial interno. Este e-mail NÃO foi enviado aos clientes.']
    headers=''.join(f'<th style="background:#edf4f8;padding:10px;border:1px solid #dfe8ed;text-align:left;white-space:nowrap">{html.escape(name)}</th>' for _,name in FIELDS)
    trs=[]
    for i,item in enumerate(candidates):
        cells=[]
        for (field,name),value in zip(FIELDS,row_values(item)):
            if field=='intranet':
                link=html.escape(source.intranet_url(item['id']),quote=True)
                content=f'<a href="{link}" style="color:#087f87">Abrir intranet</a>'
            else:
                content=html.escape(str(value))
            cells.append(f'<td style="padding:9px;border:1px solid #e2e8ee;white-space:nowrap">{content}</td>')
        trs.append(f'<tr style="background:{"#fff" if i%2==0 else "#f8fafc"}">{"".join(cells)}</tr>')
    optional_button=''
    if s.PUBLIC_APP_URL:
        url=html.escape(s.PUBLIC_APP_URL.rstrip('/')+'/#clientes',quote=True)
        optional_button=(f'<p><a href="{url}" style="background:#0b8990;color:white;padding:11px 18px;'
                         'border-radius:6px;text-decoration:none;display:inline-block">'
                         'Abrir Clientes Ociosos e copiar para o Google Sheets</a></p>')
    page=f'''<!doctype html><html><body style="font-family:Arial,sans-serif;color:#1b3349;background:#f5f8fa;padding:22px">
    <div style="background:#fff;max-width:100%;padding:22px;border-radius:10px">
      <h2 style="color:#0b8290">Clientes Ociosos · Alerta comercial</h2>
      <p>{html.escape(date_str)} — <b>{len(candidates)} cliente(s)</b> completaram exatamente <b>{days} dias sem acesso</b>.</p>
      <p><b>Comunicado interno:</b> nenhuma mensagem foi enviada aos clientes listados.</p>
      <p>Informações para acompanhamento comercial:</p>
      <div style="overflow-x:auto"><table cellspacing="0" style="border-collapse:collapse;font-size:12px"><thead><tr>{headers}</tr></thead><tbody>{''.join(trs)}</tbody></table></div>
      <p>O arquivo <b>CSV está anexado</b> e pode ser importado no Google Sheets.</p>
      {optional_button}
      <p style="font-size:12px;color:#6e8192">Aviso interno automático · O alerta para cada empresa é enviado uma vez por ciclo, prazo e destinatário interno. Nenhum cliente recebe este e-mail.</p>
    </div></body></html>'''
    msg=_build_email(title,'\n'.join(plain),recipients,page)
    filename=f'clientes_ociosos_{date.isoformat()}_{days}dias.csv'
    # BOM UTF-8 para abrir diretamente no Excel brasileiro. CSV ';' e valores com ',' decimal.
    msg.add_attachment(('\ufeff'+export_table(candidates,';')).encode('utf-8'),
                       maintype='text',subtype='csv',filename=filename)
    return msg


def run_monitoring():
    """Uma mensagem por destinatário e prazo; deduplicação por destinatário+ciclo.

    Clientes com exatamente N dias entram no dia N. Envios bem-sucedidos são
    registrados individualmente, mesmo quando outro destinatário falha.
    """
    with _lock:
        t=now()
        cfg=storage.config()
        data=clients(force=True)
        stats,dist=summarize(data)
        storage.save_snapshot(t.date(),stats,dist,t.isoformat(timespec='seconds'))
        rules=cfg['regras_destinatarios']
        candidates_by_days={
            days:[i for i in data if i['dias_ultimo_acesso']==days and i['ultimo_acesso']]
            for days in {r['dias'] for r in rules}
        }
        total_candidates=sum(len(candidates_by_days[r['dias']]) for r in rules)
        sent_count=0
        deliveries=0
        if s.DEMO:
            outcome=dict(status='demo',candidatos=total_candidates,enviados=0,
                         mensagem='Base simulada: nenhum e-mail real foi enviado.')
        elif not cfg['habilitado']:
            outcome=dict(status='desativado',candidatos=total_candidates,enviados=0,
                         mensagem='Alertas desativados na página de configurações.')
        elif not rules:
            outcome=dict(status='erro',candidatos=0,enviados=0,
                         mensagem='Cadastre pelo menos um destinatário.')
        else:
            sent=storage.sent_keys()
            contacts=email_policy.customer_contacts(data)
            errors=[]
            for rule in rules:
                email, days=rule['email'], rule['dias']
                pending=[i for i in candidates_by_days[days]
                         if (i['id'],str(i['ultimo_acesso'])[:10],days,email) not in sent]
                if not pending:
                    continue
                try:
                    # Jamais enviar para contato de cliente, ainda que alguém o cadastre por engano.
                    email_policy.validate_internal_email(email, contacts)
                    # Um e-mail individual: cada destinatário vê somente seu prazo.
                    _send(build_digest(pending,t.date(),days,[email]))
                    storage.log_sent(pending,email,t.isoformat(timespec='seconds'),days)
                    sent_count+=len(pending)
                    deliveries+=1
                except Exception:
                    logger.exception('Falha no envio SMTP para um destinatário')
                    errors.append(email)
            if errors:
                outcome=dict(status='erro',candidatos=total_candidates,enviados=sent_count,
                             mensagem=f'{deliveries} e-mail(s) enviado(s); falha no envio para {len(errors)} destinatário(s). Confira SMTP e logs.')
            elif deliveries:
                outcome=dict(status='enviado',candidatos=total_candidates,enviados=sent_count,
                             mensagem=f'{deliveries} e-mail(s) enviado(s), com {sent_count} ocorrência(s) de cliente.')
            else:
                outcome=dict(status='sem_novos',candidatos=total_candidates,enviados=0,
                             mensagem='Nenhum novo cliente atingiu os prazos de seus destinatários.')
        storage.log_run(outcome['status'],outcome['mensagem'],outcome['candidatos'],
                        outcome['enviados'],t.isoformat(timespec='seconds'),cfg['versao'])
        return outcome
