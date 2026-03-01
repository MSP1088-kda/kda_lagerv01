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

  function rowDetailsHref(row){
    if(!row) return '';
    return row.getAttribute('data-details-href') || row.getAttribute('data-href') || '';
  }

  function rowBookHref(row){
    if(!row) return '';
    return row.getAttribute('data-book-href') || '';
  }

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
        if(!row.classList.contains('kbd-row')){
          row.classList.add('kbd-row');
        }
        if(!row.hasAttribute('tabindex')){
          row.setAttribute('tabindex', '0');
        }

        const bindSelection = function(){
          kbdRows = rows;
          setKbdSelection(idx, false);
        };

        row.addEventListener('click', bindSelection);
        row.addEventListener('focus', bindSelection);
        row.addEventListener('keydown', function(e){
          if(e.altKey || e.ctrlKey || e.metaKey) return;
          if(document.activeElement !== row) return;

          if(e.key === 'ArrowDown'){
            e.preventDefault();
            kbdRows = rows;
            setKbdSelection(idx + 1, true);
            const next = kbdRows[kbdIndex];
            if(next && typeof next.focus === 'function'){
              next.focus();
            }
            return;
          }
          if(e.key === 'ArrowUp'){
            e.preventDefault();
            kbdRows = rows;
            setKbdSelection(idx - 1, true);
            const prev = kbdRows[kbdIndex];
            if(prev && typeof prev.focus === 'function'){
              prev.focus();
            }
            return;
          }
          if(e.key === 'Enter'){
            const href = rowDetailsHref(row);
            if(!href) return;
            e.preventDefault();
            window.location.href = href;
            return;
          }
          if(e.key === 'i' || e.key === 'I'){
            const href = rowBookHref(row);
            if(!href) return;
            e.preventDefault();
            window.location.href = href;
          }
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
    const href = rowDetailsHref(row);
    if(!href) return false;
    window.location.href = href;
    return true;
  }

  function openKbdBookSelection(){
    if(!kbdRows.length || kbdIndex < 0) return false;
    const row = kbdRows[kbdIndex];
    const href = rowBookHref(row);
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

  function initNavDropdowns(){
    const groups = Array.from(document.querySelectorAll('[data-nav-dropdown]'));
    if(!groups.length) return;

    const focusableItems = function(menu){
      return Array.from(menu.querySelectorAll('a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'));
    };

    const setOpen = function(group, nextOpen, focusFirst){
      const toggle = group.querySelector('[data-nav-dropdown-toggle]');
      const menu = group.querySelector('[data-nav-dropdown-menu]');
      if(!toggle || !menu) return;

      toggle.setAttribute('aria-expanded', nextOpen ? 'true' : 'false');
      menu.hidden = !nextOpen;
      if(nextOpen && focusFirst){
        const first = focusableItems(menu)[0];
        if(first && typeof first.focus === 'function'){
          first.focus();
        }
      }
    };

    const closeAll = function(exceptGroup){
      groups.forEach(group => {
        if(exceptGroup && group === exceptGroup) return;
        setOpen(group, false, false);
      });
    };

    groups.forEach(group => {
      const toggle = group.querySelector('[data-nav-dropdown-toggle]');
      const menu = group.querySelector('[data-nav-dropdown-menu]');
      if(!toggle || !menu) return;

      setOpen(group, false, false);

      toggle.addEventListener('click', function(e){
        e.preventDefault();
        const isOpen = toggle.getAttribute('aria-expanded') === 'true';
        closeAll(group);
        setOpen(group, !isOpen, false);
      });

      toggle.addEventListener('keydown', function(e){
        if(e.key === 'ArrowDown'){
          e.preventDefault();
          closeAll(group);
          setOpen(group, true, true);
          return;
        }
        if(e.key === 'Enter' || e.key === ' '){
          e.preventDefault();
          const isOpen = toggle.getAttribute('aria-expanded') === 'true';
          closeAll(group);
          setOpen(group, !isOpen, !isOpen);
          return;
        }
        if(e.key === 'Escape'){
          e.preventDefault();
          setOpen(group, false, false);
        }
      });

      menu.addEventListener('keydown', function(e){
        const items = focusableItems(menu);
        if(!items.length) return;
        const currentIndex = items.indexOf(document.activeElement);
        if(e.key === 'ArrowDown'){
          e.preventDefault();
          const nextIndex = currentIndex < 0 ? 0 : (currentIndex + 1) % items.length;
          items[nextIndex].focus();
          return;
        }
        if(e.key === 'ArrowUp'){
          e.preventDefault();
          const prevIndex = currentIndex <= 0 ? items.length - 1 : currentIndex - 1;
          items[prevIndex].focus();
          return;
        }
        if(e.key === 'Escape'){
          e.preventDefault();
          setOpen(group, false, false);
          toggle.focus();
        }
      });

      group.addEventListener('focusout', function(){
        window.setTimeout(function(){
          if(!group.contains(document.activeElement)){
            setOpen(group, false, false);
          }
        }, 0);
      });
    });

    document.addEventListener('click', function(e){
      const target = e.target;
      if(!(target instanceof Element)) return;
      const inGroup = target.closest('[data-nav-dropdown]');
      if(inGroup){
        closeAll(inGroup);
        return;
      }
      closeAll(null);
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

    const areaSelect = form.querySelector('select[name="area_id"]');
    const kindSelect = form.querySelector('select[name="device_kind_id"]');
    const typeSelect = form.querySelector('select[name="device_type_id"]');
    if(!areaSelect && !kindSelect && !typeSelect) return;

    const reload = function(source){
      const url = new URL(window.location.href);
      const itemTypeEl = form.querySelector('input[name="item_type"], select[name="item_type"]');
      const itemType = itemTypeEl ? String(itemTypeEl.value || '').trim() : '';
      if(itemType){
        url.searchParams.set('item_type', itemType);
      }else{
        url.searchParams.delete('item_type');
      }

      const areaVal = areaSelect ? String(areaSelect.value || '').trim() : '';
      if(areaVal && areaVal !== '0'){
        url.searchParams.set('area_id', areaVal);
      }else{
        url.searchParams.delete('area_id');
      }

      if(source === 'area'){
        if(kindSelect){
          kindSelect.value = '0';
        }
        if(typeSelect){
          typeSelect.value = '0';
        }
      }else if(source === 'kind' && typeSelect){
        typeSelect.value = '0';
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

    if(areaSelect){
      areaSelect.addEventListener('change', function(){
        reload('area');
      });
    }
    if(kindSelect){
      kindSelect.addEventListener('change', function(){
        reload('kind');
      });
    }
    if(typeSelect){
      typeSelect.addEventListener('change', function(){
        reload('type');
      });
    }
  }

  function initCatalogListCascadeFilter(){
    const form = document.querySelector('form[data-catalog-cascade-filter="1"]');
    if(!form) return;
    const areaSelect = form.querySelector('#catalog_area_id');
    const kindSelect = form.querySelector('#catalog_kind_id');
    const typeSelect = form.querySelector('#catalog_type_id');
    if(!areaSelect && !kindSelect && !typeSelect) return;

    const syncKindOptions = function(){
      if(!kindSelect) return;
      const selectedArea = areaSelect ? String(areaSelect.value || '0') : '0';
      const options = Array.from(kindSelect.options || []);
      options.forEach(function(opt){
        const value = String(opt.value || '');
        if(value === '' || value === '0'){
          opt.hidden = false;
          return;
        }
        const areaId = String(opt.getAttribute('data-area-id') || '');
        const visible = !selectedArea || selectedArea === '0' || !areaId || areaId === selectedArea;
        opt.hidden = !visible;
      });
      const selected = kindSelect.options[kindSelect.selectedIndex] || null;
      if(selected && selected.hidden){
        kindSelect.value = '0';
      }
    };

    const syncTypeOptions = function(){
      if(!typeSelect) return;
      const selectedArea = areaSelect ? String(areaSelect.value || '0') : '0';
      const selectedKind = kindSelect ? String(kindSelect.value || '0') : '0';
      const options = Array.from(typeSelect.options || []);
      options.forEach(function(opt){
        const value = String(opt.value || '');
        if(value === '' || value === '0'){
          opt.hidden = false;
          return;
        }
        const kindId = String(opt.getAttribute('data-kind-id') || '');
        const areaId = String(opt.getAttribute('data-area-id') || '');
        let visible = true;
        if(selectedKind && selectedKind !== '0'){
          visible = (kindId === selectedKind);
        }else if(selectedArea && selectedArea !== '0'){
          visible = (!areaId || areaId === selectedArea);
        }
        opt.hidden = !visible;
      });
      const selected = typeSelect.options[typeSelect.selectedIndex] || null;
      if(selected && selected.hidden){
        typeSelect.value = '0';
      }
    };

    const submit = function(){
      if(typeof form.requestSubmit === 'function'){
        form.requestSubmit();
      }else{
        form.submit();
      }
    };

    if(areaSelect){
      areaSelect.addEventListener('change', function(){
        syncKindOptions();
        if(typeSelect) typeSelect.value = '0';
        syncTypeOptions();
        submit();
      });
    }
    if(kindSelect){
      kindSelect.addEventListener('change', function(){
        syncTypeOptions();
        submit();
      });
    }
    if(typeSelect){
      typeSelect.addEventListener('change', function(){
        submit();
      });
    }

    syncKindOptions();
    syncTypeOptions();
  }

  function initImportMapCascadeDefaults(){
    const form = document.querySelector('form[data-import-map-form="1"]');
    if(!form) return;
    const areaSelect = form.querySelector('select[name="manual_area_id"]');
    const kindSelect = form.querySelector('select[name="manual_kind_id"]');
    const typeSelect = form.querySelector('select[name="manual_type_id"]');
    if(!areaSelect || !kindSelect || !typeSelect) return;

    const syncKindOptions = function(){
      const selectedArea = String(areaSelect.value || '');
      const options = Array.from(kindSelect.options || []);
      options.forEach(function(opt){
        const value = String(opt.value || '');
        if(!value){
          opt.hidden = false;
          return;
        }
        const areaId = String(opt.getAttribute('data-area-id') || '');
        const visible = !selectedArea || !areaId || areaId === selectedArea;
        opt.hidden = !visible;
      });
      const selected = kindSelect.options[kindSelect.selectedIndex] || null;
      if(selected && selected.hidden){
        kindSelect.value = '';
      }
    };

    const syncTypeOptions = function(){
      const selectedArea = String(areaSelect.value || '');
      const selectedKind = String(kindSelect.value || '');
      const options = Array.from(typeSelect.options || []);
      options.forEach(function(opt){
        const value = String(opt.value || '');
        if(!value){
          opt.hidden = false;
          return;
        }
        const kindId = String(opt.getAttribute('data-kind-id') || '');
        const areaId = String(opt.getAttribute('data-area-id') || '');
        let visible = true;
        if(selectedKind){
          visible = (kindId === selectedKind);
        }else if(selectedArea){
          visible = (!areaId || areaId === selectedArea);
        }
        opt.hidden = !visible;
      });
      const selected = typeSelect.options[typeSelect.selectedIndex] || null;
      if(selected && selected.hidden){
        typeSelect.value = '';
      }
    };

    areaSelect.addEventListener('change', function(){
      syncKindOptions();
      syncTypeOptions();
    });
    kindSelect.addEventListener('change', function(){
      syncTypeOptions();
    });

    syncKindOptions();
    syncTypeOptions();
  }

  function initTxFormAdjustActions(){
    const form = document.querySelector('form[action="/inventory/transactions/new"]');
    if(!form) return;
    const txType = form.querySelector('select[name="tx_type"]');
    const setZeroWrap = document.getElementById('tx_set_zero_wrap');
    if(!txType || !setZeroWrap) return;

    const sync = function(){
      setZeroWrap.hidden = String(txType.value || '') !== 'adjust';
    };
    txType.addEventListener('change', sync);
    sync();
  }

  function initProductDetailPanels(){
    const priceToggleBtn = document.getElementById('priceToggleBtn');
    const pricePanel = document.getElementById('priceEditPanel');
    if(priceToggleBtn && pricePanel){
      priceToggleBtn.addEventListener('click', function(){
        const next = !!pricePanel.hidden;
        pricePanel.hidden = !next;
        priceToggleBtn.setAttribute('aria-expanded', next ? 'true' : 'false');
        if(next){
          const first = pricePanel.querySelector('input,select,textarea,button');
          if(first) first.focus();
        }
      });
    }

    const orderToggleBtn = document.getElementById('orderToggleBtn');
    const orderPanel = document.getElementById('orderCreatePanel');
    if(orderToggleBtn && orderPanel){
      orderToggleBtn.addEventListener('click', function(){
        const next = !!orderPanel.hidden;
        orderPanel.hidden = !next;
        orderToggleBtn.setAttribute('aria-expanded', next ? 'true' : 'false');
        if(next){
          const first = orderPanel.querySelector('input,select,textarea,button');
          if(first) first.focus();
        }
      });
    }
  }

  function initRepairCreateProductToggle(){
    const checkbox = document.getElementById('repair_create_product_chk');
    const box = document.getElementById('repair_create_product_box');
    const select = document.getElementById('repair_product_id');
    if(!checkbox || !box || !select) return;
    const sync = function(){
      const on = !!checkbox.checked;
      box.hidden = !on;
      select.required = !on;
    };
    checkbox.addEventListener('change', sync);
    sync();
  }

  function initFirstErrorFocus(){
    const marker = document.querySelector('[data-first-error]');
    const fromMarker = marker ? String(marker.getAttribute('data-first-error') || '').trim() : '';
    const fromBody = document.body ? String(document.body.getAttribute('data-first-error') || '').trim() : '';
    const fromWindow = String(window.__firstErrorFieldId || '').trim();
    const targetId = fromWindow || fromBody || fromMarker;
    if(!targetId) return;
    window.setTimeout(function(){
      const target = document.getElementById(targetId);
      if(!target || typeof target.focus !== 'function') return;
      target.focus();
      if(typeof target.select === 'function'){
        target.select();
      }
    }, 0);
  }

  function toggleCustomerViewMode(){
    fetch('/ui/customer_view/toggle', {
      method: 'POST',
      headers: { 'Accept': 'application/json' }
    }).then(function(){
      window.location.reload();
    }).catch(function(){
      window.location.reload();
    });
  }

  function handleQuickPageHotkeys(e){
    const page = document.querySelector('[data-quick-page="1"]');
    if(!page) return false;
    if(e.altKey || e.ctrlKey || e.metaKey) return false;
    if(isTypingTarget(document.activeElement)) return false;
    const map = {
      '1': '/inventory/transactions/new?tx_type=receipt',
      '2': '/inventory/transactions/new?tx_type=issue',
      '3': '/inventory/reparaturen/new',
      '4': '/inventory/reparaturen',
      '5': '/purchase/orders',
      '6': '/catalog/products'
    };
    const href = map[e.key];
    if(!href) return false;
    e.preventDefault();
    window.location.href = href;
    return true;
  }

  const cmdState = {
    open: false,
    selectedIndex: 0,
    filtered: []
  };

  function cmdFallbackCommands(){
    return [
      {name: 'Uebersicht', label: 'Übersicht', url: '/dashboard', aliases: 'start dashboard'},
      {name: 'Katalog', label: 'Katalog', url: '/catalog/products', aliases: 'katalog artikel lager bestand'},
      {name: 'Menue', label: 'Menü', url: '/menu', aliases: 'alles navigation'}
    ];
  }

  function readNavCommands(){
    const raw = Array.isArray(window.__navCommands) ? window.__navCommands : [];
    const out = [];
    const seen = new Set();
    raw.forEach(row => {
      const label = String(row.label || row.label_de || '').trim();
      const group = String(row.group || '').trim();
      const url = String(row.url || row.path || '').trim();
      if(!label || !url) return;
      const key = `${label}|${url}`;
      if(seen.has(key)) return;
      seen.add(key);
      out.push({
        name: label,
        label: group ? `${label} (${group})` : label,
        url: url,
        aliases: String(row.aliases || '').trim(),
        hotkey: String(row.hotkey || '').trim()
      });
    });
    return out.length ? out : cmdFallbackCommands();
  }

  const cmdCommands = readNavCommands();

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
      const hotkey = row.hotkey ? ` <span class=\"muted\">${row.hotkey}</span>` : '';
      html += `<button type="button" class="cmd-item${selected}" data-cmd-index="${idx}">${row.label}${hotkey}</button>`;
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
      '2': '/catalog/products',
      '3': '/stammdaten/lieferanten',
      '4': '/inventory/reparaturen',
      '5': '/catalog/sets',
      '6': '/settings/company'
    };
  }

  function runtimeAltHotkeys(){
    const raw = (window.__navHotkeys && typeof window.__navHotkeys === 'object') ? window.__navHotkeys : {};
    const out = {};
    Object.keys(raw).forEach(key => {
      const match = /^alt\+([0-9])$/i.exec(String(key || '').trim());
      if(!match) return;
      const digit = match[1];
      const href = String(raw[key] || '').trim();
      if(!href) return;
      out[digit] = href;
    });
    return out;
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
    const form = document.querySelector('[data-product-form="1"], [data-formularregeln-form="1"], [data-loadbee-form="1"], [data-price-form="1"]');
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

  function handleProductDetailHotkeys(e){
    const page = document.querySelector('[data-page="product-detail"]');
    if(!page) return false;
    if(e.altKey || e.ctrlKey || e.metaKey) return false;
    if(isTypingTarget(document.activeElement)) return false;

    if(e.key === 'e' || e.key === 'E'){
      const btn = document.getElementById('detailEditBtn');
      if(!btn) return false;
      e.preventDefault();
      btn.click();
      return true;
    }
    if(e.key === 'a' || e.key === 'A'){
      const btn = document.getElementById('detailArchiveBtn');
      if(!btn || btn.disabled) return false;
      e.preventDefault();
      btn.click();
      return true;
    }
    if(e.key === 'i' || e.key === 'I'){
      const btn = document.getElementById('detailReceiptBtn');
      if(!btn || btn.disabled) return false;
      e.preventDefault();
      btn.click();
      return true;
    }
    return false;
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

    if(e.key === 'F9' && !e.altKey && !e.ctrlKey && !e.metaKey){
      if(isAuthenticated()){
        e.preventDefault();
        toggleCustomerViewMode();
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

    if(handleQuickPageHotkeys(e)){
      return;
    }

    if(handleProductDetailHotkeys(e)){
      return;
    }

    if(!e.altKey && !e.ctrlKey && !e.metaKey && !isTypingTarget(active)){
      if(e.key === 'p' || e.key === 'P'){
        const btn = document.getElementById('priceToggleBtn');
        if(btn){
          e.preventDefault();
          btn.click();
          return;
        }
      }
      if(e.key === 'a' || e.key === 'A'){
        const btn = document.getElementById('applyRuleBtn');
        if(btn){
          e.preventDefault();
          btn.click();
          return;
        }
      }
      if(e.key === 'b' || e.key === 'B'){
        const btn = document.getElementById('orderToggleBtn');
        if(btn){
          e.preventDefault();
          btn.click();
          return;
        }
      }
      if(e.key === 'i' || e.key === 'I'){
        if(openKbdBookSelection()){
          e.preventDefault();
          return;
        }
        const form = document.getElementById('repairSendForm');
        if(form){
          e.preventDefault();
          form.submit();
          return;
        }
      }
      if(e.key === 'z' || e.key === 'Z'){
        const form = document.getElementById('repairReturnForm');
        if(form){
          e.preventDefault();
          form.submit();
          return;
        }
      }
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
      if(e.key === 'l' || e.key === 'L'){
        const draftClear = document.querySelector('[data-draft-clear-form="1"]');
        if(draftClear){
          e.preventDefault();
          if(typeof draftClear.requestSubmit === 'function'){
            draftClear.requestSubmit();
          }else{
            draftClear.submit();
          }
          return;
        }
      }
      const map = runtimeAltHotkeys();
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
  initNavDropdowns();
  initCommandPalette();
  initLoadbeePanel();
  initProductAttributeReload();
  initCatalogListCascadeFilter();
  initImportMapCascadeDefaults();
  initTxFormAdjustActions();
  initProductDetailPanels();
  initRepairCreateProductToggle();
  initFirstErrorFocus();
  attachSelectFilter('tx_product_filter', 'tx_product_id');
  attachSelectFilter('reservation_product_filter', 'reservation_product_id');
  attachSelectFilter('set_item_product_filter', 'set_item_product_id');
  attachSelectFilter('repair_product_filter', 'repair_product_id');
})();
