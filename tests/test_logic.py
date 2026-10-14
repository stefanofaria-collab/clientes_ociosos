"""Testes offline: nunca acessam banco corporativo e nunca enviam e-mails reais."""
from datetime import date
from email import policy
from email.parser import BytesParser
from app.service import summarize, export_table, build_digest
from app.source import EXCLUDED, mock_clients, QUERY


def test_distribution_and_counters():
    items=[{'dias_ultimo_acesso': x} for x in (0,1,1,30,44,45,45,46,None)]
    summary,counts=summarize(items)
    assert len(counts)==45
    assert counts[0]==2 and counts[44]==2
    assert summary['total']==9 and summary['faixa_30']==5
    assert summary['faixa_45']==2 and summary['acima_45']==1
    assert summary['sem_acesso']==1 and summary['acessaram_hoje']==1
    assert summary['media']==26.5


def test_demo_deterministic_and_ids_distinct():
    data=mock_clients(date(2026,10,14))
    assert len(data)==570 and len({c['id'] for c in data})==570
    assert any(c['dias_ultimo_acesso']==15 for c in data)
    assert all('razao_social' in c and 'intranet' in c for c in data)


def test_query_is_deterministic_and_new_columns():
    assert 'ROW_NUMBER()' in QUERY.text
    assert 'ORDER BY ep.data_vencimento DESC, ep.id DESC' in QUERY.text
    assert 'e.id NOT IN :excluidos' in QUERY.text
    assert 'DATEDIFF(:hoje' in QUERY.text
    assert 'ep.plano_id <> 1' in QUERY.text
    assert 'ep.plano_agregado > ep.valor' in QUERY.text
    assert 'FROM lojas GROUP BY empresa_id' in QUERY.text
    assert all(c in QUERY.text for c in ('razao_social','nome_usuario','celular','email','duracao'))
    assert len(EXCLUDED)==len(set(EXCLUDED))


def test_settings_persist_and_version(tmp_path,monkeypatch):
    from app import storage,settings
    monkeypatch.setattr(settings,'STATE_DB_PATH',tmp_path/'monitor.sqlite3')
    monkeypatch.setattr(settings,'ALERT_EMAILS',['stefano.faria@clickdigital.com.br'])
    monkeypatch.setattr(settings,'ALERTS_ENABLED',False)
    storage.init()
    before=storage.config()
    assert before['dias_alerta']==45 and before['habilitado']==False
    result=storage.set_config([{'email':'diretoria@clickdigital.com.br','dias':15},{'email':'stefano.faria@clickdigital.com.br','dias':45}],True)
    assert result['dias_alerta']==15 and result['versao']==before['versao']+1
    assert len(storage.config()['destinatarios'])==2
    assert {r['dias'] for r in storage.config()['regras_destinatarios']}=={15,45}
    assert storage.last_run_today('2026-10-14',result['versao']) is None
    storage.log_run('sem_novos','teste',0,0,'2026-10-14T12:00:00-03:00',result['versao'])
    assert storage.ran_successfully_today('2026-10-14',result['versao'])
    assert not storage.ran_successfully_today('2026-10-14',result['versao']+1)


def test_export_includes_all_fields_and_safe_values():
    sample=mock_clients(date(2026,10,14))[0]
    sample['nome_usuario']='=HYPERLINK("x")'
    sample['razao_social']='Empresa; Alerta'
    export=export_table([sample],';')
    assert 'ID da empresa;Razão social;Plano;Duração;' in export
    assert 'Valor do plano (R$)' in export and 'Nome do usuário' in export
    assert 'Telefone;Celular;E-mail;Intranet' in export
    assert "'=HYPERLINK" in export
    assert 'https://intranet.clickdigital.com.br/clientes/visualizar/' in export


def test_mail_contains_html_full_table_and_attached_csv(monkeypatch):
    from app import settings
    monkeypatch.setattr(settings,'SMTP_FROM','teste@clickdigital.com.br')
    item=mock_clients(date(2026,10,14))[0]
    msg=build_digest([item],date(2026,10,14),15,['destino@clickdigital.com.br'])
    msg2=BytesParser(policy=policy.default).parsebytes(msg.as_bytes())
    assert '15 dias' in msg['Subject']
    html_part=msg2.get_body(preferencelist=('html',))
    assert 'Razão social' in html_part.get_content()
    assert 'Nome do usuário' in html_part.get_content()
    assert 'Abrir intranet' in html_part.get_content()
    attachments=list(msg2.iter_attachments())
    assert len(attachments)==1 and attachments[0].get_filename().endswith('.csv')
    body=attachments[0].get_payload(decode=True).decode('utf-8-sig')
    assert 'ID da empresa;Razão social' in body
    assert str(item['id']) in body


