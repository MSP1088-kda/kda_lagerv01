(function(){
  function isTypingTarget(el){
    if(!el) return false;
    const tag = (el.tagName || '').toLowerCase();
    return tag === 'input' || tag === 'textarea' || tag === 'select';
  }

  // Version line
  fetch('/meta/version').then(r=>r.json()).then(v=>{
    const el = document.getElementById('versionLine');
    if(!el) return;
    const buildDate = v.build_date || '';
    el.textContent = `v${v.version} (build ${v.build}, ${buildDate}, ${v.git_sha})`;
  }).catch(()=>{});

  // Keyboard shortcuts
  document.addEventListener('keydown', function(e){
    const active = document.activeElement;

    // "/" focuses search field
    if(e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey && !isTypingTarget(active)){
      const q = document.getElementById('q');
      if(q){
        e.preventDefault();
        q.focus();
        q.select();
      }
      return;
    }

    // ESC blurs
    if(e.key === 'Escape' && isTypingTarget(active)){
      active.blur();
      return;
    }

    // Alt+number navigation
    if(e.altKey && !e.ctrlKey && !e.metaKey){
      const k = e.key;
      const map = {
        '1': '/dashboard',
        '2': '/catalog/products',
        '3': '/inventory/stock',
        '4': '/settings/company',
      };
      if(map[k]){
        e.preventDefault();
        window.location.href = map[k];
      }
      if(k === '0'){
        // best-effort logout (submit form if exists)
        const f = document.querySelector('form[action="/logout"]');
        if(f){
          e.preventDefault();
          f.submit();
        }
      }
    }
  }, true);
})();
