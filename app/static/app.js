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

  const pageLoadingState = {
    overlayEl: null,
    messageEl: null,
    detailEl: null,
    elapsedEl: null,
    etaEl: null,
    showTimer: null,
    elapsedTimer: null,
    visible: false,
    startedAt: 0,
    actionKey: ''
  };
  const PAGE_LOADING_HISTORY_KEY = 'kdaPageLoadingHistoryV1';
  const PAGE_LOADING_PENDING_KEY = 'kdaPageLoadingPendingV1';

  function pageLoadingElementsReady(){
    if(pageLoadingState.overlayEl){
      return true;
    }
    pageLoadingState.overlayEl = document.getElementById('pageLoadingOverlay');
    pageLoadingState.messageEl = document.getElementById('pageLoadingMessage');
    pageLoadingState.detailEl = document.getElementById('pageLoadingDetail');
    pageLoadingState.elapsedEl = document.getElementById('pageLoadingElapsed');
    pageLoadingState.etaEl = document.getElementById('pageLoadingEta');
    return !!pageLoadingState.overlayEl;
  }

  function pageLoadingStorageRead(key, useSession){
    try{
      const storage = useSession ? window.sessionStorage : window.localStorage;
      const raw = storage.getItem(key);
      if(!raw) return {};
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' ? parsed : {};
    }catch(_e){
      return {};
    }
  }

  function pageLoadingStorageWrite(key, value, useSession){
    try{
      const storage = useSession ? window.sessionStorage : window.localStorage;
      storage.setItem(key, JSON.stringify(value));
    }catch(_e){}
  }

  function pageLoadingStorageRemove(key, useSession){
    try{
      const storage = useSession ? window.sessionStorage : window.localStorage;
      storage.removeItem(key);
    }catch(_e){}
  }

  function pageLoadingClearTimers(){
    if(pageLoadingState.showTimer){
      clearTimeout(pageLoadingState.showTimer);
      pageLoadingState.showTimer = null;
    }
    if(pageLoadingState.elapsedTimer){
      clearInterval(pageLoadingState.elapsedTimer);
      pageLoadingState.elapsedTimer = null;
    }
  }

  function pageLoadingElapsedLabel(seconds){
    const s = Math.max(0, Number(seconds || 0));
    if(s < 60){
      return 'Läuft seit ' + String(s) + ' s';
    }
    const mins = Math.floor(s / 60);
    const rest = s % 60;
    return 'Läuft seit ' + String(mins) + ' min ' + String(rest) + ' s';
  }

  function pageLoadingDurationLabel(seconds){
    const s = Math.max(0, Math.round(Number(seconds || 0)));
    if(s < 60){
      return String(s) + ' s';
    }
    const mins = Math.floor(s / 60);
    const rest = s % 60;
    if(!rest){
      return String(mins) + ' min';
    }
    return String(mins) + ' min ' + String(rest) + ' s';
  }

  function pageLoadingHistoryForKey(actionKey){
    const history = pageLoadingStorageRead(PAGE_LOADING_HISTORY_KEY, false);
    const key = String(actionKey || '').trim();
    const items = Array.isArray(history[key]) ? history[key] : [];
    const clean = items
      .map(function(value){ return Number(value || 0); })
      .filter(function(value){ return Number.isFinite(value) && value > 0; });
    if(!clean.length){
      return { avgMs: 0, count: 0 };
    }
    const total = clean.reduce(function(sum, value){ return sum + value; }, 0);
    return {
      avgMs: Math.round(total / clean.length),
      count: clean.length
    };
  }

  function pageLoadingRememberDuration(actionKey, durationMs){
    const key = String(actionKey || '').trim();
    const duration = Number(durationMs || 0);
    if(!key || !Number.isFinite(duration) || duration <= 0){
      return;
    }
    const history = pageLoadingStorageRead(PAGE_LOADING_HISTORY_KEY, false);
    const items = Array.isArray(history[key]) ? history[key] : [];
    items.push(duration);
    history[key] = items.slice(-8);
    pageLoadingStorageWrite(PAGE_LOADING_HISTORY_KEY, history, false);
  }

  function pageLoadingMarkPending(actionKey){
    const key = String(actionKey || '').trim();
    if(!key){
      return;
    }
    pageLoadingStorageWrite(PAGE_LOADING_PENDING_KEY, {
      key: key,
      startedAt: Date.now()
    }, true);
  }

  function pageLoadingResolvePending(){
    const pending = pageLoadingStorageRead(PAGE_LOADING_PENDING_KEY, true);
    const key = String(pending.key || '').trim();
    const startedAt = Number(pending.startedAt || 0);
    if(key && startedAt > 0){
      const duration = Date.now() - startedAt;
      if(duration > 0 && duration < 30 * 60 * 1000){
        pageLoadingRememberDuration(key, duration);
      }
    }
    pageLoadingStorageRemove(PAGE_LOADING_PENDING_KEY, true);
  }

  function pageLoadingEtaText(elapsedSeconds){
    if(elapsedSeconds < 10){
      return '';
    }
    const history = pageLoadingHistoryForKey(pageLoadingState.actionKey);
    let predictedTotalSeconds = 0;
    let suffix = ' (grobe Schätzung)';
    if(history.avgMs > 0){
      predictedTotalSeconds = Math.max(elapsedSeconds + 1, Math.round(history.avgMs / 1000));
      suffix = ' (Ø aus ' + String(history.count) + ' ähnlichen Vorgängen)';
    }else{
      predictedTotalSeconds = Math.max(20, Math.round(elapsedSeconds * 1.6));
    }
    const remainingSeconds = Math.max(0, predictedTotalSeconds - elapsedSeconds);
    if(remainingSeconds <= 1){
      return 'Sollte in Kürze fertig sein.' + suffix;
    }
    return 'Voraussichtlich noch ca. ' + pageLoadingDurationLabel(remainingSeconds) + suffix;
  }

  function pageLoadingUpdateElapsed(){
    if(!pageLoadingElementsReady() || !pageLoadingState.elapsedEl){
      return;
    }
    const elapsedSeconds = Math.floor((Date.now() - pageLoadingState.startedAt) / 1000);
    pageLoadingState.elapsedEl.textContent = pageLoadingElapsedLabel(elapsedSeconds);
    if(pageLoadingState.etaEl){
      const etaText = pageLoadingEtaText(elapsedSeconds);
      pageLoadingState.etaEl.textContent = etaText;
      pageLoadingState.etaEl.hidden = !etaText;
    }
  }

  function showPageLoading(message, detail, actionKey){
    if(!pageLoadingElementsReady()){
      return;
    }
    pageLoadingClearTimers();
    pageLoadingState.visible = true;
    pageLoadingState.startedAt = Date.now();
    pageLoadingState.actionKey = String(actionKey || '').trim();
    if(pageLoadingState.messageEl){
      pageLoadingState.messageEl.textContent = String(message || 'Seite wird geladen...');
    }
    if(pageLoadingState.detailEl){
      pageLoadingState.detailEl.textContent = String(detail || 'Bitte warten.');
    }
    if(pageLoadingState.etaEl){
      pageLoadingState.etaEl.textContent = '';
      pageLoadingState.etaEl.hidden = true;
    }
    if(pageLoadingState.overlayEl){
      pageLoadingState.overlayEl.hidden = false;
      pageLoadingState.overlayEl.setAttribute('aria-hidden', 'false');
    }
    if(document.body){
      document.body.classList.add('page-loading-open');
    }
    pageLoadingUpdateElapsed();
    pageLoadingState.elapsedTimer = window.setInterval(pageLoadingUpdateElapsed, 1000);
  }

  function hidePageLoading(){
    pageLoadingClearTimers();
    pageLoadingState.visible = false;
    pageLoadingState.actionKey = '';
    if(pageLoadingState.overlayEl){
      pageLoadingState.overlayEl.hidden = true;
      pageLoadingState.overlayEl.setAttribute('aria-hidden', 'true');
    }
    if(document.body){
      document.body.classList.remove('page-loading-open');
    }
  }

  function schedulePageLoading(message, detail, delayMs, actionKey){
    if(!pageLoadingElementsReady()){
      return;
    }
    pageLoadingClearTimers();
    const ms = Math.max(0, Number(delayMs || 0));
    if(ms === 0){
      showPageLoading(message, detail, actionKey);
      return;
    }
    pageLoadingState.showTimer = window.setTimeout(function(){
      showPageLoading(message, detail, actionKey);
    }, ms);
  }

  function navigateTo(href, message, detail, actionKey){
    const targetHref = String(href || '').trim();
    if(!targetHref){
      return;
    }
    pageLoadingMarkPending(actionKey);
    schedulePageLoading(
      message || 'Seite wird geladen...',
      detail || 'Bitte warten.',
      120,
      actionKey
    );
    window.location.href = targetHref;
  }

  function initPageLoadingStatus(){
    if(!pageLoadingElementsReady()){
      return;
    }

    const formLoadingConfig = function(form){
      const method = String(form.getAttribute('method') || 'get').trim().toLowerCase();
      const actionAttr = String(form.getAttribute('action') || window.location.pathname).trim();
      let actionPath = actionAttr;
      try{
        actionPath = new URL(actionAttr, window.location.href).pathname;
      }catch(_e){}

      let message = String(form.getAttribute('data-loading-message') || '').trim();
      let detail = String(form.getAttribute('data-loading-detail') || '').trim();
      let delay = (method === 'get') ? 450 : 220;
      const actionKey = method.toUpperCase() + ':' + actionPath;

      if(actionPath === '/catalog/import'){
        if(!message) message = 'Import-Kontext wird geladen...';
        if(!detail) detail = 'Auswahl wird übernommen.';
        delay = 120;
      }else if(actionPath === '/catalog/import/upload'){
        if(!message) message = 'CSV-Datei wird geprüft...';
        if(!detail) detail = 'Datei wird hochgeladen und Vorschau vorbereitet.';
        delay = 0;
      }else if(/^\/catalog\/import\/\d+\/map$/.test(actionPath)){
        if(!message) message = 'Mapping wird gespeichert...';
        if(!detail) detail = 'Zuordnungen werden validiert.';
        delay = 0;
      }else if(/^\/catalog\/import\/\d+\/run$/.test(actionPath)){
        if(!message) message = 'CSV-Import wird gestartet...';
        if(!detail) detail = 'Der Lauf wechselt in den Hintergrund. Du kannst danach normal weiterarbeiten.';
        delay = 0;
      }else{
        if(!message){
          message = (method === 'get') ? 'Seite wird geladen...' : 'Vorgang wird ausgeführt...';
        }
        if(!detail){
          detail = (method === 'get') ? 'Bitte warten.' : 'Bitte warten, Daten werden verarbeitet.';
        }
      }

      if(String(form.getAttribute('data-loading-immediate') || '') === '1'){
        delay = 0;
      }else{
        const hasFile = Array.from(form.querySelectorAll('input[type="file"]')).some(function(inp){
          return !!(inp.files && inp.files.length);
        });
        if(hasFile){
          delay = 0;
        }
      }
      return { message, detail, delay, actionKey };
    };

    pageLoadingResolvePending();

    window.addEventListener('pageshow', function(){
      hidePageLoading();
      pageLoadingResolvePending();
    });

    document.addEventListener('submit', function(e){
      if(e.defaultPrevented) return;
      const form = e.target;
      if(!(form instanceof HTMLFormElement)) return;
      if(String(form.getAttribute('data-loading') || '').trim().toLowerCase() === 'off') return;
      const target = String(form.getAttribute('target') || '').trim().toLowerCase();
      if(target === '_blank') return;
      const cfg = formLoadingConfig(form);
      pageLoadingMarkPending(cfg.actionKey);
      schedulePageLoading(cfg.message, cfg.detail, cfg.delay, cfg.actionKey);
    });

    document.addEventListener('click', function(e){
      if(e.defaultPrevented) return;
      if(e.button !== 0 || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
      const target = e.target;
      if(!(target instanceof Element)) return;
      const link = target.closest('a[href]');
      if(!link) return;
      if(String(link.getAttribute('data-loading') || '').trim().toLowerCase() === 'off') return;
      const targetAttr = String(link.getAttribute('target') || '').trim().toLowerCase();
      if(targetAttr === '_blank' || link.hasAttribute('download')) return;
      const href = String(link.getAttribute('href') || '').trim();
      if(!href || href.startsWith('#') || href.toLowerCase().startsWith('javascript:')) return;
      let url;
      try{
        url = new URL(href, window.location.href);
      }catch(_e){
        return;
      }
      if(url.origin !== window.location.origin) return;
      if(url.pathname === window.location.pathname && url.search === window.location.search && url.hash){
        return;
      }
      const message = String(link.getAttribute('data-loading-message') || '').trim() || 'Seite wird geladen...';
      const detail = String(link.getAttribute('data-loading-detail') || '').trim() || 'Bitte warten.';
      const actionKey = 'GET:' + String(url.pathname || '');
      pageLoadingMarkPending(actionKey);
      schedulePageLoading(message, detail, 350, actionKey);
    });
  }

  const JOB_MONITOR_COLLAPSED_KEY = 'kdaJobMonitorCollapsedV1';
  const jobMonitorState = {
    rootEl: null,
    primaryEl: null,
    summaryEl: null,
    etaEl: null,
    headBarEl: null,
    bodyEl: null,
    toggleEl: null,
    timer: null,
    collapsed: false
  };

  function escapeHtml(value){
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function jobMonitorStatusLabel(status){
    const key = String(status || '').trim().toLowerCase();
    if(key === 'queued') return 'Wartet';
    if(key === 'running') return 'Läuft';
    if(key === 'done') return 'Erfolgreich';
    if(key === 'failed') return 'Fehlgeschlagen';
    return String(status || '');
  }

  function jobMonitorProgressText(job){
    const progress = (job && job.progress && typeof job.progress === 'object') ? job.progress : {};
    const processed = Number(progress.processed_count || 0);
    const total = Number(progress.total_count || 0);
    if(total > 0){
      return String(processed) + ' / ' + String(total);
    }
    if(processed > 0){
      return String(processed) + ' bearbeitet';
    }
    return 'läuft';
  }

  function jobMonitorPercent(job){
    const progress = (job && job.progress && typeof job.progress === 'object') ? job.progress : {};
    const processed = Number(progress.processed_count || 0);
    const total = Number(progress.total_count || 0);
    if(total > 0){
      return Math.max(0, Math.min(100, Math.round((processed / total) * 100)));
    }
    return 0;
  }

  function jobMonitorItemHtml(job){
    const progress = (job && job.progress && typeof job.progress === 'object') ? job.progress : {};
    const eta = Number(job && job.eta_seconds || 0);
    const percent = jobMonitorPercent(job);
    const determinate = Number(progress.total_count || 0) > 0;
    const localCount = Number(progress.local_decision_count || 0);
    const openaiCount = Number(progress.openai_decision_count || 0);
    const cachedCount = Number(progress.cached_decision_count || 0);
    const links = [];
    if(job && job.result_url){
      links.push('<a href="' + escapeHtml(job.result_url) + '">Ergebnis</a>');
    }
    links.push('<a href="/system/sync-log">Protokoll</a>');
    return [
      '<article class="job-monitor-item">',
      '<div class="job-monitor-item-head">',
      '<div><b>' + escapeHtml(job.title || job.entity_type || 'Job') + '</b></div>',
      '<div class="muted">' + escapeHtml(jobMonitorStatusLabel(job.status)) + '</div>',
      '</div>',
      '<div class="job-monitor-phase">' + escapeHtml(progress.phase || 'Bitte warten') + '</div>',
      '<div class="job-monitor-bar"><div class="job-monitor-bar-fill' + (determinate ? '' : ' indeterminate') + '" style="' + (determinate ? ('width:' + String(percent) + '%;') : 'width:35%;') + '"></div></div>',
      progress.phase_detail ? '<div class="muted">' + escapeHtml(progress.phase_detail) + '</div>' : '',
      progress.current_item_label ? '<div class="muted">Datensatz: ' + escapeHtml(progress.current_item_label) + (progress.current_item_ref ? ' | ' + escapeHtml(progress.current_item_ref) : '') + '</div>' : '',
      '<div class="job-monitor-metrics">',
      '<span>Fortschritt: ' + escapeHtml(jobMonitorProgressText(job)) + (determinate ? ' (' + String(percent) + '%)' : '') + '</span>',
      Number(progress.error_count || 0) > 0 ? '<span>Fehler: ' + escapeHtml(progress.error_count) + '</span>' : '',
      localCount > 0 ? '<span>Lokal: ' + escapeHtml(localCount) + '</span>' : '',
      openaiCount > 0 ? '<span>OpenAI: ' + escapeHtml(openaiCount) + '</span>' : '',
      cachedCount > 0 ? '<span>Cache: ' + escapeHtml(cachedCount) + '</span>' : '',
      eta > 0 ? '<span>ETA: ' + escapeHtml(pageLoadingDurationLabel(eta)) + '</span>' : '',
      '</div>',
      progress.note ? '<div class="muted">' + escapeHtml(progress.note) + '</div>' : '',
      '<div class="job-monitor-links">' + links.join(' | ') + '</div>',
      '</article>'
    ].join('');
  }

  function jobMonitorHeadUpdate(job, runningCount, queuedCount){
    if(!jobMonitorState.primaryEl || !jobMonitorState.summaryEl || !jobMonitorState.etaEl || !jobMonitorState.headBarEl){
      return;
    }
    const progress = (job && job.progress && typeof job.progress === 'object') ? job.progress : {};
    const percent = jobMonitorPercent(job);
    const determinate = Number(progress.total_count || 0) > 0;
    const eta = Number(job && job.eta_seconds || 0);
    const parts = [];
    if(runningCount) parts.push(String(runningCount) + ' läuft');
    if(queuedCount) parts.push(String(queuedCount) + ' wartet');
    if(progress.phase){
      parts.push(String(progress.phase));
    }
    jobMonitorState.primaryEl.textContent = String(job && job.title || 'Hintergrundjob');
    jobMonitorState.summaryEl.textContent = parts.join(' | ') || 'aktiv';
    if(eta > 0){
      jobMonitorState.etaEl.textContent = 'ETA: ' + pageLoadingDurationLabel(eta);
      jobMonitorState.etaEl.hidden = false;
    }else{
      jobMonitorState.etaEl.textContent = '';
      jobMonitorState.etaEl.hidden = true;
    }
    jobMonitorState.headBarEl.classList.toggle('indeterminate', !determinate);
    jobMonitorState.headBarEl.style.width = determinate ? (String(percent) + '%') : '35%';
  }

  function jobMonitorApplyCollapsed(){
    if(!jobMonitorState.rootEl || !jobMonitorState.bodyEl || !jobMonitorState.toggleEl){
      return;
    }
    jobMonitorState.rootEl.classList.toggle('job-monitor-collapsed', !!jobMonitorState.collapsed);
    jobMonitorState.bodyEl.hidden = !!jobMonitorState.collapsed;
    jobMonitorState.toggleEl.textContent = jobMonitorState.collapsed ? 'Details' : 'Details aus';
    jobMonitorState.toggleEl.setAttribute('aria-expanded', jobMonitorState.collapsed ? 'false' : 'true');
    try{
      window.localStorage.setItem(JOB_MONITOR_COLLAPSED_KEY, jobMonitorState.collapsed ? '1' : '0');
    }catch(_e){}
  }

  function jobMonitorRender(items){
    if(!jobMonitorState.rootEl || !jobMonitorState.primaryEl || !jobMonitorState.summaryEl || !jobMonitorState.bodyEl || !jobMonitorState.etaEl || !jobMonitorState.headBarEl){
      return;
    }
    if(!Array.isArray(items) || !items.length){
      jobMonitorState.rootEl.hidden = true;
      jobMonitorState.primaryEl.textContent = 'Kein aktiver Job';
      jobMonitorState.bodyEl.innerHTML = '';
      jobMonitorState.summaryEl.textContent = 'Keine aktiven Jobs';
      jobMonitorState.etaEl.textContent = '';
      jobMonitorState.etaEl.hidden = true;
      return;
    }
    const running = items.filter(function(item){ return String(item.status || '').toLowerCase() === 'running'; }).length;
    const queued = items.filter(function(item){ return String(item.status || '').toLowerCase() === 'queued'; }).length;
    const first = items[0] || null;
    jobMonitorHeadUpdate(first, running, queued);
    jobMonitorState.bodyEl.innerHTML = items.map(jobMonitorItemHtml).join('');
    jobMonitorState.rootEl.hidden = false;
    jobMonitorApplyCollapsed();
  }

  async function jobMonitorPoll(){
    if(!isAuthenticated() || !jobMonitorState.rootEl){
      return;
    }
    try{
      const res = await fetch('/api/jobs/active', { headers: { 'Accept': 'application/json' }, credentials: 'same-origin' });
      if(!res.ok){
        return;
      }
      const payload = await res.json();
      jobMonitorRender(Array.isArray(payload.items) ? payload.items : []);
    }catch(_e){}
  }

  function initJobMonitor(){
    if(!isAuthenticated()){
      return;
    }
    jobMonitorState.rootEl = document.getElementById('jobMonitor');
    jobMonitorState.primaryEl = document.getElementById('jobMonitorPrimary');
    jobMonitorState.summaryEl = document.getElementById('jobMonitorSummary');
    jobMonitorState.etaEl = document.getElementById('jobMonitorEta');
    jobMonitorState.headBarEl = document.getElementById('jobMonitorHeadBar');
    jobMonitorState.bodyEl = document.getElementById('jobMonitorBody');
    jobMonitorState.toggleEl = document.getElementById('jobMonitorToggle');
    if(!jobMonitorState.rootEl || !jobMonitorState.primaryEl || !jobMonitorState.summaryEl || !jobMonitorState.etaEl || !jobMonitorState.headBarEl || !jobMonitorState.bodyEl || !jobMonitorState.toggleEl){
      return;
    }
    try{
      const saved = window.localStorage.getItem(JOB_MONITOR_COLLAPSED_KEY);
      jobMonitorState.collapsed = saved === null ? true : saved === '1';
    }catch(_e){
      jobMonitorState.collapsed = true;
    }
    jobMonitorState.toggleEl.addEventListener('click', function(){
      jobMonitorState.collapsed = !jobMonitorState.collapsed;
      jobMonitorApplyCollapsed();
    });
    jobMonitorApplyCollapsed();
    jobMonitorPoll();
    if(jobMonitorState.timer){
      window.clearInterval(jobMonitorState.timer);
    }
    jobMonitorState.timer = window.setInterval(jobMonitorPoll, 1500);
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
            navigateTo(href);
            return;
          }
          if(e.key === 'i' || e.key === 'I'){
            const href = rowBookHref(row);
            if(!href) return;
            e.preventDefault();
            navigateTo(href);
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
    navigateTo(href);
    return true;
  }

  function openKbdBookSelection(){
    if(!kbdRows.length || kbdIndex < 0) return false;
    const row = kbdRows[kbdIndex];
    const href = rowBookHref(row);
    if(!href) return false;
    navigateTo(href);
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

  function initFilterSelectInputs(){
    const inputs = Array.from(document.querySelectorAll('[data-filter-select]'));
    inputs.forEach(function(input){
      const inputId = String(input.id || '').trim();
      const selectId = String(input.getAttribute('data-filter-select') || '').trim();
      if(!inputId || !selectId) return;
      attachSelectFilter(inputId, selectId);
    });
  }

  function initCustomerListLiveSearch(){
    const input = document.getElementById('crm_customer_q');
    const rows = Array.from(document.querySelectorAll('[data-customer-row]'));
    if(!input || !rows.length) return;
    const empty = document.querySelector('[data-customer-empty]');

    const apply = function(){
      const q = normalizeText(input.value || '').trim();
      let visibleCount = 0;
      let lastVisibleLink = '';
      rows.forEach(function(row){
        const haystack = normalizeText(row.getAttribute('data-customer-search') || '');
        const visible = !q || haystack.indexOf(q) !== -1;
        row.hidden = !visible;
        if(visible){
          visibleCount += 1;
          const link = row.querySelector('a[href]');
          if(link){
            lastVisibleLink = String(link.getAttribute('href') || '').trim();
          }
        }
      });
      if(empty){
        empty.hidden = visibleCount > 0;
      }
      return { visibleCount, lastVisibleLink };
    };

    input.addEventListener('input', apply);
    input.addEventListener('keydown', function(e){
      if(e.key !== 'Enter'){
        return;
      }
      const state = apply();
      if(state.visibleCount === 1 && state.lastVisibleLink){
        e.preventDefault();
        navigateTo(state.lastVisibleLink);
      }
    });
    apply();
  }

  function formatTraitRangeValue(raw){
    const n = Number(raw);
    if(!Number.isFinite(n)){
      return String(raw || '');
    }
    const rounded = Math.round(n * 1000) / 1000;
    return String(rounded).replace('.', ',');
  }

  function initTraitRangeSliders(){
    const sliders = Array.from(document.querySelectorAll('[data-trait-range-slider="1"]'));
    if(!sliders.length) return;

    const groups = {};
    sliders.forEach(function(slider){
      const groupKey = String(slider.getAttribute('data-trait-range-group') || '').trim();
      const role = String(slider.getAttribute('data-trait-range-role') || '').trim();
      const targetId = String(slider.getAttribute('data-trait-range-target') || '').trim();
      if(!groupKey || !role || !targetId) return;
      const targetInput = document.getElementById(targetId);
      if(!targetInput) return;
      const valueId = String(slider.getAttribute('data-trait-range-value') || '').trim();
      const valueEl = valueId ? document.getElementById(valueId) : null;
      const group = groups[groupKey] || {
        minSlider: null,
        maxSlider: null,
        minTarget: null,
        maxTarget: null,
        minValueEl: null,
        maxValueEl: null,
        fillEl: null
      };
      if(role === 'min'){
        group.minSlider = slider;
        group.minTarget = targetInput;
        group.minValueEl = valueEl;
      }else if(role === 'max'){
        group.maxSlider = slider;
        group.maxTarget = targetInput;
        group.maxValueEl = valueEl;
      }
      if(!group.fillEl){
        group.fillEl = document.querySelector('[data-trait-range-fill="' + groupKey + '"]');
      }
      groups[groupKey] = group;
    });

    const syncRangeFill = function(group){
      if(!group.fillEl || !group.minSlider || !group.maxSlider) return;
      const sliderMin = parseFloat(String(group.minSlider.min || ''));
      const sliderMax = parseFloat(String(group.minSlider.max || ''));
      const minValue = parseFloat(String(group.minSlider.value || ''));
      const maxValue = parseFloat(String(group.maxSlider.value || ''));
      if(!Number.isFinite(sliderMin) || !Number.isFinite(sliderMax) || sliderMax <= sliderMin){
        group.fillEl.style.left = '0%';
        group.fillEl.style.width = '0%';
        return;
      }
      const left = ((minValue - sliderMin) / (sliderMax - sliderMin)) * 100;
      const right = ((maxValue - sliderMin) / (sliderMax - sliderMin)) * 100;
      group.fillEl.style.left = Math.max(0, Math.min(100, left)) + '%';
      group.fillEl.style.width = Math.max(0, Math.min(100, right) - Math.max(0, Math.min(100, left))) + '%';
    };

    const normalizePair = function(group, sourceRole){
      if(!group.minSlider || !group.maxSlider) return;
      let minValue = parseFloat(String(group.minSlider.value || ''));
      let maxValue = parseFloat(String(group.maxSlider.value || ''));
      if(!Number.isFinite(minValue) || !Number.isFinite(maxValue)) return;
      if(minValue > maxValue){
        if(sourceRole === 'min'){
          maxValue = minValue;
          group.maxSlider.value = String(maxValue);
        }else{
          minValue = maxValue;
          group.minSlider.value = String(minValue);
        }
      }
      if(group.minValueEl){
        group.minValueEl.textContent = formatTraitRangeValue(group.minSlider.value);
      }
      if(group.maxValueEl){
        group.maxValueEl.textContent = formatTraitRangeValue(group.maxSlider.value);
      }
      syncRangeFill(group);
    };

    const commitToInputs = function(group){
      if(group.minSlider && group.minTarget){
        group.minTarget.value = String(group.minSlider.value || '');
      }
      if(group.maxSlider && group.maxTarget){
        group.maxTarget.value = String(group.maxSlider.value || '');
      }
    };

    Object.keys(groups).forEach(function(key){
      const group = groups[key];
      if(!group.minSlider || !group.maxSlider) return;

      const setActiveSlider = function(role){
        if(!group.minSlider || !group.maxSlider) return;
        group.minSlider.style.zIndex = (role === 'min') ? '6' : '4';
        group.maxSlider.style.zIndex = (role === 'max') ? '6' : '5';
      };

      if(group.minTarget && String(group.minTarget.value || '').trim() !== ''){
        group.minSlider.value = String(group.minTarget.value || group.minSlider.value);
      }
      if(group.maxTarget && String(group.maxTarget.value || '').trim() !== ''){
        group.maxSlider.value = String(group.maxTarget.value || group.maxSlider.value);
      }
      normalizePair(group, '');
      setActiveSlider('');

      group.minSlider.addEventListener('input', function(){
        setActiveSlider('min');
        normalizePair(group, 'min');
        commitToInputs(group);
      });
      group.maxSlider.addEventListener('input', function(){
        setActiveSlider('max');
        normalizePair(group, 'max');
        commitToInputs(group);
      });
      group.minSlider.addEventListener('pointerdown', function(){
        setActiveSlider('min');
      });
      group.maxSlider.addEventListener('pointerdown', function(){
        setActiveSlider('max');
      });
    });
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
      navigateTo(query ? (url.pathname + '?' + query) : url.pathname);
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
    const form = document.querySelector('form[data-catalog-v2-filter="1"]');
    if(!form) return;
    const filterRegionSelector = '[data-catalog-filter-region="1"]';
    const resultsRegionSelector = '[data-catalog-results-region="1"]';
    const liveStatusSelector = '[data-catalog-live-status="1"]';
    let debounceTimer = null;
    let requestSeq = 0;
    let activeController = null;

    const setBusy = function(isBusy, message){
      const resultsRegion = document.querySelector(resultsRegionSelector);
      const liveStatus = document.querySelector(liveStatusSelector);
      if(resultsRegion){
        resultsRegion.setAttribute('data-loading', isBusy ? '1' : '0');
      }
      if(liveStatus){
        liveStatus.textContent = isBusy ? (message || 'Filtert ...') : (message || '');
      }
    };

    const buildUrl = function(){
      const action = form.getAttribute('action') || window.location.pathname;
      const url = new URL(action, window.location.origin);
      const formData = new FormData(form);
      formData.forEach(function(value, key){
        const cleanKey = String(key || '').trim();
        if(!cleanKey || value instanceof File) return;
        const cleanValue = String(value || '').trim();
        if(cleanValue === '') return;
        url.searchParams.append(cleanKey, cleanValue);
      });
      return url;
    };

    const applyResponse = function(html, url){
      const parser = new DOMParser();
      const doc = parser.parseFromString(html, 'text/html');
      const currentFilterRegion = form.querySelector(filterRegionSelector);
      const nextFilterRegion = doc.querySelector(filterRegionSelector);
      const currentPanel = form.querySelector('[data-catalog-filter-panel="1"]');
      const currentCollapsed = currentPanel ? currentPanel.getAttribute('data-collapsed') : '0';
      if(currentFilterRegion && nextFilterRegion){
        currentFilterRegion.replaceWith(nextFilterRegion);
      }
      const currentResultsRegion = document.querySelector(resultsRegionSelector);
      const nextResultsRegion = doc.querySelector(resultsRegionSelector);
      if(currentResultsRegion && nextResultsRegion){
        currentResultsRegion.replaceWith(nextResultsRegion);
      }
      const toggleBtn = form.querySelector('[data-catalog-filter-toggle="1"]');
      const nextPanel = form.querySelector('[data-catalog-filter-panel="1"]');
      if(toggleBtn && nextPanel){
        const collapsed = currentCollapsed === '1';
        nextPanel.setAttribute('data-collapsed', collapsed ? '1' : '0');
        toggleBtn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        toggleBtn.textContent = collapsed ? 'Filter' : 'Filter ausblenden';
      }
      const finalUrl = url.pathname + (url.search || '');
      window.history.replaceState({}, '', finalUrl);
    };

    const fetchLive = function(){
      const url = buildUrl();
      requestSeq += 1;
      const currentSeq = requestSeq;
      if(activeController && typeof activeController.abort === 'function'){
        activeController.abort();
      }
      activeController = typeof AbortController === 'function' ? new AbortController() : null;
      setBusy(true, 'Filtert ...');
      fetch(url.toString(), {
        method: 'GET',
        credentials: 'same-origin',
        headers: {'X-Requested-With': 'fetch'},
        signal: activeController ? activeController.signal : undefined,
      })
        .then(function(response){
          if(!response.ok){
            throw new Error('HTTP ' + response.status);
          }
          return response.text();
        })
        .then(function(html){
          if(currentSeq !== requestSeq) return;
          applyResponse(html, url);
          setBusy(false, '');
        })
        .catch(function(error){
          if(error && error.name === 'AbortError'){
            return;
          }
          window.location.assign(url.toString());
        });
    };

    const scheduleFetch = function(delay){
      if(debounceTimer){
        window.clearTimeout(debounceTimer);
      }
      debounceTimer = window.setTimeout(fetchLive, Math.max(0, delay || 0));
    };

    form.addEventListener('submit', function(e){
      e.preventDefault();
      fetchLive();
    });

    form.addEventListener('change', function(e){
      const target = e.target;
      if(!(target instanceof HTMLElement)) return;
      if(!target.closest('input,select,textarea')) return;
      scheduleFetch(target.id === 'catalog_kind_id' ? 60 : 100);
    });

    form.addEventListener('input', function(e){
      const target = e.target;
      if(!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)) return;
      const fieldName = String(target.name || '').trim();
      if(!fieldName) return;
      if(fieldName === 'q'){
        scheduleFetch(220);
        return;
      }
      if(fieldName.indexOf('f_') === 0){
        scheduleFetch(140);
      }
    });

    form.addEventListener('keydown', function(e){
      if(e.key !== 'Escape') return;
      const target = e.target;
      if(!(target instanceof HTMLElement)) return;
      if(!target.closest('input,select,textarea')) return;
      const fields = Array.from(form.querySelectorAll('input[name^=\"f_\"], select[name^=\"f_\"]'));
      if(!fields.length) return;
      fields.forEach(function(el){
        if(!(el instanceof HTMLInputElement) && !(el instanceof HTMLSelectElement)) return;
        if(el instanceof HTMLInputElement){
          el.value = '';
        }else{
          el.value = '';
        }
      });
      e.preventDefault();
      fetchLive();
    });
  }

  function initCatalogMobileFilterPanel(){
    const form = document.querySelector('form[data-catalog-v2-filter="1"]');
    if(!form) return;
    const toggleBtn = form.querySelector('[data-catalog-filter-toggle="1"]');
    if(!toggleBtn) return;

    const mq = window.matchMedia('(max-width: 900px)');
    let userTouched = false;

    const getPanel = function(){
      return form.querySelector('[data-catalog-filter-panel="1"]');
    };

    const setCollapsed = function(nextCollapsed){
      const panel = getPanel();
      if(!panel) return;
      const collapsed = !!nextCollapsed;
      panel.setAttribute('data-collapsed', collapsed ? '1' : '0');
      toggleBtn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
      toggleBtn.textContent = collapsed ? 'Filter' : 'Filter ausblenden';
    };

    const syncMode = function(){
      const panel = getPanel();
      if(!panel) return;
      if(mq.matches){
        if(!userTouched){
          setCollapsed(true);
        }
      }else{
        setCollapsed(false);
        userTouched = false;
      }
    };

    toggleBtn.addEventListener('click', function(){
      userTouched = true;
      const panel = getPanel();
      const isCollapsed = !panel || panel.getAttribute('data-collapsed') === '1';
      setCollapsed(!isCollapsed);
    });

    if(typeof mq.addEventListener === 'function'){
      mq.addEventListener('change', syncMode);
    }else if(typeof mq.addListener === 'function'){
      mq.addListener(syncMode);
    }
    syncMode();
  }

  function mobileActionPath(action){
    const key = String(action || '').trim().toLowerCase();
    if(key === 'ausbuchen') return '/m/ausbuchen';
    if(key === 'umlagerung') return '/m/umlagerung';
    if(key === 'bestellen') return '/m/bestellen';
    return '/m/einbuchen';
  }

  function initMobileHomeQuickSearch(){
    const page = document.querySelector('[data-mobile-home="1"]');
    if(!page) return;
    const searchInput = document.getElementById('mSearch');
    const kindSelect = document.getElementById('mKindId');
    const resultsWrap = document.getElementById('mResults');
    if(!searchInput || !resultsWrap) return;

    const actionButtons = Array.from(page.querySelectorAll('[data-mobile-action]'));
    let currentAction = String(page.getAttribute('data-mobile-action') || 'einbuchen').trim().toLowerCase();
    if(!currentAction){
      currentAction = 'einbuchen';
    }
    let debounceTimer = null;
    let requestSeq = 0;
    let lastItems = [];

    const renderMessage = function(text){
      resultsWrap.innerHTML = '';
      const hint = document.createElement('div');
      hint.className = 'muted';
      hint.textContent = text;
      resultsWrap.appendChild(hint);
    };

    const openProductForAction = function(productId){
      const id = parseInt(String(productId || '0'), 10) || 0;
      if(id <= 0) return;
      const href = mobileActionPath(currentAction) + '?product_id=' + encodeURIComponent(String(id));
      navigateTo(href);
    };

    const setAction = function(nextAction){
      currentAction = String(nextAction || 'einbuchen').trim().toLowerCase() || 'einbuchen';
      actionButtons.forEach(function(btn){
        const btnAction = String(btn.getAttribute('data-mobile-action') || '').trim().toLowerCase();
        btn.classList.toggle('active', btnAction === currentAction);
      });
    };

    const renderItems = function(items){
      resultsWrap.innerHTML = '';
      if(!items.length){
        renderMessage('Keine Treffer gefunden.');
        return;
      }
      items.forEach(function(item){
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'mobile-result-btn';
        btn.addEventListener('click', function(){
          openProductForAction(item.id);
        });

        const title = document.createElement('div');
        title.className = 'mobile-result-title';
        title.textContent = String(item.display_name || 'Unbenanntes Produkt');
        btn.appendChild(title);

        const parts = [];
        const manufacturerName = String(item.manufacturer_name || '').trim();
        const kindName = String(item.kind_name || '').trim();
        const ean = String(item.ean || '').trim();
        if(manufacturerName) parts.push(manufacturerName);
        if(kindName) parts.push(kindName);
        if(ean) parts.push('EAN ' + ean);
        if(typeof item.stock_total === 'number'){
          parts.push('Bestand ' + String(item.stock_total));
        }

        const meta = document.createElement('div');
        meta.className = 'mobile-result-meta';
        meta.textContent = parts.join(' | ');
        btn.appendChild(meta);
        resultsWrap.appendChild(btn);
      });
    };

    const runSearch = function(){
      const q = String(searchInput.value || '').trim();
      if(q.length < 2){
        lastItems = [];
        renderMessage('Tippe mindestens 2 Zeichen, um Treffer zu sehen.');
        return;
      }
      const seq = ++requestSeq;
      const params = new URLSearchParams();
      params.set('q', q);
      if(kindSelect){
        const kindId = String(kindSelect.value || '').trim();
        if(kindId && kindId !== '0'){
          params.set('kind_id', kindId);
        }
      }
      fetch('/api/products/quicksearch?' + params.toString(), {
        headers: { 'Accept': 'application/json' }
      }).then(function(resp){
        if(!resp.ok){
          throw new Error('HTTP ' + String(resp.status));
        }
        return resp.json();
      }).then(function(data){
        if(seq !== requestSeq){
          return;
        }
        const items = Array.isArray(data.items) ? data.items : [];
        lastItems = items;
        renderItems(items);
      }).catch(function(){
        if(seq !== requestSeq){
          return;
        }
        lastItems = [];
        renderMessage('Suche ist gerade nicht verfügbar.');
      });
    };

    const queueSearch = function(){
      if(debounceTimer){
        clearTimeout(debounceTimer);
      }
      debounceTimer = setTimeout(runSearch, 200);
    };

    searchInput.addEventListener('input', function(){
      queueSearch();
    });
    searchInput.addEventListener('keydown', function(e){
      if(e.key === 'Enter'){
        e.preventDefault();
        if(lastItems.length === 1){
          openProductForAction(lastItems[0].id);
          return;
        }
        runSearch();
      }
    });
    if(kindSelect){
      kindSelect.addEventListener('change', function(){
        queueSearch();
      });
    }

    actionButtons.forEach(function(btn){
      btn.addEventListener('click', function(){
        const nextAction = String(btn.getAttribute('data-mobile-action') || '').trim().toLowerCase();
        if(!nextAction) return;
        setAction(nextAction);
        if(lastItems.length === 1){
          openProductForAction(lastItems[0].id);
        }
      });
    });

    setAction(currentAction);
  }

  function initMobileCatalog(){
    const page = document.querySelector('[data-mobile-catalog="1"]');
    if(!page) return;
    const searchInput = document.getElementById('mCatalogSearch');
    const kindSelect = document.getElementById('mCatalogKind');
    const featureToggle = document.getElementById('mCatalogFeatureToggle');
    const featureWrap = document.getElementById('mCatalogFeatureWrap');
    const featureFields = document.getElementById('mCatalogFeatureFields');
    const resultsWrap = document.getElementById('mCatalogResults');
    if(!searchInput || !kindSelect || !featureToggle || !featureWrap || !featureFields || !resultsWrap) return;

    const nextPath = String(page.getAttribute('data-next') || '').trim();
    let debounceTimer = null;
    let requestSeq = 0;
    let featureOpen = false;

    const setFeatureOpen = function(nextOpen){
      featureOpen = !!nextOpen;
      featureWrap.hidden = !featureOpen;
      featureWrap.setAttribute('data-open', featureOpen ? '1' : '0');
      featureToggle.setAttribute('aria-expanded', featureOpen ? 'true' : 'false');
      featureToggle.textContent = featureOpen ? 'Merkmale ausblenden' : 'Merkmale';
    };

    const syncFeatureToggle = function(){
      const hasRows = !!featureFields.querySelector('[data-feature-id]');
      const hasKind = String(kindSelect.value || '').trim() !== '' && String(kindSelect.value || '0') !== '0';
      const visible = hasRows && hasKind;
      featureToggle.hidden = !visible;
      if(!visible){
        setFeatureOpen(false);
      }
    };

    const renderState = function(text){
      resultsWrap.innerHTML = '';
      const state = document.createElement('div');
      state.className = 'm-catalog-state';
      state.textContent = text;
      resultsWrap.appendChild(state);
    };

    const cardTargetUrl = function(productId){
      const id = parseInt(String(productId || '0'), 10) || 0;
      if(id <= 0){
        return '';
      }
      if(nextPath){
        const joiner = nextPath.indexOf('?') >= 0 ? '&' : '?';
        return nextPath + joiner + 'product_id=' + encodeURIComponent(String(id));
      }
      return '/catalog/products/' + encodeURIComponent(String(id));
    };

    const renderItems = function(items){
      resultsWrap.innerHTML = '';
      if(!items.length){
        renderState('Keine Treffer.');
        return;
      }
      items.forEach(function(item){
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'mobile-catalog-card';
        btn.addEventListener('click', function(){
          const href = cardTargetUrl(item.id);
          if(href){
            navigateTo(href);
          }
        });

        const media = document.createElement('div');
        media.className = 'mobile-catalog-card-media';
        const imageUrl = String(item.image_url || '').trim();
        if(imageUrl){
          const img = document.createElement('img');
          img.setAttribute('src', imageUrl);
          img.setAttribute('alt', 'Produktbild');
          img.setAttribute('loading', 'lazy');
          media.appendChild(img);
        }else{
          const empty = document.createElement('div');
          empty.className = 'mobile-catalog-card-media-empty';
          empty.textContent = 'Kein Bild';
          media.appendChild(empty);
        }
        btn.appendChild(media);

        const title = document.createElement('div');
        title.className = 'mobile-catalog-card-title';
        title.textContent = String(item.title || 'Unbenanntes Produkt');
        btn.appendChild(title);
        resultsWrap.appendChild(btn);
      });
    };

    const createFilterSelect = function(row, name, labelText, options, selectedValue){
      const wrap = document.createElement('div');
      wrap.className = 'mobile-catalog-feature-row';
      wrap.setAttribute('data-feature-id', String(row.id || '0'));
      wrap.setAttribute('data-feature-type', String(row.data_type || 'text'));

      const label = document.createElement('label');
      const selectId = 'mCatalogDyn_' + String(name || '').replace(/[^a-zA-Z0-9_]/g, '_');
      label.setAttribute('for', selectId);
      label.textContent = labelText;
      wrap.appendChild(label);

      const select = document.createElement('select');
      select.id = selectId;
      select.name = name;
      select.setAttribute('data-feature-input', '1');

      const empty = document.createElement('option');
      empty.value = '';
      empty.textContent = '-';
      select.appendChild(empty);

      (Array.isArray(options) ? options : []).forEach(function(opt){
        const option = document.createElement('option');
        const value = String((opt && opt.value) || '');
        option.value = value;
        option.textContent = String((opt && opt.label) || value);
        if(opt && opt.disabled){
          option.disabled = true;
        }
        if(value && value === String(selectedValue || '')){
          option.selected = true;
        }
        select.appendChild(option);
      });

      wrap.appendChild(select);
      return wrap;
    };

    const renderFeatureFilters = function(filters){
      featureFields.innerHTML = '';
      const rows = Array.isArray(filters) ? filters : [];
      if(!rows.length){
        const empty = document.createElement('div');
        empty.className = 'muted';
        empty.textContent = 'Keine Merkmale für die aktuelle Auswahl.';
        featureFields.appendChild(empty);
        syncFeatureToggle();
        return;
      }

      rows.forEach(function(row){
        const id = parseInt(String((row && row.id) || '0'), 10) || 0;
        if(id <= 0){
          return;
        }
        const dataType = String((row && row.data_type) || 'text');
        const label = String((row && row.label) || ('Merkmal ' + String(id)));
        if(dataType === 'number'){
          const minWrap = createFilterSelect(
            row,
            'f_' + String(id) + '_min',
            label + ' (Min)',
            row.min_options || [],
            String((row && row.min) || '')
          );
          const maxWrap = createFilterSelect(
            row,
            'f_' + String(id) + '_max',
            label + ' (Max)',
            row.max_options || [],
            String((row && row.max) || '')
          );
          featureFields.appendChild(minWrap);
          featureFields.appendChild(maxWrap);
          return;
        }
        if(dataType === 'bool'){
          const boolWrap = createFilterSelect(
            row,
            'f_' + String(id),
            label,
            row.bool_options || [],
            String((row && row.value) || '')
          );
          featureFields.appendChild(boolWrap);
          return;
        }
        const textWrap = createFilterSelect(
          row,
          'f_' + String(id),
          label,
          row.options || [],
          String((row && row.value) || '')
        );
        featureFields.appendChild(textWrap);
      });
      syncFeatureToggle();
    };

    const collectParams = function(includeFilters){
      const params = new URLSearchParams();
      const q = String(searchInput.value || '').trim();
      const kindId = String(kindSelect.value || '').trim();
      if(q){
        params.set('q', q);
      }
      if(kindId && kindId !== '0'){
        params.set('kind_id', kindId);
      }
      params.set('limit', '30');
      if(includeFilters){
        params.set('include_filters', '1');
      }

      const featureInputs = Array.from(featureFields.querySelectorAll('[data-feature-input="1"]'));
      featureInputs.forEach(function(input){
        if(!(input instanceof HTMLSelectElement) && !(input instanceof HTMLInputElement)){
          return;
        }
        const name = String(input.name || '').trim();
        const value = String(input.value || '').trim();
        if(!name || !value){
          return;
        }
        params.set(name, value);
      });
      return params;
    };

    const runRequest = function(includeFilters){
      const seq = ++requestSeq;
      renderState('Lade...');
      const params = collectParams(includeFilters);
      fetch('/api/mobile/catalog?' + params.toString(), {
        headers: { 'Accept': 'application/json' }
      }).then(function(resp){
        if(!resp.ok){
          throw new Error('HTTP ' + String(resp.status));
        }
        return resp.json();
      }).then(function(data){
        if(seq !== requestSeq){
          return;
        }
        if(includeFilters && Array.isArray(data.filters)){
          renderFeatureFilters(data.filters);
        }else{
          syncFeatureToggle();
        }
        const items = Array.isArray(data.items) ? data.items : [];
        renderItems(items);
      }).catch(function(){
        if(seq !== requestSeq){
          return;
        }
        renderState('Katalog ist gerade nicht verfügbar.');
      });
    };

    const queueRequest = function(includeFilters){
      if(debounceTimer){
        clearTimeout(debounceTimer);
      }
      debounceTimer = setTimeout(function(){
        runRequest(includeFilters);
      }, 240);
    };

    searchInput.addEventListener('input', function(){
      queueRequest(false);
    });
    searchInput.addEventListener('keydown', function(e){
      if(e.key !== 'Enter'){
        return;
      }
      e.preventDefault();
      runRequest(false);
    });
    kindSelect.addEventListener('change', function(){
      renderFeatureFilters([]);
      queueRequest(true);
    });
    featureFields.addEventListener('change', function(e){
      const target = e.target;
      if(!(target instanceof Element)) return;
      if(!target.matches('[data-feature-input="1"]')) return;
      queueRequest(false);
    });
    featureToggle.addEventListener('click', function(){
      setFeatureOpen(!featureOpen);
    });

    setFeatureOpen(false);
    syncFeatureToggle();
    runRequest(true);
  }

  function initMobileSparePartForm(){
    const form = document.querySelector('[data-mobile-spare-form="1"]');
    if(!form) return;

    const ownerSelect = document.getElementById('m_spare_owner_id');
    const fileInput = document.getElementById('m_spare_image_file');
    const previewWrap = form.querySelector('[data-spare-preview="1"]');
    const previewImg = form.querySelector('[data-spare-preview-img="1"]');
    const previewEmpty = form.querySelector('[data-spare-preview-empty="1"]');
    const ownerStorageKey = 'kda.mobile.spare.owner_id';
    let previewUrl = '';

    const optionExists = function(selectEl, value){
      if(!selectEl) return false;
      const target = String(value || '').trim();
      if(!target || target === '0') return false;
      return Array.from(selectEl.options || []).some(function(opt){
        return String(opt.value || '') === target;
      });
    };

    if(ownerSelect){
      const urlParams = new URLSearchParams(window.location.search || '');
      if(!urlParams.has('owner_id') && !String(ownerSelect.value || '').trim()){
        try{
          const remembered = window.localStorage ? String(window.localStorage.getItem(ownerStorageKey) || '').trim() : '';
          if(optionExists(ownerSelect, remembered)){
            ownerSelect.value = remembered;
          }
        }catch(_e){}
      }

      ownerSelect.addEventListener('change', function(){
        try{
          const val = String(ownerSelect.value || '').trim();
          if(window.localStorage && val && val !== '0'){
            window.localStorage.setItem(ownerStorageKey, val);
          }
        }catch(_e){}
      });
    }

    const clearPreview = function(){
      if(previewUrl){
        try{
          URL.revokeObjectURL(previewUrl);
        }catch(_e){}
        previewUrl = '';
      }
      if(previewImg){
        previewImg.setAttribute('src', '');
        previewImg.hidden = true;
      }
      if(previewEmpty){
        previewEmpty.hidden = false;
      }
      if(previewWrap){
        previewWrap.classList.remove('has-image');
      }
    };

    const setPreview = function(file){
      clearPreview();
      if(!file || !previewImg){
        return;
      }
      try{
        previewUrl = URL.createObjectURL(file);
      }catch(_e){
        previewUrl = '';
      }
      if(!previewUrl){
        return;
      }
      previewImg.setAttribute('src', previewUrl);
      previewImg.hidden = false;
      if(previewEmpty){
        previewEmpty.hidden = true;
      }
      if(previewWrap){
        previewWrap.classList.add('has-image');
      }
    };

    if(fileInput){
      fileInput.addEventListener('change', function(){
        const file = (fileInput.files && fileInput.files.length) ? fileInput.files[0] : null;
        setPreview(file);
      });
    }

    form.addEventListener('submit', function(){
      if(!ownerSelect) return;
      try{
        const val = String(ownerSelect.value || '').trim();
        if(window.localStorage && val && val !== '0'){
          window.localStorage.setItem(ownerStorageKey, val);
        }
      }catch(_e){}
    });
  }

  function initMobileTransferForm(){
    const form = document.querySelector('[data-mobile-transfer-form="1"]');
    if(!form) return;
    const fromSelect = document.getElementById('m_transfer_from_warehouse_id');
    const toSelect = document.getElementById('m_transfer_to_warehouse_id');
    const swapBtn = form.querySelector('[data-transfer-swap]');
    if(!fromSelect || !toSelect) return;

    const storageKey = 'kda.mobile.transfer.to_warehouse_id';

    const optionExists = function(selectEl, value){
      const target = String(value || '').trim();
      if(!target) return false;
      return Array.from(selectEl.options || []).some(function(opt){
        return String(opt.value || '') === target;
      });
    };

    const pickAlternativeTarget = function(fromValue){
      const fromRaw = String(fromValue || '');
      const first = Array.from(toSelect.options || []).find(function(opt){
        const val = String(opt.value || '');
        return val && val !== '0' && val !== fromRaw;
      });
      if(first){
        toSelect.value = first.value;
      }
    };

    const syncTargetAgainstSource = function(){
      if(String(fromSelect.value || '') === String(toSelect.value || '')){
        pickAlternativeTarget(fromSelect.value);
      }
    };

    const urlParams = new URLSearchParams(window.location.search || '');
    if(!urlParams.has('to_warehouse_id')){
      try{
        const remembered = window.localStorage ? String(window.localStorage.getItem(storageKey) || '').trim() : '';
        if(remembered && optionExists(toSelect, remembered) && remembered !== String(fromSelect.value || '')){
          toSelect.value = remembered;
        }
      }catch(_e){}
    }
    syncTargetAgainstSource();

    if(swapBtn){
      swapBtn.addEventListener('click', function(){
        const currentFrom = String(fromSelect.value || '');
        const currentTo = String(toSelect.value || '');
        fromSelect.value = currentTo;
        toSelect.value = currentFrom;
        syncTargetAgainstSource();
      });
    }

    fromSelect.addEventListener('change', function(){
      syncTargetAgainstSource();
    });

    form.addEventListener('submit', function(){
      try{
        if(window.localStorage && String(toSelect.value || '').trim()){
          window.localStorage.setItem(storageKey, String(toSelect.value || '').trim());
        }
      }catch(_e){}
    });
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

  function initImportMapDuplicateWarning(){
    const form = document.querySelector('form[data-import-map-form="1"]');
    if(!form) return;
    const warningBox = document.getElementById('mapDuplicateWarning');
    if(!warningBox) return;

    const parseIndexFromName = function(name){
      const raw = String(name || '');
      const idx = raw.replace('feature_use_', '');
      const parsed = Number(idx);
      return Number.isFinite(parsed) ? parsed : -1;
    };

    const normalizeNewLabel = function(value){
      return String(value || '')
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_+|_+$/g, '');
    };

    const syncWarning = function(){
      const checkboxes = Array.from(form.querySelectorAll('input[type="checkbox"][name^="feature_use_"]'));
      const seen = new Map();
      const duplicates = [];

      checkboxes.forEach(function(chk){
        if(!(chk instanceof HTMLInputElement) || !chk.checked){
          return;
        }
        const idx = parseIndexFromName(chk.name);
        if(idx < 0){
          return;
        }
        const existing = form.querySelector('select[name="feature_existing_key_' + idx + '"]');
        const newLabelInput = form.querySelector('input[name="feature_new_label_' + idx + '"]');
        const selectedExisting = existing ? String(existing.value || '').trim() : '';
        let key = '';
        if(selectedExisting && selectedExisting !== '__neu__'){
          key = 'exist:' + selectedExisting.toLowerCase();
        }else{
          const newLabel = normalizeNewLabel(newLabelInput ? newLabelInput.value : '');
          if(newLabel){
            key = 'new:' + newLabel;
          }
        }
        if(!key){
          return;
        }
        if(seen.has(key)){
          duplicates.push(key.replace(/^(exist:|new:)/, ''));
        }else{
          seen.set(key, idx);
        }
      });

      if(duplicates.length){
        const uniq = Array.from(new Set(duplicates));
        warningBox.textContent = 'Warnung: Doppelte Merkmalsziele gewählt: ' + uniq.join(', ');
        warningBox.hidden = false;
      }else{
        warningBox.textContent = '';
        warningBox.hidden = true;
      }
    };

    form.addEventListener('change', function(e){
      const target = e.target;
      if(!(target instanceof Element)) return;
      if(target.matches('input[name^="feature_use_"], select[name^="feature_existing_key_"], input[name^="feature_new_label_"]')){
        syncWarning();
      }
    });
    form.addEventListener('keyup', function(e){
      const target = e.target;
      if(!(target instanceof Element)) return;
      if(target.matches('input[name^="feature_new_label_"]')){
        syncWarning();
      }
    });
    syncWarning();
  }

  function initImportUploadCascade(){
    const form = document.querySelector('form[data-import-upload-form="1"]');
    if(!form) return;
    const areaSelect = form.querySelector('select[name="area_id"]');
    const kindSelect = form.querySelector('select[name="kind_id"]');
    if(!areaSelect || !kindSelect) return;

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

    areaSelect.addEventListener('change', syncKindOptions);
    syncKindOptions();
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

    const imageOverlay = document.getElementById('productImageOverlay');
    const imageOverlayImage = document.getElementById('productImageOverlayImage');
    const imageOverlayCloseBtn = document.getElementById('productImageOverlayClose');
    const imageOverlayPrevBtn = document.getElementById('productImageOverlayPrev');
    const imageOverlayNextBtn = document.getElementById('productImageOverlayNext');
    const imageOverlayCounter = document.getElementById('productImageOverlayCounter');
    const imageLinks = Array.from(document.querySelectorAll('[data-product-image-open="1"]'));
    const documentOverlay = document.getElementById('productDocumentOverlay');
    const documentOverlayFrame = document.getElementById('productDocumentOverlayFrame');
    const documentOverlayTitle = document.getElementById('productDocumentOverlayTitle');
    const documentOverlayCloseBtn = document.getElementById('productDocumentOverlayClose');
    const documentOverlayDownload = document.getElementById('productDocumentOverlayDownload');
    const documentOverlayPrint = document.getElementById('productDocumentOverlayPrint');
    const documentOverlayExternal = document.getElementById('productDocumentOverlayExternal');
    const documentButtons = Array.from(document.querySelectorAll('[data-product-document-open="1"]'));
    const imageItems = imageLinks.map(function(link, index){
      const href = String(link.getAttribute('href') || '').trim();
      const thumb = link.querySelector('img');
      const fallbackAlt = 'Produktbild ' + String(index + 1);
      const alt = thumb ? String(thumb.getAttribute('alt') || fallbackAlt) : fallbackAlt;
      return { link, href, alt };
    }).filter(function(item){
      return !!item.href;
    });
    if(imageOverlay && imageOverlayImage && imageItems.length){
      let lastTrigger = null;
      let currentIndex = 0;

      const renderImage = function(nextIndex){
        const total = imageItems.length;
        if(!total){
          return;
        }
        let safeIndex = nextIndex;
        if(safeIndex < 0){
          safeIndex = total - 1;
        }else if(safeIndex >= total){
          safeIndex = 0;
        }
        currentIndex = safeIndex;
        const item = imageItems[currentIndex];
        imageOverlayImage.setAttribute('src', item.href);
        imageOverlayImage.setAttribute('alt', item.alt);
        if(imageOverlayCounter){
          imageOverlayCounter.textContent = 'Bild ' + String(currentIndex + 1) + ' von ' + String(total);
        }
        const canNavigate = total > 1;
        if(imageOverlayPrevBtn){
          imageOverlayPrevBtn.disabled = !canNavigate;
        }
        if(imageOverlayNextBtn){
          imageOverlayNextBtn.disabled = !canNavigate;
        }
      };

      const showPrevImage = function(){
        if(imageItems.length < 2){
          return false;
        }
        renderImage(currentIndex - 1);
        return true;
      };

      const showNextImage = function(){
        if(imageItems.length < 2){
          return false;
        }
        renderImage(currentIndex + 1);
        return true;
      };

      const closeImageOverlay = function(){
        if(imageOverlay.hidden){
          return false;
        }
        imageOverlay.hidden = true;
        imageOverlay.setAttribute('aria-hidden', 'true');
        imageOverlayImage.setAttribute('src', '');
        imageOverlayImage.setAttribute('alt', '');
        document.body.classList.remove('image-lightbox-open');
        if(lastTrigger && typeof lastTrigger.focus === 'function'){
          lastTrigger.focus();
        }
        lastTrigger = null;
        return true;
      };

      const openImageOverlay = function(index, triggerEl){
        if(index < 0 || index >= imageItems.length){
          return;
        }
        lastTrigger = triggerEl || imageItems[index].link;
        renderImage(index);
        imageOverlay.hidden = false;
        imageOverlay.setAttribute('aria-hidden', 'false');
        document.body.classList.add('image-lightbox-open');
        if(imageOverlayCloseBtn){
          imageOverlayCloseBtn.focus();
        }
      };

      imageItems.forEach(function(item, index){
        item.link.addEventListener('click', function(e){
          e.preventDefault();
          openImageOverlay(index, item.link);
        });
      });

      if(imageOverlayCloseBtn){
        imageOverlayCloseBtn.addEventListener('click', function(){
          closeImageOverlay();
        });
      }
      if(imageOverlayPrevBtn){
        imageOverlayPrevBtn.addEventListener('click', function(){
          showPrevImage();
        });
      }
      if(imageOverlayNextBtn){
        imageOverlayNextBtn.addEventListener('click', function(){
          showNextImage();
        });
      }

      imageOverlay.addEventListener('click', function(e){
        const target = e.target;
        if(!(target instanceof Element)){
          return;
        }
        if(target === imageOverlay || target.hasAttribute('data-image-lightbox-close')){
          closeImageOverlay();
        }
      });

      document.addEventListener('keydown', function(e){
        if(imageOverlay.hidden){
          return;
        }
        if(e.key === 'Escape' && closeImageOverlay()){
          e.preventDefault();
          e.stopPropagation();
          return;
        }
        if(e.key === 'ArrowLeft' && showPrevImage()){
          e.preventDefault();
          e.stopPropagation();
          return;
        }
        if(e.key === 'ArrowRight' && showNextImage()){
          e.preventDefault();
          e.stopPropagation();
        }
      }, true);
    }

    if(documentOverlay && documentOverlayFrame && documentButtons.length){
      let lastDocumentTrigger = null;

      const closeDocumentOverlay = function(){
        if(documentOverlay.hidden){
          return false;
        }
        documentOverlay.hidden = true;
        documentOverlay.setAttribute('aria-hidden', 'true');
        documentOverlayFrame.setAttribute('src', 'about:blank');
        document.body.classList.remove('document-lightbox-open');
        if(lastDocumentTrigger && typeof lastDocumentTrigger.focus === 'function'){
          lastDocumentTrigger.focus();
        }
        lastDocumentTrigger = null;
        return true;
      };

      const openDocumentOverlay = function(triggerEl){
        const viewerUrl = String(triggerEl.getAttribute('data-document-viewer-url') || '').trim();
        const downloadUrl = String(triggerEl.getAttribute('data-document-download-url') || '').trim();
        const sourceUrl = String(triggerEl.getAttribute('data-document-source-url') || '').trim();
        const title = String(triggerEl.getAttribute('data-document-title') || 'Dokument').trim();
        const frameUrl = viewerUrl || sourceUrl || downloadUrl;
        if(!frameUrl){
          return;
        }
        lastDocumentTrigger = triggerEl;
        if(documentOverlayTitle){
          documentOverlayTitle.textContent = title;
        }
        if(documentOverlayDownload){
          if(downloadUrl){
            documentOverlayDownload.setAttribute('href', downloadUrl);
            documentOverlayDownload.hidden = false;
          }else{
            documentOverlayDownload.setAttribute('href', '#');
            documentOverlayDownload.hidden = true;
          }
        }
        if(documentOverlayExternal){
          const externalUrl = sourceUrl || viewerUrl || downloadUrl;
          if(externalUrl){
            documentOverlayExternal.setAttribute('href', externalUrl);
            documentOverlayExternal.hidden = false;
          }else{
            documentOverlayExternal.setAttribute('href', '#');
            documentOverlayExternal.hidden = true;
          }
        }
        if(documentOverlayPrint){
          documentOverlayPrint.disabled = !viewerUrl;
        }
        documentOverlayFrame.setAttribute('src', frameUrl);
        documentOverlay.hidden = false;
        documentOverlay.setAttribute('aria-hidden', 'false');
        document.body.classList.add('document-lightbox-open');
        if(documentOverlayCloseBtn){
          documentOverlayCloseBtn.focus();
        }
      };

      documentButtons.forEach(function(button){
        button.addEventListener('click', function(e){
          e.preventDefault();
          openDocumentOverlay(button);
        });
      });

      if(documentOverlayCloseBtn){
        documentOverlayCloseBtn.addEventListener('click', function(){
          closeDocumentOverlay();
        });
      }
      if(documentOverlayPrint){
        documentOverlayPrint.addEventListener('click', function(){
          try{
            if(documentOverlayFrame.contentWindow){
              documentOverlayFrame.contentWindow.focus();
              documentOverlayFrame.contentWindow.print();
              return;
            }
          }catch(err){
          }
          const fallbackUrl = String(documentOverlayExternal && documentOverlayExternal.getAttribute('href') || '').trim();
          if(fallbackUrl){
            window.open(fallbackUrl, '_blank', 'noopener');
          }
        });
      }

      documentOverlay.addEventListener('click', function(e){
        const target = e.target;
        if(!(target instanceof Element)){
          return;
        }
        if(target === documentOverlay || target.hasAttribute('data-document-lightbox-close')){
          closeDocumentOverlay();
        }
      });

      document.addEventListener('keydown', function(e){
        if(documentOverlay.hidden){
          return;
        }
        if(e.key === 'Escape' && closeDocumentOverlay()){
          e.preventDefault();
          e.stopPropagation();
        }
      }, true);
    }
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
    schedulePageLoading('Ansicht wird umgeschaltet...', 'Seite wird neu geladen.', 0);
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
      '5': '/einkauf/bestellungen',
      '6': '/catalog/products'
    };
    const href = map[e.key];
    if(!href) return false;
    e.preventDefault();
    navigateTo(href);
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
      navigateTo(row.url);
      return;
    }
    if(q){
      navigateTo('/catalog/products?q=' + encodeURIComponent(q));
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
    navigateTo(href);
    return true;
  }

  function handleEinkaufLetterHotkeys(e){
    if(e.altKey || e.ctrlKey || e.metaKey) return false;
    if(isTypingTarget(document.activeElement)) return false;
    const path = String(window.location && window.location.pathname || '');
    if(!(path.startsWith('/einkauf') || document.querySelector('[data-dashboard-hotkeys="1"]'))){
      return false;
    }
    const map = {
      'n': '/einkauf/bestellungen/neu',
      'N': '/einkauf/bestellungen/neu',
      'w': '/einkauf/wareneingaenge/neu',
      'W': '/einkauf/wareneingaenge/neu',
      'r': '/einkauf/rechnungen/neu',
      'R': '/einkauf/rechnungen/neu',
      'd': '/einkauf/dokumente',
      'D': '/einkauf/dokumente'
    };
    const href = map[e.key];
    if(!href) return false;
    e.preventDefault();
    navigateTo(href);
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
      navigateTo('/catalog/products/new?item_type=' + selected);
      return true;
    }
    if(e.key === 'Escape'){
      e.preventDefault();
      navigateTo('/catalog/products');
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
    navigateTo('/stammdaten/formularregeln?item_type=' + selected);
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

  function submitFormById(formId){
    const id = String(formId || '').trim();
    if(!id) return false;
    const form = document.getElementById(id);
    if(!(form instanceof HTMLFormElement)) return false;
    const blockingBtn = document.querySelector('button[form=\"' + id + '\"][disabled]');
    if(blockingBtn){
      return false;
    }
    if(typeof form.requestSubmit === 'function'){
      form.requestSubmit();
    }else{
      form.submit();
    }
    return true;
  }

  function handleRepairListHotkeys(e){
    const page = document.querySelector('[data-page=\"repair-list\"]');
    if(!page) return false;
    if(e.altKey || e.ctrlKey || e.metaKey) return false;
    if(isTypingTarget(document.activeElement)) return false;
    if(e.key === 'n' || e.key === 'N'){
      const btn = document.getElementById('repairNewBtn');
      if(!btn) return false;
      e.preventDefault();
      btn.click();
      return true;
    }
    return false;
  }

  function handleRepairDetailHotkeys(e){
    const page = document.querySelector('[data-page=\"repair-detail\"]');
    if(!page) return false;

    if((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === 'Enter')){
      if(submitFormById('repairNoteForm')){
        e.preventDefault();
        return true;
      }
      return false;
    }

    if(e.altKey || e.ctrlKey || e.metaKey) return false;
    if(isTypingTarget(document.activeElement)) return false;

    const map = {
      'a': 'repairActionAForm',
      'b': 'repairActionBForm',
      'r': 'repairActionRForm',
      'e': 'repairActionEForm',
      'v': 'repairActionVForm',
      'l': 'repairActionLForm',
      's': 'repairActionSForm'
    };
    const key = String(e.key || '').toLowerCase();
    const formId = map[key];
    if(!formId) return false;
    if(submitFormById(formId)){
      e.preventDefault();
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

  function initPdfMarkerReviews(){
    const scopes = Array.prototype.slice.call(document.querySelectorAll('[data-pdf-marker-scope]'));
    if(!scopes.length){
      return;
    }

    function clamp(value, min, max){
      return Math.min(max, Math.max(min, value));
    }

    function parseMarker(rawValue){
      const raw = String(rawValue || '').trim();
      if(!raw){
        return null;
      }
      try{
        const parsed = JSON.parse(raw);
        if(!parsed || typeof parsed !== 'object'){
          return null;
        }
        const page = Math.max(1, parseInt(parsed.page || 1, 10) || 1);
        const x = clamp(Number(parsed.x || 0), 0, 100);
        const y = clamp(Number(parsed.y || 0), 0, 100);
        const w = clamp(Number(parsed.w || 0), 0, 100 - x);
        const h = clamp(Number(parsed.h || 0), 0, 100 - y);
        if(!w || !h){
          return null;
        }
        return {
          page: page,
          x: Number(x.toFixed(3)),
          y: Number(y.toFixed(3)),
          w: Number(w.toFixed(3)),
          h: Number(h.toFixed(3))
        };
      }catch(_e){
        return null;
      }
    }

    function markerSummary(marker){
      if(!marker){
        return 'Keine Markierung';
      }
      return 'Seite ' + String(marker.page) + ' · ' + String(Math.round(marker.x)) + '% / ' + String(Math.round(marker.y)) + '%';
    }

    scopes.forEach(function(scope){
      const root = scope.querySelector('[data-pdf-marker-root]');
      if(!root || root.getAttribute('data-pdf-marker-ready') === '1'){
        return;
      }
      root.setAttribute('data-pdf-marker-ready', '1');

      const previewBase = String(root.getAttribute('data-preview-base') || '').trim();
      if(!previewBase){
        return;
      }

      const image = root.querySelector('[data-pdf-image]');
      const layer = root.querySelector('[data-pdf-layer]');
      const draft = root.querySelector('[data-pdf-draft]');
      const stage = root.querySelector('[data-pdf-stage]');
      const stageWrap = root.querySelector('.pdf-marker-stage-wrap');
      const statusEl = root.querySelector('[data-pdf-status]');
      const pageLabelEl = root.querySelector('[data-pdf-page-label]');
      const zoomLabelEl = root.querySelector('[data-pdf-zoom-label]');
      const prevBtn = root.querySelector('[data-pdf-prev]');
      const nextBtn = root.querySelector('[data-pdf-next]');
      const zoomInBtn = root.querySelector('[data-pdf-zoom-in]');
      const zoomOutBtn = root.querySelector('[data-pdf-zoom-out]');
      const zoomResetBtn = root.querySelector('[data-pdf-zoom-reset]');
      const countTotalEl = scope.querySelector('[data-pdf-marker-count-total]');
      const countMarkedEl = scope.querySelector('[data-pdf-marker-count-marked]');
      const countOpenEl = scope.querySelector('[data-pdf-marker-count-open]');
      const countRequiredOpenEl = scope.querySelector('[data-pdf-marker-count-required-open]');
      const progressFillEl = scope.querySelector('[data-pdf-marker-progress-fill]');
      const progressLabelEl = scope.querySelector('[data-pdf-marker-progress-label]');
      const nextOpenBtn = scope.querySelector('[data-pdf-marker-next-open]');
      const firstOpenBtn = scope.querySelector('[data-pdf-marker-first-open]');
      if(!image || !layer || !draft || !stage){
        return;
      }

      const fields = Array.prototype.slice.call(scope.querySelectorAll('[data-pdf-marker-field]')).map(function(el){
        const attrId = parseInt(el.getAttribute('data-attr-id') || '0', 10) || 0;
        const input = el.querySelector('[data-pdf-marker-input]');
        if(!attrId || !input){
          return null;
        }
        return {
          el: el,
          attrId: attrId,
          attrName: String(el.getAttribute('data-attr-name') || '').trim() || ('Merkmal ' + String(attrId)),
          input: input,
          summary: el.querySelector('[data-pdf-marker-summary]'),
          chip: el.querySelector('[data-pdf-marker-chip]'),
          selectBtn: el.querySelector('[data-pdf-marker-select]'),
          openBtn: el.querySelector('[data-pdf-marker-open]'),
          clearBtn: el.querySelector('[data-pdf-marker-clear]'),
          required: String(el.getAttribute('data-pdf-marker-required') || '') === '1'
        };
      }).filter(Boolean);
      if(!fields.length){
        return;
      }

      const markers = {};
      fields.forEach(function(field){
        const marker = parseMarker(field.input.value);
        if(marker){
          markers[field.attrId] = marker;
        }
      });

      let activeAttrId = 0;
      let pageCount = Math.max(1, parseInt(root.getAttribute('data-page-count') || '1', 10) || 1);
      let currentPage = clamp(parseInt(root.getAttribute('data-initial-page') || '1', 10) || 1, 1, pageCount);
      let zoom = clamp(parseFloat(root.getAttribute('data-initial-zoom') || '1.4') || 1.4, 0.8, 2.4);
      let dragState = null;
      let afterImageLoad = null;

      function fieldById(attrId){
        for(let i = 0; i < fields.length; i += 1){
          if(fields[i].attrId === attrId){
            return fields[i];
          }
        }
        return null;
      }

      function nextUnmarkedField(afterAttrId){
        if(!fields.length){
          return null;
        }
        let startIndex = 0;
        for(let i = 0; i < fields.length; i += 1){
          if(fields[i].attrId === afterAttrId){
            startIndex = i + 1;
            break;
          }
        }
        for(let offset = 0; offset < fields.length; offset += 1){
          const field = fields[(startIndex + offset) % fields.length];
          if(!markers[field.attrId]){
            return field;
          }
        }
        return fieldById(afterAttrId) || fields[0];
      }

      function setStatus(message){
        if(statusEl){
          statusEl.textContent = String(message || '');
        }
      }

      function updateToolbar(){
        if(pageLabelEl){
          pageLabelEl.textContent = 'Seite ' + String(currentPage) + ' / ' + String(pageCount);
        }
        if(zoomLabelEl){
          zoomLabelEl.textContent = String(Math.round(zoom * 100)) + '%';
        }
        if(prevBtn){
          prevBtn.disabled = currentPage <= 1;
        }
        if(nextBtn){
          nextBtn.disabled = currentPage >= pageCount;
        }
      }

      function writeMarker(field, marker){
        if(marker){
          markers[field.attrId] = marker;
          field.input.value = JSON.stringify(marker);
        }else{
          delete markers[field.attrId];
          field.input.value = '';
        }
      }

      function updateFieldStates(){
        let markedCount = 0;
        let requiredOpenCount = 0;
        fields.forEach(function(field){
          const marker = markers[field.attrId] || null;
          const isActive = field.attrId === activeAttrId;
          field.el.classList.toggle('is-active', field.attrId === activeAttrId);
          field.el.classList.toggle('has-marker', !!marker);
          if(marker){
            markedCount += 1;
          }else if(field.required){
            requiredOpenCount += 1;
          }
          if(field.summary){
            field.summary.textContent = markerSummary(marker);
          }
          if(field.chip){
            field.chip.classList.toggle('is-active', !marker && isActive);
            field.chip.classList.toggle('is-marked', !!marker);
            field.chip.textContent = marker ? 'Markiert' : (isActive ? 'Aktiv' : 'Offen');
          }
          if(field.openBtn){
            field.openBtn.hidden = !marker;
          }
          if(field.clearBtn){
            field.clearBtn.hidden = !marker;
          }
          if(field.selectBtn){
            field.selectBtn.textContent = field.attrId === activeAttrId ? 'Aktiv im PDF' : 'Im PDF markieren';
          }
        });
        const totalCount = fields.length;
        const openCount = Math.max(0, totalCount - markedCount);
        const percent = totalCount ? Math.round((markedCount / totalCount) * 100) : 0;
        if(countTotalEl){
          countTotalEl.textContent = String(totalCount);
        }
        if(countMarkedEl){
          countMarkedEl.textContent = String(markedCount);
        }
        if(countOpenEl){
          countOpenEl.textContent = String(openCount);
        }
        if(countRequiredOpenEl){
          countRequiredOpenEl.textContent = String(requiredOpenCount);
        }
        if(progressFillEl){
          progressFillEl.style.width = String(percent) + '%';
        }
        if(progressLabelEl){
          progressLabelEl.textContent = totalCount ? (String(markedCount) + ' von ' + String(totalCount) + ' Merkmalen markiert') : 'Keine Merkmale';
        }
      }

      function scrollToMarker(marker){
        if(!marker || !stageWrap){
          return;
        }
        const wrapWidth = stageWrap.clientWidth || 0;
        const wrapHeight = stageWrap.clientHeight || 0;
        const targetLeft = Math.max(0, ((marker.x + marker.w / 2) / 100) * stage.offsetWidth - wrapWidth / 2);
        const targetTop = Math.max(0, ((marker.y + marker.h / 2) / 100) * stage.offsetHeight - wrapHeight / 2);
        stageWrap.scrollTo({ left: targetLeft, top: targetTop, behavior: 'smooth' });
      }

      function selectField(attrId){
        activeAttrId = attrId;
        const field = fieldById(attrId);
        if(field){
          setStatus('Aktiv: ' + field.attrName + '. Rechteck im PDF aufziehen oder bestehende Markierung anpassen.');
          try{
            field.el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
          }catch(_e){}
        }
        layer.classList.add('is-armed');
        updateFieldStates();
        try{
          stage.focus({ preventScroll: true });
        }catch(_e){
          try{
            stage.focus();
          }catch(_err){}
        }
      }

      function renderMarkers(){
        layer.innerHTML = '';
        fields.forEach(function(field){
          const marker = markers[field.attrId];
          if(!marker || marker.page !== currentPage){
            return;
          }
          const box = document.createElement('button');
          box.type = 'button';
          box.className = 'pdf-marker-box' + (field.attrId === activeAttrId ? ' active' : '');
          box.style.left = String(marker.x) + '%';
          box.style.top = String(marker.y) + '%';
          box.style.width = String(marker.w) + '%';
          box.style.height = String(marker.h) + '%';
          box.setAttribute('aria-label', field.attrName);
          box.innerHTML = '<span class="pdf-marker-box-label">' + field.attrName + '</span>';
          box.addEventListener('click', function(ev){
            ev.preventDefault();
            selectField(field.attrId);
            scrollToMarker(marker);
          });
          layer.appendChild(box);
        });
      }

      function loadPreview(){
        updateToolbar();
        image.src = previewBase + '?page=' + encodeURIComponent(String(currentPage)) + '&zoom=' + encodeURIComponent(String(zoom.toFixed(2)));
      }

      function openMarker(field){
        const marker = markers[field.attrId];
        if(!marker){
          return;
        }
        selectField(field.attrId);
        if(currentPage !== marker.page){
          currentPage = marker.page;
          afterImageLoad = function(){
            scrollToMarker(marker);
          };
          loadPreview();
          return;
        }
        scrollToMarker(marker);
        renderMarkers();
      }

      function pointerPercent(ev){
        const rect = layer.getBoundingClientRect();
        if(!rect.width || !rect.height){
          return null;
        }
        return {
          x: clamp(((ev.clientX - rect.left) / rect.width) * 100, 0, 100),
          y: clamp(((ev.clientY - rect.top) / rect.height) * 100, 0, 100)
        };
      }

      function updateDraftBox(marker){
        draft.hidden = false;
        draft.style.left = String(marker.x) + '%';
        draft.style.top = String(marker.y) + '%';
        draft.style.width = String(marker.w) + '%';
        draft.style.height = String(marker.h) + '%';
      }

      fields.forEach(function(field){
        if(field.selectBtn){
          field.selectBtn.addEventListener('click', function(ev){
            ev.preventDefault();
            selectField(field.attrId);
          });
        }
        if(field.clearBtn){
          field.clearBtn.addEventListener('click', function(ev){
            ev.preventDefault();
            writeMarker(field, null);
            updateFieldStates();
            renderMarkers();
            selectField(field.attrId);
          });
        }
        if(field.openBtn){
          field.openBtn.addEventListener('click', function(ev){
            ev.preventDefault();
            openMarker(field);
          });
        }
      });

      layer.addEventListener('mousedown', function(ev){
        if(ev.button !== 0 || ev.target !== layer){
          return;
        }
        if(!activeAttrId){
          setStatus('Erst rechts ein Merkmal auswählen, dann die Stelle im PDF markieren.');
          return;
        }
        const point = pointerPercent(ev);
        if(!point){
          return;
        }
        ev.preventDefault();
        dragState = {
          attrId: activeAttrId,
          startX: point.x,
          startY: point.y
        };
        updateDraftBox({ x: point.x, y: point.y, w: 0.1, h: 0.1 });
      });

      document.addEventListener('mousemove', function(ev){
        if(!dragState){
          return;
        }
        const point = pointerPercent(ev);
        if(!point){
          return;
        }
        const x1 = Math.min(dragState.startX, point.x);
        const y1 = Math.min(dragState.startY, point.y);
        const x2 = Math.max(dragState.startX, point.x);
        const y2 = Math.max(dragState.startY, point.y);
        updateDraftBox({
          x: x1,
          y: y1,
          w: Math.max(0.1, x2 - x1),
          h: Math.max(0.1, y2 - y1)
        });
      });

      document.addEventListener('mouseup', function(ev){
        if(!dragState){
          return;
        }
        const point = pointerPercent(ev) || { x: dragState.startX, y: dragState.startY };
        const x1 = Math.min(dragState.startX, point.x);
        const y1 = Math.min(dragState.startY, point.y);
        const x2 = Math.max(dragState.startX, point.x);
        const y2 = Math.max(dragState.startY, point.y);
        draft.hidden = true;
        const field = fieldById(dragState.attrId);
        if(field && (x2 - x1) >= 0.6 && (y2 - y1) >= 0.6){
          writeMarker(field, {
            page: currentPage,
            x: Number(x1.toFixed(3)),
            y: Number(y1.toFixed(3)),
            w: Number((x2 - x1).toFixed(3)),
            h: Number((y2 - y1).toFixed(3))
          });
          const nextField = nextUnmarkedField(field.attrId);
          if(nextField && nextField.attrId !== field.attrId){
            setStatus(field.attrName + ' wurde markiert. Weiter mit ' + nextField.attrName + '.');
            selectField(nextField.attrId);
          }else{
            setStatus(field.attrName + ' wurde auf Seite ' + String(currentPage) + ' markiert.');
            selectField(field.attrId);
          }
          updateFieldStates();
          renderMarkers();
        }else if(field){
          setStatus('Markierung für ' + field.attrName + ' war zu klein. Bitte das Feld mit gedrückter Maustaste aufziehen.');
        }
        dragState = null;
      });

      image.addEventListener('load', function(){
        renderMarkers();
        if(typeof afterImageLoad === 'function'){
          const callback = afterImageLoad;
          afterImageLoad = null;
          callback();
        }
      });

      stage.addEventListener('keydown', function(ev){
        if(ev.key === 'ArrowRight' && currentPage < pageCount){
          ev.preventDefault();
          currentPage += 1;
          loadPreview();
          return;
        }
        if(ev.key === 'ArrowLeft' && currentPage > 1){
          ev.preventDefault();
          currentPage -= 1;
          loadPreview();
          return;
        }
        if((ev.key === '+' || ev.key === '=') && !ev.ctrlKey && !ev.metaKey){
          ev.preventDefault();
          zoom = clamp(Number((zoom + 0.2).toFixed(2)), 0.8, 2.4);
          loadPreview();
          return;
        }
        if(ev.key === '-' && !ev.ctrlKey && !ev.metaKey){
          ev.preventDefault();
          zoom = clamp(Number((zoom - 0.2).toFixed(2)), 0.8, 2.4);
          loadPreview();
        }
      });

      if(prevBtn){
        prevBtn.addEventListener('click', function(ev){
          ev.preventDefault();
          if(currentPage <= 1){
            return;
          }
          currentPage -= 1;
          loadPreview();
        });
      }
      if(nextBtn){
        nextBtn.addEventListener('click', function(ev){
          ev.preventDefault();
          if(currentPage >= pageCount){
            return;
          }
          currentPage += 1;
          loadPreview();
        });
      }
      if(zoomInBtn){
        zoomInBtn.addEventListener('click', function(ev){
          ev.preventDefault();
          zoom = clamp(Number((zoom + 0.2).toFixed(2)), 0.8, 2.4);
          loadPreview();
        });
      }
      if(zoomOutBtn){
        zoomOutBtn.addEventListener('click', function(ev){
          ev.preventDefault();
          zoom = clamp(Number((zoom - 0.2).toFixed(2)), 0.8, 2.4);
          loadPreview();
        });
      }
      if(zoomResetBtn){
        zoomResetBtn.addEventListener('click', function(ev){
          ev.preventDefault();
          zoom = 1.4;
          loadPreview();
        });
      }
      if(nextOpenBtn){
        nextOpenBtn.addEventListener('click', function(ev){
          ev.preventDefault();
          const field = nextUnmarkedField(activeAttrId || 0);
          if(field){
            selectField(field.attrId);
          }
        });
      }
      if(firstOpenBtn){
        firstOpenBtn.addEventListener('click', function(ev){
          ev.preventDefault();
          const field = nextUnmarkedField(0);
          if(field){
            selectField(field.attrId);
          }
        });
      }

      updateFieldStates();
      const initialField = nextUnmarkedField(0);
      if(initialField){
        selectField(initialField.attrId);
      }else{
        setStatus('Rechts ein Merkmal auswählen und dann die passende Stelle im PDF markieren.');
      }
      loadPreview();
    });
  }

  fetch('/meta/version').then(r=>r.json()).then(v=>{
    const el = document.getElementById('versionLine');
    if(!el) return;
    const buildDate = v.build_date || '';
    el.textContent = `v${v.version} (Stand ${v.build}, ${buildDate}, ${v.git_sha})`;
  }).catch(()=>{});

  document.addEventListener('keydown', function(e){
    const active = document.activeElement;
    const pageLoadingOpen = document.body && document.body.classList.contains('page-loading-open');
    if(pageLoadingOpen){
      return;
    }
    const imageOverlayOpen = document.body && document.body.classList.contains('image-lightbox-open');
    if(imageOverlayOpen){
      return;
    }

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

    if(handleEinkaufLetterHotkeys(e)){
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

    if(handleRepairListHotkeys(e)){
      return;
    }

    if(handleRepairDetailHotkeys(e)){
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
        navigateTo(href);
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
  initPageLoadingStatus();
  initJobMonitor();
  initGenericScanButtons();
  initSerialScanButtons();
  initHelpPanel();
  initNavDropdowns();
  initCommandPalette();
  initLoadbeePanel();
  initProductAttributeReload();
  initCatalogListCascadeFilter();
  initCatalogMobileFilterPanel();
  initImportUploadCascade();
  initImportMapCascadeDefaults();
  initImportMapDuplicateWarning();
  initPdfMarkerReviews();
  initTxFormAdjustActions();
  initProductDetailPanels();
  initTraitRangeSliders();
  initMobileHomeQuickSearch();
  initMobileCatalog();
  initMobileSparePartForm();
  initMobileTransferForm();
  initFirstErrorFocus();
  initFilterSelectInputs();
  initCustomerListLiveSearch();
  attachSelectFilter('tx_product_filter', 'tx_product_id');
  attachSelectFilter('reservation_product_filter', 'reservation_product_id');
  attachSelectFilter('set_item_product_filter', 'set_item_product_id');
  attachSelectFilter('repair_product_filter', 'repair_product_id');
  attachSelectFilter('m_receipt_product_filter', 'm_receipt_product_id');
  attachSelectFilter('m_issue_product_filter', 'm_issue_product_id');
  attachSelectFilter('m_transfer_product_filter', 'm_transfer_product_id');
  attachSelectFilter('m_order_product_filter', 'm_order_product_id');
})();
