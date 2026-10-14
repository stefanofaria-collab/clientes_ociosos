# Clientes Ociosos — versão 2.0.3

Web app de **monitoramento comercial da inatividade** de clientes GestãoClick. Implementado com FastAPI, JS, HTML, CSS, MySQL (leitura) e SQLite (preferências, histórico, alertas). O aplicativo não modifica o banco corporativo.

## Instalação em `C:\Users\stefano.faria\Desktop\Projetos\clientes_ociosos`

**Opção A — instalador pronto:** baixe o arquivo `Download.zip` na pasta do projeto e execute o comando PowerShell de atualização enviado na conversa. O instalador não é disponibilizado separadamente.

O script instala os arquivos no caminho acima, preservando o `.env`, a pasta `data` (incluindo alertas e preferências) e a pasta `.venv` que já existirem.

**Opção B — manual:** extraia o diretório `clientes_ociosos` do ZIP na pasta `C:\Users\stefano.faria\Desktop\Projetos\`, criando exatamente a pasta de destino. Na primeira instalação, execute:

```powershell
cd "C:\Users\stefano.faria\Desktop\Projetos\clientes_ociosos"
powershell -ExecutionPolicy Bypass -File .\iniciar.ps1
```

Na primeira execução, `iniciar.ps1` cria `.env` com os valores de exemplo. Feche o app, **configure esse arquivo** e inicie novamente.

Abra **http://127.0.0.1:8515**. O painel abre diretamente, sem usuário ou senha. As variáveis antigas `APP_USER` e `APP_PASSWORD` no `.env` existente serão ignoradas.

## Configurar conexão com ClickDados

A primeira preferência é apontar `CLICKDADOS_ENV_PATH` para o `.env` verdadeiro do backend ClickDados. Exemplo, sujeito ao caminho real da sua instalação:

```env
CLICKDADOS_ENV_PATH=C:/Users/stefano.faria/Desktop/Projetos/gestao_clientes/backend/.env
```

O projeto aproveita `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_CHARSET`, `DB_SSL`, `DB_SSL_CA` sem copiar a senha do ClickDados. Se esse caminho não existir ou faltar alguma credencial, o painel sinaliza erro de acesso ao MySQL. Use usuário com permissão apenas de `SELECT` sempre que possível.

Com `CLICKDADOS_ENV_PATH` **vazio** e sem credenciais `DB_*`, entra em **demonstração** (570 clientes inventados, sem disparos comerciais).

## Nova página Configurações

- **Dias sem acesso:** altere para qualquer inteiro de 1 a 365 (inicial 45). Com 15 dias, por exemplo, somente os clientes que completaram exatamente 15 dias na data da execução serão candidatos.
- **Destinatários:** adicione, remova e salve e-mails pelo próprio painel. O valor inicial é `stefano.faria@clickdigital.com.br`.
- **Ativar/desativar:** controle os disparos sem editar `.env`. Desativado por padrão na primeira instalação.
- **Persistência:** alterações ficam no SQLite `data/monitor.sqlite3`, não no banco ClickDados; ao reinstalar preserve a pasta `data`.
- **Frequência:** diário, 08:00 em America/Sao_Paulo (hora inicial definida no `.env`). Mudanças de período aplicam-se sem reiniciar; se o horário já passou, o monitor verifica a configuração atual, e o botão manual permite executar imediatamente.

O evento de envio é único por `(id, data do último acesso, período em dias)`: assim, a alteração do limite de 45 para 15 pode gerar um **novo** evento para clientes que estejam em exatos 15 dias para os quais não houve um alerta interno sob esse limite. Nunca envia retroativamente para quem já ultrapassou o limite no dia em que o período é alterado.

## Configuração SMTP

No `.env`:

```env
SMTP_HOST=servidor-autorizado-da-empresa
SMTP_PORT=587
SMTP_USER=usuario-credenciado
SMTP_PASS=senha-ou-token
SMTP_FROM=remetente-autorizado@clickdigital.com.br
SMTP_USE_SSL=false
SMTP_STARTTLS=true
```

Use **Enviar alerta real** para enviar o mesmo relatório da automação (dados reais do MySQL, HTML e CSV) aos destinatários internos cadastrados. A confirmação apresenta a quantidade de clientes em cada prazo antes do envio. O relatório pode ser enviado com a automação desativada, e **não** marca os alertas automáticos como enviados. Depois, em **Configurações**, marque **Ativar envio de alertas** e clique em **Salvar configurações**.

A instalação não inclui credenciais SMTP. O aplicativo foi validado com simulações; o **envio real** depende da configuração e de testes na rede da empresa. Microsoft 365 pode bloquear SMTP AUTH básico: caso ocorra, peça um relay autenticado/autorizado ao TI.

## E-mail de alerta

Envia um e-mail **separado por destinatário e prazo**, com os clientes que completaram exatamente aquele prazo e uma tabela HTML contendo:

1. ID da empresa; 2. Razão social; 3. Plano; 4. Duração; 5. Valor do plano;
6. Nome do usuário; 7. Telefone; 8. Celular; 9. E-mail; 10. Link da intranet.

Inclui **CSV completo anexo** compatível com Excel e Google Sheets (UTF-8 BOM, `;` como separador, valor com vírgula decimal). Não requer que destinatários acessem o servidor para receber o anexo.

Para oferecer no corpo do e-mail um botão **Abrir Clientes Ociosos**, configure opcionalmente `PUBLIC_APP_URL=https://dominio-interno-https-da-empresa`. Use somente caso haja rede corporativa e controle de acesso implementado externamente. Não publique o painel diretamente na internet.

