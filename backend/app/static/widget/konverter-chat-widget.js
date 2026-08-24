(()=>{var j=["Summarize this document","What are the key recommendations?","Who published this and when?"];function K(c){let i=c.replace(/\r\n/g,`
`).split(`
`),r=[],e=0;for(;e<i.length;){if(!i[e].trim()){e+=1;continue}if(/^\s*[-*+]\s+/.test(i[e])){let a=[];for(;e<i.length;){let s=i[e].match(/^\s*[-*+]\s+(.*)/);if(!s)break;a.push(s[1]),e+=1}r.push({kind:"bullet-list",items:a});continue}if(/^\s*\d+[.)]\s+/.test(i[e])){let a=[];for(;e<i.length;){let s=i[e].match(/^\s*\d+[.)]\s+(.*)/);if(!s)break;a.push(s[1]),e+=1}r.push({kind:"numbered-list",items:a});continue}let d=[];for(;e<i.length&&i[e].trim()&&!/^\s*[-*+]\s+/.test(i[e])&&!/^\s*\d+[.)]\s+/.test(i[e]);)d.push(i[e].replace(/^#{1,6}\s+/,"")),e+=1;r.push({kind:"paragraph",text:d.join(" ")})}return r}function G(c){return c.replace(/(\*\*|__)(.*?)\1/g,"$2").replace(/(\*|_)(.*?)\1/g,"$2").replace(/^\s*[-*+]\s+/gm,"").replace(/^\s*\d+[.)]\s+/gm,"").replace(/\s+/g," ").trim()}function H(c,i){let r=i.split(/(\*\*[^*]+\*\*)/g).filter(e=>e!=="");for(let e of r){let d=e.match(/^\*\*([^*]+)\*\*$/);if(d){let a=document.createElement("strong");a.textContent=d[1],c.appendChild(a)}else c.appendChild(document.createTextNode(e))}}function W(c,i){c.innerHTML="";for(let r of K(i)){if(r.kind==="bullet-list"||r.kind==="numbered-list"){let d=document.createElement(r.kind==="bullet-list"?"ul":"ol");for(let a of r.items){let s=document.createElement("li");H(s,a),d.appendChild(s)}c.appendChild(d);continue}let e=document.createElement("p");H(e,r.text),c.appendChild(e)}}var V=`
.kcw-widget{position:fixed;right:24px;bottom:24px;z-index:2147483000;font-family:Arial,"Helvetica Neue",sans-serif}
.kcw-widget *{box-sizing:border-box}
.kcw-fab{display:flex;align-items:center;justify-content:center;width:56px;height:56px;border:none;border-radius:50%;background:#005493;color:#fff;box-shadow:0 8px 24px rgba(0,49,88,.32);cursor:pointer}
.kcw-fab[hidden]{display:none}
.kcw-fab:hover,.kcw-fab:focus-visible{background:#003f73}
.kcw-fab svg{width:24px;height:24px}
.kcw-panel{display:flex;flex-direction:column;width:min(380px,calc(100vw - 48px));height:min(560px,calc(100vh - 140px));background:#fff;border:1px solid #d5d5d5;border-radius:8px;box-shadow:0 16px 44px rgba(0,32,64,.22);padding:16px;gap:10px;color:#1c1c1c}
.kcw-panel[hidden]{display:none}
.kcw-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
.kcw-head h4{font-size:13px;font-weight:600;margin:0}
.kcw-hint{font-size:12px;color:#6b6b6b;margin:4px 0 0}
.kcw-close{display:flex;align-items:center;justify-content:center;width:28px;height:28px;flex-shrink:0;border:none;border-radius:6px;background:transparent;color:#6b6b6b;cursor:pointer}
.kcw-close:hover,.kcw-close:focus-visible{background:#f3f7fa;color:#1c1c1c}
.kcw-close svg{width:18px;height:18px}
.kcw-messages{display:flex;flex-direction:column;gap:8px;flex:1 1 auto;min-height:0;overflow-y:auto;padding-right:2px}
.kcw-empty{display:flex;flex-direction:column;gap:10px}
.kcw-empty p{font-size:12.5px;color:#6b6b6b;margin:0}
.kcw-starters{display:flex;flex-direction:column;gap:6px}
.kcw-starter{text-align:left;font-size:12.5px;font-weight:500;color:#003f73;background:#f3f7fa;border:1px solid #b8b8b8;border-radius:8px;padding:8px 12px;cursor:pointer}
.kcw-starter:hover,.kcw-starter:focus-visible{background:#f6f6f6;border-color:#005493}
.kcw-message{border-radius:8px;padding:8px 10px;font-size:13px;line-height:1.5;max-width:92%}
.kcw-message p{margin:8px 0 0;white-space:pre-wrap}
.kcw-message>*:first-child{margin-top:4px}
.kcw-message ul,.kcw-message ol{margin:8px 0 0;padding-left:20px}
.kcw-message li+li{margin-top:2px}
.kcw-role{font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.03em;color:#6b6b6b}
.kcw-message-user{background:#f3f7fb;align-self:flex-end}
.kcw-message-assistant{background:#f6f6f6}
.kcw-typing{display:inline-flex;align-items:center;gap:3px;margin-top:4px;height:14px}
.kcw-typing span{width:5px;height:5px;border-radius:50%;background:#6b6b6b;animation:kcw-bounce 1.1s ease-in-out infinite}
.kcw-typing span:nth-child(2){animation-delay:.15s}
.kcw-typing span:nth-child(3){animation-delay:.3s}
@keyframes kcw-bounce{0%,60%,100%{transform:translateY(0);opacity:.5}30%{transform:translateY(-3px);opacity:1}}
.kcw-error{font-size:12px;color:#8a1f1f;background:#fbeaea;border:1px solid #e3b7b7;border-radius:6px;padding:6px 9px;margin:0}
.kcw-input-row{display:flex;flex-direction:column;gap:8px}
.kcw-input-row textarea{resize:vertical;font:13px/1.4 Arial,"Helvetica Neue",sans-serif;padding:8px 10px;border:1px solid #b8b8b8;border-radius:6px;min-height:44px}
.kcw-char-count{align-self:flex-end;font-size:11px;color:#6b6b6b;margin-top:-4px}
.kcw-actions{display:flex;justify-content:flex-end;gap:6px}
.kcw-icon-btn{display:flex;align-items:center;justify-content:center;min-width:34px;height:34px;padding:7px;border:1px solid #b8b8b8;border-radius:6px;background:#fff;color:#1c1c1c;cursor:pointer}
.kcw-icon-btn[hidden]{display:none}
.kcw-icon-btn svg{width:16px;height:16px}
.kcw-icon-btn:disabled{opacity:.45;cursor:not-allowed}
.kcw-icon-btn.kcw-active{color:#003f73;background:#f3f7fa;border-color:#005493}
.kcw-icon-btn-primary{background:#005493;border-color:#003f73;color:#fff}
.kcw-icon-btn-primary:disabled{opacity:.45}
.kcw-status{font-size:11.5px;color:#6b6b6b;min-height:14px}
.kcw-sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media (max-width:520px){.kcw-widget{right:12px;bottom:12px}.kcw-panel{width:calc(100vw - 24px);height:min(520px,calc(100vh - 110px))}}
`,x={message:'<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>',close:'<path d="M18 6 6 18M6 6l12 12"/>',mic:'<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3"/>',micOff:'<path d="M2 2l20 20M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V5a3 3 0 0 0-5.94-.6M19 10v2a7 7 0 0 1-.11 1.23M12 19v3M8 23h8"/>',send:'<path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"/><path d="m21.854 2.147-10.94 10.939"/>',stop:'<rect width="14" height="14" x="5" y="5" rx="2"/>'};function y(c){return`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${c}</svg>`}function R(c){let i=c.apiBase.replace(/\/+$/,""),r=c.documentId,e=document.createElement("style");e.textContent=V,document.head.appendChild(e);let d=document.createElement("div");d.className="kcw-widget",document.body.appendChild(d);let a=document.createElement("button");a.type="button",a.className="kcw-fab",a.setAttribute("aria-label","Ask about this document"),a.innerHTML=y(x.message);let s=document.createElement("div");s.className="kcw-panel",s.hidden=!0,s.innerHTML=`
    <div class="kcw-head">
      <div>
        <h4>Ask about this document</h4>
        <p class="kcw-hint">Answers use this document&rsquo;s reviewed content and structured export as context.</p>
      </div>
      <button type="button" class="kcw-close" aria-label="Close chat">${y(x.close)}</button>
    </div>
    <div class="kcw-messages" role="log" aria-live="off"></div>
    <div class="kcw-sr-only" role="status" aria-live="polite"></div>
    <form class="kcw-input-row">
      <label class="kcw-sr-only" for="kcw-input">Ask a question about this document</label>
      <textarea id="kcw-input" rows="2" maxlength="4000" placeholder="Ask a question about this document\u2026"></textarea>
      <span class="kcw-char-count" hidden></span>
      <div class="kcw-actions">
        <button type="button" class="kcw-icon-btn kcw-mic-btn" aria-label="Start voice input" title="Start voice input" hidden>${y(x.mic)}</button>
        <button type="submit" class="kcw-icon-btn kcw-icon-btn-primary kcw-send-btn" aria-label="Send" title="Send" disabled>${y(x.send)}</button>
      </div>
    </form>
    <div class="kcw-status" aria-live="polite"></div>
  `,d.appendChild(a),d.appendChild(s);let b=s.querySelector(".kcw-messages"),N=s.querySelector(".kcw-sr-only"),B=s.querySelector(".kcw-input-row"),h=s.querySelector("#kcw-input"),E=s.querySelector(".kcw-char-count"),_=s.querySelector(".kcw-send-btn"),k=s.querySelector(".kcw-mic-btn"),O=s.querySelector(".kcw-close"),$=s.querySelector(".kcw-status"),p=[],C=!1,g=!1,l=null,S=window.SpeechRecognition||window.webkitSpeechRecognition;S&&(k.hidden=!1);function v(){if(b.innerHTML="",p.length===0){let t=document.createElement("div");t.className="kcw-empty";let n=document.createElement("p");n.textContent="Ask a question about this document to get started.",t.appendChild(n);let m=document.createElement("div");m.className="kcw-starters";for(let o of j){let f=document.createElement("button");f.type="button",f.className="kcw-starter",f.textContent=o,f.addEventListener("click",()=>void M(o)),m.appendChild(f)}t.appendChild(m),b.appendChild(t);return}for(let t of p){let n=document.createElement("div");n.className=`kcw-message kcw-message-${t.role}`;let m=document.createElement("span");if(m.className="kcw-role",m.textContent=t.role==="user"?"You":"Assistant",n.appendChild(m),t.content)if(t.role==="assistant"){let o=document.createElement("div");W(o,t.content),n.appendChild(o)}else{let o=document.createElement("p");o.textContent=t.content,n.appendChild(o)}else{let o=document.createElement("span");o.className="kcw-typing",o.setAttribute("role","status"),o.setAttribute("aria-label","Assistant is typing"),o.innerHTML="<span></span><span></span><span></span>",n.appendChild(o)}b.appendChild(n)}b.scrollTop=b.scrollHeight}function A(t){let n=s.querySelector(".kcw-error");if(!t){n==null||n.remove();return}n||(n=document.createElement("p"),n.className="kcw-error",n.setAttribute("role","alert"),b.insertAdjacentElement("afterend",n)),n.textContent=t}async function M(t){let n=t.trim();if(!n||C)return;A(null),h.value="",E.hidden=!0;let m=p.slice(-20).map(u=>({role:u.role,content:u.content}));p=[...p,{role:"user",content:n},{role:"assistant",content:""}],C=!0,_.disabled=!0,v();let o="",f=u=>{o+=u,p=[...p],p[p.length-1]={role:"assistant",content:o},v()};try{let u=await fetch(`${i}/public/documents/${encodeURIComponent(r)}/chat`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({message:n,history:m})});if(!u.ok){let T="The assistant couldn't answer that. Please try again.";try{let w=await u.clone().json();typeof(w==null?void 0:w.detail)=="string"&&(T=w.detail)}catch{}p=p.slice(0,-1),A(T),v();return}if(!u.body)f(await u.text());else{let T=u.body.getReader(),w=new TextDecoder;for(;;){let{done:D,value:I}=await T.read();if(D)break;f(w.decode(I,{stream:!0}))}}o.trim()&&(N.textContent=`Assistant replied: ${G(o)}`)}catch{p=p.slice(0,-1),A("The connection was interrupted. Please try again."),v()}finally{C=!1,_.disabled=!h.value.trim()}}B.addEventListener("submit",t=>{t.preventDefault(),M(h.value)}),h.addEventListener("input",()=>{_.disabled=!h.value.trim();let t=h.value.length;t>4e3*.9?(E.hidden=!1,E.textContent=`${t} / 4000`):E.hidden=!0}),h.addEventListener("keydown",t=>{t.key==="Enter"&&!t.shiftKey&&(t.preventDefault(),M(h.value))});function q(){l==null||l.stop()}function z(){!S||l||C||(l=new S,l.lang="en-AU",l.continuous=!1,l.interimResults=!1,l.onresult=t=>{var m,o,f,u;let n=(u=(f=(o=(m=t.results)==null?void 0:m[0])==null?void 0:o[0])==null?void 0:f.transcript)!=null?u:"";n.trim()&&M(n)},l.onerror=()=>{g=!1,l=null,L()},l.onend=()=>{g=!1,l=null,L()},g=!0,L(),l.start())}function L(){k.classList.toggle("kcw-active",g),k.innerHTML=y(g?x.micOff:x.mic),k.setAttribute("aria-label",g?"Stop voice input":"Start voice input"),$.textContent=g?"Listening\u2026":""}k.addEventListener("click",()=>{g?q():z()}),O.addEventListener("click",()=>{s.hidden=!0,a.hidden=!1}),a.addEventListener("click",()=>{a.hidden=!0,s.hidden=!1,h.focus()}),v()}(function(){if(window.__KONVERTER_CHAT_WIDGET_MOUNTED__)return;let i=window.__KONVERTER_CHAT__;!i||!i.documentId||!i.apiBase||(window.__KONVERTER_CHAT_WIDGET_MOUNTED__=!0,document.readyState==="loading"?document.addEventListener("DOMContentLoaded",()=>R(i)):R(i))})();})();
