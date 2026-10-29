(function(root){
 'use strict';
 const doc=root.document;
 let pending=null;
 function eligible(target){
  const select=target?.closest?.('select');
  return root.matchMedia('(max-width:1100px)').matches && select && !select.disabled &&
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
  const cancel=()=>root.closeMobileChoiceModal();
  const observer=new MutationObserver(()=>{if(!select.isConnected)cancel();});
  pending=select;
  owner?.addEventListener('close',cancel);
  observer.observe(doc.body,{childList:true,subtree:true});
  try{
   const choice=await root.openMobileChoiceModal({title,options,value:oldValue});
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
  // Keep the following synthetic click from opening Android's native list.
  if(pending===select)return;
  void choose(select);
 }
 doc.addEventListener('pointerdown',event=>{
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
  if(event.key==='Escape' && doc.getElementById('mobileChoiceModal')?.open){
   event.preventDefault();event.stopImmediatePropagation();root.closeMobileChoiceModal();return;
  }
  if(!['Enter',' ','ArrowDown','ArrowUp','Home','End'].includes(event.key) || event.ctrlKey || event.metaKey)return;
  const select=eligible(event.target);if(!select)return;
  event.preventDefault();event.stopPropagation();void choose(select);
 },true);
})(window);