**Por segurança, botões com código JavaScript não funcionam em e-mails**. Por isso os comandos **Copiar para Google Sheets** e **Baixar CSV** ficam no painel. Os destinatários também podem importar o CSV anexo diretamente no Google Sheets.

## Exportar e copiar no painel

Na tabela **Clientes monitorados**, faça pesquisa por ID ou razão social e/ou defina filtros de dias **De** e **Até**. Em seguida:

- **Copiar para Google Sheets**: copia TSV com todas as linhas correspondentes aos filtros, abre `sheets.new`, e você cola com `Ctrl+V` na célula A1. Caso o bloqueador de pop-ups impeça a abertura, acesse manualmente `https://sheets.new` após copiar. A cópia exige contexto seguro (localhost ou HTTPS).
- **Baixar CSV**: exporta todas as linhas correspondentes aos filtros, não só a página atual (20 linhas por página). Todos os dez campos do e-mail estão presentes.

O link de intranet de cada empresa segue o padrão **confirmado no código do ClickDados**:

`https://intranet.clickdigital.com.br/clientes/visualizar/{empresa_id}?aba=5`

## Consulta corporativa

A consulta mantém as regras recebidas: ERP, origem `empresa_indicacao_id=1`, plano diferente de 1, vencimento do plano a partir do dia, cliente ativado e todos os IDs explicitamente excluídos. Usa `CASE WHEN ep.plano_agregado > ep.valor THEN ep.plano_agregado ELSE ep.valor END` e remove marcadores ` + recursos` do nome do plano.

**Diferença intencional em relação ao SQL enviado:** em lugar de `GROUP BY e.id` sobre colunas não agregadas, escolhe um **plano elegível por empresa** (`ROW_NUMBER`, ordenando por `data_vencimento DESC, id DESC`); dados de celular são agregados por empresa, e o `LEFT JOIN lojas` evita omitir cliente sem loja. Isso torna os dados determinísticos e reduz duplicatas. Verifique no MySQL real se este critério de seleção do plano corresponde ao plano desejado pela equipe comercial.

A SQL usa CTE e `ROW_NUMBER()`, exigindo MySQL 8+ ou versão compatível.

## Histórico e operação

