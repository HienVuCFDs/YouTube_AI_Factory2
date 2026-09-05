// studio-lanes.js - wizard steps, the short lane, storyboard
//
// Part of one page split into ordered files. These are classic
// scripts sharing a single global scope and running in document
// order, so this is a move rather than a rewrite: the files
// concatenated in order are byte for byte the block they came from,
// which is what the test asserts.
  function syncStudioLaneTabs() {
    const wanted = shortLaneWanted();
    SHORT_LANE_PANES.forEach((stepId) => {
      const split = document.querySelector(`.studio-lane-split[data-lane-step="${stepId}"]`);
      if (split) split.classList.toggle('is-split', wanted);
      const short = document.querySelector(
        `.studio-lane-pane[data-lane-step="${stepId}"][data-lane="short"]`);
      // Hidden rather than merely un-split: an unwanted short column must not
      // stay on the page taking half the width off the long video.
      if (short) short.hidden = !wanted;
    });
  }

  const SHORT_LANE_STEPS = [
    {key: 'script',  label: 'Kịch bản'},
    {key: 'voice',   label: 'Giọng đọc'},
    {key: 'visuals', label: 'Cảnh'},
    {key: 'render',  label: 'Dựng'},
  ];

  // Read from the timeline rather than a status column, so a step that is
  // re-run reports honestly instead of staying green from last time.
  async function loadShortLane() {
    const projectId = Number(state.studioProjectId || state.projectId || 0);
    if (!projectId) { state.shortLane = null; syncStudioLaneTabs(); return; }
    try { renderShortLane(await api(`/api/projects/${projectId}/short-lane`)); }
    catch (_) { syncStudioLaneTabs(); }
  }

  function shortStepStrip(lane) {
    const steps = lane?.steps || {};
    return '<div class="studio-steps">' + SHORT_LANE_STEPS.map((step, index) => {
      const done = Boolean(steps[step.key]);
      return `<div class="studio-step-chip${done ? ' is-done' : ''}">`
        + `<b>${done ? '✓' : String(index + 1).padStart(2, '0')}</b>`
        + `<span>${step.label}</span></div>`;
    }).join('') + '</div>';
  }

  function renderShortLane(lane) {
    state.shortLane = lane || null;
    state.shortShots = lane?.shots || [];
    syncStudioLaneTabs();
    const projectId = Number(state.studioProjectId || state.projectId || 0);
    const script = lane?.script;
    const scenes = lane?.scenes || 0;
    const sourceAction = [...document.querySelectorAll('button')].find((button) =>
      button.getAttribute('onclick')?.includes('cutShortSourceScenes()'));
    const buildAction = [...document.querySelectorAll('button')].find((button) =>
      button.getAttribute('onclick')?.includes("queueShortVariantJob('source_visuals')"));
    const isReup = state.studioWorkflow === 'reup';
    const readyToCut = Number(lane?.voiced || 0) === Number(scenes) && Number(scenes) > 0;
    if (sourceAction) {
      sourceAction.textContent = isReup
        ? (readyToCut ? 'Cắt cảnh Short từ video nguồn' : 'Cắt cảnh Short · cần giọng trước')
        : 'Tạo hình AI cho Short';
      sourceAction.disabled = isReup ? !readyToCut : !Number(scenes);
      sourceAction.title = isReup
        ? (readyToCut ? 'Cắt clip nguồn đúng theo độ dài của từng đoạn giọng Short.' : 'Tạo đủ giọng trước để clip được cắt đúng thời lượng.')
        : 'Tạo ảnh 9:16 theo storyboard riêng của Short.';
    }
    if (buildAction) {
      buildAction.textContent = isReup
        ? (readyToCut ? 'Cắt cảnh Short từ video nguồn' : 'Cắt cảnh Short · cần giọng trước')
        : 'Tạo hình AI cho Short';
      buildAction.disabled = isReup ? !readyToCut : !Number(scenes);
      buildAction.title = isReup
        ? 'Cắt clip nguồn đúng theo độ dài của từng đoạn giọng Short.'
        : 'Tạo ảnh 9:16 theo storyboard riêng của Short.';
    }

    const scriptView = $('studioShortScriptView');
    if (scriptView) {
      scriptView.innerHTML = script
        ? shortStepStrip(lane)
          + `<h4 style="margin:10px 0 4px">${esc(script.script_title || 'Bản Short')}</h4>`
          + `<div class="studio-model-note">Khoảng ${lane.estimated_seconds || 0} giây · ${scenes} cảnh</div>`
          + `<p style="margin:8px 0 0"><b>Hook:</b> ${esc(script.hook || '')}</p>`
          + `<p style="margin:6px 0 0;white-space:pre-wrap">${esc(script.main_content || '')}</p>`
          + (script.cta ? `<p style="margin:6px 0 0"><b>Kết:</b> ${esc(script.cta)}</p>` : '')
        : '<div class="studio-empty">Chưa có kịch bản Short. Bấm “Viết lại kịch bản Short”, '
          + 'hoặc bật “Tạo Short riêng cùng lúc” rồi viết kịch bản.</div>';
    }

    const storyboard = $('studioShortStoryboard');
    if (storyboard) {
      const shots = lane?.shots || [];
      if (!shots.length) {
        storyboard.innerHTML = '<div class="studio-empty">Chưa có storyboard Short — viết kịch bản Short trước.</div>';
      } else {
        storyboard.innerHTML = `<div id="studioShortStoryboardCards"></div>`;
        // The same cards as the long video: picture, a player for the voice,
        // and the per-scene controls.
        renderStudioStoryboard(shots, lane.timeline || [], 'studioShortStoryboardCards');
        storyboard.insertAdjacentHTML('afterbegin', shortStepStrip(lane));
      }
    }

    const voiceState = $('studioShortVoiceState');
    if (voiceState) {
      voiceState.innerHTML = scenes
        ? shortStepStrip(lane)
          + `<div class="studio-model-note" style="margin-top:8px">Đã có giọng cho `
          + `${lane.voiced || 0}/${scenes} cảnh của Short.</div>`
        : '<div class="studio-empty">Chưa có cảnh nào để đọc.</div>';
    }
    renderShortVoiceReview(lane, projectId);

    // Both finished videos sit on the publish step. The short's used to be
    // shown back in the build step, so the last step listed one of the two
    // videos the project had just made and offered no way to publish the other.
    const output = $('studioShortFinal');
    const outputKey = JSON.stringify([projectId, script?.id, lane?.output_path, lane?.render_version,
      lane?.output_path ? null : [lane?.with_visuals, scenes]]);
    if (output && output.dataset.renderKey !== outputKey) {
      output.dataset.renderKey = outputKey;
      output.innerHTML = '<div class="studio-lane-head" style="display:block">Short</div>'
        + (lane?.output_path
          ? `<div class="studio-result"><video controls playsinline preload="metadata"`
            + ` style="max-width:320px;border-radius:8px;background:#000"`
            + ` src="/api/projects/${projectId}/short-video?v=${encodeURIComponent(lane?.render_version || '')}"></video>`
            + `<div class="studio-model-note short-playback-error" hidden>Không phát được video. Hãy thử nút Mở / tải MP4 bên dưới.</div>`
            + `<div class="studio-actions" style="margin-top:8px;gap:6px;flex-wrap:wrap">`
            + `<a class="btn ghost" href="/api/projects/${projectId}/short-video" target="_blank" rel="noreferrer">Mở / tải MP4</a>`
            + `<button class="btn primary" type="button" onclick="openPublishDialog('short')">Đăng Short</button>`
            + `</div></div>`
          : `<div class="studio-result"><div class="studio-empty">Chưa dựng Short. `
            + `Hình ${lane?.with_visuals || 0}/${scenes} cảnh — quay lại Xưởng dựng để dựng.</div></div>`);
      output.querySelector('video')?.addEventListener('error', () => {
        const note = output.querySelector('.short-playback-error');
        if (note) note.hidden = false;
      });
    }
  }

  function stopShortVoiceSequence() {
    const audio = state.shortVoiceSequence;
    if (audio) { audio.pause(); audio.src = ''; }
    state.shortVoiceSequence = null;
  }

  async function playShortVoiceSequence(projectId) {
    const timeline = (state.shortLane?.timeline || []).filter((segment) => String(segment.audio_path || '').trim());
    if (!timeline.length) return setMessage('Short chưa có file giọng để nghe.', 'error');
    stopShortVoiceSequence();
    let index = 0;
    const playNext = async () => {
      if (index >= timeline.length) { state.shortVoiceSequence = null; return; }
      const segment = timeline[index++];
      const audio = new Audio(`/api/projects/${projectId}/timeline/${segment.id}/audio-preview`);
      state.shortVoiceSequence = audio;
      audio.onended = () => { void playNext(); };
      audio.onerror = () => { setMessage(`Không phát được giọng cảnh ${segment.segment_index}.`, 'error'); state.shortVoiceSequence = null; };
      try { await audio.play(); }
      catch (_) { setMessage('Trình duyệt chặn phát audio. Hãy bấm nghe từng cảnh.', 'error'); state.shortVoiceSequence = null; }
    };
    setMessage(`Đang phát liên tục ${timeline.length} đoạn giọng Short.`);
    await playNext();
  }

  function renderShortVoiceReview(lane, projectId) {
    const target = $('studioShortVoiceState');
    const scenes = Number(lane?.scenes || 0);
    if (!target || !scenes) return;
    const voiced = Number(lane?.voiced || 0);
    target.innerHTML = shortStepStrip(lane)
      + `<div class="studio-model-note" style="margin-top:8px">Đã có giọng cho ${voiced}/${scenes} cảnh Short. Bạn có thể nghe từng cảnh tại Storyboard hoặc phát toàn bộ ở đây.</div>`
      + `<div class="studio-actions" style="margin-top:8px;gap:6px"><button class="btn small primary" type="button" onclick="playShortVoiceSequence(${Number(projectId)})" ${voiced ? '' : 'disabled'}>▶ Nghe toàn bộ Short</button><button class="btn small ghost" type="button" onclick="stopShortVoiceSequence()">Dừng</button></div>`;
  }

  function renderShortScriptState(payload) { renderShortLane(payload); }
  async function loadShortScriptState() { await loadShortLane(); }

  async function writeShortScript() {
    const projectId = Number(state.studioProjectId || state.projectId || 0);
    if (!projectId) { setMessage('Hãy mở một dự án trước.', 'error'); return; }
    const seconds = Number($('studioShortScriptSeconds')?.value || 45);
    setMessage('Đang viết kịch bản cho bản short riêng...', '');
    try {
      const result = await api(`/api/projects/${projectId}/short-script`, {
        method: 'POST',
        body: JSON.stringify({seconds, use_model: true}),
      });
      renderShortScriptState(result);
      setMessage(`Đã viết bản short ${result.estimated_seconds}s với ${(result.timeline || []).length} cảnh.`, 'success');
    } catch (error) { setMessage(error.message, 'error'); }
  }

  // Every job for the standalone short carries variant:'short', which is what
  // points it at that script's own timeline instead of the long video's.
  const SHORT_JOB_PROVIDERS = {
    voiceover: 'edge_tts', source_visuals: 'source_video', render_short: 'ffmpeg_builtin',
  };

  async function queueShortVariantJob(jobType) {
    const projectId = Number(state.studioProjectId || state.projectId || 0);
    if (!projectId) { setMessage('Hãy mở một dự án trước.', 'error'); return; }
    // Content Shorts are illustrated from their own vertical storyboard. Only
    // the reup workflow has source footage to cut, so never send a Content
    // Short through the source-video worker.
    if (jobType === 'source_visuals' && state.studioWorkflow !== 'reup') {
      await generateShortSceneImages();
      return;
    }
    const provider = jobType === 'voiceover'
      ? ($('studioVoiceProviderSelect')?.value || SHORT_JOB_PROVIDERS.voiceover)
      : SHORT_JOB_PROVIDERS[jobType];
    try {
      await api(`/api/projects/${projectId}/jobs`, {
        method: 'POST',
        body: JSON.stringify({job_type: jobType, provider, confirmed: true, variant: 'short'}),
      });
      setMessage('Đã xếp hàng cho luồng Short.', 'success');
      await loadProductionQueueStatus?.();
      await loadShortLane();
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function generateShortSceneImages() {
    const provider = $('studioSceneImageProviderSelect')?.value || 'flow_image';
    await runStudioSceneBatch(provider, false, null, 'short');
    await loadShortLane();
  }



  async function detectTimelineCleanup() {
    const projectId = Number(state.studioProjectId || state.projectId || 0);
    if (!projectId) { setMessage('Hãy mở một dự án trước.', 'error'); return; }
    setMessage('Đang đo trên video gốc để tìm phụ đề và logo...', '');
    try {
      const result = await api(`/api/projects/${projectId}/timeline/cleanups`, {
        method: 'POST',
        body: JSON.stringify({detect: true}),
      });
      renderCleanupState(result.cleanups, result.segments);
      setMessage(
        result.status === 'nothing_found'
          ? 'Không tìm thấy phụ đề hay logo cháy sẵn trên video gốc.'
          : `Đã dò ra ${result.cleanups.length} vùng và che trên ${result.segments} cảnh.`,
        result.status === 'nothing_found' ? '' : 'success');
    } catch (error) { setMessage(error.message, 'error'); }
  }

  const CLEANUP_KIND_LABELS = {subtitle: 'phụ đề cháy sẵn', logo: 'logo kênh', watermark: 'watermark', other: 'vết'};
  const CLEANUP_POSITION_LABELS = {
    bottom_center: 'dưới giữa', top_center: 'trên giữa', top_right: 'trên phải',
    top_left: 'trên trái', bottom_right: 'dưới phải', bottom_left: 'dưới trái', center: 'giữa khung',
  };

  function renderCleanupState(cleanups, segments) {
    const box = $('studioCleanupState');
    if (!box) return;
    const list = (cleanups || []).filter((item) => item && item.kind !== 'none');
    const turnedOff = (cleanups || []).some((item) => item && item.kind === 'none');
    if (turnedOff) {
      box.innerHTML = '<b>Đã tắt che.</b> Render sẽ giữ nguyên phụ đề và logo của bản gốc.';
      return;
    }
    if (!list.length) {
      box.innerHTML = '<b>Chưa đánh dấu.</b> Lúc render app sẽ tự đo trên video gốc và che phần tìm được.';
      return;
    }
    box.innerHTML = list.map((item) =>
      `Đang che <b>${esc(CLEANUP_KIND_LABELS[item.kind] || 'vết')} · ${esc(CLEANUP_POSITION_LABELS[item.position] || item.position)}</b>`
      + ` bằng ${item.method === 'crop' ? 'cắt bỏ' : 'làm mờ'}`
      + (item.source === 'detected' ? ' (app tự dò từ video gốc)' : '')
    ).join(' · ') + (segments ? ` — áp cho ${segments} cảnh. Cần render lại để thấy kết quả.` : '');
  }

  async function loadAutomationStatus(quiet = false) {
    const projectId = Number(state.automationProjectId || 0);
    if (!projectId) return;
    try {
      const data = await api(`/api/automation/projects/${projectId}`);
      state.automationStatus = data;
      renderAutomationApprovals(data);
      renderAutomationStatus(data);
      renderAutomationTrace(data);
      if ($('automationRefreshButton')) $('automationRefreshButton').disabled = false;
    } catch (error) {
      if (!quiet && $('automationSummary')) $('automationSummary').textContent = `Không tải được pipeline: ${error.message}`;
    }
  }

  async function startAutomationPipeline() {
    const goal = $('automationGoal')?.value.trim() || '';
    if (goal.length < 10) return setMessage('Hãy viết yêu cầu cấp cao tối thiểu 10 ký tự.', 'error');
    const button = $('automationStartButton');
    if (button) button.disabled = true;
    if ($('automationStateTag')) $('automationStateTag').textContent = 'ĐANG XẾP TASK';
    try {
      const result = await api('/api/automation/pipelines', {
        method: 'POST',
        body: JSON.stringify({
          goal,
          title: $('automationTitle')?.value.trim() || '',
          language: 'vi',
          auto_generate_media: Boolean($('automationGenerateMedia')?.checked),
          auto_render: Boolean($('automationAutoRender')?.checked),
        }),
      });
      state.automationProjectId = Number(result.project.id);
      try { localStorage.setItem('ytFactory.automationProjectId', String(state.automationProjectId)); } catch (_) {}
      if ($('automationRefreshButton')) $('automationRefreshButton').disabled = false;
      setMessage(`Đã giao Research task cho dự án #${state.automationProjectId}.`, 'success');
      await loadAutomationProjectList();
      await loadAutomationStatus();
    } catch (error) {
      if ($('automationSummary')) $('automationSummary').textContent = `Không khởi động được: ${error.message}`;
      setMessage(`Auto pipeline lỗi: ${error.message}`, 'error');
    } finally {
      if (button) button.disabled = false;
    }
  }

  try {
    state.automationProjectId = Number(localStorage.getItem('ytFactory.automationProjectId') || 0) || null;
    if (state.automationProjectId && $('automationRefreshButton')) $('automationRefreshButton').disabled = false;
  } catch (_) {}

  function uiPreference(key, fallback = true) {
    try {
      const value = localStorage.getItem(`ytFactory.ui.${key}`);
      return value === null ? fallback : value === 'open';
    } catch (_) { return fallback; }
  }

  function saveUiPreference(key, open) {
    try { localStorage.setItem(`ytFactory.ui.${key}`, open ? 'open' : 'closed'); } catch (_) {}
  }

  function setPanelVisual(panelId, open) {
    const panel = $(panelId);
    const tab = panel?.querySelector('.collapsible-tab');
    const chevron = $(`${panelId}PanelChevron`);
    if (!panel || !tab) return;
    panel.classList.toggle('is-collapsed', !open);
    tab.setAttribute('aria-expanded', String(open));
    if (chevron) chevron.textContent = open ? '⌃' : '⌄';
  }

  function togglePanel(panelId) {
    const panel = $(panelId);
    if (!panel) return;
    const open = panel.classList.contains('is-collapsed');
    setPanelVisual(panelId, open);
    saveUiPreference(`panel.${panelId}`, open);
  }

  function handlePanelKey(event, panelId) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      togglePanel(panelId);
    }
  }

  function restorePanel(panelId) {
    setPanelVisual(panelId, uiPreference(`panel.${panelId}`, true));
  }

  function setChannelGroupVisual(groupId, open) {
    const button = $(`${groupId}Toggle`);
    if (!button) return;
    document.querySelectorAll(`[data-channel-group="${groupId}"]`).forEach((row) => row.classList.toggle('is-collapsed', !open));
    button.setAttribute('aria-expanded', String(open));
    const chevron = button.querySelector('.group-tab-chevron');
    if (chevron) chevron.textContent = open ? '⌃' : '⌄';
  }

  function toggleChannelGroup(groupId) {
    const button = $(`${groupId}Toggle`);
    if (!button) return;
    const open = button.getAttribute('aria-expanded') !== 'true';
    setChannelGroupVisual(groupId, open);
    saveUiPreference(`channel-group.${groupId}`, open);
  }

  // FastAPI's `detail` is whatever the endpoint put there: usually a
  // sentence, sometimes an object - the publish gate answers with a list of
  // reasons, because "not ready" is never one sentence. Handed straight to
  // new Error(), an object stringifies to "[object Object]" and the reasons
  // vanish at the exact moment they matter.
  function apiErrorText(detail, status) {
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (Array.isArray(detail)) {
      const lines = detail.map((item) => apiErrorText(item, status)).filter(Boolean);
      if (lines.length) return lines.join(' · ');
    }
    if (detail && typeof detail === 'object') {
      const head = String(detail.message || detail.msg || '').trim();
      const reasons = (detail.blockers || detail.errors || [])
        .map((item) => String(item?.detail || item?.label || item?.msg || '').trim())
        .filter(Boolean);
      const text = [head, ...reasons].filter(Boolean).join(' · ');
      if (text) return text;
      try { return JSON.stringify(detail); } catch (_) { /* fall through */ }
    }
    return `HTTP ${status}`;
  }

  function apiError(data, response) {
    const error = new Error(apiErrorText(data?.detail, response.status));
    // The structured answer travels with the message so a caller that knows
    // how to render a checklist still can.
    error.detail = data?.detail;
    error.status = response.status;
    return error;
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {headers: {'Content-Type': 'application/json'}, ...options});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw apiError(data, response);
    return data;
  }

  const browserLeaseClientId = (() => {
    try {
      const key = 'ytFactory.browserClientId';
      const current = sessionStorage.getItem(key);
      if (current) return current;
      const created = (window.crypto?.randomUUID?.() || `tab-${Date.now()}-${Math.random().toString(36).slice(2)}`);
      sessionStorage.setItem(key, created);
      return created;
    } catch (_) {
      return `tab-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    }
  })();
  let browserLeaseTimer = null;

  function sendBrowserHeartbeat(status = 'online') {
    const body = JSON.stringify({client_id: browserLeaseClientId, status});
    if (status === 'offline' && navigator.sendBeacon) {
      const sent = navigator.sendBeacon('/api/browser/heartbeat', new Blob([body], {type: 'application/json'}));
      if (sent) return;
    }
    void fetch('/api/browser/heartbeat', {method: 'POST', headers: {'Content-Type': 'application/json'}, body, keepalive: status === 'offline'}).catch(() => {});
  }

  function startBrowserLease() {
    if (browserLeaseTimer) return;
    sendBrowserHeartbeat('online');
    browserLeaseTimer = window.setInterval(() => sendBrowserHeartbeat('online'), 10000);
    window.addEventListener('pagehide', () => sendBrowserHeartbeat('offline'), {once: true});
  }

  function statusTag(status) {
    const map = {ok: ['green', 'HOẠT ĐỘNG'], error: ['red', 'LỖI'], never: ['', 'SẴN SÀNG']};
    const [kind, label] = map[status] || ['', String(status || 'KHÔNG RÕ').toUpperCase()];
    return `<span class="tag ${kind}">${label}</span>`;
  }

  function analysisTag(video) {
    if (video.analysis_status === 'completed') return '<span class="tag green">HOÀN TẤT</span>';
    if (video.analysis_status === 'running') return '<span class="tag orange">ĐANG CHẠY</span>';
    if (video.analysis_status === 'error') return '<span class="tag red">LỖI</span>';
    return '<span class="tag">ĐANG CHỜ</span>';
  }

  function transcriptTag(video) {
    return video.has_transcript ? '<span class="tag green">CÓ TRANSCRIPT</span>' : '<span class="tag">CHƯA CÓ TRANSCRIPT</span>';
  }

  function projectStatusTag(status) {
    const map = {
      draft: ['orange', 'BẢN NHÁP'],
      script: ['cyan', 'ĐANG VIẾT'],
      review: ['orange', 'CHỜ DUYỆT'],
      approved: ['green', 'ĐÃ DUYỆT'],
      archived: ['', 'LƯU TRỮ'],
    };
    const [kind, label] = map[status] || ['', String(status || 'draft').toUpperCase()];
    return `<span class="tag ${kind}">${label}</span>`;
  }

  function scriptStatusTag(status) {
    const map = {
      draft: ['orange', 'BẢN NHÁP'],
      review: ['cyan', 'CHỜ DUYỆT'],
      approved: ['green', 'ĐÃ DUYỆT'],
    };
    const [kind, label] = map[status] || ['', String(status || 'missing').toUpperCase()];
    return `<span class="tag ${kind}">${label}</span>`;
  }

  function shotStatusTag(status) {
    const map = {
      planned: ['orange', 'KẾ HOẠCH'],
      // Set by the edit plan when a scene's line talks about something the
      // source footage never shows. The card below it already has the
      // controls to draw or attach one.
      needs_visual: ['red', 'THIẾU HÌNH'],
      ready: ['cyan', 'SẴN SÀNG'],
      done: ['green', 'XONG'],
    };
    const [kind, label] = map[status] || ['', String(status || 'planned').toUpperCase()];
    return `<span class="tag ${kind}">${label}</span>`;
  }

  function timelineStatusTag(status) {
    const map = {
      planned: ['orange', 'KẾ HOẠCH'],
      voice_ready: ['cyan', 'ĐÃ CÓ VOICE'],
      asset_ready: ['cyan', 'ĐÃ CÓ ASSET'],
      ready: ['green', 'SẴN SÀNG'],
      done: ['green', 'XONG'],
    };
    const [kind, label] = map[status] || ['', String(status || 'planned').toUpperCase()];
    return `<span class="tag ${kind}">${label}</span>`;
  }

  function productionJobStatusTag(status) {
    const map = {
      queued: ['orange', 'ĐANG CHỜ'],
      running: ['cyan', 'ĐANG CHẠY'],
      completed: ['green', 'HOÀN TẤT'],
      error: ['red', 'LỖI'],
      cancelled: ['red', 'ĐÃ HỦY'],
    };
    const [kind, label] = map[status] || ['', String(status || 'unknown').toUpperCase()];
    return `<span class="tag ${kind}">${label}</span>`;
  }

  function fileSize(bytes) {
    const value = Number(bytes || 0);
    if (!value) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
    return `${(value / Math.pow(1024, index)).toFixed(index ? 1 : 0)} ${units[index]}`;
  }

  function assetOptions(assets, types, currentPath) {
    const accepted = Array.isArray(types) ? types : [types];
    const options = assets.filter((asset) => accepted.includes(asset.asset_type)).map((asset) => `
      <option value="${asset.id}" ${asset.file_path === currentPath ? 'selected' : ''}>${esc(asset.original_name)} · ${fileSize(asset.file_size)}</option>`).join('');
    return `<option value="">Chọn asset local...</option>${options}`;
  }

  async function loadHealth() {
    const health = await api('/api/health');
    const status = $('apiStatus');
    status.className = `status-pill ${health.api_key_configured ? 'ok' : 'warn'}`;
    status.innerHTML = `<span class="dot"></span> ${health.api_key_configured ? 'API ĐÃ KẾT NỐI' : 'THIẾU API KEY'}`;
  }

  async function loadOAuthStatus() {
    state.oauth = await api('/api/oauth/youtube/status');
    const status = $('oauthStatus');
    const button = $('oauthConnectButton');
    if (!state.oauth.configured) {
      status.className = 'status-pill';
      status.innerHTML = '<span class="dot"></span> OAUTH CHƯA CẤU HÌNH';
      button.textContent = 'Kết nối YouTube OAuth';
    } else if (state.oauth.connected) {
      status.className = 'status-pill ok';
      status.innerHTML = '<span class="dot"></span> OAUTH ĐÃ KẾT NỐI';
      button.textContent = 'Ngắt kết nối OAuth';
    } else {
      status.className = 'status-pill warn';
      status.innerHTML = '<span class="dot"></span> OAUTH CHƯA KẾT NỐI';
      button.textContent = 'Kết nối YouTube OAuth';
    }
  }

  async function toggleOAuthConnection() {
    if (state.oauth?.connected) {
      try {
        await api('/api/oauth/youtube/disconnect', {method: 'POST'});
        await loadOAuthStatus();
        setMessage('Đã ngắt kết nối YouTube OAuth.', 'success');
      } catch (error) { setMessage(error.message, 'error'); }
      return;
    }
    if (!state.oauth?.configured) {
      document.getElementById('integrations')?.scrollIntoView({behavior: 'smooth', block: 'start'});
      setMessage('Hãy nhập Google OAuth Client ID và Client Secret trong mục Kết nối AI Cloud & App Local trước.', 'error');
      return;
    }
    window.open('/oauth/youtube/authorize', '_blank', 'noopener');
    setMessage('Đã mở tab xác thực Google. Sau khi đồng ý, quay lại đây và bấm Làm mới.', '');
  }

  async function saveYouTubeOAuthConfig() {
    const clientId = $('youtubeOAuthClientId')?.value || '';
    const clientSecret = $('youtubeOAuthClientSecret')?.value || '';
    const redirectUri = $('youtubeOAuthRedirectUri')?.value || '';
    if (!clientId && !clientSecret && !redirectUri) {
      setMessage('Hãy nhập Client ID, Client Secret hoặc Redirect URI.', 'error');
      return;
    }
    try {
      await api('/api/oauth/youtube/config', {method: 'POST', body: JSON.stringify({client_id: clientId || null, client_secret: clientSecret || null, redirect_uri: redirectUri || null})});
      await Promise.all([loadOAuthStatus(), loadIntegrations(), loadToolStatus()]);
      setMessage('Đã lưu cấu hình YouTube OAuth trên máy này.', 'success');
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function clearYouTubeOAuthConfig() {
    if (!confirm('Xóa Client ID, Client Secret và token YouTube khỏi máy?')) return;
    try {
      await api('/api/oauth/youtube/config', {method: 'POST', body: JSON.stringify({clear: true})});
      await Promise.all([loadOAuthStatus(), loadIntegrations(), loadToolStatus()]);
      setMessage('Đã xóa cấu hình YouTube OAuth.', 'success');
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function checkYouTubeChannels() {
    try {
      const response = await api('/api/oauth/youtube/channels');
      const channels = response.channels || [];
      setMessage(channels.length ? `OAuth đã thấy ${channels.length} kênh: ${channels.map((item) => item.title).join(', ')}` : 'OAuth đã kết nối nhưng tài khoản chưa trả về kênh YouTube.', channels.length ? 'success' : 'error');
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function loadSummary() {
    const summary = await api('/api/summary');
    $('channelsCount').textContent = number(summary.channels);
    $('enabledCount').textContent = number(summary.enabled_channels);
    $('videosCount').textContent = number(summary.videos);
    $('pendingCount').textContent = number(summary.pending_analysis);
    $('completedFoot').textContent = `${number(summary.completed_analysis)} ĐÃ HOÀN TẤT · ${number(summary.production_projects)} DỰ ÁN`;
  }

  async function loadToolStatus() {
    state.toolStatus = await api('/api/tool-status');
    const ready = state.toolStatus.filter((item) => item.ready).length;
    const configure = state.toolStatus.filter((item) => item.phase === 'configure').length;
    $('toolStatusSummary').textContent = `${ready}/${state.toolStatus.length} SẴN SÀNG · ${configure} CẦN CẤU HÌNH`;
    $('toolStatusBody').innerHTML = `<div class="tool-status-grid">${state.toolStatus.map((item) => `
      <div class="tool-status-card ${esc(item.phase)}">
        <div class="tool-status-title"><span>${esc(item.label)}</span><span class="tag ${item.ready ? 'green' : item.phase === 'configure' ? 'orange' : ''}">${item.ready ? 'SẴN SÀNG' : item.phase === 'configure' ? 'CẤU HÌNH' : 'KẾ HOẠCH'}</span></div>
        <div class="tool-status-detail">${esc(item.detail)}</div>
      </div>`).join('')}</div>`;
  }

  async function loadModelCatalog() {
    state.modelCatalog = await api('/api/model-catalog');
    const ready = state.modelCatalog.filter((item) => item.ready).length;
    $('modelCatalogSummary').textContent = `${ready}/${state.modelCatalog.length} SẴN SÀNG`;
    $('modelCatalogBody').innerHTML = `<div class="tool-status-grid">${state.modelCatalog.map((item) => `<div class="tool-status-card ${item.ready ? 'ready' : 'configure'}"><div class="tool-status-title"><span>${esc(item.stage)} · ${esc(item.provider)}</span><span class="tag ${item.ready ? 'green' : 'orange'}">${item.ready ? 'SẴN SÀNG' : 'CẤU HÌNH'}</span></div><div class="tool-status-detail">${esc(item.model)} · ${esc(item.mode)} · VRAM: ${esc(item.vram)}</div></div>`).join('')}</div>`;
  }

  async function createDatabaseBackup() {
    setMessage('Đang tạo bản sao lưu database...');
    try {
      const result = await api('/api/maintenance/database-backup', {method: 'POST'});
      setMessage(`Đã sao lưu SQLite (${number(result.bytes)} byte).`, 'success');
    } catch (error) { setMessage(`Không sao lưu được database: ${error.message}`, 'error'); }
  }

  async function pruneDatabaseBackups() {
    try {
      const inventory = await api('/api/maintenance/database-backups');
      if (inventory.count <= 14) {
        setMessage(`Hiện có ${inventory.count} backup; chưa cần dọn (giữ tối đa 14).`, 'success');
        return;
      }
      const removeCount = inventory.count - 14;
      if (!confirm(`Dọn ${removeCount} backup cũ nhất? 14 bản gần nhất sẽ được giữ lại.`)) return;
      const result = await api('/api/maintenance/database-backups/prune', {
        method: 'POST', body: JSON.stringify({keep: 14, confirmed: true}),
      });
      setMessage(`Đã dọn ${result.removed.length} backup cũ; còn ${result.count} bản.`, 'success');
    } catch (error) { setMessage(`Không dọn được backup: ${error.message}`, 'error'); }
  }

  function integrationInputIds(provider) {
    return { key: `integrationKey-${provider}`, model: `integrationModel-${provider}` };
  }

  const INTEGRATION_GROUPS = [
    ['api_key', 'Nhập API key', 'Chỉ cần khi bạn muốn dùng dịch vụ tính phí theo lần gọi. Bỏ trống cũng không sao.'],
    ['login', 'Đăng nhập một lần', 'Các gói bạn đã trả tiền. Đăng nhập xong thì app dùng lại mãi.'],
    ['worker', 'Cần đang mở hoặc đang chạy', 'Phải bật lúc tạo media, không phải bật một lần rồi thôi.'],
    ['builtin', 'Có sẵn trên máy', 'Không cần làm gì.'],
  ];

  function renderIntegrationGroups(items) {
    const list = items || [];
    const missing = list.filter((item) => !item.ready);
    // A group with nothing outstanding starts folded: the point of the panel
    // is what still needs doing, not an inventory of what already works.
    const sections = INTEGRATION_GROUPS.map(([group, name, why]) => {
      const rows = list.filter((item) => (item.group || 'builtin') === group);
      if (!rows.length) return '';
      const pending = rows.filter((item) => !item.ready).length;
      const open = pending > 0 ? ' open' : '';
      const tag = pending
        ? `<span class="tag orange">${pending} chưa xong</span>`
        : '<span class="tag green">đủ</span>';
      return `<details class="integration-group"${open}>
        <summary><span class="integration-group-name">${esc(name)}</span>${tag}<span class="integration-group-why">${esc(why)}</span></summary>
        <div class="integration-group-body"><div class="integration-grid">${rows.map(renderIntegrationCard).join('')}</div></div>
      </details>`;
    }).join('');
    const todo = missing.length
      ? `<div class="integration-todo">Còn <b>${missing.length}</b> mục chưa sẵn sàng: ${missing.map((item) => esc(item.label)).join(' · ')}.<br>Chỉ cần làm những mục thuộc đường bạn định dùng — xem <b>Kho provider &amp; lý do khoá</b> để biết mục nào đang chặn việc tạo media.</div>`
      : '<div class="integration-todo">Mọi kết nối đều sẵn sàng.</div>';
    return todo + sections;
  }

  function renderIntegrationCard(item) {
    const cardClass = item.connection === 'handoff' ? 'handoff' : (item.ready ? 'connected' : '');
    const status = item.connection === 'handoff' ? 'HANDOFF' : (item.ready ? 'ĐÃ KẾT NỐI' : 'CHƯA CẤU HÌNH');
    if (item.connection === 'youtube_oauth') {
      return `<div class="integration-card ${cardClass}">
        <div class="tool-status-title"><span>${esc(item.label)}</span><span class="tag ${item.ready ? 'green' : item.configured ? 'cyan' : 'orange'}">${item.ready ? 'ĐÃ KẾT NỐI' : item.configured ? 'CHỜ CẤP QUYỀN' : 'CẦN CẤU HÌNH'}</span></div>
        <div class="secondary-text">${esc(item.category)} · ${esc(item.detail)}</div>
        <input id="youtubeOAuthClientId" type="text" autocomplete="off" placeholder="Google OAuth Client ID${item.client_id_hint ? ` · hiện tại ${esc(item.client_id_hint)}` : ''}" />
        <input id="youtubeOAuthClientSecret" type="password" autocomplete="new-password" placeholder="Google OAuth Client Secret mới (để trống nếu giữ nguyên)" />
        <input id="youtubeOAuthRedirectUri" type="url" value="${esc(item.redirect_uri || 'http://127.0.0.1:8787/oauth/youtube/callback')}" placeholder="Redirect URI" />
        <div class="secondary-text" style="margin-top:6px">Google Cloud Console phải khai báo đúng Redirect URI này. Upload thật dùng OAuth, không dùng API key.</div>
        <div class="queue-controls"><button class="btn small primary" type="button" onclick="saveYouTubeOAuthConfig()">Lưu cấu hình OAuth</button><button class="btn small ghost" type="button" onclick="toggleOAuthConnection()">${item.ready ? 'Ngắt kết nối' : 'Cấp quyền YouTube'}</button><button class="btn small ghost" type="button" onclick="checkYouTubeChannels()">Kiểm tra kênh</button><button class="btn small danger" type="button" onclick="clearYouTubeOAuthConfig()">Xóa cấu hình</button></div>
      </div>`;
    }
    if (item.connection === 'codex_cli') {
      return `<div class="integration-card ${item.ready ? 'connected' : ''}">
        <div class="tool-status-title"><span>${esc(item.label)}</span><span class="tag ${item.ready ? 'green' : 'orange'}">${item.ready ? 'ĐÃ ĐĂNG NHẬP' : 'CẦN ĐĂNG NHẬP'}</span></div>
        <div class="secondary-text">${esc(item.category)} · ${esc(item.detail)}</div>
        <div class="queue-controls">${item.ready ? '<span class="tag green">Có thể chọn ở AI Writer</span>' : '<button class="btn small primary" type="button" onclick="beginCodexLogin()">Đăng nhập Codex</button>'}<button class="btn small ghost" type="button" onclick="reloadCodexStatus()">Kiểm tra lại</button></div>
      </div>`;
    }
    if (item.connection === 'claude_code_cli') {
      return `<div class="integration-card ${item.ready ? 'connected' : ''}">
        <div class="tool-status-title"><span>${esc(item.label)}</span><span class="tag ${item.ready ? 'green' : 'orange'}">${item.ready ? 'ĐÃ ĐĂNG NHẬP' : 'CẦN ĐĂNG NHẬP'}</span></div>
        <div class="secondary-text">${esc(item.category)} · ${esc(item.detail)}</div>
        ${item.ready ? '' : '<div class="secondary-text" style="margin-top:6px">Dùng chung tài khoản với Claude Code bạn đang dùng hàng ngày. Nếu chưa đăng nhập, chạy <code>DANG_NHAP_CLAUDE_CODE.bat</code> trong thư mục gốc app.</div>'}
        <div class="queue-controls"><button class="btn small ghost" type="button" onclick="reloadClaudeCodeStatus()">Kiểm tra lại</button></div>
      </div>`;
    }
    if (item.connection === 'antigravity_cli') {
      return `<div class="integration-card ${item.ready ? 'connected' : ''}">
        <div class="tool-status-title"><span>${esc(item.label)}</span><span class="tag ${item.ready ? 'green' : 'orange'}">${item.ready ? 'ĐÃ ĐĂNG NHẬP' : 'CẦN ĐĂNG NHẬP'}</span></div>
        <div class="secondary-text">${esc(item.category)} · ${esc(item.detail)}</div>
        ${item.ready ? '' : '<div class="secondary-text" style="margin-top:6px">Mở app Antigravity và đăng nhập tài khoản Google một lần.</div>'}
        <div class="queue-controls"><button class="btn small ghost" type="button" onclick="reloadIntegrationsAndTools()">Kiểm tra lại</button></div>
      </div>`;
    }
    if (item.connection === 'browser_extension' || item.connection === 'sidecar') {
      // These two cannot be switched on from here: one needs a browser window
      // left open, the other a worker started outside the app. Saying so
      // plainly beats a button that would only ever fail.
      const stateLabel = item.ready ? 'ĐANG KẾT NỐI' : 'CHƯA KẾT NỐI';
      return `<div class="integration-card ${item.ready ? 'connected' : ''}">
        <div class="tool-status-title"><span>${esc(item.label)}</span><span class="tag ${item.ready ? 'green' : 'orange'}">${stateLabel}</span></div>
        <div class="secondary-text">${esc(item.category)}</div>
        <div class="secondary-text" style="margin-top:4px">Cấp nguồn cho: ${esc(item.model)}</div>
        <div class="secondary-text" style="margin-top:6px">${esc(item.detail)}</div>
        <div class="queue-controls"><button class="btn small ghost" type="button" onclick="reloadIntegrationsAndTools()">Kiểm tra lại</button></div>
      </div>`;
    }
    if (item.connection === 'cloud_subscription' && item.key === 'gflow_cli') {
      const stateLabel = item.ready ? 'ĐÃ ĐĂNG NHẬP' : item.installed ? 'CẦN ĐĂNG NHẬP' : 'CHƯA CÀI CLI';
      return `<div class="integration-card ${item.ready ? 'connected' : ''}">
        <div class="tool-status-title"><span>${esc(item.label)}</span><span class="tag ${item.ready ? 'green' : 'orange'}">${stateLabel}</span></div>
        <div class="secondary-text">${esc(item.category)} · profile ${esc(item.profile || 'default')} ${item.version ? `· ${esc(item.version)}` : ''}</div>
        <div class="secondary-text" style="margin-top:6px">${esc(item.detail)}</div>
        <div class="queue-controls">${item.ready ? '<span class="tag green">Sẵn sàng tạo video</span>' : item.installed ? '<button class="btn small primary" type="button" onclick="beginGFlowLogin()">Đăng nhập Google Flow</button>' : ''}<button class="btn small ghost" type="button" onclick="reloadGFlowStatus()">Kiểm tra lại</button></div>
      </div>`;
    }
    if (item.connection === 'handoff') {
      return `<div class="integration-card ${cardClass}">
        <div class="tool-status-title"><span>${esc(item.label)}</span><span class="tag cyan">${status}</span></div>
        <div class="secondary-text">${esc(item.category)} · ${esc(item.detail)}</div>
        <div class="queue-controls"><a class="btn small ghost" href="#projects">Mở dự án để xuất JSON</a></div>
      </div>`;
    }
    if (item.connection === 'local_engine') {
      return `<div class="integration-card ${cardClass}">
        <div class="tool-status-title"><span>${esc(item.label)}</span><span class="tag ${item.ready ? 'green' : 'orange'}">${item.ready ? 'SẴN SÀNG' : 'CHƯA SẴN SÀNG'}</span></div>
        <div class="secondary-text">${esc(item.category)} · Runtime: ${esc(item.model || '—')}</div>
        <div class="secondary-text" style="margin-top:6px">${esc(item.detail)}</div>
        <div class="queue-controls"><button class="btn small ghost" type="button" onclick="setWorkspace('production')">Mở danh sách dự án</button><button class="btn small ghost" type="button" onclick="refresh()">Kiểm tra lại</button></div>
      </div>`;
    }
    const ids = integrationInputIds(item.key);
    const keyLabel = item.key === 'runway' ? 'Runway API secret' : 'API key';
    return `<div class="integration-card ${cardClass}">
      <div class="tool-status-title"><span>${esc(item.label)}</span><span class="tag ${item.ready ? 'green' : 'orange'}">${status}</span></div>
      <div class="secondary-text">${esc(item.category)} · ${esc(item.detail)}</div>
      <input id="${ids.key}" type="password" autocomplete="off" placeholder="${keyLabel} mới (để trống nếu giữ nguyên)" />
      <input id="${ids.model}" type="text" value="${esc(item.model || '')}" placeholder="Model" />
      <div class="queue-controls"><button class="btn small primary" type="button" onclick="saveIntegration('${item.key}')">Lưu & bật</button><button class="btn small ghost" type="button" onclick="clearIntegrationKey('${item.key}')">Xóa key</button></div>
    </div>`;
  }

  async function loadIntegrations() {
    state.integrations = await api('/api/integrations');
    const connected = state.integrations.filter((item) => item.connection === 'api_key' && item.ready).length;
    const cloud = state.integrations.filter((item) => item.connection === 'api_key').length;
    $('integrationSummary').textContent = `${connected}/${cloud} AI CLOUD ĐÃ KẾT NỐI`;
    $('integrationBody').innerHTML = renderIntegrationGroups(state.integrations);
    updateStudioSceneGenerationAvailability();
  }

  async function saveIntegration(provider) {
    const ids = integrationInputIds(provider);
    const apiKey = $(ids.key)?.value || '';
    const model = $(ids.model)?.value || '';
    if (!apiKey && !model) { setMessage('Hãy nhập API key hoặc model trước khi lưu.', 'error'); return; }
    setMessage(`Đang lưu cấu hình ${provider} trên máy cục bộ...`);
    try {
      const response = await api('/api/integrations', { method: 'POST', body: JSON.stringify({provider, api_key: apiKey || null, model: model || null}) });
      setMessage(`${response.integration.label} đã được cấu hình.`, 'success');
      await Promise.all([loadIntegrations(), loadToolStatus(), loadModelCatalog(), loadAnalysisProviders()]);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function clearIntegrationKey(provider) {
    if (!confirm('Xóa API key này khỏi file .env trên máy?')) return;
    try {
      await api('/api/integrations', { method: 'POST', body: JSON.stringify({provider, clear_api_key: true}) });
      setMessage('Đã xóa API key khỏi cấu hình local.', 'success');
      await Promise.all([loadIntegrations(), loadToolStatus(), loadModelCatalog(), loadAnalysisProviders()]);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function beginCodexLogin() {
    setMessage('Đang mở cửa sổ Codex để đăng nhập...');
    try {
      const response = await api('/api/integrations/codex/login', {method: 'POST'});
      setMessage(response.integration.detail, 'success');
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function reloadCodexStatus() {
    try {
      await Promise.all([loadIntegrations(), loadToolStatus(), loadModelCatalog(), loadAnalysisProviders()]);
      setMessage('Đã kiểm tra lại trạng thái Codex CLI.', 'success');
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function reloadClaudeCodeStatus() {
    try {
      await Promise.all([loadIntegrations(), loadToolStatus(), loadOrchestratorSettings(), loadAutomationPolicy(), loadProviderCatalog(), loadAutomationProjectList()]);
      setMessage('Đã kiểm tra lại trạng thái Claude Code CLI.', 'success');
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function beginGFlowLogin() {
    setMessage('Đang mở Chrome để đăng nhập Google Flow...');
    try {
      const response = await api('/api/integrations/gflow/login', {method: 'POST'});
      setMessage(response.integration.detail, 'success');
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function reloadGFlowStatus() {
    try {
      const response = await api('/api/integrations/gflow/status', {method: 'POST'});
      await Promise.all([loadIntegrations(), loadToolStatus(), loadModelCatalog()]);
      setMessage(response.integration.logged_in ? 'Google Flow đã đăng nhập và sẵn sàng.' : response.integration.detail, response.integration.logged_in ? 'success' : 'error');
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function reloadIntegrationsAndTools() {
    try {
      await Promise.all([loadIntegrations(), loadToolStatus(), loadAnalysisProviders()]);
      setMessage('Đã kiểm tra lại trạng thái.', 'success');
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function loadOrchestratorSettings() {
    const data = await api('/api/settings/orchestrator');
    const select = $('orchestratorProviderSelect');
    if (select) select.value = data.provider;
    const hint = $('orchestratorProviderHint');
    if (hint) {
      const codex = data.options.find((item) => item.key === 'codex_cli');
      const claude = data.options.find((item) => item.key === 'claude_code_cli');
      const antigravity = data.options.find((item) => item.key === 'antigravity');
      hint.innerHTML = `Codex: ${codex?.logged_in ? '<span class="tag green">đã đăng nhập</span>' : '<span class="tag orange">chưa đăng nhập</span>'} · Claude: ${claude?.logged_in ? '<span class="tag green">đã đăng nhập</span>' : '<span class="tag orange">chưa đăng nhập</span>'} · Antigravity: ${antigravity?.logged_in ? '<span class="tag green">đã đăng nhập</span>' : '<span class="tag orange">chưa đăng nhập</span>'}`;
    }
    await loadAgentAssignments();
  }

  const POLICY_NUMBER_FIELDS = {
    policyMaxAttempts: 'max_attempts',
    policyMinReviewScore: 'min_review_score',
    policyMinSceneQcScore: 'min_scene_qc_score',
    policyMaxProjectCost: 'max_project_cost',
    policyMaxDailyCost: 'max_daily_cost',
  };
  const POLICY_FLAG_FIELDS = {
    policyAllowPaidApis: 'allow_paid_apis',
    policyAllowSubscriptionMedia: 'allow_subscription_media',
    policyPauseOnExhaustion: 'pause_on_provider_exhaustion',
    policyAutoGenerateMedia: 'auto_generate_media',
    policyAutoRender: 'auto_render',
  };

  async function loadAutomationPolicy() {
    const tag = $('automationPolicyTag');
    try {
      const data = await api('/api/settings/automation-policy');
      const policy = data.policy || {};
      const rules = $('policyGlobalRules');
      if (rules) rules.value = policy.global_rules || '';
      Object.entries(POLICY_NUMBER_FIELDS).forEach(([id, key]) => {
        const field = $(id);
        if (field) field.value = Number(policy[key] ?? 0);
      });
      Object.entries(POLICY_FLAG_FIELDS).forEach(([id, key]) => {
        const field = $(id);
        if (field) field.checked = Boolean(policy[key]);
      });
      const ceilings = [];
      if (Number(policy.max_project_cost) > 0) ceilings.push(`$${Number(policy.max_project_cost).toFixed(2)}/dự án`);
      if (Number(policy.max_daily_cost) > 0) ceilings.push(`$${Number(policy.max_daily_cost).toFixed(2)}/ngày`);
      const hint = $('automationPolicyHint');
      if (hint) {
        hint.textContent = ceilings.length
          ? `Trần chi phí đang áp: ${ceilings.join(' · ')}. Provider miễn phí hoặc đã trả theo gói không bị trần này chặn.`
          : 'Chưa đặt trần chi phí. Chỉ có khoá API trả phí đang bảo vệ bạn khỏi chi tiêu ngoài ý muốn.';
      }
      if (tag) { tag.className = 'tag green'; tag.textContent = 'ĐANG ÁP DỤNG'; }
    } catch (error) {
      if (tag) { tag.className = 'tag red'; tag.textContent = 'KHÔNG TẢI ĐƯỢC'; }
      setMessage(error.message, 'error');
    }
  }

  async function saveAutomationPolicy() {
    const body = {global_rules: $('policyGlobalRules')?.value || ''};
    Object.entries(POLICY_NUMBER_FIELDS).forEach(([id, key]) => {
      body[key] = Number($(id)?.value || 0);
    });
    Object.entries(POLICY_FLAG_FIELDS).forEach(([id, key]) => {
      body[key] = Boolean($(id)?.checked);
    });
    try {
      await api('/api/settings/automation-policy', {method: 'POST', body: JSON.stringify(body)});
      setMessage('Đã lưu quy tắc và hạn mức tự động.', 'success');
      await loadAutomationPolicy();
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function saveOrchestratorProvider() {
    const provider = $('orchestratorProviderSelect')?.value || 'codex_cli';
    try {
      await api('/api/settings/orchestrator', {method: 'POST', body: JSON.stringify({provider})});
      setMessage('Đã lưu AI điều phối chính.', 'success');
      await loadOrchestratorSettings();
    } catch (error) { setMessage(error.message, 'error'); }
  }

  const AGENT_STAGE_LABELS = {
    orchestration: 'Điều phối chính', script: 'Kịch bản', storyboard: 'Storyboard & kế hoạch',
    image_generation: 'Tạo ảnh', video_generation: 'Tạo video', quality_review: 'Nghiệm thu chất lượng',
  };
  const AGENT_LABELS = {codex_cli: 'Codex CLI', claude_code_cli: 'Claude Code CLI', antigravity: 'Google Antigravity'};

  function agentOptions(selected, includeAuto = false, disableAntigravity = false) {
    const auto = includeAuto ? `<option value="auto" ${selected === 'auto' ? 'selected' : ''}>Tự chọn AI khác executor</option>` : '';
    return auto + Object.entries(AGENT_LABELS).map(([key, label]) =>
      `<option value="${key}" ${selected === key ? 'selected' : ''} ${disableAntigravity && key === 'antigravity' ? 'disabled' : ''}>${label}</option>`
    ).join('');
  }

  async function loadAgentAssignments() {
    const target = $('agentAssignmentsBody');
    if (!target) return;
    try {
      const data = await api('/api/settings/agent-assignments');
      state.agentAssignments = data;
      target.innerHTML = (data.stages || []).map((stage) => {
        const item = data.assignments?.[stage] || {};
        const reviewerDisabled = stage === 'quality_review';
        const fallback = (item.fallback_agents || [])[0] || '';
        return `<div class="studio-actions" style="align-items:end;gap:8px;margin-bottom:8px;flex-wrap:wrap">
          <div class="studio-field" style="min-width:190px"><label>${esc(AGENT_STAGE_LABELS[stage] || stage)}</label><select id="agentMode-${stage}"><option value="fixed" ${item.mode === 'fixed' ? 'selected' : ''}>Khóa theo người dùng</option><option value="auto" ${item.mode === 'auto' ? 'selected' : ''}>AI điều phối tự chọn</option><option value="fallback" ${item.mode === 'fallback' ? 'selected' : ''}>Ưu tiên + dự phòng</option></select></div>
          <div class="studio-field" style="min-width:170px"><label>AI thực hiện</label><select id="agentExecutor-${stage}">${agentOptions(item.executor)}</select></div>
          <div class="studio-field" style="min-width:170px"><label>AI dự phòng</label><select id="agentFallback-${stage}"><option value="">Không đặt</option>${agentOptions(fallback)}</select></div>
          <div class="studio-field" style="min-width:190px"><label>AI nghiệm thu</label><select id="agentReviewer-${stage}">${agentOptions(item.reviewer || 'auto', true, reviewerDisabled)}</select></div>
        </div>`;
      }).join('');
    } catch (error) {
      target.innerHTML = `<div class="empty">Không tải được phân công AI: ${esc(error.message)}</div>`;
    }
  }

  async function saveAgentAssignments() {
    const stages = state.agentAssignments?.stages || Object.keys(AGENT_STAGE_LABELS);
    const assignments = {};
    stages.forEach((stage) => {
      const executor = $(`agentExecutor-${stage}`)?.value || 'codex_cli';
      const fallback = $(`agentFallback-${stage}`)?.value || '';
      assignments[stage] = {
        mode: $(`agentMode-${stage}`)?.value || 'auto', executor,
        allowed_agents: Object.keys(AGENT_LABELS),
        fallback_agents: fallback && fallback !== executor ? [fallback] : [],
        reviewer: $(`agentReviewer-${stage}`)?.value || 'auto',
      };
    });
    try {
      await api('/api/settings/agent-assignments', {method: 'POST', body: JSON.stringify({assignments})});
      setMessage('Đã lưu phân công AI theo công đoạn.', 'success');
      await loadAgentAssignments();
    } catch (error) { setMessage(`Không lưu được phân công AI: ${error.message}`, 'error'); }
  }

  async function loadAnalysisProviders() {
    const providers = await api('/api/analysis-providers');
    const providerLabel = (item) => ({local_metadata: 'Local · không cần API key', anthropic_claude: 'Claude · AI cloud', openai_gpt: 'GPT · AI cloud', codex_cli: 'Codex CLI · tài khoản đã đăng nhập', claude_code_cli: 'Claude Code CLI · tài khoản đã đăng nhập', antigravity: 'Antigravity · tài khoản đã đăng nhập'}[item.provider] || item.label || item.provider);
    const select = $('analysisProviderSelect');
    const selected = select.value;
    select.innerHTML = providers.map((item) => `<option value="${esc(item.provider)}" ${item.available ? '' : 'disabled'}>${esc(providerLabel(item))}${item.available ? '' : ' · chưa cấu hình'}</option>`).join('');
    if (providers.some((item) => item.provider === selected && item.available)) select.value = selected;
    const writerProviders = providers.filter((item) => item.provider !== 'local_metadata');
    ['studioAnalysisProviderSelect', 'studioWriterProviderSelect', 'studioChatProviderSelect'].forEach((id) => {
      const target = $(id);
      if (!target) return;
      const previous = target.value;
      const source = writerProviders;
      target.innerHTML = source.map((item) => `<option value="${esc(item.provider)}" ${item.available ? '' : 'disabled'}>${esc(providerLabel(item))}${item.available ? '' : ' · chưa cấu hình'}</option>`).join('');
      if (source.some((item) => item.provider === previous && item.available)) target.value = previous;
      else {
        const preferred = source.find((item) => item.provider === 'codex_cli' && item.available) || source.find((item) => item.available);
        if (preferred) target.value = preferred.provider;
      }
    });
  }

  function studioSelectedVideo() {
    return state.videoCatalog.find((video) => video.youtube_video_id === state.studioVideoId) || null;
  }

  function studioSourceIsAudio(video = studioSelectedVideo()) {
    const source = String(video?.local_media_path || video?.video_url || '').split('?')[0].toLowerCase();
    const extension = source.split('.').pop() || '';
    return AUDIO_SOURCE_EXTENSIONS.has(extension);
  }

  function normalizeStudioWorkflowForSource() {
    if (state.studioWorkflow !== 'reup' || !studioSourceIsAudio()) return false;
    // Audio has useful speech/content for analysis, but no frames to cut into
    // scenes. Apply this on restores as well as immediately after an upload.
    state.studioWorkflow = 'content';
    renderWorkflowsPanel();
    if (state.studioProjectId) {
      void api(`/api/projects/${state.studioProjectId}/workflow`, {
        method: 'PATCH', body: JSON.stringify({workflow: 'content'}),
      }).catch(() => {});
    }
    try { localStorage.setItem('ytFactory.workflow', 'content'); } catch (_) {}
    return true;
  }

  function populateStudioSourceChannelSelect() {
    const select = $('studioSourceChannelSelect');
    if (!select) return;
    const previous = state.studioSourceChannelId || select.value;
    select.innerHTML = state.channels.length
      ? state.channels.map((channel) => `<option value="${esc(channel.youtube_channel_id)}">${esc(channel.title || channel.youtube_channel_id)}</option>`).join('')
      : '<option value="">Chưa có kênh nguồn</option>';
    state.studioSourceChannelId = state.channels.some((channel) => channel.youtube_channel_id === previous)
      ? previous : (state.channels[0]?.youtube_channel_id || '');
    select.value = state.studioSourceChannelId;
  }

  function populateStudioVideoSelect() {
    const select = $('studioVideoSelect');
    if (!select) return;
    const previous = state.studioVideoId || select.value;
    const sourceVideos = state.videoCatalog.filter((video) => !state.studioSourceChannelId || video.youtube_channel_id === state.studioSourceChannelId);
    select.innerHTML = sourceVideos.length
      ? '<option value="">Chọn video của kênh</option>' + sourceVideos.map((video) => `<option value="${esc(video.youtube_video_id)}">${esc(video.title || video.youtube_video_id)}</option>`).join('')
      : '<option value="">Chưa có video trong thư viện</option>';
    if (sourceVideos.some((video) => video.youtube_video_id === previous)) {
      select.value = previous;
      state.studioVideoId = previous;
      renderStudioVideoPreview();
    }
  }

  function selectStudioSourceChannel() {
    state.studioSourceChannelId = $('studioSourceChannelSelect')?.value || '';
    state.studioVideoId = '';
    populateStudioVideoSelect();
    renderStudioVideoPreview();
    saveStudioSession();
  }

  function renderStudioVideoPreview() {
    const container = $('studioVideoPreview');
    const button = $('studioAnalyzeButton');
    const writerButton = $('studioWriteButton');
    const video = studioSelectedVideo();
    if (!container || !button) return;
    button.disabled = !video;
    if (writerButton && !state.scriptId) writerButton.disabled = !video;
    if (!video) { container.hidden = true; return; }
    container.hidden = false;
    const sourceDuration = Number(video.duration_seconds || 0);
    const durationLabel = sourceDuration ? ` · Video gốc: ${formatStudioDuration(sourceDuration)}` : '';
    container.innerHTML = `<img src="${esc(video.thumbnail_url || '')}" alt=""><div><div class="primary-text">${esc(video.title || video.youtube_video_id)}</div><div class="secondary-text">${esc(channelName(video.youtube_channel_id))} · ${date(video.published_at)}${durationLabel}</div><div class="secondary-text">${video.analysis_status === 'completed' ? 'Đã có phân tích trước đó' : 'Chưa phân tích'}</div></div>`;
  }

  function setStudioStep(step) {
    normalizeStudioWorkflowForSource();
    const next = Math.max(1, Math.min(7, Number(step) || 1));
    const flow = currentWorkflow();
    const labels = Object.fromEntries((flow.steps || []).map((label, index) => [index + 1, label.toUpperCase()]));
    state.studioStep = next;
    renderStudioShortWorkflowNote();
    if (next === 3 && $('studioScriptInstructionInput') && !$('studioScriptInstructionInput').value.trim()) $('studioScriptInstructionInput').value = $('studioCreativeDirectionInput')?.value || '';
    if (next === 3 && $('studioTargetDurationSeconds') && !$('studioTargetDurationSeconds').value.trim()) {
      const sourceDuration = Number(studioSelectedVideo()?.duration_seconds || 0);
      if (sourceDuration >= 30 && $('studioDurationHint')) $('studioDurationHint').textContent = `Để trống: AI sẽ bám gần thời lượng video gốc ${formatStudioDuration(sourceDuration)} (${sourceDuration} giây).`;
    }
    // The original panels were created in storyboard/voice order. Keep their
    // stable DOM ids while presenting the human workflow as voice then storyboard.
    const visiblePanelStep = next === 4 ? 5 : next === 5 ? 4 : next;
    // The publish step is reached after rendering, so the bundle loaded when
    // the project was opened no longer describes it: without this the panel
    // still says there is no video and offers nothing to publish.
    if (next === 7 && state.studioProjectId) void refreshStudioPublish(state.studioProjectId);
    document.querySelectorAll('[data-studio-step]').forEach((panel) => { panel.hidden = Number(panel.dataset.studioStep) !== visiblePanelStep; });
    document.querySelectorAll('[data-studio-tab]').forEach((tab) => {
      const value = Number(tab.dataset.studioTab);
      tab.classList.toggle('active', value === next);
      tab.classList.toggle('done', value < next);
      const label = tab.querySelector('strong');
      if (label && flow.steps?.[value - 1]) label.textContent = flow.steps[value - 1];
    });
    // Hang nao khong gan data-wf thi thuoc ca hai quy trinh.
    document.querySelectorAll('[data-wf]').forEach((row) => {
      row.hidden = row.dataset.wf !== state.studioWorkflow;
    });
    // Một file đã tải lên nằm sẵn trên máy, nên bước "tải video nguồn" không
    // còn việc gì để làm; để nguyên chỉ khiến người dùng tưởng mình bỏ sót.
    const downloadButton = $('studioDownloadSourceButton');
    if (downloadButton) {
      const alreadyLocal = studioSelectedVideo()?.media_status === 'downloaded_for_editing';
      downloadButton.hidden = alreadyLocal;
      const cut = $('studioCutByDialogueButton');
      const exported = $('studioCutSourceScenesButton');
      if (cut) cut.textContent = `${alreadyLocal ? 1 : 2}. Cắt cảnh theo lời thoại`;
      if (exported) exported.textContent = `${alreadyLocal ? 2 : 3}. Xuất clip từ video gốc`;
    }
    if ($('studioStatusTag')) $('studioStatusTag').textContent = labels[next] || 'TẠO VIDEO';
    if (next === 4) {
      syncStudioVoiceModelOptions();
      syncStudioSubtitleOptions();
      void hydrateStudioVoiceSettings();
    }
    saveStudioSession();
  }

  // Audio hangs off a timeline row, so anything that replaces the rows -
  // cutting by dialogue, rebuilding the storyboard - loses the link while the
  // files sit untouched on disk. Matching them back by the words they were
  // spoken from costs nothing and saves generating them all again.
  async function reattachStudioVoice(variant = 'long') {
    const projectId = Number(state.studioProjectId || state.projectId || 0);
    if (!projectId) return setMessage('Hãy mở một dự án trước.', 'error');
    setMessage('Đang tìm giọng đã tạo và gắn lại vào từng cảnh...', '');
    try {
      const result = await api(`/api/projects/${projectId}/timeline/reattach-voice`, {
        method: 'POST', body: JSON.stringify({video_variant: variant}),
      });
      if (!result.attached) {
        setMessage(
          result.library_size
            ? `Không cảnh nào khớp với ${result.library_size} file giọng đã có — lời trong storyboard đã khác.`
            : 'Chưa có file giọng nào để gắn lại.',
          'error');
      } else {
        setMessage(`Đã gắn lại giọng cho ${result.attached} cảnh.`
          + (result.missing.length ? ` Còn ${result.missing.length} cảnh chưa có giọng.` : ''),
          'success');
      }
      const bundle = await api(`/api/projects/${projectId}`);
      state.timeline = bundle.latest_timeline || [];
      state.narrationSource = bundle.narration_source || state.narrationSource;
      renderStudioStoryboard(bundle.latest_shots || [], state.timeline);
      await loadShortLane();
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function hydrateStudioVoiceSettings() {
    if (!state.studioProjectId || !$('studioVoiceReferenceAsset')) return;
    try {
      const [settings, assets] = await Promise.all([
        api(`/api/projects/${state.studioProjectId}/render-settings`),
        api(`/api/projects/${state.studioProjectId}/assets`),
      ]);
      const reference = $('studioVoiceReferenceAsset');
      const chosenReference = String(settings.voice_reference_asset_id || '');
      const audioAssets = (assets || []).filter((asset) => asset.asset_type === 'audio');
      state.studioVoiceAssets = audioAssets;
      reference.innerHTML = `<option value="">Chọn file giọng mẫu 10–20 giây</option>${audioAssets.map((asset) => `<option value="${asset.id}">${esc(asset.original_name || `Audio #${asset.id}`)}</option>`).join('')}`;
      reference.value = chosenReference;
      const projectSamples = $('studioVoiceProjectSamples');
      if (projectSamples) projectSamples.innerHTML = audioAssets.map((asset) => `<option value="asset:${asset.id}">${esc(asset.original_name || `Giọng đã tải #${asset.id}`)}</option>`).join('');
      const sampleList = $('studioUploadedVoiceSamples');
      if (sampleList) {
        sampleList.innerHTML = audioAssets.map((asset) => `
          <div class="storyboard-card" style="min-height:0"><div class="storyboard-card-head"><span class="storyboard-card-title">${esc(asset.original_name)}</span></div><div class="storyboard-body"><audio controls preload="metadata" src="/api/assets/${asset.id}/download"></audio><div class="queue-controls" style="justify-content:flex-start;margin-top:8px"><button class="btn small primary" onclick="selectStudioUploadedVoiceSample(${asset.id})">Chọn giọng này</button><button class="btn small ghost" onclick="renameStudioVoiceSample(${asset.id})">Đổi tên</button></div></div></div>`).join('') || '<div class="secondary-text">Chưa có file audio để dùng làm giọng mẫu.</div>';
      }
      if ($('studioVoiceProviderSelect')) $('studioVoiceProviderSelect').value = settings.voice_provider || $('studioVoiceProviderSelect').value;
      if ($('studioVoiceModelSelect')) {
        const modelSelect = $('studioVoiceModelSelect');
        const modelValue = settings.voice_provider === 'voxcpm' && chosenReference
          ? `asset:${chosenReference}`
          : (settings.voice_model || modelSelect.value);
        if (modelValue && ![...modelSelect.options].some((option) => option.value === modelValue)) {
          const option = document.createElement('option');
          option.value = modelValue;
          option.textContent = 'VoxCPM2 · preset đã chọn';
          modelSelect.appendChild(option);
        }
        modelSelect.value = modelValue;
      }
      if ($('studioVoiceRateSelect')) $('studioVoiceRateSelect').value = settings.voice_rate || $('studioVoiceRateSelect').value;
      if ($('studioVoicePromptText')) $('studioVoicePromptText').value = settings.voice_prompt_text || '';
      if ($('studioSubtitleModelSelect')) $('studioSubtitleModelSelect').value = settings.subtitle_model || 'timeline';
      syncStudioVoiceModelOptions();
      syncStudioSubtitleOptions();
      await refreshStudioVoicePreviews();
    } catch (_) {
      // The rest of the voice form remains usable if the project was just created.
    }
  }

  async function refreshStudioVoicePreviews() {
    const list = $('studioVoicePreviewList');
    if (!state.studioProjectId || !list) return;
    try {
      const previews = await api(`/api/projects/${state.studioProjectId}/voice-previews`);
      list.innerHTML = previews.filter((item) => item.ready).map((item) => `
        <div class="storyboard-card" style="min-height:0">
          <div class="storyboard-card-head"><span class="storyboard-card-title">${esc(item.label)}</span></div>
          <div class="storyboard-body"><audio controls preload="metadata" src="${item.url}"></audio><div class="queue-controls" style="justify-content:flex-start;margin-top:8px"><button class="btn small primary" onclick="selectStudioVoicePreview('${esc(item.key)}')">Chọn giọng này</button></div></div>
        </div>`).join('') || '<div class="secondary-text">Chưa tạo giọng thử. Bấm “Tạo & nghe thử 6 giọng”.</div>';
    } catch (_) {
      list.innerHTML = '<div class="secondary-text">Không tải được thư viện giọng thử.</div>';
    }
  }

  async function generateStudioVoicePreviews() {
    if (!state.studioProjectId) return setMessage('Hãy tạo project và kịch bản trước.', 'error');
    const button = $('studioGenerateVoicePreviewsButton');
    if (button) button.disabled = true;
    try {
      if ($('studioVoiceProviderSelect')) $('studioVoiceProviderSelect').value = 'voxcpm';
      setStudioProgress(10, 'Đang đưa 6 giọng VoxCPM vào GPU để nghe thử...');
      const response = await api(`/api/projects/${state.studioProjectId}/voice-previews`, {method: 'POST'});
      if (!response.job?.id) throw new Error('Không tạo được job giọng thử VoxCPM.');
      setMessage(`Đang tạo 6 giọng thử VoxCPM (job #${response.job.id})...`, 'success');
      for (let attempt = 0; attempt < 1200; attempt += 1) {
        const job = await api(`/api/jobs/${response.job.id}`);
        if (job.status === 'completed') {
          await refreshStudioVoicePreviews();
          setStudioProgress(100, 'Đã tạo xong 6 giọng để nghe thử.');
          setMessage('Đã tạo xong 6 preset Vox. Chọn preset trong ô Giọng/model voice rồi bấm Nghe thử.', 'success');
          return;
        }
        if (job.status === 'error' || job.status === 'cancelled') throw new Error(job.error || 'Tạo giọng thử không thành công.');
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
      throw new Error('Tạo giọng thử đang mất nhiều thời gian; bạn có thể quay lại bước này sau.');
    } catch (error) {
      setStudioProgress(0, `Tạo giọng thử thất bại: ${error.message}`, 'error');
      setMessage(error.message, 'error');
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function selectStudioVoicePreview(key) {
    if (!state.studioProjectId) return;
    try {
      setStudioProgress(35, 'Đang khóa preset giọng cho toàn bộ video...');
      const response = await api(`/api/projects/${state.studioProjectId}/voice-previews/${encodeURIComponent(key)}/select`, {method: 'POST'});
      await hydrateStudioVoiceSettings();
      if ($('studioVoiceProviderSelect')) $('studioVoiceProviderSelect').value = 'voxcpm';
      if ($('studioVoiceSummary')) $('studioVoiceSummary').innerHTML = `<div class="studio-check"><b>✓</b><span>Đã chọn ${esc(response.preset?.label || 'giọng VoxCPM')}. Giọng này được khóa làm reference cho mọi cảnh.</span></div>`;
      setStudioProgress(100, `Đã chọn ${response.preset?.label || 'giọng VoxCPM'}.`);
      saveStudioSession();
      setMessage('Đã khóa giọng đã chọn cho toàn bộ video. Bạn có thể tạo giọng đọc.', 'success');
    } catch (error) {
      setStudioProgress(0, `Không chọn được giọng: ${error.message}`, 'error');
      setMessage(error.message, 'error');
    }
  }

  async function selectStudioUploadedVoiceSample(assetId) {
    if (!state.studioProjectId || !$('studioVoiceReferenceAsset')) return;
    $('studioVoiceReferenceAsset').value = String(assetId);
    if ($('studioVoiceModelSelect')) $('studioVoiceModelSelect').value = `asset:${assetId}`;
    if ($('studioVoiceProviderSelect')) $('studioVoiceProviderSelect').value = 'voxcpm';
    try {
      setStudioProgress(40, 'Đang khóa giọng mẫu đã chọn cho mọi cảnh...');
      await saveRenderSettings(state.studioProjectId);
      if ($('studioVoiceSummary')) $('studioVoiceSummary').innerHTML = '<div class="studio-check"><b>✓</b><span>Đã chọn giọng mẫu này cho toàn bộ video VoxCPM.</span></div>';
      setStudioProgress(100, 'Đã lưu giọng mẫu cố định.');
      saveStudioSession();
      setMessage('Đã chọn giọng. VoxCPM sẽ dùng cùng một reference cho mọi cảnh.', 'success');
    } catch (error) {
      setStudioProgress(0, `Không chọn được giọng: ${error.message}`, 'error');
      setMessage(error.message, 'error');
    }
  }

  function syncStudioVoiceModelOptions() {
    const provider = $('studioVoiceProviderSelect')?.value || 'edge_tts';
    const select = $('studioVoiceModelSelect');
    if (!select) return;
    document.querySelectorAll('[data-voice-provider-panel]').forEach((panel) => {
      panel.hidden = panel.dataset.voiceProviderPanel !== provider;
    });
    const providerNote = $('studioVoiceProviderNote');
    if (providerNote) {
      providerNote.textContent = provider === 'voxcpm'
        ? 'VoxCPM2 tạo giọng theo preset hoặc file giọng mẫu, để mọi cảnh giữ cùng một người đọc.'
        : provider === 'pyvideotrans'
          ? 'pyVideoTrans chạy local GPU. Chỉ hiển thị các giọng tương thích với engine hiện tại.'
          : 'Edge TTS dùng giọng Microsoft Neural. Chọn giọng rồi bấm Nghe thử.';
    }
    [...select.querySelectorAll('optgroup')].forEach((group) => {
      const providers = group.dataset.voiceProviders || '';
      group.hidden = Boolean(providers) && !providers.split(/\s+/).includes(provider);
    });
    [...select.options].forEach((option) => {
      const providers = option.parentElement?.dataset?.voiceProviders || '';
      option.hidden = Boolean(providers) && !providers.split(/\s+/).includes(provider);
    });
    if (select.selectedOptions[0]?.hidden) {
      const available = [...select.options].find((option) => !option.hidden);
      if (available) select.value = available.value;
    }
  }

  function syncStudioSubtitleOptions() {
    const engineSelect = $('studioSubtitleModelSelect');
    const provider = $('studioSubtitleProviderSelect');
    if (!engineSelect || !provider) return;
    provider.value = engineSelect.value === 'timeline' ? 'timeline_text' : 'faster_whisper_local';
  }

  async function previewStudioSelectedVoice() {
    const choice = $('studioVoiceModelSelect')?.value || '';
    const provider = $('studioVoiceProviderSelect')?.value || 'edge_tts';
    if (choice.startsWith('library:')) {
      const key = choice.slice('library:'.length);
      const audio = new Audio(`/api/voice-library/${encodeURIComponent(key)}/audio`);
      audio.addEventListener('error', () => setMessage('Không tải được bản nghe thử của giọng này.', 'error'), {once: true});
      return audio.play().catch(() => setMessage('Trình duyệt đang chặn phát âm thanh. Hãy bấm nút Nghe thử một lần nữa.', 'error'));
    }
    if (choice.startsWith('preset:')) {
      if (!state.studioProjectId) return setMessage('Hãy tạo hoặc mở dự án trước khi nghe preset Vox.', 'error');
      const key = choice.slice('preset:'.length);
      const audio = new Audio(`/api/projects/${state.studioProjectId}/voice-previews/${encodeURIComponent(key)}/audio`);
      audio.addEventListener('error', () => setMessage('Preset này chưa được tạo. Bấm “Tạo 6 mẫu Vox” trước.', 'error'), {once: true});
      return audio.play().catch(() => setMessage('Preset này chưa được tạo. Bấm “Tạo 6 mẫu Vox” trước.', 'error'));
    }
    if (choice.startsWith('asset:')) {
      const assetId = choice.slice('asset:'.length);
      const audio = new Audio(`/api/assets/${encodeURIComponent(assetId)}/download`);
      audio.addEventListener('error', () => setMessage('Không tải được file giọng này.', 'error'), {once: true});
      return audio.play().catch(() => setMessage('Trình duyệt đang chặn phát âm thanh. Hãy bấm nút Nghe thử một lần nữa.', 'error'));
    }
    if (provider === 'edge_tts' || provider === 'pyvideotrans') {
      const button = document.querySelector('[onclick="previewStudioSelectedVoice()"]');
      if (button) button.disabled = true;
      try {
        setMessage('Đang tạo bản nghe thử bằng Edge TTS…');
        const rate = $('studioVoiceRateSelect')?.value || '+0%';
        const response = await fetch(`/api/voice-previews/edge/${encodeURIComponent(choice)}?rate=${encodeURIComponent(rate)}`);
        const data = response.ok ? null : await response.json().catch(() => ({}));
        if (!response.ok) throw apiError(data, response);
        const url = URL.createObjectURL(await response.blob());
        const audio = new Audio(url);
        audio.addEventListener('ended', () => URL.revokeObjectURL(url), {once: true});
        audio.addEventListener('error', () => { URL.revokeObjectURL(url); setMessage('Không phát được bản nghe thử.', 'error'); }, {once: true});
        await audio.play();
        setMessage('Đang phát bản nghe thử.', 'success');
      } catch (error) {
        setMessage(error.message, 'error');
      } finally {
        if (button) button.disabled = false;
      }
      return;
    }
    setMessage('Chọn một preset hoặc giọng mẫu VoxCPM2 để nghe thử.', 'info');
  }

  async function selectStudioSharedVoiceSample(key) {
    if (!state.studioProjectId) return setMessage('Hãy tạo hoặc mở một dự án trước.', 'error');
    try {
      setStudioProgress(35, 'Đang thêm giọng mẫu vào dự án và khóa cùng một giọng cho mọi cảnh...');
      const response = await api(`/api/projects/${state.studioProjectId}/voice-library/${encodeURIComponent(key)}/select`, {method: 'POST'});
      await hydrateStudioVoiceSettings();
      if ($('studioVoiceProviderSelect')) $('studioVoiceProviderSelect').value = 'voxcpm';
      if ($('studioVoiceSummary')) $('studioVoiceSummary').innerHTML = `<div class="studio-check"><b>✓</b><span>Đã chọn ${esc(response.label || 'giọng mẫu')} cho toàn bộ video. Bạn có thể bấm “Đổi tên” ở danh sách file bên dưới.</span></div>`;
      setStudioProgress(100, `Đã chọn ${response.label || 'giọng mẫu'}.`);
      saveStudioSession();
      setMessage('Đã thêm và chọn giọng mẫu cho dự án hiện tại.', 'success');
    } catch (error) {
      setStudioProgress(0, `Không chọn được giọng: ${error.message}`, 'error');
      setMessage(error.message, 'error');
    }
  }

  async function renameStudioVoiceSample(assetId) {
    const currentName = (state.studioVoiceAssets || []).find((asset) => Number(asset.id) === Number(assetId))?.original_name || '';
    const nextName = prompt('Tên hiển thị của giọng', currentName);
    if (nextName === null) return;
    const name = nextName.trim();
    if (!name) return setMessage('Tên giọng không được để trống.', 'error');
    try {
      await api(`/api/assets/${assetId}`, {method: 'PATCH', body: JSON.stringify({original_name: name})});
      await hydrateStudioVoiceSettings();
      setMessage(`Đã đổi tên giọng thành “${name}”.`, 'success');
    } catch (error) { setMessage(`Không đổi được tên giọng: ${error.message}`, 'error'); }
  }

  function renameCurrentStudioVoiceSample() {
    const assetId = Number($('studioVoiceReferenceAsset')?.value || 0);
    if (!assetId) return setMessage('Hãy chọn một giọng VoxCPM đã tải trước khi đổi tên.', 'error');
    void renameStudioVoiceSample(assetId);
  }

  async function selectStudioVideo(preferredProjectId = null) {
    state.studioVideoId = $('studioVideoSelect')?.value || '';
    state.scriptId = null;
    state.studioAnalysis = null;
    state.studioReference = null;
    state.studioWriter = null;
    state.studioProjectId = null;
    renderStudioVideoPreview();
    if ($('studioGenerateStoryboardButton')) $('studioGenerateStoryboardButton').disabled = true;
    if ($('studioOpenProjectButton')) $('studioOpenProjectButton').disabled = true;
    if ($('studioGenerateTimelineButton')) $('studioGenerateTimelineButton').disabled = true;
    if ($('studioQueueRenderButton')) $('studioQueueRenderButton').disabled = true;
    if ($('studioGenerateImagesButton')) $('studioGenerateImagesButton').disabled = true;
    $('studioOrchestrateButton')?.addEventListener('click', () => void runStudioOrchestrate());
    if ($('studioGenerateVideosButton')) $('studioGenerateVideosButton').disabled = true;
    if ($('studioProjectSummary')) $('studioProjectSummary').textContent = 'Chưa tạo';
    if ($('studioScriptSummary')) $('studioScriptSummary').textContent = 'Chưa có';
    if ($('studioShotSummary')) $('studioShotSummary').textContent = 'Chưa tạo';
    if ($('studioStoryboardResult')) $('studioStoryboardResult').innerHTML = '<div class="studio-empty">Sau khi có kịch bản, hãy tạo storyboard để chia nội dung thành các cảnh.</div>';
    if ($('studioFinalResult')) $('studioFinalResult').innerHTML = '<div class="studio-empty">Chưa có job render. Hãy quay lại bước 6 để dựng video.</div>';
    if (!state.studioVideoId) return;
    try {
      const existing = await api(`/api/videos/${encodeURIComponent(state.studioVideoId)}/reference-analysis`);
      if (existing?.status === 'completed' && existing.result) {
        state.studioAnalysis = existing;
        state.studioReference = existing;
        renderStudioAnalysis(existing);
      }
    } catch (_) {}
    await restoreStudioProgress(preferredProjectId);
    saveStudioSession();
  }

  async function restoreStudioProgress(preferredProjectId = null) {
    if (!state.studioVideoId) return;
    const existingProject = (preferredProjectId
      ? state.projects.find((item) => Number(item.id) === Number(preferredProjectId))
      : null) || state.projects.find((item) => item.youtube_video_id === state.studioVideoId);
    let nextStep = state.studioAnalysis?.result ? 2 : 1;
    if (!existingProject) {
      setStudioStep(nextStep);
      return;
    }
    try {
      const bundle = await api(`/api/projects/${existingProject.id}`);
      state.studioProjectId = existingProject.id;
      // Quy trinh thuoc ve du an, khong thuoc ve trinh duyet: mo lai mot du an
      // cu phai tra dung cac buoc ma no da duoc dung nen.
      const savedWorkflow = bundle.project?.workflow || existingProject.workflow;
      if (WORKFLOWS[savedWorkflow]) state.studioWorkflow = savedWorkflow;
      normalizeStudioWorkflowForSource();
      if ((bundle.reference_analysis || bundle.metadata_analysis)?.result) {
        state.studioAnalysis = bundle.reference_analysis || bundle.metadata_analysis;
        state.studioReference = bundle.reference_analysis || null;
        renderStudioAnalysis(state.studioAnalysis);
        nextStep = 2;
      }
      if (bundle.latest_script) {
        state.studioWriter = bundle.writer_content || state.studioWriter;
        state.scriptId = bundle.latest_script.id || null;
        renderStudioScript(bundle.latest_script, state.studioWriter);
        nextStep = 3;
      }
      // Outside that branch on purpose: the short is written from the source
      // material, not from the long script, so a project can hold a short
      // and no long script at all. Loading it only when a long script existed
      // hid the whole lane in exactly that case.
      loadShortLane();
      syncStudioLaneTabs();
      loadProjectLog();
      renderStudioPublish(bundle);
      if ((bundle.latest_shots || []).length) {
        state.shots = bundle.latest_shots || [];
        renderStudioStoryboard(bundle.latest_shots, bundle.latest_timeline || []);
        if ($('studioShotSummary')) $('studioShotSummary').textContent = `${bundle.latest_shots.length} cảnh`;
        if ($('studioOpenProjectButton')) $('studioOpenProjectButton').disabled = false;
        updateStudioSceneGenerationAvailability();
        nextStep = 4;
      }
      if ((bundle.latest_timeline || []).length) {
        if ($('studioGenerateTimelineButton')) $('studioGenerateTimelineButton').disabled = false;
        if ($('studioQueueRenderButton')) $('studioQueueRenderButton').disabled = false;
        nextStep = (bundle.latest_timeline || []).some((segment) => String(segment.audio_path || '').trim()) ? 5 : 4;
      }
      if (bundle.final_video?.available) nextStep = 7;
    } catch (_) {
      // The wizard remains usable even if a previous project was removed.
    }
    setStudioStep(nextStep);
    saveStudioSession();
  }

  async function restoreSavedStudioSession() {
    const saved = savedStudioSession();
    if (!saved) return;
    const savedProject = state.projects.find((item) => Number(item.id) === Number(saved.projectId));
    const videoId = saved.videoId || savedProject?.youtube_video_id;
    if (!videoId || !state.videoCatalog.some((item) => item.youtube_video_id === videoId)) return;
    state.studioSourceChannelId = saved.sourceChannelId || savedProject?.youtube_channel_id || '';
    state.studioVideoId = videoId;
    populateStudioSourceChannelSelect();
    populateStudioVideoSelect();
    if ($('studioVideoSelect')) $('studioVideoSelect').value = videoId;
    const fields = [
      ['studioCreativeDirectionInput', saved.creativeDirection],
      ['studioScriptInstructionInput', saved.scriptInstruction],
      ['studioTargetDurationSeconds', saved.targetDuration],
      ['studioRemakeModeSelect', saved.remakeMode],
      ['studioAnalysisLanguage', saved.analysisLanguage],
      ['studioScriptLanguage', saved.scriptLanguage],
      ['studioManagedChannelSelect', saved.managedChannelId],
      ['studioWriterProviderSelect', saved.writerProvider],
      ['studioVoiceProviderSelect', saved.voiceProvider],
      ['studioVoiceModelSelect', saved.voiceModel],
      ['studioVoiceRateSelect', saved.voiceRate],
      ['studioVoiceReferenceAsset', saved.voiceReferenceAsset],
      ['studioVoicePromptText', saved.voicePromptText],
    ];
    fields.forEach(([id, value]) => { if (value && $(id)) $(id).value = value; });
    if (typeof saved.createStandaloneShort === 'boolean' && $('studioCreateStandaloneShort')) $('studioCreateStandaloneShort').checked = saved.createStandaloneShort;
    if (saved.standaloneShortSeconds && $('studioInitialShortSeconds')) $('studioInitialShortSeconds').value = saved.standaloneShortSeconds;
    await selectStudioVideo(savedProject?.id || saved.projectId || null);
    const availableStep = state.studioStep;
    const savedStep = Number(saved.studioStep || 0);
    if (savedStep && savedStep <= availableStep) setStudioStep(savedStep);
  }
