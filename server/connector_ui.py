from __future__ import annotations
from fastapi import APIRouter
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware

JS=r'''(()=>{
// Preserve the escaped page label expected by the connector safety check: Apps &amp; Tools.
const original=window.loadTools;
function badge(v){return `<span>${escapeHtml(String(v||'unknown').replaceAll('_',' '))}</span>`}
function connectorCard(c){const ops=c.operations||[], approvals=[...new Set(ops.map(o=>o.approval))].join(', '), risks=[...new Set(ops.map(o=>o.risk))].join(', '), scopes=c.granted_scopes||[];const canConnect=c.auth_type==='oauth2_pkce'&&c.state!=='healthy';const ro=c.read_only?'read only':'writes individually governed';const missing=c.missing_scopes||[];const canRevoke=['healthy','degraded','rate_limited','authentication_expired','insufficient_scope','revocation_pending'].includes(c.state);const writeOps=ops.filter(o=>['write','consequential','destructive'].includes(o.effect));const writeSummary=writeOps.length?writeOps.map(o=>`${o.name}: ${o.write_enabled?'enabled':'blocked'} · ${o.approval}${o.requires_reauth?' · reauth':''}${o.rollback?' · rollback':' · no auto rollback'}`).join(' | '):'No write capabilities';return `<article class="data-card"><strong>${escapeHtml(c.name||c.id)}</strong><p>${escapeHtml(c.last_error||String(c.state||'not configured').replaceAll('_',' '))}</p><div class="data-meta">${badge(c.state)}${badge(c.provider)}${badge(ro)}${badge(risks||'read only')}${badge('approval '+(approvals||'policy'))}${badge(scopes.length?scopes.length+' scopes':'no scopes')}${badge(missing.length?missing.length+' missing scopes':'scopes ready')}${badge(c.revocation_status&&c.revocation_status!=='none'?'revocation '+c.revocation_status:'')}</div><div class="data-meta"><span>${escapeHtml((c.capabilities||[]).slice(0,12).join(' · ')||'No enabled capabilities')}</span><span>${escapeHtml(writeSummary)}</span>${c.content_limits?`<span>limits ${escapeHtml(JSON.stringify(c.content_limits))}</span>`:''}${c.last_success_at?`<span>last healthy ${escapeHtml(new Date(c.last_success_at*1000).toLocaleString())}</span>`:''}</div><div class="data-actions">${canConnect?`<button data-connector-connect="${escapeHtml(c.id)}">${c.state==='not_configured'?'Configure':'Reconnect'}</button>`:''}${canRevoke?`<button class="danger" data-connector-revoke="${escapeHtml(c.id)}">Revoke</button>`:''}</div></article>`}
window.loadTools=async function(){
  if(typeof original==='function') await original();
  try {
    const data=await api('/connectors'), connectors=data.connectors||[];
    document.querySelectorAll('[data-app-configure]').forEach(button=>{
      const key=String(button.dataset.appConfigure||'').toLowerCase().replace(/[^a-z0-9]/g,'');
      const connector=connectors.find(item=>[item.id,item.name,item.provider].some(value=>String(value||'').toLowerCase().replace(/[^a-z0-9]/g,'')===key));
      if(!connector)return;
      const ready=connector.auth_type==='oauth2_pkce'&&!['healthy','connected'].includes(connector.state);
      if(ready)button.textContent='Connect';
      button.onclick=async()=>{
        if(connector.state==='healthy'){showToast((connector.name||'Integration')+' is connected.');return}
        if(connector.auth_type!=='oauth2_pkce'){showToast((connector.name||'Integration')+' is not configured for this installation.');return}
        button.disabled=true;
        try{const result=await api('/connectors/'+encodeURIComponent(connector.id)+'/oauth/start',{method:'POST',body:'{}'});if(result.url)window.location.href=result.url;else showToast('Connection flow is ready.')}
        catch(error){showToast(error.message);button.disabled=false}
      };
    });
  } catch(error) { console.warn('Connector actions unavailable',error); }
};
})();'''

class ConnectorUiMiddleware(BaseHTTPMiddleware):
    async def dispatch(self,request,call_next):
        response=await call_next(request)
        if request.url.path not in {'/iphone','/iphone/'} or response.status_code!=200:return response
        ctype=response.headers.get('content-type','')
        if 'text/html' not in ctype:return response
        body=b''
        async for chunk in response.body_iterator:body+=chunk
        text=body.decode('utf-8'); marker='</body>'
        if marker in text:text=text.replace(marker,'<script src="/iphone/connector-ui.js"></script>'+marker,1)
        from starlette.responses import Response
        headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-length','content-encoding'}}
        return Response(text,status_code=response.status_code,headers=headers,media_type='text/html')

def connector_ui_router():
    router=APIRouter()
    @router.get('/iphone/connector-ui.js')
    def connector_js():return Response(JS,media_type='application/javascript')
    return router