- O gráfico de linhas por dias de inatividade continua com **1 a 45 dias**, independentemente de o limiar escolhido ser maior ou menor que 45.
- Cards de **completaram o limite** e **acima do limite** são dinâmicos; o card de 30+ dias permanece um indicador estável de risco.
- Snapshot diário evolui **a partir da primeira coleta** (não há histórico passado inventado).
- O agendador requer que o servidor permaneça em execução, com apenas **um processo/worker**. A cada minuto verifica se já passou o horário da execução; se não houve execução bem-sucedida com as configurações atuais, executa. Erros são retentados no máximo uma vez por hora, enquanto o cliente estiver no dia exato do limite.
- Envio SMTP e SQLite não formam transação única; falha entre aceitação do SMTP e salvamento local pode, excepcionalmente, duplicar uma notificação. Para operação distribuída é necessário serviço de fila e idempotência transacional.
- O painel não possui login. **Não exponha a porta 8515 em rede pública ou na internet.** Mantenha `APP_HOST=127.0.0.1` (acesso somente no computador local). Para uso com outras pessoas, implante autenticação, HTTPS, controle de acesso e política de retenção via proxy corporativo antes de alterar o host.
- O app lê os dados da base em cache por 5 min e ao monitorar sempre faz consulta nova.

## Endpoints

Sem login (acesso local): `GET /api/dashboard`, `GET /api/configuracoes`, `PUT /api/configuracoes`, `GET /api/clientes`, `GET /api/exportar?formato=csv|tsv`, `GET /api/alertas`, `GET /api/historico`, `POST /api/atualizar`, `POST /api/email/testar`, `POST /api/monitorar`.

## Testar

```powershell
.\.venv\Scripts\python.exe -m pip install pytest httpx
.\.venv\Scripts\python.exe -m pytest tests -q
```

Os testes não usam banco corporativo nem envio SMTP real.


## Solução de problemas: variáveis do MySQL incompletas (v2.0.1)

Se aparecer `Variáveis do MySQL incompletas. Verifique CLICKDADOS_ENV_PATH`,
a aplicação iniciou, mas não localizou as quatro variáveis `DB_HOST`, `DB_NAME`,
`DB_USER` e `DB_PASSWORD`.

1. Verifique a existência do arquivo do ClickDados, por exemplo:
   `C:/Users/stefano.faria/Desktop/Projetos/gestao_clientes/backend/.env`.
2. No arquivo `.env` desta aplicação, ajuste `CLICKDADOS_ENV_PATH=` para o
   **caminho real** do `.env` do ClickDados. Não cole credenciais em chats.
3. Reinicie a aplicação (`Ctrl+C` e `iniciar.ps1`).

A partir da v2.0.1, o app também procura arquivos `.env` válidos nas pastas
mais comuns de projetos ClickDados / gestão comercial no Desktop e OneDrive.
Se não encontrar credenciais, a rotina automática é suspensa até que sejam
configuradas; não tenta enviar e-mail e não enche o log com rastreamentos repetidos.
O endpoint `/api/conexao` informa qual `.env` está em uso
(sem expor as credenciais). O endpoint `/health` indica se o MySQL está configurado.
Essas verificações não garantem conectividade com o servidor MySQL: permissões,
firewall e SSL ainda precisam ser validados na primeira consulta real.

O instalador mantém a configuração anterior; atualizar o ZIP **não sobrescreve**
o `.env` existente.


## 2.0.2 — credenciais diretas

Quando `DB_HOST`, `DB_NAME`, `DB_USER` e `DB_PASSWORD` estão completos no
arquivo `.env` deste projeto, não é necessário analisar arquivos `.env` de outros
projetos. Isso evita avisos de parse emitidos por arquivos externos com sintaxe
incompatível. A rotina com status `desativado` indica que o envio de alertas
ainda não foi habilitado; não indica erro de conexão. Acesse `/health` e o
painel para verificar os dados reais do MySQL.


## 2.0.3 — painel sem login

