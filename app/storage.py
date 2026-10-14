"""SQLite: preferências por destinatário, histórico, execução e alertas idempotentes."""
import json
import sqlite3
from app import settings as s, email_policy


def connection():
    s.STATE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(s.STATE_DB_PATH), timeout=20)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=20000')
    return db


def _rules_from_legacy(emails, days):
    """Migração compatível com as configurações da versão 2.0.x."""
    result = []
    for email in emails:
        email = str(email).strip().lower()
        if email and not any(x['email'] == email for x in result):
            # Configurações antigas podem conter endereços externos;
            # preservamos para revisão, mas o SMTP não poderá enviar a eles.
            result.append({'email': email, 'dias': int(days)})
    return result


def init():
    with connection() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS snapshots(
            dia TEXT PRIMARY KEY, coletado_em TEXT NOT NULL,
            total INTEGER, media REAL, sem_acesso INTEGER,
            faixa_30 INTEGER, faixa_45 INTEGER, acima_45 INTEGER,
            distribuicao TEXT NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS alertas(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id INTEGER NOT NULL,
            ultimo_acesso TEXT NOT NULL,
            dias INTEGER NOT NULL,
            enviado_em TEXT NOT NULL,
            destinatario TEXT NOT NULL,
            UNIQUE(empresa_id, ultimo_acesso, dias, destinatario))''')
        db.execute('''CREATE TABLE IF NOT EXISTS execucoes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            executado_em TEXT NOT NULL,
            resultado TEXT NOT NULL, detalhes TEXT,
            candidatos INTEGER NOT NULL DEFAULT 0,
            enviados INTEGER NOT NULL DEFAULT 0,
            config_versao INTEGER NOT NULL DEFAULT 1)''')
        db.execute('''CREATE TABLE IF NOT EXISTS configuracoes(
            id INTEGER PRIMARY KEY CHECK(id=1),
            dias_alerta INTEGER NOT NULL CHECK(dias_alerta BETWEEN 1 AND 365),
            destinatarios TEXT NOT NULL,
            habilitado INTEGER NOT NULL,
            versao INTEGER NOT NULL DEFAULT 1,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            regras_destinatarios TEXT)''')
        columns = {row['name'] for row in db.execute('PRAGMA table_info(execucoes)')}
        if 'config_versao' not in columns:
            db.execute('ALTER TABLE execucoes ADD COLUMN config_versao INTEGER NOT NULL DEFAULT 1')
        columns = {row['name'] for row in db.execute('PRAGMA table_info(configuracoes)')}
        if 'regras_destinatarios' not in columns:
            db.execute('ALTER TABLE configuracoes ADD COLUMN regras_destinatarios TEXT')
        db.execute('''INSERT OR IGNORE INTO configuracoes
          (id,dias_alerta,destinatarios,habilitado) VALUES(1,?,?,?)''',
          (45, json.dumps(s.ALERT_EMAILS), int(s.ALERTS_ENABLED)))
        row = db.execute('SELECT dias_alerta, destinatarios, regras_destinatarios FROM configuracoes WHERE id=1').fetchone()
        if row['regras_destinatarios'] is None:
            rules = _rules_from_legacy(json.loads(row['destinatarios']), row['dias_alerta'])
            db.execute('UPDATE configuracoes SET regras_destinatarios=? WHERE id=1',
                       (json.dumps(rules, ensure_ascii=False),))

        # A tabela antiga deduplicava por cliente e prazo, não por destinatário.
        # Migra o histórico para que mensagens já enviadas não sejam reenviadas.
        columns = {row['name'] for row in db.execute('PRAGMA table_info(alertas)')}
        if 'destinatario' not in columns:
            db.execute('ALTER TABLE alertas RENAME TO alertas_legacy')
            db.execute('''CREATE TABLE alertas(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_id INTEGER NOT NULL,
                ultimo_acesso TEXT NOT NULL,
                dias INTEGER NOT NULL,
                enviado_em TEXT NOT NULL,
                destinatario TEXT NOT NULL,
                UNIQUE(empresa_id, ultimo_acesso, dias, destinatario))''')
            for old in db.execute('SELECT * FROM alertas_legacy').fetchall():
                for recipient in str(old['destinatarios']).replace(';', ',').split(','):
                    recipient = recipient.strip().lower()
                    if recipient:
                        db.execute('''INSERT OR IGNORE INTO alertas
                            (empresa_id,ultimo_acesso,dias,enviado_em,destinatario)
                            VALUES(?,?,?,?,?)''', (old['empresa_id'], old['ultimo_acesso'],
                                                   old['dias'], old['enviado_em'], recipient))
            db.execute('DROP TABLE alertas_legacy')


def config():
    with connection() as db:
        row = db.execute('SELECT * FROM configuracoes WHERE id=1').fetchone()
    if not row:
        init()
        return config()
    rules = json.loads(row['regras_destinatarios'] or '[]')
    return dict(dias_alerta=row['dias_alerta'],
                destinatarios=[x['email'] for x in rules],
                regras_destinatarios=rules,
                habilitado=bool(row['habilitado']), versao=row['versao'])


def set_config(rules, enabled):
    # Validação completa também ocorre na API; salvamentos diretos passam por aqui.
    if len(rules) > 30:
        raise ValueError('Máximo de 30 destinatários')
    normalized = []
    seen = set()
    for rule in rules:
        email = email_policy.validate_internal_email(rule['email'])
        days = int(rule['dias'])
        if not email or email in seen or not 1 <= days <= 365:
            raise ValueError('Destinatário repetido ou prazo inválido')
        seen.add(email)
        normalized.append({'email': email, 'dias': days})
    if enabled and not normalized:
        raise ValueError('Cadastre um destinatário para ativar os alertas.')
    # Dias mínimo somente para compatibilidade com widgets de versões antigas.
    days = min((r['dias'] for r in normalized), default=45)
    with connection() as db:
        db.execute('''UPDATE configuracoes SET
            dias_alerta=?, destinatarios=?, regras_destinatarios=?, habilitado=?,
            versao=versao+1, atualizado_em=CURRENT_TIMESTAMP WHERE id=1''',
            (days, json.dumps([r['email'] for r in normalized]),
             json.dumps(normalized, ensure_ascii=False), int(enabled)))
    return config()


def save_snapshot(today, stats, dist, when):
    with connection() as db:
        db.execute('''INSERT INTO snapshots
          (dia, coletado_em,total,media,sem_acesso,faixa_30,faixa_45,acima_45,distribuicao)
          VALUES(?,?,?,?,?,?,?,?,?)
          ON CONFLICT(dia) DO UPDATE SET
          coletado_em=excluded.coletado_em,total=excluded.total,
          media=excluded.media,sem_acesso=excluded.sem_acesso,
          faixa_30=excluded.faixa_30,faixa_45=excluded.faixa_45,
          acima_45=excluded.acima_45, distribuicao=excluded.distribuicao''',
          (today.isoformat(), when, stats['total'], stats['media'], stats['sem_acesso'],
           stats['faixa_30'], stats['faixa_45'],stats['acima_45'],json.dumps(dist)))


def history(limit=45):
    with connection() as db:
        rows = db.execute('SELECT * FROM snapshots ORDER BY dia DESC LIMIT ?', (limit,)).fetchall()
    return [dict(r) for r in reversed(rows)]


def sent_keys():
    with connection() as db:
        rows = db.execute('SELECT empresa_id,ultimo_acesso,dias,destinatario FROM alertas').fetchall()
    return {(r['empresa_id'], r['ultimo_acesso'], r['dias'], r['destinatario']) for r in rows}


def log_sent(clients, recipient, timestamp, days):
    with connection() as db:
        for client in clients:
            db.execute('''INSERT OR IGNORE INTO alertas
              (empresa_id,ultimo_acesso,dias,enviado_em,destinatario)
              VALUES(?,?,?,?,?)''',
              (client['id'], str(client['ultimo_acesso'])[:10], days, timestamp, recipient.lower()))


def log_run(result, details, candidates, sent, timestamp, version=1):
    with connection() as db:
        db.execute('''INSERT INTO execucoes(executado_em,resultado,detalhes,candidatos,enviados,config_versao)
                      VALUES(?,?,?,?,?,?)''',
                      (timestamp,result,str(details)[:600],candidates,sent,version))


def recent_alerts(limit=20):
    with connection() as db:
        rows=db.execute('SELECT * FROM alertas ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
    return [dict(r) for r in rows]


def recent_runs(limit=10):
    with connection() as db:
        rows=db.execute('SELECT * FROM execucoes ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
    return [dict(r) for r in rows]


def ran_successfully_today(day, version):
    with connection() as db:
        row=db.execute('''SELECT resultado FROM execucoes WHERE substr(executado_em,1,10)=?
                        AND config_versao=? ORDER BY id DESC LIMIT 1''', (day,version)).fetchone()
    return bool(row and row['resultado'] in ('enviado','sem_novos','desativado','demo'))


def last_run_today(day,version):
    with connection() as db:
        row=db.execute('''SELECT executado_em, resultado FROM execucoes
                       WHERE substr(executado_em,1,10)=? AND config_versao=?
                       ORDER BY id DESC LIMIT 1''',(day,version)).fetchone()
    return dict(row) if row else None