def test_mail_idempotent_dynamic_threshold_and_new_cycle(tmp_path,monkeypatch):
    from app import settings,service,storage
    monkeypatch.setattr(settings,'STATE_DB_PATH',tmp_path/'monitor.sqlite3')
    monkeypatch.setattr(settings,'DEMO',False)
    storage.init()
    storage.set_config([{'email':'stefano.faria@clickdigital.com.br','dias':15}],True)
    today=service.now().date()
    client=mock_clients(today)[0]
    client['dias_ultimo_acesso']=15
    client['ultimo_acesso']=(today.replace(day=today.day) if False else date.fromordinal(today.toordinal()-15)).isoformat()
    samples=[client]
    monkeypatch.setattr(service,'clients',lambda force=False:samples)
    messages=[]
    monkeypatch.setattr(service,'_send',lambda msg:messages.append(msg))
    assert service.run_monitoring()['status']=='enviado'
    assert service.run_monitoring()['status']=='sem_novos'
    assert len(messages)==1
    assert storage.recent_alerts()[0]['dias']==15
    storage.set_config([{'email':'diretoria@clickdigital.com.br','dias':12}],True)
    samples[0]['dias_ultimo_acesso']=12
    assert service.run_monitoring()['status']=='enviado'
    assert len(messages)==2
    assert storage.recent_alerts()[0]['dias']==12
    # Se o cliente acessar e completar novamente 12 dias, começa outro ciclo.
    samples[0]['ultimo_acesso']='2026-05-01'
    assert service.run_monitoring()['status']=='enviado'
    assert len(messages)==3