O painel, os arquivos estáticos e todas as APIs abrem diretamente, sem usuário/senha. Não há mais validação de `APP_PASSWORD`; variáveis antigas `APP_USER` e `APP_PASSWORD` permanecem no `.env` sem efeito. A conexão MySQL, SMTP, histórico e destinatários são preservados. Por conter dados pessoais de clientes e comandos que podem disparar e-mails, mantenha a aplicação escutando apenas em `127.0.0.1`; para acesso compartilhado implemente proteção na camada de rede.


## Atualização 2.1.0: períodos individuais

O gráfico da visão geral mostra agora **2 a 45 dias sem acesso**. O dia 1 permanece nos indicadores e na média geral, mas não é desenhado na linha.

Em **Configurações**, cada destinatário tem um prazo próprio (1–365 dias). Exemplo: `stefano.faria@clickdigital.com.br` em 45 dias e `teste@clickdigital.com.br` em 15 dias. A automação consulta todos os clientes uma única vez e envia **e-mails separados** com tabela e CSV por destinatário, somente para quem completou exatamente o prazo daquele e-mail.

A deduplicação usa **empresa + data do último acesso + prazo + destinatário**. Alterações de prazo e destinatários não fazem o sistema reenviar para os demais destinatários; envios antigos são migrados automaticamente do banco SQLite. Não exclua a pasta `data`.

Para solucionar falhas no botão **Enviar alerta real**, configure diretamente no `.env` `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`, `SMTP_USE_SSL` e `SMTP_STARTTLS` de acordo com seu provedor corporativo. Nunca compartilhe `SMTP_PASS` na conversa: coloque o segredo apenas no arquivo local. O teste informa se o SMTP aceitou a mensagem, o que não garante a entrega final na caixa de entrada.


## Atualização 2.1.1 — e-mail exclusivamente interno + favicon

- **Nunca envia e-mails aos clientes** consultados. A coluna `email` aparece exclusivamente na tabela HTML e no CSV.
- A configuração aceita somente destinatários com domínio corporativo permitido em `INTERNAL_EMAIL_DOMAINS` no `.env` (padrão `clickdigital.com.br`). Exemplo: `INTERNAL_EMAIL_DOMAINS=clickdigital.com.br,gestaoclick.com.br` somente se **ambos** forem domínios internos oficiais.
- Há uma validação ao cadastrar ou editar destinatários, outra imediatamente antes da abertura de conexão SMTP e uma comparação com os e-mails de contato da base durante os envios automáticos e os testes de e-mail.
- O envelope SMTP é preenchido explicitamente com um único endereço interno validado. Mensagens com `Cc` ou `Bcc` são bloqueadas.
- Configurações anteriores com e-mails externos não são apagadas, mas ficam bloqueadas até serem corrigidas no painel.
- A aba do navegador usa a mesma marca (velocímetro) do menu lateral: `/static/favicon.svg`, `/static/favicon.png` e `/favicon.ico`. Atualize a página com **Ctrl+F5** se o navegador mantiver o ícone antigo no cache.
- Os valores de `.env`, `data/` e `.venv` devem ser preservados durante a atualização. Não copie senhas para o código.


## Atualização 2.2.0 — envio manual do e-mail real

- O antigo botão **Testar e-mail** foi substituído por **Enviar alerta real** no painel e em Configurações.
- Antes do envio, consulta novamente a base MySQL e mostra uma confirmação com e-mail interno, prazo e quantidade de clientes de hoje.
- Ao confirmar, envia a **mesma mensagem HTML com a tabela completa e CSV anexado** da rotina automática. Seleciona apenas clientes que completaram exatamente o prazo individual hoje.
- Se não houver clientes naquele prazo, envia o relatório real com zero clientes e CSV com cabeçalho.
- O envio manual funciona mesmo com `ALERTS_ENABLED=false` / alertas desativados em Configurações.
- Não grava os envios na tabela de alertas automáticos e não bloqueia o disparo automático posterior. Como é um envio real, confirmar novamente pode provocar um novo e-mail.
- Não aceita endereços de clientes nem destinatários externos. Os endereços de clientes são apenas dados de contato do relatório.
- Para acesso local sem autenticação, mantenha `APP_HOST=127.0.0.1`.
