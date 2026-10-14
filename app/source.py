"""Consulta somente-leitura ao MySQL corporativo; um registro por empresa."""
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from random import Random
from sqlalchemy import create_engine, URL, text, bindparam
from app import settings as s

EXCLUDED = tuple(sorted(set(int(x) for x in '''
1 24 43 2054 123242 216321 346439 388198 196044 10744
11807 166104 200440 177551 209512 261147 463295 458966 403472 226637 414735
361435 376050 367178 263918 447481 48142 438358 239292 376338 479723 480921
481136 479405 482279 124451 174166 184848 186733 248366 444241 462938 473336
476148 480590 485458 487138 487525 193364 267891 369137 484832 3897 209986
334995 423464 379294 278505 363585 202297 487136 495757 74618 448705 492276
492276 493057 493495 495367 495470 500211 500213 500508 500582 502764 497959
510928 514140 187078 521671 224287 205324 517101
'''.split())))

# A consulta original trazia GROUP BY e.id com colunas não agregadas;
# nessas condições o MySQL pode escolher um plano/contato arbitrário.
# Aqui escolhemos um plano elegível de forma determinística: vencimento mais recente,
# em caso de empate maior ID. Para lojas usamos um agregado único por empresa.
QUERY = text('''
WITH planos AS (
  SELECT ep.empresa_id, ep.razao_social,
         REPLACE(REPLACE(ep.nome_plano, ' + recursos', ''), ' (+) recursos', '') AS nome_plano,
         ep.duracao,
         CASE WHEN ep.plano_agregado > ep.valor THEN ep.plano_agregado ELSE ep.valor END AS valor,
         ep.nome_usuario, ep.telefone, ep.email,
         ROW_NUMBER() OVER (
           PARTITION BY ep.empresa_id
           ORDER BY ep.data_vencimento DESC, ep.id DESC
         ) AS pos
    FROM empresas_planos ep
   WHERE ep.plano_id <> 1 AND ep.data_vencimento >= :hoje
), celulares AS (
  SELECT empresa_id, MAX(NULLIF(TRIM(celular), '')) AS celular
    FROM lojas GROUP BY empresa_id
)
SELECT e.id, p.razao_social, e.modalidade, e.empresa_indicacao_id,
       e.tipo_cobranca, p.nome_plano, p.duracao, p.valor,
       p.nome_usuario, p.telefone, l.celular, p.email,
       e.ultimo_acesso,
       DATEDIFF(:hoje, DATE(e.ultimo_acesso)) AS dias_ultimo_acesso
  FROM empresas e
  JOIN planos p ON p.empresa_id = e.id AND p.pos = 1
  LEFT JOIN celulares l ON l.empresa_id = e.id
 WHERE e.ativou_em IS NOT NULL
   AND e.modalidade = 'ERP'
   AND e.empresa_indicacao_id = 1
   AND e.id NOT IN :excluidos
 ORDER BY e.id
''').bindparams(bindparam('excluidos', expanding=True))


def intranet_url(empresa_id):
    return f'https://intranet.clickdigital.com.br/clientes/visualizar/{int(empresa_id)}?aba=5'


@lru_cache(maxsize=1)
def engine():
    url = URL.create('mysql+pymysql', username=s.DB_USER, host=s.DB_HOST,
                     port=s.DB_PORT, database=s.DB_NAME, query={'charset': s.DB_CHARSET})
    conn_args = {'password': s.DB_PASSWORD.encode('utf-8'), 'connect_timeout': 12,
                 'read_timeout': 60, 'write_timeout': 15}
    if s.DB_SSL:
        ssl_opt = {}
        if s.DB_SSL_CA:
            ssl_opt['ca'] = s.DB_SSL_CA
        conn_args['ssl'] = ssl_opt
    return create_engine(url, pool_pre_ping=True, pool_recycle=280,
                         pool_size=2, max_overflow=2, connect_args=conn_args)


def mock_clients(today: date):
    """Base fictícia sem números de telefone reais."""
    rng = Random(145)
    out = []
    for i in range(1, 571):
        days = rng.randrange(0, 68)
        if i % 19 == 0: days = 45
        if i % 41 == 0: days = None
        access = (today - timedelta(days=days)).isoformat() if days is not None else None
        client_id = 700000 + i
        out.append(dict(id=client_id, razao_social=f'Empresa de demonstração {i:04}',
                        modalidade='ERP', empresa_indicacao_id=1,
                        tipo_cobranca='Recorrente' if i % 3 else 'Boleto',
                        nome_plano=['Bronze', 'Prata', 'Ouro', 'Platina'][i % 4],
                        duracao=['Mensal', 'Trimestral', 'Anual'][i % 3],
                        valor=float([69.9, 119.9, 199.9, 309.9][i % 4]),
                        nome_usuario=f'Contato Exemplo {i:04}',
                        telefone='(00) 0000-0000', celular='(00) 00000-0000',
                        email=f'exemplo{i}@example.invalid',
                        ultimo_acesso=access, dias_ultimo_acesso=days,
                        intranet=intranet_url(client_id)))
    return out


def get_clients(today: date):
    if s.DEMO:
        return mock_clients(today)
    if not all([s.DB_HOST, s.DB_NAME, s.DB_USER, s.DB_PASSWORD]):
        raise RuntimeError('Variáveis do MySQL incompletas. Verifique CLICKDADOS_ENV_PATH no .env local e reinicie o app.')
    with engine().connect() as conn:
        rows = conn.execute(QUERY, {'hoje': today, 'excluidos': EXCLUDED}).mappings().all()
    result = []
    for row in rows:
        r = dict(row)
        stamp = r.get('ultimo_acesso')
        r['ultimo_acesso'] = (stamp.isoformat(sep=' ') if isinstance(stamp, datetime)
                             else stamp.isoformat() if isinstance(stamp, date) else str(stamp) if stamp else None)
        r['id'] = int(r['id'])
        r['dias_ultimo_acesso'] = int(r['dias_ultimo_acesso']) if r['dias_ultimo_acesso'] is not None else None
        r['valor'] = float(r['valor']) if isinstance(r['valor'], (Decimal, int, float)) else None
        for key in ['razao_social','modalidade','tipo_cobranca','nome_plano','duracao','nome_usuario','telefone','celular','email']:
            r[key] = str(r.get(key) or '')
        r['intranet'] = intranet_url(r['id'])
        result.append(r)
    return result