def test_api_sem_login_config_and_export(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from app import main,settings
    monkeypatch.setattr(settings,'STATE_DB_PATH',tmp_path/'server.sqlite3')
    monkeypatch.setattr(settings,'DEMO',True)
    with TestClient(main.app) as client:
        assert client.get('/').status_code==200
        assert client.get('/static/main.js').status_code==200
        assert client.get('/static/style.css').status_code==200
        dash=client.get('/api/dashboard').json()
        assert dash['fonte']=='demo' and dash['dias_alerta']==45
        assert client.get('/api/configuracoes').status_code==200
        invalid=client.put('/api/configuracoes',json={'regras_destinatarios':[{'email':'a-invalid','dias':15}], 'habilitado':True})
        assert invalid.status_code==422
        valid=client.put('/api/configuracoes',json={'regras_destinatarios':[{'email':'diretoria@clickdigital.com.br','dias':15},{'email':'stefano.faria@clickdigital.com.br','dias':45}], 'habilitado':True})
        assert valid.status_code==200 and len(valid.json()['destinatarios'])==2
        assert valid.json()['regras_destinatarios'][1]['dias']==45
        assert client.get('/api/dashboard').json()['limites_alerta']==[15,45]
        filtered=client.get('/api/clientes?de=15&ate=15').json()
        assert all(c['dias_ultimo_acesso']==15 for c in filtered['itens'])
        csv_resp=client.get('/api/exportar?formato=csv&de=15&ate=15')
        assert csv_resp.status_code==200 and csv_resp.text.startswith('\ufeffID da empresa;')
        tsv_resp=client.get('/api/exportar?formato=tsv')
        assert tsv_resp.status_code==200 and '\tRazão social' in tsv_resp.text
        assert client.post('/api/monitorar').json()['status']=='demo'


def test_resolucao_do_env_clickdados(tmp_path, monkeypatch):
    from app import settings
    projects = tmp_path / 'Desktop' / 'Projetos'
    app_dir = projects / 'clientes_ociosos'
    app_dir.mkdir(parents=True)
    clickdados = projects / 'gestao_clientes' / 'backend'
    clickdados.mkdir(parents=True)
    env = clickdados / '.env'
    env.write_text('DB_HOST=example.invalid\nDB_USER=analista\nDB_NAME=erp\nDB_PASSWORD=teste\n',encoding='utf8')
    monkeypatch.setattr(settings, 'ROOT', app_dir)
    candidates = list(settings._potential_clickdados_paths())
    assert env in candidates
    assert settings._valid_source(settings._read_env(env))
    assert not settings._valid_source(settings._read_env(tmp_path / 'ausente.env'))


def test_health_indica_origem_sem_revelar_senha(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app import main, settings
    monkeypatch.setattr(settings, 'STATE_DB_PATH', tmp_path / 'monitor.sqlite3')
    monkeypatch.setattr(settings, 'DEMO', False)
    monkeypatch.setattr(settings, 'MYSQL_CONFIGURADO', False)
    # Sem acesso ao banco: processo sobe para que o erro possa ser diagnosticado.
    with TestClient(main.app) as client:
        h = client.get('/health').json()
        assert h['status'] == 'configuracao_pendente'
        assert h['mysql_configurado'] is False
        data = client.get('/api/conexao').json()
        assert not data['mysql_configurado']
        assert 'DB_PASSWORD' not in str(data)


def test_direct_mysql_skips_malformed_external_env(tmp_path):
    """Não parsear .env externo quando DB_* locais estão completos."""
    import os
    import subprocess
    import sys
    import shutil
    from pathlib import Path

    projects = tmp_path / 'Desktop' / 'Projetos'
    appdir = projects / 'clientes_ociosos'
    pkg = appdir / 'app'
    pkg.mkdir(parents=True)
    (pkg / '__init__.py').write_text('', encoding='utf-8')
    source = Path(__file__).resolve().parents[1] / 'app' / 'settings.py'
    shutil.copy2(source, pkg / 'settings.py')
    bad_dir = projects / 'gestao_clientes' / 'backend'
    bad_dir.mkdir(parents=True)
    (bad_dir / '.env').write_text('NOT A VALID ENV LINE !!\nANOTHER ONE !!\n', encoding='utf8')
    values = {
        'CLICKDADOS_ENV_PATH': str(bad_dir / '.env'),
        'DB_HOST': 'example.invalid', 'DB_PORT': '3306',
        'DB_NAME': 'beteltecprod', 'DB_USER': 'usuario_leitura',
        'DB_PASSWORD': 'senha-ficticia',
    }
    (appdir / '.env').write_text('\n'.join(f'{k}={v}' for k,v in values.items()), encoding='utf8')
    env = os.environ.copy()
    for key in values:
        env.pop(key, None)
    result = subprocess.run(
        [sys.executable, '-c',
         'from app import settings; print(settings.MYSQL_CONFIGURADO, bool(settings.CLICKDADOS_ENV_SOURCE))'],
        cwd=appdir, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'True False'
    assert 'could not parse' not in result.stderr


def test_no_auth_required_and_settings_password_optional(monkeypatch, tmp_path):
    """Tela e rotas REST, inclusive envio de teste, não têm dependência HTTP Basic."""
    from fastapi.testclient import TestClient
    from app import main, settings, service
    monkeypatch.setattr(settings, 'STATE_DB_PATH', tmp_path / 'monitor.sqlite3')
    monkeypatch.setattr(settings, 'DEMO', True)
    monkeypatch.setattr(settings, 'APP_HOST', '127.0.0.1')
    monkeypatch.setattr(service, 'test_email', lambda: {'status':'teste'})
    with TestClient(main.app) as client:
        for path in ('/', '/static/main.js', '/static/style.css', '/api/configuracoes', '/api/dashboard', '/api/clientes', '/api/historico', '/api/alertas', '/api/conexao', '/health'):
            resp = client.get(path)
            assert resp.status_code == 200, f'{path}: {resp.status_code} {resp.text[:90]}'
            assert 'www-authenticate' not in resp.headers
        assert client.post('/api/email/testar').status_code == 200
        assert client.post('/api/atualizar').status_code == 200
        assert client.post('/api/monitorar').status_code == 200
        assert client.get('/api/exportar?formato=csv').status_code == 200


def test_bloqueio_cross_origin_em_acoes_sem_login(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app import main, settings
    monkeypatch.setattr(settings, 'STATE_DB_PATH', tmp_path / 'monitor.sqlite3')
    monkeypatch.setattr(settings, 'DEMO', True)
    with TestClient(main.app) as client:
        cross = client.post('/api/monitorar', headers={'Origin':'https://site-externo.invalid'})
        assert cross.status_code == 403
        allowed = client.post('/api/monitorar', headers={'Origin':'http://testserver'})
        assert allowed.status_code == 200
        assert client.get('/api/clientes').headers['Cache-Control']=='no-store'


def test_migracao_config_e_alertas_v2_0(tmp_path, monkeypatch):
    """Migra preferências e alertas anteriores sem perda nem reenvio."""
    import sqlite3, json
    from app import storage, settings
    path = tmp_path / 'monitor.sqlite3'
    with sqlite3.connect(str(path)) as db:
        db.execute('CREATE TABLE configuracoes(id INTEGER PRIMARY KEY, dias_alerta INTEGER, destinatarios TEXT, habilitado INTEGER, versao INTEGER, atualizado_em TEXT)')
        db.execute('INSERT INTO configuracoes VALUES(1,45,?,1,8,?)',
                   (json.dumps(['stefano.faria@clickdigital.com.br', 'teste@clickdigital.com.br']), '2026-10-14'))
        db.execute('''CREATE TABLE alertas(id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id INTEGER NOT NULL, ultimo_acesso TEXT NOT NULL, dias INTEGER NOT NULL,
            enviado_em TEXT NOT NULL, destinatarios TEXT NOT NULL,
            UNIQUE(empresa_id,ultimo_acesso,dias))''')
        db.execute('''INSERT INTO alertas(empresa_id,ultimo_acesso,dias,enviado_em,destinatarios)
            VALUES(10,'2026-08-30',45,'2026-10-14T08:00:00',?)''',
            ('stefano.faria@clickdigital.com.br, teste@clickdigital.com.br',))
    monkeypatch.setattr(settings, 'STATE_DB_PATH', path)
    storage.init()
    assert storage.config()['regras_destinatarios'] == [
        {'email': 'stefano.faria@clickdigital.com.br', 'dias': 45},
        {'email': 'teste@clickdigital.com.br', 'dias': 45}]
    keys = storage.sent_keys()
    assert (10, '2026-08-30', 45, 'stefano.faria@clickdigital.com.br') in keys
    assert (10, '2026-08-30', 45, 'teste@clickdigital.com.br') in keys
    storage.init()
    assert len(storage.sent_keys()) == 2


def test_multiple_independent_alert_rules(tmp_path, monkeypatch):
    from app import settings, service, storage
    monkeypatch.setattr(settings, 'STATE_DB_PATH', tmp_path/'m.sqlite3')
    monkeypatch.setattr(settings, 'DEMO', False)
    storage.init()
    storage.set_config([
        {'email': 'stefano.faria@clickdigital.com.br', 'dias': 45},
        {'email': 'teste@clickdigital.com.br', 'dias': 15}], True)
    today = service.now().date()
    template = mock_clients(today)[0]
    def sample(id, days):
        return {**template, 'id': id, 'dias_ultimo_acesso': days,
                'ultimo_acesso': date.fromordinal(today.toordinal()-days).isoformat()}
    data = [sample(100, 15), sample(200, 45), sample(300, 1), sample(400, 18)]
    monkeypatch.setattr(service, 'clients', lambda force=False: data)
    sent = []
    monkeypatch.setattr(service, '_send', lambda msg: sent.append(msg))
    first = service.run_monitoring()
    assert first['status']=='enviado' and first['enviados']==2
    assert len(sent)==2
    assert {m['To'] for m in sent}=={'stefano.faria@clickdigital.com.br','teste@clickdigital.com.br'}
    assert '45 dias' in next(m for m in sent if m['To'].startswith('stefano'))['Subject']
    assert '15 dias' in next(m for m in sent if m['To'].startswith('teste'))['Subject']
    assert service.run_monitoring()['status']=='sem_novos'
    assert len(sent)==2
    storage.set_config([
        {'email':'stefano.faria@clickdigital.com.br','dias':45},
        {'email':'teste@clickdigital.com.br','dias':45}],True)
    assert service.run_monitoring()['enviados']==1
    assert sent[-1]['To']=='teste@clickdigital.com.br'
    assert len(storage.sent_keys())==3


def test_independent_delivery_with_failed_recipient_retry(tmp_path, monkeypatch):
    from app import settings,service,storage
    monkeypatch.setattr(settings,'STATE_DB_PATH',tmp_path/'monitor.sqlite3')
    monkeypatch.setattr(settings,'DEMO',False)
    storage.init()
    storage.set_config([
        {'email':'stefano.faria@clickdigital.com.br','dias':45},
        {'email':'teste@clickdigital.com.br','dias':15}],True)
    today=service.now().date()
    tpl=mock_clients(today)[0]
    records=[{**tpl,'id':100,'dias_ultimo_acesso':45,'ultimo_acesso':date.fromordinal(today.toordinal()-45).isoformat()},
             {**tpl,'id':101,'dias_ultimo_acesso':15,'ultimo_acesso':date.fromordinal(today.toordinal()-15).isoformat()}]
    monkeypatch.setattr(service,'clients',lambda force=False:records)
    delivered=[]
    def fail_one(msg):
        if msg['To'].startswith('teste'):
            raise RuntimeError('SMTP temporariamente indisponível')
        delivered.append(msg['To'])
    monkeypatch.setattr(service,'_send',fail_one)
    result=service.run_monitoring()
    assert result['status']=='erro' and result['enviados']==1
    assert len(storage.sent_keys())==1
    monkeypatch.setattr(service,'_send',lambda msg:delivered.append(msg['To']))
    assert service.run_monitoring()['enviados']==1
    assert delivered==['stefano.faria@clickdigital.com.br','teste@clickdigital.com.br']


def test_distribution_frontend_begins_day_2():
    from pathlib import Path
    script=(Path(__file__).resolve().parents[1]/'app/static/main.js').read_text()
    html=(Path(__file__).resolve().parents[1]/'app/static/index.html').read_text()
    assert 'r.distribuicao.slice(1)' in script
    assert 'String(i+2)' in script
    assert 'de 2 a 45' in html
    assert 'data-rule-days' in script


def test_smtp_config_incomplete_message_without_secrets(monkeypatch,tmp_path):
    from fastapi.testclient import TestClient
    from app import main, settings
    monkeypatch.setattr(settings,'STATE_DB_PATH',tmp_path/'monitor.sqlite3')
    monkeypatch.setattr(settings,'DEMO',True)
    monkeypatch.setattr(settings,'SMTP_HOST','')
    monkeypatch.setattr(settings,'SMTP_FROM','')
    monkeypatch.setattr(settings,'SMTP_USER','')
    monkeypatch.setattr(settings,'SMTP_PASS','')
    with TestClient(main.app) as client:
        assert client.get('/api/configuracoes').json()['smtp_configurado'] is False
        response=client.post('/api/email/testar')
        assert response.status_code==503
        assert response.json()['detail']=='Configure SMTP_HOST e SMTP_FROM no .env.'


# Proteções adicionais: clientes nunca recebem e-mail, mesmo por engano.
def test_bloqueio_em_cadastro_e_api_para_emails_de_clientes(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import settings, storage, main
    monkeypatch.setattr(settings, 'STATE_DB_PATH', tmp_path / 'monitor.sqlite3')
    monkeypatch.setattr(settings, 'DEMO', True)
    monkeypatch.setattr(settings, 'INTERNAL_EMAIL_DOMAINS', ('clickdigital.com.br',))
    storage.init()
    import pytest
    with pytest.raises(ValueError, match='exclusivamente interno'):
        storage.set_config([{'email':'cliente@gmail.com','dias':45}], True)
    with TestClient(main.app) as client:
        res=client.put('/api/configuracoes',json={
            'regras_destinatarios':[{'email':'cliente@gmail.com','dias':15}],
            'habilitado':True})
        assert res.status_code==422
        assert 'interno' in res.json()['detail']


def test_barreira_final_smtp_nunca_aceita_clientes_ou_bcc(monkeypatch):
    from app import settings, service
    from email.message import EmailMessage
    import pytest
    monkeypatch.setattr(settings, 'INTERNAL_EMAIL_DOMAINS', ('clickdigital.com.br',))
    msg=EmailMessage();msg['From']='stefano.faria@clickdigital.com.br'
    msg['To']='cliente@gmail.com';msg.set_content('teste')
    # Deve recusar ANTES de abrir conexão com o servidor.
    monkeypatch.setattr(service.smtplib, 'SMTP', lambda *a,**kw: pytest.fail('Tentou abrir o SMTP externo'))
    with pytest.raises(ValueError, match='interno'):
        service._send(msg)
    safe=EmailMessage();safe['From']='stefano.faria@clickdigital.com.br'
    safe['To']='stefano.faria@clickdigital.com.br';safe['Bcc']='cliente@gmail.com';safe.set_content('teste')
    with pytest.raises(ValueError, match='Cc, Bcc'):
        service._send(safe)
    safe2=EmailMessage();safe2['From']='stefano.faria@clickdigital.com.br'
    safe2['To']='stefano.faria@clickdigital.com.br, cliente@gmail.com';safe2.set_content('teste')
    with pytest.raises(ValueError, match='único'):
        service._send(safe2)


def test_destinatario_na_base_de_clientes_bloqueado_no_monitoramento(tmp_path, monkeypatch):
    from app import settings, service, storage
    monkeypatch.setattr(settings,'STATE_DB_PATH',tmp_path/'monitor.sqlite3')
    monkeypatch.setattr(settings,'DEMO',False)
    monkeypatch.setattr(settings,'INTERNAL_EMAIL_DOMAINS',('clickdigital.com.br',))
    storage.init()
    internal='contato@clickdigital.com.br'
    storage.set_config([{'email':internal,'dias':15}],True)
    today=service.now().date()
    sample=mock_clients(today)[0]
    sample['id']=100;sample['email']=internal
    sample['dias_ultimo_acesso']=15
    sample['ultimo_acesso']=date.fromordinal(today.toordinal()-15).isoformat()
    monkeypatch.setattr(service,'clients',lambda force=False:[sample])
    monkeypatch.setattr(service,'_send',lambda msg: __import__('pytest').fail('Cliente recebeu e-mail'))
    result=service.run_monitoring()
    assert result['status']=='erro' and result['enviados']==0
    assert not storage.sent_keys()


def test_envelope_smtp_usa_apenas_endereco_interno(monkeypatch):
    from app import settings,service
    from email.message import EmailMessage
    monkeypatch.setattr(settings,'INTERNAL_EMAIL_DOMAINS',('clickdigital.com.br',))
    monkeypatch.setattr(settings,'SMTP_HOST','smtp.test.local')
    monkeypatch.setattr(settings,'SMTP_FROM','stefano.faria@clickdigital.com.br')
    monkeypatch.setattr(settings,'SMTP_USER','')
    monkeypatch.setattr(settings,'SMTP_PASS','')
    monkeypatch.setattr(settings,'SMTP_USE_SSL',False)
    monkeypatch.setattr(settings,'SMTP_STARTTLS',False)
    seen=[]
    class FakeSMTP:
        def __init__(self,*a,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def send_message(self,msg,to_addrs):seen.append(to_addrs)
    monkeypatch.setattr(service.smtplib,'SMTP',FakeSMTP)
    msg=EmailMessage();msg['To']='Stefano <stefano.faria@clickdigital.com.br>';msg.set_content('ok')
    service._send(msg)
    assert seen==[['stefano.faria@clickdigital.com.br']]


def test_favicon_carrega_na_aba_do_navegador(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from app import main,settings
    monkeypatch.setattr(settings,'STATE_DB_PATH',tmp_path/'monitor.sqlite3')
    monkeypatch.setattr(settings,'DEMO',True)
    with TestClient(main.app) as client:
        page=client.get('/')
        assert '/static/favicon.svg' in page.text and 'rel="icon"' in page.text
        for path in ('/static/favicon.svg','/static/favicon.png','/favicon.ico'):
            img=client.get(path)
            assert img.status_code==200 and len(img.content)>100


def test_envio_de_teste_bloqueia_email_que_tambem_e_de_cliente(tmp_path, monkeypatch):
    from app import settings, storage, service
    import pytest
    monkeypatch.setattr(settings,'STATE_DB_PATH',tmp_path/'monitor.sqlite3')
    monkeypatch.setattr(settings,'DEMO',False)
    monkeypatch.setattr(settings,'INTERNAL_EMAIL_DOMAINS',('clickdigital.com.br',))
    monkeypatch.setattr(settings,'SMTP_HOST','smtp.gmail.com')
    monkeypatch.setattr(settings,'SMTP_FROM','teste@clickdigital.com.br')
    monkeypatch.setattr(settings,'SMTP_USER','')
    storage.init()
    recipient='teste@clickdigital.com.br'
    storage.set_config([{'email':recipient,'dias':15}],False)
    sample=mock_clients(service.now().date())[0]
    sample['email']=recipient
    monkeypatch.setattr(service,'clients',lambda force=False:[sample])
    monkeypatch.setattr(service,'_send',lambda msg: pytest.fail('E-mail para cliente!'))
    with pytest.raises(ValueError, match='e-mail de cliente'):
        service.test_email()


def test_envio_manual_gera_relatorio_real_para_prazos_individuais_sem_registrar_automatico(tmp_path, monkeypatch):
    from app import service, storage, settings
    from datetime import timedelta
    monkeypatch.setattr(settings, 'STATE_DB_PATH', tmp_path / 'monitor.sqlite3')
    monkeypatch.setattr(settings, 'DEMO', False)
    monkeypatch.setattr(settings, 'SMTP_HOST', 'smtp.example.test')
    monkeypatch.setattr(settings, 'SMTP_FROM', 'stefano.faria@clickdigital.com.br')
    monkeypatch.setattr(settings, 'SMTP_USER', '')
    monkeypatch.setattr(settings, 'INTERNAL_EMAIL_DOMAINS', ('clickdigital.com.br',))
    storage.init()
    storage.set_config([
        {'email': 'stefano.faria@clickdigital.com.br', 'dias': 45},
        {'email': 'diretoria@clickdigital.com.br', 'dias': 15},
    ], False)  # Teste funciona mesmo com envio automatico DESATIVADO.
    today = service.now().date()
    rows = []
    for index, days in enumerate((15, 45, 46, 0), start=1):
        row = mock_clients(today)[index]
        row['id'] = 400000 + index
        row['dias_ultimo_acesso'] = days
        row['ultimo_acesso'] = (today - timedelta(days=days)).isoformat()
        rows.append(row)
    reads=[]
    def fetch(force=False):
        reads.append(force)
        return rows
    monkeypatch.setattr(service, 'clients', fetch)
    sent=[]
    monkeypatch.setattr(service, '_send', lambda message: sent.append(message))
    preview = service.email_preview()
    assert reads == [True]
    assert preview['destinatarios'] == [
        {'email':'stefano.faria@clickdigital.com.br','dias':45,'clientes':1},
        {'email':'diretoria@clickdigital.com.br','dias':15,'clientes':1}]
    assert sent == []
    result=service.test_email()
    assert result['detalhes'] == preview['destinatarios']
    assert len(sent) == 2
    assert sent[0]['To'] == 'stefano.faria@clickdigital.com.br'
    assert sent[1]['To'] == 'diretoria@clickdigital.com.br'
    assert '45 dias' in sent[0]['Subject'] and '15 dias' in sent[1]['Subject']
    for msg, wanted, excluded in ((sent[0], rows[1], rows[0]), (sent[1], rows[0], rows[1])):
        html_body = msg.get_body(preferencelist=('html',)).get_content()
        assert str(wanted['id']) in msg.get_body(preferencelist=('plain',)).get_content()
        assert str(wanted['id']) in html_body
        assert str(excluded['id']) not in html_body
        assert 'Nome do usuário' in html_body and 'Abrir intranet' in html_body
        files = list(msg.iter_attachments())
        assert len(files) == 1
        csv_text = files[0].get_payload(decode=True).decode('utf-8-sig')
        assert str(wanted['id']) in csv_text
        assert str(excluded['id']) not in csv_text
    # Manual nao conta como ja enviado; automatizacao nao e consumida.
    assert storage.sent_keys() == set()
    assert storage.recent_runs() == []
    service.test_email()
    assert len(sent) == 4  # novo clique confirmado no frontend = novo e-mail


def test_envio_manual_com_zero_clientes_usa_template_real(tmp_path, monkeypatch):
    from app import service, storage, settings
    monkeypatch.setattr(settings,'STATE_DB_PATH', tmp_path / 'monitor.sqlite3')
    monkeypatch.setattr(settings,'DEMO',False)
    monkeypatch.setattr(settings,'SMTP_HOST','smtp.example.test')
    monkeypatch.setattr(settings,'SMTP_FROM','stefano.faria@clickdigital.com.br')
    monkeypatch.setattr(settings,'SMTP_USER','')
    storage.init()
    storage.set_config([{'email':'stefano.faria@clickdigital.com.br','dias':45}],False)
    monkeypatch.setattr(service,'clients',lambda force=False:[])
    sent=[]
    monkeypatch.setattr(service,'_send',lambda msg:sent.append(msg))
    response=service.test_email()
    assert response['detalhes'][0]['clientes']==0
    assert len(sent)==1
    assert '0 cliente(s)' in sent[0]['Subject']
    assert 'Razão social' in sent[0].get_body(preferencelist=('html',)).get_content()
    assert 'ID da empresa' in list(sent[0].iter_attachments())[0].get_payload(decode=True).decode('utf-8-sig')


def test_envio_manual_nao_pode_enviar_para_cliente_corporativo(tmp_path,monkeypatch):
    from app import service, storage, settings
    import pytest
    monkeypatch.setattr(settings,'STATE_DB_PATH',tmp_path/'monitor.sqlite3')
    monkeypatch.setattr(settings,'DEMO',False)
    monkeypatch.setattr(settings,'SMTP_HOST','smtp.example.test')
    monkeypatch.setattr(settings,'SMTP_FROM','stefano.faria@clickdigital.com.br')
    monkeypatch.setattr(settings,'SMTP_USER','')
    monkeypatch.setattr(settings,'INTERNAL_EMAIL_DOMAINS',('clickdigital.com.br',))
    storage.init()
    storage.set_config([{'email':'stefano.faria@clickdigital.com.br','dias':45}],False)
    row=mock_clients(service.now().date())[0]
    row['email']='stefano.faria@clickdigital.com.br'
    monkeypatch.setattr(service,'clients',lambda force=False:[row])
    monkeypatch.setattr(service,'_send',lambda msg:pytest.fail('SMTP foi acionado indevidamente'))
    with pytest.raises(ValueError, match='e-mail de cliente'):
        service.email_preview()
    with pytest.raises(ValueError, match='e-mail de cliente'):
        service.test_email()


def test_endpoint_previas_e_envio_manual_relatorio_real(tmp_path,monkeypatch):
    from app import main, settings, service, storage
    from fastapi.testclient import TestClient
    from datetime import timedelta
    monkeypatch.setattr(settings,'STATE_DB_PATH',tmp_path/'monitor.sqlite3')
    monkeypatch.setattr(settings,'DEMO',False)
    monkeypatch.setattr(settings,'SMTP_HOST','smtp.example.test')
    monkeypatch.setattr(settings,'SMTP_FROM','stefano.faria@clickdigital.com.br')
    monkeypatch.setattr(settings,'SMTP_USER','')
    today=service.now().date()
    row=mock_clients(today)[0]
    row['dias_ultimo_acesso']=45
    row['ultimo_acesso']=(today-timedelta(days=45)).isoformat()
    monkeypatch.setattr(service,'clients',lambda force=False:[row])
    sent=[]
    monkeypatch.setattr(service,'_send',lambda msg:sent.append(msg))
    with TestClient(main.app) as client:
        storage.set_config([{'email':'stefano.faria@clickdigital.com.br','dias':45}],False)
        preview=client.get('/api/email/previa')
        assert preview.status_code==200
        assert preview.json()['destinatarios'][0]['clientes']==1
        assert 'razao_social' not in str(preview.json())
        assert len(sent)==0
        response=client.post('/api/email/testar')
        assert response.status_code==200, response.text
        assert 'Relatório real' in response.json()['mensagem']
        assert len(sent)==1
        assert storage.sent_keys()==set()


def test_interface_email_real_e_confirmacao():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    js=(root/'app/static/main.js').read_text(encoding='utf-8')
    html=(root/'app/static/index.html').read_text(encoding='utf-8')
    assert 'Enviar alerta real' in html
    assert 'Testar e-mail' not in html
    assert '/api/email/previa' in js
    assert "window.confirm(message)" in js
    assert "'/api/email/testar'" in js
    assert 'Nenhum cliente será notificado' in js
