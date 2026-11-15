(function(root){
 'use strict';
 const doc=root.document;
 let pending=null,pointerIntent=null;
 // The online page already owns this API. Offline pages use the same dialog
 // and contract without borrowing handlers from a particular tool panel.
 if(typeof root.openMobileChoiceModal!=='function'){
  let current=null,version=0;
  const bound=new WeakSet();
  const finish=result=>{
   if(!current)return;
   const previous=current;current=null;++version;
   previous.modal.classList.add('hidden');previous.modal.setAttribute('aria-hidden','true');
   delete previous.modal.dataset.positioning;
   if(previous.modal.open)previous.modal.close();
   previous.resolve(result);
   const ownerDialog=previous.focus?.closest?.('dialog');
   if(previous.focus?.isConnected&&!previous.focus.disabled&&(!ownerDialog||ownerDialog.open))
    previous.focus.focus({preventScroll:true});
  };
  root.closeMobileChoiceModal=owner=>{
   // Event listeners also pass their MouseEvent here; only an explicit
   // control owner narrows the close request.
   if(owner instanceof root.Element&&current?.owner!==owner)return;
   finish(null);
  };
  root.openMobileChoiceModal=({title='请选择',intro='',options=[],value='',owner=null}={})=>{
   const modal=doc.getElementById('mobileChoiceModal'),list=doc.getElementById('mobileChoiceList');
   const titleEl=doc.getElementById('mobileChoiceTitle'),introEl=doc.getElementById('mobileChoiceIntro');
   if(!modal||!list||!titleEl||!introEl)return Promise.resolve(null);
   finish(null);
   if(!bound.has(modal)){
    modal.addEventListener('cancel',event=>{event.preventDefault();root.closeMobileChoiceModal();});
    modal.addEventListener('close',()=>{if(!modal.open)root.closeMobileChoiceModal();});
    modal.addEventListener('click',event=>{
     if(event.target===modal||event.target.closest?.('#mobileChoiceClose'))root.closeMobileChoiceModal();
    });
    bound.add(modal);
   }
   const rows=Array.isArray(options)?options.map(row=>({value:String(row.value??''),
    label:String(row.label??row.value??''),disabled:row.disabled===true})):[];
   titleEl.textContent=String(title||'请选择');introEl.textContent=String(intro||'');
   introEl.hidden=!intro;introEl.classList.toggle('hidden',!intro);
   list.replaceChildren(...rows.map(row=>{
    const button=doc.createElement('button');button.type='button';button.className='mobile-choice-option';
    button.disabled=row.disabled;button.classList.toggle('active',row.value===String(value));
    button.setAttribute('role','radio');button.setAttribute('aria-checked',String(row.value===String(value)));
    const label=doc.createElement('span');label.className='mobile-choice-option-text';label.textContent=row.label;
    button.append(label);button.addEventListener('click',()=>{if(!row.disabled)finish(row);});return button;
   }));
   root.DMateI18n?.translate?.(modal);
   return new Promise(resolve=>{
    const ownVersion=++version;
    current={modal,resolve,owner,focus:owner instanceof root.Element?owner:doc.activeElement};
    modal.classList.remove('hidden');modal.setAttribute('aria-hidden','false');modal.dataset.positioning='true';
    if(typeof modal.showModal==='function'&&!modal.open)modal.showModal();
    root.requestAnimationFrame(()=>root.requestAnimationFrame(()=>{
     if(version!==ownVersion||!current)return;
     delete modal.dataset.positioning;
     (list.querySelector('.active:not(:disabled)')||list.querySelector('button:not(:disabled)')
      ||doc.getElementById('mobileChoiceClose'))?.focus({preventScroll:true});
    }));
   });
  };
 }
 function eligible(target){
  const select=target?.closest?.('select') || target?.closest?.('label')?.control;
  return root.matchMedia('(max-width:1100px)').matches && select?.tagName==='SELECT' && !select.disabled &&
   select.dataset.dmateNativeSelect!=='true' &&
   !select.multiple && select.size<=1 && select.options.length &&
   typeof root.openMobileChoiceModal==='function' ? select : null;
 }
 async function choose(select){
  if(pending)return;
  const owner=select.closest('dialog'),oldValue=select.value;
  const options=[...select.options].filter(option=>!option.hidden).map(option=>({
   value:option.value,label:option.label,
   disabled:option.disabled || option.parentElement?.disabled===true
  }));
  if(!options.length)return;
  const title=select.getAttribute('aria-label') || select.labels?.[0]?.querySelector('span')?.textContent || '请选择';
  const cancel=()=>root.closeMobileChoiceModal(select);
  const observer=new MutationObserver(()=>{if(!select.isConnected||select.disabled)cancel();});
  pending=select;
  owner?.addEventListener('close',cancel);
  observer.observe(doc.body,{childList:true,subtree:true});
  observer.observe(select,{attributes:true,attributeFilter:['disabled']});
  try{
   const choice=await root.openMobileChoiceModal({title,options,value:oldValue,owner:select});
   if(!choice || !select.isConnected || select.disabled || (owner&&!owner.open) || select.value!==oldValue)return;
   const option=[...select.options].find(row=>row.value===choice.value);
   if(!option || option.hidden || option.disabled || option.parentElement?.disabled===true || choice.value===oldValue)return;
   select.value=choice.value;
   select.dispatchEvent(new Event('input',{bubbles:true}));
   select.dispatchEvent(new Event('change',{bubbles:true}));
  }finally{
   pending=null;observer.disconnect();owner?.removeEventListener('close',cancel);
   if(select.isConnected && !select.disabled && (!owner||owner.open))select.focus({preventScroll:true});
  }
 }
 function activate(event){
  const select=eligible(event.target);if(!select)return;
  event.preventDefault();
  // Selecting a canvas edge can insert this field before the finger's click
  // arrives. Only open for a gesture which actually began on this control.
  const recent=pointerIntent && performance.now()-pointerIntent.time<1000;
  if((event.detail>0 || event.isTrusted&&recent) && (!recent || pointerIntent.select!==select))return;
  // Keep the following synthetic click from opening Android's native list.
  if(pending===select)return;
  void choose(select);
 }
 doc.addEventListener('pointerdown',event=>{
  pointerIntent={select:eligible(event.target),time:performance.now()};
  const chooser=event.target.closest?.('#mobileChoiceModal');
  if(chooser?.open){
   // The underlying drawing/scan panels must not treat option taps as outside clicks.
   if(event.target===chooser)root.closeMobileChoiceModal();
   event.stopImmediatePropagation();return;
  }
  if(eligible(event.target))event.preventDefault();
 },true);
 doc.addEventListener('click',activate,true);
 doc.addEventListener('keydown',event=>{
  pointerIntent=null;
  if(event.key==='Escape' && doc.getElementById('mobileChoiceModal')?.open){
   event.preventDefault();event.stopImmediatePropagation();root.closeMobileChoiceModal();return;
  }
  if(!['Enter',' ','ArrowDown','ArrowUp','Home','End'].includes(event.key) || event.ctrlKey || event.metaKey)return;
  const select=eligible(event.target);if(!select)return;
  event.preventDefault();event.stopPropagation();void choose(select);
 },true);
})(window);
