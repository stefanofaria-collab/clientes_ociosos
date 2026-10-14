const $ = id => document.getElementById(id);
const number = value => new Intl.NumberFormat('pt-BR').format(value ?? 0);
const escapeHTML = val => String(val ?? '').replace(/[&<>"']/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s]));
const datePt = raw => { if (!raw) return 'Não registrado'; let t=String(raw).slice(0,10).split('-');return t.length===3?`${t[2]}/${t[1]}/${t[0]}`:raw; };
const state = { page:1, lastData:null, totalRows:0, limit:20, pending:false, threshold:45, thresholds:[45], recipientRules:[], allowedInternalDomains:['clickdigital.com.br'] };
function toast(message, error=false) {const el=$('toast');el.textContent=message;el.classList.remove('hidden');el.classList.toggle('error', error);setTimeout(()=>el.classList.add('hidden'),6000);}
async function request(path, options={}) {
  const response=await fetch(path,{cache:'no-store',...options});
  if(!response.ok){let data={};try{data=await response.json();}catch(e){}throw Error(data.detail||`Erro HTTP ${response.status}`);}
  return response.json();
}
function drawLine(svgId, data, opts={}) {
 const svg=$(svgId), n=data.length, W=opts.trend?400:730, H=opts.trend?210:272;
 const l=opts.trend?39:39,r=opts.trend?12:18,t=16,b=opts.trend?35:38;
 const width=W-l-r,height=H-t-b;
 const values = (data.length?data:[0]).map(v=>Number(v)||0);
 const maxValue=Math.max(...values,0), max=Math.max(4, Math.ceil(maxValue/4)*4), ticks=4;
 const xAt=i=>l+(n===1?width/2:width*i/(n-1)), yAt=v=>t+height-height*v/max;
 const path=values.map((v,i)=>`${i===0?'M':'L'}${xAt(i).toFixed(2)} ${yAt(v).toFixed(2)}`).join(' ');
 const area=values.length>1?`${path} L${xAt(n-1)} ${yAt(0)} L${xAt(0)} ${yAt(0)} Z`:'';
 let markup=`<defs><linearGradient id="grad-${svgId}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#11a4a9" stop-opacity=".16"/><stop offset="100%" stop-color="#11a4a9" stop-opacity=".005"/></linearGradient></defs>`;
 for(let i=0;i<=ticks;i++){const value=max*i/ticks, y=yAt(value);markup+=`<line class="svg-grid" x1="${l}" x2="${W-r}" y1="${y}" y2="${y}"/><text class="svg-label" x="${l-10}" y="${y+4}" text-anchor="end">${number(value)}</text>`;}
 const labels=opts.labels || values.map((_,i)=>String(i+1));
 const indices=opts.trend ? [...new Set([0,Math.floor((n-1)/2),n-1])] : [...new Set([0,3,8,13,18,23,28,33,38,n-1])];
 for(const i of indices){if(i>=n)continue;markup+=`<text class="svg-label" x="${xAt(i)}" y="${H-10}" text-anchor="middle">${escapeHTML(labels[i]||'')}</text>`;}
 if(area)markup+=`<path d="${area}" fill="url(#grad-${svgId})"/>`;
 if(path && values.length>1)markup+=`<path d="${path}" class="svg-stroke"/>`;
 // Render pontos em amarelo/ciano, mantendo responsividade.
 values.forEach((v,i)=>{if(opts.trend && n>20 && i%3 && i!==n-1)return;markup+=`<circle class="svg-point" cx="${xAt(i)}" cy="${yAt(v)}" r="${opts.trend?3:2.6}"/>`;});
 svg.innerHTML=markup;
 if(!opts.trend){
  svg.onpointermove=e=>{
    const pt=svg.createSVGPoint();pt.x=e.clientX;pt.y=e.clientY;const p=pt.matrixTransform(svg.getScreenCTM().inverse());
    const index=Math.max(0, Math.min(n-1,Math.round((p.x-l)/width*(n-1))));
    const tool=$('distTooltip');tool.textContent=`Dia ${labels[index]} • ${number(values[index])} cliente(s)`;
    const wrap=svg.parentElement, rect=wrap.getBoundingClientRect();
    tool.style.left=`${Math.min(Math.max(e.clientX-rect.left+10,10),rect.width-140)}px`;
    tool.style.top=`${Math.max(e.clientY-rect.top-44,0)}px`;tool.classList.remove('hidden');
  };svg.onpointerleave=()=>$('distTooltip').classList.add('hidden');
 }
}
function riskStatus(days) {
 if(days===null) return ['Sem registro','gray'];
 if(state.thresholds.includes(days)) return [`Alerta ${days} dias`,'red'];
 if(days>state.threshold) return ['Acima do menor prazo','red'];
 if(days>=Math.max(1,state.threshold-10)) return ['Atenção','yellow'];
 return ['Regular',''];
}
async function loadDashboard(){
 const r=await request('/api/dashboard');state.lastData=r;state.threshold=r.dias_alerta;state.thresholds=r.limites_alerta||[];
 $('limitLabel').textContent=state.thresholds.length ? state.thresholds.map(x=>`${x}d`).join(' · ') : 'NENHUM';$('overLimitLabel').textContent=r.dias_alerta;
 $('kpiTotal').textContent=number(r.data.total);$('kpiAverage').textContent=number(r.data.media);
 $('kpiRisk').textContent=number(r.data.faixa_30);$('kpiTrigger').textContent=number(r.data.faixa_limite);
 $('kpiOver45').textContent=number(r.data.acima_limite);$('kpiUnknown').textContent=number(r.data.sem_acesso);
 $('trendCurrent').textContent=number(r.data.faixa_30);
 $('alertEmails').textContent=(r.regras_destinatarios||[]).map(x=>`${x.email} (${x.dias}d)`).join(', ')||'Nenhum destinatário';
 $('sideSchedule').textContent=r.horario_execucao;
 const demo=r.fonte==='demo';$('demoBanner').classList.toggle('hidden',!demo);
 $('databaseStatus').innerHTML=`<span class="status-dot"></span> ${demo?'Dados simulados':'MySQL conectado'}`;
 $('alertStatus').textContent=demo?'Alertas: demonstração':r.alertas_ativos?'Alertas: ativados':'Alertas: desativados';
 $('alertStatus').classList.toggle('enabled',r.alertas_ativos);
 $('updatedAt').textContent=`Atualizado em ${new Date(r.coletado_em).toLocaleString('pt-BR',{dateStyle:'short',timeStyle:'short'})}`;
 const distFromTwo=r.distribuicao.slice(1);
 drawLine('distributionChart',distFromTwo,{labels:distFromTwo.map((_,i)=>String(i+2))});
 $('errorBanner').classList.add('hidden');
}
async function loadHistory(){
 const r=await request('/api/historico');const points=r.itens||[];
 if(!points.length){drawLine('trendChart',[0],{trend:true,labels:['Hoje']});return;}
 const labels=points.map(i=>{const a=i.dia.split('-');return `${a[2]}/${a[1]}`;});
 drawLine('trendChart',points.map(i=>i.faixa_30),{trend:true,labels});
 $('trendFoot').textContent=points.length===1?'O histórico começa hoje e será construído diariamente.':`Série diária registrada: ${datePt(points[0].dia)} a ${datePt(points.at(-1).dia)}.`;
 if(points.length>=2){const old=points[0].faixa_30,last=points.at(-1).faixa_30,delta=last-old; $('trendVariation').textContent=`${delta>=0?'+':''}${number(delta)} no período`;}
}
async function loadClients(){
 const params=new URLSearchParams({pagina:state.page,limite:state.limit});
 const q=$('searchId').value.trim(),de=$('filterFrom').value,ate=$('filterTo').value;
 if(q)params.set('q',q);if(de!=='')params.set('de',de);if(ate!=='')params.set('ate',ate);
 const r=await request('/api/clientes?'+params);state.totalRows=r.total;
 $('clientTotal').textContent=`${number(r.total)} registros`;
 const rows=r.itens.map(c=>{const [label,cls]=riskStatus(c.dias_ultimo_acesso);
  const currency=c.valor===null?'—':Number(c.valor).toLocaleString('pt-BR',{style:'currency',currency:'BRL'});
  return `<tr><td>#${number(c.id)}</td><td title="${escapeHTML(c.razao_social)}">${escapeHTML(c.razao_social)}</td><td>${escapeHTML(c.nome_plano)}</td><td>${escapeHTML(c.duracao)}</td><td>${currency}</td><td>${escapeHTML(c.nome_usuario)}</td><td>${escapeHTML(c.telefone)}</td><td>${escapeHTML(c.celular)}</td><td>${escapeHTML(c.email)}</td><td>${datePt(c.ultimo_acesso)}</td><td>${c.dias_ultimo_acesso===null?'—':number(c.dias_ultimo_acesso)+' dias'}</td><td><a href="${escapeHTML(c.intranet)}" target="_blank" rel="noopener noreferrer">Abrir ↗</a></td><td><span class="status-label ${cls}">${label}</span></td></tr>`;
 }).join('');
 $('clientRows').innerHTML=rows || '<tr><td colspan="13" class="empty-state">Nenhum cliente encontrado para os filtros.</td></tr>';
 const start=r.total?1+(state.page-1)*state.limit:0,end=Math.min(r.total,state.page*state.limit);
 $('rangeInfo').textContent=`Mostrando ${number(start)}–${number(end)} de ${number(r.total)}`;
 $('pageLabel').textContent=state.page;
 $('prevPage').disabled=state.page<=1;$('nextPage').disabled=state.page*state.limit>=r.total;
}
async function loadAlerts(){
 const r=await request('/api/alertas');const alerts=r.alertas||[],runs=r.execucoes||[];
 $('lastRuns').textContent=`${runs.length} execuções recentes`;
 $('alertRows').innerHTML=alerts.length ? alerts.slice(0,6).map(a=>`<div class="event"><span class="evt-dot"></span><div><strong>Alerta interno sobre a empresa #${number(a.empresa_id)}</strong><small>${new Date(a.enviado_em).toLocaleString('pt-BR',{dateStyle:'short',timeStyle:'short'})} • ${a.dias} dias de inatividade · ${escapeHTML(a.destinatario||'')}</small></div></div>`).join('') : '<div class="empty-state">Ainda não há alertas enviados. As execuções aparecem no registro diário.</div>';
}
async function reloadAll(){
 try{await loadDashboard();await Promise.all([loadClients(),loadAlerts(),loadHistory()]);}
 catch(e){$('errorMessage').textContent=e.message;$('errorBanner').classList.remove('hidden');toast(e.message,true);}
}
function debounced(fn,delay=400){let timer;return ()=>{clearTimeout(timer);timer=setTimeout(fn,delay);};}
async function runAction(button,path,description,confirmText){
 if(state.pending)return;
 if(confirmText&&!window.confirm(confirmText))return;
 state.pending=true;button.disabled=true;
 try{const result=await request(path,{method:'POST'});toast(result.mensagem||`${description}: concluído.`);await reloadAll();}
 catch(e){toast(e.message,true);}finally{button.disabled=false;state.pending=false;}
}
async function sendRealAlert(button){
 if(state.pending)return;
 state.pending=true;button.disabled=true;
 try{
  const report=await request('/api/email/previa');
  const recipients=report.destinatarios||[];
  if(!recipients.length){toast('Nenhum destinatário configurado.',true);return;}
  const lines=recipients.map(x=>`• ${x.email} — ${x.dias} dias: ${number(x.clientes)} cliente(s)`);
  const message=[
   'Enviar o relatório REAL da automação, com tabela e CSV dos clientes de hoje?',
   '',...lines,'',
   'Somente estes endereços internos receberão e-mail. Nenhum cliente será notificado.',
   'Este envio manual é independente do agendamento e pode ser repetido.'
  ].join('\n');
  if(!window.confirm(message))return;
  const result=await request('/api/email/testar',{method:'POST'});
  toast(result.mensagem||'Relatório enviado.');
  await reloadAll();
 }catch(e){toast(e.message,true);}
 finally{state.pending=false;button.disabled=false;}
}
function filterParams(){
 const params=new URLSearchParams();
 const q=$('searchId').value.trim(),de=$('filterFrom').value,ate=$('filterTo').value;
 if(q)params.set('q',q);if(de!=='')params.set('de',de);if(ate!=='')params.set('ate',ate);
 return params;
}
async function copyToSheets(){
 const button=$('btnCopySheets');button.disabled=true;
 try {
  if(!navigator.clipboard || !window.isSecureContext)throw new Error('Cópia requer localhost ou HTTPS no navegador. Use Baixar CSV.');
  const reply=await fetch('/api/exportar?formato=tsv&'+filterParams().toString(),{cache:'no-store'});
  if(!reply.ok)throw new Error('Não foi possível obter os dados para copiar.');
  const tsv=await reply.text();
  await navigator.clipboard.writeText(tsv);
  toast('Tabela copiada! Cole com Ctrl+V na célula A1 do Google Sheets.');
  window.open('https://sheets.new','_blank','noopener,noreferrer');
 }catch(e){toast(e.message,true);}finally{button.disabled=false;}
}
async function downloadCSV(){
 const button=$('btnCSV');button.disabled=true;
 try {
  const reply=await fetch('/api/exportar?formato=csv&'+filterParams().toString(),{cache:'no-store'});
  if(!reply.ok)throw new Error('Não foi possível exportar o CSV.');
  const url=URL.createObjectURL(await reply.blob());
  const link=document.createElement('a');link.href=url;link.download='clientes_ociosos.csv';
  document.body.appendChild(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),5000);
  toast('CSV exportado com todas as empresas do filtro atual.');
 }catch(e){toast(e.message,true);}finally{button.disabled=false;}
}
function renderRecipients(){
 $('recipientList').innerHTML=state.recipientRules.length?
  state.recipientRules.map((rule,i)=>`<div class="recipient-item"><span class="recipient-address">${escapeHTML(rule.email)}</span><label class="recipient-days-label"><input type="number" min="1" max="365" step="1" data-rule-days="${i}" value="${Number(rule.dias)}" aria-label="Dias sem acesso para ${escapeHTML(rule.email)}"> dias</label><button type="button" data-recipient="${i}" aria-label="Remover ${escapeHTML(rule.email)}">Remover</button></div>`).join(''):
  '<div class="empty-state">Nenhum destinatário cadastrado.</div>';
 $('recipientList').querySelectorAll('button[data-recipient]').forEach(button=>{
  button.onclick=()=>{state.recipientRules.splice(Number(button.dataset.recipient),1);renderRecipients();};
 });
 $('recipientList').querySelectorAll('input[data-rule-days]').forEach(input=>{
  input.onchange=()=>{
   const days=Number(input.value);
   if(!Number.isInteger(days)||days<1||days>365){toast('O período deve ficar entre 1 e 365 dias.',true);input.value=state.recipientRules[Number(input.dataset.ruleDays)].dias;return;}
   state.recipientRules[Number(input.dataset.ruleDays)].dias=days;renderThresholds();
  };
 });
 renderThresholds();
}
function renderThresholds(){
 const days=[...new Set(state.recipientRules.map(x=>x.dias))].sort((a,b)=>a-b);
 $('settingsThresholds').textContent=days.length?days.map(x=>`${x} dias`).join(' · '):'Nenhum destinatário';
}
function addRecipient(){
 const input=$('recipientEmail');const email=input.value.trim().toLowerCase();
 const days=Number($('recipientDays').value);
 if(!/^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,63}$/.test(email)){
  toast('Digite um endereço de e-mail válido.',true);input.focus();return;
 }
 const domain=email.split('@')[1]||'';
 if(!state.allowedInternalDomains.includes(domain)){toast('Destinatário bloqueado: somente e-mails corporativos internos autorizados.',true);input.focus();return;}
 if(!Number.isInteger(days)||days<1||days>365){toast('Digite um prazo entre 1 e 365 dias.',true);$('recipientDays').focus();return;}
 if(state.recipientRules.some(x=>x.email===email)){toast('Esse e-mail já está cadastrado. Altere os dias na linha do destinatário.',true);return;}
 if(state.recipientRules.length>=30){toast('Limite de 30 destinatários.',true);return;}
 state.recipientRules.push({email,dias:days});input.value='';renderRecipients();
}
async function loadSettings(){
 const config=await request('/api/configuracoes');
 state.allowedInternalDomains=config.dominios_internos||['clickdigital.com.br'];
 $('settingsEnabled').checked=config.habilitado;
 state.recipientRules=(config.regras_destinatarios||[]).map(x=>({...x}));renderRecipients();
 $('settingsSchedule').textContent=config.horario_execucao+' (Brasília)';
 $('smtpStatus').textContent=config.smtp_configurado?'Configurado':'Pendente de configuração no .env';
}
async function saveSettings(){
 // Lê valores ainda focados mesmo que o evento change não tenha ocorrido.
 for(const input of $('recipientList').querySelectorAll('input[data-rule-days]')){
   const days=Number(input.value);
   if(!Number.isInteger(days)||days<1||days>365){toast('Todos os prazos devem ser inteiros de 1 a 365 dias.',true);input.focus();return;}
   state.recipientRules[Number(input.dataset.ruleDays)].dias=days;
 }
 const enabled=$('settingsEnabled').checked;
 if(enabled&&!state.recipientRules.length){toast('Cadastre ao menos um destinatário para ativar alertas.',true);return;}
 const button=$('btnSaveSettings');button.disabled=true;
 try{
  const result=await request('/api/configuracoes',{method:'PUT',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({regras_destinatarios:state.recipientRules,habilitado:enabled})});
  toast(result.mensagem);await loadSettings();await reloadAll();
 }catch(e){toast(e.message,true);}finally{button.disabled=false;}
}
function selectView(hash){
 const config=hash==='#configuracoes';
 $('breadcrumbCurrent').textContent=config?'Configurações':'Visão geral';
 $('configView').classList.toggle('hidden',!config);
 $('dashboardView').classList.toggle('hidden',config);
 for(const element of document.querySelectorAll('.menu-item'))
  element.classList.toggle('active',element.getAttribute('href')===(config?'#configuracoes':hash||'#painel'));
 if(config)loadSettings().catch(e=>toast(e.message,true));
}
window.addEventListener('DOMContentLoaded',()=>{
 const now=new Date();$('todayDate').textContent=now.toLocaleDateString('pt-BR',{day:'2-digit',month:'long',year:'numeric'});
 $('footerYear').textContent=now.getFullYear();
 $('btnRefresh').onclick=()=>runAction($('btnRefresh'),'/api/atualizar','Atualização');
 $('btnTestEmail').onclick=()=>sendRealAlert($('btnTestEmail'));
 $('btnTestConfigEmail').onclick=()=>sendRealAlert($('btnTestConfigEmail'));
 $('btnMonitor').onclick=()=>runAction($('btnMonitor'),'/api/monitorar','Monitoramento',`Executar monitoramento agora? Se os alertas estiverem ativados, pode enviar e-mails exclusivamente para os destinatários internos configurados. Nenhum cliente recebe mensagens.`);
 $('recipientDays').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();addRecipient();}});
 const filter=debounced(()=>{state.page=1;loadClients().catch(e=>toast(e.message,true));});
 for(const id of ['searchId','filterFrom','filterTo'])$(id).addEventListener('input',filter);
 $('btnClear').onclick=()=>{for(const id of ['searchId','filterFrom','filterTo'])$(id).value='';state.page=1;loadClients().catch(e=>toast(e.message,true));};
 $('prevPage').onclick=()=>{if(state.page>1){state.page--;loadClients().catch(e=>toast(e.message,true));}};
 $('nextPage').onclick=()=>{if(state.page*state.limit<state.totalRows){state.page++;loadClients().catch(e=>toast(e.message,true));}};
 $('btnCSV').onclick=downloadCSV;$('btnCopySheets').onclick=copyToSheets;
 $('btnAddRecipient').onclick=addRecipient;
 $('recipientEmail').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();addRecipient();}});

 $('btnSaveSettings').onclick=saveSettings;
 for(const el of document.querySelectorAll('.menu-item'))el.onclick=()=>{selectView(el.getAttribute('href'));};
 selectView(location.hash);window.addEventListener('hashchange',()=>selectView(location.hash));
 reloadAll();setInterval(reloadAll,300000);
});
