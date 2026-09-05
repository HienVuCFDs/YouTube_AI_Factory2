// publish.js - publish gate, dialog, copyright, log
//
// Part of one page split into ordered files. These are classic
// scripts sharing a single global scope and running in document
// order, so this is a move rather than a rewrite: the files
// concatenated in order are byte for byte the block they came from,
// which is what the test asserts.
  async function refreshStudioPublish(projectId) {
    // openProjectDetail belongs to the other screen; from the wizard the panel
    // has to reload itself or a queued publication stays invisible. The short
    // lane comes with it, because the publish step now shows that video too.
    try { renderStudioPublish(await api(`/api/projects/${projectId}`)); }
    catch (_) { /* the message about the queued publication already landed */ }
    await loadShortLane();
  }

  // Each video has its own publish flow. They are different files of
  // different shapes going to different places - a 16:9 master cannot be a
  // Reel, and a 9:16 short is not a YouTube video - so one shared form with a
  // "which one" dropdown kept offering combinations that could not work.
  const PUBLISH_TARGETS = [
    {platform: 'youtube', label: 'YouTube', profiles: ['youtube_landscape', 'youtube_shorts']},
    {platform: 'tiktok', label: 'TikTok', profiles: ['tiktok']},
    {platform: 'facebook', label: 'Facebook', profiles: ['facebook_reels', 'facebook_feed']},
    {platform: 'instagram', label: 'Instagram', profiles: ['instagram_reels']},
  ];

  // Which shapes each rendered file can honestly claim to be. The server
  // measures the file and refuses a mismatch, so offering one here would only
  // produce a 400 after the user had filled the whole form in.
  //
  // Derived rather than listed: writing the list out by hand had already lost
  // Instagram from the short's destinations, which the server would have
  // accepted perfectly well. facebook_feed is in neither because it is 1:1 -
  // square fits neither the landscape master nor the vertical short.
  const VERTICAL_PUBLISH_PROFILES = ['youtube_shorts', 'instagram_reels', 'tiktok', 'facebook_reels'];
  const VARIANT_PROFILES = {
    long: ['youtube_landscape'],
    short: VERTICAL_PUBLISH_PROFILES,
  };

  function renderStudioPublish(bundle) {
    const box = $('studioPublishPanel');
    if (!box) return;
    const project = bundle?.project || {};
    if (!project.id) { box.innerHTML = ''; return; }
    state.publishBundle = bundle;
    renderCopyrightPanel();
    syncFinalVideoLink(bundle);
    const publications = bundle.publications || [];
    const thumbnailVariant = state.thumbnailVariant || 'long';
    const thumbnails = (bundle.thumbnails || []).filter((item) => (item.video_variant || 'long') === thumbnailVariant);
    const draft = state.thumbnailDrafts?.[`${project.id}:${thumbnailVariant}`] || {};
    const writer = (bundle.writer_content || {}).result || {};
    // The writer already produced titles, a description and hashtags for this
    // video. None of it used to reach here, so the form opened pre-filled with
    // the SOURCE video's title - the one thing that must not be reused.
    state.publishTitles = (writer.new_titles || []).map((item) => String(item || '').trim()).filter(Boolean);
    state.publishDescription = String(writer.new_description || '');
    state.publishHashtags = (writer.hashtags || []).join(', ');
    const thumbGrid = thumbnails.length
      ? thumbnails.map((item) => `<button type="button" class="studio-thumb${item.selected ? ' is-selected' : ''}"`
          + ` onclick="selectStudioThumbnail(${item.id}, ${project.id})" title="Chọn ảnh này">`
          + `<img loading="lazy" src="/api/assets/${item.asset_id}/download" style="aspect-ratio:${thumbnailVariant === 'short' ? '9/16' : '16/9'};height:${thumbnailVariant === 'short' ? '240px' : '110px'};width:auto;object-fit:contain" alt="thumbnail" /></button>`).join('')
      : '<div class="studio-empty">Chưa có ảnh bìa cho bản video này. Chọn cách tạo bên dưới.</div>';

    box.innerHTML = `<div class="studio-option-card"><b>Thumbnail</b>
      <select id="thumbnailVideoVariant" aria-label="Ảnh bìa cho video" onchange="setThumbnailVariant(this.value)"><option value="long" ${thumbnailVariant === 'long' ? 'selected' : ''}>Video dài · 16:9</option><option value="short" ${thumbnailVariant === 'short' ? 'selected' : ''}>Short / Reels · 9:16</option></select>
      <div class="studio-model-note" style="margin-top:4px">Ảnh bìa được lưu và chọn riêng cho từng bản. AI vẽ theo kịch bản đã chọn; thiết kế từ video thêm bố cục chữ, nền tương phản. Ảnh dọc giữ chữ trong vùng giữa để dễ xem trên điện thoại.</div>
      <div class="studio-actions" style="margin-top:8px;gap:6px;flex-wrap:wrap">
        <select id="thumbnailVariants" aria-label="Số ảnh"><option value="2">2 ảnh</option><option value="3" selected>3 ảnh</option><option value="5">5 ảnh</option></select>
        <select id="thumbnailProvider" aria-label="Model vẽ thumbnail">${THUMBNAIL_PROVIDER_OPTIONS}</select>
        <button class="btn primary" type="button" onclick="generateStudioThumbnails(${project.id}, 'ai')">AI vẽ thumbnail</button>
        <button class="btn" type="button" onclick="generateStudioThumbnails(${project.id}, 'designed')">Thiết kế bìa từ video</button>
        <button class="btn ghost" type="button" onclick="generateStudioThumbnails(${project.id}, 'frame')">Cắt khung từ video</button>
      </div>
      <div class="studio-field" style="margin-top:8px"><label for="thumbnailDirection">Gợi ý thêm cho AI (không bắt buộc)</label>
        <input id="thumbnailDirection" type="text" value="${esc(draft.prompt || '')}" oninput="saveThumbnailDraft()" placeholder="Ví dụ: cận mặt người đàn ông, rừng tuyết phía sau" /></div>
      <div class="studio-field" style="margin-top:8px"><label for="thumbnailTitleText">Chữ trên ảnh bìa · nên dùng 3–6 từ</label><input id="thumbnailTitleText" maxlength="120" value="${esc(draft.title || '')}" oninput="saveThumbnailDraft()" placeholder="Nhập hook ngắn; để trống khi chỉ cần hình" /></div>
      <div id="studioThumbnailGrid" style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">${thumbGrid}</div>
    </div>
    <div class="studio-option-card" style="margin-top:12px"><b>Các lần đăng</b>
      <div class="studio-model-note" style="margin-top:6px">${publisherWaitingNote(publications)}</div>
      <div style="margin-top:8px">${publications.length
        ? publications.map((item) => publicationRow(item, project)).join('')
        : '<div class="studio-empty">Chưa có lần đăng nào.</div>'}</div>
    </div>`;
    if (draft.provider) $('thumbnailProvider').value = draft.provider;
    if (draft.variants) $('thumbnailVariants').value = draft.variants;
  }

  function saveThumbnailDraft() {
    const projectId = state.publishBundle?.project?.id;
    if (!projectId) return;
    state.thumbnailDrafts ||= {};
    state.thumbnailDrafts[`${projectId}:${state.thumbnailVariant || 'long'}`] = {
      prompt: $('thumbnailDirection')?.value || '', title: $('thumbnailTitleText')?.value || '',
      provider: $('thumbnailProvider')?.value, variants: $('thumbnailVariants')?.value,
    };
  }

  function setThumbnailVariant(variant) {
    saveThumbnailDraft();
    state.thumbnailVariant = variant === 'short' ? 'short' : 'long';
    if (state.publishBundle) renderStudioPublish(state.publishBundle);
  }

  // The long video's link is static markup, so it needs filling in once the
  // bundle says the file exists - otherwise it points at "#" and does nothing.
  function syncFinalVideoLink(bundle) {
    const link = $('studioFinalDownload');
    if (!link) return;
    const project = bundle?.project || {};
    const available = Boolean(bundle?.final_video?.available);
    link.href = available ? (bundle.final_video.url || `/api/projects/${project.id}/final-video`) : '#';
    link.hidden = !available;
  }

  function publishChannelGroups() {
    const names = (state.managedChannels || [])
      .map((channel) => String(channel.group_name || '').trim())
      .filter(Boolean);
    return Array.from(new Set(names)).sort();
  }

  function publishChannelsFor(platform, group) {
    return (state.managedChannels || []).filter((channel) => {
      if (String(channel.platform || 'youtube').toLowerCase() !== platform) return false;
      if (!group) return true;
      return String(channel.group_name || '').trim() === group;
    });
  }

  // A destination is a channel, not just a platform: an account has several,
  // and they are grouped by topic. Offering the platform without saying which
  // channel of it would have published to whichever one happened to be first.
  function renderPublishTargets() {
    const variant = state.publishVariant || 'long';
    const isShort = variant === 'short';
    const allowed = VARIANT_PROFILES[variant] || [];
    const group = $('publishDialogGroup')?.value || '';
    const container = $('publishTargetList');
    if (!container) return;
    container.innerHTML = PUBLISH_TARGETS.map((target) => {
      const usable = target.profiles.filter((profile) => allowed.includes(profile));
      const channels = publishChannelsFor(target.platform, group);
      const wrongShape = !usable.length;
      const noChannel = !channels.length;
      const blocked = wrongShape || noChannel;
      const options = (wrongShape ? target.profiles : usable)
        .map((profile) => `<option value="${profile}">${esc(PUBLISH_PROFILE_LABELS[profile] || profile)}</option>`)
        .join('');
      const channelOptions = channels
        .map((channel) => {
          const linked = (state.channelAccounts || {})[channel.id];
          const mark = linked === true ? ' ✓' : linked === false ? ' (chưa đăng nhập)' : '';
          return `<option value="${channel.id}">${esc(channel.name)}`
            + `${channel.group_name ? ` · ${esc(channel.group_name)}` : ''}${mark}</option>`;
        })
        .join('');
      let note = '';
      if (wrongShape) {
        note = `Cần bản ${isShort ? '16:9' : 'dọc 9:16'} \u2014 dùng ${isShort ? 'video dài' : 'Short'} cho nền tảng này.`;
      } else if (noChannel) {
        note = group
          ? `Chưa có kênh ${esc(target.label)} trong nhóm \u201c${esc(group)}\u201d.`
          : `Chưa khai báo kênh ${esc(target.label)} trong Cài đặt.`;
      } else if (target.platform !== 'youtube') {
        note = 'Tạo gói để đăng tay';
      }
      return `<div class="publish-target${blocked ? ' is-blocked' : ''}">
        <label><input type="checkbox" class="publish-target-check" data-platform="${target.platform}"
          ${blocked ? 'disabled' : ''} ${!blocked && target.platform === 'youtube' ? 'checked' : ''} /> ${esc(target.label)}</label>
        <select class="publish-target-channel" data-platform="${target.platform}" ${blocked ? 'disabled' : ''}
          aria-label="Kênh ${esc(target.label)}">${channelOptions || '<option value="">\u2014</option>'}</select>
        <select class="publish-target-profile" data-platform="${target.platform}" ${blocked ? 'disabled' : ''}
          aria-label="Định dạng ${esc(target.label)}">${options}</select>
        ${target.platform === 'youtube' && !blocked
          ? '<button class="btn small ghost" type="button" onclick="connectChannelAccount()">Đăng nhập kênh này</button>'
          : ''}
        ${note ? `<span class="studio-model-note">${note}</span>` : ''}
      </div>`;
    }).join('');
  }

  async function saveSegmentCut(segmentId) {
    const start = $(`studioCutStart-${segmentId}`)?.value;
    const payload = {
      source_start_seconds: String(start ?? '').trim() === '' ? -1 : Number(start),
      edit_trim_head: Number($(`studioTrimHead-${segmentId}`)?.value || 0),
      edit_trim_tail: Number($(`studioTrimTail-${segmentId}`)?.value || 0),
      recut: true,
    };
    setMessage('Đang cắt lại cảnh này từ video gốc...', '');
    try {
      const result = await api(`/api/timeline/${segmentId}/cut`, {
        method: 'PATCH', body: JSON.stringify(payload),
      });
      if (result.recut_error) { setMessage(result.recut_error, 'error'); return; }
      setMessage('Đã cắt lại cảnh. Xem trước ngay bên trên.', 'success');
      // Redraw both lanes: the segment belongs to one of them and the caller
      // does not know which.
      const bundle = await api(`/api/projects/${state.studioProjectId}`);
      state.narrationSource = bundle.narration_source || state.narrationSource;
      renderStudioStoryboard(bundle.latest_shots || [], bundle.latest_timeline || []);
      await loadShortLane();
    } catch (error) { setMessage(error.message, 'error'); }
  }

  // Reviewing a short means hearing it end to end, not pressing play on each
  // scene. The scenes are separate files, so they are queued rather than
  // concatenated - no render, nothing written to disk.
  function playWholeShortVoice() {
    const lane = state.shortLane;
    const projectId = Number(state.studioProjectId || 0);
    const scenes = (lane?.timeline || []).filter((item) => String(item.audio_path || '').trim());
    if (!projectId || !scenes.length) return setMessage('Chưa có giọng đọc nào để nghe.', 'error');
    if (state.shortVoicePlayer) { state.shortVoicePlayer.pause(); state.shortVoicePlayer = null; }
    let index = 0;
    const player = new Audio();
    state.shortVoicePlayer = player;
    const box = $('studioShortPlayAllState');
    const step = () => {
      if (index >= scenes.length || state.shortVoicePlayer !== player) {
        if (box) box.textContent = 'Đã nghe hết bản Short.';
        state.shortVoicePlayer = null;
        return;
      }
      const scene = scenes[index];
      if (box) box.textContent = `Đang phát cảnh ${scene.segment_index}/${scenes.length}…`;
      player.src = `/api/projects/${projectId}/timeline/${scene.id}/audio-preview`;
      index += 1;
      player.play().catch(() => { if (box) box.textContent = 'Trình duyệt chặn tự phát — bấm lại.'; });
    };
    player.addEventListener('ended', step);
    player.addEventListener('error', step);
    step();
  }

  function stopWholeShortVoice() {
    if (state.shortVoicePlayer) { state.shortVoicePlayer.pause(); state.shortVoicePlayer = null; }
    const box = $('studioShortPlayAllState');
    if (box) box.textContent = 'Đã dừng.';
  }

  const RISK_LABELS = {low: 'RỦI RO THẤP', medium: 'CẦN XEM LẠI', high: 'RỦI RO CAO'};

  // Publishing is the last point where any of this can still be changed, so
  // the check sits here rather than earlier: before it, the numbers it rests
  // on - how many seconds came from the source, whether the marks were
  // covered - do not exist yet.
  function renderCopyrightPanel() {
    const box = $('studioCopyrightPanel');
    if (!box) return;
    const checks = state.copyrightChecks || {};
    const rows = ['long', 'short'].map((variant) => {
      const label = variant === 'short' ? 'Short' : 'Video dài';
      const result = checks[variant];
      if (!result) {
        return `<div class="risk-finding"><b>${label}</b> — chưa kiểm tra.
          <button class="btn small" type="button" onclick="runCopyrightCheck('${variant}')">Kiểm tra bản quyền</button></div>`;
      }
      const facts = result.facts || {};
      const findings = (result.findings || []).concat(
        (result.model_review?.findings || []).map((item) => ({...item, code: item.policy || 'policy'})));
      return `<div class="risk-finding sev-${esc(result.verdict)}">
        <b>${label}</b> <span class="risk-badge risk-${esc(result.verdict)}">${RISK_LABELS[result.verdict] || result.verdict}</span>
        <button class="btn small ghost" type="button" onclick="runCopyrightCheck('${variant}')">Kiểm lại</button>
        <div class="studio-model-note" style="margin-top:6px">
          Hình từ video gốc ${Math.round((facts.source_share || 0) * 100)}% ·
          lời trùng transcript ${Math.round((facts.narration_overlap || 0) * 100)}% ·
          ${facts.carries_source_audio ? 'còn tiếng gốc' : 'đã bỏ tiếng gốc'} ·
          che dấu ${(facts.source_scenes || 0) - (facts.scenes_with_marks_uncovered || 0)}/${facts.source_scenes || 0} cảnh
        </div>
        ${result.model_review?.summary ? `<div class="studio-model-note" style="margin-top:6px">${esc(result.model_review.summary)}</div>` : ''}
        ${findings.map((item) => `<div class="risk-finding sev-${esc(item.severity)}">
          ${esc(item.detail || '')}<br><small>→ ${esc(item.fix || '')}</small></div>`).join('')}
      </div>`;
    }).join('');
    box.innerHTML = `<div class="studio-option-card"><b>Kiểm tra bản quyền &amp; chính sách</b>
      <div class="studio-model-note" style="margin-top:4px">Đo phần còn lại của video gốc trong bản dựng — thời lượng hình đi mượn, tiếng gốc, dấu của kênh gốc, độ trùng lời — rồi đối chiếu chính sách nội dung dùng lại của YouTube.</div>
      <div style="margin-top:10px">${rows}</div></div>`;
  }

  async function runCopyrightCheck(variant) {
    const project = state.publishBundle?.project || {};
    if (!project.id) return setMessage('Hãy mở một dự án trước.', 'error');
    setMessage('Đang đo phần dùng lại từ video gốc...', '');
    try {
      const title = variant === 'short'
        ? String(state.shortLane?.script?.script_title || '')
        : String((state.publishTitles || [])[0] || '');
      const result = await api(`/api/projects/${project.id}/copyright-check`, {
        method: 'POST',
        body: JSON.stringify({video_variant: variant, use_model: true, publish_title: title}),
      });
      state.copyrightChecks = {...(state.copyrightChecks || {}), [variant]: result};
      renderCopyrightPanel();
      setMessage(`Kết quả: ${RISK_LABELS[result.verdict] || result.verdict}.`,
        result.verdict === 'high' ? 'error' : 'success');
    } catch (error) { setMessage(error.message, 'error'); }
  }

  // One account per channel, because a creator's channels are usually not
  // all on one Google account - and uploading with whichever account was
  // linked last puts the video on the wrong channel, which cannot be undone
  // from in here.
  async function loadChannelAccounts() {
    const channels = state.managedChannels || [];
    const linked = {};
    await Promise.all(channels.map(async (channel) => {
      if (String(channel.platform || 'youtube').toLowerCase() !== 'youtube') return;
      try {
        const status = await api(`/api/oauth/youtube/status?managed_channel_id=${channel.id}`);
        linked[channel.id] = Boolean(status.connected);
      } catch (_) { linked[channel.id] = false; }
    }));
    state.channelAccounts = linked;
    return linked;
  }

  function connectChannelAccount() {
    const selected = document.querySelector('.publish-target-channel[data-platform="youtube"]')?.value;
    if (!selected) return setMessage('Hãy chọn kênh trước.', 'error');
    window.open(`/oauth/youtube/authorize?managed_channel_id=${selected}`, '_blank', 'noopener');
    setMessage('Đã mở tab đăng nhập Google cho kênh này. Xong thì đóng và mở lại hộp thoại đăng.', '');
  }

  function openPublishDialog(variant) {
    const bundle = state.publishBundle;
    const project = bundle?.project || {};
    if (!project.id) return setMessage('Hãy mở một dự án trước.', 'error');
    const isShort = variant === 'short';
    if (isShort && !state.shortLane?.output_path) {
      return setMessage('Chưa dựng xong Short để đăng.', 'error');
    }
    if (!isShort && !bundle?.final_video?.available) {
      return setMessage('Chưa dựng xong video dài để đăng.', 'error');
    }
    state.publishVariant = variant;
    void loadChannelAccounts().then(() => renderPublishTargets());
    const defaultTitle = isShort
      ? String(state.shortLane?.script?.script_title || '')
      : String((state.publishTitles || [])[0] || '');
    const groups = publishChannelGroups();
    const projectGroup = (state.managedChannels || [])
      .find((channel) => Number(channel.id) === Number(project.managed_channel_id))?.group_name || '';

    $('publishDialogTitle').textContent = isShort ? 'Đăng Short' : 'Đăng video dài';
    $('publishDialogBody').innerHTML = `
      <div class="studio-field"><label for="publishDialogGroup">Nhóm thẻ kênh</label>
        <select id="publishDialogGroup" onchange="renderPublishTargets()">
          <option value="">Tất cả nhóm</option>
          ${groups.map((name) => `<option value="${esc(name)}" ${name === projectGroup ? 'selected' : ''}>${esc(name)}</option>`).join('')}
        </select></div>
      <b style="display:block;margin-top:12px;font-size:12px;letter-spacing:.06em;color:var(--muted)">NỀN TẢNG · KÊNH · ĐỊNH DẠNG</b>
      <div id="publishTargetList" style="margin-top:8px"></div>
      <div class="studio-actions" style="margin-top:10px;gap:6px;flex-wrap:wrap">
        <button class="btn small" type="button" onclick="loadPublishChecklist()">Kiểm tra điều kiện đăng</button>
        <button class="btn small ghost" type="button" onclick="loadPlatformCopy()">Soạn caption riêng từng nền tảng</button>
      </div>
      <div id="publishChecklistBox" style="margin-top:8px"></div>
      <div id="publishCopyBox" style="margin-top:8px"></div>
      ${state.publishTitles?.length && !isShort ? `<div class="studio-field" style="margin-top:12px"><label for="publishDialogTitlePick">Tiêu đề AI gợi ý</label>
        <select id="publishDialogTitlePick" onchange="useSuggestedTitle()"><option value="">\u2014 chọn một tiêu đề \u2014</option>
        ${state.publishTitles.map((title) => `<option value="${esc(title)}">${esc(title)}</option>`).join('')}</select></div>` : ''}
      <div class="studio-field" style="margin-top:8px"><label for="publishDialogTitleInput">Tiêu đề</label>
        <input id="publishDialogTitleInput" type="text" maxlength="100" value="${esc(defaultTitle)}"
          placeholder="Tiêu đề cho video này \u2014 không dùng lại tiêu đề video gốc" /></div>
      <div class="studio-field" style="margin-top:8px"><label for="publishDialogDescription">Mô tả</label>
        <textarea id="publishDialogDescription" rows="4">${esc(state.publishDescription || '')}</textarea></div>
      <div class="studio-field" style="margin-top:8px"><label for="publishDialogTags">Hashtag / tag</label>
        <input id="publishDialogTags" type="text" value="${esc(state.publishHashtags || '')}" /></div>
      <div class="studio-grid" style="margin-top:8px">
        <div class="studio-field"><label for="publishDialogPrivacy">Quyền riêng tư</label>
          <select id="publishDialogPrivacy"><option value="">Theo kênh</option><option value="private">Riêng tư</option><option value="unlisted">Không công khai</option><option value="public">Công khai</option></select></div>
        <div class="studio-field"><label for="publishDialogSchedule">Đăng lúc</label>
          <input id="publishDialogSchedule" type="datetime-local" /></div>
      </div>`;
    renderPublishTargets();
    $('publishDialogNote').textContent = 'Chỉ YouTube đăng tự động; nền tảng khác tạo gói để bạn tải MP4 rồi đăng tay.';
    $('publishDialog').showModal();
  }

  function useSuggestedTitle() {
    const picked = $('publishDialogTitlePick')?.value || '';
    if (picked && $('publishDialogTitleInput')) $('publishDialogTitleInput').value = picked;
  }

  const LOG_STATUS_LABELS = {
    completed: 'xong', error: 'lỗi', running: 'đang chạy', queued: 'chờ',
    cancelled: 'đã huỷ', approved: 'đã duyệt', draft: 'nháp', ready_manual: 'chờ đăng tay',
  };

  // Assembled from rows that already existed rather than kept in memory,
  // which is why reopening the app does not lose the thread.
  async function loadProjectLog() {
    const projectId = Number(state.studioProjectId || state.projectId || 0);
    const panel = $('studioLogPanel');
    if (panel) panel.hidden = !projectId;
    if (!projectId) return;
    try { renderProjectLog(await api(`/api/projects/${projectId}/log`)); }
    catch (_) { /* a project with no history yet is not an error */ }
  }

  function renderProjectLog(log) {
    const summary = log?.summary || {};
    const head = $('studioLogSummary');
    if (head) {
      const minutes = Math.round((summary.machine_seconds || 0) / 60);
      head.textContent = `${summary.steps || 0} bước · ${summary.failures || 0} lỗi · `
        + `${minutes} phút máy chạy`
        + (summary.cost_usd ? ` · $${summary.cost_usd}` : '')
        + ((summary.retried_steps || []).length ? ` · chạy lại: ${summary.retried_steps.join(', ')}` : '');
    }
    const body = $('studioLogBody');
    if (!body) return;
    const rows = (log?.entries || []).slice().reverse().map((entry) => {
      const took = entry.seconds ? `${entry.seconds}s` : '';
      const status = LOG_STATUS_LABELS[entry.status] || entry.status || '';
      return `<div class="log-row${entry.status === 'error' ? ' is-error' : ''}">
        <span class="log-when">${esc(String(entry.at || '').slice(0, 16).replace('T', ' '))}</span>
        <span class="log-stage">${esc(entry.stage || '')}</span>
        <span class="log-what">${esc(entry.label || '')}
          ${entry.attempt > 1 ? `<small>(lần ${entry.attempt})</small>` : ''}
          <small>· ${esc(status)}</small>
          ${entry.error ? `<br><small class="error-text">${esc(entry.error)}</small>` : ''}
          ${entry.detail ? `<br><small>${esc(entry.detail)}</small>` : ''}</span>
        <span class="log-took">${took}</span>
      </div>`;
    }).join('');
    body.innerHTML = rows || '<div class="studio-empty">Chưa có gì trong nhật ký.</div>';
  }

  const CHECK_MARKS = {pass: '✓', warn: '!', block: '✕'};

  // Every one of these was already knowable somewhere, and each was found
  // separately - usually after the upload. Gathering them means one answer
  // to "is this ready" instead of one refusal per attempt.
  async function loadPublishChecklist() {
    const project = state.publishBundle?.project || {};
    const variant = state.publishVariant || 'long';
    const first = document.querySelector('.publish-target-check:checked');
    const platform = first?.dataset.platform || 'youtube';
    const profile = document.querySelector(
      `.publish-target-profile[data-platform="${platform}"]`)?.value || 'youtube_landscape';
    const box = $('publishChecklistBox');
    if (box) box.innerHTML = '<div class="studio-model-note">Đang kiểm tra…</div>';
    try {
      const result = await api(`/api/projects/${project.id}/publish-checklist`, {
        method: 'POST',
        body: JSON.stringify({
          video_variant: variant, platform, output_profile: profile,
          title: $('publishDialogTitleInput')?.value || '',
          description: $('publishDialogDescription')?.value || '',
          tags: String($('publishDialogTags')?.value || '').split(',').map((i) => i.trim()).filter(Boolean),
          reuse_verdict: (state.copyrightChecks || {})[variant]?.verdict || '',
        }),
      });
      state.publishChecklist = result;
      renderPublishChecklist(result);
    } catch (error) {
      if (box) box.innerHTML = `<div class="error-text">${esc(error.message)}</div>`;
    }
  }

  function renderPublishChecklist(result) {
    const box = $('publishChecklistBox');
    if (!box) return;
    box.innerHTML = `<div class="risk-finding sev-${result.ready ? 'low' : 'high'}">
      <b>${result.ready ? 'Đủ điều kiện đăng' : 'Chưa đủ điều kiện đăng'}</b>
      ${(result.checks || []).map((item) => `<div class="studio-check">
        <b>${CHECK_MARKS[item.level] || '·'}</b><span>${esc(item.label)}
        ${item.detail ? `<br><small>${esc(item.detail)}</small>` : ''}
        ${item.level !== 'pass' && item.fix ? `<br><small>→ ${esc(item.fix)}</small>` : ''}</span></div>`).join('')}
    </div>`;
  }

  // Same substance everywhere, different shape: a YouTube description is read
  // in search, a TikTok caption is read over the video while it plays.
  async function loadPlatformCopy() {
    const project = state.publishBundle?.project || {};
    const chosen = Array.from(document.querySelectorAll('.publish-target-check:checked'))
      .map((box) => box.dataset.platform);
    const box = $('publishCopyBox');
    if (!chosen.length) { if (box) box.innerHTML = '<div class="studio-model-note">Hãy chọn nền tảng trước.</div>'; return; }
    try {
      const result = await api(`/api/projects/${project.id}/platform-copy`, {
        method: 'POST',
        body: JSON.stringify({
          video_variant: state.publishVariant || 'long',
          platforms: chosen,
          title: $('publishDialogTitleInput')?.value || '',
          description: $('publishDialogDescription')?.value || '',
          tags: String($('publishDialogTags')?.value || '').split(',').map((i) => i.trim()).filter(Boolean),
        }),
      });
      state.platformCopy = result.variants || {};
      if (box) {
        box.innerHTML = Object.entries(state.platformCopy).map(([platform, copy]) => `
          <div class="risk-finding"><b>${esc(platform)}</b>
            <div class="studio-field" style="margin-top:6px"><label>Tiêu đề (${copy.title.length}/${copy.limits.title})</label>
              <input id="publishCopyTitle-${platform}" type="text" value="${esc(copy.title)}" /></div>
            <div class="studio-field" style="margin-top:6px"><label>Caption</label>
              <textarea id="publishCopyDesc-${platform}" rows="3">${esc(copy.description)}</textarea></div>
          </div>`).join('');
      }
    } catch (error) {
      if (box) box.innerHTML = `<div class="error-text">${esc(error.message)}</div>`;
    }
  }

  async function submitPublishDialog() {
    const project = state.publishBundle?.project || {};
    const variant = state.publishVariant || 'long';
    const chosen = Array.from(document.querySelectorAll('.publish-target-check'))
      .filter((box) => box.checked)
      .map((box) => ({
        platform: box.dataset.platform,
        profile: document.querySelector(`.publish-target-profile[data-platform="${box.dataset.platform}"]`)?.value || '',
        channelId: Number(document.querySelector(
          `.publish-target-channel[data-platform="${box.dataset.platform}"]`)?.value || 0) || null,
      }));
    if (!chosen.length) return setMessage('Hãy chọn ít nhất một nền tảng.', 'error');
    // Not a block: it is the user's channel and their call. But an unchecked
    // or high-risk video must not go out because nobody mentioned it.
    const check = (state.copyrightChecks || {})[variant];
    if (!check) {
      if (!confirm('Chưa kiểm tra bản quyền cho bản này. Vẫn đăng?')) return;
    } else if (check.verdict === 'high') {
      const reasons = (check.findings || []).map((item) => `• ${item.detail}`).join('\n');
      if (!confirm(`Kiểm tra bản quyền: RỦI RO CAO\n\n${reasons}\n\nVẫn đăng?`)) return;
    }
    const scheduled = $('publishDialogSchedule')?.value || '';
    const payload = {
      confirmed: true,

      video_variant: variant,
      title: $('publishDialogTitleInput')?.value || '',
      description: $('publishDialogDescription')?.value || '',
      tags: String($('publishDialogTags')?.value || '').split(',').map((item) => item.trim()).filter(Boolean),
      privacy_status: $('publishDialogPrivacy')?.value || null,
      scheduled_at: scheduled ? new Date(scheduled).toISOString() : null,
      reuse_verdict: (state.copyrightChecks || {})[variant]?.verdict || '',
    };
    const done = [];
    const failed = [];
    for (const target of chosen) {
      try {
        await api(`/api/projects/${project.id}/publish`, {
          method: 'POST',
          body: JSON.stringify({
            ...payload,
            // Per-platform copy when it has been prepared: the same caption
            // everywhere is why a reup lands on one feed and vanishes on the rest.
            title: $(`publishCopyTitle-${target.platform}`)?.value || payload.title,
            description: $(`publishCopyDesc-${target.platform}`)?.value || payload.description,
            tags: (state.platformCopy || {})[target.platform]?.tags || payload.tags,
            platform: target.platform,
            output_profile: target.profile,
            // Each destination carries its own channel: one publish can go to
            // a YouTube channel and a TikTok account that are not the same
            // account at all.
            managed_channel_id: target.channelId,
          }),
        });
        done.push(target.platform);
      } catch (error) {
        // One platform failing must not lose the ones that worked. A gate
        // refusal carries the whole list, so it is shown as a list.
        let message = error.message;
        try {
          const parsed = JSON.parse(message);
          if (parsed?.blockers) {
            renderPublishChecklist({ready: false, checks: parsed.checks || parsed.blockers});
            message = `${parsed.message} ${parsed.blockers.map((item) => item.label).join(', ')}`;
          }
        } catch (_) { /* an ordinary error message, not a checklist */ }
        failed.push(`${target.platform}: ${message}`);
      }
    }
    $('publishDialog').close();
    if (done.length) setMessage(`Đã xếp hàng đăng: ${done.join(', ')}.`, failed.length ? '' : 'success');
    if (failed.length) setMessage(failed.join(' · '), 'error');
    await refreshStudioPublish(project.id);
  }

  // A frame lifted out of the video is whatever the camera was doing that
  // second - a blink, an empty wide shot. Useful, free, and not what makes
  // anyone click, so the composed one is the default and both are offered.
  const THUMBNAIL_PROVIDER_OPTIONS = [
    ['gemini_image', 'Gemini Image · API'],
    ['openai_image', 'OpenAI Image · API'],
    ['gflow_image', 'gFlow · gói thuê bao'],
  ].map(([key, label]) => `<option value="${key}">${label}</option>`).join('');

  async function generateStudioThumbnails(projectId, mode = 'ai') {
    if (state.thumbnailBusy) return;
    saveThumbnailDraft();
    state.thumbnailBusy = true;
    const variants = Number($('thumbnailVariants')?.value || 3);
    const provider = $('thumbnailProvider')?.value || 'gemini_image';
    setMessage(mode === 'ai'
      ? 'AI đang vẽ thumbnail theo câu chuyện của video...'
      : 'Đang cắt thumbnail từ video đã dựng...', '');
    try {
      await api(`/api/projects/${projectId}/thumbnails/generate`, {
        method: 'POST',
        body: JSON.stringify({
          variants, mode, provider,
          video_variant: state.thumbnailVariant || 'long',
          title_text: $('thumbnailTitleText')?.value || '',
          prompt: $('thumbnailDirection')?.value || '',
        }),
      });
      setMessage('Đã tạo thumbnail. Bấm vào một ảnh để chọn.', 'success');
      await refreshStudioPublish(projectId);
    } catch (error) { setMessage(error.message, 'error'); }
    finally { state.thumbnailBusy = false; }
  }

  async function selectStudioThumbnail(thumbnailId, projectId) {
    try {
      await api(`/api/thumbnails/${thumbnailId}/select`, {method: 'POST'});
      setMessage('Đã chọn thumbnail cho lần đăng này.', 'success');
      await refreshStudioPublish(projectId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  function publicationRow(item, project) {
    const platform = item.platform || 'youtube';
    const variant = item.video_variant === 'short' ? 'Short' : 'Video dài';
    const delivery = item.status === 'ready_manual' ? 'Sẵn sàng đăng thủ công' : item.status;
    const videoUrl = item.video_variant === 'short'
      ? `/api/projects/${project.id}/short-video` : `/api/projects/${project.id}/final-video`;
    return `<div class="job-row"><span class="job-dot ${item.status === 'completed' ? 'completed' : item.status === 'uploading' ? 'running' : ''}"></span>`
      + `<div class="job-main"><div class="job-title">${esc(platform)} · ${esc(variant)} · ${esc(delivery)}</div>`
      + `<div class="job-meta">${esc(item.output_profile || '')} · ${esc(item.scheduled_at || item.created_at || '')}`
      + `${item.youtube_video_id ? ` · ${esc(item.youtube_video_id)}` : ''}</div>`
      + `${item.error ? `<div class="error-text">${esc(item.error)}</div>` : ''}</div>`
      + `${item.status === 'ready_manual' ? `<a class="btn small ghost" href="/api/publications/${item.id}/manual-package" target="_blank" rel="noreferrer">Tải gói đăng</a>` : ''}`
      + `${['queued', 'ready_manual'].includes(item.status) ? `<button class="btn small danger" onclick="cancelPublication(${item.id}, ${project.id})">Hủy</button>` : ''}`
      + `${['error', 'cancelled'].includes(item.status) ? `<button class="btn small ghost" onclick="retryPublication(${item.id}, ${project.id})">Chạy lại</button>` : ''}</div>`;
  }

  async function queueProjectPublication(projectId) {
    const platform = $('publicationPlatform')?.value || 'youtube';
    const variant = $('publicationVariant')?.value || 'long';
    const verb = platform === 'youtube' ? 'đưa vào hàng đợi upload YouTube' : 'chuẩn bị gói đăng thủ công';
    if (!confirm(`${verb} cho ${variant === 'short' ? 'Short' : 'video dài'}?`)) return;
    try {
      const scheduledInput = $('publicationScheduledAt')?.value || '';
      const tags = String($('publicationTags')?.value || '').split(',').map((item) => item.trim()).filter(Boolean);
      const response = await api(`/api/projects/${projectId}/publish`, {method: 'POST', body: JSON.stringify({
        confirmed: true,
        managed_channel_id: Number($('publicationChannel')?.value || 0) || null,
        platform,
        output_profile: $('publicationProfile')?.value || null,
        video_variant: variant,
        thumbnail_asset_id: Number($('publicationThumbnail')?.value || 0) || null,
        title: $('publicationTitle')?.value || '',
        description: $('publicationDescription')?.value || '',
        tags,
        privacy_status: $('publicationPrivacy')?.value || null,
        scheduled_at: scheduledInput ? new Date(scheduledInput).toISOString() : null,
      })});
      setMessage(response.status === 'ready_manual'
        ? `Đã chuẩn bị gói ${platform} #${response.publication?.id || ''}; tải MP4 để đăng.`
        : `Đã đưa publication #${response.publication?.id || ''} vào hàng đợi YouTube.`, 'success');
      await refreshStudioPublish(projectId);
      await openProjectDetail(projectId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function cancelPublication(publicationId, projectId) {
    if (!confirm('Hủy publication đang xếp hàng?')) return;
    try {
      await api(`/api/publications/${publicationId}/cancel`, {method: 'POST'});
      setMessage('Đã hủy publication.', 'success');
      await openProjectDetail(projectId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function retryPublication(publicationId, projectId) {
    try {
      await api(`/api/publications/${publicationId}/retry`, {method: 'POST'});
      setMessage('Đã đưa publication vào hàng đợi lại.', 'success');
      await openProjectDetail(projectId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function queueProductionJob(projectId, jobType, provider, confirmed = false) {
    if (confirmed && !confirm(`Chạy ${provider} cho ${jobType} có thể dùng CPU/GPU và tạo file media. Bạn đã kiểm tra timeline và muốn tiếp tục?`)) return;
    setMessage(`Đang đưa ${jobType} (${provider}) vào worker...`);
    try {
      const response = await api(`/api/projects/${projectId}/jobs`, {
        method: 'POST',
        body: JSON.stringify({job_type: jobType, provider, confirmed}),
      });
      setMessage(`Đã đưa ${jobType} (${provider}) vào hàng đợi.`, 'success');
      await openProjectDetail(projectId);
      if (response.job?.id) void watchProductionJob(projectId, response.job.id, jobType);
      return response;
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function applyChannelPreset(projectId) {
    if (!confirm('Áp dụng preset kênh sẽ thay định dạng, voice, phụ đề và ngôn ngữ của project. Tiếp tục?')) return;
    try {
      await api(`/api/projects/${projectId}/apply-channel-preset`, {method: 'POST'});
      setMessage('Đã áp dụng preset kênh vào render settings.', 'success');
      await openProjectDetail(projectId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function cancelProductionJob(projectId, jobId) {
    if (!confirm('Hủy job đang chờ này? Job chưa chạy sẽ không tạo media.')) return;
    try {
      await api(`/api/jobs/${jobId}/cancel`, {method: 'POST'});
      setMessage('Đã hủy production job.', 'success');
      await openProjectDetail(projectId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function retryProductionJob(projectId, jobId, jobType) {
    try {
      const response = await api(`/api/jobs/${jobId}/retry`, {method: 'POST'});
      setMessage(`Đã đưa ${jobType} vào hàng đợi để chạy lại.`, 'success');
      await openProjectDetail(projectId);
      if (response.job?.id) void watchProductionJob(projectId, response.job.id, jobType);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function watchProductionJob(projectId, jobId, jobType) {
    for (let attempt = 0; attempt < 1200; attempt += 1) {
      try {
        const job = await api(`/api/jobs/${jobId}`);
        if (job.status === 'completed') {
          setMessage(`${jobType} đã hoàn tất.`, 'success');
          if (jobType === 'premiere_draft') {
            window.open(`/api/projects/${projectId}/premiere-export/download`, '_blank', 'noopener,noreferrer');
          }
          await openProjectDetail(projectId, jobType === 'render' ? 'export' : 'overview');
          return job;
        }
        if (job.status === 'error') {
          setMessage(`${jobType} thất bại: ${job.error || 'Lỗi không xác định.'}`, 'error');
          await openProjectDetail(projectId);
          return job;
        }
        if (attempt % 4 === 0) setMessage(`${jobType} đang xử lý... (${job.status})`);
      } catch (error) {
        setMessage(`Không đọc được trạng thái ${jobType}: ${error.message}`, 'error');
        return null;
      }
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
    setMessage(`${jobType} chạy quá lâu; hãy mở lại project để xem trạng thái.`, 'error');
    return null;
  }

  async function exportPremiere(projectId) {
    setMessage('Đang đóng gói file cho Premiere...');
    try {
      const response = await api(`/api/projects/${projectId}/premiere-export`, {
        method: 'POST',
        body: JSON.stringify({force: false}),
      });
      setMessage(`Đã tạo gói Premiere gồm ${response.segments} cảnh.`, 'success');
      window.open(response.download_url, '_blank', 'noopener,noreferrer');
      await openProjectDetail(projectId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  function updateBatchToolbar() {
    const count = state.selectedVideoIds.size;
    $('batchToolbar').classList.toggle('open', count > 0);
    $('batchCount').textContent = `${count} video đã chọn`;
    const idsOnPage = state.videos.map((video) => video.youtube_video_id);
    const selectAll = $('selectAllVideos');
    selectAll.checked = idsOnPage.length > 0 && idsOnPage.every((id) => state.selectedVideoIds.has(id));
  }

  function toggleVideoSelection(videoId, checked) {
    if (checked) state.selectedVideoIds.add(videoId);
    else state.selectedVideoIds.delete(videoId);
    updateBatchToolbar();
  }

  function toggleSelectAllVideos(checked) {
    for (const video of state.videos) {
      if (checked) state.selectedVideoIds.add(video.youtube_video_id);
      else state.selectedVideoIds.delete(video.youtube_video_id);
    }
    document.querySelectorAll('.video-select').forEach((box) => { box.checked = checked; });
    updateBatchToolbar();
  }

  function clearVideoSelection() {
    state.selectedVideoIds.clear();
    document.querySelectorAll('.video-select').forEach((box) => { box.checked = false; });
    updateBatchToolbar();
  }

  function selectedVideoIdsArray() {
    return Array.from(state.selectedVideoIds);
  }

  function confirmWhisper(count) {
    const target = count === 1 ? '1 video' : `${count} video`;
    return confirm(`Whisper sẽ trích xuất audio tạm thời cho ${target} để tạo transcript. Audio tạm sẽ bị xoá sau khi xử lý, nhưng quá trình này vẫn cần tải luồng audio từ YouTube. Tiếp tục?`);
  }

  async function batchAnalyze() {
    const videoIds = selectedVideoIdsArray();
    if (!videoIds.length) return;
    const provider = $('analysisProviderSelect').value || 'local_metadata';
    setMessage(`Đang đưa ${videoIds.length} video vào hàng đợi phân tích (provider: ${provider})...`);
    try {
      const result = await api('/api/analysis-queue', {method: 'POST', body: JSON.stringify({video_ids: videoIds, provider, force: true})});
      setMessage(`Đã đưa ${result.queued} video vào hàng đợi phân tích.`, 'success');
      clearVideoSelection();
      await refresh();
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function batchTranscript() {
    const videoIds = selectedVideoIdsArray();
    if (!videoIds.length) return;
    if (!confirmWhisper(videoIds.length)) return;
    setMessage(`Đang đưa ${videoIds.length} video vào hàng đợi transcript (Whisper)...`);
    try {
      const result = await api('/api/transcript-queue', {method: 'POST', body: JSON.stringify({video_ids: videoIds, force: true, confirmed: true})});
      setMessage(`Đã đưa ${result.queued} video vào hàng đợi transcript.`, 'success');
      clearVideoSelection();
      await refresh();
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function batchWriter() {
    const videoIds = selectedVideoIdsArray();
    if (!videoIds.length) return;
    const providerSelect = $('analysisProviderSelect').value;
    const provider = (providerSelect === 'anthropic_claude' || providerSelect === 'openai_gpt' || providerSelect === 'codex_cli' || providerSelect === 'claude_code_cli' || providerSelect === 'antigravity') ? providerSelect : null;
    let done = 0;
    for (const videoId of videoIds) {
      setMessage(`AI Writer: đang xử lý ${done + 1}/${videoIds.length} (${videoId})...`);
      try {
        await api(`/api/videos/${encodeURIComponent(videoId)}/writer`, {method: 'POST', body: JSON.stringify({provider})});
      } catch (error) {
        setMessage(`AI Writer dừng ở video ${videoId}: ${error.message}`, 'error');
        await refresh();
        return;
      }
      done += 1;
    }
    setMessage(`AI Writer đã xử lý xong ${done} video.`, 'success');
    clearVideoSelection();
    await refresh();
  }

  async function batchDownload(mediaType) {
    const videoIds = selectedVideoIdsArray();
    if (!videoIds.length) return;
    const label = mediaType === 'audio' ? 'audio' : 'video';
    if (!confirm(`Tải ${label} cho ${videoIds.length} video đã chọn về máy để dựng lại? File sẽ được giữ lại đến khi bạn xoá thủ công.`)) return;
    let done = 0;
    for (const videoId of videoIds) {
      setMessage(`Đang tải ${label} ${done + 1}/${videoIds.length} (${videoId})...`);
      try {
        await api(`/api/videos/${encodeURIComponent(videoId)}/download?media_type=${encodeURIComponent(mediaType)}&confirmed=true`, {method: 'POST'});
      } catch (error) {
        setMessage(`Tải dừng ở video ${videoId}: ${error.message}`, 'error');
        await refresh();
        return;
      }
      done += 1;
    }
    setMessage(`Đã tải xong ${label} cho ${done} video.`, 'success');
    clearVideoSelection();
    await refresh();
  }

  async function loadJobs() {
    state.jobs = await api('/api/analysis-jobs?limit=8');
    const jobStatus = (status) => ({completed: 'HOÀN TẤT', error: 'LỖI', cancelled: 'ĐÃ HỦY', running: 'ĐANG CHẠY'}[status] || 'ĐANG CHỜ');
    $('jobsBody').innerHTML = state.jobs.length ? state.jobs.map((job) => `
      <div class="job-row"><span class="job-dot ${esc(job.status)}"></span><div class="job-main"><div class="job-title">${esc(channelName(state.videos.find((v) => v.youtube_video_id === job.youtube_video_id)?.youtube_channel_id))}</div><div class="job-meta">${esc(job.youtube_video_id)} · ${esc(job.provider)} · ${date(job.finished_at || job.created_at)}</div></div><span class="tag ${job.status === 'completed' ? 'green' : job.status === 'error' ? 'red' : job.status === 'cancelled' ? 'red' : 'orange'}">${jobStatus(job.status)}</span>${job.status === 'queued' ? `<button class="btn small ghost" type="button" onclick="cancelAnalysisJob(${job.id})">Hủy</button>` : ''}${['error', 'cancelled'].includes(job.status) ? `<button class="btn small ghost" type="button" onclick="retryAnalysisJob(${job.id})">Chạy lại</button>` : ''}</div>`).join('') : '<div class="empty">Chưa có tác vụ phân tích. Hãy bấm Phân tích trên một video.</div>';
  }

  async function cancelAnalysisJob(jobId) {
    try {
      await api(`/api/analysis-jobs/${jobId}/cancel`, {method: 'POST'});
      setMessage('Đã hủy job.', 'success');
      await Promise.all([loadJobs(), loadQueueStatus(), loadTranscriptQueueStatus()]);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function retryAnalysisJob(jobId) {
    try {
      await api(`/api/analysis-jobs/${jobId}/retry`, {method: 'POST'});
      setMessage('Đã đưa job vào hàng đợi lại.', 'success');
      await Promise.all([loadJobs(), loadQueueStatus(), loadTranscriptQueueStatus()]);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function loadQueueStatus() {
    state.queue = await api('/api/analysis-queue');
    const queue = state.queue;
    const status = $('queueStatusTag');
    if (!queue.worker_running) {
      status.className = 'tag red';
      status.textContent = 'WORKER ĐÃ DỪNG';
    } else if (queue.paused) {
      status.className = 'tag orange';
      status.textContent = `TẠM DỪNG · ${number(queue.queued)} ĐANG CHỜ · ${number(queue.running)} ĐANG CHẠY`;
    } else {
      status.className = 'tag cyan';
      status.textContent = `${number(queue.queued)} ĐANG CHỜ · ${number(queue.running)} ĐANG CHẠY`;
    }
    $('queuePauseButton').textContent = queue.paused ? 'Tiếp tục' : 'Tạm dừng';
  }

  async function loadTranscriptQueueStatus() {
    state.transcriptQueue = await api('/api/transcript-queue');
    const queue = state.transcriptQueue;
    const status = $('transcriptQueueStatusTag');
    if (!queue.worker_running) {
      status.className = 'tag red';
      status.textContent = 'WORKER ĐÃ DỪNG';
    } else if (queue.paused) {
      status.className = 'tag orange';
      status.textContent = `TẠM DỪNG · ${number(queue.queued)} ĐANG CHỜ · ${number(queue.running)} ĐANG CHẠY`;
    } else {
      status.className = 'tag cyan';
      status.textContent = `${number(queue.queued)} ĐANG CHỜ · ${number(queue.running)} ĐANG CHẠY · ${number(queue.completed)} HOÀN TẤT`;
    }
    $('transcriptPauseButton').textContent = queue.paused ? 'Tiếp tục' : 'Tạm dừng';
  }

  async function loadProductionQueueStatus() {
    const previous = state.productionQueue;
    state.productionQueue = await api('/api/production-queue');
    syncStudioRenderProvider();
    await refreshStudioAfterFinishedJobs(previous, state.productionQueue);
  }

  // A voiceover writes its files and attaches them to the scenes, but the page
  // went on showing the timeline it had loaded before the job started — so a
  // finished voiceover looked like a failed one, the play buttons were never
  // drawn, and the obvious next move was to run something destructive.
  // The queue reports counts, not a job list, so a change in how many have
  // finished is the signal that something new is on disk.
  function finishedJobSignature(queue) {
    if (!queue) return '';
    return `${queue.completed ?? 0}:${queue.error ?? 0}:${queue.running ?? 0}`;
  }

  async function refreshStudioAfterFinishedJobs(previous, current) {
    if (!previous || !state.studioProjectId) return;
    const before = finishedJobSignature(previous);
    const after = finishedJobSignature(current);
    if (before === after) return;
    try {
      const bundle = await api(`/api/projects/${state.studioProjectId}`);
      state.timeline = bundle.latest_timeline || [];
      state.narrationSource = bundle.narration_source || state.narrationSource;
      renderStudioStoryboard(bundle.latest_shots || [], state.timeline);
      // The short is its own lane with its own jobs, and a finished one has
      // to show there too - otherwise its steps stay grey after the work is
      // actually done, which is what makes people re-run it.
      await loadShortLane();
    } catch (_) { /* the poll must keep running even if one refresh fails */ }
  }

  function syncStudioRenderProvider() {
    const select = $('studioRenderProviderSelect');
    if (!select) return;
    const gpuOnly = Boolean(state.productionQueue?.gpu_only);
    Array.from(select.options).forEach((option) => {
      const allowed = !gpuOnly || option.value === 'ffmpeg_builtin';
      option.disabled = !allowed;
      option.hidden = !allowed;
    });
    if (gpuOnly) select.value = 'ffmpeg_builtin';
  }

  // Hết hạn mức là chuyện thường hằng tuần với các gói thuê bao, không phải
  // lỗi. Trước đây nó chìm vào cột error của job còn AI điều phối lặng lẽ
  // chuyển sang agent khác, nên người dùng không hề biết model nào đã dừng.
  function formatLimitReset(value) {
    if (!value) return 'chưa rõ thời điểm khôi phục';
    const when = new Date(value);
    if (Number.isNaN(when.getTime())) return 'chưa rõ thời điểm khôi phục';
    const hours = (when - new Date()) / 3600000;
    const stamp = when.toLocaleString('vi-VN', {dateStyle: 'short', timeStyle: 'short'});
    if (hours <= 0) return `dự kiến đã khôi phục (${stamp})`;
    if (hours < 24) return `khôi phục lúc ${stamp} (còn ~${Math.max(1, Math.round(hours))} giờ)`;
    return `khôi phục lúc ${stamp} (còn ~${Math.round(hours / 24)} ngày)`;
  }

  async function loadUsageLimits() {
    const banner = $('usageLimitBanner');
    if (!banner) return;
    try {
      const result = await api('/api/usage-limits');
      const limits = result.limits || [];
      if (!limits.length) {
        banner.hidden = true;
        banner.innerHTML = '';
        state.usageLimits = [];
        return;
      }
      // Chỉ báo một lần cho mỗi model, không nhắc lại mỗi vòng refresh.
      const fresh = limits
        .filter((item) => !(state.usageLimits || []).some((seen) => seen.provider === item.provider))
        .map((item) => item.label);
      state.usageLimits = limits;
      banner.hidden = false;
      banner.innerHTML = `<div class="usage-limit-title">⚠ ${limits.length} model đang hết hạn mức</div>
        <ul>${limits.map((item) => `<li><b>${esc(item.label)}</b> — ${esc(formatLimitReset(item.resets_at))}
          <button class="btn small ghost" style="margin-left:8px" onclick="retryUsageLimitedProvider('${esc(item.provider)}')">Cho thử lại</button>
          <div class="usage-limit-when">${esc(item.message || '')}</div></li>`).join('')}</ul>`;
      if (fresh.length) {
        setMessage(`Hết hạn mức: ${fresh.join(', ')}. Các bước dùng model này sẽ chuyển sang model khác hoặc dừng lại.`, 'error');
      }
    } catch (_) {
      // Không để việc báo hạn mức làm hỏng vòng refresh.
    }
  }

  async function retryUsageLimitedProvider(provider) {
    try {
      const result = await api(`/api/usage-limits/${encodeURIComponent(provider)}/clear`, {method: 'POST'});
      setMessage(`Đã cho phép ${result.label || provider} thử lại. Task chờ nghiệm thu sẽ tự tiếp tục.`, 'success');
      await loadUsageLimits();
      await loadAutomationStatus(true);
    } catch (error) {
      setMessage(`Không mở lại được model: ${error.message}`, 'error');
    }
  }

  // Trước đây không có đường nào dừng: phân tích và viết kịch bản là request
  // HTTP chặn, chạy hàng chục phút, đóng app là cách duy nhất thoát ra.
  function elapsedSince(iso) {
    const started = new Date(iso);
    if (Number.isNaN(started.getTime())) return '';
    const seconds = Math.max(0, Math.round((Date.now() - started.getTime()) / 1000));
    return seconds < 60 ? `${seconds} giây` : `${Math.floor(seconds / 60)} phút ${seconds % 60} giây`;
  }

  async function loadRunningOperations() {
    const bar = $('runningOpsBar');
    if (!bar) return;
    try {
      const result = await api('/api/operations');
      const running = result.operations || [];
      if (!running.length) { bar.hidden = true; bar.innerHTML = ''; return; }
      bar.hidden = false;
      bar.innerHTML = `<div class="running-ops-head">Đang chạy · ${running.length}</div>
        ${running.map((item) => `<div class="running-op">
          <div><b>${esc(item.label || item.kind)}</b>
            <div class="running-op-step">${esc(item.step || '')}${item.step ? ' · ' : ''}${esc(elapsedSince(item.started_at))}</div></div>
          <button class="btn small danger" onclick="cancelRunningOperation('${esc(item.id)}')"
            ${item.cancelled ? 'disabled' : ''}>${item.cancelled ? 'Đang dừng...' : 'Dừng'}</button>
        </div>`).join('')}
        ${running.length > 1 ? '<div class="studio-actions"><button class="btn small danger" onclick="cancelAllOperations()">Dừng tất cả</button></div>' : ''}`;
    } catch (_) { /* thanh này không được phép làm hỏng vòng refresh */ }
  }

  async function cancelRunningOperation(operationId) {
    try {
      await api(`/api/operations/${encodeURIComponent(operationId)}/cancel`, {method: 'POST'});
      setMessage('Đang dừng tiến trình...', 'success');
    } catch (error) { setMessage(`Không dừng được: ${error.message}`, 'error'); }
    await loadRunningOperations();
  }

  async function cancelAllOperations() {
    if (!confirm('Dừng tất cả tiến trình đang chạy?')) return;
    try {
      const result = await api('/api/operations/cancel-all', {method: 'POST'});
      setMessage(`Đã yêu cầu dừng ${result.cancelled} tiến trình.`, 'success');
    } catch (error) { setMessage(`Không dừng được: ${error.message}`, 'error'); }
    await loadRunningOperations();
  }

  let studioRefreshPending = null;
  let studioSettingsPending = null;
  let lastLibraryRefresh = 0;
  let lastSettingsRefresh = 0;

  function refreshStudioSettings() {
    if (studioSettingsPending) return studioSettingsPending;
    studioSettingsPending = Promise.allSettled([
      loadHealth(), loadWorkflows(), loadEdgeVoices(), loadOAuthStatus(),
      loadToolStatus(), loadModelCatalog(), loadIntegrations(),
      loadOrchestratorSettings(), loadAnalysisProviders(),
    ]).finally(() => { lastSettingsRefresh = Date.now(); studioSettingsPending = null; });
    return studioSettingsPending;
  }

  // Optional runtime probes must not gate opening a saved project. Polls share
  // one in-flight refresh, and only user refreshes reload the configuration.
  function refresh(options = {}) {
    if (!options.poll || Date.now() - lastSettingsRefresh >= 60000) void refreshStudioSettings();
    if (studioRefreshPending) return studioRefreshPending;
    studioRefreshPending = (async () => {
      const tasks = [loadUsageLimits(), loadRunningOperations(), loadSummary(),
        loadQueueStatus(), loadTranscriptQueueStatus(), loadProductionQueueStatus(), loadJobs()];
      if (!options.poll || Date.now() - lastLibraryRefresh >= 30000) {
        tasks.push((async () => {
          await Promise.all([loadChannels(), loadManagedChannels()]);
          await Promise.all([loadVideos(), loadProjects()]);
          lastLibraryRefresh = Date.now();
        })());
      }
      if (state.workspace === 'orchestration') {
        tasks.push(loadAutomationProjectList(), loadAutomationInbox(), loadProviderCatalog());
      }
      if (state.automationProjectId) tasks.push(loadAutomationStatus(true));
      const results = await Promise.allSettled(tasks);
      const failed = results.find((result) => result.status === 'rejected');
      if (failed && !options.poll) setMessage(failed.reason?.message || 'Không tải được một phần dữ liệu.', 'error');
    })().finally(() => { studioRefreshPending = null; });
    return studioRefreshPending;
  }

  async function queuePendingTranscripts() {
    const button = $('queueTranscriptButton');
    const limit = Number($('transcriptLimit').value);
    if (!confirmWhisper(limit)) return;
    button.disabled = true;
    setMessage('Đang đưa video vào hàng đợi tạo transcript (Whisper)... có thể chậm trên CPU.');
    try {
      const channelId = $('transcriptChannelSelect').value || null;
      const result = await api('/api/transcript-queue', {method: 'POST', body: JSON.stringify({channel_id: channelId, limit, force: false, confirmed: true})});
      setMessage(`Đã đưa ${result.queued} video vào hàng đợi transcript. Worker sẽ xử lý nền.`, 'success');
      await refresh();
    } catch (error) { setMessage(error.message, 'error'); }
    finally { button.disabled = false; }
  }

  async function toggleTranscriptQueue() {
    const paused = Boolean(state.transcriptQueue?.paused);
    try { await api('/api/transcript-queue', {method: 'PATCH', body: JSON.stringify({paused: !paused})}); await loadTranscriptQueueStatus(); setMessage(paused ? 'Đã tiếp tục hàng đợi transcript.' : 'Đã tạm dừng hàng đợi transcript.', 'success'); } catch (error) { setMessage(error.message, 'error'); }
  }

  async function queuePendingAnalysis() {
    const button = $('queueAnalysisButton');
    button.disabled = true;
    setMessage('Đang đưa video vào hàng đợi phân tích...');
    try {
      const channelId = $('analysisChannelSelect').value || null;
      const limit = Number($('analysisLimit').value);
      const provider = $('analysisProviderSelect').value || 'local_metadata';
      const result = await api('/api/analysis-queue', {method: 'POST', body: JSON.stringify({channel_id: channelId, limit, force: false, provider})});
      setMessage(`Đã đưa ${result.queued} video vào hàng đợi (provider: ${provider}). Worker sẽ xử lý nền.`, 'success');
      await refresh();
    } catch (error) { setMessage(error.message, 'error'); }
    finally { button.disabled = false; }
  }

  async function toggleAnalysisQueue() {
    const paused = Boolean(state.queue?.paused);
    try { await api('/api/analysis-queue', {method: 'PATCH', body: JSON.stringify({paused: !paused})}); await loadQueueStatus(); setMessage(paused ? 'Đã tiếp tục hàng đợi phân tích.' : 'Đã tạm dừng hàng đợi phân tích.', 'success'); } catch (error) { setMessage(error.message, 'error'); }
  }

  async function syncChannel(channelId) {
    setMessage('Đang đồng bộ metadata. Hệ thống sẽ không tải video...');
    try { const result = await api(`/api/channels/${encodeURIComponent(channelId)}/sync`, {method: 'POST'}); setMessage(`Đồng bộ hoàn tất: đã kiểm tra ${result.videos_seen}, thêm mới ${result.videos_new}.`, 'success'); await refresh(); } catch (error) { setMessage(error.message, 'error'); }
  }

  async function editChannelGroup(channelId) {
    const channel = state.channels.find((item) => item.youtube_channel_id === channelId);
    if (!channel) return;
    const groupName = prompt('Nhãn nhóm cho kênh (để trống để bỏ nhãn):', channel.group_name || '');
    if (groupName === null) return;
    try {
      await api(`/api/channels/${encodeURIComponent(channelId)}/group`, {
        method: 'PATCH', body: JSON.stringify({group_name: groupName.trim()}),
      });
      setMessage('Đã cập nhật nhãn kênh.', 'success');
      await refresh();
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function toggleChannel(channelId, enabled) {
    try { await api(`/api/channels/${encodeURIComponent(channelId)}/tracking`, {method: 'PATCH', body: JSON.stringify({enabled})}); await refresh(); } catch (error) { setMessage(error.message, 'error'); }
  }

  async function analyzeVideo(videoId) {
    const provider = $('analysisProviderSelect').value || 'local_metadata';
    setMessage(`Đang kiểm tra transcript cho ${videoId}...`);
    try {
      const transcript = await ensureTranscriptForAnalysis(videoId, (text) => setMessage(text));
      setMessage(`Đã có transcript (${number(transcript.word_count || 0)} từ). Đang phân tích video (provider: ${provider})...`);
      const response = await api(`/api/videos/${encodeURIComponent(videoId)}/analyze?provider=${encodeURIComponent(provider)}`, {method: 'POST'});
      renderAnalysis(response);
      state.studioVideoId = videoId;
      if ($('studioVideoSelect')) $('studioVideoSelect').value = videoId;
      state.studioAnalysis = response;
      renderStudioVideoPreview();
      renderStudioAnalysis(response);
      setMessage('Transcript và phân tích video đã hoàn tất.', 'success');
      await refresh();
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function ensureTranscriptForAnalysis(videoId, reportProgress = () => {}) {
    const existing = await api(`/api/videos/${encodeURIComponent(videoId)}/transcript`);
    if (existing?.status !== 'missing' && String(existing?.content_text || '').trim()) return existing;
    reportProgress('Video chưa có transcript. Đang trích audio tạm thời và nhận diện lời nói bằng Whisper...');
    const response = await api(`/api/videos/${encodeURIComponent(videoId)}/transcript/auto`, {
      method: 'POST',
      body: JSON.stringify({confirmed: true}),
    });
    const transcript = response.transcript;
    if (!transcript || !String(transcript.content_text || '').trim()) throw new Error('Whisper không tạo được transcript có nội dung.');
    return transcript;
  }

  async function autoTranscribeVideo(videoId) {
    if (!confirmWhisper(1)) return;
    setMessage(`Đang trích xuất audio tạm thời và chạy Whisper cho ${videoId}... có thể mất vài phút.`);
    try {
      const response = await api(`/api/videos/${encodeURIComponent(videoId)}/transcript/auto`, {method: 'POST', body: JSON.stringify({confirmed: true})});
      setMessage(`Whisper hoàn tất (${response.language || 'không rõ ngôn ngữ'}). Audio tạm đã được xoá, chỉ giữ lại transcript.`, 'success');
      await openTranscript(videoId);
      await refresh();
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function loadCaptionsList(videoId) {
    const container = $('captionsList');
    if (!state.oauth?.configured) {
      container.textContent = 'Chưa cấu hình GOOGLE_OAUTH_CLIENT_ID/SECRET trong .env.';
      return;
    }
    if (!state.oauth?.connected) {
      container.textContent = 'Chưa kết nối YouTube OAuth — bấm nút ở góc trên để kết nối.';
      return;
    }
    container.textContent = 'Đang tải danh sách caption...';
    try {
      const captions = await api(`/api/videos/${encodeURIComponent(videoId)}/captions`);
      if (!captions.length) {
        container.textContent = 'Video này không có caption chính chủ nào.';
        return;
      }
      container.innerHTML = captions.map((c) => `<div class="job-row"><span class="job-dot completed"></span><div class="job-main"><div class="job-title">${esc(c.language || '?')} · ${esc(c.name || (c.is_auto_synced ? 'Tự động (ASR)' : 'Thủ công'))}</div></div><button class="btn small ghost" onclick="importCaption('${esc(videoId)}', '${esc(c.caption_id)}', '${esc(c.language || '')}')">Nhập caption này</button></div>`).join('');
    } catch (error) {
      container.textContent = error.message;
    }
  }

  async function importCaption(videoId, captionId, language) {
    setMessage('Đang tải caption chính chủ từ YouTube...');
    try {
      const response = await api(`/api/videos/${encodeURIComponent(videoId)}/transcript/from-caption`, {
        method: 'POST',
        body: JSON.stringify({caption_id: captionId, language}),
      });
      setMessage('Đã nhập caption chính chủ làm transcript.', 'success');
      await openTranscript(videoId);
      await refresh();
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function openTranscript(videoId) {
    setWorkspace('source');
    state.transcriptVideoId = videoId;
    try {
      const transcript = await api(`/api/videos/${encodeURIComponent(videoId)}/transcript`);
      const video = state.videos.find((item) => item.youtube_video_id === videoId);
      $('transcriptTitle').textContent = `${video?.title || videoId} · ${videoId}`;
      $('transcriptText').value = transcript.content_text || '';
      $('transcriptSource').value = transcript.source_type || 'manual';
      $('transcriptFormat').value = transcript.transcript_format || 'txt';
      $('transcriptLanguage').value = transcript.language || '';
      $('transcriptMeta').textContent = transcript.content_text ? `${number(transcript.word_count)} từ · nguồn: ${transcript.source_type}` : 'Chưa có transcript';
      $('transcriptDetail').classList.add('open');
      $('transcriptDetail').scrollIntoView({behavior: 'smooth', block: 'nearest'});
      loadCaptionsList(videoId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function saveTranscript() {
    if (!state.transcriptVideoId) return;
    const button = $('saveTranscript');
    button.disabled = true;
    setMessage('Đang lưu transcript...');
    try {
      const response = await api(`/api/videos/${encodeURIComponent(state.transcriptVideoId)}/transcript`, {
        method: 'POST',
        body: JSON.stringify({
          text: $('transcriptText').value,
          source_type: $('transcriptSource').value,
          transcript_format: $('transcriptFormat').value,
          language: $('transcriptLanguage').value,
        }),
      });
      const transcript = response.transcript;
      $('transcriptMeta').textContent = `${number(transcript.word_count)} từ · nguồn: ${transcript.source_type}`;
      setMessage('Đã lưu transcript. Có thể dùng làm đầu vào cho bước phân tích nội dung.', 'success');
      await refresh();
    } catch (error) { setMessage(error.message, 'error'); }
    finally { button.disabled = false; }
  }

  function renderAnalysis(payload) {
    const result = payload.result || payload;
    $('analysisTitle').textContent = `${result.title || payload.video_id || ''} · ${result.provider || payload.provider || 'metadata'}`;
    const keywords = (result.keywords || []).map((item) => `<span class="keyword">${esc(item.keyword)} <small>×${esc(item.count)}</small></span>`).join('') || '<span class="secondary-text">Chưa phát hiện từ khóa</span>';
    const recommendations = (result.recommendations || []).map((item) => `<li>${esc(item)}</li>`).join('') || '<li>Chưa có đề xuất.</li>';
    $('analysisBody').innerHTML = `
      <div class="analysis-grid"><div class="analysis-item"><label>Loại nội dung</label><strong>${esc(result.content_type || '—')}</strong></div><div class="analysis-item"><label>Ngôn ngữ</label><strong>${esc(result.language || '—')}</strong></div><div class="analysis-item"><label>Chủ đề</label><strong>${esc(result.topic || '—')}</strong></div></div>
      <div class="analysis-columns"><div><div class="eyebrow">TỪ KHÓA</div><div class="keyword-list">${keywords}</div><div class="eyebrow" style="margin-top:15px">MỞ ĐẦU MÔ TẢ</div><p class="panel-sub">${esc(result.description_opening || 'Không có mô tả.')}</p></div><div><div class="eyebrow">ĐỀ XUẤT</div><ul class="analysis-list">${recommendations}</ul><div class="eyebrow" style="margin-top:12px">BƯỚC TIẾP THEO</div><span class="tag cyan">${esc(result.next_step || 'kiểm duyệt thủ công')}</span></div></div>`;
    const metrics = result.metrics || {};
    const fullExtra = `<div class="analysis-item" style="margin-top:14px"><label>Hook</label><p class="panel-sub">${esc(result.hook || '—')}</p><div class="eyebrow" style="margin-top:12px">Chỉ số</div><p class="panel-sub">Tiêu đề: ${esc(metrics.title_length ?? '—')} ký tự · Mô tả: ${esc(metrics.description_length ?? '—')} ký tự · Tags: ${esc(metrics.tag_count ?? '—')} · Thumbnail: ${metrics.has_thumbnail ? 'Có' : 'Không'} · Caption: ${metrics.caption_available ? 'Có' : 'Không'}</p><details style="margin-top:10px"><summary>Xem JSON đầy đủ</summary><pre class="studio-json">${esc(JSON.stringify(result, null, 2))}</pre></details></div>`;
    $('analysisBody').insertAdjacentHTML('beforeend', fullExtra);
    $('analysisDetail').classList.add('open');
    $('analysisDetail').scrollIntoView({behavior: 'smooth', block: 'nearest'});
  }

  function renderWriter(payload) {
    const result = payload.result || payload;
    $('writerTitle').textContent = `${result.title || payload.video_id || ''} · ${result.provider || payload.provider || ''}`;
    const titles = (result.new_titles || []).map((item) => `<li>${esc(item)}</li>`).join('') || '<li>Chưa có tiêu đề gợi ý.</li>';
    const ideas = (result.key_ideas || []).map((item) => `<li>${esc(item)}</li>`).join('') || '<li>Chưa có ý tưởng.</li>';
    const hashtags = (result.hashtags || []).map((tag) => `<span class="keyword">#${esc(tag)}</span>`).join('') || '<span class="secondary-text">Chưa có hashtag</span>';
    const outline = (result.script_outline || []).map((item) => `<li>${esc(item)}</li>`).join('') || '<li>Chưa có dàn ý.</li>';
    $('writerBody').innerHTML = `
      <div class="analysis-item" style="margin-bottom:14px"><label>Tóm tắt video gốc</label><p class="panel-sub">${esc(result.summary || 'Chưa có tóm tắt.')}</p></div>
      <div class="analysis-columns">
        <div><div class="eyebrow">TIÊU ĐỀ MỚI GỢI Ý</div><ul class="analysis-list">${titles}</ul><div class="eyebrow" style="margin-top:15px">Ý TƯỞNG CHÍNH</div><ul class="analysis-list">${ideas}</ul></div>
        <div><div class="eyebrow">MÔ TẢ MỚI</div><p class="panel-sub">${esc(result.new_description || 'Chưa có mô tả.')}</p><div class="eyebrow" style="margin-top:12px">HASHTAG</div><div class="keyword-list">${hashtags}</div><div class="eyebrow" style="margin-top:12px">CTA</div><p class="panel-sub">${esc(result.cta || '—')}</p></div>
      </div>
      <div class="eyebrow" style="margin-top:15px">DÀN Ý KỊCH BẢN MỚI</div><ul class="analysis-list">${outline}</ul>
      <div class="secondary-text" style="margin-top:10px">Nguồn dữ liệu: ${result.source_type === 'transcript' ? 'metadata + transcript' : 'chỉ metadata (chưa có transcript)'}</div>`;
    $('writerDetail').classList.add('open');
    $('writerDetail').scrollIntoView({behavior: 'smooth', block: 'nearest'});
  }

  async function generateWriterContent(videoId) {
    setMessage(`Đang tạo nội dung mới bằng AI Writer cho ${videoId}... có thể mất chút thời gian.`);
    try {
      const providerSelect = $('analysisProviderSelect').value;
      const provider = (providerSelect === 'anthropic_claude' || providerSelect === 'openai_gpt' || providerSelect === 'codex_cli' || providerSelect === 'claude_code_cli' || providerSelect === 'antigravity') ? providerSelect : null;
      const response = await api(`/api/videos/${encodeURIComponent(videoId)}/writer`, {method: 'POST', body: JSON.stringify({provider})});
      renderWriter(response);
      setMessage('AI Writer đã tạo xong nội dung mới.', 'success');
      await refresh();
    } catch (error) { setMessage(error.message, 'error'); }
  }

  function closeAllDownloadMenus() {
    document.querySelectorAll('.dropdown-menu.open').forEach((el) => el.classList.remove('open'));
  }

  function toggleDownloadMenu(event, videoId) {
    event.stopPropagation();
    const menu = $(`downloadMenu-${videoId}`);
    const wasOpen = menu.classList.contains('open');
    closeAllDownloadMenus();
    if (!wasOpen) menu.classList.add('open');
  }

  document.addEventListener('click', closeAllDownloadMenus);

  async function downloadVideoForEditing(videoId, mediaType) {
    closeAllDownloadMenus();
    const label = mediaType === 'audio' ? 'audio' : 'video';
    if (!confirm(`Tải ${label} này về máy để dựng lại (có bình luận/góc nhìn riêng của bạn)? File sẽ được giữ lại đến khi bạn xoá thủ công.`)) return;
    setMessage(`Đang tải ${label} ${videoId} về máy... có thể mất một lúc tuỳ độ dài video.`);
    try {
      const result = await api(`/api/videos/${encodeURIComponent(videoId)}/download?media_type=${encodeURIComponent(mediaType)}&confirmed=true`, {method: 'POST'});
      setMessage(`Đã tải xong: ${result.path}`, 'success');
      await refresh();
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function deleteDownloadedVideo(videoId) {
    if (!confirm('Xoá file media đã tải của video này khỏi máy?')) return;
    setMessage(`Đang xoá file đã tải cho ${videoId}...`);
    try {
      await api(`/api/videos/${encodeURIComponent(videoId)}/download`, {method: 'DELETE'});
      setMessage('Đã xoá file video đã tải.', 'success');
      await refresh();
    } catch (error) { setMessage(error.message, 'error'); }
  }

  const SOURCE_IMPORT_FORM = {
    channel: {
      label: 'URL kênh / @handle / ID',
      placeholder: 'https://youtube.com/@GoogleDevelopers',
      submit: '＋ Thêm & đồng bộ',
    },
    video: {
      label: 'URL video YouTube',
      placeholder: 'https://www.youtube.com/watch?v=...',
      submit: '＋ Thêm video này',
    },
    link: {
      label: 'Link video từ nền tảng bất kỳ',
      placeholder: 'https://www.bilibili.com/video/BV1... · TikTok · Vimeo · Archive.org',
      submit: '＋ Thêm từ link',
    },
  };

  function updateSourceImportForm() {
    const mode = $('sourceImportType')?.value || 'channel';
    const shape = SOURCE_IMPORT_FORM[mode] || SOURCE_IMPORT_FORM.channel;
    $('sourceImportResult')?.setAttribute('hidden', '');
    $('referenceLabel').textContent = shape.label;
    $('reference').placeholder = shape.placeholder;
    $('sourceImportSubmit').textContent = shape.submit;
    const hint = $('sourceImportLinkHint');
    if (hint) {
      hint.hidden = mode !== 'link';
      // Metadata only: nothing is fetched until a download is asked for.
      hint.textContent = 'App đọc tiêu đề, tác giả và thời lượng bằng yt-dlp (khoảng 1800 trang được hỗ trợ). Chưa tải file về máy; bấm Tải video/audio ở bước sau khi cần.';
    }
  }

  function showSourceImportResult(video) {
    const result = $('sourceImportResult');
    const title = $('sourceImportResultTitle');
    const remake = $('sourceImportRemakeButton');
    const videoId = String(video?.youtube_video_id || '');
    if (!result || !title || !remake || !videoId) return;
    title.textContent = `Đã thêm: ${video?.title || videoId}`;
    remake.onclick = () => startStudioFromVideo(videoId);
    result.removeAttribute('hidden');
  }

  $('addChannelForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const submit = event.target.querySelector('button[type="submit"]');
    const mode = $('sourceImportType')?.value || 'channel';
    const isVideo = mode === 'video';
    const isLink = mode === 'link';
    const reference = $('reference').value;
    const groupName = $('groupName').value;
    submit.disabled = true;
    setMessage(
      isLink ? 'Đang đọc thông tin video từ link...'
      : isVideo ? 'Đang lấy metadata của đúng một video...'
      : 'Đang đăng ký kênh và đồng bộ metadata...'
    );
    try {
      let result;
      if (isLink) {
        result = await api('/api/videos/import-link', {method: 'POST', body: JSON.stringify({url: reference, group_name: groupName})});
      } else {
        result = await api(isVideo ? '/api/videos/import' : '/api/channels', {method: 'POST', body: JSON.stringify({reference, group_name: groupName})});
      }
      $('reference').value = '';
      setMessage(
        isLink ? `Đã thêm “${result.video?.title || ''}” từ ${result.platform}. Chưa tải file về máy.`
        : isVideo ? `Đã thêm đúng video “${result.video?.title || ''}”. Không quét các video khác của kênh.`
        : `Đã đăng ký kênh. Đã lưu ${result.videos_new} video mới.`,
        'success'
      );
      await refresh();
      if (isVideo || isLink) showSourceImportResult(result.video);
    } catch (error) { setMessage(error.message, 'error'); }
    finally { submit.disabled = false; }
  });
  $('refreshButton').addEventListener('click', refresh);
  $('queueAnalysisButton').addEventListener('click', queuePendingAnalysis);
  $('queuePauseButton').addEventListener('click', toggleAnalysisQueue);
  $('queueTranscriptButton').addEventListener('click', queuePendingTranscripts);
  $('transcriptPauseButton').addEventListener('click', toggleTranscriptQueue);
  $('oauthConnectButton').addEventListener('click', toggleOAuthConnection);
  $('sourceImportType').addEventListener('change', updateSourceImportForm);
  $('studioSourceChannelSelect').addEventListener('change', selectStudioSourceChannel);
  $('studioVideoSelect').addEventListener('change', selectStudioVideo);
  $('studioAnalyzeButton').addEventListener('click', analyzeStudioVideo);
  // Phần lớn trường hợp hai ngôn ngữ này giống nhau, nên chọn một lần là đủ;
  // vẫn đổi riêng được khi cần phân tích tiếng Anh mà viết kịch bản tiếng Việt.
  $('studioAnalysisLanguage')?.addEventListener('change', (event) => {
    const target = $('studioScriptLanguage');
    if (target && !target.dataset.touched) target.value = event.target.value;
  });
  $('studioScriptLanguage')?.addEventListener('change', (event) => { event.target.dataset.touched = '1'; });
  $('studioSourceUpload')?.addEventListener('change', (event) => { void uploadStudioSourceFile(event.target.files?.[0]); event.target.value = ''; });
  $('studioImageUpload')?.addEventListener('change', (event) => { void uploadStudioReferenceImages(event.target.files); event.target.value = ''; });
  $('studioFolderUpload')?.addEventListener('change', (event) => { void uploadStudioReferenceImages(event.target.files); event.target.value = ''; });
  $('studioAnalyzeImagesButton')?.addEventListener('click', () => void analyzeStudioReferenceImages());
  $('studioWriteButton').addEventListener('click', writeStudioScript);
  $('studioChatButton').addEventListener('click', chatStudioScript);
  $('studioGenerateStoryboardButton').addEventListener('click', generateStudioStoryboard);
  $('studioGenerateImagesButton').addEventListener('click', generateStudioSceneImagesBatch);
  $('studioGenerateVideosButton').addEventListener('click', generateStudioSceneVideosBatch);
  $('studioPlanVisualsButton')?.addEventListener('click', () => void planStudioVisuals());
  $('studioPlanEditButton')?.addEventListener('click', () => void planStudioEdit());
  $('studioDownloadSourceButton')?.addEventListener('click', () => void downloadStudioSource());
  const studioDialogueCutButton = $('studioCutByDialogueButton');
  if (studioDialogueCutButton) {
    studioDialogueCutButton.textContent = '2. Chọn mốc hình theo lời thoại';
    studioDialogueCutButton.addEventListener('click', () => void cutStudioScenesByDialogue());
  }
  const studioSourceCutButton = $('studioCutSourceScenesButton');
  if (studioSourceCutButton) studioSourceCutButton.textContent = '3. Cắt clip theo các mốc đã chọn';
  $('studioPlanSourceCuesButton')?.addEventListener('click', () => void planStudioSourceCues());
  $('studioCutSourceScenesButton')?.addEventListener('click', () => void cutStudioSourceScenes());
  $('studioRenderReupButton')?.addEventListener('click', () => void renderStudioReup());
  $('studioSceneImageProviderSelect').addEventListener('change', updateStudioSceneGenerationAvailability);
  $('studioSceneVideoProviderSelect').addEventListener('change', updateStudioSceneGenerationAvailability);
  $('studioScriptInstructionInput').addEventListener('input', inferStudioDurationFromPrompt);
  $('studioTargetDurationSeconds').addEventListener('input', updateStudioDurationHint);
  $('studioSaveVoiceButton').addEventListener('click', saveStudioVoiceSettings);
  $('studioGenerateVoiceoverButton').addEventListener('click', generateStudioVoiceover);
  $('studioReviewVoiceButton')?.addEventListener('click', () => void reviewStudioVoiceover());
  $('studioGenerateTimelineButton').addEventListener('click', generateStudioTimeline);
  $('studioQueueRenderButton').addEventListener('click', queueStudioRender);
  $('studioOpenProjectButton')?.addEventListener('click', openStudioProject);
  $('studioManagedChannelSelect').addEventListener('change', renderStudioManagedSummary);
  ['studioCreativeDirectionInput', 'studioScriptInstructionInput', 'studioTargetDurationSeconds', 'studioChatMessage'].forEach((id) => {
    $(id)?.addEventListener('input', saveStudioSession);
  });
  ['studioRemakeModeSelect', 'studioManagedChannelSelect', 'studioWriterProviderSelect', 'studioCreateStandaloneShort', 'studioInitialShortSeconds', 'studioVoiceRateSelect', 'studioVoiceReferenceAsset', 'studioVoicePromptText'].forEach((id) => {
    $(id)?.addEventListener('change', saveStudioSession);
  });
  $('studioVoiceProviderSelect')?.addEventListener('change', () => {
    syncStudioVoiceModelOptions();
    saveStudioSession();
    // Entering step 4 rehydrates this dropdown from the project's saved
    // settings, so a choice that lived only in the page was overwritten the
    // next time the user walked back into the step - picking Edge TTS and
    // finding VoxCPM again. Writing the choice down as it is made means the
    // rehydrate reads back the same answer.
    if (state.studioProjectId) void saveRenderSettings(state.studioProjectId, {quiet: true});
  });
  $('studioSubtitleModelSelect')?.addEventListener('change', () => {
    syncStudioSubtitleOptions();
    saveStudioSession();
  });
  $('studioVoiceModelSelect')?.addEventListener('change', () => {
    saveStudioSession();
    const choice = $('studioVoiceModelSelect')?.value || '';
    if (choice.startsWith('library:')) void selectStudioSharedVoiceSample(choice.slice('library:'.length));
    else if (choice.startsWith('preset:')) void selectStudioVoicePreview(choice.slice('preset:'.length));
    else if (choice.startsWith('asset:')) void selectStudioUploadedVoiceSample(Number(choice.slice('asset:'.length)));
  });
  $('managedChannelForm').addEventListener('submit', saveManagedChannel);
  $('videoGroupFilter').addEventListener('change', applyVideoFilters);
  $('videoChannelFilter').addEventListener('change', applyVideoChannelFilter);
  $('closeProject').addEventListener('click', () => $('projectDetail').classList.remove('open'));
  $('closeAnalysis').addEventListener('click', () => $('analysisDetail').classList.remove('open'));
  $('saveTranscript').addEventListener('click', saveTranscript);
  $('closeTranscript').addEventListener('click', () => $('transcriptDetail').classList.remove('open'));
  $('closeWriter').addEventListener('click', () => $('writerDetail').classList.remove('open'));
  restorePanel('channels');
  restorePanel('videos');
  try { state.studioWorkflow = localStorage.getItem('ytFactory.workflow') || 'content'; } catch (_) {}
  const savedWorkspace = localStorage.getItem('ytFactory.workspace') || 'dashboard';
  const initialWorkspace = workspaces[savedWorkspace] ? savedWorkspace : 'dashboard';
  try { setWorkspace(initialWorkspace, false); } catch (_) { setWorkspace('dashboard', false); }
  startBrowserLease();
  async function initializeApp() {
    const sessionBeforeRestore = savedStudioSession();
    await refresh();
    await restoreSavedStudioSession();
    await restoreSavedProjectDetail(sessionBeforeRestore);
  }
  void initializeApp();
  async function pollStudioStatus() {
    try { if (!document.hidden) await refresh({poll: true}); }
    finally { window.setTimeout(pollStudioStatus, 5000); }
  }
  window.setTimeout(pollStudioStatus, 5000);
