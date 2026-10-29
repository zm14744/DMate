(function(root){
 'use strict';
 const pending=new WeakMap();let serial=0;
 function cancel(owner){pending.get(owner)?.finish(false);}
 function request(owner,settings={}){
  const doc=owner?.ownerDocument,win=doc?.defaultView;
  if(!doc||!win||!owner.isConnected)return Promise.resolve(false);
  cancel(owner);
  const parent=owner.closest('dialog');
  if(parent&&!parent.open)return Promise.resolve(false);
  return new Promise(resolve=>{
   const el=(tag,className,text)=>{const node=doc.createElement(tag);node.className=className;if(text!==undefined)node.textContent=text;return node;};
   const prompt=el('dialog','dmate-delete-confirm'),head=el('header','dmate-delete-confirm-head');
   const title=el('h3','dmate-delete-confirm-title',String(settings.title||'确认删除？'));
   const body=el('p','dmate-delete-confirm-body',String(settings.body||'删除后无法恢复。'));
   const actions=el('footer','dmate-delete-confirm-actions'),close=el('button','dmate-delete-confirm-close modal-close-dot');
   const confirm=el('button','dmate-delete-confirm-delete',String(settings.confirmText||'删除'));
   const previous=doc.activeElement;let finished=false,frame=0;
   title.id='dmateDeleteConfirmTitle'+(++serial);body.id='dmateDeleteConfirmBody'+serial;
   prompt.setAttribute('aria-labelledby',title.id);prompt.setAttribute('aria-describedby',body.id);
   prompt.dataset.positioning='true';close.type=confirm.type='button';close.title='取消删除';close.setAttribute('aria-label','取消删除');
   const finish=value=>{
    if(finished)return;finished=true;
    if(frame)win.cancelAnimationFrame(frame);
    parent?.removeEventListener('close',ownerClosed);
    if(pending.get(owner)?.node===prompt)pending.delete(owner);
    if(prompt.open)prompt.close();prompt.remove();
    // A backdrop pointerdown is followed by the browser's own focus step.
    // Restore after that step and after callers re-enable their delete trigger.
    win.requestAnimationFrame(()=>{if(!pending.has(owner)&&previous?.isConnected&&!previous.disabled&&(!parent||parent.open))previous.focus?.({preventScroll:true});});
    resolve(Boolean(value));
   };
   const ownerClosed=()=>finish(false);
   close.addEventListener('click',()=>finish(false));confirm.addEventListener('click',()=>finish(true));
   prompt.addEventListener('cancel',event=>{event.preventDefault();finish(false);});
   prompt.addEventListener('close',()=>finish(false));
   prompt.addEventListener('pointerdown',event=>{
    if(event.target!==prompt)return;const box=prompt.getBoundingClientRect();
    if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)finish(false);
   });
   head.append(title,close);actions.append(confirm);prompt.append(head,body,actions);
   pending.set(owner,{node:prompt,finish});(parent||owner).append(prompt);parent?.addEventListener('close',ownerClosed);
   try{
    prompt.showModal();prompt.getBoundingClientRect();
    frame=win.requestAnimationFrame(()=>{
     if(finished)return;prompt.getBoundingClientRect();
     frame=win.requestAnimationFrame(()=>{if(finished)return;delete prompt.dataset.positioning;close.focus({preventScroll:true});});
    });
   }catch(_){finish(false);}
  });
 }
 root.DMateDeleteConfirm={request,cancel};
})(typeof window!=='undefined'?window:globalThis);
