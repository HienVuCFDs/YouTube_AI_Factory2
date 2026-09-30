// library.js - video library, filters, analysis
//
// Part of one page split into ordered files. These are classic
// scripts sharing a single global scope and running in document
// order, so this is a move rather than a rewrite: the files
// concatenated in order are byte for byte the block they came from,
// which is what the test asserts.
  function populateVideoFilters() {
    const groupSelect = $('videoGroupFilter');
    const channelSelect = $('videoChannelFilter');
    if (!groupSelect || !channelSelect) return;
    const previousGroup = state.videoGroupFilter || groupSelect.value || '';
    const groups = [...new Set(state.channels.map(channelGroupName))].sort((left, right) => left.localeCompare(right, 'vi'));
    groupSelect.innerHTML = '<option value="">Tất cả nhóm</option>' + groups.map((group) => `<option value="${esc(group)}">${esc(group)}</option>`).join('');
    state.videoGroupFilter = groups.includes(previousGroup) ? previousGroup : '';
    groupSelect.value = state.videoGroupFilter;

    const channels = state.channels.filter((channel) => !state.videoGroupFilter || channelGroupName(channel) === state.videoGroupFilter);
    const previousChannel = state.videoChannelFilter || channelSelect.value || '';
    channelSelect.innerHTML = '<option value="">Tất cả kênh</option>' + channels.map((channel) => `<option value="${esc(channel.youtube_channel_id)}">${esc(channel.title || channel.youtube_channel_id)}</option>`).join('');
    state.videoChannelFilter = channels.some((channel) => channel.youtube_channel_id === previousChannel) ? previousChannel : '';
    channelSelect.value = state.videoChannelFilter;
  }

  function renderVideos() {
    const group = state.videoGroupFilter;
    const channelId = state.videoChannelFilter;
    state.videos = state.videoCatalog.filter((video) => {
      const channel = state.channels.find((item) => item.youtube_channel_id === video.youtube_channel_id);
      return (!group || channelGroupName(channel) === group) && (!channelId || video.youtube_channel_id === channelId);
    });
    const isFiltered = Boolean(group || channelId);
    $('videoCountLabel').textContent = isFiltered ? `${state.videos.length}/${state.videoCatalog.length} BẢN GHI` : `${state.videos.length} BẢN GHI`;
    $('videoFilterStatus').textContent = isFiltered ? `Đang lọc · ${state.videos.length} video` : `Tổng ${state.videoCatalog.length} video`;
    $('videosBody').innerHTML = state.videos.length ? state.videos.map((video) => `
      <tr>
        <td><input type="checkbox" class="video-select" ${state.selectedVideoIds.has(video.youtube_video_id) ? 'checked' : ''} onchange="toggleVideoSelection('${esc(video.youtube_video_id)}', this.checked)" /></td>
        <td class="video-cell"><a class="video-link" href="${esc(video.video_url)}" target="_blank" rel="noreferrer"><img class="thumb" src="${esc(video.thumbnail_url)}" alt=""><span><span class="video-title">${esc(video.title || video.youtube_video_id)}</span><span class="secondary-text">${esc(video.youtube_video_id)}</span></span></a></td>
        <td><span class="primary-text">${esc(channelName(video.youtube_channel_id))}</span><div class="secondary-text">${esc(video.youtube_channel_id)}</div></td>
        <td class="secondary-text">${date(video.published_at)}</td>
        <td class="secondary-text">${number(video.view_count)}</td>
        <td>${analysisTag(video)}<div class="secondary-text">${esc(video.analysis_provider || '—')}</div><div class="secondary-text">${transcriptTag(video)}</div></td>
        <td><div class="video-actions"><button class="btn small primary" onclick="startStudioFromVideo('${esc(video.youtube_video_id)}')">Dựng lại video →</button><button class="btn small ${video.analysis_status === 'completed' ? 'ghost' : 'primary'}" onclick="analyzeVideo('${esc(video.youtube_video_id)}')">${video.analysis_status === 'completed' ? 'Phân tích lại' : 'Phân tích'}</button><button class="btn small ghost" onclick="openTranscript('${esc(video.youtube_video_id)}')">Transcript</button><button class="btn small ghost" onclick="autoTranscribeVideo('${esc(video.youtube_video_id)}')">Whisper</button><button class="btn small ${video.has_writer_content ? 'ghost' : 'primary'}" onclick="generateWriterContent('${esc(video.youtube_video_id)}')">AI Writer</button><button class="btn small ghost" onclick="createProductionProject('${esc(video.youtube_video_id)}')">Dự án chi tiết</button>${video.media_status === 'downloaded_for_editing' ? `<button class="btn small danger" onclick="deleteDownloadedVideo('${esc(video.youtube_video_id)}')" title="${esc(video.local_media_path || '')}">Xoá file đã tải</button>` : `<div class="dropdown"><button class="btn small ghost" onclick="toggleDownloadMenu(event, '${esc(video.youtube_video_id)}')">Tải video ▾</button><div class="dropdown-menu" id="downloadMenu-${esc(video.youtube_video_id)}"><button class="btn small ghost" onclick="downloadVideoForEditing('${esc(video.youtube_video_id)}', 'video')">Tải video (mp4)</button><button class="btn small ghost" onclick="downloadVideoForEditing('${esc(video.youtube_video_id)}', 'audio')">Tải audio (mp3)</button></div></div>`}</div></td>
      </tr>`).join('') : '<tr><td colspan="7" class="empty">Không có video phù hợp với bộ lọc.</td></tr>';
    updateBatchToolbar();
    populateStudioVideoSelect();
  }

  function applyVideoFilters() {
    state.videoGroupFilter = $('videoGroupFilter').value;
    state.videoChannelFilter = '';
    populateVideoFilters();
    renderVideos();
  }

  function applyVideoChannelFilter() {
    state.videoChannelFilter = $('videoChannelFilter').value;
    renderVideos();
  }

  function clearVideoFilters() {
    state.videoGroupFilter = '';
    state.videoChannelFilter = '';
    populateVideoFilters();
    renderVideos();
  }

  function workflowReferenceName(channelId) {
    const item = state.workflowReferences.find((channel) => channel.youtube_channel_id === channelId);
    return item?.title || channelId || 'Chưa gắn workflow';
  }

  function populateManagedWorkflowSelect(select, includeEmpty = true) {
    if (!select) return;
    const selected = select.value;
    const empty = includeEmpty ? '<option value="">Chưa gắn workflow</option>' : '';
    select.innerHTML = empty + state.workflowReferences.map((channel) => `<option value="${esc(channel.youtube_channel_id)}">${esc(channel.title || channel.youtube_channel_id)}${channel.group_name ? ` · ${esc(channel.group_name)}` : ''}</option>`).join('');
    if (state.workflowReferences.some((channel) => channel.youtube_channel_id === selected)) select.value = selected;
  }

  function populateStudioManagedChannelSelect() {
    const select = $('studioManagedChannelSelect');
    if (!select) return;
    const selected = select.value;
    select.innerHTML = '<option value="">Chưa chọn kênh của tôi</option>' + state.managedChannels.map((channel) => `<option value="${channel.id}">${esc(channel.name)}${channel.group_name ? ` · ${esc(channel.group_name)}` : ''}</option>`).join('');
    if (state.managedChannels.some((channel) => String(channel.id) === selected)) select.value = selected;
    renderStudioManagedSummary();
  }

  function renderStudioManagedSummary() {
    const summary = $('studioWorkflowSummary');
    if (!summary) return;
    const channel = state.managedChannels.find((item) => String(item.id) === String($('studioManagedChannelSelect')?.value || ''));
    if (!channel) {
      summary.textContent = 'Chọn kênh của tôi để áp dụng workflow đã gắn.';
      return;
    }
    summary.innerHTML = `<b>${esc(channel.name)}</b> · ${esc(channel.output_profile)}<br><span>Workflow tham khảo: ${esc(channel.workflow_reference_title || workflowReferenceName(channel.workflow_reference_channel_id))}</span>`;
  }

  function resetManagedChannelForm() {
    $('managedChannelForm')?.reset();
    if ($('managedChannelId')) $('managedChannelId').value = '';
    if ($('managedChannelMessage')) $('managedChannelMessage').textContent = '';
    populateManagedWorkflowSelect($('managedChannelWorkflow'));
  }

  function editManagedChannel(channelId) {
    const channel = state.managedChannels.find((item) => Number(item.id) === Number(channelId));
    if (!channel) return;
    $('managedChannelId').value = channel.id;
    $('managedChannelName').value = channel.name || '';
    $('managedChannelUrl').value = channel.channel_url || '';
    $('managedChannelPlatform').value = channel.platform || 'youtube';
    $('managedChannelGroup').value = channel.group_name || '';
    $('managedChannelWorkflow').value = channel.workflow_reference_channel_id || '';
    $('managedChannelProfile').value = channel.output_profile || 'youtube_landscape';
    $('managedChannelLanguage').value = channel.language || 'vi';
    $('managedChannelTransition').value = channel.default_transition_style || 'fade';
    $('managedChannelVoiceProvider').value = channel.default_voice_provider || 'edge_tts';
    $('managedChannelVoiceModel').value = channel.default_voice_model || 'vi-VN-HoaiMyNeural';
    $('managedChannelSubtitleProvider').value = channel.default_subtitle_provider || 'timeline_text';
    $('managedChannelSubtitleModel').value = channel.default_subtitle_model || 'timeline';
    $('managedChannelNotes').value = channel.notes || '';
    $('managedScheduleEnabled').checked = Boolean(channel.schedule_enabled);
    $('managedScheduleFrequency').value = channel.schedule_frequency || 'weekly';
    $('managedScheduleTime').value = channel.schedule_time || '19:00';
    $('managedScheduleTimezone').value = channel.schedule_timezone || 'Asia/Bangkok';
    $('managedScheduleDays').value = channel.schedule_days || 'mon';
    $('managedDefaultPrivacy').value = channel.default_privacy || 'private';
    $('managedAutoUpload').checked = Boolean(channel.auto_upload);
    $('managedChannelMessage').textContent = `Đang chỉnh sửa ${channel.name}.`;
    $('managedChannelName').focus();
  }

  // A channel is set up here, so this is where its account is connected.
  // Buried in the publish dialog it was found only at the end, with a
  // finished video already in hand.
  // Signing in first and letting the account name the channel, rather than
  // typing a name and URL from memory into a form and only then finding out
  // whether it connects.
  function addChannelBySignIn() {
    window.open('/oauth/youtube/authorize', '_blank', 'noopener');
    setMessage(
      'Đã mở tab Google. Chọn tài khoản và kênh muốn thêm, xong quay lại đây bấm “Làm mới danh sách kênh”.',
      '');
  }

  async function refreshManagedChannels() {
    await loadManagedChannels();
    setMessage(`Đã làm mới: ${state.managedChannels.length} kênh.`, 'success');
  }

  function channelAccountRow(channel) {
    if (String(channel.platform || 'youtube').toLowerCase() !== 'youtube') {
      return '<div class="managed-card-meta">Nền tảng này chưa đăng tự động — app sẽ xuất gói để bạn đăng tay.</div>';
    }
    const account = (state.channelAccounts || {})[channel.id];
    if (account === undefined) {
      return `<div class="managed-card-meta">Tài khoản đăng: đang kiểm…</div>`;
    }
    if (!account.connected) {
      return `<div class="managed-card-meta">
        <span class="tag red">CHƯA ĐĂNG NHẬP</span>
        Kênh này chưa nối tài khoản Google nên chưa đăng được.
        <button class="btn small primary" style="margin-left:6px"
          onclick="connectManagedChannel(${channel.id})">Đăng nhập kênh này</button>
      </div>`;
    }
    const where = account.youtube_title
      ? `Đăng lên: <b>${esc(account.youtube_title)}</b>`
      : 'Đã đăng nhập';
    // Borrowing the app-wide account is not the same as having one, and two
    // channels quietly posting to the same place should not look like two.
    const borrowed = account.own_account === false
      ? ' <span class="tag">DÙNG CHUNG TÀI KHOẢN APP</span>' : '';
    return `<div class="managed-card-meta">
      <span class="tag green">ĐÃ NỐI</span> ${where}${borrowed}
      <button class="btn small ghost" style="margin-left:6px"
        onclick="connectManagedChannel(${channel.id})">Đổi tài khoản</button>
      <button class="btn small ghost" onclick="checkManagedChannelAccount(${channel.id})">Kiểm tra</button>
    </div>`;
  }

  async function loadManagedChannelAccounts() {
    const accounts = {};
    await Promise.all((state.managedChannels || []).map(async (channel) => {
      if (String(channel.platform || 'youtube').toLowerCase() !== 'youtube') return;
      try {
        const status = await api(`/api/oauth/youtube/status?managed_channel_id=${channel.id}`);
        accounts[channel.id] = {
          connected: Boolean(status.connected),
          own_account: status.own_account,
        };
      } catch (_) { accounts[channel.id] = {connected: false}; }
    }));
    state.channelAccounts = accounts;
    renderManagedChannels();
  }

  function connectManagedChannel(channelId) {
    window.open(`/oauth/youtube/authorize?managed_channel_id=${channelId}`, '_blank', 'noopener');
    setMessage('Đã mở tab Google. Chọn tài khoản và kênh, xong quay lại đây bấm “Kiểm tra”.', '');
  }

  // Signed in is not the same as signed in to the right channel: one Google
  // account can own several, and the consent screen asks which.
  async function checkManagedChannelAccount(channelId) {
    setMessage('Đang hỏi YouTube xem kênh này đăng lên đâu...', '');
    try {
      const result = await api(`/api/oauth/youtube/channels?managed_channel_id=${channelId}`);
      const first = (result.channels || [])[0];
      if (!first) { setMessage('Tài khoản này không có kênh YouTube nào.', 'error'); return; }
      state.channelAccounts = {
        ...(state.channelAccounts || {}),
        [channelId]: {connected: true, own_account: true, youtube_title: first.title},
      };
      renderManagedChannels();
      setMessage(`Kênh này sẽ đăng lên: ${first.title}`, 'success');
    } catch (error) { setMessage(error.message, 'error'); }
  }

  function renderManagedChannels() {
    const body = $('managedChannelsBody');
    if (!body) return;
    $('managedChannelCountLabel').textContent = `${state.managedChannels.length} KÊNH`;
    if (!state.managedChannels.length) {
      body.innerHTML = '<div class="empty">Chưa có kênh của tôi. Hãy thêm kênh ở biểu mẫu bên trái.</div>';
      return;
    }
    const groups = new Map();
    state.managedChannels.forEach((channel) => {
      const group = String(channel.group_name || '').trim() || 'Chưa gắn nhóm';
      if (!groups.has(group)) groups.set(group, []);
      groups.get(group).push(channel);
    });
    body.innerHTML = [...groups.entries()].map(([group, channels]) => `<div class="managed-card"><div class="eyebrow">${esc(group)}</div>${channels.map((channel) => `
      <div class="managed-card" style="margin-top:8px;background:rgba(9,11,16,.38)">
        <div class="managed-card-head"><div><div class="managed-card-title">${esc(channel.name)}</div><div class="managed-card-meta"><a href="${esc(channel.channel_url)}" target="_blank" rel="noreferrer">${esc(channel.channel_url)}</a><br>Nền tảng: ${esc(channel.platform || 'youtube')} · Định dạng: ${esc(channel.output_profile)} · Ngôn ngữ: ${esc(channel.language || 'vi')}<br>Preset: ${esc(channel.default_voice_provider || 'edge_tts')} · ${esc(channel.default_voice_model || '')} · ${esc(channel.default_subtitle_provider || 'timeline_text')}<br>Workflow tham khảo: <b>${esc(channel.workflow_reference_title || workflowReferenceName(channel.workflow_reference_channel_id))}</b>${channel.notes ? `<br>Ghi chú: ${esc(channel.notes)}` : ''}</div></div><span class="tag ${channel.enabled ? 'green' : 'red'}">${channel.enabled ? 'ĐANG DÙNG' : 'TẠM TẮT'}</span></div>
        ${channelAccountRow(channel)}
        <div class="managed-card-actions"><button class="btn small ghost" onclick="editManagedChannel(${channel.id})">Chỉnh sửa</button><button class="btn small ${channel.enabled ? 'danger' : 'primary'}" onclick="toggleManagedChannel(${channel.id}, ${!channel.enabled})">${channel.enabled ? 'Tạm tắt' : 'Bật lại'}</button></div>
      </div>`).join('')}</div>`).join('');
  }

  async function loadManagedChannels() {
    const [managed, references] = await Promise.all([api('/api/managed-channels'), api('/api/workflow-reference-channels')]);
    state.managedChannels = managed;
    state.workflowReferences = references;
    populateManagedWorkflowSelect($('managedChannelWorkflow'));
    populateStudioManagedChannelSelect();
    renderManagedChannels();
    void loadManagedChannelAccounts();
  }

  async function saveManagedChannel(event) {
    event.preventDefault();
    const id = $('managedChannelId').value;
    const payload = {
      name: $('managedChannelName').value.trim(),
      channel_url: $('managedChannelUrl').value.trim(),
      platform: $('managedChannelPlatform').value,
      group_name: $('managedChannelGroup').value.trim(),
      workflow_reference_channel_id: $('managedChannelWorkflow').value || '',
      output_profile: $('managedChannelProfile').value,
      language: $('managedChannelLanguage').value,
      default_transition_style: $('managedChannelTransition').value,
      default_voice_provider: $('managedChannelVoiceProvider').value,
      default_voice_model: $('managedChannelVoiceModel').value.trim(),
      default_subtitle_provider: $('managedChannelSubtitleProvider').value,
      default_subtitle_model: $('managedChannelSubtitleModel').value.trim(),
      notes: $('managedChannelNotes').value.trim(),
      schedule_enabled: $('managedScheduleEnabled').checked,
      schedule_frequency: $('managedScheduleFrequency').value,
      schedule_time: $('managedScheduleTime').value,
      schedule_timezone: $('managedScheduleTimezone').value,
      schedule_days: $('managedScheduleDays').value.trim(),
      default_privacy: $('managedDefaultPrivacy').value,
      auto_upload: $('managedAutoUpload').checked,
    };
    const message = $('managedChannelMessage');
    try {
      const response = await api(id ? `/api/managed-channels/${id}` : '/api/managed-channels', {method: id ? 'PATCH' : 'POST', body: JSON.stringify(payload)});
      message.textContent = id ? 'Đã cập nhật kênh.' : 'Đã thêm kênh của tôi.';
      message.className = 'message success';
      resetManagedChannelForm();
      await loadManagedChannels();
      setMessage(`Đã lưu ${response.channel.name}.`, 'success');
    } catch (error) {
      message.textContent = error.message;
      message.className = 'message error';
    }
  }

  async function toggleManagedChannel(channelId, enabled) {
    try {
      await api(`/api/managed-channels/${channelId}`, {method: 'PATCH', body: JSON.stringify({enabled})});
      await loadManagedChannels();
      setMessage(enabled ? 'Đã bật kênh xuất bản.' : 'Đã tạm tắt kênh xuất bản.', 'success');
    } catch (error) { setMessage(error.message, 'error'); }
  }

  // ---- Nguồn tham khảo: NGUỒN / KÊNH / HÀNG ĐỢI / THƯ VIỆN ----
  const SOURCE_TABS = ['sources', 'channels', 'queue', 'library'];

  function currentSourceTab() {
    if (!SOURCE_TABS.includes(state.sourceTab)) {
      let saved = '';
      try { saved = localStorage.getItem('ytFactory.sourceTab') || ''; } catch (_) {}
      state.sourceTab = SOURCE_TABS.includes(saved) ? saved : 'channels';
    }
    return state.sourceTab;
  }

  function applySourceTab() {
    if (state.workspace !== 'source') return;
    const tab = currentSourceTab();
    document.querySelectorAll('[data-source-tab]').forEach((panel) => { panel.hidden = panel.dataset.sourceTab !== tab; });
    document.querySelectorAll('[data-source-tab-button]').forEach((button) => {
      const active = button.dataset.sourceTabButton === tab;
      button.classList.toggle('active', active);
      button.setAttribute('aria-selected', String(active));
    });
    // The saved-sources list is one read of the database; nothing is fetched from outside.
    if (tab === 'sources') void loadSources();
  }

  function setSourceTab(tab) {
    state.sourceTab = SOURCE_TABS.includes(tab) ? tab : 'channels';
    try { localStorage.setItem('ytFactory.sourceTab', state.sourceTab); } catch (_) {}
    applySourceTab();
  }

  // ---- Tab NGUỒN: một ô cho link hoặc file ----
  // Không chọn loại trước. Server (source_detector) nhận dạng; thêm nguồn đi
  // qua đúng importer đã có: đồng bộ kênh, nhập link, tải file lên, ảnh vào dự án.
  function openAddSource() {
    setSourceTab('sources');
    const input = $('sourceInput');
    input?.scrollIntoView({block: 'center'});
    input?.focus();
  }

  const SOURCE_KIND_LABELS = {
    youtube_channel: 'Kênh YouTube', channel: 'Kênh', video: 'Video', audio: 'Audio', product: 'Sản phẩm',
    article: 'Bài viết', web: 'Trang web', image: 'Ảnh', image_collection: 'Bộ ảnh',
    invalid: 'Không phải link', unsupported: 'Chưa hỗ trợ',
  };
  const SOURCE_KIND_ICONS = {
    video: '▶', audio: '♪', product: '🛍', article: '🌐', web: '🌐', image: '🖼', image_collection: '🖼',
    youtube_channel: '◎', channel: '◎', unsupported: '⚠', invalid: '⚠',
  };
  const SOURCE_PLATFORM_LABELS = {
    shopee: 'Shopee', tiktok_shop: 'TikTok Shop', lazada: 'Lazada', tiki: 'Tiki', sendo: 'Sendo',
    amazon: 'Amazon', aliexpress: 'AliExpress', taobao: 'Taobao', shein: 'Shein', temu: 'Temu',
    vimeo: 'Vimeo', dailymotion: 'Dailymotion', local: 'Máy của bạn', shop: 'Sàn thương mại',
  };
  const SOURCE_GROUPS = [['all', 'Tất cả'], ['video', 'Video'], ['article', 'Bài viết'], ['product', 'Sản phẩm'], ['file', 'Ảnh/File']];
  const SOURCE_STATUS = {
    detected: ['Đã nhận dạng', 'green'], unreadable: ['Không đọc được nguồn', 'orange'],
    invalid: ['Không đọc được nguồn', 'orange'], need_connection: ['Cần đăng nhập/kết nối', 'orange'],
  };

  function sourcePlatformLabel(key) {
    return SOURCE_PLATFORM_LABELS[key] || PLATFORM_LABELS[key] || (key ? key.charAt(0).toUpperCase() + key.slice(1) : '');
  }

  function clockText(seconds) {
    const total = Math.round(Number(seconds) || 0);
    if (!total) return '';
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = String(total % 60).padStart(2, '0');
    return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${String(m).padStart(2, '0')}:${s}`;
  }

  function sizeText(bytes) {
    const value = Number(bytes) || 0;
    return value >= 1048576 ? `${(value / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(value / 1024))} KB`;
  }

  // "Video YouTube", "Sản phẩm · Shopee", "Bài viết · VnExpress": what it is and where from.
  function sourceHeading(item) {
    const meta = item.metadata || {};
    const platform = sourcePlatformLabel(item.platform);
    if (item.kind === 'video' && item.origin === 'file') return 'Video từ máy';
    if (item.kind === 'audio') return 'Audio từ máy';
    if (item.kind === 'video') return meta.is_short ? `Shorts · ${platform}` : `Video ${platform}`.trim();
    if (item.kind === 'youtube_channel') return 'Kênh YouTube';
    if (item.kind === 'channel') return `Kênh ${platform}`.trim();
    if (item.kind === 'product') return `Sản phẩm · ${meta.marketplace || platform || 'Trang bán hàng'}`;
    if (item.kind === 'article') return `Bài viết · ${meta.site_name || meta.domain || platform}`;
    if (item.kind === 'web') return `Trang web · ${meta.site_name || meta.domain || ''}`.replace(/ · $/, '');
    if (item.kind === 'image_collection') return `Bộ ảnh · ${number(meta.file_count)} ảnh`;
    return SOURCE_KIND_LABELS[item.kind] || 'Nguồn';
  }

  // Only what was actually read; a missing field is left out, never guessed.
  function sourceFacts(item) {
    const meta = item.metadata || {};
    const facts = [];
    if (item.origin === 'file') {
      const files = meta.files || [];
      facts.push(files.slice(0, 4).map((file) => file.name).join(', ') + (files.length > 4 ? ` và ${files.length - 4} file khác` : ''));
      facts.push(sizeText(meta.total_size));
      return facts.filter(Boolean);
    }
    if (item.kind === 'youtube_channel') {
      facts.push([item.native_id, meta.handle].filter(Boolean).join(' · '));
      if (meta.subscriber_count != null) facts.push(`${compactNumber(meta.subscriber_count)} người đăng ký`);
      if (meta.video_count != null) facts.push(`${number(meta.video_count)} video`);
    } else if (item.kind === 'video') {
      if (meta.channel_name) facts.push(`Kênh: ${meta.channel_name}`);
      if (meta.author && !meta.channel_name) facts.push(`Tác giả: ${meta.author}`);
      if (clockText(meta.duration_seconds)) facts.push(clockText(meta.duration_seconds));
      if (meta.view_count != null) facts.push(`${compactNumber(meta.view_count)} lượt xem`);
    } else if (item.kind === 'product') {
      if (meta.seller) facts.push(meta.seller);
      if (meta.price_text) facts.push(`Giá hiện tại: ${meta.price_text}${meta.captured_at ? ` (đọc lúc ${date(meta.captured_at)})` : ''}`);
      if (meta.rating) facts.push(`${meta.rating} ★`);
      if (meta.sold_count) facts.push(`Đã bán ${meta.sold_count}`);
    } else if (['article', 'web'].includes(item.kind)) {
      if (meta.domain) facts.push(meta.domain);
      if (meta.published_at) facts.push(date(meta.published_at));
    }
    return facts.filter(Boolean);
  }

  async function detectSourceLink() {
    const text = ($('sourceInput')?.value || '').trim();
    if (!text) { $('sourceInput')?.focus(); return; }
    const ticket = beginSourcePreview();
    try {
      // The link's shape first - instant - then what the source says about itself.
      const quick = await api('/api/sources/detect', {method: 'POST', body: JSON.stringify({text, probe: false})});
      if (state.sourceTicket !== ticket) return;
      const reading = quick.status === 'detected';
      state.sourcePreview = {phase: reading ? 'reading' : 'done', items: [quick], files: []};
      renderSourcePreview();
      if (!reading) return;
      const full = await api('/api/sources/detect', {method: 'POST', body: JSON.stringify({text, probe: true})});
      if (state.sourceTicket !== ticket) return;
      state.sourcePreview = {phase: 'done', items: [full], files: []};
    } catch (error) {
      if (state.sourceTicket !== ticket) return;
      state.sourcePreview = {phase: 'error', items: [], files: [], error: error.message};
    }
    renderSourcePreview();
  }

  function beginSourcePreview() {
    clearSourcePreview();
    state.sourceTicket = (state.sourceTicket || 0) + 1;
    state.sourcePreview = {phase: 'detecting', items: [], files: []};
    renderSourcePreview();
    return state.sourceTicket;
  }

  function clearSourcePreview() {
    (state.sourceObjectUrls || []).forEach((url) => URL.revokeObjectURL(url));
    state.sourceObjectUrls = [];
    state.sourcePreview = null;
  }

  function cancelSourcePreview() {
    state.sourceTicket = (state.sourceTicket || 0) + 1;
    clearSourcePreview();
    renderSourcePreview();
  }

  function pickSourceFiles(input) {
    const files = [...(input.files || [])];
    input.value = '';
    if (files.length) void detectSourceFiles(files.map((file) => ({file, path: file.webkitRelativePath || ''})));
  }

  function sourceDragOver(event) {
    event.preventDefault();
    $('sourceDropZone')?.classList.add('dragging');
  }

  function sourceDragLeave(event) {
    if (!event.currentTarget.contains(event.relatedTarget)) $('sourceDropZone')?.classList.remove('dragging');
  }

  async function sourceDrop(event) {
    event.preventDefault();
    $('sourceDropZone')?.classList.remove('dragging');
    const transfer = event.dataTransfer;
    if (!transfer) return;
    // A folder is opened where the browser allows it: every file in it, with its path.
    const entries = [...(transfer.items || [])]
      .map((item) => (item.kind === 'file' && item.webkitGetAsEntry ? item.webkitGetAsEntry() : null)).filter(Boolean);
    const picked = entries.length
      ? (await Promise.all(entries.map((entry) => readDroppedEntry(entry, '')))).flat()
      : [...(transfer.files || [])].map((file) => ({file, path: ''}));
    if (picked.length) return detectSourceFiles(picked);
    // A link dragged in from another tab arrives as text.
    const text = (transfer.getData('text/uri-list') || transfer.getData('text/plain') || '')
      .split('\n').map((line) => line.trim()).find((line) => line && !line.startsWith('#'));
    if (text) {
      $('sourceInput').value = text;
      return detectSourceLink();
    }
  }

  async function readDroppedEntry(entry, prefix) {
    if (entry.isFile) {
      return new Promise((resolve) => entry.file((file) => resolve([{file, path: prefix + file.name}]), () => resolve([])));
    }
    if (!entry.isDirectory) return [];
    const reader = entry.createReader();
    const children = [];
    for (;;) {
      const batch = await new Promise((resolve) => reader.readEntries(resolve, () => resolve([])));
      if (!batch.length) break;
      children.push(...batch);
    }
    return (await Promise.all(children.map((child) => readDroppedEntry(child, `${prefix}${entry.name}/`)))).flat();
  }

  async function detectSourceFiles(picked) {
    // The same file picked twice counts once.
    const seen = new Set();
    const chosen = picked.filter(({file}) => {
      const key = `${file.name}|${file.size}|${file.lastModified}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    const ticket = beginSourcePreview();
    try {
      const body = {files: chosen.map(({file, path}, index) => ({index, name: file.name, type: file.type || '', size: file.size, path}))};
      const result = await api('/api/sources/detect-files', {method: 'POST', body: JSON.stringify(body)});
      if (state.sourceTicket !== ticket) return;
      state.sourcePreview = {phase: 'done', items: result.sources || [], files: chosen.map(({file}) => file)};
    } catch (error) {
      if (state.sourceTicket !== ticket) return;
      state.sourcePreview = {phase: 'error', items: [], files: [], error: error.message};
    }
    renderSourcePreview();
  }

  function canAddSource(item) {
    return ['add_channel', 'open_channel', 'add_source', 'upload'].includes(item.suggested_action);
  }

  // A picture from the machine is shown from the browser's own copy; nothing is uploaded to preview it.
  function localPreviewUrl(item, files) {
    const entry = (item.metadata?.files || []).find((file) => /^image\//.test(file.type) || /\.(jpe?g|png|webp|gif|bmp)$/i.test(file.name));
    const file = entry ? files[entry.index] : null;
    if (!file) return '';
    const url = URL.createObjectURL(file);
    (state.sourceObjectUrls = state.sourceObjectUrls || []).push(url);
    return url;
  }

  function sourcePreviewCard(item, files) {
    const icon = SOURCE_KIND_ICONS[item.kind] || '•';
    const picture = item.origin === 'file' ? localPreviewUrl(item, files) : item.thumbnail;
    const [statusText, tone] = SOURCE_STATUS[item.status] || SOURCE_STATUS.detected;
    const existing = item.existing?.channel_id ? 'Kênh này đã có trong danh sách kênh.'
      : item.existing?.video_id ? (item.existing.is_source ? 'Nguồn này đã có trong danh sách.' : 'Đã có trong kho video; thêm sẽ dùng lại bản ghi đó.') : '';
    const facts = sourceFacts(item);
    return `<article class="source-card ${item.status !== 'detected' ? 'is-warn' : ''}">
        <div class="source-thumb large"><span aria-hidden="true">${icon}</span>${picture ? `<img src="${esc(picture)}" alt="" onerror="this.hidden=true">` : ''}</div>
        <div class="source-card-body">
          <div class="source-card-kind">${esc(sourceHeading(item))} <span class="tag ${tone}">${esc(statusText)}</span></div>
          ${item.title ? `<div class="source-card-title">${esc(item.title)}</div>` : ''}
          ${facts.length ? `<div class="source-card-facts">${facts.map((fact) => `<span>${esc(fact)}</span>`).join('')}</div>` : ''}
          ${item.message ? `<div class="source-card-note">${esc(item.message)}</div>` : ''}
          ${existing ? `<div class="source-card-note">${esc(existing)}</div>` : ''}
        </div>
      </article>`;
  }

  function renderSourcePreview() {
    const target = $('sourcePreview');
    if (!target) return;
    const preview = state.sourcePreview;
    if (!preview) { target.hidden = true; target.innerHTML = ''; return; }
    target.hidden = false;
    const cancel = `<button class="btn ghost" type="button" onclick="cancelSourcePreview()">Hủy</button>`;
    if (preview.phase === 'detecting') {
      target.innerHTML = `<div class="source-status"><span class="source-spinner" aria-hidden="true"></span> Đang nhận dạng…</div>`;
      return;
    }
    if (preview.phase === 'error') {
      target.innerHTML = `<div class="source-status warn">Không đọc được nguồn. ${esc(preview.error || '')}</div><div class="source-actions">${cancel}</div>`;
      return;
    }
    if (preview.phase === 'added') {
      const added = preview.added || [];
      const one = added.length === 1 && added[0].video_id ? added[0] : null;
      target.innerHTML = `<div class="source-status ok">✓ ${added.length ? `Đã thêm ${esc(added.map((item) => item.reused ? `${item.title} (đã có sẵn)` : item.title).join(', '))}.` : 'Chưa thêm được nguồn nào.'}</div>
        ${(preview.failed || []).map((line) => `<div class="source-card-note warn">${esc(line)}</div>`).join('')}
        <div class="source-actions">${cancel.replace('Hủy', 'Đóng')}${one ? `<button class="btn primary" type="button" onclick="useSource('${esc(one.video_id)}')">Dùng để tạo video →</button>` : ''}</div>`;
      return;
    }
    const items = preview.items || [];
    const addable = items.filter(canAddSource);
    const reading = preview.phase === 'reading';
    const needsConnection = items.some((item) => item.status === 'need_connection');
    let label = addable.length > 1 ? `Thêm ${addable.length} nguồn` : 'Thêm nguồn';
    if (addable.length === 1 && addable[0].suggested_action === 'add_channel') label = 'Thêm kênh & đồng bộ';
    if (addable.length === 1 && addable[0].suggested_action === 'open_channel') label = 'Mở kênh';
    target.innerHTML = `
      ${reading ? `<div class="source-status"><span class="source-spinner" aria-hidden="true"></span> Đang đọc thông tin…</div>` : ''}
      <div class="source-cards">${items.map((item) => sourcePreviewCard(item, preview.files || [])).join('')}</div>
      <div class="source-actions">
        ${cancel}
        ${needsConnection ? `<button class="btn ghost" type="button" onclick="setWorkspace('settings')">Mở Công cụ & kết nối</button>` : ''}
        ${addable.length ? `<button class="btn primary" type="button" onclick="addDetectedSources()" ${reading || preview.busy ? 'disabled' : ''}>${preview.busy ? 'Đang thêm…' : esc(label)}</button>` : ''}
      </div>`;
  }

  async function addDetectedSources() {
    const preview = state.sourcePreview;
    if (!preview || preview.busy || preview.phase !== 'done') return;
    const items = preview.items.filter(canAddSource);
    if (!items.length) return;
    // A channel already followed is opened, not added again.
    if (items.length === 1 && items[0].suggested_action === 'open_channel') {
      return openDetectedChannel(items[0].existing?.channel_id || items[0].native_id);
    }
    preview.busy = true;
    renderSourcePreview();
    const added = [];
    const failed = [];
    for (const item of items) {
      try {
        if (item.origin === 'file') added.push(...await importSourceFiles(item, preview.files || []));
        else added.push(await importSourceLink(item));
      } catch (error) {
        failed.push(`${item.title || SOURCE_KIND_LABELS[item.kind] || 'Nguồn'}: ${error.message}`);
      }
    }
    const channel = added.find((item) => item.channel_id);
    if (channel && added.length === 1 && !failed.length) {
      setMessage(channel.status === 'exists' ? 'Kênh đã có trong danh sách.' : `Đã thêm kênh “${channel.title}” và đồng bộ video.`, 'success');
      return openDetectedChannel(channel.channel_id);
    }
    clearSourcePreview();
    state.sourcePreview = {phase: 'added', added, failed};
    if ($('sourceInput') && added.length && !failed.length) $('sourceInput').value = '';
    setMessage(failed.length ? `Đã thêm ${added.length} nguồn; ${failed.length} nguồn lỗi.` : `Đã thêm ${added.length} nguồn.`, failed.length ? 'error' : 'success');
    renderSourcePreview();
    await Promise.all([loadSources(), loadVideos().catch(() => {})]);
  }

  async function importSourceLink(item) {
    setMessage(item.kind === 'youtube_channel' ? 'Đang thêm kênh và đồng bộ video…' : 'Đang thêm nguồn…');
    const result = await api('/api/sources/import', {method: 'POST', body: JSON.stringify({text: item.url})});
    return {
      kind: result.kind, status: result.status, video_id: result.video?.youtube_video_id || '',
      channel_id: result.channel_id || '', title: result.video?.title || result.channel?.title || item.title || item.url,
      reused: Boolean(result.reused_row || result.status === 'exists'),
    };
  }

  // Files go where the server's router said (item.route); the bytes never left
  // the browser before this. "upload": each video or audio file its own source,
  // through the upload that already existed. "image_collection": one collection,
  // its pictures sent with the project's own asset upload.
  async function importSourceFiles(item, files) {
    const chosen = (item.metadata?.files || []).map((entry) => files[entry.index]).filter(Boolean);
    if (!['upload', 'image_collection'].includes(item.route)) throw new Error('Loại file này chưa thêm được.');
    if (item.route === 'image_collection') {
      const created = await api('/api/sources/image-collection', {method: 'POST', body: JSON.stringify({title: item.title})});
      const projectId = created.project?.id;
      let uploaded = 0;
      const problems = [];
      for (const [index, file] of chosen.entries()) {
        setMessage(`Đang tải ảnh ${index + 1}/${chosen.length}: ${file.name}`);
        const form = new FormData();
        form.append('asset_type', 'image');
        form.append('file', file);
        const response = await fetch(`/api/projects/${projectId}/assets/upload`, {method: 'POST', body: form});
        if (response.ok) uploaded += 1;
        else problems.push(apiError(await response.json().catch(() => ({})), response).message);
      }
      if (!uploaded) throw new Error(problems[0] || 'Không tải được ảnh nào.');
      const note = problems.length ? ` (${problems.length} ảnh lỗi)` : '';
      return [{kind: item.kind, video_id: created.video_id, project_id: projectId, title: `${item.title} · ${uploaded} ảnh${note}`}];
    }
    const results = [];
    for (const file of chosen) {
      setMessage(`Đang tải "${file.name}" lên (${sizeText(file.size)})…`);
      const form = new FormData();
      form.append('file', file);
      // FormData đặt Content-Type kèm boundary; helper api() ép JSON nên không dùng được.
      const response = await fetch('/api/uploads/source', {method: 'POST', body: form});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw apiError(data, response);
      results.push({kind: item.kind, video_id: data.video?.youtube_video_id || '', title: data.video?.title || file.name, reused: data.status === 'duplicate'});
    }
    return results;
  }

  // A channel belongs in KÊNH, never in this list: open it there, selected.
  async function openDetectedChannel(channelId) {
    clearSourcePreview();
    renderSourcePreview();
    state.selectedChannel = channelId;
    try { localStorage.setItem('ytFactory.selectedChannel', channelId); } catch (_) {}
    setSourceTab('channels');
    await loadChannels();
    $('channelWorkspace')?.classList.add('is-detail-open');
  }

  async function loadSources() {
    try {
      const data = await api('/api/sources');
      state.sources = data.items || [];
      state.sourceCounts = data.counts || {};
      state.sourcesError = '';
    } catch (error) {
      state.sourcesError = error.message;
    }
    renderSourceList();
  }

  function currentSourceGroup() {
    if (!state.sourceGroup) {
      let saved = '';
      try { saved = localStorage.getItem('ytFactory.sourceGroup') || ''; } catch (_) {}
      state.sourceGroup = SOURCE_GROUPS.some(([key]) => key === saved) ? saved : 'all';
    }
    return state.sourceGroup;
  }

  function setSourceGroup(group) {
    state.sourceGroup = SOURCE_GROUPS.some(([key]) => key === group) ? group : 'all';
    try { localStorage.setItem('ytFactory.sourceGroup', state.sourceGroup); } catch (_) {}
    renderSourceList();
  }

  function sourceRowMeta(item) {
    const platform = sourcePlatformLabel(item.platform);
    if (item.group === 'file') {
      if (item.kind === 'image_collection') return `${item.image_count > 1 ? 'Bộ ảnh' : 'Ảnh'} · ${number(item.image_count)} ảnh`;
      return [item.kind === 'audio' ? 'Audio từ máy' : 'Video từ máy', clockText(item.duration_seconds)].filter(Boolean).join(' · ');
    }
    if (item.kind === 'product') return [platform || 'Sản phẩm', item.price_text].filter(Boolean).join(' · ');
    if (item.kind === 'video') return [item.is_short ? `${platform} Shorts` : platform, item.site, clockText(item.duration_seconds)].filter(Boolean).join(' · ');
    return item.site || platform || 'Trang web';
  }

  function sourceRow(item) {
    const icon = SOURCE_KIND_ICONS[item.kind] || '•';
    const analyze = item.analyzing ? '<span class="tag cyan">Đang phân tích</span>'
      : item.analyzed ? '<span class="tag green">Đã phân tích</span>' : '';
    return `<div class="source-row">
        <div class="source-thumb"><span aria-hidden="true">${icon}</span>${item.thumbnail_url ? `<img src="${esc(item.thumbnail_url)}" alt="" loading="lazy" onerror="this.hidden=true">` : ''}</div>
        <div class="source-row-main">
          <div class="source-row-title clamp" title="${esc(item.title)}">${esc(item.title)}</div>
          <div class="source-row-meta">${item.group === 'file' ? '' : `<span class="source-kind-label">${esc(SOURCE_KIND_LABELS[item.kind] || 'Nguồn')}</span> `}${esc(sourceRowMeta(item))}</div>
        </div>
        <div class="source-row-side">${analyze}<span class="secondary-text">${item.added_at ? esc(date(item.added_at)) : ''}</span></div>
        <button type="button" class="channel-menu-button" aria-label="Thao tác" onclick="event.stopPropagation(); openSourceMenu('${esc(item.video_id)}', this)">⋯</button>
      </div>`;
  }

  function renderSourceList() {
    const filters = $('sourceFilters');
    const list = $('sourceList');
    if (!filters || !list) return;
    const counts = state.sourceCounts || {};
    const group = currentSourceGroup();
    filters.innerHTML = SOURCE_GROUPS.map(([key, label]) => `<button type="button" role="tab" class="source-filter ${key === group ? 'active' : ''}" aria-selected="${key === group}" onclick="setSourceGroup('${key}')">${label} <b>${number(counts[key] || 0)}</b></button>`).join('');
    if (state.sourcesError) {
      list.innerHTML = `<div class="empty">Chưa tải được danh sách nguồn. ${esc(state.sourcesError)}</div>`;
      return;
    }
    const items = (state.sources || []).filter((item) => group === 'all' || item.group === group);
    list.innerHTML = items.length ? items.map(sourceRow).join('')
      : `<div class="empty">${(state.sources || []).length ? 'Không có nguồn nào trong mục này.' : 'Chưa có nguồn nào. Dán link hoặc thả file ở trên để thêm.'}</div>`;
  }

  // ⋯: only actions that already exist elsewhere in the app.
  function openSourceMenu(videoId, button) {
    closeSourceMenu();
    const item = (state.sources || []).find((source) => source.video_id === videoId);
    if (!item) return;
    const actions = [
      ['Dùng để tạo video', `useSource('${esc(videoId)}')`],
      item.project_id ? ['Mở dự án', `openProjectDetail(${Number(item.project_id)})`] : null,
      item.url ? ['Mở trang gốc', `window.open('${esc(item.url)}', '_blank', 'noopener')`] : null,
      item.url ? ['Sao chép link', `copySourceLink('${esc(videoId)}')`] : null,
    ].filter(Boolean);
    const menu = document.createElement('div');
    menu.id = 'sourceMenu';
    menu.className = 'channel-menu';
    menu.setAttribute('role', 'menu');
    menu.innerHTML = actions.map(([label, action]) => `<button type="button" role="menuitem" onclick="closeSourceMenu(); ${action}">${esc(label)}</button>`).join('');
    document.body.appendChild(menu);
    const box = button.getBoundingClientRect();
    menu.style.top = `${window.scrollY + box.bottom + 4}px`;
    menu.style.left = `${window.scrollX + Math.max(8, box.right - menu.offsetWidth)}px`;
    setTimeout(() => document.addEventListener('click', closeSourceMenu, {once: true}), 0);
  }

  function closeSourceMenu() {
    document.getElementById('sourceMenu')?.remove();
  }

  async function copySourceLink(videoId) {
    const item = (state.sources || []).find((source) => source.video_id === videoId);
    try {
      await navigator.clipboard.writeText(item?.url || '');
      setMessage('Đã sao chép link.', 'success');
    } catch (_) {
      setMessage('Không sao chép được link.', 'error');
    }
  }

  // Bước 1 chọn nguồn từ kho video; một bộ ảnh đã là dự án nên mở thẳng dự án đó.
  async function useSource(videoId) {
    const item = (state.sources || []).find((source) => source.video_id === videoId);
    if (item?.kind === 'image_collection' && item.project_id) return resumeStudioProject(item.project_id);
    if (!state.videoCatalog?.some((video) => video.youtube_video_id === videoId)) await loadVideos();
    return startStudioFromVideo(videoId);
  }

  // ---- Tab KÊNH: danh sách bên trái, chi tiết bên phải ----
  // Mở tab, chọn kênh, đổi tab con: chỉ ĐỌC (GET). Chỉ “Cập nhật nghiên cứu”
  // mới chạy engine - cùng engine mà bước Kế hoạch dùng.
  const CHANNEL_RESEARCH_POLL_MS = 2500;
  const RESEARCH_TONE = {fresh: 'green', stale: 'orange', partial: 'orange', running: 'cyan'};
  const RESEARCH_RESULT = {
    new: 'nghiên cứu lần đầu', reused: 'dùng lại hồ sơ còn mới',
    incremental: 'cập nhật phần video mới', refreshed: 'nghiên cứu lại toàn bộ',
  };
  const PLATFORM_LABELS = {
    youtube: 'YouTube', tiktok: 'TikTok', facebook: 'Facebook', instagram: 'Instagram', bilibili: 'Bilibili',
    web: 'Trang web', shop: 'Sàn thương mại', upload: 'Tệp tải lên', idea: 'Ý tưởng',
  };
  const CHANNEL_STATUS_FILTERS = [
    ['fresh', 'Mới cập nhật'], ['stale', 'Cần cập nhật'], ['partial', 'Nghiên cứu chưa đầy đủ'],
    ['none', 'Chưa nghiên cứu'], ['running', 'Đang nghiên cứu'], ['paused', 'Tạm dừng giám sát'],
  ];
  const YOUTUBE_CHANNEL = /^UC[\w-]{22}$/;

  async function loadChannels() {
    state.channels = await api('/api/channels');
    populateChannelSelect($('analysisChannelSelect'));
    populateChannelSelect($('transcriptChannelSelect'));
    populateStudioSourceChannelSelect();
    populateVideoFilters();
    renderChannelFilters();
    // A remembered pick may be an old synthetic row: show its channel instead.
    let wanted = state.selectedChannel;
    if (!wanted) {
      try { wanted = localStorage.getItem('ytFactory.selectedChannel') || ''; } catch (_) {}
    }
    state.selectedChannel = primaryChannelKey(wanted) || filteredChannels()[0]?.youtube_channel_id || null;
    renderChannelList();
    if (state.selectedChannel) void loadChannelDetail(state.selectedChannel);
    else renderChannelDetail(null);
    shownChannels().filter((item) => item.research?.state === 'running').forEach((item) => followChannelResearch(item.youtube_channel_id));
  }

  // Rows the list shows: one per real channel. Every row stays in
  // state.channels for the pickers and filters that need the old ones.
  function shownChannels() {
    return state.channels.filter((channel) => channel.display?.primary !== false);
  }

  function primaryChannelKey(channelId) {
    const channel = state.channels.find((item) => item.youtube_channel_id === channelId);
    return channel ? (channel.display?.primary_key || channel.youtube_channel_id) : '';
  }

  function channelPlatform(channel) {
    return channel?.identity?.platform || 'web';
  }

  function platformLabel(platform) {
    return PLATFORM_LABELS[platform] || platform || '—';
  }

  function channelAvatar(url, title, size = 'md') {
    const initials = String(title || '?').trim().split(/\s+/).slice(0, 2).map((word) => word[0] || '').join('').toUpperCase() || '?';
    return url
      ? `<img class="channel-avatar ${size}" src="${esc(url)}" alt="" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('span'), {className: 'channel-avatar ${size} initials', textContent: '${esc(initials)}'}))">`
      : `<span class="channel-avatar ${size} initials" aria-hidden="true">${esc(initials)}</span>`;
  }

  function monitoringBadge(channel) {
    if (!channel.tracking_enabled) return '<span class="status-badge red">Tạm dừng</span>';
    if (channel.sync_status === 'error') return '<span class="status-badge red">Lỗi đồng bộ</span>';
    return '<span class="status-badge green">Hoạt động</span>';
  }

  function researchBadge(research) {
    const item = research || {};
    return `<span class="status-badge ${RESEARCH_TONE[item.state] || ''}">${esc(item.label || 'Chưa nghiên cứu')}</span>`;
  }

  function coverageLine(coverage) {
    const parts = [];
    if (coverage?.videos) parts.push(`${number(coverage.videos)} video`);
    if (coverage?.comments_sampled) parts.push(`${number(coverage.comments_sampled)} comment mẫu`);
    return parts.join(' · ');
  }

  function renderChannelFilters() {
    const platform = $('channelPlatformFilter');
    if (platform) {
      const chosen = platform.value;
      const present = [...new Set(shownChannels().map(channelPlatform))].sort();
      platform.innerHTML = '<option value="">Tất cả nền tảng</option>'
        + present.map((key) => `<option value="${esc(key)}">${esc(platformLabel(key))}</option>`).join('');
      platform.value = present.includes(chosen) ? chosen : '';
    }
    const status = $('channelStatusFilter');
    if (status && status.options.length <= 1) {
      status.innerHTML = '<option value="">Tất cả trạng thái</option>'
        + CHANNEL_STATUS_FILTERS.map(([key, label]) => `<option value="${key}">${label}</option>`).join('');
    }
  }

  function filteredChannels() {
    const query = ($('channelSearch')?.value || '').trim().toLowerCase();
    const platform = $('channelPlatformFilter')?.value || '';
    const status = $('channelStatusFilter')?.value || '';
    return shownChannels()
      .filter((channel) => !query || `${channel.title} ${channel.youtube_channel_id} ${channel.identity?.native_channel_id || ''}`.toLowerCase().includes(query))
      .filter((channel) => !platform || channelPlatform(channel) === platform)
      .filter((channel) => !status || (status === 'paused' ? !channel.tracking_enabled : channel.research?.state === status))
      .sort((left, right) => String(right.research?.updated_at || '').localeCompare(String(left.research?.updated_at || ''))
        || String(left.title || '').localeCompare(String(right.title || ''), 'vi'));
  }

  function renderChannelList() {
    const list = $('channelList');
    if (!list) return;
    const channels = filteredChannels();
    const total = shownChannels().length;
    $('channelCountLabel').textContent = `${channels.length}${channels.length !== total ? `/${total}` : ''} kênh`;
    if (!total) {
      list.innerHTML = '<div class="empty">Chưa có kênh nào. Bấm “Thêm kênh” để bắt đầu.</div>';
      return;
    }
    if (!channels.length) {
      list.innerHTML = '<div class="empty">Không có kênh khớp bộ lọc.</div>';
      return;
    }
    list.innerHTML = channels.map((channel) => {
      const key = channel.youtube_channel_id;
      const identity = channel.identity || {};
      const coverage = coverageLine(channel.research?.coverage);
      const selected = key === state.selectedChannel;
      return `<article class="channel-card${selected ? ' selected' : ''}" role="option" aria-selected="${selected}" tabindex="0"
          onclick="selectChannel('${esc(key)}')" onkeydown="if (event.key === 'Enter') selectChannel('${esc(key)}')">
        ${channelAvatar(channel.avatar_url || channel.thumbnail_url, channel.title)}
        <div class="channel-card-body">
          <div class="channel-card-title">${esc(channel.title || key)}</div>
          <div class="channel-card-meta">${esc(platformLabel(channelPlatform(channel)))} · ${esc(identity.native_channel_id || key)}${(channel.display?.group_keys || []).length > 1 ? ` · gộp ${channel.display.group_keys.length} bản ghi` : ''}</div>
          <div class="channel-card-badges">${monitoringBadge(channel)}${researchBadge(channel.research)}</div>
          ${coverage ? `<div class="channel-card-stats">${esc(coverage)}</div>` : ''}
          ${channel.research?.updated_at ? `<div class="channel-card-updated">Cập nhật: ${esc(date(channel.research.updated_at))}</div>` : ''}
        </div>
        <button class="channel-menu-button" type="button" aria-label="Thao tác" onclick="event.stopPropagation(); openChannelMenu('${esc(key)}', this)">⋮</button>
      </article>`;
    }).join('');
  }

  function selectChannel(channelId) {
    state.selectedChannel = primaryChannelKey(channelId) || channelId;
    channelId = state.selectedChannel;
    try { localStorage.setItem('ytFactory.selectedChannel', channelId); } catch (_) {}
    $('channelWorkspace')?.classList.add('is-detail-open');
    renderChannelList();
    void loadChannelDetail(channelId);
  }

  function closeChannelDetail() {
    $('channelWorkspace')?.classList.remove('is-detail-open');
  }

  // ⋮: only actions the backend already has.
  function openChannelMenu(channelId, button) {
    closeChannelMenu();
    const channel = state.channels.find((item) => item.youtube_channel_id === channelId);
    if (!channel) return;
    const researchable = !['not_applicable', 'unsupported'].includes(channel.research?.state);
    const items = [
      YOUTUBE_CHANNEL.test(channelId) ? ['Đồng bộ ngay', `syncChannel('${esc(channelId)}')`] : null,
      researchable ? ['Cập nhật nghiên cứu', `selectChannel('${esc(channelId)}'); refreshChannelResearch('${esc(channelId)}')`] : null,
      [channel.tracking_enabled ? 'Tạm dừng' : 'Tiếp tục', `toggleChannel('${esc(channelId)}', ${!channel.tracking_enabled})`],
      ['Đổi nhãn', `editChannelGroup('${esc(channelId)}')`],
    ].filter(Boolean);
    const menu = document.createElement('div');
    menu.id = 'channelMenu';
    menu.className = 'channel-menu';
    menu.setAttribute('role', 'menu');
    menu.innerHTML = items.map(([label, action]) => `<button type="button" role="menuitem" onclick="closeChannelMenu(); ${action}">${esc(label)}</button>`).join('');
    document.body.appendChild(menu);
    const box = button.getBoundingClientRect();
    menu.style.top = `${window.scrollY + box.bottom + 4}px`;
    menu.style.left = `${window.scrollX + Math.max(8, box.right - menu.offsetWidth)}px`;
    setTimeout(() => document.addEventListener('click', closeChannelMenu, {once: true}), 0);
  }

  function closeChannelMenu() {
    document.getElementById('channelMenu')?.remove();
  }

  async function loadChannelDetail(channelId) {
    if (!channelId) return null;
    if (!state.channelResearch?.[channelId] && channelId === state.selectedChannel) {
      const target = $('channelDetail');
      if (target) target.innerHTML = '<div class="empty">Đang đọc hồ sơ kênh…</div>';
    }
    try {
      const bundle = await api(`/api/channels/${encodeURIComponent(channelId)}/research`);
      state.channelResearch = {...(state.channelResearch || {}), [channelId]: bundle};
      if (channelId === state.selectedChannel) renderChannelDetail(channelId);
      if (bundle.research?.summary?.state === 'running') followChannelResearch(channelId);
      return bundle;
    } catch (error) {
      if (channelId === state.selectedChannel) $('channelDetail').innerHTML = `<div class="empty">Không đọc được hồ sơ kênh: ${esc(error.message)}</div>`;
      return null;
    }
  }

  function setChannelDetailTab(channelId, tab) {
    state.channelDetailTab = tab;
    renderChannelDetail(channelId);
  }

  function renderChannelDetail(channelId) {
    const target = $('channelDetail');
    if (!target) return;
    const bundle = channelId ? state.channelResearch?.[channelId] : null;
    if (!channelId) {
      target.innerHTML = '<div class="empty">Chọn một kênh ở danh sách bên trái.</div>';
      return;
    }
    if (!bundle) return;
    const channel = state.channels.find((item) => item.youtube_channel_id === channelId) || {};
    const overview = bundle.overview || {};
    const identity = bundle.identity || {};
    const title = overview.title || channel.title || channelId;
    const syncable = (bundle.monitoring?.rows || []).find((row) => YOUTUBE_CHANNEL.test(row.channel_key));
    const tab = state.channelDetailTab || 'overview';
    const tabs = [['overview', 'TỔNG QUAN'], ['videos', 'VIDEO'], ['monitoring', 'GIÁM SÁT'], ['research', 'NGHIÊN CỨU']];
    const body = tab === 'videos' ? renderChannelVideos(channelId, bundle)
      : tab === 'monitoring' ? renderChannelMonitoring(channelId, bundle)
        : tab === 'research' ? renderChannelResearch(channelId, bundle)
          : renderChannelOverview(channelId, bundle);
    target.innerHTML = `
      <header class="channel-detail-header">
        <button class="btn small ghost channel-back" type="button" onclick="closeChannelDetail()">← Danh sách kênh</button>
        ${channelAvatar(bundle.avatar_url || channel.avatar_url || channel.thumbnail_url, title, 'lg')}
        <div class="channel-detail-title">
          <h2>${esc(title)}</h2>
          <div class="channel-card-meta">${esc(platformLabel(identity.platform || channelPlatform(channel)))}
            ${identity.native_channel_id ? ` · ${esc(identity.native_channel_id)}` : ''}
            ${overview.channel_url ? ` <a href="${esc(overview.channel_url)}" target="_blank" rel="noreferrer" aria-label="Mở kênh">↗</a>` : ''}</div>
        </div>
        <div class="channel-detail-actions">
          ${syncable ? `<button class="btn" type="button" onclick="syncChannel('${esc(syncable.channel_key)}')">Đồng bộ ngay</button>` : ''}
          <button class="btn" type="button" onclick="toggleChannel('${esc(channelId)}', ${!channel.tracking_enabled})">${channel.tracking_enabled ? 'Tạm dừng' : 'Tiếp tục'}</button>
          <button class="btn channel-menu-button" type="button" aria-label="Thao tác khác" onclick="event.stopPropagation(); openChannelMenu('${esc(channelId)}', this)">⋯</button>
        </div>
      </header>
      <nav class="channel-detail-tabs" role="tablist">${tabs.map(([key, label]) => `
        <button type="button" role="tab" class="channel-detail-tab${key === tab ? ' active' : ''}" aria-selected="${key === tab}"
          onclick="setChannelDetailTab('${esc(channelId)}', '${key}')">${label}</button>`).join('')}</nav>
      <div class="channel-detail-body">${body}</div>`;
  }

  // ---- Charts: one series each, drawn from what the bundle holds ----
  const CHART_BLUE = '#3987e5';
  const DURATION_RAMP = ['#a8cbf7', '#6aa7ef', '#3987e5', '#2a6fc4', '#1d4f91'];

  function compactNumber(value) {
    const amount = Number(value || 0);
    if (amount >= 1e6) return `${(amount / 1e6).toFixed(amount >= 1e7 ? 0 : 1)}M`;
    if (amount >= 1e3) return `${(amount / 1e3).toFixed(amount >= 1e4 ? 0 : 1)}K`;
    return String(Math.round(amount));
  }

  function viewsChart(recent) {
    const points = (recent || []).filter((item) => item.published_at && item.view_count != null)
      .sort((left, right) => String(left.published_at).localeCompare(String(right.published_at)));
    if (points.length < 3) return '';
    const width = 560; const height = 190; const left = 44; const right = 12; const top = 12; const bottom = 26;
    const times = points.map((item) => new Date(item.published_at).getTime());
    const minT = Math.min(...times); const maxT = Math.max(...times);
    const logs = points.map((item) => Math.log10(Math.max(1, item.view_count)));
    const minL = Math.floor(Math.min(...logs)); const maxL = Math.ceil(Math.max(...logs));
    const x = (t) => left + (maxT === minT ? 0.5 : (t - minT) / (maxT - minT)) * (width - left - right);
    const y = (l) => top + (1 - (l - minL) / Math.max(1, maxL - minL)) * (height - top - bottom);
    const path = points.map((item, index) => `${index ? 'L' : 'M'}${x(times[index]).toFixed(1)},${y(logs[index]).toFixed(1)}`).join(' ');
    const grid = [];
    for (let level = minL; level <= maxL; level += 1) {
      grid.push(`<line x1="${left}" x2="${width - right}" y1="${y(level)}" y2="${y(level)}" class="chart-gridline"/>`
        + `<text x="${left - 6}" y="${y(level) + 4}" class="chart-axis" text-anchor="end">${compactNumber(10 ** level)}</text>`);
    }
    const ticks = [0, 1, 2, 3].map((part) => {
      const t = minT + (part / 3) * (maxT - minT);
      return `<text x="${x(t)}" y="${height - 6}" class="chart-axis" text-anchor="middle">${new Date(t).toLocaleDateString('vi-VN', {day: '2-digit', month: '2-digit'})}</text>`;
    }).join('');
    const marks = points.map((item, index) => `<circle cx="${x(times[index]).toFixed(1)}" cy="${y(logs[index]).toFixed(1)}" r="9" class="chart-hit">
      <title>${esc(item.title)} · ${esc(date(item.published_at))} · ${esc(number(item.view_count))} lượt xem</title></circle>
      <circle cx="${x(times[index]).toFixed(1)}" cy="${y(logs[index]).toFixed(1)}" r="3" fill="${CHART_BLUE}" stroke="var(--surface)" stroke-width="2" pointer-events="none"/>`).join('');
    return `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Lượt xem ${points.length} video gần nhất theo ngày đăng">
        ${grid.join('')}${ticks}<path d="${path}" fill="none" stroke="${CHART_BLUE}" stroke-width="2" stroke-linejoin="round"/>${marks}</svg>
      <details class="chart-table"><summary>Xem bảng số liệu</summary><table><tbody>${points.slice().reverse().map((item) => `
        <tr><td>${esc(date(item.published_at))}</td><td>${esc(item.title)}</td><td class="num">${esc(number(item.view_count))}</td></tr>`).join('')}</tbody></table></details>`;
  }

  function weekdayChart(recent) {
    const dated = (recent || []).filter((item) => item.published_at);
    if (dated.length < 3) return '';
    const labels = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN'];
    const counts = [0, 0, 0, 0, 0, 0, 0];
    dated.forEach((item) => { counts[(new Date(item.published_at).getDay() + 6) % 7] += 1; });
    const max = Math.max(...counts, 1);
    const width = 280; const height = 150; const barWidth = 26; const gap = (width - 7 * barWidth) / 8;
    const bars = counts.map((count, index) => {
      const barHeight = Math.max(count ? 4 : 0, (count / max) * 100);
      const xPos = gap + index * (barWidth + gap);
      return `<g><rect x="${xPos}" y="${118 - barHeight}" width="${barWidth}" height="${barHeight}" rx="4" fill="${CHART_BLUE}"><title>${labels[index]}: ${count} video</title></rect>
        ${count ? `<text x="${xPos + barWidth / 2}" y="${112 - barHeight}" class="chart-value" text-anchor="middle">${count}</text>` : ''}
        <text x="${xPos + barWidth / 2}" y="138" class="chart-axis" text-anchor="middle">${labels[index]}</text></g>`;
    }).join('');
    return `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Số video đăng theo thứ trong tuần">${bars}</svg>`;
  }

  function durationChart(duration) {
    const entries = Object.entries(duration?.buckets || {});
    const total = entries.reduce((sum, [, count]) => sum + count, 0);
    if (!total) return '';
    const segments = entries.map(([bucket, count], index) => count ? `<span class="duration-segment" style="flex:${count};background:${DURATION_RAMP[index]}" title="${esc(bucket)}: ${count}/${total} video"></span>` : '').join('');
    const legend = entries.map(([bucket, count], index) => `<div class="duration-legend-item"><i style="background:${DURATION_RAMP[index]}"></i><span>${esc(bucket)}</span><b>${count}/${total}</b></div>`).join('');
    return `<div class="duration-bar" role="img" aria-label="Phân bố độ dài video">${segments}</div><div class="duration-legend">${legend}</div>`;
  }

  function topicBars(topics, sampled) {
    if (!(topics || []).length || !sampled) return '';
    return `<div class="topic-bars">${topics.slice(0, 6).map((item) => `
      <div class="topic-row"><span>${esc(item.term)}</span><span class="topic-track"><i style="width:${Math.round(100 * item.videos / sampled)}%"></i></span><b>${item.videos}/${sampled} video</b></div>`).join('')}</div>`;
  }

  // ---- Tabs of the detail ----
  function kpi(value, label) {
    return value === null || value === undefined || value === '' ? ''
      : `<div class="kpi"><b>${esc(value)}</b><span>${esc(label)}</span></div>`;
  }

  function infoRow(label, value) {
    return value === null || value === undefined || value === '' ? '' : `<div class="info-row"><span>${esc(label)}</span><div>${value}</div></div>`;
  }

  function researchStatusCard(channelId, bundle) {
    const summary = bundle.research?.summary || {};
    const running = summary.state === 'running' || state.channelResearchPending?.[channelId];
    const blocked = ['not_applicable', 'unsupported'].includes(summary.state);
    const stages = bundle.stages || [];
    const run = summary.run || {};
    const done = new Set(run.stages_done || []);
    const progress = running ? `<div class="research-progress"><b>Đang cập nhật nghiên cứu...</b>${stages.map((stage) => {
      const mark = done.has(stage.key) ? '✓' : stage.key === run.stage ? '●' : '○';
      return `<div class="research-stage ${done.has(stage.key) ? 'done' : stage.key === run.stage ? 'current' : ''}">${mark} ${esc(stage.label)}</div>`;
    }).join('')}</div>` : '';
    const failed = !running && summary.last_run?.status === 'failed'
      ? '<div class="secondary-text warning-text">Lần cập nhật trước chưa xong. Thử lại sau.</div>' : '';
    return `<div class="research-status-wrap"><div class="research-status-card">
        <div>
          <div class="secondary-text">Research</div>
          <div class="research-status-line"><i class="dot ${RESEARCH_TONE[summary.state] || ''}"></i>${esc(summary.label || 'Chưa nghiên cứu')}</div>
          ${summary.updated_at ? `<div class="secondary-text">Cập nhật: ${esc(date(summary.updated_at))}</div>` : ''}
          ${summary.reason && !summary.updated_at ? `<div class="secondary-text">${esc(summary.reason)}</div>` : ''}
        </div>
        ${blocked ? '' : `<button class="btn primary" type="button" ${running ? 'disabled' : ''} onclick="refreshChannelResearch('${esc(channelId)}')">${summary.state === 'unresolved' ? 'Tra kênh gốc & nghiên cứu' : 'Cập nhật nghiên cứu'}</button>`}
      </div>${progress}${failed}</div>`;
  }

  // What the newest project research that used this channel collected. Its
  // comments are from that project's sample (source + similar videos), not
  // the channel's comments.
  function latestResearch(latest) {
    if (!latest) return '';
    const parts = [
      latest.similar_videos ? `${number(latest.similar_videos)} video tương tự` : '',
      latest.comments_sampled ? `${number(latest.comments_sampled)} comment mẫu` : '',
      latest.transcripts ? `${number(latest.transcripts)} transcript` : '',
      latest.web_read + latest.web_snippets ? `${number(latest.web_read + latest.web_snippets)} nguồn web (${number(latest.web_read)} đã đọc)` : '',
    ].filter(Boolean);
    return `<div class="latest-research">
        <div class="research-sub">Nghiên cứu gần đây · dự án #${esc(latest.project_id)}</div>
        ${parts.length ? `<div>${esc(parts.join(' · '))}</div>` : ''}
        <div class="secondary-text">Dữ liệu của lần lập kế hoạch này (video nguồn và video tương tự), không phải toàn bộ comment của kênh.</div>
      </div>`;
  }

  function partialNotice(channelId, latest) {
    const unread = latest?.unread_sources || [];
    if (!latest || (latest.status !== 'partial' && !unread.length)) return '';
    return `<div class="partial-notice">
        <b>⚠ Nghiên cứu dự án #${esc(latest.project_id)} chưa đầy đủ</b>
        <span>${unread.length ? `Có ${unread.length} nguồn chưa đọc được.` : 'Một phần dữ liệu chưa thu thập được.'}
          <button class="link-button" type="button" onclick="setChannelDetailTab('${esc(channelId)}', 'research'); setTimeout(() => document.getElementById('researchLimitations')?.scrollIntoView({block: 'center'}), 50)">Xem chi tiết →</button></span>
      </div>`;
  }

  function renderChannelOverview(channelId, bundle) {
    const overview = bundle.overview || {};
    const identity = bundle.identity || {};
    const research = bundle.research || {};
    const summary = research.summary || {};
    const profile = research.profile || {};
    const latest = bundle.latest_report;
    const row = (bundle.monitoring?.rows || [])[0] || {};
    const channel = state.channels.find((item) => item.youtube_channel_id === channelId) || {};
    const kpis = [
      kpi(overview.subscriber_count != null ? compactNumber(overview.subscriber_count) : null, 'Người đăng ký'),
      kpi(overview.video_count != null ? number(overview.video_count) : null, 'Tổng video'),
      kpi(summary.coverage?.videos ? number(summary.coverage.videos) : null, 'Video gần đây đã đọc'),
    ].join('');
    // Channel tiles hold channel-scope figures only. What the latest project
    // research collected (similar videos, their comments) is shown apart,
    // named as that project's, never as the channel's own.
    const researchTiles = [
      summary.coverage?.videos ? kpi(number(summary.coverage.videos), 'video của kênh đã nghiên cứu') : '',
      summary.coverage?.comments_sampled ? kpi(number(summary.coverage.comments_sampled), 'comment của kênh đã lấy mẫu') : '',
    ].join('');
    const recent = bundle.recent_videos || [];
    const performance = research.performance || {};
    const cadence = profile.cadence || {};
    const charts = [
      viewsChart(recent) ? `<div class="chart-card wide"><h3>Hiệu suất gần đây</h3><div class="secondary-text">Lượt xem hiện tại của ${recent.length} video gần nhất, theo ngày đăng (thang log)${performance.median_views != null ? ` · trung vị ${number(performance.median_views)}` : ''}</div>${viewsChart(recent)}</div>` : '',
      weekdayChart(recent) ? `<div class="chart-card"><h3>Nhịp đăng video</h3>${cadence.uploads_per_week != null ? `<div class="secondary-text">~ ${esc(cadence.uploads_per_week)} video / tuần</div>` : ''}${weekdayChart(recent)}</div>` : '',
      durationChart(profile.duration) ? `<div class="chart-card"><h3>Độ dài video phổ biến</h3>${profile.duration.median_seconds ? `<div class="secondary-text">Trung vị ${esc(formatStudioDuration(profile.duration.median_seconds))}</div>` : ''}${durationChart(profile.duration)}</div>` : '',
      topicBars(profile.topics, profile.sample?.videos) ? `<div class="chart-card"><h3>Chủ đề chính <span class="secondary-text">(theo tag, trên ${profile.sample.videos} video)</span></h3>${topicBars(profile.topics, profile.sample.videos)}</div>` : '',
    ].filter(Boolean).join('');
    return `
      <div class="overview-top">${kpis ? `<div class="kpi-row">${kpis}</div>` : ''}${researchStatusCard(channelId, bundle)}</div>
      <div class="overview-grid">
        <section class="detail-card"><h3>Thông tin kênh</h3>
          ${infoRow('Tên kênh', esc(overview.title || channelId))}
          ${infoRow('Nền tảng', esc(platformLabel(identity.platform)))}
          ${infoRow('Channel ID', identity.native_channel_id ? esc(identity.native_channel_id) : '<span class="secondary-text">Chưa xác định</span>')}
          ${infoRow('Mô tả', research.channel?.description ? `<div class="clamp" title="Bấm để xem đầy đủ" onclick="this.classList.toggle('open')">${esc(research.channel.description)}</div>` : '')}
          ${infoRow('Lần đồng bộ', row.last_sync_at ? esc(date(row.last_sync_at)) : '<span class="secondary-text">Chưa đồng bộ</span>')}
          ${infoRow('Trạng thái', monitoringBadge(channel))}
        </section>
        <section class="detail-card"><h3>Nghiên cứu kênh</h3>
          ${researchTiles ? `<div class="kpi-row compact">${researchTiles}</div>` : '<div class="empty">Chưa nghiên cứu kênh này.</div>'}
          ${latestResearch(latest)}
          ${partialNotice(channelId, latest)}
        </section>
      </div>
      ${charts ? `<div class="chart-grid">${charts}</div>` : ''}`;
  }

  function renderChannelVideos(channelId, bundle) {
    const videos = bundle.videos || [];
    if (!videos.length) return '<div class="empty">Chưa có video nào của kênh này trong app. Cập nhật nghiên cứu hoặc đồng bộ để đọc video gần đây.</div>';
    const query = (state.channelVideoQuery || '').toLowerCase();
    const sort = state.channelVideoSort || 'recent';
    const shown = videos.filter((item) => !query || String(item.title || '').toLowerCase().includes(query))
      .sort((left, right) => sort === 'views' ? (right.view_count || 0) - (left.view_count || 0)
        : String(right.published_at || '').localeCompare(String(left.published_at || '')));
    return `<div class="video-tools">
        <input type="search" placeholder="Tìm video..." value="${esc(state.channelVideoQuery || '')}" aria-label="Tìm video"
          onchange="state.channelVideoQuery = this.value; renderChannelDetail('${esc(channelId)}')">
        <select aria-label="Sắp xếp" onchange="state.channelVideoSort = this.value; renderChannelDetail('${esc(channelId)}')">
          <option value="recent"${sort === 'recent' ? ' selected' : ''}>Mới nhất</option>
          <option value="views"${sort === 'views' ? ' selected' : ''}>Nhiều lượt xem</option>
        </select>
        <span class="secondary-text">${shown.length}/${videos.length} video</span>
      </div>
      <div class="channel-videos">${shown.map((item) => `
        <div class="channel-video">
          ${item.thumbnail_url ? `<img src="${esc(item.thumbnail_url)}" alt="" loading="lazy">` : '<span class="channel-video-thumb"></span>'}
          <div class="channel-video-body">
            <div class="primary-text">${item.url ? `<a href="${esc(item.url)}" target="_blank" rel="noreferrer">${esc(item.title || item.video_id)}</a>` : esc(item.title || item.video_id)}</div>
            <div class="secondary-text">${[item.published_at ? date(item.published_at) : '', item.duration_seconds ? formatStudioDuration(item.duration_seconds) : '',
              item.view_count != null ? `${number(item.view_count)} lượt xem` : '', item.comment_count != null ? `${number(item.comment_count)} comment` : '']
              .filter(Boolean).map(esc).join(' · ')}</div>
          </div>
          ${item.in_library || (item.url && YOUTUBE_CHANNEL.test(bundle.identity?.native_channel_id || ''))
            ? `<button class="btn small" type="button" onclick="useChannelVideoAsSource('${esc(item.row_key)}', '${esc(item.url)}')">Dùng làm nguồn</button>` : ''}
        </div>`).join('')}</div>`;
  }

  // An existing row opens in the studio; a video only known from research is
  // imported first through the usual one-video import.
  async function useChannelVideoAsSource(rowKey, url) {
    try {
      let key = rowKey;
      if (!key) {
        setMessage('Đang thêm video làm nguồn…');
        const result = await api('/api/videos/import', {method: 'POST', body: JSON.stringify({reference: url, group_name: ''})});
        key = result.video?.youtube_video_id;
        await loadVideos();
      }
      if (key) await startStudioFromVideo(key);
    } catch (error) { setMessage(`Chưa dùng được video này: ${error.message}`, 'error'); }
  }

  function renderChannelMonitoring(channelId, bundle) {
    const monitoring = bundle.monitoring || {};
    const run = monitoring.last_sync_run;
    const rows = (monitoring.rows || []).map((row) => `
      <tr>
        <td><div class="primary-text">${esc(row.title || row.channel_key)}</div><div class="secondary-text">${esc(row.channel_key)}</div></td>
        <td>${row.tracking_enabled ? statusTag(row.sync_status) : '<span class="tag red">ĐÃ TẠM DỪNG</span>'}</td>
        <td class="secondary-text">${date(row.last_sync_at)}${row.last_error ? `<div class="warning-text">${esc(String(row.last_error).slice(0, 120))}</div>` : ''}</td>
        <td><div class="channel-actions">
          ${YOUTUBE_CHANNEL.test(row.channel_key) ? `<button class="btn small ghost" onclick="syncChannel('${esc(row.channel_key)}')">Đồng bộ</button>` : ''}
          <button class="btn small ${row.tracking_enabled ? 'danger' : ''}" onclick="toggleChannel('${esc(row.channel_key)}', ${!row.tracking_enabled})">${row.tracking_enabled ? 'Tạm dừng' : 'Tiếp tục'}</button>
          <button class="btn small ghost" onclick="editChannelGroup('${esc(row.channel_key)}')">Nhãn</button>
        </div></td>
      </tr>`).join('');
    return `<div class="kpi-row">
        ${kpi(number(monitoring.videos), 'video trong kho')}
        ${kpi(number(monitoring.videos_with_counts), 'video có số liệu')}
        ${monitoring.total_views != null ? kpi(compactNumber(monitoring.total_views), 'tổng lượt xem (video trong kho)') : ''}
        ${kpi(number(monitoring.statistics_snapshots), 'bản chụp số liệu')}
        ${kpi(number(monitoring.metadata_versions), 'phiên bản metadata')}
      </div>
      ${monitoring.latest_statistics_at ? `<div class="secondary-text">Bản chụp số liệu mới nhất: ${esc(date(monitoring.latest_statistics_at))}</div>` : ''}
      ${run ? `<div class="secondary-text">Lần đồng bộ gần nhất: ${esc(run.status)} · ${esc(date(run.started_at))} · kiểm tra ${esc(number(run.videos_seen))}, mới ${esc(number(run.videos_new))}</div>` : ''}
      ${rows ? `<div class="table-wrap"><table><thead><tr><th>Bản ghi kênh</th><th>Trạng thái</th><th>Đồng bộ gần nhất</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>` : ''}`;
  }

  function researchSection(title, html, id = '') {
    return html ? `<section class="detail-card"${id ? ` id="${id}"` : ''}><h3>${esc(title)}</h3>${html}</section>` : '';
  }

  function chips(items) {
    return items.length ? `<div class="keyword-list">${items.map((item) => `<span class="keyword">${esc(item)}</span>`).join('')}</div>` : '';
  }

  function renderChannelResearch(channelId, bundle) {
    const research = bundle.research || {};
    const summary = research.summary || {};
    const profile = research.profile || {};
    const performance = research.performance || {};
    const patterns = research.patterns || [];
    const audience = research.audience || {};
    const latest = bundle.latest_report;
    const titles = profile.titles || {};
    const shapes = (titles.shapes || []).filter((item) => item.count >= 2);
    const cadence = profile.cadence || {};
    const samples = audience.samples || [];
    const byKind = (sample, kind) => (sample.patterns || []).find((item) => item.kind === kind) || {};
    const questions = samples.map((sample) => {
      const item = byKind(sample, 'questions');
      return item.count ? `<li>${esc(`${item.count}/${item.of} comment mẫu là câu hỏi`)}${(item.examples || []).length ? ` · “${esc(item.examples[0])}”` : ''}</li>` : '';
    }).join('');
    const concerns = samples.flatMap((sample) => (byKind(sample, 'terms').items || []).slice(0, 5)
      .map((item) => `<li>${esc(`${item.count}/${item.of} comment mẫu đề cập “${item.term}”`)}</li>`)).join('');
    const negatives = samples.map((sample) => {
      const item = byKind(sample, 'negative');
      return item.count ? `<li>${esc(`${item.count}/${item.of} comment mẫu có từ khoá tiêu cực`)}${(item.examples || []).length ? ` · “${esc(item.examples[0])}”` : ''}</li>` : '';
    }).join('');
    const coverage = [
      summary.coverage?.videos ? `${number(summary.coverage.videos)} video của kênh` : '',
      summary.coverage?.comments_sampled ? `${number(summary.coverage.comments_sampled)} comment của kênh đã lấy mẫu` : '',
    ].filter(Boolean);
    const unread = latest?.unread_sources || [];
    const sections = [
      researchSection('Tổng quan kênh', research.channel?.description ? `<div class="clamp" title="Bấm để xem đầy đủ" onclick="this.classList.toggle('open')">${esc(research.channel.description)}</div>` : ''),
      researchSection('Chủ đề chính', topicBars(profile.topics, profile.sample?.videos)),
      researchSection('Tag chung của kênh', chips((profile.channel_tags || []).map((item) => `${item.term} · ${item.videos} video`))),
      researchSection('Nhịp đăng', cadence.uploads_per_week != null ? `<p>${esc(`${cadence.uploads_per_week} video/tuần · khoảng cách trung vị ${cadence.median_gap_days ?? '—'} ngày · ${cadence.uploads_last_30_days} video trong 30 ngày`)}</p>${weekdayChart(bundle.recent_videos)}` : ''),
      researchSection('Độ dài phổ biến', durationChart(profile.duration)),
      researchSection('Hiệu suất gần đây', performance.median_views != null ? `<p>${esc(`Trung vị ${number(performance.median_views)} lượt xem trên ${performance.measured_videos} video`)}${performance.p25_views != null ? esc(` · khoảng giữa ${number(performance.p25_views)}–${number(performance.p75_views)}`) : ''}</p>`
        + (performance.recent_median_views != null ? `<p>${esc(`${performance.recent_videos} video gần nhất (≥ 7 ngày): trung vị ${number(performance.recent_median_views)} · ×${performance.recent_vs_overall} so với chung`)}</p>` : '')
        + ((performance.standouts || []).length ? `<div class="research-sub">Video nổi bật</div><ul class="studio-result-list">${performance.standouts.map((item) => `
          <li><a href="https://www.youtube.com/watch?v=${esc(item.video_id)}" target="_blank" rel="noreferrer">${esc(item.title)}</a> <span class="secondary-text">${esc(`${number(item.view_count)} lượt xem · ×${item.times_median} trung vị`)}</span></li>`).join('')}</ul>` : '') : ''),
      researchSection('Mẫu tiêu đề', titles.measured ? `<p class="secondary-text">${esc(`${titles.measured} tiêu đề · dài trung bình ${titles.average_length} ký tự`)}</p>`
        + (shapes.length ? `<ul class="studio-result-list">${shapes.map((item) => `<li>${esc(`${item.label}: ${item.count}/${item.of}`)}</li>`).join('')}</ul>` : '')
        + chips((titles.top_terms || []).map((item) => `${item.term} (${item.count}/${item.of})`)) : ''),
      researchSection('Hook / Content patterns', patterns.length ? `<ul class="studio-result-list">${patterns.map((item) => `<li>${esc(item.description)} <span class="secondary-text">· ${item.evidence_count} ví dụ</span></li>`).join('')}</ul>` : ''),
      researchSection('Người xem (từ comment mẫu)', audience.total_sample ? `<p class="secondary-text">${esc(`${audience.total_sample} comment mẫu từ ${audience.videos} video của kênh · chỉ phản ánh mẫu đã đọc, không đại diện toàn bộ người xem`)}</p>`
        + (questions ? `<div class="research-sub">Những câu hỏi phổ biến</div><ul class="studio-result-list">${questions}</ul>` : '')
        + (concerns ? `<div class="research-sub">Mối quan tâm</div><ul class="studio-result-list">${concerns}</ul>` : '')
        + (negatives ? `<div class="research-sub">Phản đối / pain points (theo từ khoá)</div><ul class="studio-result-list">${negatives}</ul>` : '') : ''),
      researchSection('Giới hạn', unread.length || (latest?.limitations || []).length
        ? `<ul class="studio-result-list">${unread.map((item) => `<li>${esc(`${item.what} · ${item.where}: ${item.why}`)}</li>`).join('')}${(latest?.limitations || []).map((item) => `<li>${esc(item)}</li>`).join('')}</ul>` : '', 'researchLimitations'),
    ].filter(Boolean).join('');
    return `${researchStatusCard(channelId, bundle)}
      ${coverage.length ? `<div class="coverage-line"><b>Kênh</b>${coverage.map((item) => `<span>${esc(item)}</span>`).join('')}</div>` : ''}
      ${latestResearch(latest)}
      ${sections ? `<div class="research-sections">${sections}</div>` : '<div class="empty">Chưa có dữ liệu nghiên cứu cho kênh này.</div>'}`;
  }

  async function refreshChannelResearch(channelId, mode = 'auto') {
    if (state.channelResearchPending?.[channelId]) return;
    state.channelResearchPending = {...(state.channelResearchPending || {}), [channelId]: true};
    if (channelId === state.selectedChannel) renderChannelDetail(channelId);
    followChannelResearch(channelId);
    try {
      const response = await api(`/api/channels/${encodeURIComponent(channelId)}/research/refresh`, {
        method: 'POST', body: JSON.stringify({mode}),
      });
      setMessage(`Đã cập nhật nghiên cứu kênh: ${RESEARCH_RESULT[response.result?.status] || 'xong'}.`, 'success');
    } catch (error) {
      setMessage(error.status === 409 ? 'Kênh này đang được nghiên cứu, đang theo dõi tiến độ.' : `Chưa cập nhật được nghiên cứu: ${error.message}`, error.status === 409 ? '' : 'error');
    } finally {
      delete state.channelResearchPending[channelId];
      await loadChannelDetail(channelId);
      await loadChannels();
    }
  }

  // Hỏi lại server trong lúc một lượt nghiên cứu chạy, kể cả sau khi tải lại
  // trang, và kể cả khi lượt đó do bước Kế hoạch khởi động.
  function followChannelResearch(channelId) {
    state.channelResearchWatch = state.channelResearchWatch || {};
    if (state.channelResearchWatch[channelId]) return;
    const tick = async () => {
      let bundle = null;
      try { bundle = await api(`/api/channels/${encodeURIComponent(channelId)}/research`); } catch (_) { /* hỏi lại sau */ }
      if (bundle) {
        state.channelResearch = {...(state.channelResearch || {}), [channelId]: bundle};
        if (state.selectedChannel === channelId) renderChannelDetail(channelId);
      }
      const running = bundle?.research?.summary?.state === 'running' || state.channelResearchPending?.[channelId];
      if (running) {
        state.channelResearchWatch[channelId] = setTimeout(tick, CHANNEL_RESEARCH_POLL_MS);
        return;
      }
      delete state.channelResearchWatch[channelId];
      if (!state.channelResearchPending?.[channelId]) void loadChannels();
    };
    state.channelResearchWatch[channelId] = setTimeout(tick, CHANNEL_RESEARCH_POLL_MS);
  }

  async function loadVideos() {
    const videos = await api('/api/videos?limit=500');
    const signature = JSON.stringify([videos, state.channels]);
    if (state.videoCatalogSignature === signature) return;
    state.videoCatalogSignature = signature;
    state.videoCatalog = videos;
    renderVideos();
  }

  function projectStatusOptions(current) {
    const options = [
      ['draft', 'Bản nháp'],
      ['script', 'Đang viết'],
      ['review', 'Chờ duyệt'],
      ['approved', 'Đã duyệt'],
      ['archived', 'Lưu trữ'],
    ];
    return options.map(([value, label]) => `<option value="${value}" ${value === current ? 'selected' : ''}>${label}</option>`).join('');
  }

  async function loadProjects() {
    const projects = await api('/api/projects?limit=50');
    const signature = JSON.stringify([projects, state.channels]);
    if (state.projectCatalogSignature === signature) return;
    state.projectCatalogSignature = signature;
    state.projects = projects;
    const activeProjects = state.projects.filter((project) => !Number(project.is_published) && project.status !== 'archived');
    const publishedProjects = state.projects.filter((project) => Number(project.is_published));
    const archivedProjects = state.projects.filter((project) => !Number(project.is_published) && project.status === 'archived');
    const projectRows = (projects, emptyText) => projects.length ? projects.map((project) => {
      const publication = project.publication_status || '';
      const publicationLabel = publication === 'published' ? 'Đã xuất bản' : publication === 'queued' ? 'Đã xếp lịch đăng' : publication === 'publishing' ? 'Đang xuất bản' : publication === 'failed' ? 'Đăng lỗi' : '';
      const publicationClass = publication === 'published' ? 'cyan' : publication === 'failed' ? 'orange' : '';
      return `
      <div class="job-row">
        <span class="job-dot ${project.status === 'approved' ? 'completed' : project.status === 'review' ? 'running' : ''}"></span>
        <div class="job-main">
          <div class="job-title">${esc(project.title || project.source_title || project.youtube_video_id)}</div>
          <div class="job-meta">${esc(channelName(project.youtube_channel_id))} · ${esc(project.youtube_video_id)} · ${date(project.updated_at)}</div>
          <div class="secondary-text">${project.has_transcript ? 'Có transcript' : 'Chưa có transcript'} · ${project.has_writer_content ? 'Có AI Writer' : 'Chưa có AI Writer'}${project.project_published_at ? ` · Đăng ${date(project.project_published_at)}` : ''}${project.notes ? ` · ${esc(project.notes)}` : ''}</div>
        </div>
        ${projectStatusTag(project.status)}
        ${publicationLabel ? `<span class="tag ${publicationClass}">${publicationLabel}</span>` : ''}
        <div class="queue-controls">
          <select aria-label="Trạng thái dự án" onchange="updateProjectStatus(${project.id}, this.value)">${projectStatusOptions(project.status)}</select>
          <button class="btn small primary" onclick="resumeStudioProject(${project.id})">Tiếp tục tạo video</button>
          <button class="btn small ghost" onclick="editProjectNotes(${project.id})">Ghi chú</button>
          <button class="btn small ghost" onclick="generateWriterContent('${esc(project.youtube_video_id)}')">AI Writer</button>
          <a class="btn small ghost" href="${esc(project.video_url)}" target="_blank" rel="noreferrer">Mở video</a>
        </div>
      </div>`;
    }).join('') : `<div class="empty">${emptyText}</div>`;
    $('projectCountLabel').textContent = `${activeProjects.length} ĐANG LÀM · ${publishedProjects.length} ĐÃ XUẤT BẢN`;
    $('projectsBody').innerHTML = `
      <div class="project-list-section"><div class="project-list-heading"><strong>ĐANG LÀM</strong><span class="tag">${activeProjects.length} DỰ ÁN</span></div>${projectRows(activeProjects, 'Chưa có dự án đang làm.')}</div>
      <div class="project-list-section"><div class="project-list-heading"><strong>ĐÃ XUẤT BẢN</strong><span class="tag cyan">${publishedProjects.length} VIDEO</span></div>${projectRows(publishedProjects, 'Chưa có video đã xuất bản.')}</div>
      ${archivedProjects.length ? `<div class="project-list-section"><div class="project-list-heading"><strong>LƯU TRỮ</strong><span class="tag">${archivedProjects.length}</span></div>${projectRows(archivedProjects, '')}</div>` : ''}`;
  }

  async function createProductionProject(videoId) {
    setMessage(`Đang tạo dự án sản xuất cho ${videoId}...`);
    try {
      await api(`/api/videos/${encodeURIComponent(videoId)}/project`, {method: 'POST', body: JSON.stringify({})});
      setMessage('Đã đưa video vào xưởng dự án.', 'success');
      await loadProjects();
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function startStudioFromVideo(videoId) {
    const video = state.videoCatalog.find((item) => item.youtube_video_id === videoId);
    if (!video) return setMessage('Không tìm thấy video đã chọn trong thư viện.', 'error');
    setWorkspace('dashboard');
    setStudioStep(1);
    state.studioSourceChannelId = video.youtube_channel_id || '';
    populateStudioSourceChannelSelect();
    populateStudioVideoSelect();
    const select = $('studioVideoSelect');
    if (select) select.value = videoId;
    await selectStudioVideo();
    setMessage(`Đã chọn “${video.title || videoId}”. Bấm “Phân tích”.`, 'success');
  }

  async function updateProjectStatus(projectId, status) {
    try {
      await api(`/api/projects/${projectId}`, {method: 'PATCH', body: JSON.stringify({status})});
      setMessage('Đã cập nhật trạng thái dự án.', 'success');
      await loadProjects();
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function editProjectNotes(projectId) {
    const project = state.projects.find((item) => item.id === projectId);
    const notes = prompt('Ghi chú cho dự án sản xuất:', project?.notes || '');
    if (notes === null) return;
    try {
      await api(`/api/projects/${projectId}`, {method: 'PATCH', body: JSON.stringify({notes})});
      setMessage('Đã lưu ghi chú dự án.', 'success');
      await loadProjects();
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function openProjectDetail(projectId, initialView = 'overview') {
    setWorkspace('production');
    try {
      const bundle = await api(`/api/projects/${projectId}`);
      // Mỗi lần mở xưởng, luôn bắt đầu ở trang có nội dung; tránh giữ tab cũ rỗng sau khi dữ liệu thay đổi.
      state.projectView = ['overview', 'editor', 'assets', 'export'].includes(initialView) ? initialView : 'overview';
      renderProjectDetail(bundle);
    } catch (error) {
      $('projectTitle').textContent = `Không mở được dự án #${projectId}`;
      $('projectBody').innerHTML = `<div class="empty">Không tải được chi tiết dự án: ${esc(error.message || 'Lỗi không xác định.')}<div class="studio-actions" style="margin-top:12px"><button class="btn primary" onclick="openProjectDetail(${Number(projectId)})">Thử lại</button></div></div>`;
      $('projectDetail').classList.add('open');
      setMessage(error.message, 'error');
    }
  }

  function switchProjectView(view) {
    const allowed = new Set(['overview', 'editor', 'assets', 'export']);
    state.projectView = allowed.has(view) ? view : 'overview';
    document.querySelectorAll('[data-project-view]').forEach((panel) => {
      panel.hidden = panel.dataset.projectView !== state.projectView;
    });
    document.querySelectorAll('[data-project-tab]').forEach((tab) => {
      const active = tab.dataset.projectTab === state.projectView;
      tab.classList.toggle('active', active);
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    saveStudioSession();
  }

  function selectedVoiceProvider() {
    return $('renderVoiceProvider')?.value || 'edge_tts';
  }

  async function queueSelectedVoiceover(projectId, jobType = 'voiceover') {
    const provider = selectedVoiceProvider();
    await saveRenderSettings(projectId);
    return queueProductionJob(projectId, jobType, provider, true);
  }

  function renderProjectDetail(bundle) {
    const project = bundle.project || {};
    const video = bundle.source_video || {};
    const transcript = bundle.latest_transcript;
    const script = bundle.latest_script;
    const shots = bundle.latest_shots || [];
    const timeline = bundle.latest_timeline || [];
    const finalVideo = bundle.final_video || {};
      const productionJobs = bundle.production_jobs || [];
      const productionJobEvents = bundle.production_job_events || {};
      const publications = bundle.publications || [];
      const thumbnails = bundle.thumbnails || [];
    const assets = bundle.project_assets || [];
    const renderSettings = bundle.render_settings || {music_asset_id: null, music_volume: 0.12, transition_style: 'fade', output_profile: 'youtube_landscape', voice_provider: 'edge_tts', voice_model: 'vi-VN-HoaiMyNeural', voice_reference_asset_id: null, voice_prompt_text: '', subtitle_provider: 'timeline_text', subtitle_model: 'timeline', publish_language: 'vi'};
    const selectedVoiceModel = String(renderSettings.voice_model || 'vi-VN-HoaiMyNeural');
    const selectedVoiceReferenceAsset = Number(renderSettings.voice_reference_asset_id || 0);
    const selectedSubtitleModel = String(renderSettings.subtitle_model || 'timeline');
    const sceneGenerationJobs = bundle.scene_generation_jobs || [];
    const metadata = bundle.metadata_analysis?.result || null;
    const writer = bundle.writer_content?.result || null;
    const readiness = bundle.readiness || {};
    const managedChannelSummary = project.managed_channel_name
      ? `${project.managed_channel_name} · workflow: ${project.workflow_reference_title || 'chưa gắn'}`
      : 'Chưa chọn kênh xuất bản';
    const channelPresetAction = project.managed_channel_id
      ? `<div class="queue-controls" style="justify-content:flex-start;margin-top:8px"><button class="btn small ghost" onclick="applyChannelPreset(${project.id})">Áp dụng preset kênh vào render</button><span class="secondary-text">${esc(renderSettings.output_profile)} · ${esc(renderSettings.voice_provider)} · ${esc(renderSettings.subtitle_provider)}</span></div>`
      : '';
    const managedChannelOptions = `<option value="">Dùng kênh gắn với project</option>${state.managedChannels.map((channel) => `<option value="${channel.id}" ${Number(project.managed_channel_id) === Number(channel.id) ? 'selected' : ''}>${esc(channel.name)} · ${esc(channel.platform || 'youtube')}${channel.group_name ? ` · ${esc(channel.group_name)}` : ''}</option>`).join('')}`;
    const thumbnailOptions = `<option value="">Không đổi thumbnail</option>${assets.filter((asset) => asset.asset_type === 'image').map((asset) => `<option value="${asset.id}">${esc(asset.original_name || asset.file_path || `Asset #${asset.id}`)}</option>`).join('')}`;
    const voiceReferenceOptions = `<option value="">Không dùng voice reference</option>${assets.filter((asset) => asset.asset_type === 'audio').map((asset) => `<option value="${asset.id}" ${selectedVoiceReferenceAsset === Number(asset.id) ? 'selected' : ''}>${esc(asset.original_name || asset.file_path || `Audio #${asset.id}`)} · ${fileSize(asset.file_size)}</option>`).join('')}`;
    state.projectId = project.id;
    state.scriptId = script?.id || null;
    state.shots = shots;
    state.timeline = timeline;
    state.productionJobs = productionJobs;
    state.assets = assets;
    const suggestedTitles = [...new Set([
      ...(Array.isArray(writer?.new_titles) ? writer.new_titles : []),
      script?.script_title || project.title || '',
    ].map((item) => String(item || '').trim()).filter(Boolean))].slice(0, 4);
    const thumbnailBrief = [
      `Khung hình chính: ${suggestedTitles[0] || project.title || 'nội dung video'}.`,
      writer?.creative_direction || writer?.summary || script?.hook || '',
      'Ưu tiên một chủ thể rõ ràng, tương phản cao, ít chữ, dễ đọc ở kích thước nhỏ; không dùng ảnh hay logo không có quyền sử dụng.',
    ].filter(Boolean).join(' ');
    state.publicationSuggestions = {
      sourceVideoId: String(project.youtube_video_id || ''),
      titles: suggestedTitles,
      description: String(writer?.new_description || ''),
      tags: Array.isArray(writer?.hashtags) ? writer.hashtags : [],
      thumbnailBrief,
    };
    saveStudioSession();
    const openaiImageIntegration = state.integrations.find((item) => item.key === 'openai_gpt');
    const openaiImageReady = Boolean(openaiImageIntegration?.ready);
    const geminiIntegration = state.integrations.find((item) => item.key === 'google_gemini');
    const geminiReady = Boolean(geminiIntegration?.ready);
    $('projectTitle').textContent = `${project.title || video.title || project.id} · ${projectStatusTag(project.status).replace(/<[^>]*>/g, '')}`;
    $('projectHandoffLink').href = `/api/projects/${project.id}/handoff`;
    const nextActions = (bundle.next_actions || []).map((item) => `<li>${esc(item)}</li>`).join('') || '<li>Không có việc chờ xử lý.</li>';
    const titles = writer?.new_titles?.length ? writer.new_titles.map((item) => `<li>${esc(item)}</li>`).join('') : '<li>Chưa có tiêu đề mới.</li>';
    const outline = writer?.script_outline?.length ? writer.script_outline.map((item) => `<li>${esc(item)}</li>`).join('') : '<li>Chưa có dàn ý kịch bản.</li>';
    const keywords = metadata?.keywords?.length ? metadata.keywords.map((item) => `<span class="keyword">${esc(item.keyword)} <small>×${esc(item.count)}</small></span>`).join('') : '<span class="secondary-text">Chưa có từ khóa metadata</span>';
    const transcriptText = transcript?.content_text ? esc(transcript.content_text) : 'Chưa có transcript.';
    const scriptTitle = script?.script_title || '';
    const scriptHook = script?.hook || '';
    const scriptIntro = script?.intro || '';
    const scriptMain = script?.main_content || '';
    const scriptCta = script?.cta || '';
    const scriptActions = script ? `
      <button class="btn small primary" onclick="saveCurrentScript()">Lưu kịch bản</button>
      <button class="btn small ghost" onclick="setCurrentScriptReview()">Chuyển chờ duyệt</button>
      <button class="btn small ghost" onclick="approveCurrentScript()">Duyệt</button>
      <a class="btn small ghost" href="/api/scripts/${script.id}/markdown" target="_blank" rel="noreferrer">Xuất Markdown</a>` :
      `<button class="btn small primary" onclick="createScriptDraft(${project.id})">Tạo bản nháp từ AI Writer</button>`;
    const shotRows = shots.length ? shots.map((shot) => `
      <div class="job-row" style="align-items:flex-start">
        <span class="job-dot ${shot.status === 'done' ? 'completed' : shot.status === 'ready' ? 'running' : ''}"></span>
        <div class="job-main">
          <div class="job-title">Cảnh ${number(shot.shot_index)} · ${esc(shot.section)} · ${shotStatusTag(shot.status)}</div>
          <div class="transcript-grid" style="grid-template-columns:1fr 1fr; margin-top:8px">
            <div class="transcript-field"><label for="shotNarration-${shot.id}">Lời dẫn</label><textarea id="shotNarration-${shot.id}" class="transcript-editor" style="min-height:88px">${esc(shot.narration)}</textarea></div>
            <div class="transcript-field"><label for="shotPrompt-${shot.id}">Visual/B-roll prompt</label><textarea id="shotPrompt-${shot.id}" class="transcript-editor" style="min-height:88px">${esc(shot.visual_prompt)}</textarea></div>
          </div>
          <div class="queue-controls" style="justify-content:flex-start; margin-top:8px">
            <select id="shotAsset-${shot.id}" aria-label="Loại asset">
              <option value="talking_head" ${shot.asset_type === 'talking_head' ? 'selected' : ''}>Talking head</option>
              <option value="broll" ${shot.asset_type === 'broll' ? 'selected' : ''}>B-roll</option>
              <option value="generated_image" ${shot.asset_type === 'generated_image' ? 'selected' : ''}>Ảnh AI</option>
              <option value="screen_recording" ${shot.asset_type === 'screen_recording' ? 'selected' : ''}>Quay màn hình</option>
            </select>
            <input id="shotDuration-${shot.id}" style="width:76px" type="number" min="1" max="3600" value="${esc(shot.duration_seconds)}" />
            <select id="shotStatus-${shot.id}" aria-label="Trạng thái cảnh">
              <option value="planned" ${shot.status === 'planned' ? 'selected' : ''}>Đang chuẩn bị</option>
              <option value="ready" ${shot.status === 'ready' ? 'selected' : ''}>Sẵn sàng</option>
              <option value="done" ${shot.status === 'done' ? 'selected' : ''}>Xong</option>
            </select>
            <button class="btn small ghost" onclick="saveShot(${shot.id})">Lưu cảnh</button>
          </div>
        </div>
      </div>`).join('') : '<div class="empty">Chưa có shot list. Tạo shot list sau khi đã có kịch bản.</div>';
    const storyboardRows = shots.length ? `<div class="storyboard-grid" aria-label="Storyboard">${shots.map((shot, shotPosition) => {
      const segment = timeline.find((item) => Number(item.shot_id) === Number(shot.id)) || {};
      const visualPath = String(segment.visual_path || '').trim();
      const visualPreviewUrl = visualPath ? `/api/projects/${project.id}/timeline/${segment.id}/visual-preview` : '';
      const visualPreview = visualPath
        ? (/\.(jpg|jpeg|png|webp|bmp|gif)$/i.test(visualPath) ? `<img src="${visualPreviewUrl}" alt="Storyboard cảnh ${esc(shot.shot_index)}">` : `<video src="${visualPreviewUrl}" controls muted preload="metadata"></video>`)
        : `<div><div class="eyebrow">${esc(shot.asset_type || 'broll')}</div><div class="storyboard-prompt">${esc(shot.visual_prompt || 'Chưa có visual prompt. Hãy mô tả cảnh, chuyển động và nguồn asset.')}</div></div>`;
      return `<article class="storyboard-card">
        <div class="storyboard-card-head"><div class="storyboard-card-title">Cảnh ${number(shot.shot_index)} · ${esc(shot.section || 'main')}</div>${shotStatusTag(shot.status)}</div>
        <div class="storyboard-media">${visualPreview}</div>
        <div class="storyboard-body">
          <div class="transcript-grid">
            <div class="transcript-field"><label for="shotNarration-${shot.id}">Lời dẫn / voiceover</label><textarea id="shotNarration-${shot.id}" class="transcript-editor">${esc(shot.narration)}</textarea></div>
            <div class="transcript-field"><label for="shotPrompt-${shot.id}">Hình ảnh / chuyển động / prompt</label><textarea id="shotPrompt-${shot.id}" class="transcript-editor">${esc(shot.visual_prompt)}</textarea></div>
          </div>
          <div class="storyboard-controls">
            <select id="shotAsset-${shot.id}" aria-label="Loại asset">
              <option value="talking_head" ${shot.asset_type === 'talking_head' ? 'selected' : ''}>Talking head</option>
              <option value="broll" ${shot.asset_type === 'broll' ? 'selected' : ''}>B-roll</option>
              <option value="generated_image" ${shot.asset_type === 'generated_image' ? 'selected' : ''}>Ảnh AI</option>
              <option value="screen_recording" ${shot.asset_type === 'screen_recording' ? 'selected' : ''}>Quay màn hình</option>
            </select>
            <input id="shotDuration-${shot.id}" type="number" min="1" max="3600" value="${esc(shot.duration_seconds)}" title="Thời lượng (giây)">
            <select id="shotStatus-${shot.id}" aria-label="Trạng thái cảnh">
              <option value="planned" ${shot.status === 'planned' ? 'selected' : ''}>Đang chuẩn bị</option>
              <option value="ready" ${shot.status === 'ready' ? 'selected' : ''}>Sẵn sàng</option>
              <option value="done" ${shot.status === 'done' ? 'selected' : ''}>Xong</option>
            </select>
            <button class="btn small ghost" onclick="saveShot(${shot.id})">Lưu cảnh</button>
          </div>
          <div class="storyboard-summary"><span>${number(shot.duration_seconds)} giây</span><span>Timeline: ${segment.start_seconds == null ? 'chưa tạo' : `${segment.start_seconds}s–${segment.end_seconds}s`}</span>${visualPath ? `<span>${visualPath.includes('director_draft_visuals') ? 'Visual draft – cần thay' : 'Visual đã gắn'}</span>` : '<span>Chưa gắn visual thật</span>'}${segment.audio_path ? '<span>Đã có giọng đọc</span>' : ''}</div>
          <div class="queue-controls" style="justify-content:flex-start; margin-top:8px; flex-wrap:wrap">
            <input id="shotImageFile-${shot.id}" type="file" accept="image/*,video/*" style="max-width:180px" onchange="uploadShotImage(${project.id}, ${shot.id}, this)" aria-label="Tải ảnh/video cho cảnh" />
            ${visualPath ? `<button class="btn small danger" type="button" onclick="deleteShotImage(${project.id}, ${segment.id})">Xóa ảnh/video</button>` : ''}
            <select id="shotSceneRatio-${shot.id}" aria-label="Định dạng kích thước"><option value="1280:720">Ngang 16:9</option><option value="720:1280">Dọc 9:16</option><option value="1024:1024">Vuông 1:1</option></select>
            <select id="shotImageProvider-${shot.id}" aria-label="Engine tạo ảnh AI">${IMAGE_PROVIDER_OPTIONS}</select>
            <button class="btn small primary" type="button" onclick="generateShotImage(${project.id}, ${shot.id})">Tạo ảnh AI cho cảnh</button>
            <select id="shotVideoProvider-${shot.id}" aria-label="Engine tạo video AI">${VIDEO_PROVIDER_OPTIONS}</select>
            <button class="btn small primary" type="button" onclick="generateShotVideo(${project.id}, ${shot.id})">${/\.(jpg|jpeg|png|webp|bmp|gif)$/i.test(visualPath) ? 'Tạo video AI từ ảnh cho cảnh' : 'Cần tạo ảnh trước'}</button>
            <button class="btn small ghost" type="button" onclick="regenerateShotVoice(${project.id}, ${shot.id})">Tạo lại giọng đọc cảnh này</button>
          </div>
        </div>
         <div class="queue-controls" style="justify-content:flex-start; margin-top:8px; flex-wrap:wrap"><button class="btn small ghost" onclick="moveStoryboardShot(${project.id}, ${shot.id}, -1)" ${shotPosition === 0 ? 'disabled' : ''}>↑</button><button class="btn small ghost" onclick="moveStoryboardShot(${project.id}, ${shot.id}, 1)" ${shotPosition === shots.length - 1 ? 'disabled' : ''}>↓</button><button class="btn small ghost" onclick="duplicateStoryboardShot(${project.id}, ${shot.id})">Nhân bản</button><button class="btn small danger" onclick="deleteStoryboardShot(${project.id}, ${shot.id})">Xóa cảnh</button></div>
       </article>`;
    }).join('')}</div>` : '<div class="empty">Chưa có storyboard. Tạo shot list sau khi đã có kịch bản.</div>';
    const shotActions = script ? `
      <button class="btn small primary" onclick="createStoryboardShot(${project.id})">+ Thêm cảnh</button>
      <button class="btn small ghost" onclick="generateShotList(${project.id}, ${shots.length ? 'false' : 'true'})">${shots.length ? 'Giữ shot list hiện tại' : 'Tạo shot list'}</button>
      <button class="btn small ghost" onclick="regenerateShotList(${project.id})">Tạo lại shot list</button>
      <a class="btn small ghost" href="/api/projects/${project.id}/shots/markdown" target="_blank" rel="noreferrer">Xuất shot Markdown</a>` :
      '<span class="secondary-text">Cần có kịch bản trước khi tạo shot list.</span>';
    const totalTimelineDuration = timeline.reduce((total, item) => total + Number(item.duration_seconds || 0), 0);
    const timelineRows = timeline.length ? timeline.map((segment) => {
      const sceneJob = sceneGenerationJobs.find((item) => Number(item.timeline_segment_id) === Number(segment.id));
      const sceneJobActions = sceneJob
        ? (sceneJob.status === 'queued' ? `<button class="btn small ghost" type="button" onclick="cancelSceneJob(${project.id}, ${sceneJob.id})">Hủy</button>`
          : ['error', 'cancelled'].includes(sceneJob.status) ? `<button class="btn small ghost" type="button" onclick="retrySceneJob(${project.id}, ${sceneJob.id})">Chạy lại</button>`
          : (sceneJob.status === 'running' && SUBSCRIPTION_SCENE_PROVIDERS.has(sceneJob.provider)) ? `<button class="btn small ghost" type="button" onclick="retrySceneJob(${project.id}, ${sceneJob.id})">Kẹt lâu? Chạy lại</button>`
          : '')
        : '';
      const sceneStatus = sceneJob ? `${productionJobStatusTag(sceneJob.status)} · ${esc(sceneJob.provider)}${sceneJob.error ? ` · ${esc(sceneJob.error)}` : ''} ${sceneJobActions}` : 'Chưa tạo ảnh AI cho đoạn này.';
      const sceneControls = `
        <select id="sceneRatio-${segment.id}" aria-label="Tỷ lệ cảnh AI"><option value="1280:720">Ngang 16:9</option><option value="720:1280">Dọc 9:16</option><option value="1024:1024">Vuông 1:1</option></select>
        <select id="sceneImageProvider-${segment.id}" aria-label="Engine tạo ảnh AI"><option value="antigravity_image">Antigravity · ảnh theo gói</option><option value="meta_ai_image">Meta AI · ảnh (gói đăng ký)</option><option value="gemini_image" ${geminiReady ? 'selected' : ''}>Gemini Image</option>${openaiImageReady ? '<option value="openai_image">GPT Image</option>' : ''}</select>
        <button class="btn small primary" onclick="generateSceneImage(${project.id}, ${segment.id})">Tạo ảnh AI</button>
        <select id="sceneVideoProvider-${segment.id}" aria-label="Engine tạo video AI">${VIDEO_PROVIDER_OPTIONS}</select>
        <button class="btn small primary" onclick="generateSceneVideo(${project.id}, ${segment.id})">${/\.(jpg|jpeg|png|webp|bmp|gif)$/i.test(String(segment.visual_path || '')) ? 'Tạo video AI từ ảnh' : 'Cần tạo ảnh trước'}</button>`;
      return `
      <div class="job-row" style="align-items:flex-start">
        <span class="job-dot ${segment.status === 'done' || segment.status === 'ready' ? 'completed' : segment.status === 'voice_ready' || segment.status === 'asset_ready' ? 'running' : ''}"></span>${segmentHaveBadges(segment)}
        <div class="job-main">
          <div class="job-title">Đoạn ${number(segment.segment_index)} · ${esc(segment.section)} · ${segment.start_seconds}s–${segment.end_seconds}s · ${timelineStatusTag(segment.status)}</div>
          <div class="transcript-grid" style="grid-template-columns:1fr 1fr; margin-top:8px">
            <div class="transcript-field"><label for="timelineVoice-${segment.id}">Voiceover</label><textarea id="timelineVoice-${segment.id}" class="transcript-editor" style="min-height:88px">${esc(segment.voice_text)}</textarea></div>
            <div class="transcript-field"><label for="timelinePrompt-${segment.id}">Visual prompt</label><textarea id="timelinePrompt-${segment.id}" class="transcript-editor" style="min-height:88px">${esc(segment.visual_prompt)}</textarea></div>
          </div>
          <div class="queue-controls" style="justify-content:flex-start; margin-top:8px; flex-wrap:wrap">
            <input id="timelineDuration-${segment.id}" style="width:76px" type="number" min="1" max="3600" value="${esc(segment.duration_seconds)}" title="Thời lượng (giây)" />
            <input id="timelineAudio-${segment.id}" style="min-width:180px" value="${esc(segment.audio_path)}" placeholder="Đường dẫn audio TTS" />
            <input id="timelineVisual-${segment.id}" style="min-width:180px" value="${esc(segment.visual_path)}" placeholder="Đường dẫn video/ảnh" />
            <select id="timelineAudioAsset-${segment.id}" onchange="attachTimelineAsset(${segment.id}, this.value)" aria-label="Gắn audio local">${assetOptions(assets, 'audio', segment.audio_path)}</select>
            <select id="timelineVisualAsset-${segment.id}" onchange="attachTimelineAsset(${segment.id}, this.value)" aria-label="Gắn video hoặc ảnh local">${assetOptions(assets, ['video', 'image'], segment.visual_path)}</select>
            <select id="timelineStatus-${segment.id}" aria-label="Trạng thái timeline">
              <option value="planned" ${segment.status === 'planned' ? 'selected' : ''}>Đang chuẩn bị</option>
              <option value="voice_ready" ${segment.status === 'voice_ready' ? 'selected' : ''}>Đã có voice</option>
              <option value="asset_ready" ${segment.status === 'asset_ready' ? 'selected' : ''}>Đã có asset</option>
              <option value="ready" ${segment.status === 'ready' ? 'selected' : ''}>Sẵn sàng</option>
              <option value="done" ${segment.status === 'done' ? 'selected' : ''}>Xong</option>
            </select>
            <button class="btn small ghost" onclick="saveTimelineSegment(${segment.id})">Lưu đoạn</button>
          </div>
          <div class="queue-controls" style="justify-content:flex-start; margin-top:8px; flex-wrap:wrap">${sceneControls}</div>
          <div class="secondary-text" style="margin-top:6px">AI tạo cảnh · ${sceneStatus}</div>
        </div>
      </div>`;
    }).join('') : '<div class="empty">Chưa có timeline. Hãy tạo sau khi đã có shot list.</div>';
    const batchSceneAction = timeline.length
      ? `<select id="batchSceneRatio-${project.id}" aria-label="Định dạng kích thước"><option value="1280:720">Ngang 16:9</option><option value="720:1280">Dọc 9:16</option><option value="1024:1024">Vuông 1:1</option></select><select id="batchImageProvider-${project.id}" aria-label="Engine tạo tất cả ảnh"><option value="antigravity_image">Antigravity · ảnh theo gói</option><option value="meta_ai_image">Meta AI · ảnh (gói đăng ký)</option><option value="gemini_image" ${geminiReady ? 'selected' : ''}>Gemini Image</option>${openaiImageReady ? '<option value="openai_image">GPT Image</option>' : ''}</select><button class="btn small primary" onclick="generateAllSceneImages(${project.id})">✦ Tạo tất cả ảnh AI</button><select id="batchVideoProvider-${project.id}" aria-label="Engine tạo tất cả video">${VIDEO_PROVIDER_OPTIONS}</select><button class="btn small primary" onclick="generateAllSceneVideos(${project.id})">✦ Tạo tất cả video AI</button>`
      : '';
    const timelineActions = shots.length ? `
      <button class="btn small primary" onclick="generateTimeline(${project.id}, ${timeline.length ? 'false' : 'true'})">${timeline.length ? 'Giữ timeline hiện tại' : 'Tạo timeline'}</button>
      <button class="btn small ghost" onclick="regenerateTimeline(${project.id})">Tạo lại timeline</button>
      ${batchSceneAction}
      <a class="btn small ghost" href="/api/projects/${project.id}/timeline/manifest" target="_blank" rel="noreferrer">Xuất manifest JSON</a>
      <a class="btn small ghost" href="/api/projects/${project.id}/timeline/markdown" target="_blank" rel="noreferrer">Xuất timeline Markdown</a>
      <button class="btn small primary" onclick="exportPremiere(${project.id})">Xuất gói Premiere</button>` :
      '<span class="secondary-text">Cần có shot list trước khi tạo timeline.</span>';
    const assetRows = assets.length ? assets.map((asset) => `
      <div class="job-row">
        <span class="job-dot ${asset.analysis_status === 'completed' ? 'completed' : asset.analysis_status === 'running' ? 'running' : ''}"></span>
        <div class="job-main">
          <div class="job-title">${esc(asset.asset_type)} · ${esc(asset.original_name)} · ${fileSize(asset.file_size)}</div>
          <div class="job-meta">${esc(asset.analysis_status)}${asset.has_transcript ? ' · Đã có transcript' : ''} · SHA-256 ${esc(String(asset.sha256 || '').slice(0, 12))}</div>
          ${asset.analysis_error ? `<div class="error-text">${esc(asset.analysis_error)}</div>` : ''}
        </div>
        <div class="queue-controls" style="justify-content:flex-end">
          <a class="btn small ghost" href="/api/assets/${asset.id}/download" target="_blank" rel="noreferrer">Mở file</a>
          ${asset.asset_type === 'audio' || asset.asset_type === 'video' ? `<button class="btn small ghost" onclick="analyzeLocalAsset(${asset.id})">Whisper local</button>` : ''}
        </div>
      </div>`).join('') : '<div class="empty">Chưa có nguyên liệu local trong project.</div>';
    const assetPanel = `
      <div data-project-view="assets" class="analysis-item project-view-panel" style="margin-top:14px">
        <label>Thư viện nguyên liệu local · ${number(assets.length)} file</label>
        <p class="panel-sub">Upload video, audio hoặc ảnh để phân tích cục bộ, gắn vào timeline và đóng gói sang Premiere.</p>
        <div class="queue-controls" style="justify-content:flex-start; margin-top:10px; flex-wrap:wrap">
          <input id="assetUploadFile" type="file" accept="video/*,audio/*,image/*" />
          <select id="assetUploadType" aria-label="Loại nguyên liệu"><option value="video">Video</option><option value="audio">Audio</option><option value="image">Ảnh</option></select>
          <button class="btn small primary" onclick="uploadProjectAsset(${project.id})">Upload nguyên liệu</button>
        </div>
        <div style="margin-top:8px">${assetRows}</div>
        </div>`;
    const thumbnailCards = thumbnails.length ? thumbnails.map((thumbnail) => `
      <article class="storyboard-card" style="max-width:320px">
        <div class="storyboard-card-head"><div class="storyboard-card-title">${thumbnail.selected ? '✓ Đã chọn' : 'Phương án'}</div><span class="tag ${thumbnail.selected ? 'green' : 'orange'}">${esc(thumbnail.provider)}</span></div>
        <div class="storyboard-media"><img src="/api/assets/${thumbnail.asset_id}/download" alt="${esc(thumbnail.original_name)}"></div>
        <div class="storyboard-body"><div class="secondary-text">${esc(thumbnail.prompt || 'Frame từ video đã render')}</div><div class="secondary-text" style="margin-top:5px">${esc(thumbnail.model)}${thumbnail.seed == null ? '' : ` · seed ${esc(thumbnail.seed)}`}</div><div class="queue-controls" style="justify-content:flex-start;margin-top:8px"><button class="btn small ${thumbnail.selected ? 'ghost' : 'primary'}" onclick="selectProjectThumbnail(${project.id}, ${thumbnail.id})" ${thumbnail.selected ? 'disabled' : ''}>${thumbnail.selected ? 'Đang dùng' : 'Chọn bản này'}</button><button class="btn small danger" onclick="deleteProjectThumbnail(${project.id}, ${thumbnail.id})">Xoá</button></div></div>
      </article>`).join('') : '<div class="empty">Chưa có thumbnail. Tạo từ video đã render rồi chọn một bản cuối.</div>';
    const thumbnailPanel = `<div class="analysis-item" style="margin-top:12px"><label>Thumbnail · ${number(thumbnails.length)} phương án</label><p class="panel-sub">Hai cách: <b>AI vẽ</b> ảnh bìa theo câu chuyện của video, hoặc <b>cắt khung</b> từ bản đã render (app chọn khung nét và đủ sáng nhất).</p><div class="queue-controls" style="justify-content:flex-start;margin-top:8px;flex-wrap:wrap"><input id="thumbnailPrompt" value="${esc(script?.script_title || project.title || '')}" placeholder="Prompt/ghi chú thumbnail" aria-label="Prompt thumbnail"><select id="projectThumbnailProvider" aria-label="Model vẽ thumbnail">${imageProviderOptions('gemini_image')}</select><button class="btn small primary" onclick="generateProjectThumbnails(${project.id}, 'ai')">AI vẽ thumbnail</button><button class="btn small ghost" onclick="generateProjectThumbnails(${project.id}, 'frame')">Cắt khung từ video</button></div><div class="storyboard-grid" style="margin-top:10px">${thumbnailCards}</div></div>`;
    const musicOptions = `<option value="">Không dùng nhạc nền</option>${assets.filter((asset) => asset.asset_type === 'audio').map((asset) => `<option value="${asset.id}" ${Number(renderSettings.music_asset_id) === Number(asset.id) ? 'selected' : ''}>${esc(asset.original_name)} · ${fileSize(asset.file_size)}</option>`).join('')}`;
    const productionJobRows = productionJobs.length ? productionJobs.map((job) => `
      <div class="job-row">
        <span class="job-dot ${job.status === 'completed' ? 'completed' : job.status === 'running' ? 'running' : ''}"></span>
        <div class="job-main">
          <div class="job-title">${esc(job.job_type)} · ${esc(job.provider)} · ${productionJobStatusTag(job.status)}</div>
          <div class="job-meta">${date(job.created_at)}${job.output_path ? ` · ${esc(job.output_path)}` : ''}</div>
          ${job.error ? `<div class="error-text">${esc(job.error)}</div>` : ''}
          ${(productionJobEvents[job.id] || []).length ? `<details style="margin-top:6px"><summary class="secondary-text">Nhật ký job (${number((productionJobEvents[job.id] || []).length)})</summary><div class="secondary-text" style="margin-top:5px">${(productionJobEvents[job.id] || []).map((event) => `<div>${date(event.created_at)} · ${esc(event.message)}</div>`).join('')}</div></details>` : ''}
        </div>
        ${job.status === 'queued' ? `<button class="btn small danger" onclick="cancelProductionJob(${project.id}, ${job.id})">Hủy</button>` : ''}
        ${['error', 'cancelled'].includes(job.status) ? `<button class="btn small primary" onclick="retryProductionJob(${project.id}, ${job.id}, '${esc(job.job_type)}')">Chạy lại</button>` : ''}
      </div>`).join('') : '<div class="empty">Chưa có production job.</div>';
    const sourceMediaReady = video.media_status === 'downloaded_for_editing' && Boolean(video.local_media_path);
    const sourceVisualAction = sourceMediaReady
      ? `<button class="btn small ghost" onclick="queueProductionJob(${project.id}, 'source_visuals', 'source_video', true)">2. Cắt cảnh từ video nguồn</button>`
      : `<button class="btn small ghost" onclick="downloadProjectSource(${project.id}, '${esc(video.youtube_video_id)}')">1. Tự động tải video nguồn</button>`;
    const productionActions = timeline.length ? `
      <button class="btn small primary" onclick="queueProductionJob(${project.id}, 'voiceover', 'dry_run')">Voiceover dry-run</button>
      <button class="btn small primary" onclick="queueProductionJob(${project.id}, 'premiere_draft', 'dry_run')">Premiere draft dry-run</button>
      <button class="btn small ghost" onclick="queueSelectedVoiceover(${project.id}, 'premiere_draft')">AI voiceover + Premiere theo lựa chọn</button>
      <button class="btn small ghost" onclick="queueSelectedVoiceover(${project.id}, 'voiceover')">Tạo voice theo lựa chọn</button>
      ${sourceVisualAction}
      <button class="btn small primary" onclick="queueProductionJob(${project.id}, 'render', 'dry_run')">Render dry-run</button>
      ${state.productionQueue?.gpu_only && state.productionQueue?.nvenc_available ? `<button class="btn small primary" onclick="queueProductionJob(${project.id}, 'render', 'ffmpeg_builtin', true)">Render FFmpeg · NVIDIA GPU</button>` : '<span class="tag orange">GPU/NVENC chưa sẵn sàng · render bị khóa</span>'}` :
      '<span class="secondary-text">Cần có timeline trước khi chạy worker.</span>';
    const quickProductionActions = timeline.length ? `
      <button class="btn primary" onclick="queueSelectedVoiceover(${project.id}, 'voiceover')">1. Tạo giọng đọc</button>
      ${state.productionQueue?.gpu_only && state.productionQueue?.nvenc_available ? `<button class="btn primary" onclick="queueProductionJob(${project.id}, 'render', 'ffmpeg_builtin', true)">2. Dựng MP4 bằng NVIDIA GPU</button>` : '<span class="tag orange">Chưa sẵn sàng render GPU</span>'}` :
      '<span class="secondary-text">Cần có storyboard và timeline trước khi dựng video.</span>';
    const renderQuickPanel = `
      <div data-project-view="export" class="analysis-item project-view-panel" style="margin-top:14px;border-color:rgba(245,158,11,.42);background:linear-gradient(120deg,rgba(245,158,11,.09),rgba(16,20,27,.9) 55%)">
        <label>2. DỰNG VIDEO · CHỈ DÙNG HAI NÚT NÀY</label>
        <p class="panel-sub">Sau khi mỗi cảnh đã có ảnh/video, bấm tạo giọng đọc, chờ xong rồi bấm dựng MP4. Cài đặt chi tiết nằm bên dưới và không bắt buộc.</p>
        <div class="queue-controls" style="justify-content:flex-start;margin-top:10px;flex-wrap:wrap">${quickProductionActions}</div>
      </div>`;
    const finalVideoPanel = finalVideo.available ? `
      <div data-project-view="export" class="analysis-item project-view-panel" style="margin-top:14px;border-color:rgba(34,197,94,.5)">
        <label>Video hoàn chỉnh · sẵn sàng</label>
        <p class="panel-sub">Bản MP4 đã render xong. Xem lại trước khi chuyển sang Publisher.</p>
        <video controls preload="metadata" style="display:block;width:100%;max-width:960px;margin-top:10px;border-radius:10px;background:#000" src="${esc(finalVideo.url || `/api/projects/${project.id}/final-video`)}"></video>
        <div class="queue-controls" style="justify-content:flex-start;margin-top:10px"><a class="btn small primary" href="${esc(finalVideo.url || `/api/projects/${project.id}/final-video`)}" target="_blank" rel="noreferrer">Mở / tải MP4</a>${finalVideo.size_bytes ? `<span class="secondary-text">${fileSize(finalVideo.size_bytes)}</span>` : ''}</div>
      </div>` : `
      <div data-project-view="export" class="analysis-item project-view-panel" style="margin-top:14px">
        <label>Video hoàn chỉnh · chưa có</label>
        <p class="panel-sub">Cần tạo timeline, gắn hình/video thật cho từng cảnh, sau đó bấm “Render FFmpeg · NVIDIA GPU”. App sẽ hiển thị MP4 tại đây khi job hoàn tất.</p>
      </div>`;
    const adapterStatus = state.productionQueue?.voxcpm_runtime_ready ? 'VOXCPM2 GPU SẴN SÀNG' : state.productionQueue?.edge_tts_runtime_ready ? 'EDGE TTS SẴN SÀNG' : state.productionQueue?.pyvideotrans_runtime_ready ? 'PYVIDEOTRANS SẴN SÀNG' : 'TTS CHƯA SẴN SÀNG';
    const ffmpegStatus = state.productionQueue?.ffmpeg_builtin_available ? 'FFMPEG LOCAL SẴN SÀNG' : 'FFMPEG LOCAL KHÔNG TÌM THẤY';
    const publicationRows = publications.length ? publications.map((item) => `<div class="job-row"><span class="job-dot ${item.status === 'completed' ? 'completed' : item.status === 'uploading' ? 'running' : ''}"></span><div class="job-main"><div class="job-title">YouTube Publisher · ${esc(item.status)}</div><div class="job-meta">${esc(item.scheduled_at || item.created_at || '')}${item.youtube_video_id ? ` · ${esc(item.youtube_video_id)}` : ''}</div>${item.error ? `<div class="error-text">${esc(item.error)}</div>` : ''}</div>${item.status === 'queued' ? `<button class="btn small danger" onclick="cancelPublication(${item.id}, ${project.id})">Hủy</button>` : ''}${['error', 'cancelled'].includes(item.status) ? `<button class="btn small ghost" onclick="retryPublication(${item.id}, ${project.id})">Chạy lại</button>` : ''}</div>`).join('') : '<div class="empty">Chưa có publication nào.</div>';
    const publisherActions = `<div class="analysis-item" style="margin-top:12px;border-color:rgba(34,211,238,.35)"><label>Publisher YouTube · chờ duyệt cuối</label><p class="panel-sub">Chỉ đưa video đã render vào hàng đợi. Nếu không chọn thời gian, app dùng lịch mặc định của kênh.</p><div class="queue-controls" style="justify-content:flex-start; margin-top:8px; flex-wrap:wrap"><select id="publicationChannel" aria-label="Kênh đăng">${managedChannelOptions}</select><select id="publicationThumbnail" aria-label="Thumbnail">${thumbnailOptions}</select><select id="publicationPrivacy" aria-label="Quyền riêng tư"><option value="">Theo kênh</option><option value="private">Riêng tư</option><option value="unlisted">Không công khai</option><option value="public">Công khai</option></select><label style="display:flex;align-items:center;gap:6px;text-transform:none;letter-spacing:0;font-size:12px;color:var(--muted)">Đăng lúc <input id="publicationScheduledAt" type="datetime-local" /></label><button class="btn small primary" onclick="queueProjectPublication(${project.id})">Đưa video vào Publisher</button><span class="secondary-text">${publications.length} publication</span></div><div id="publisherWaiting" class="studio-model-note" style="margin-top:6px">${publisherWaitingNote(publications)}</div><div style="display:none"></div><div style="margin-top:8px">${publicationRows}</div></div>`;
    const platformPublicationRows = publications.length ? publications.map((item) => {
      const platform = String(item.platform || 'youtube').toUpperCase();
      const variant = item.video_variant === 'short' ? 'Short' : 'Video dài';
      const delivery = item.status === 'ready_manual' ? 'Sẵn sàng đăng thủ công' : item.status;
      const videoUrl = item.video_variant === 'short' ? `/api/projects/${project.id}/short-video` : `/api/projects/${project.id}/final-video`;
      return `<div class="job-row"><span class="job-dot ${item.status === 'completed' ? 'completed' : item.status === 'uploading' ? 'running' : ''}"></span><div class="job-main"><div class="job-title">${esc(platform)} · ${esc(variant)} · ${esc(delivery)}</div><div class="job-meta">${esc(item.output_profile || '')} · ${esc(item.scheduled_at || item.created_at || '')}${item.youtube_video_id ? ` · ${esc(item.youtube_video_id)}` : ''}</div>${item.error ? `<div class="error-text">${esc(item.error)}</div>` : ''}</div>${item.status === 'ready_manual' ? `<a class="btn small ghost" href="/api/publications/${item.id}/manual-package" target="_blank" rel="noreferrer">Tải gói đăng</a>` : ''}${['queued', 'ready_manual'].includes(item.status) ? `<button class="btn small danger" onclick="cancelPublication(${item.id}, ${project.id})">Hủy</button>` : ''}${['error', 'cancelled'].includes(item.status) ? `<button class="btn small ghost" onclick="retryPublication(${item.id}, ${project.id})">Chạy lại</button>` : ''}</div>`;
    }).join('') : '<div class="empty">Chưa có lần xuất bản nào.</div>';
    const platformPublishingActions = `<div class="analysis-item" style="margin-top:12px;border-color:rgba(34,211,238,.35)"><label>XUẤT BẢN ĐA NỀN TẢNG · chờ duyệt cuối</label><p class="panel-sub">Chọn đúng kênh đích, nền tảng, loại video và tỷ lệ. YouTube sẽ upload qua OAuth; TikTok, Facebook và Instagram tạo gói MP4/metadata sẵn sàng để đăng thủ công cho đến khi kết nối OAuth riêng.</p><div class="queue-controls" style="justify-content:flex-start; margin-top:8px; flex-wrap:wrap"><select id="publicationPlatform" aria-label="Nền tảng" onchange="syncPublicationTarget()"><option value="youtube">YouTube</option><option value="tiktok">TikTok</option><option value="facebook">Facebook</option><option value="instagram">Instagram</option></select><select id="publicationChannel" aria-label="Kênh đăng" onchange="syncPublicationTarget()">${managedChannelOptions}</select><select id="publicationVariant" aria-label="Loại video" onchange="syncPublicationTarget()"><option value="long">Video dài</option><option value="short">Short riêng</option></select><select id="publicationProfile" aria-label="Định dạng xuất bản"><option value="youtube_landscape">YouTube video · 16:9</option><option value="youtube_shorts">YouTube Shorts · 9:16</option><option value="tiktok">TikTok · 9:16</option><option value="instagram_reels">Instagram Reels · 9:16</option><option value="facebook_reels">Facebook Reels · 9:16</option><option value="facebook_feed">Facebook Feed · 1:1</option></select><select id="publicationThumbnail" aria-label="Thumbnail YouTube">${thumbnailOptions}</select><select id="publicationPrivacy" aria-label="Quyền riêng tư"><option value="">Theo kênh</option><option value="private">Riêng tư</option><option value="unlisted">Không công khai</option><option value="public">Công khai</option></select><label style="display:flex;align-items:center;gap:6px;text-transform:none;letter-spacing:0;font-size:12px;color:var(--muted)">Đăng lúc <input id="publicationScheduledAt" type="datetime-local" /></label></div><div class="studio-grid" style="margin-top:8px"><div class="studio-field"><label for="publicationTitle">Tiêu đề</label><input id="publicationTitle" value="${esc(script?.script_title || project.title || '')}" maxlength="100"></div><div class="studio-field"><label for="publicationTags">Hashtag / tag</label><input id="publicationTags" value="${esc((writer?.hashtags || []).join(', '))}" placeholder="ai, short, #video"></div></div><div class="studio-field" style="margin-top:8px"><label for="publicationDescription">Mô tả / caption</label><textarea id="publicationDescription" maxlength="5000">${esc(writer?.new_description || '')}</textarea></div><div class="queue-controls" style="justify-content:flex-start; margin-top:8px; flex-wrap:wrap"><button class="btn small primary" onclick="queueProjectPublication(${project.id})">Chuẩn bị / đăng video</button><span id="publicationTargetNote" class="secondary-text">YouTube: upload tự động khi OAuth đã kết nối.</span><span class="secondary-text">${publications.length} lần xuất bản</span></div><div style="margin-top:8px">${platformPublicationRows}</div></div>`;
    const directorAction = `
      <div class="analysis-item" style="margin-bottom:14px; border-color:rgba(34,197,94,.5); background:linear-gradient(120deg,rgba(34,197,94,.11),rgba(16,20,27,.9) 52%)">
        <label>AI ĐẠO DIỄN · DỰNG VIDEO TRỌN LUỒNG</label>
        <p class="panel-sub">Nhập ý tưởng của bạn trước. Codex sẽ tạo câu chuyện và prompt cảnh mới dựa trên cấu trúc/phong cách tham chiếu. Sau đó cần tạo video AI hoặc gắn asset thật cho từng cảnh; app không render thẻ chữ thành bản xuất bản.</p>
        <div class="queue-controls" style="justify-content:flex-start; margin-top:10px; flex-wrap:wrap">
          <button class="btn primary" onclick="runDirectorAuto(${project.id})">✦ AI Đạo diễn: tạo kịch bản &amp; storyboard</button>
          <button class="btn ghost" onclick="showProjectQuality(${project.id})">Xem Quality Check</button>
        </div>
        <div class="secondary-text" style="margin-top:8px">Kịch bản: Codex đang đăng nhập · Voice: ${adapterStatus} · Render: ${ffmpegStatus}</div>
      </div>`;
    const autoDraftPanel = timeline.length ? `<div data-project-view="overview" class="project-view-panel">
      ${directorAction}
      <div class="analysis-item" style="margin-bottom:14px; border-color:rgba(245,158,11,.42); background:linear-gradient(120deg,rgba(245,158,11,.1),rgba(16,20,27,.9) 52%)">
        <label>AI AUTO DRAFT · ĐIỀU KHIỂN TỰ ĐỘNG</label>
        <p class="panel-sub">Các nút bên dưới dành cho khi bạn muốn chạy từng công đoạn hoặc xuất timeline sang Premiere để tinh chỉnh thủ công.</p>
        <div class="queue-controls" style="justify-content:flex-start; margin-top:10px; flex-wrap:wrap">
          <button class="btn primary" onclick="queueSelectedVoiceover(${project.id}, 'premiere_draft')">▶ Tự động lồng tiếng + tạo gói Premiere</button>
          <button class="btn ghost" onclick="exportPremiere(${project.id})">Xuất gói Premiere hiện tại</button>
          <button class="btn ghost" onclick="queueProductionJob(${project.id}, 'premiere_draft', 'dry_run')">Chạy thử không lồng tiếng</button>
        </div>
        <div class="secondary-text" style="margin-top:8px">Voice: ${adapterStatus} · Render: ${ffmpegStatus} · Worker: ${state.productionQueue?.worker_running ? 'ĐANG CHẠY' : 'ĐÃ DỪNG'}</div>
      </div>` : `<div data-project-view="overview" class="project-view-panel">
      ${directorAction}
      <div class="analysis-item" style="margin-bottom:14px">
        <label>AI AUTO DRAFT · CHƯA SẴN SÀNG</label>
        <p class="panel-sub">Bạn vẫn có thể bấm AI Đạo diễn ở trên để tự tạo script, shot list, timeline và dựng bản video đầu tiên.</p>
      </div>`;
    const projectGuide = `
      <div data-project-view="overview" class="analysis-item project-view-panel" style="margin-bottom:14px;border-color:rgba(34,211,238,.45);background:linear-gradient(120deg,rgba(34,211,238,.1),rgba(16,20,27,.9) 55%)">
        <label>BẮT ĐẦU TẠI ĐÂY · 3 VIỆC DỄ HIỂU</label>
        <p class="panel-sub">Bạn không cần chỉnh các đường dẫn, timeline hay thông số kỹ thuật. Chỉ làm ba việc dưới đây theo thứ tự.</p>
        <div class="analysis-list" style="margin:10px 0 0"><div><b>1. Nội dung & cảnh:</b> kiểm tra kịch bản và lời AI đọc ở từng cảnh. Hiện có <b>${number(shots.length)} cảnh</b>.</div><div><b>2. Dựng video:</b> chọn giọng, tạo voice và bấm render khi các cảnh đã có ảnh/video.</div><div><b>3. Xuất bản:</b> xem MP4 hoàn chỉnh rồi mới đưa vào YouTube.</div></div>
        <div class="queue-controls" style="justify-content:flex-start;margin-top:12px;flex-wrap:wrap"><button class="btn primary" onclick="switchProjectView('editor')">1. Mở nội dung & cảnh</button><button class="btn ghost" onclick="switchProjectView('export')">2. Sang dựng & xuất video</button><button class="btn ghost" onclick="switchProjectView('assets')">Tệp của bạn (chỉ khi cần)</button></div>
      </div>`;
    $('projectBody').innerHTML = `
      <div class="project-tabs" role="tablist" aria-label="Khu vực dự án">
        <button class="project-tab" data-project-tab="overview" onclick="switchProjectView('overview')">Bắt đầu</button>
        <button class="project-tab" data-project-tab="editor" onclick="switchProjectView('editor')">Nội dung &amp; cảnh</button>
        <button class="project-tab" data-project-tab="export" onclick="switchProjectView('export')">Dựng &amp; xuất</button>
        <button class="project-tab" data-project-tab="assets" onclick="switchProjectView('assets')">Tệp nâng cao</button>
      </div>
      ${projectGuide}
      <details data-project-view="overview" class="analysis-item project-view-panel" style="margin-bottom:14px"><summary class="panel-sub" style="cursor:pointer"><b>AI Đạo diễn và công cụ tự động (nâng cao)</b> · chỉ dùng khi muốn làm lại toàn bộ</summary><div style="margin-top:12px">${autoDraftPanel}</div></details>
      <div data-project-view="overview" class="analysis-grid project-view-panel">
        <div class="analysis-item"><label>Trạng thái</label><strong>${projectStatusTag(project.status)}</strong></div>
        <div class="analysis-item"><label>Transcript</label><strong>${readiness.has_transcript ? 'Đã có' : 'Chưa có'}</strong></div>
        <div class="analysis-item"><label>AI Writer</label><strong>${readiness.has_writer_content ? 'Đã có' : 'Chưa có'}</strong></div>
      </div>
      <div data-project-view="overview" class="analysis-item project-view-panel" style="margin-top:10px"><label>Kênh xuất bản & workflow</label><strong>${esc(managedChannelSummary)}</strong>${channelPresetAction}</div>
      <div data-project-view="overview" class="analysis-columns project-view-panel">
        <div>
          <div class="eyebrow">VIDEO NGUỒN</div>
          <p class="panel-sub">${esc(video.title || project.title || '')}</p>
          <div class="secondary-text">${esc(video.youtube_video_id || '')} · ${esc(channelName(video.youtube_channel_id))} · ${date(video.published_at)}</div>
          <div class="eyebrow" style="margin-top:15px">CHECKLIST TIẾP THEO</div>
          <ul class="analysis-list">${nextActions}</ul>
          <div class="eyebrow" style="margin-top:15px">TỪ KHÓA METADATA</div>
          <div class="keyword-list">${keywords}</div>
        </div>
        <div>
          <div class="eyebrow">AI WRITER · TIÊU ĐỀ MỚI</div>
          <ul class="analysis-list">${titles}</ul>
          <div class="eyebrow" style="margin-top:15px">DÀN Ý KỊCH BẢN</div>
          <ul class="analysis-list">${outline}</ul>
        </div>
      </div>
      <div data-project-view="overview" class="analysis-item project-view-panel" style="margin-top:14px"><label>Transcript preview${transcript?.content_text_truncated ? ' · đã rút gọn' : ''}</label><p class="panel-sub" style="white-space:pre-wrap">${transcriptText}</p></div>
      ${assetPanel}
      <div data-project-view="editor" class="analysis-item project-view-panel" style="margin-top:14px">
        <label>Kịch bản sản xuất ${script ? `· v${script.version} · ${scriptStatusTag(script.status)}` : '· chưa có'}</label>
        <div class="transcript-grid" style="margin-top:10px">
          <div class="transcript-field"><label for="scriptTitleInput">Tiêu đề</label><input id="scriptTitleInput" value="${esc(scriptTitle)}" ${script ? '' : 'disabled'} /></div>
          <div class="transcript-field"><label for="scriptStatusView">Trạng thái</label><input id="scriptStatusView" value="${esc(script?.status || 'missing')}" disabled /></div>
          <div class="transcript-field"><label>Thao tác</label><div class="queue-controls" style="justify-content:flex-start">${scriptActions}</div></div>
        </div>
        <div class="transcript-field"><label for="scriptHookInput">Hook</label><textarea id="scriptHookInput" class="transcript-editor" style="min-height:80px" ${script ? '' : 'disabled'}>${esc(scriptHook)}</textarea></div>
        <div class="transcript-field"><label for="scriptIntroInput">Intro</label><textarea id="scriptIntroInput" class="transcript-editor" style="min-height:100px" ${script ? '' : 'disabled'}>${esc(scriptIntro)}</textarea></div>
        <div class="transcript-field"><label for="scriptMainInput">Nội dung chính</label><textarea id="scriptMainInput" class="transcript-editor" style="min-height:220px" ${script ? '' : 'disabled'}>${esc(scriptMain)}</textarea></div>
        <div class="transcript-field"><label for="scriptCtaInput">CTA</label><textarea id="scriptCtaInput" class="transcript-editor" style="min-height:80px" ${script ? '' : 'disabled'}>${esc(scriptCta)}</textarea></div>
      </div>
      <div data-project-view="editor" class="analysis-item project-view-panel" style="margin-top:14px">
        <label>Shot list / kế hoạch cảnh · ${number(shots.length)} cảnh</label>
        <div class="queue-controls" style="justify-content:flex-start; margin-top:10px">${shotActions}</div>
        <div style="margin-top:8px">${storyboardRows}</div>
      </div>
      ${renderQuickPanel}
      <div data-project-view="export" class="analysis-item project-view-panel" style="margin-top:14px">
        <label>Voiceover + timeline dựng video · ${number(timeline.length)} đoạn · ${number(totalTimelineDuration)} giây</label>
        <p class="panel-sub">Bạn chỉ cần dùng phần này khi muốn chỉnh từng đoạn thật sâu. Các nút tạo giọng và render đơn giản nằm ngay bên dưới.</p>
        <details style="margin-top:10px"><summary class="secondary-text" style="cursor:pointer">Mở chỉnh sâu timeline từng đoạn</summary><div class="queue-controls" style="justify-content:flex-start; margin-top:10px; flex-wrap:wrap">${timelineActions}</div><div style="margin-top:8px">${timelineRows}</div></details>
      </div>
      ${finalVideoPanel}
      <div data-project-view="export" class="analysis-item project-view-panel" style="margin-top:14px">
        <label>Thiết lập render tự động</label>
        <p class="panel-sub">Chọn nhạc nền đã import, âm lượng nền và kiểu chuyển cảnh. Voice AI vẫn được ưu tiên lớn hơn nhạc.</p>
        <div class="queue-controls" style="justify-content:flex-start; margin-top:10px; flex-wrap:wrap">
          <select id="renderMusicAsset" aria-label="Nhạc nền">${musicOptions}</select>
          <label style="display:flex;align-items:center;gap:6px;text-transform:none;letter-spacing:0;font-size:12px;color:var(--muted)">Âm lượng <input id="renderMusicVolume" type="number" min="0" max="0.5" step="0.01" value="${esc(renderSettings.music_volume ?? 0.12)}" style="width:72px" /></label>
          <select id="renderTransitionStyle" aria-label="Chuyển cảnh"><option value="fade" ${renderSettings.transition_style === 'fade' ? 'selected' : ''}>Fade ngắn</option><option value="none" ${renderSettings.transition_style === 'none' ? 'selected' : ''}>Cắt thẳng</option></select>
          <select id="renderOutputProfile" aria-label="Định dạng đầu ra"><option value="youtube_landscape" ${renderSettings.output_profile === 'youtube_landscape' ? 'selected' : ''}>YouTube video · 16:9</option><option value="youtube_shorts" ${renderSettings.output_profile === 'youtube_shorts' ? 'selected' : ''}>YouTube Shorts · 9:16</option><option value="tiktok" ${renderSettings.output_profile === 'tiktok' ? 'selected' : ''}>TikTok · 9:16</option><option value="instagram_reels" ${renderSettings.output_profile === 'instagram_reels' ? 'selected' : ''}>Instagram Reels · 9:16</option><option value="facebook_reels" ${renderSettings.output_profile === 'facebook_reels' ? 'selected' : ''}>Facebook Reels · 9:16</option><option value="facebook_feed" ${renderSettings.output_profile === 'facebook_feed' ? 'selected' : ''}>Facebook Feed · 1:1</option></select>
          <select id="renderVoiceProvider" aria-label="Model lồng tiếng"><option value="edge_tts" ${renderSettings.voice_provider === 'edge_tts' ? 'selected' : ''}>Edge TTS · cloud/online</option><option value="pyvideotrans" ${renderSettings.voice_provider === 'pyvideotrans' ? 'selected' : ''}>pyVideoTrans · local GPU</option><option value="voxcpm" ${renderSettings.voice_provider === 'voxcpm' ? 'selected' : ''}>VoxCPM2 · local GPU · đa ngôn ngữ</option></select>
          <select id="renderVoiceModel" aria-label="Giọng/model lồng tiếng">
            <option value="vi-VN-HoaiMyNeural" ${selectedVoiceModel === 'vi-VN-HoaiMyNeural' ? 'selected' : ''}>VI · Hoài My</option>
            <option value="vi-VN-NamMinhNeural" ${selectedVoiceModel === 'vi-VN-NamMinhNeural' ? 'selected' : ''}>VI · Nam Minh</option>
            <option value="en-US-AriaNeural" ${selectedVoiceModel === 'en-US-AriaNeural' ? 'selected' : ''}>EN · Aria</option>
            <option value="en-US-GuyNeural" ${selectedVoiceModel === 'en-US-GuyNeural' ? 'selected' : ''}>EN · Guy</option>
            <option value="th-TH-PremwadeeNeural" ${selectedVoiceModel === 'th-TH-PremwadeeNeural' ? 'selected' : ''}>TH · Premwadee</option>
            <option value="pt-BR-FranciscaNeural" ${selectedVoiceModel === 'pt-BR-FranciscaNeural' ? 'selected' : ''}>PT-BR · Francisca</option>
            <option value="pt-BR-AntonioNeural" ${selectedVoiceModel === 'pt-BR-AntonioNeural' ? 'selected' : ''}>PT-BR · Antonio</option>
            <option value="voxcpm-default" ${selectedVoiceModel === 'voxcpm-default' ? 'selected' : ''}>VoxCPM2 · giọng mặc định</option>
            <option value="design:Vietnamese female narrator, warm, clear and natural" ${selectedVoiceModel === 'design:Vietnamese female narrator, warm, clear and natural' ? 'selected' : ''}>VoxCPM2 · nữ thuyết minh ấm</option>
            <option value="design:Vietnamese male narrator, deep, clear and confident" ${selectedVoiceModel === 'design:Vietnamese male narrator, deep, clear and confident' ? 'selected' : ''}>VoxCPM2 · nam thuyết minh chắc</option>
          </select>
          <select id="renderVoiceRate" aria-label="Tốc độ giọng đọc">
            <option value="-25%" ${renderSettings.voice_rate === '-25%' ? 'selected' : ''}>Rất chậm · -25%</option>
            <option value="-15%" ${renderSettings.voice_rate === '-15%' ? 'selected' : ''}>Chậm · -15%</option>
            <option value="-8%" ${renderSettings.voice_rate === '-8%' ? 'selected' : ''}>Hơi chậm · -8%</option>
            <option value="+0%" ${(renderSettings.voice_rate || '+0%') === '+0%' ? 'selected' : ''}>Bình thường · 0%</option>
            <option value="+8%" ${renderSettings.voice_rate === '+8%' ? 'selected' : ''}>Hơi nhanh · +8%</option>
            <option value="+15%" ${renderSettings.voice_rate === '+15%' ? 'selected' : ''}>Nhanh · +15%</option>
            <option value="+25%" ${renderSettings.voice_rate === '+25%' ? 'selected' : ''}>Rất nhanh · +25%</option>
          </select>
          <select id="renderVoiceReferenceAsset" aria-label="Giọng mẫu VoxCPM">${voiceReferenceOptions}</select>
          <input id="renderVoiceReferenceFile" type="file" accept="audio/*" aria-label="Upload file giọng mẫu" />
          <button class="btn small ghost" onclick="uploadVoiceReferenceAudio(${project.id})">Upload giọng mẫu</button>
          <input id="renderVoicePromptText" value="${esc(renderSettings.voice_prompt_text || '')}" placeholder="Mô tả giọng mẫu, ví dụ: giọng nam ấm, chậm, rõ" aria-label="Mô tả giọng mẫu" />
          <select id="renderSubtitleProvider" aria-label="Nguồn phụ đề"><option value="timeline_text" ${renderSettings.subtitle_provider === 'timeline_text' ? 'selected' : ''}>Phụ đề từ timeline</option><option value="faster_whisper_local" ${renderSettings.subtitle_provider === 'faster_whisper_local' ? 'selected' : ''}>Faster-Whisper · local</option></select>
          <select id="renderSubtitleModel" aria-label="Model phụ đề">
            <option value="timeline" ${selectedSubtitleModel === 'timeline' ? 'selected' : ''}>Timeline text</option>
            <option value="faster-whisper-small" ${selectedSubtitleModel === 'faster-whisper-small' ? 'selected' : ''}>Faster-Whisper small</option>
            <option value="faster-whisper-medium" ${selectedSubtitleModel === 'faster-whisper-medium' ? 'selected' : ''}>Faster-Whisper medium</option>
            <option value="faster-whisper-large-v3" ${selectedSubtitleModel === 'faster-whisper-large-v3' ? 'selected' : ''}>Faster-Whisper large-v3</option>
          </select>
          <select id="renderPublishLanguage" aria-label="Ngôn ngữ xuất bản"><option value="vi" ${renderSettings.publish_language === 'vi' ? 'selected' : ''}>Tiếng Việt</option><option value="en" ${renderSettings.publish_language === 'en' ? 'selected' : ''}>Tiếng Anh</option><option value="th" ${renderSettings.publish_language === 'th' ? 'selected' : ''}>Tiếng Thái</option><option value="pt-BR" ${renderSettings.publish_language === 'pt-BR' ? 'selected' : ''}>Tiếng Bồ Đào Nha (Brazil)</option><option value="es" ${renderSettings.publish_language === 'es' ? 'selected' : ''}>Tiếng Tây Ban Nha</option><option value="fr" ${renderSettings.publish_language === 'fr' ? 'selected' : ''}>Tiếng Pháp</option><option value="de" ${renderSettings.publish_language === 'de' ? 'selected' : ''}>Tiếng Đức</option><option value="ja" ${renderSettings.publish_language === 'ja' ? 'selected' : ''}>Tiếng Nhật</option><option value="ko" ${renderSettings.publish_language === 'ko' ? 'selected' : ''}>Tiếng Hàn</option><option value="zh-CN" ${renderSettings.publish_language === 'zh-CN' ? 'selected' : ''}>Tiếng Trung</option><option value="id" ${renderSettings.publish_language === 'id' ? 'selected' : ''}>Tiếng Indonesia</option></select>
          <button class="btn small ghost" onclick="saveRenderSettings(${project.id})">Lưu thiết lập</button>
        </div>
        <div class="queue-controls" style="justify-content:flex-start; margin-top:10px; flex-wrap:wrap">
          <label style="display:flex;align-items:center;gap:6px;text-transform:none;letter-spacing:0;font-size:12px;color:var(--muted)">OpenMontage runtime
            <select id="openMontageRuntime" aria-label="OpenMontage runtime">
              <option value="openmontage">Theo cấu hình local</option>
              <option value="openmontage_ffmpeg">FFmpeg · cắt ghép video ổn định</option>
              <option value="openmontage_remotion">Remotion · motion graphics / ảnh động</option>
              <option value="openmontage_hyperframes">HyperFrames · HTML/CSS/GSAP</option>
            </select>
          </label>
        </div>
        <p class="secondary-text" style="margin-top:8px">VoxCPM2: chọn một file giọng mẫu sạch khoảng 10–20 giây và dùng lại cho mọi đoạn để khóa màu giọng. Nếu chưa có file mẫu, app dùng giọng mặc định và có thể thay đổi giữa các đoạn.</p>
        <label>Production worker · voiceover / render</label>
        <p class="panel-sub">Chọn provider và giọng ở trên trước khi chạy. VoxCPM2/pyVideoTrans là local GPU; Edge TTS là cloud/online. Render FFmpeg dùng NVENC GPU.</p>
        <div class="queue-controls" style="justify-content:flex-start; margin-top:10px; flex-wrap:wrap">${productionActions}</div>
        ${thumbnailPanel}
        ${platformPublishingActions}
        <div style="margin-top:8px">${productionJobRows}</div>
      </div>
      <div data-project-view="overview" class="analysis-item project-view-panel" style="margin-top:10px"><label>Ghi chú project</label><p class="panel-sub">${esc(project.notes || 'Chưa có ghi chú.')}</p></div>`;
    syncPublicationTarget();
    renderPublicationSuggestions(project.id);
    switchProjectView(state.projectView || 'overview');
    $('projectDetail').classList.add('open');
    $('projectDetail').scrollIntoView({behavior: 'smooth', block: 'nearest'});
  }

  async function createScriptDraft(projectId) {
    setMessage('Đang tạo bản nháp kịch bản từ AI Writer...');
    try {
      const response = await api(`/api/projects/${projectId}/script/draft`, {method: 'POST'});
      state.scriptId = response.script.id;
      setMessage(`Đã tạo kịch bản v${response.script.version}.`, 'success');
      await openProjectDetail(projectId);
      await loadProjects();
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function runDirectorAuto(projectId) {
    const creativeDirection = prompt('Mô tả VIDEO MỚI bạn muốn tạo. Hãy nêu nhân vật, bối cảnh, diễn biến và thông điệp.\n\nVí dụ: Đổi câu chuyện thành chú mèo giao thư trong thành phố mưa; phong cách hoạt hình 3D ấm áp; cao trào là mèo cứu bưu kiện; kết thúc về lòng tốt.');
    if (creativeDirection === null) return;
    if (creativeDirection.trim().length < 12) return setMessage('Hãy nhập ý tưởng đủ rõ: nhân vật, bối cảnh và diễn biến chính.', 'error');
    const targetDurationRaw = prompt('Thời lượng video mục tiêu (giây). Ví dụ: 90', '90');
    if (targetDurationRaw === null) return;
    const targetDuration = Number(targetDurationRaw);
    if (!Number.isFinite(targetDuration) || targetDuration < 30 || targetDuration > 1800) return setMessage('Thời lượng cần nằm trong khoảng 30–1800 giây.', 'error');
    setMessage('AI Đạo diễn đang tạo kịch bản mới và blueprint video AI cho từng cảnh...');
    try {
      const response = await api(`/api/projects/${projectId}/director-draft`, {
        method: 'POST',
        body: JSON.stringify({provider: 'codex_cli', creative_direction: creativeDirection.trim(), target_duration_seconds: Math.round(targetDuration), auto_produce: false}),
      });
      state.scriptId = response.script?.id || null;
      setMessage('Đã tạo kịch bản và storyboard. Bước tiếp theo: tạo/duyệt video AI cho từng cảnh trong tab Dựng & duyệt.', 'success');
      await openProjectDetail(projectId, 'editor');
      await loadProjects();
    } catch (error) { setMessage(`AI Đạo diễn chưa chạy được: ${error.message}`, 'error'); }
  }

  async function showProjectQuality(projectId) {
    setMessage('Đang đọc Quality Check...');
    try {
      const report = await api(`/api/projects/${projectId}/quality-check`);
      const failed = Object.entries(report.checks || {}).filter(([, ok]) => !ok).map(([name]) => name);
      const label = report.status === 'pass' ? 'PASS' : 'CẦN KIỂM TRA';
      setMessage(`Quality Check: ${label} · ${report.segments || 0} đoạn · voice ${report.audio_duration_seconds || 0}s${failed.length ? ` · cảnh báo: ${failed.join(', ')}` : ''}`, report.status === 'pass' ? 'success' : 'error');
    } catch (error) { setMessage(`Không đọc được Quality Check: ${error.message}`, 'error'); }
  }

  // Both panels reach the same endpoint, and this one used to omit the mode
  // entirely - so it fell back to cropping a frame however the request was
  // meant, which is why "AI thumbnails" kept producing stills from the video.
  async function generateProjectThumbnails(projectId, mode = 'ai') {
    setMessage(mode === 'ai'
      ? 'AI đang vẽ thumbnail theo câu chuyện của video...'
      : 'Đang chọn khung nét nhất để cắt thumbnail...');
    try {
      const prompt = $('thumbnailPrompt')?.value || '';
      const provider = $('projectThumbnailProvider')?.value || 'gemini_image';
      const response = await api(`/api/projects/${projectId}/thumbnails/generate`, {
        method: 'POST', body: JSON.stringify({prompt, variants: 3, mode, provider}),
      });
      setMessage(`Đã tạo ${response.thumbnails?.length || 0} thumbnail local. Hãy chọn một bản cuối.`, 'success');
      await openProjectDetail(projectId);
    } catch (error) { setMessage(`Không tạo được thumbnail: ${error.message}`, 'error'); }
  }

  async function deleteProjectThumbnail(projectId, thumbnailId) {
    if (!confirm('Xoá thumbnail này? Ảnh sẽ bị xoá khỏi máy.')) return;
    try {
      await api(`/api/thumbnails/${thumbnailId}`, {method: 'DELETE'});
      setMessage('Đã xoá thumbnail.', 'success');
      await openProjectDetail(projectId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function selectProjectThumbnail(projectId, thumbnailId) {
    try {
      await api(`/api/thumbnails/${thumbnailId}/select`, {method: 'POST'});
      setMessage('Đã chọn thumbnail cho project.', 'success');
      await openProjectDetail(projectId);
    } catch (error) { setMessage(`Không chọn được thumbnail: ${error.message}`, 'error'); }
  }

  function currentScriptPayload(status = null) {
    const payload = {
      script_title: $('scriptTitleInput').value,
      hook: $('scriptHookInput').value,
      intro: $('scriptIntroInput').value,
      main_content: $('scriptMainInput').value,
      cta: $('scriptCtaInput').value,
    };
    if (status) payload.status = status;
    return payload;
  }

  async function saveCurrentScript(status = null) {
    if (!state.scriptId) return;
    setMessage('Đang lưu kịch bản...');
    try {
      const response = await api(`/api/scripts/${state.scriptId}`, {
        method: 'PATCH',
        body: JSON.stringify(currentScriptPayload(status)),
      });
      setMessage(`Đã lưu kịch bản v${response.script.version}.`, 'success');
      await openProjectDetail(response.script.project_id);
      await loadProjects();
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function setCurrentScriptReview() {
    await saveCurrentScript('review');
  }

  async function approveCurrentScript() {
    if (!state.scriptId) return;
    if (!confirm('Duyệt kịch bản này và đánh dấu project là đã duyệt?')) return;
    setMessage('Đang duyệt kịch bản...');
    try {
      const response = await api(`/api/scripts/${state.scriptId}/approve`, {method: 'POST'});
      setMessage('Đã duyệt kịch bản và project.', 'success');
      await openProjectDetail(response.script.project_id);
      await loadProjects();
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function generateShotList(projectId, force = false) {
    setMessage(force ? 'Đang tạo lại shot list...' : 'Đang tạo shot list...');
    try {
      const response = await api(`/api/projects/${projectId}/shots/generate`, {
        method: 'POST',
        body: JSON.stringify({force}),
      });
      setMessage(`Đã tạo ${response.shots.length} cảnh cho shot list.`, 'success');
      await openProjectDetail(projectId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function regenerateShotList(projectId) {
    if (!confirm('Tạo lại shot list sẽ thay thế các cảnh hiện tại của kịch bản mới nhất. Tiếp tục?')) return;
    await generateShotList(projectId, true);
  }

  async function createStoryboardShot(projectId) {
    setMessage('Đang thêm cảnh mới...');
    try {
      const response = await api(`/api/projects/${projectId}/shots`, {
        method: 'POST',
        body: JSON.stringify({section: 'main', asset_type: 'broll', duration_seconds: 8}),
      });
      setMessage(`Đã thêm cảnh ${response.shot.shot_index}. Hãy nhập lời dẫn và prompt rồi lưu.`, 'success');
      await openProjectDetail(projectId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function duplicateStoryboardShot(projectId, shotId) {
    setMessage(`Đang nhân bản cảnh ${shotId}...`);
    try {
      const response = await api(`/api/shots/${shotId}/duplicate`, {method: 'POST'});
      setMessage(`Đã nhân bản thành cảnh ${response.shot.shot_index}. Hãy sửa nội dung trước khi dựng.`, 'success');
      await openProjectDetail(projectId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function saveShot(shotId) {
    setMessage(`Đang lưu cảnh ${shotId}...`);
    try {
      await api(`/api/shots/${shotId}`, {
        method: 'PATCH',
        body: JSON.stringify({
          narration: $(`shotNarration-${shotId}`).value,
          visual_prompt: $(`shotPrompt-${shotId}`).value,
          asset_type: $(`shotAsset-${shotId}`).value,
          duration_seconds: Number($(`shotDuration-${shotId}`).value),
          status: $(`shotStatus-${shotId}`).value,
        }),
      });
      setMessage('Đã lưu cảnh.', 'success');
      if (state.projectId) await openProjectDetail(state.projectId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function moveStoryboardShot(projectId, shotId, direction) {
    const current = state.shots || [];
    const index = current.findIndex((shot) => Number(shot.id) === Number(shotId));
    const nextIndex = index + Number(direction);
    if (index < 0 || nextIndex < 0 || nextIndex >= current.length) return;
    const order = current.map((shot) => Number(shot.id));
    [order[index], order[nextIndex]] = [order[nextIndex], order[index]];
    try {
      await api(`/api/projects/${projectId}/shots/reorder`, {method: 'POST', body: JSON.stringify({shot_ids: order})});
      setMessage('Đã đổi thứ tự storyboard.', 'success');
      await openProjectDetail(projectId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function deleteStoryboardShot(projectId, shotId) {
    if (!confirm('Xóa cảnh này khỏi storyboard? Timeline liên quan sẽ cần được rà soát lại.')) return;
    try {
      await api(`/api/shots/${shotId}`, {method: 'DELETE'});
      setMessage('Đã xóa cảnh khỏi storyboard.', 'success');
      await openProjectDetail(projectId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  function sceneProviderLabel(provider) {
    return {
      auto: 'Auto · AI điều phối tự chọn',
      antigravity_image: 'Antigravity', gflow_cli: 'Google Flow/Veo (gflow-cli)', gflow_image: 'Flow ảnh (gflow-cli)', flow_veo: 'Flow Extension (legacy)', meta_ai_video: 'Meta AI (Vibes)',
      gemini_image: 'Gemini Image', gemini_veo: 'Google Veo', openai_image: 'GPT Image', runway: 'Runway',
      phantom_canvas_image: 'Gemini Web (Phantom Canvas)', phantom_canvas_video: 'Gemini Web video (Phantom Canvas)',
      gemini_web_image: 'Gemini (web)', chatgpt_web_image: 'ChatGPT (web)', flow_image: 'Flow (ảnh)', auto_parallel: 'nhiều AI song song',
      motion_graphics: 'Motion graphics', stock_footage: 'Kho footage mở',
    }[provider] || provider || 'AI';
  }


  // Spreading a batch over several sites is what makes it run in parallel —
  // the extension already runs jobs concurrently, but scenes sent to one site
  // queue behind that site's single tab.
  const PARALLEL_IMAGE_PROVIDERS = ['phantom_canvas_image', 'flow_image', 'chatgpt_web_image', 'gemini_web_image'];
  const PARALLEL_VIDEO_PROVIDERS = ['gflow_cli'];
  function batchProviderPayload(provider, isVeo) {
    if (provider !== 'auto_parallel') return {provider};
    return {providers: isVeo ? PARALLEL_VIDEO_PROVIDERS : PARALLEL_IMAGE_PROVIDERS};
  }

  const VIDEO_SCENE_PROVIDERS = new Set(['phantom_canvas_video', 'gemini_veo', 'gflow_cli', 'flow_veo', 'meta_ai_video', 'runway']);
  const IMAGE_EXTENSIONS = new Set(['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp']);
  const AUDIO_SOURCE_EXTENSIONS = new Set(['mp3', 'wav', 'm4a', 'flac', 'ogg', 'aac']);
  // Providers that need no API key, driven instead by the caller's own
  // logged-in web/agent session (browser sidecar or Antigravity's agent).
  const SUBSCRIPTION_SCENE_PROVIDERS = new Set(['phantom_canvas_image', 'phantom_canvas_video', 'antigravity_image', 'gflow_cli', 'gflow_image', 'flow_veo', 'flow_image', 'meta_ai_video', 'meta_ai_image', 'gemini_web_image', 'chatgpt_web_image', 'auto_parallel']);
  // This list is used by single-scene controls. `auto_parallel` belongs only
  // to batch generation; sending it to POST /scene-jobs is an invalid provider.
  const IMAGE_PROVIDER_OPTIONS = '<option value="phantom_canvas_image">Gemini Web · Phantom Canvas (đề xuất)</option><option value="flow_image">Flow trong Cốc Cốc · 0 tín dụng</option><option value="gflow_image">Flow qua gflow-cli · profile riêng</option><option value="antigravity_image">Antigravity · ảnh theo gói</option><option value="meta_ai_image">Meta AI · ảnh (gói đăng ký)</option><option value="gemini_image">Gemini Image (API)</option><option value="openai_image">GPT Image (API)</option><option value="gemini_web_image">Gemini · web (gói đăng ký)</option><option value="chatgpt_web_image">ChatGPT · web (gói đăng ký)</option>';
  const VIDEO_PROVIDER_OPTIONS = '<option value="phantom_canvas_video">Gemini Web video · Phantom Canvas (đề xuất)</option><option value="gflow_cli">Google Flow/Veo · gflow-cli</option><option value="flow_veo">Flow Extension · legacy</option><option value="gemini_veo">Google Veo (API)</option>';

  async function findReferenceImageAssetId(projectId, visualPath) {
    if (!visualPath) return null;
    const extension = visualPath.split('.').pop()?.toLowerCase() || '';
    if (!IMAGE_EXTENSIONS.has(extension)) return null;
    try {
      const bundle = await api(`/api/projects/${projectId}`);
      const match = (bundle.project_assets || []).find((asset) => asset.asset_type === 'image' && asset.file_path === visualPath);
      return match ? match.id : null;
    } catch { return null; }
  }

  async function ensureSegmentForShot(projectId, shotId) {
    // force:false is a safe no-op if a timeline already exists — this only
    // creates one the first time a shot-level action is used before the
    // user has explicitly generated a timeline themselves.
    await api(`/api/projects/${projectId}/timeline/generate`, {method: 'POST', body: JSON.stringify({force: false})});
    const timeline = await api(`/api/projects/${projectId}/timeline`);
    const segment = timeline.find((item) => Number(item.shot_id) === Number(shotId));
    if (!segment) throw new Error('Không tạo được đoạn timeline tương ứng cho cảnh này.');
    return segment;
  }

  async function uploadShotImage(projectId, shotId, inputEl) {
    const file = inputEl?.files?.[0];
    if (!file) return;
    setMessage(`Đang tải ${file.name} lên...`);
    try {
      const segment = await ensureSegmentForShot(projectId, shotId);
      const form = new FormData();
      form.append('asset_type', file.type.startsWith('video') ? 'video' : 'image');
      form.append('file', file);
      const response = await fetch(`/api/projects/${projectId}/assets/upload`, {method: 'POST', body: form});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw apiError(data, response);
      await api(`/api/timeline/${segment.id}/attach-asset`, {method: 'POST', body: JSON.stringify({asset_id: data.asset.id})});
      setMessage('Đã gắn ảnh/video vào cảnh.', 'success');
      await openProjectDetail(projectId);
    } catch (error) { setMessage(error.message, 'error'); }
    finally { if (inputEl) inputEl.value = ''; }
  }

  async function deleteShotImage(projectId, segmentId) {
    if (!segmentId || !confirm('Xóa ảnh/video khỏi cảnh này?')) return;
    try {
      await api(`/api/timeline/${segmentId}`, {method: 'PATCH', body: JSON.stringify({visual_path: ''})});
      setMessage('Đã xóa ảnh/video khỏi cảnh.', 'success');
      await openProjectDetail(projectId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function createSceneJob(projectId, shotId, promptText, provider, ratio) {
    if (promptText.length < 3) throw new Error('Hãy nhập mô tả hình ảnh/prompt cho cảnh này trước.');
    const isVeo = VIDEO_SCENE_PROVIDERS.has(provider);
    const usesSubscription = SUBSCRIPTION_SCENE_PROVIDERS.has(provider);
    const segment = await ensureSegmentForShot(projectId, shotId);
    const referenceAssetId = isVeo ? await findReferenceImageAssetId(projectId, segment.visual_path) : null;
    if (isVeo && !referenceAssetId) {
      setMessage('Cảnh chưa có ảnh nguồn. Hãy tạo hoặc gắn ảnh cho cảnh trước khi tạo video.', 'error');
      return null;
    }
    const fromImageNote = referenceAssetId ? ' Cảnh đã có ảnh — sẽ tạo video từ ảnh đó (image-to-video).' : '';
    const sidecarWarning = await sidecarWarningText(provider);
    if (!confirm(`Tạo ${isVeo ? 'video' : 'ảnh'} AI bằng ${sceneProviderLabel(provider)} cho cảnh này?${fromImageNote} ${usesSubscription ? 'Dùng gói đã đăng nhập.' : 'Việc này dùng API cloud và có thể phát sinh chi phí.'}${sidecarWarning ? `\n\n${sidecarWarning}` : ''}`)) return null;
    setMessage(`Đang đưa cảnh vào hàng đợi ${sceneProviderLabel(provider)}...`);
    const response = await api(`/api/projects/${projectId}/scene-jobs`, {
      method: 'POST',
      body: JSON.stringify({
        timeline_segment_id: segment.id, provider, prompt: promptText,
        duration_seconds: isVeo ? 8 : 5, ratio, confirmed: true,
        reference_asset_id: referenceAssetId,
        requires_reference_image: isVeo,
      }),
    });
    setMessage('Đã đưa tác vụ tạo cảnh vào hàng đợi. Kết quả sẽ tự gắn vào cảnh.', 'success');
    return response;
  }

  async function generateShotImage(projectId, shotId) {
    const promptText = $(`shotPrompt-${shotId}`)?.value?.trim() || '';
    const provider = $(`shotImageProvider-${shotId}`)?.value || 'gemini_image';
    const ratio = $(`shotSceneRatio-${shotId}`)?.value || '1280:720';
    try {
      const response = await createSceneJob(projectId, shotId, promptText, provider, ratio);
      if (!response) return;
      await openProjectDetail(projectId);
      if (response.job?.id) void watchSceneGenerationJob(projectId, response.job.id);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function generateShotVideo(projectId, shotId) {
    const promptText = $(`shotPrompt-${shotId}`)?.value?.trim() || '';
    const provider = $(`shotVideoProvider-${shotId}`)?.value || 'gflow_cli';
    const ratio = $(`shotSceneRatio-${shotId}`)?.value || '1280:720';
    try {
      const response = await createSceneJob(projectId, shotId, promptText, provider, ratio);
      if (!response) return;
      await openProjectDetail(projectId);
      if (response.job?.id) void watchSceneGenerationJob(projectId, response.job.id);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function generateStudioShotImage(shotId) {
    const projectId = state.studioProjectId;
    if (!projectId) return;
    const shot = findStudioShot(shotId);
    const promptText = (shot?.visual_prompt || '').trim();
    const provider = $(`studioShotImageProvider-${shotId}`)?.value || 'gemini_image';
    const ratio = $(`studioShotSceneRatio-${shotId}`)?.value || '1280:720';
    try {
      const response = await createSceneJob(projectId, shotId, promptText, provider, ratio);
      if (!response) return;
      const bundle = await api(`/api/projects/${projectId}`);
      state.shots = bundle.latest_shots || [];
      renderStudioStoryboard(state.shots, bundle.latest_timeline || []);
      if (response.job?.id) void watchStudioShotSceneJob(response.job.id);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function generateStudioShotVideo(shotId) {
    const projectId = state.studioProjectId;
    if (!projectId) return;
    const shot = findStudioShot(shotId);
    const promptText = (shot?.visual_prompt || '').trim();
    const provider = $(`studioShotVideoProvider-${shotId}`)?.value || 'gflow_cli';
    const ratio = $(`studioShotSceneRatio-${shotId}`)?.value || '1280:720';
    try {
      const response = await createSceneJob(projectId, shotId, promptText, provider, ratio);
      if (!response) return;
      const bundle = await api(`/api/projects/${projectId}`);
      state.shots = bundle.latest_shots || [];
      renderStudioStoryboard(state.shots, bundle.latest_timeline || []);
      if (response.job?.id) void watchStudioShotSceneJob(response.job.id);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function watchStudioShotSceneJob(jobId) {
    const projectId = state.studioProjectId;
    for (let attempt = 0; attempt < 300; attempt += 1) {
      try {
        const job = await api(`/api/scene-jobs/${jobId}`);
        if (job.status === 'completed' || job.status === 'error') {
          const bundle = await api(`/api/projects/${projectId}`);
          state.shots = bundle.latest_shots || [];
          renderStudioStoryboard(state.shots, bundle.latest_timeline || []);
          setMessage(
            job.status === 'completed' ? `Cảnh AI cho đoạn ${job.segment_index} đã tạo xong.` : `Tạo cảnh AI thất bại: ${job.error || 'Lỗi không xác định.'}`,
            job.status === 'completed' ? 'success' : 'error',
          );
          return job;
        }
      } catch (error) { setMessage(`Không đọc được trạng thái tạo cảnh: ${error.message}`, 'error'); return null; }
      await new Promise((resolve) => setTimeout(resolve, 5000));
    }
    setMessage('Tạo cảnh đang chạy lâu; hãy làm mới trang để kiểm tra trạng thái.', 'error');
    return null;
  }

  async function createVoiceJob(projectId, shotId) {
    if (!confirm('Tạo lại giọng đọc riêng cho cảnh này? Sẽ ghi đè audio hiện có của cảnh (nếu có).')) return false;
    setMessage('Đang tạo lại giọng đọc cho cảnh này...');
    const segment = await ensureSegmentForShot(projectId, shotId);
    const renderSettings = await api(`/api/projects/${projectId}/render-settings`);
    const provider = renderSettings?.voice_provider || 'edge_tts';
    await api(`/api/projects/${projectId}/jobs`, {
      method: 'POST',
      body: JSON.stringify({job_type: 'voiceover_segment', provider, confirmed: true, segment_id: segment.id}),
    });
    setMessage('Đã đưa việc tạo giọng đọc cho cảnh này vào hàng đợi.', 'success');
    return true;
  }

  async function regenerateShotVoice(projectId, shotId) {
    try {
      const done = await createVoiceJob(projectId, shotId);
      if (!done) return;
      await openProjectDetail(projectId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function regenerateStudioShotVoice(shotId) {
    const projectId = state.studioProjectId;
    if (!projectId) return;
    try {
      const done = await createVoiceJob(projectId, shotId);
      if (!done) return;
      const bundle = await api(`/api/projects/${projectId}`);
      state.shots = bundle.latest_shots || [];
      renderStudioStoryboard(state.shots, bundle.latest_timeline || []);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function generateTimeline(projectId, force = false) {
    setMessage(force ? 'Đang tạo lại timeline...' : 'Đang tạo timeline...');
    try {
      const response = await api(`/api/projects/${projectId}/timeline/generate`, {
        method: 'POST',
        body: JSON.stringify({force}),
      });
      setMessage(`Đã tạo ${response.timeline.length} đoạn timeline (${response.total_duration_seconds} giây).`, 'success');
      await openProjectDetail(projectId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function regenerateTimeline(projectId) {
    if (!confirm('Tạo lại timeline sẽ thay thế các segment hiện tại của kịch bản mới nhất. Tiếp tục?')) return;
    await generateTimeline(projectId, true);
  }

  async function saveTimelineSegment(segmentId) {
    setMessage(`Đang lưu segment ${segmentId}...`);
    try {
      await api(`/api/timeline/${segmentId}`, {
        method: 'PATCH',
        body: JSON.stringify({
          voice_text: $(`timelineVoice-${segmentId}`).value,
          subtitle_text: $(`timelineVoice-${segmentId}`).value,
          visual_prompt: $(`timelinePrompt-${segmentId}`).value,
          duration_seconds: Number($(`timelineDuration-${segmentId}`).value),
          audio_path: $(`timelineAudio-${segmentId}`).value,
          visual_path: $(`timelineVisual-${segmentId}`).value,
          status: $(`timelineStatus-${segmentId}`).value,
        }),
      });
      setMessage('Đã lưu segment timeline.', 'success');
      if (state.projectId) await openProjectDetail(state.projectId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  // `quiet` is for saves the user did not ask for by name - persisting a
  // dropdown the moment it changes. The save still has to happen, but
  // announcing it twice per click buries the messages that matter.
  async function saveRenderSettings(projectId, {quiet = false} = {}) {
    if (!quiet) setMessage('Đang lưu thiết lập render...');
    try {
      const current = await api(`/api/projects/${projectId}/render-settings`);
      const usingStudio = localStorage.getItem('ytFactory.workspace') === 'dashboard' && Boolean($('studioVoiceProviderSelect'));
      const selected = (renderId, studioId, fallback = '') => {
        const element = $(usingStudio ? studioId : renderId);
        return element ? element.value : fallback;
      };
      const response = await api(`/api/projects/${projectId}/render-settings`, {
        method: 'PATCH',
        body: JSON.stringify({
          music_asset_id: $('renderMusicAsset')?.value ? Number($('renderMusicAsset').value) : (current.music_asset_id || null),
          music_volume: Number($('renderMusicVolume')?.value || current.music_volume || 0.12),
          transition_style: $('renderTransitionStyle')?.value || current.transition_style || 'fade',
          output_profile: selected('renderOutputProfile', 'studioOutputProfileSelect', current.output_profile || 'youtube_landscape'),
          voice_provider: selected('renderVoiceProvider', 'studioVoiceProviderSelect', current.voice_provider || 'edge_tts'),
          voice_model: selected('renderVoiceModel', 'studioVoiceModelSelect', current.voice_model || 'vi-VN-HoaiMyNeural'),
          voice_rate: selected('renderVoiceRate', 'studioVoiceRateSelect', current.voice_rate || '+0%'),
          // The hidden field holding the chosen sample is filled in by
          // hydrateStudioVoiceSettings, which only runs once step 4 is open.
          // Saving before that read an empty field as "no sample" and wiped
          // the project's voice - so VoxCPM went back to inventing a new
          // speaker per scene. An empty field with no options in it means
          // "not loaded yet", not "cleared"; only a blank pick from a
          // populated list clears the sample.
          voice_reference_asset_id: (() => {
            const element = $(usingStudio ? 'studioVoiceReferenceAsset' : 'renderVoiceReferenceAsset');
            const stored = current.voice_reference_asset_id || null;
            if (!element) return stored;
            if (element.value) return Number(element.value);
            return element.options && element.options.length > 1 ? null : stored;
          })(),
          voice_prompt_text: selected('renderVoicePromptText', 'studioVoicePromptText', current.voice_prompt_text || ''),
          subtitle_provider: selected('renderSubtitleProvider', 'studioSubtitleProviderSelect', current.subtitle_provider || 'timeline_text'),
          subtitle_model: selected('renderSubtitleModel', 'studioSubtitleModelSelect', current.subtitle_model || 'timeline'),
          publish_language: selected('renderPublishLanguage', 'studioPublishLanguageSelect', current.publish_language || 'vi'),
        }),
      });
      if (!quiet) setMessage('Đã lưu thiết lập nhạc nền và chuyển cảnh.', 'success');
      if (response.settings && state.projectId && Number(state.projectId) === Number(projectId)) await openProjectDetail(state.projectId);
    } catch (error) { setMessage(`Không lưu được thiết lập render: ${error.message}`, 'error'); }
  }

  async function createTimelineSceneJob(projectId, segmentId, promptText, provider, ratio, isVeo) {
    if (promptText.length < 3) throw new Error('Hãy nhập visual prompt cho đoạn này trước.');
    const referenceAssetId = isVeo ? await findReferenceImageAssetId(projectId, $(`timelineVisual-${segmentId}`)?.value || '') : null;
    if (isVeo && !referenceAssetId) {
      setMessage('Đoạn này chưa có ảnh nguồn. Hãy tạo hoặc gắn ảnh trước khi tạo video.', 'error');
      return null;
    }
    const fromImageNote = referenceAssetId ? ' Cảnh đã có ảnh — sẽ tạo video từ ảnh đó (image-to-video).' : '';
    const sidecarWarning = await sidecarWarningText(provider);
    if (!confirm(`Tạo ${isVeo ? 'video' : 'ảnh'} AI bằng ${sceneProviderLabel(provider)} từ prompt.${fromImageNote} ${SUBSCRIPTION_SCENE_PROVIDERS.has(provider) ? 'Dùng gói đã đăng nhập.' : 'Việc này dùng API cloud và có thể phát sinh chi phí.'} Tiếp tục?${sidecarWarning ? `\n\n${sidecarWarning}` : ''}`)) return null;
    setMessage(`Đang đưa cảnh ${segmentId} vào hàng đợi ${sceneProviderLabel(provider)}...`);
    const response = await api(`/api/projects/${projectId}/scene-jobs`, {
      method: 'POST',
      body: JSON.stringify({
        timeline_segment_id: segmentId,
        provider,
        prompt: promptText,
        duration_seconds: isVeo ? 8 : 5,
        ratio,
        reference_asset_id: referenceAssetId,
        requires_reference_image: isVeo,
        confirmed: true,
      }),
    });
    setMessage('Đã đưa tác vụ tạo cảnh vào hàng đợi. Kết quả sẽ tự gắn vào timeline.', 'success');
    return response;
  }

  async function generateSceneImage(projectId, segmentId) {
    const prompt = $(`timelinePrompt-${segmentId}`)?.value?.trim() || '';
    const provider = $(`sceneImageProvider-${segmentId}`)?.value || 'gemini_image';
    const ratio = $(`sceneRatio-${segmentId}`)?.value || '1280:720';
    try {
      const response = await createTimelineSceneJob(projectId, segmentId, prompt, provider, ratio, false);
      if (!response) return;
      await openProjectDetail(projectId);
      if (response.job?.id) void watchSceneGenerationJob(projectId, response.job.id);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function generateSceneVideo(projectId, segmentId) {
    const prompt = $(`timelinePrompt-${segmentId}`)?.value?.trim() || '';
    const provider = $(`sceneVideoProvider-${segmentId}`)?.value || 'gflow_cli';
    const ratio = $(`sceneRatio-${segmentId}`)?.value || '1280:720';
    try {
      const response = await createTimelineSceneJob(projectId, segmentId, prompt, provider, ratio, true);
      if (!response) return;
      await openProjectDetail(projectId);
      if (response.job?.id) void watchSceneGenerationJob(projectId, response.job.id);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function cancelSceneJob(projectId, jobId) {
    try {
      await api(`/api/scene-jobs/${jobId}/cancel`, {method: 'POST'});
      setMessage('Đã hủy job tạo cảnh.', 'success');
      await openProjectDetail(projectId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function retrySceneJob(projectId, jobId) {
    try {
      const response = await api(`/api/scene-jobs/${jobId}/retry`, {method: 'POST'});
      setMessage('Đã đưa job vào hàng đợi lại.', 'success');
      await openProjectDetail(projectId);
      if (response.job?.id) void watchSceneGenerationJob(projectId, response.job.id);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function runTimelineSceneBatch(projectId, provider, ratio, isVeo) {
    const sidecarWarning = await sidecarWarningText(provider);
    if (!confirm(`${isVeo ? 'Tạo video từ ảnh storyboard' : 'Tạo ảnh AI'} bằng ${sceneProviderLabel(provider)} cho toàn bộ cảnh? ${isVeo ? 'Cảnh chưa có ảnh sẽ được tạo ảnh trước; video không chuyển ngầm sang text-to-video. ' : ''}Mỗi cảnh sẽ dùng API credits/gói đã đăng nhập.${sidecarWarning ? `\n\n${sidecarWarning}` : ''}`)) return;
    setMessage(`Đang đưa các cảnh vào hàng đợi ${sceneProviderLabel(provider)}...`);
    try {
      const referenceImageProvider = $(`batchImageProvider-${projectId}`)?.value || 'flow_image';
      const response = await api(`/api/projects/${projectId}/scene-jobs/batch`, {
        method: 'POST', body: JSON.stringify({
          ...batchProviderPayload(provider, isVeo), duration_seconds: isVeo ? 8 : 5, ratio,
          requires_reference_image: isVeo, reference_image_provider: referenceImageProvider, confirmed: true,
        }),
      });
      const jobs = response.jobs || [];
      if (!jobs.length) return setMessage('Không có cảnh nào cần tạo thêm; hãy kiểm tra storyboard.', 'success');
      setMessage(`Đã đưa ${jobs.length}/${response.total_segments || jobs.length} cảnh sang ${sceneProviderLabel(provider)}. Kết quả hoàn tất sẽ tự hiện trong storyboard.`, 'success');
      await openProjectDetail(projectId, 'editor');
      jobs.forEach((job) => { if (job.id) void watchSceneGenerationJob(projectId, job.id); });
    } catch (error) { setMessage(`Không thể tạo hàng loạt cảnh AI: ${error.message}`, 'error'); }
  }

  async function generateAllSceneImages(projectId) {
    const provider = $(`batchImageProvider-${projectId}`)?.value || 'gemini_image';
    const ratio = $(`batchSceneRatio-${projectId}`)?.value || '1280:720';
    await runTimelineSceneBatch(projectId, provider, ratio, false);
  }

  async function generateAllSceneVideos(projectId) {
    const provider = $(`batchVideoProvider-${projectId}`)?.value || 'gflow_cli';
    const ratio = $(`batchSceneRatio-${projectId}`)?.value || '1280:720';
    await runTimelineSceneBatch(projectId, provider, ratio, true);
  }

  async function watchSceneGenerationJob(projectId, jobId) {
    for (let attempt = 0; attempt < 300; attempt += 1) {
      try {
        const job = await api(`/api/scene-jobs/${jobId}`);
        if (job.status === 'completed') {
          setMessage(`Cảnh AI cho đoạn ${job.segment_index} đã tạo xong và được gắn vào timeline.`, 'success');
          await openProjectDetail(projectId);
          return job;
        }
        if (job.status === 'error') {
          setMessage(`Tạo cảnh AI thất bại: ${job.error || 'Lỗi không xác định.'}`, 'error');
          await openProjectDetail(projectId);
          return job;
        }
        if (attempt % 3 === 0) setMessage(`${sceneProviderLabel(job.provider)} đang tạo cảnh... (${job.status})`);
      } catch (error) {
        setMessage(`Không đọc được trạng thái tạo cảnh: ${error.message}`, 'error');
        return null;
      }
      await new Promise((resolve) => setTimeout(resolve, 5000));
    }
    setMessage('Tạo cảnh đang chạy lâu; hãy mở lại project để kiểm tra trạng thái.', 'error');
    return null;
  }

  async function uploadProjectAsset(projectId) {
    const fileInput = $('assetUploadFile');
    const file = fileInput?.files?.[0];
    if (!file) { setMessage('Hãy chọn một file video, audio hoặc ảnh trước.', 'error'); return; }
    setMessage(`Đang upload ${file.name}...`);
    try {
      const form = new FormData();
      form.append('asset_type', $('assetUploadType').value);
      form.append('file', file);
      const response = await fetch(`/api/projects/${projectId}/assets/upload`, {method: 'POST', body: form});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw apiError(data, response);
      setMessage(`Đã import ${data.asset.original_name} vào project.`, 'success');
      await openProjectDetail(projectId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function uploadVoiceReferenceAudio(projectId) {
    const fileInput = $('renderVoiceReferenceFile');
    const file = fileInput?.files?.[0];
    if (!file) { setMessage('Hãy chọn file audio giọng mẫu trước.', 'error'); return; }
    setMessage(`Đang upload giọng mẫu ${file.name}...`);
    try {
      const form = new FormData();
      form.append('asset_type', 'audio');
      form.append('file', file);
      const response = await fetch(`/api/projects/${projectId}/assets/upload`, {method: 'POST', body: form});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw apiError(data, response);
      await openProjectDetail(projectId);
      if ($('renderVoiceReferenceAsset')) $('renderVoiceReferenceAsset').value = String(data.asset.id);
      await saveRenderSettings(projectId);
      setMessage(`Đã chọn ${data.asset.original_name} làm giọng mẫu VoxCPM2.`, 'success');
    } catch (error) { setMessage(`Không upload được giọng mẫu: ${error.message}`, 'error'); }
  }

  async function uploadStudioVoiceReferenceAudio() {
    const projectId = state.studioProjectId;
    const file = $('studioVoiceReferenceFile')?.files?.[0];
    if (!projectId) { setMessage('Hãy tạo project và kịch bản trước.', 'error'); return; }
    if (!file) { setMessage('Hãy chọn file audio giọng mẫu trước.', 'error'); return; }
    setStudioProgress(15, `Đang tải giọng mẫu ${file.name}...`);
    try {
      const form = new FormData();
      form.append('asset_type', 'audio');
      form.append('file', file);
      const response = await fetch(`/api/projects/${projectId}/assets/upload`, {method: 'POST', body: form});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw apiError(data, response);
      const voiceName = $('studioVoiceReferenceName')?.value.trim() || '';
      if (voiceName) {
        await api(`/api/assets/${data.asset.id}`, {method: 'PATCH', body: JSON.stringify({original_name: voiceName})});
      }
      await hydrateStudioVoiceSettings();
      if ($('studioVoiceReferenceAsset')) $('studioVoiceReferenceAsset').value = String(data.asset.id);
      await saveRenderSettings(projectId);
      setStudioProgress(100, `Đã khóa giọng mẫu: ${data.asset.original_name}.`);
      setMessage('Đã chọn giọng mẫu. VoxCPM sẽ dùng đúng file này cho mọi cảnh.', 'success');
    } catch (error) {
      setStudioProgress(0, `Không tải được giọng mẫu: ${error.message}`, 'error');
      setMessage(`Không tải được giọng mẫu: ${error.message}`, 'error');
    }
  }

  async function analyzeLocalAsset(assetId) {
    if (!confirm('Whisper local sẽ đọc file audio/video này bằng CPU/GPU và lưu transcript vào project. Tiếp tục?')) return;
    setMessage(`Đang phân tích asset ${assetId} bằng Whisper local...`);
    try {
      await api(`/api/assets/${assetId}/analyze`, {
        method: 'POST',
        body: JSON.stringify({confirmed: true, language: ''}),
      });
      setMessage('Đã phân tích asset và lưu transcript.', 'success');
      if (state.projectId) await openProjectDetail(state.projectId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function attachTimelineAsset(segmentId, assetId) {
    if (!assetId) return;
    setMessage(`Đang gắn asset ${assetId} vào segment ${segmentId}...`);
    try {
      await api(`/api/timeline/${segmentId}/attach-asset`, {
        method: 'POST',
        body: JSON.stringify({asset_id: Number(assetId)}),
      });
      setMessage('Đã gắn asset vào timeline.', 'success');
      if (state.projectId) await openProjectDetail(state.projectId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function downloadProjectSource(projectId, videoId) {
    if (!confirm('Tự động tải video nguồn về máy để cắt các đoạn minh hoạ? App không dùng cookie hay tài khoản YouTube.')) return;
    setMessage('Đang tải video nguồn về máy; thời gian phụ thuộc độ dài video và kết nối.');
    try {
      const result = await api(`/api/videos/${encodeURIComponent(videoId)}/download?media_type=video&confirmed=true`, {method: 'POST'});
      setMessage(`Đã tải video nguồn: ${result.path}`, 'success');
      await refresh();
      await openProjectDetail(projectId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function downloadProjectSourceWithCookieFile(projectId, videoId, cookieFile) {
    if (!cookieFile) return;
    if (!confirm('Dùng cookies.txt này cho đúng một lần tải video nguồn? File chỉ được dùng trong thư mục tạm và bị xoá ngay sau khi tải.')) return;
    setMessage('Đang tải video nguồn bằng cookies.txt tạm thời...');
    try {
      const form = new FormData();
      form.append('cookie_file', cookieFile);
      const response = await fetch(`/api/videos/${encodeURIComponent(videoId)}/download-with-cookie-file?media_type=video&confirmed=true`, {
        method: 'POST', body: form,
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.detail || `HTTP ${response.status}`);
      setMessage(`Đã tải video nguồn: ${result.path}`, 'success');
      await refresh();
      await openProjectDetail(projectId);
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function queueOpenMontage(projectId) {
    const provider = $('openMontageRuntime')?.value || 'openmontage';
    return queueProductionJob(projectId, 'render', provider, true);
  }

  function renderPublicationSuggestions(projectId) {
    const titleInput = $('publicationTitle');
    const anchor = titleInput?.closest('.studio-grid');
    if (!anchor || $('publicationSuggestions')) return;
    const suggestion = state.publicationSuggestions || {};
    const titles = Array.isArray(suggestion.titles) ? suggestion.titles : [];
    const titleChoices = titles.length
      ? titles.map((title, index) => `<button class="btn small ${index === 0 ? 'primary' : 'ghost'}" type="button" data-value="${esc(title)}" onclick="applyPublicationTitleSuggestion(this)">${esc(title)}</button>`).join('')
      : '<span class="secondary-text">Chưa có gợi ý tiêu đề. Hãy tạo AI Writer từ bước kịch bản.</span>';
    const metadataButton = suggestion.description || (suggestion.tags || []).length
      ? `<button class="btn small ghost" type="button" data-description="${esc(suggestion.description || '')}" data-tags="${esc((suggestion.tags || []).join(', '))}" onclick="applyPublicationMetadataSuggestion(this)">Áp dụng mô tả &amp; hashtag AI</button>`
      : '';
    const thumbnailAction = suggestion.thumbnailBrief
      ? `<div class="secondary-text" style="margin-top:6px">${esc(suggestion.thumbnailBrief)}</div><div class="queue-controls" style="justify-content:flex-start;margin-top:7px"><button class="btn small ghost" type="button" data-brief="${esc(suggestion.thumbnailBrief)}" onclick="applyPublicationThumbnailBrief(this)">Dùng brief cho thumbnail</button><button class="btn small primary" type="button" data-brief="${esc(suggestion.thumbnailBrief)}" onclick="generatePublicationThumbnailFrames(${Number(projectId)}, this)">Tạo 3 phương án frame</button></div>`
      : '<div class="secondary-text" style="margin-top:6px">Chưa có brief thumbnail. Tạo AI Writer để nhận đề xuất theo nội dung video.</div>';
    anchor.insertAdjacentHTML('afterend', `<div id="publicationSuggestions" class="analysis-item" style="margin-top:8px;border-color:rgba(168,85,247,.42)"><label>ĐỀ XUẤT AI TRƯỚC KHI XUẤT BẢN</label><p class="panel-sub">Chọn một tiêu đề, áp dụng caption/hashtag và chuẩn bị brief thumbnail. Bạn vẫn có thể chỉnh lại mọi nội dung trước khi đăng.</p><div class="queue-controls" style="justify-content:flex-start;flex-wrap:wrap">${titleChoices}<button class="btn small ghost" type="button" onclick="generatePublicationAiSuggestions(${Number(projectId)})">Tạo / làm mới đề xuất AI</button></div><div class="queue-controls" style="justify-content:flex-start;margin-top:7px">${metadataButton}</div><div style="margin-top:8px"><b style="font-size:12px">Đề xuất thumbnail</b>${thumbnailAction}</div></div>`);
  }

  function applyPublicationTitleSuggestion(button) {
    const title = String(button?.dataset?.value || '');
    const input = $('publicationTitle');
    if (input && title) input.value = title;
  }

  function applyPublicationMetadataSuggestion(button) {
    const description = String(button?.dataset?.description || '');
    const tags = String(button?.dataset?.tags || '');
    if ($('publicationDescription') && description) $('publicationDescription').value = description;
    if ($('publicationTags') && tags) $('publicationTags').value = tags;
    setMessage('Đã áp dụng mô tả và hashtag do AI đề xuất.', 'success');
  }

  function applyPublicationThumbnailBrief(button) {
    const brief = String(button?.dataset?.brief || '');
    if ($('thumbnailPrompt') && brief) $('thumbnailPrompt').value = brief;
    setMessage('Đã đưa brief vào phần Thumbnail. Bạn có thể tạo phương án frame hoặc chỉnh brief trước.', 'success');
  }

  async function generatePublicationAiSuggestions(projectId) {
    const videoId = String(state.publicationSuggestions?.sourceVideoId || '');
    if (!videoId) return setMessage('Không tìm được video nguồn để tạo đề xuất.', 'error');
    const selected = $('analysisProviderSelect')?.value || '';
    const provider = ['anthropic_claude', 'openai_gpt', 'codex_cli', 'claude_code_cli', 'antigravity'].includes(selected) ? selected : null;
    setMessage('AI đang tạo đề xuất tiêu đề, caption, hashtag và brief thumbnail...');
    try {
      await api(`/api/videos/${encodeURIComponent(videoId)}/writer`, {method: 'POST', body: JSON.stringify({provider})});
      await refresh();
      await openProjectDetail(projectId, 'export');
      setMessage('Đã cập nhật đề xuất xuất bản bằng AI.', 'success');
    } catch (error) { setMessage(`Không tạo được đề xuất AI: ${error.message}`, 'error'); }
  }

  async function generatePublicationThumbnailFrames(projectId, button) {
    applyPublicationThumbnailBrief(button);
    await generateProjectThumbnails(projectId);
  }

  const PUBLICATION_PLATFORM_DEFAULTS = {
    youtube: {profile: 'youtube_landscape', note: 'YouTube: upload tự động khi OAuth đã kết nối.'},
    tiktok: {profile: 'tiktok', note: 'TikTok: app chuẩn bị MP4 và metadata để bạn đăng thủ công.'},
    facebook: {profile: 'facebook_reels', note: 'Facebook: app chuẩn bị MP4 và metadata để bạn đăng thủ công.'},
    instagram: {profile: 'instagram_reels', note: 'Instagram: app chuẩn bị MP4 và metadata để bạn đăng thủ công.'},
  };

  function syncPublicationTarget() {
    const platformSelect = $('publicationPlatform');
    let platform = platformSelect?.value || 'youtube';
    const channelId = Number($('publicationChannel')?.value || 0);
    const variant = $('publicationVariant')?.value || 'long';
    const channel = state.managedChannels.find((item) => Number(item.id) === channelId);
    const profile = $('publicationProfile');
    const note = $('publicationTargetNote');
    if (channel?.platform && channel.platform !== platform) {
      platform = channel.platform;
      if (platformSelect) platformSelect.value = platform;
    }
    const defaults = PUBLICATION_PLATFORM_DEFAULTS[platform] || PUBLICATION_PLATFORM_DEFAULTS.youtube;
    if (profile) profile.value = channel?.output_profile || (variant === 'short' && platform === 'youtube' ? 'youtube_shorts' : defaults.profile);
    if (note) note.textContent = channel ? `${esc(channel.name)} · ${defaults.note}` : defaults.note;
  }

  const PUBLISHER_PLATFORM_LABELS = {
    tiktok: 'TikTok', facebook: 'Facebook', instagram: 'Instagram',
  };

  // Only YouTube has an uploader. Rows for the other platforms sit as a
  // ready-to-post package, which looks like a stuck queue unless it is named.
  function publisherWaitingNote(publications) {
    const waiting = {};
    (publications || []).forEach((item) => {
      if (item.status !== 'ready_manual') return;
      const key = String(item.platform || '').toLowerCase();
      if (!key || key === 'youtube') return;
      waiting[key] = (waiting[key] || 0) + 1;
    });
    const parts = Object.entries(waiting)
      .map(([key, count]) => `${PUBLISHER_PLATFORM_LABELS[key] || key}: ${count}`);
    if (!parts.length) return 'Chỉ YouTube được đăng tự động; các nền tảng khác sẽ tạo gói để bạn tải lên tay.';
    return `Chờ đăng thủ công — ${parts.join(' · ')}. App chưa nối API các nền tảng này, `
      + 'nên chúng không bị đưa nhầm lên YouTube; bấm “Tải gói đăng” rồi đăng tay.';
  }

  // The publish controls existed but were built into a variable that was
  // never inserted anywhere, so the app had no upload button at all: the last
  // wizard step only offered a link across to the channel list, which has no
  // upload button either. They belong on the step that says "Xuất bản".
  const PUBLISH_PROFILE_LABELS = {
    youtube_landscape: 'YouTube ngang · 16:9',
    youtube_shorts: 'YouTube Shorts · 9:16',
    instagram_reels: 'Instagram Reels · 9:16',
    tiktok: 'TikTok · 9:16',
    facebook_reels: 'Facebook Reels · 9:16',
    facebook_feed: 'Facebook feed · 1:1',
  };

  async function cutShortSourceScenes() {
    // The same control is intentionally workflow-aware: Reup cuts the local
    // source; Content queues vertical AI visuals on the Short's own timeline.
    await queueShortVariantJob('source_visuals');
    await loadShortLane();
  }
