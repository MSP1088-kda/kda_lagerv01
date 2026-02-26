(function(){
  function isTypingTarget(el){
    if(!el) return false;
    const tag = (el.tagName || '').toLowerCase();
    return tag === 'input' || tag === 'textarea' || tag === 'select';
  }

  function isAuthenticated(){
    return document.body && document.body.getAttribute('data-auth') === '1';
  }

  function normalizeText(v){
    return String(v || '').toLowerCase();
  }

  let kbdRows = [];
  let kbdIndex = -1;

  function setKbdSelection(index, scrollIntoView){
    if(!kbdRows.length) return;
    const next = Math.max(0, Math.min(index, kbdRows.length - 1));
    if(kbdIndex >= 0 && kbdRows[kbdIndex]){
      kbdRows[kbdIndex].classList.remove('kbd-selected');
    }
    kbdIndex = next;
    const row = kbdRows[kbdIndex];
    row.classList.add('kbd-selected');
    if(scrollIntoView){
      row.scrollIntoView({block: 'nearest'});
    }
  }

  function initKeyboardList(){
    const lists = Array.from(document.querySelectorAll('[data-kbd-list="true"]'));
    if(!lists.length) return;

    for(const list of lists){
      const rows = Array.from(list.querySelectorAll('[data-kbd-row="true"]'));
      if(!rows.length) continue;

      rows.forEach((row, idx) => {
        row.addEventListener('click', function(){
          kbdRows = rows;
          setKbdSelection(idx, false);
        });
      });

      if(!kbdRows.length){
        kbdRows = rows;
        setKbdSelection(0, false);
      }
    }
  }

  function moveKbdSelection(delta){
    if(!kbdRows.length) return false;
    setKbdSelection((kbdIndex >= 0 ? kbdIndex : 0) + delta, true);
    return true;
  }

  function openKbdSelection(){
    if(!kbdRows.length || kbdIndex < 0) return false;
    const row = kbdRows[kbdIndex];
    const href = row.getAttribute('data-href') || '';
    if(!href) return false;
    window.location.href = href;
    return true;
  }

  function scanUnsupported(input){
    alert('Kameraerkennung wird nicht unterstützt');
    if(input){
      input.focus();
    }
  }

  async function startSerialScan(input){
    if(!('BarcodeDetector' in window) || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia){
      scanUnsupported(input);
      return;
    }

    let detector;
    try{
      detector = new BarcodeDetector({
        formats: ['code_128', 'code_39', 'ean_13', 'ean_8', 'upc_a', 'upc_e', 'qr_code']
      });
    }catch(_e){
      detector = new BarcodeDetector();
    }

    const overlay = document.createElement('div');
    overlay.className = 'scan-overlay';
    overlay.innerHTML = `
      <div class="scan-panel">
        <video autoplay playsinline></video>
        <div class="row right">
          <button type="button" class="btn">Abbrechen</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const video = overlay.querySelector('video');
    const closeBtn = overlay.querySelector('button');
    let stream = null;
    let stopped = false;
    let timer = null;

    const stopScan = function(){
      if(stopped) return;
      stopped = true;
      if(timer){
        clearTimeout(timer);
      }
      if(stream){
        stream.getTracks().forEach(t => t.stop());
      }
      overlay.remove();
    };

    closeBtn.addEventListener('click', stopScan);

    try{
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' } },
        audio: false
      });
    }catch(_e){
      stopScan();
      scanUnsupported(input);
      return;
    }

    video.srcObject = stream;
    try{
      await video.play();
    }catch(_e){}

    const scanStep = async function(){
      if(stopped) return;
      try{
        const codes = await detector.detect(video);
        if(codes && codes.length && codes[0].rawValue){
          input.value = String(codes[0].rawValue);
          input.dispatchEvent(new Event('input', { bubbles: true }));
          stopScan();
          input.focus();
          return;
        }
      }catch(_e){}
      timer = setTimeout(scanStep, 200);
    };

    scanStep();
  }

  function initSerialScanButtons(){
    const serialInputs = Array.from(document.querySelectorAll('input[name="serial_number"]'));
    serialInputs.forEach(input => {
      if(input.dataset.scanReady === '1') return;
      if(document.querySelector(`[data-scan-target="${input.id}"]`)){
        input.dataset.scanReady = '1';
        return;
      }
      input.dataset.scanReady = '1';

      const wrap = document.createElement('div');
      wrap.className = 'scan-input-row';
      const parent = input.parentNode;
      if(!parent) return;
      parent.insertBefore(wrap, input);
      wrap.appendChild(input);

      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn scan-btn';
      btn.textContent = 'Scannen';
      btn.addEventListener('click', function(){
        startSerialScan(input);
      });
      wrap.appendChild(btn);
    });
  }

  function initGenericScanButtons(){
    const buttons = Array.from(document.querySelectorAll('[data-scan-target]'));
    buttons.forEach(btn => {
      if(btn.dataset.scanReady === '1') return;
      btn.dataset.scanReady = '1';
      btn.addEventListener('click', function(){
        const targetId = btn.getAttribute('data-scan-target') || '';
        if(!targetId) return;
        const input = document.getElementById(targetId);
        if(!input) return;
        startSerialScan(input);
      });
    });
  }

  function toggleHelpPanel(){
    const panel = document.getElementById('helpPanel');
    const btn = document.getElementById('helpToggle');
    if(!panel || !btn) return;

    const willShow = panel.hidden;
    panel.hidden = !willShow;
    btn.setAttribute('aria-expanded', willShow ? 'true' : 'false');
  }

  function initHelpPanel(){
    const btn = document.getElementById('helpToggle');
    if(!btn) return;
    btn.addEventListener('click', function(){
      toggleHelpPanel();
    });
  }

  function attachSelectFilter(inputId, selectId){
    const input = document.getElementById(inputId);
    const select = document.getElementById(selectId);
    if(!input || !select) return;

    const applyFilter = function(triggerKey){
      const q = String(input.value || '').trim().toLowerCase();
      let visibleCount = 0;
      let firstVisible = null;
      const options = Array.from(select.options || []);
      options.forEach(function(opt){
        const text = String(opt.textContent || '').toLowerCase();
        const visible = !q || text.indexOf(q) !== -1;
        opt.hidden = !visible;
        if(visible){
          visibleCount += 1;
          if(!firstVisible){
            firstVisible = opt;
          }
        }
      });
      if(triggerKey === 'Enter' && visibleCount === 1 && firstVisible){
        select.value = firstVisible.value;
        select.dispatchEvent(new Event('change', { bubbles: true }));
      }
    };

    input.addEventListener('keydown', function(e){
      if(e.key === 'Enter'){
        e.preventDefault();
      }
    });

    input.addEventListener('keyup', function(e){
      if(e.key === 'Escape'){
        input.value = '';
      }
      applyFilter(e.key);
    });

    applyFilter('');
  }

  function initProductAttributeReload(){
    const form = document.querySelector('[data-product-form="1"][data-product-new="1"]');
    if(!form) return;

    const kindSelect = form.querySelector('select[name="device_kind_id"]');
    const typeSelect = form.querySelector('select[name="device_type_id"]');
    if(!kindSelect && !typeSelect) return;

    const reload = function(){
      const url = new URL(window.location.href);
      const itemTypeEl = form.querySelector('input[name="item_type"], select[name="item_type"]');
      const itemType = itemTypeEl ? String(itemTypeEl.value || '').trim() : '';
      if(itemType){
        url.searchParams.set('item_type', itemType);
      }

      const kindVal = kindSelect ? String(kindSelect.value || '').trim() : '';
      const typeVal = typeSelect ? String(typeSelect.value || '').trim() : '';
      if(kindVal && kindVal !== '0'){
        url.searchParams.set('device_kind_id', kindVal);
      }else{
        url.searchParams.delete('device_kind_id');
      }
      if(typeVal && typeVal !== '0'){
        url.searchParams.set('device_type_id', typeVal);
      }else{
        url.searchParams.delete('device_type_id');
      }

      const query = url.searchParams.toString();
      window.location.href = query ? (url.pathname + '?' + query) : url.pathname;
    };

    if(kindSelect){
      kindSelect.addEventListener('change', reload);
    }
    if(typeSelect){
      typeSelect.addEventListener('change', reload);
    }
  }

  const cmdState = {
    open: false,
    selectedIndex: 0,
    filtered: []
  };

  const cmdCommands = [
    {name: 'Uebersicht', label: 'Übersicht', url: '/dashboard', aliases: 'start dashboard home'},
    {name: 'Suchen', label: 'Suchen', url: '/catalog/products', aliases: 'suche search find'},
    {name: 'Wareneingang', label: 'Wareneingang', url: '/inventory/transactions/new?tx_type=receipt', aliases: 'eingang receipt'},
    {name: 'Bestand', label: 'Bestand', url: '/inventory/stock', aliases: 'lager stock'},
    {name: 'Buchungen', label: 'Buchungen', url: '/inventory/transactions/new', aliases: 'transactions'},
    {name: 'Reservierungen', label: 'Reservierungen', url: '/inventory/reservations', aliases: 'reservierung reserve'},
    {name: 'Reparaturen', label: 'Reparaturen', url: '/inventory/reparaturen', aliases: 'rep reparatur repair'},
    {name: 'Produkte', label: 'Produkte', url: '/catalog/products', aliases: 'katalog artikel'},
    {name: 'Sets', label: 'Sets', url: '/catalog/sets', aliases: 'set module'},
    {name: 'Formularregeln', label: 'Formularregeln', url: '/stammdaten/formularregeln', aliases: 'stammdaten feldregeln formular'},
    {name: 'Hersteller', label: 'Hersteller', url: '/stammdaten/hersteller', aliases: 'vendor brand'},
    {name: 'Lieferanten', label: 'Lieferanten', url: '/stammdaten/lieferanten', aliases: 'supplier einkauf'},
    {name: 'Zustaende', label: 'Zustände', url: '/stammdaten/zustaende', aliases: 'zustand condition'},
    {name: 'Lagerorte', label: 'Lagerorte', url: '/inventory/warehouses', aliases: 'warehouse bins'},
    {name: 'System', label: 'System', url: '/settings/company', aliases: 'einstellungen settings'}
  ];

  function cmdPaletteElements(){
    return {
      wrap: document.getElementById('cmdPalette'),
      input: document.getElementById('cmdInput'),
      results: document.getElementById('cmdResults')
    };
  }

  function cmdFilter(text){
    const q = normalizeText(text).trim();
    if(!q){
      return cmdCommands.slice(0, 8);
    }
    const out = [];
    for(const row of cmdCommands){
      const hay = normalizeText(row.name + ' ' + row.label + ' ' + row.aliases);
      if(hay.indexOf(q) !== -1){
        out.push(row);
      }
      if(out.length >= 8) break;
    }
    return out;
  }

  function cmdRender(){
    const parts = cmdPaletteElements();
    if(!parts.results) return;
    const rows = cmdState.filtered;
    if(!rows.length){
      parts.results.innerHTML = '<div class="cmd-item muted">Keine Treffer. Enter startet Suche.</div>';
      return;
    }
    let html = '';
    rows.forEach((row, idx) => {
      const selected = idx === cmdState.selectedIndex ? ' cmd-item-active' : '';
      html += `<button type="button" class="cmd-item${selected}" data-cmd-index="${idx}">${row.label}</button>`;
    });
    parts.results.innerHTML = html;

    Array.from(parts.results.querySelectorAll('[data-cmd-index]')).forEach(btn => {
      btn.addEventListener('click', function(){
        const idx = parseInt(btn.getAttribute('data-cmd-index') || '0', 10) || 0;
        cmdState.selectedIndex = idx;
        cmdOpenSelected();
      });
    });
  }

  function cmdRefresh(){
    const parts = cmdPaletteElements();
    if(!parts.input) return;
    cmdState.filtered = cmdFilter(parts.input.value || '');
    if(cmdState.selectedIndex >= cmdState.filtered.length){
      cmdState.selectedIndex = Math.max(0, cmdState.filtered.length - 1);
    }
    cmdRender();
  }

  function cmdOpen(){
    if(!isAuthenticated()) return;
    const parts = cmdPaletteElements();
    if(!parts.wrap || !parts.input) return;
    cmdState.open = true;
    cmdState.selectedIndex = 0;
    parts.wrap.hidden = false;
    cmdRefresh();
    setTimeout(() => {
      parts.input.focus();
      parts.input.select();
    }, 0);
  }

  function cmdClose(){
    const parts = cmdPaletteElements();
    if(!parts.wrap) return;
    cmdState.open = false;
    parts.wrap.hidden = true;
  }

  function cmdToggle(){
    if(cmdState.open){
      cmdClose();
    }else{
      cmdOpen();
    }
  }

  function cmdOpenSelected(){
    const parts = cmdPaletteElements();
    const q = parts.input ? String(parts.input.value || '').trim() : '';
    const row = cmdState.filtered[cmdState.selectedIndex] || null;
    if(row && row.url){
      window.location.href = row.url;
      return;
    }
    if(q){
      window.location.href = '/catalog/products?q=' + encodeURIComponent(q);
      return;
    }
    cmdClose();
  }

  function cmdMove(delta){
    if(!cmdState.filtered.length) return;
    const next = cmdState.selectedIndex + delta;
    cmdState.selectedIndex = Math.max(0, Math.min(next, cmdState.filtered.length - 1));
    cmdRender();
  }

  function initCommandPalette(){
    const parts = cmdPaletteElements();
    if(!parts.wrap || !parts.input || !parts.results) return;

    parts.input.addEventListener('input', function(){
      cmdState.selectedIndex = 0;
      cmdRefresh();
    });

    parts.input.addEventListener('keydown', function(e){
      if(e.key === 'ArrowDown'){
        e.preventDefault();
        cmdMove(1);
        return;
      }
      if(e.key === 'ArrowUp'){
        e.preventDefault();
        cmdMove(-1);
        return;
      }
      if(e.key === 'Enter'){
        e.preventDefault();
        cmdOpenSelected();
        return;
      }
      if(e.key === 'Escape'){
        e.preventDefault();
        cmdClose();
      }
    });

    parts.wrap.addEventListener('click', function(e){
      if(e.target === parts.wrap){
        cmdClose();
      }
    });
  }

  function dashboardHotkeyMap(){
    return {
      '1': '/inventory/transactions/new?tx_type=receipt',
      '2': '/inventory/stock',
      '3': '/catalog/products',
      '4': '/stammdaten/lieferanten',
      '5': '/inventory/reparaturen',
      '6': '/catalog/sets',
      '7': '/settings/company'
    };
  }

  function handleDashboardDigitHotkey(e){
    if(e.altKey || e.ctrlKey || e.metaKey) return false;
    const dashboard = document.querySelector('[data-dashboard-hotkeys="1"]');
    if(!dashboard) return false;
    if(isTypingTarget(document.activeElement)) return false;
    const map = dashboardHotkeyMap();
    const href = map[e.key];
    if(!href) return false;
    e.preventDefault();
    window.location.href = href;
    return true;
  }

  function handleCtrlSave(e){
    const wantsSave = (e.key === 's' || e.key === 'S') && (e.ctrlKey || e.metaKey);
    if(!wantsSave || e.altKey) return false;
    const form = document.querySelector('[data-product-form="1"], [data-formularregeln-form="1"], [data-loadbee-form="1"]');
    if(!form) return false;
    e.preventDefault();
    if(typeof form.requestSubmit === 'function'){
      form.requestSubmit();
    }else{
      form.submit();
    }
    return true;
  }

  function handleItemTypeChooserHotkeys(e){
    const chooser = document.querySelector('[data-item-type-chooser="1"]');
    if(!chooser) return false;
    if(e.altKey || e.ctrlKey || e.metaKey) return false;
    if(isTypingTarget(document.activeElement)) return false;

    const map = {
      '1': 'appliance',
      '2': 'spare_part',
      '3': 'accessory',
      '4': 'material'
    };
    const selected = map[e.key];
    if(selected){
      e.preventDefault();
      window.location.href = '/catalog/products/new?item_type=' + selected;
      return true;
    }
    if(e.key === 'Escape'){
      e.preventDefault();
      window.location.href = '/catalog/products';
      return true;
    }
    return false;
  }

  function handleFormularregelnHotkeys(e){
    const page = document.querySelector('[data-formularregeln-page="1"]');
    if(!page) return false;
    if(e.altKey || e.ctrlKey || e.metaKey) return false;
    if(isTypingTarget(document.activeElement)) return false;
    const map = {
      '1': 'appliance',
      '2': 'spare_part',
      '3': 'accessory',
      '4': 'material'
    };
    const selected = map[e.key];
    if(!selected) return false;
    e.preventDefault();
    window.location.href = '/stammdaten/formularregeln?item_type=' + selected;
    return true;
  }

  function loadbeePanelElements(){
    return {
      toggleBtn: document.getElementById('lbToggleBtn'),
      reloadBtn: document.getElementById('lbReloadBtn'),
      panel: document.getElementById('lbPanel'),
      container: document.getElementById('loadbeeTabContentId'),
      statusEl: document.getElementById('lbStatus'),
      scriptTag: document.getElementById('loadbeeScript')
    };
  }

  function lbSetStatus(text, isError){
    const parts = loadbeePanelElements();
    if(!parts.statusEl) return;
    parts.statusEl.textContent = text;
    parts.statusEl.classList.toggle('flash-error', !!isError);
  }

  function lbSetToggleText(open){
    const parts = loadbeePanelElements();
    if(!parts.toggleBtn) return;
    parts.toggleBtn.textContent = open ? 'Hersteller-Details schließen' : 'Hersteller-Details öffnen';
    parts.toggleBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  function lbTryCheckAvailability(gtin, attempt){
    const safeGtin = String(gtin || '').trim();
    const tries = Number(attempt || 0);
    if(!safeGtin){
      lbSetStatus('Keine GTIN vorhanden. Bitte EAN prüfen.', true);
      return false;
    }
    const integration = window.loadbeeIntegration;
    if(integration && typeof integration.checkAvailability === 'function'){
      try{
        integration.checkAvailability(safeGtin);
        lbSetStatus('Hersteller-Details werden geladen...', false);
        return true;
      }catch(_e){
        lbSetStatus('Hersteller-Details konnten nicht geladen werden.', true);
        return false;
      }
    }
    if(tries >= 10){
      lbSetStatus('loadbee Script konnte nicht geladen werden. Netzwerk/Adblock prüfen.', true);
      return false;
    }
    window.setTimeout(function(){
      lbTryCheckAvailability(safeGtin, tries + 1);
    }, 300);
    return true;
  }

  function lbTogglePanel(){
    const parts = loadbeePanelElements();
    if(!parts.panel) return false;
    const willOpen = !parts.panel.classList.contains('open');
    if(willOpen){
      parts.panel.classList.add('open');
      lbSetToggleText(true);
      lbTryCheckAvailability(parts.panel.getAttribute('data-gtin') || '', 0);
    }else{
      parts.panel.classList.remove('open');
      lbSetToggleText(false);
    }
    return true;
  }

  function lbReloadPanel(){
    const parts = loadbeePanelElements();
    if(!parts.panel) return false;
    if(!parts.panel.classList.contains('open')){
      parts.panel.classList.add('open');
      lbSetToggleText(true);
    }
    lbTryCheckAvailability(parts.panel.getAttribute('data-gtin') || '', 0);
    return true;
  }

  function initLoadbeePanel(){
    const parts = loadbeePanelElements();
    if(!parts.panel) return;
    lbSetToggleText(parts.panel.classList.contains('open'));
    if(parts.toggleBtn){
      parts.toggleBtn.addEventListener('click', function(){
        lbTogglePanel();
      });
    }
    if(parts.reloadBtn){
      parts.reloadBtn.addEventListener('click', function(){
        lbReloadPanel();
      });
    }
    if(parts.scriptTag && parts.scriptTag.dataset.lbBound !== '1'){
      parts.scriptTag.dataset.lbBound = '1';
      parts.scriptTag.addEventListener('error', function(){
        lbSetStatus('loadbee Script konnte nicht geladen werden. Netzwerk/Adblock prüfen.', true);
      });
    }
    if(parts.panel.classList.contains('open')){
      lbTryCheckAvailability(parts.panel.getAttribute('data-gtin') || '', 0);
    }
  }

  fetch('/meta/version').then(r=>r.json()).then(v=>{
    const el = document.getElementById('versionLine');
    if(!el) return;
    const buildDate = v.build_date || '';
    el.textContent = `v${v.version} (Stand ${v.build}, ${buildDate}, ${v.git_sha})`;
  }).catch(()=>{});

  document.addEventListener('keydown', function(e){
    const active = document.activeElement;

    if(handleCtrlSave(e)){
      return;
    }

    if((e.key === 'k' || e.key === 'K') && e.ctrlKey && !e.metaKey){
      if(isAuthenticated()){
        e.preventDefault();
        cmdToggle();
      }
      return;
    }

    if(e.key === 'F2'){
      if(isAuthenticated()){
        e.preventDefault();
        cmdToggle();
      }
      return;
    }

    if(cmdState.open){
      if(e.key === 'Escape'){
        e.preventDefault();
        cmdClose();
      }
      return;
    }

    if(e.key === 'F1'){
      e.preventDefault();
      toggleHelpPanel();
      return;
    }

    if((e.key === '?' || (e.key === '/' && e.shiftKey)) && !e.ctrlKey && !e.metaKey && !e.altKey && !isTypingTarget(active)){
      e.preventDefault();
      toggleHelpPanel();
      return;
    }

    if(e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey && !isTypingTarget(active)){
      const q = document.getElementById('q');
      if(q){
        e.preventDefault();
        q.focus();
        q.select();
      }
      return;
    }

    if(e.key === 'Escape' && isTypingTarget(active)){
      active.blur();
      return;
    }

    if(handleDashboardDigitHotkey(e)){
      return;
    }

    if(handleItemTypeChooserHotkeys(e)){
      return;
    }

    if(handleFormularregelnHotkeys(e)){
      return;
    }

    if(!e.altKey && !e.ctrlKey && !e.metaKey && !isTypingTarget(active) && (e.key === 'h' || e.key === 'H')){
      if(lbTogglePanel()){
        e.preventDefault();
      }
      return;
    }

    if(!e.altKey && !e.ctrlKey && !e.metaKey && !isTypingTarget(active) && (e.key === 'r' || e.key === 'R')){
      if(lbReloadPanel()){
        e.preventDefault();
      }
      return;
    }

    if(!e.altKey && !e.ctrlKey && !e.metaKey && !isTypingTarget(active)){
      if(e.key === 'ArrowDown'){
        if(moveKbdSelection(1)){
          e.preventDefault();
        }
        return;
      }
      if(e.key === 'ArrowUp'){
        if(moveKbdSelection(-1)){
          e.preventDefault();
        }
        return;
      }
      if(e.key === 'Enter'){
        if(openKbdSelection()){
          e.preventDefault();
        }
        return;
      }
    }

    if(e.altKey && !e.ctrlKey && !e.metaKey){
      const map = {
        '1': '/dashboard',
        '2': '/catalog/products',
        '3': '/inventory/transactions/new?tx_type=receipt',
        '4': '/inventory/stock',
        '5': '/catalog/products',
        '6': '/stammdaten/formularregeln',
        '7': '/settings/company'
      };
      const href = map[e.key];
      if(href){
        e.preventDefault();
        window.location.href = href;
        return;
      }
      if(e.key === '0'){
        const f = document.querySelector('form[action="/logout"]');
        if(f){
          e.preventDefault();
          f.submit();
        }
      }
    }
  }, true);

  initKeyboardList();
  initGenericScanButtons();
  initSerialScanButtons();
  initHelpPanel();
  initCommandPalette();
  initLoadbeePanel();
  initProductAttributeReload();
  attachSelectFilter('tx_product_filter', 'tx_product_id');
  attachSelectFilter('reservation_product_filter', 'reservation_product_id');
  attachSelectFilter('set_item_product_filter', 'set_item_product_id');
  attachSelectFilter('repair_product_filter', 'repair_product_id');
})();
