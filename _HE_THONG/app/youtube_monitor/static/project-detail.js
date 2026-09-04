// project-detail.js - the project screen and its panels
//
// Part of one page split into ordered files. These are classic
// scripts sharing a single global scope and running in document
// order, so this is a move rather than a rewrite: the files
// concatenated in order are byte for byte the block they came from,
// which is what the test asserts.
  async function restoreSavedProjectDetail(saved = savedStudioSession()) {
    if (!saved || saved.workspace !== 'production' || !saved.detailProjectId) return;
    if (!state.projects.some((item) => Number(item.id) === Number(saved.detailProjectId))) return;
    await openProjectDetail(saved.detailProjectId, saved.projectView || 'overview');
  }

  // Bước 1 vốn chỉ nhận video mà app đã tìm thấy trên YouTube, nên không có
  // đường nào để làm việc với tư liệu người dùng đã có sẵn trên máy.

  function setUploadStatus(text, type = '') {
    const target = $('studioUploadStatus');
    if (target) {
      target.textContent = text;
      target.style.color = type === 'error' ? '#c0392b' : '';
    }
    setMessage(text, type);
  }

  async function uploadStudioSourceFile(file) {
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    setUploadStatus(`Đang tải "${file.name}" lên (${(file.size / 1048576).toFixed(1)} MB)...`);
    try {
      // FormData đặt Content-Type kèm boundary; helper api() ép JSON nên không dùng được.
      const response = await fetch('/api/uploads/source', {method: 'POST', body: form});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      const video = data.video || {};
      await loadVideos();
      state.studioSourceChannelId = video.youtube_channel_id || '';
      populateStudioSourceChannelSelect();
      if ($('studioSourceChannelSelect')) $('studioSourceChannelSelect').value = state.studioSourceChannelId;
      populateStudioVideoSelect();
      if ($('studioVideoSelect')) $('studioVideoSelect').value = video.youtube_video_id;
      state.studioVideoId = video.youtube_video_id;
      await selectStudioVideo();
      const minutes = Math.round((data.duration_seconds || 0) / 60);
      if (data.media_kind === 'audio' && state.studioWorkflow === 'reup') {
        setStudioWorkflow('content', false);
      }
      setUploadStatus(`Đã nhận "${file.name}"${minutes ? ` · khoảng ${minutes} phút` : ''}. Bấm “1. Phân tích tham chiếu” để AI đọc nội dung.`, 'success');
      if (data.media_kind === 'audio') {
        setUploadStatus(`Đã nạp audio "${file.name}". App sẽ dùng nội dung để phân tích/kịch bản; phần hình sẽ được tạo theo storyboard, không cắt từ audio.`, 'success');
      }
    } catch (error) {
      setUploadStatus(`Tải lên thất bại: ${error.message}`, 'error');
    }
  }

  async function uploadStudioReferenceImages(fileList) {
    const files = Array.from(fileList || []).filter((file) =>
      IMAGE_EXTENSIONS.has(file.name.split('.').pop()?.toLowerCase() || ''));
    if (!files.length) return setUploadStatus('Không tìm thấy ảnh nào trong lựa chọn.', 'error');
    if (!state.studioProjectId) {
      if (!state.studioVideoId) {
        return setUploadStatus('Hãy chọn hoặc tải video nguồn trước, rồi mới tải ảnh tham khảo.', 'error');
      }
      try {
        const created = await api(`/api/videos/${encodeURIComponent(state.studioVideoId)}/project`, {
          method: 'POST', body: JSON.stringify({managed_channel_id: null}),
        });
        state.studioProjectId = created.project?.id || created.id || null;
      } catch (error) { return setUploadStatus(`Không tạo được dự án để chứa ảnh: ${error.message}`, 'error'); }
    }
    let done = 0;
    const failed = [];
    for (const file of files) {
      const form = new FormData();
      form.append('asset_type', 'image');
      form.append('file', file);
      setUploadStatus(`Đang tải ảnh ${done + 1}/${files.length}: ${file.name}`);
      try {
        const response = await fetch(`/api/projects/${state.studioProjectId}/assets/upload`, {method: 'POST', body: form});
        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(data.detail || `HTTP ${response.status}`);
        }
        done += 1;
      } catch (error) { failed.push(`${file.name}: ${error.message}`); }
    }
    const button = $('studioAnalyzeImagesButton');
    if (button) button.hidden = done === 0;
    setUploadStatus(
      failed.length
        ? `Đã tải ${done}/${files.length} ảnh; ${failed.length} ảnh lỗi. ${failed[0]}`
        : `Đã tải ${done} ảnh tham khảo. Bấm “Cho AI xem ảnh tham khảo” để phân tích.`,
      failed.length ? 'error' : 'success',
    );
    await renderStudioReferenceThumbs();
  }

  async function renderStudioReferenceThumbs() {
    const target = $('studioUploadResult');
    if (!target || !state.studioProjectId) return;
    try {
      const assets = await api(`/api/projects/${state.studioProjectId}/assets`);
      const images = (assets || []).filter((item) => item.asset_type === 'image');
      if (!images.length) { target.innerHTML = ''; return; }
      target.innerHTML = `<div class="studio-thumbs">${images.slice(0, 24).map((item) =>
        `<img src="/api/assets/${item.id}/download" alt="${esc(item.original_name || '')}" title="${esc(item.original_name || '')}">`).join('')}</div>`;
      const button = $('studioAnalyzeImagesButton');
      if (button) button.hidden = false;
    } catch (_) { /* thumbnail chỉ là tiện ích, không chặn luồng */ }
  }

  async function analyzeStudioReferenceImages() {
    if (!state.studioProjectId) return setUploadStatus('Chưa có dự án chứa ảnh.', 'error');
    const button = $('studioAnalyzeImagesButton');
    if (button) button.disabled = true;
    setUploadStatus('AI đang xem ảnh tham khảo...');
    try {
      const result = await api(`/api/projects/${state.studioProjectId}/assets/analyze-images`, {method: 'POST'});
      const analysis = result.result || {};
      const list = (items) => (items || []).map((item) => `<li>${esc(item)}</li>`).join('');
      const card = document.createElement('div');
      card.className = 'studio-result-card';
      card.innerHTML = `<h3>AI đọc ảnh tham khảo · xem ${esc(result.images_seen)}/${esc(result.images_total)} ảnh</h3>
        <p class="hint">${esc(analysis.summary || '')}</p>
        <p class="hint"><b>Phong cách:</b> ${esc(analysis.visual_style || '')}</p>
        ${analysis.composition ? `<p class="hint"><b>Bố cục:</b> ${esc(analysis.composition)}</p>` : ''}
        ${(analysis.palette || []).length ? `<p class="hint"><b>Màu chủ đạo</b></p><ul>${list(analysis.palette)}</ul>` : ''}
        ${(analysis.subjects || []).length ? `<p class="hint"><b>Chủ thể lặp lại</b></p><ul>${list(analysis.subjects)}</ul>` : ''}
        ${analysis.reusable_prompt ? `<p class="hint"><b>Đoạn prompt dùng lại được:</b><br><code>${esc(analysis.reusable_prompt)}</code></p>` : ''}`;
      $('studioUploadResult')?.prepend(card);
      setUploadStatus(`AI đã đọc ${result.images_seen} ảnh tham khảo.`, 'success');
    } catch (error) { setUploadStatus(`Không đọc được ảnh: ${error.message}`, 'error'); }
    finally { if (button) button.disabled = false; }
  }

  async function analyzeStudioVideo() {
    if (!state.studioVideoId) return setMessage('Hãy chọn một video trước.', 'error');
    const provider = $('studioAnalysisProviderSelect').value || 'codex_cli';
    const button = $('studioAnalyzeButton');
    button.disabled = true;
    setStudioProgress(5, 'Đang kiểm tra transcript của video...');
    setMessage('Đang chuẩn bị transcript trước khi phân tích video...');
    try {
      const transcript = await ensureTranscriptForAnalysis(state.studioVideoId, (text) => setStudioProgress(35, text));
      setStudioProgress(45, `Đã có transcript (${number(transcript.word_count || 0)} từ). Đang phân tích cấu trúc, cảnh và phong cách...`);
      const analysisLanguage = $('studioAnalysisLanguage')?.value || 'vi';
      const response = await api(`/api/videos/${encodeURIComponent(state.studioVideoId)}/reference-analysis?provider=${encodeURIComponent(provider)}&output_language=${encodeURIComponent(analysisLanguage)}`, {method: 'POST'});
      state.studioAnalysis = response;
      state.studioReference = response;
      renderStudioAnalysis(response);
      setStudioStep(2);
      setStudioProgress(100, 'Phân tích tham chiếu đã hoàn tất.');
      setMessage('Phân tích tham chiếu hoàn tất. Sang bước tiếp theo để tạo câu chuyện mới.', 'success');
      void Promise.all([loadSummary(), loadVideos(), loadProjects()]);
    } catch (error) { setStudioProgress(0, `Phân tích thất bại: ${error.message}`, 'error'); setMessage(error.message, 'error'); }
    finally { button.disabled = false; }
  }

  function renderStudioAnalysis(payload) {
    const result = payload?.result || payload || {};
    if (Array.isArray(result.scene_map)) return renderStudioReferenceAnalysis(result);
    const keywords = (result.keywords || []).map((item) => `<span class="keyword">${esc(item.keyword)} · ${esc(item.count)}</span>`).join('') || '<span class="secondary-text">Không có từ khóa</span>';
    const recommendations = (result.recommendations || []).map((item) => `<li>${esc(item)}</li>`).join('') || '<li>Không có đề xuất.</li>';
    const metrics = result.metrics || {};
    $('studioAnalysisResult').innerHTML = `
      <div class="studio-result-columns"><div class="studio-result-card"><h3>Tổng quan</h3><p><b>Loại nội dung:</b> ${esc(result.content_type || '—')}\n<b>Ngôn ngữ:</b> ${esc(result.language || '—')}\n<b>Chủ đề:</b> ${esc(result.topic || '—')}\n<b>Hook:</b> ${esc(result.hook || '—')}</p></div><div class="studio-result-card"><h3>Chỉ số metadata</h3><p>Tiêu đề: ${esc(metrics.title_length ?? '—')} ký tự\nMô tả: ${esc(metrics.description_length ?? '—')} ký tự\nTags: ${esc(metrics.tag_count ?? '—')}\nThumbnail: ${metrics.has_thumbnail ? 'Có' : 'Không'}\nCaption: ${metrics.caption_available ? 'Có' : 'Không'}</p></div></div>
      <div class="studio-result-card"><h3>Mở đầu mô tả</h3><p>${esc(result.description_opening || 'Không có.')}</p></div>
      <div class="studio-result-columns"><div class="studio-result-card"><h3>Từ khóa</h3><div class="keyword-list">${keywords}</div></div><div class="studio-result-card"><h3>Đề xuất cải thiện</h3><ul class="studio-result-list">${recommendations}</ul><p style="margin-top:10px"><b>Bước tiếp theo:</b> ${esc(result.next_step || 'kiểm duyệt thủ công')}</p></div></div>
      <details class="studio-result-card"><summary>Xem dữ liệu phân tích đầy đủ (JSON)</summary><pre class="studio-json">${esc(JSON.stringify(result, null, 2))}</pre></details>`;
  }

  function renderStudioReferenceAnalysis(result) {
    const beats = (result.scene_map || []).map((item, index) =>
      `<li><b>${index + 1}.</b> ${esc(item.what_happens || '')}</li>`).join('') || '<li>Chưa ghi được diễn biến.</li>';
    const people = (result.characters || []).map((item) =>
      `<li><b>${esc(item.name || '')}</b> — ${esc(item.role || '')}</li>`).join('') || '<li>Chưa xác định nhân vật.</li>';
    // Lời thoại là thứ bản kể lại đánh mất đầu tiên, nên hiện nguyên văn từng câu.
    const dialogue = result.dialogue || [];
    const lines = dialogue.map((item) =>
      `<div class="dialogue-line"><span class="dialogue-who">${esc(item.speaker || 'Không rõ')}</span><span>${esc(item.line || '')}</span></div>`).join('');
    const limitations = (result.limitations || []).map((item) => `<li>${esc(item)}</li>`).join('')
      || '<li>Không ghi nhận điểm nào thiếu chắc chắn.</li>';
    const parts = Number(result.transcript_parts_read || 0);
    $('studioAnalysisResult').innerHTML = `
      <div class="studio-result-card"><h3>Nội dung câu chuyện</h3>
        ${parts > 1 ? `<p class="hint">Đã đọc hết bản ghi qua ${parts} phần.</p>` : ''}
        <p>${esc(result.content_summary || '—')}</p></div>
      <div class="studio-result-columns">
        <div class="studio-result-card"><h3>Nhân vật</h3><ul class="studio-result-list">${people}</ul></div>
        <div class="studio-result-card"><h3>Diễn biến theo thứ tự</h3><ol class="studio-result-list">${beats}</ol></div>
      </div>
      <div class="studio-result-card"><h3>Lời thoại · ${dialogue.length} câu</h3>
        ${lines ? `<div class="dialogue-list">${lines}</div>` : '<div class="studio-empty">Bản ghi không có lời thoại tách được.</div>'}</div>
      <div class="studio-result-columns">
        <div class="studio-result-card"><h3>Hình ảnh</h3><p>${esc(result.visual_style || '—')}</p></div>
        <div class="studio-result-card"><h3>Chỗ không xác định được</h3>
          <p class="hint">Bước viết kịch bản không được tự lấp vào những chỗ này.</p>
          <ul class="studio-result-list">${limitations}</ul></div>
      </div>
      <details class="studio-result-card"><summary>Xem dữ liệu phân tích đầy đủ (JSON)</summary><pre class="studio-json">${esc(JSON.stringify(result, null, 2))}</pre></details>`;
  }

  function renderStudioScript(script, writerPayload = state.studioWriter) {
    if (!script) return;
    state.scriptId = script.id || state.scriptId;
    state.studioProjectId = script.project_id || state.studioProjectId;
    const writer = writerPayload?.result || writerPayload || {};
    const productionScenes = Array.isArray(writer.scene_blueprints) ? writer.scene_blueprints : [];
    const productionSeconds = productionScenes.reduce((total, scene) => total + Number(scene.duration_seconds || 0), 0);
    const productionWords = productionScenes.reduce((total, scene) => total + String(scene.narration || '').trim().split(/\s+/).filter(Boolean).length, 0);
    const targetSeconds = Number(writer.target_duration_seconds || 0);
    const titles = (writer.new_titles || []).map((item) => `<li>${esc(item)}</li>`).join('') || '<li>Đã chuyển thành kịch bản bên dưới.</li>';
    const hashtags = (writer.hashtags || []).map((item) => `<span class="keyword">#${esc(item)}</span>`).join('') || '<span class="secondary-text">Chưa có hashtag</span>';
    $('studioScriptResult').innerHTML = `
      <div class="studio-result-columns"><div class="studio-result-card"><h3>Câu chuyện mới do AI tạo</h3><p><b>Ý tưởng:</b> ${esc(writer.new_story_concept || writer.summary || '—')}\n<b>Hướng biến tấu:</b> ${esc(writer.creative_direction || '—')}</p><div class="eyebrow" style="margin-top:10px">Tiêu đề gợi ý</div><ul class="studio-result-list">${titles}</ul></div><div class="studio-result-card"><h3>Mô tả &amp; phong cách áp dụng</h3><p>${esc(writer.new_description || '—')}</p><div class="keyword-list" style="margin-top:9px">${(writer.style_application || []).map((item) => `<span class="keyword">${esc(item)}</span>`).join('') || hashtags}</div></div></div>
      <div class="studio-summary-grid"><div class="studio-summary-card"><label>Kịch bản để đọc</label><strong>${productionScenes.length} cảnh · ${productionWords.toLocaleString('vi-VN')} từ</strong></div><div class="studio-summary-card"><label>Thời lượng storyboard</label><strong>${formatStudioDuration(productionSeconds || targetSeconds)}${targetSeconds ? ` / mục tiêu ${formatStudioDuration(targetSeconds)}` : ''}</strong></div></div>
      <div class="studio-checklist"><div class="studio-check"><b>✓</b><span><b>Nguồn giọng đọc:</b> lời dẫn trong từng cảnh của Storyboard — không lấy từ ô “Mô tả &amp; phong cách áp dụng”. Sau khi sửa kịch bản, hãy tạo lại Storyboard để đồng bộ lời dẫn.</span></div></div>
      <div class="studio-result-card studio-script"><h3>Kịch bản có thể chỉnh sửa · phiên bản ${esc(script.version || '—')}</h3><div class="studio-field"><label for="studioScriptTitleInput">Tiêu đề</label><input id="studioScriptTitleInput" value="${esc(script.script_title || '')}"></div><div class="studio-field"><label for="studioScriptHookInput">Hook</label><textarea id="studioScriptHookInput">${esc(script.hook || '')}</textarea></div><div class="studio-field"><label for="studioScriptIntroInput">Mở đầu</label><textarea id="studioScriptIntroInput">${esc(script.intro || '')}</textarea></div><div class="studio-field"><label for="studioScriptMainInput">Nội dung chính</label><textarea id="studioScriptMainInput" name="main_content">${esc(script.main_content || '')}</textarea></div><div class="studio-field"><label for="studioScriptCtaInput">CTA</label><textarea id="studioScriptCtaInput">${esc(script.cta || '')}</textarea></div><div class="studio-actions"><button class="btn small primary" onclick="saveStudioScript()">Lưu phiên bản này</button><button class="btn small ghost" onclick="reviewStudioScript()">Chuyển sang chờ duyệt</button><button class="btn small" onclick="aiReviewStudioScript()">AI duyệt kịch bản</button><span data-wf="reup" hidden><button class="btn small" onclick="checkStudioFidelity()">Soát đúng nội dung gốc</button><select id="studioTranslateLanguage" aria-label="Ngôn ngữ đích"><option value="vi">Dịch sang tiếng Việt</option><option value="en">Dịch sang tiếng Anh</option><option value="zh">Dịch sang tiếng Trung</option><option value="ja">Dịch sang tiếng Nhật</option><option value="ko">Dịch sang tiếng Hàn</option></select><button class="btn small primary" onclick="translateStudioNarration()">Dịch lời bình</button></span><button class="btn small ghost" onclick="approveStudioScript()">Duyệt kịch bản</button></div></div>`;
    $('studioChatBox').hidden = false;
    $('studioToRenderButton').disabled = false;
    if ($('studioOpenProjectButton')) $('studioOpenProjectButton').disabled = false;
    $('studioGenerateStoryboardButton').disabled = false;
    if ($('studioProjectSummary')) $('studioProjectSummary').textContent = `#${state.studioProjectId}`;
    if ($('studioScriptSummary')) $('studioScriptSummary').textContent = `v${script.version || '1'}`;
  }

  // The short's storyboard is the same thing as the long video's - shots
  // joined to their segments - so it is drawn by the same code. Rendered as a
  // plain list instead, it had no picture, no player to hear the voice and no
  // per-scene controls, which is what made the short lane feel like a
  // different, poorer app.
  // A shot id is unique across the project, but the cached list was only ever
  // the long video's - so every per-scene control on a short's card looked up
  // a shot that was not there and did nothing at all.
  function findStudioShot(shotId) {
    const wanted = Number(shotId);
    return (state.shots || []).find((item) => Number(item.id) === wanted)
      || (state.shortShots || []).find((item) => Number(item.id) === wanted)
      || null;
  }

  // A written script and the source's own transcript are both plausible
  // narrations, and one button swaps the first for the second. Nothing on
  // screen said which one the voice would read, so a project could sit with
  // an English script and a Vietnamese storyboard looking perfectly normal.
  function narrationSourceNotice() {
    const found = state.narrationSource;
    if (!found || found.source !== 'transcript') return '';
    const fromScript = Math.round((found.script_overlap || 0) * 100);
    const fromSource = Math.round((found.transcript_overlap || 0) * 100);
    return `<div class="risk-finding sev-high">
      <b>Lời trong storyboard KHÔNG phải lời kịch bản.</b>
      <div class="studio-model-note" style="margin-top:4px">
        Các cảnh đang đọc lại transcript của video gốc (${fromSource}% trùng),
        chỉ ${fromScript}% trùng kịch bản bạn đã viết — “Cắt cảnh theo lời thoại” đã thay chúng.
      </div>
      <div class="studio-actions" style="margin-top:8px;gap:6px;flex-wrap:wrap">
        <button class="btn primary" type="button" onclick="rebuildStoryboardFromScript()">Dựng lại storyboard từ kịch bản</button>
        <button class="btn" type="button" onclick="translateStudioNarration()">Hoặc dịch lời gốc sang ngôn ngữ xuất bản</button>
      </div>
    </div>`;
  }

  // The way back from a dialogue cut: shots and timeline rebuilt from the
  // script that is actually approved, then whatever voice already exists for
  // those words is attached again.
  async function rebuildStoryboardFromScript() {
    const projectId = Number(state.studioProjectId || state.projectId || 0);
    if (!projectId) return setMessage('Hãy mở một dự án trước.', 'error');
    if (!confirm('Dựng lại storyboard từ kịch bản?\n\nCác cảnh đang đọc transcript của video gốc sẽ bị thay bằng lời kịch bản. Giọng đã tạo cho lời kịch bản sẽ được gắn lại tự động.')) return;
    setMessage('Đang dựng lại storyboard từ kịch bản...', '');
    try {
      await api(`/api/projects/${projectId}/shots/generate?force=true`, {method: 'POST'});
      await api(`/api/projects/${projectId}/timeline/generate?force=true`, {method: 'POST'});
      const restored = await api(`/api/projects/${projectId}/timeline/reattach-voice`, {
        method: 'POST', body: JSON.stringify({video_variant: 'long'}),
      });
      const bundle = await api(`/api/projects/${projectId}`);
      state.narrationSource = bundle.narration_source || null;
      state.shots = bundle.latest_shots || [];
      state.timeline = bundle.latest_timeline || [];
      renderStudioStoryboard(state.shots, state.timeline);
      setMessage(
        `Đã dựng lại ${state.shots.length} cảnh từ kịch bản.`
        + (restored.attached ? ` Gắn lại giọng cho ${restored.attached} cảnh.` : ' Chưa có giọng cho lời mới — hãy tạo giọng.'),
        'success');
    } catch (error) { setMessage(error.message, 'error'); }
  }

  function renderStudioStoryboard(shots = [], timeline = [], containerId = 'studioStoryboardResult') {
    const result = $(containerId);
    if (!result) return;
    if (!shots.length) {
      result.innerHTML = '<div class="studio-empty">Chưa có cảnh. Hãy tạo storyboard hoặc mở chỉnh sửa chi tiết để thêm cảnh.</div>';
      return;
    }
    result.innerHTML = narrationSourceNotice() + `<div class="studio-checklist"><div class="studio-check"><b>✓</b><span>Storyboard gồm <b>${shots.length} cảnh</b>. Mỗi thẻ bên dưới hiển thị <b>lời AI sẽ đọc</b>, prompt hình ảnh và thời lượng của cảnh.</span></div><div class="queue-controls" style="justify-content:flex-start;margin:8px 0 0;gap:6px;flex-wrap:wrap"><button class="btn small ghost" type="button" onclick="restoreStudioGeneratedVoices()">Khôi phục voice đã tạo</button><span class="secondary-text">Dùng khi audio đã tạo nhưng chưa hiện lại trong storyboard.</span></div></div><div class="storyboard-grid">${shots.map((shot, index) => {
      const segment = timeline.find((item) => Number(item.shot_id) === Number(shot.id));
      // Voiceover is rendered from timeline.voice_text.  A shot is its visual
      // plan and can be older after a per-scene translation, so displaying
      // shot.narration here made an English audio look as if it were Vietnamese.
      const spokenText = String(segment?.voice_text || shot.narration || '').trim();
      const preview = segment?.visual_path
        ? (/\.(jpg|jpeg|png|webp|bmp|gif)$/i.test(segment.visual_path) ? `<img src="/api/projects/${state.studioProjectId}/timeline/${segment.id}/visual-preview" alt="Cảnh ${shot.shot_index || index + 1}">` : `<video src="/api/projects/${state.studioProjectId}/timeline/${segment.id}/visual-preview" controls muted preload="metadata"></video>`)
        : `<div class="storyboard-prompt">Chưa có video/ảnh thật. Hãy tạo cảnh AI hoặc gắn asset trước khi render.</div>`;
      // The shape of the audio shows a dead scene or a line cut short at a
      // glance; pressing play on every scene in turn is how those get missed.
      const audioPreview = segment?.audio_path
        ? `<div class="storyboard-audio"><b>Nghe lời đọc</b>`
          + `<img class="storyboard-wave" alt="Dạng sóng giọng đọc" loading="lazy"`
          + ` src="/api/projects/${state.studioProjectId}/timeline/${segment.id}/waveform"`
          + ` onerror="this.remove()" />`
          + `<audio controls preload="metadata" src="/api/projects/${state.studioProjectId}/timeline/${segment.id}/audio-preview"></audio></div>`
        : `<div class="secondary-text" style="margin-top:8px">Chưa có giọng đọc cho cảnh này.</div>`;
      const voiceControls = segment
        ? `<div class="queue-controls" style="justify-content:flex-start;margin-top:8px;gap:6px;flex-wrap:wrap"><button class="btn small ghost" type="button" onclick="attachStudioGeneratedVoiceForScene(${segment.id})">Chọn voice đã tạo</button><button class="btn small ghost" type="button" onclick="uploadStudioVoiceForScene(${segment.id})">${segment.audio_path ? 'Thay bằng file voice' : 'Nạp file giọng vào cảnh'}</button><span class="secondary-text">Audio được gắn trực tiếp vào cảnh này.</span></div>`
        : '';
      // Where in the source this picture was taken from, editable before the
      // render rather than discovered in it.
      const cutControls = String(segment?.visual_path || '').includes('source_clips')
        ? `<div class="queue-controls" style="justify-content:flex-start;margin-top:8px;gap:6px;flex-wrap:wrap">
             <label class="secondary-text" style="display:flex;align-items:center;gap:5px">Cắt từ giây
               <input id="studioCutStart-${segment.id}" type="number" min="0" step="0.5" style="width:88px"
                 value="${Number(segment.source_start_seconds ?? -1) >= 0 ? Number(segment.source_start_seconds).toFixed(1) : ''}"
                 placeholder="tự chọn" /></label>
             <label class="secondary-text" style="display:flex;align-items:center;gap:5px">Bỏ đầu
               <input id="studioTrimHead-${segment.id}" type="number" min="0" step="0.1" style="width:72px"
                 value="${Number(segment.edit_trim_head || 0).toFixed(1)}" /></label>
             <label class="secondary-text" style="display:flex;align-items:center;gap:5px">Bỏ cuối
               <input id="studioTrimTail-${segment.id}" type="number" min="0" step="0.1" style="width:72px"
                 value="${Number(segment.edit_trim_tail || 0).toFixed(1)}" /></label>
             <button class="btn small" type="button" onclick="saveSegmentCut(${segment.id})">Cắt lại cảnh này</button>
           </div>`
        : '';
      const shotVisualPath = String(segment?.visual_path || '');
      const wantsVisual = String(shot.status || '') === 'needs_visual';
      return `
      <div class="storyboard-card"${wantsVisual ? ' style="outline:1px solid var(--danger,#e5484d)"' : ''}>
        <div class="storyboard-card-head"><span class="storyboard-card-title">Cảnh ${shot.shot_index || index + 1}</span>${shot.status ? shotStatusTag(shot.status) : ''}</div>
        <div class="storyboard-media">${preview}</div>
        <div class="storyboard-body"><div class="storyboard-narration"><b>Lời AI sẽ đọc</b>${esc(spokenText || 'Chưa có lời dẫn cho cảnh này.')}</div>${audioPreview}${voiceControls}${cutControls}<div class="storyboard-prompt">${wantsVisual ? '⊕ <b>Cảnh này thiếu hình minh hoạ.</b> ' : ''}${esc(shot.visual_prompt || 'Chưa có visual prompt')}</div><div class="storyboard-summary"><span>${esc(shot.asset_type || 'generated')}</span><span>${Number(shot.duration_seconds || 0).toFixed(1)} giây</span></div><div class="queue-controls" style="justify-content:flex-start;margin-top:9px;flex-wrap:wrap"><button class="btn small ghost" onclick="editStudioScene(${shot.id}, ${segment?.id || 0})">Sửa cảnh này</button><select id="studioShotSceneRatio-${shot.id}" aria-label="Định dạng kích thước"><option value="1280:720">Ngang 16:9</option><option value="720:1280">Dọc 9:16</option><option value="1024:1024">Vuông 1:1</option></select><select id="studioShotImageProvider-${shot.id}" aria-label="Engine tạo ảnh AI">${IMAGE_PROVIDER_OPTIONS}</select><button class="btn small primary" type="button" onclick="generateStudioShotImage(${shot.id})">Tạo ảnh AI cho cảnh</button><select id="studioShotVideoProvider-${shot.id}" aria-label="Engine tạo video AI">${VIDEO_PROVIDER_OPTIONS}</select><button class="btn small primary" type="button" onclick="generateStudioShotVideo(${shot.id})">${/\.(jpg|jpeg|png|webp|bmp|gif)$/i.test(shotVisualPath) ? 'Tạo video AI từ ảnh cho cảnh' : 'Cần tạo ảnh trước'}</button><button class="btn small ghost" type="button" onclick="regenerateStudioShotVoice(${shot.id})">Tạo lại giọng đọc cảnh này</button></div></div>
      </div>`;
    }).join('')}</div>`;
    result.querySelectorAll('.storyboard-card').forEach((card, index) => {
      const shot = shots[index] || {};
      const segment = timeline.find((item) => Number(item.shot_id) === Number(shot.id));
      const sourceStart = Number(segment?.source_start_seconds);
      if (!segment || !Number.isFinite(sourceStart) || sourceStart < 0) return;
      const end = sourceStart + Number(segment.duration_seconds || 0);
      const label = document.createElement('div');
      label.className = 'secondary-text';
      label.style.marginTop = '7px';
      label.textContent = `Cắt từ video nguồn: ${formatStudioDuration(sourceStart)} → ${formatStudioDuration(end)}`;
      card.querySelector('.storyboard-summary')?.after(label);
    });
  }

  async function refreshStudioStoryboard() {
    if (!state.studioProjectId) return null;
    const bundle = await api(`/api/projects/${state.studioProjectId}`);
    state.studioProject = bundle.project || state.studioProject;
    state.shots = bundle.latest_shots || [];
    state.timeline = bundle.latest_timeline || [];
    renderStudioStoryboard(state.shots, state.timeline);
    return bundle;
  }

  async function restoreStudioGeneratedVoices() {
    if (!state.studioProjectId) return setMessage('Chưa có project.', 'error');
    setMessage('Đang tìm các file voice đã tạo để gắn lại vào storyboard...');
    try {
      const result = await api(`/api/projects/${state.studioProjectId}/timeline/reattach-voice`, {
        method: 'POST', body: JSON.stringify({video_variant: 'long'}),
      });
      await refreshStudioStoryboard();
      const missing = (result.missing || []).length;
      setMessage(
        result.attached
          ? `Đã khôi phục voice cho ${result.attached} cảnh.${missing ? ` Còn ${missing} cảnh cần nạp tay hoặc tạo lại voice.` : ''}`
          : (result.library_size ? 'Không tìm được voice khớp lời đọc hiện tại. Hãy dùng “Nạp file giọng vào cảnh” trên từng thẻ.' : 'Chưa tìm thấy file voice đã tạo trong project.'),
        result.attached ? 'success' : 'error',
      );
    } catch (error) { setMessage(`Không khôi phục được voice: ${error.message}`, 'error'); }
  }

  async function uploadStudioVoiceForScene(segmentId) {
    if (!state.studioProjectId) return setMessage('Chưa có project.', 'error');
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'audio/*,.mp3,.wav,.m4a,.aac,.flac,.ogg';
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      setMessage(`Đang nạp ${file.name} vào cảnh...`);
      try {
        const form = new FormData();
        form.append('asset_type', 'audio');
        form.append('file', file);
        const response = await fetch(`/api/projects/${state.studioProjectId}/assets/upload`, {method: 'POST', body: form});
        const uploaded = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(uploaded.detail || `HTTP ${response.status}`);
        const assetId = Number(uploaded.asset?.id || 0);
        if (!assetId) throw new Error('App không nhận được audio vừa tải lên.');
        await api(`/api/timeline/${segmentId}/attach-asset`, {
          method: 'POST', body: JSON.stringify({asset_id: assetId}),
        });
        await refreshStudioStoryboard();
        setMessage(`Đã gắn ${file.name} vào cảnh. Bạn có thể bấm Nghe lời đọc ngay trên thẻ.`, 'success');
      } catch (error) { setMessage(`Không nạp được audio: ${error.message}`, 'error'); }
    };
    input.click();
  }

  async function attachStudioGeneratedVoiceForScene(segmentId) {
    if (!state.studioProjectId) return setMessage('Chưa có project.', 'error');
    try {
      const result = await api(`/api/projects/${state.studioProjectId}/voice-library`);
      const voices = result.voices || [];
      if (!voices.length) throw new Error('Chưa tìm thấy voice đã tạo trong project. Hãy nạp file audio từ máy.');
      const choices = voices.map((voice, index) => `${index + 1}. ${voice.filename} — ${String(voice.text || '').slice(0, 90)}`).join('\n');
      const answer = window.prompt(`Chọn số voice để gắn vào cảnh:\n\n${choices}`, '1');
      if (answer == null) return;
      const selected = voices[Number(answer) - 1];
      if (!selected) throw new Error('Số voice không hợp lệ.');
      await api(`/api/timeline/${segmentId}/attach-generated-voice`, {
        method: 'POST', body: JSON.stringify({voice_key: selected.key}),
      });
      await refreshStudioStoryboard();
      setMessage(`Đã gắn ${selected.filename} vào cảnh.`, 'success');
    } catch (error) { setMessage(`Không gắn được voice: ${error.message}`, 'error'); }
  }

  // Providers that use a browser sidecar + the caller's own logged-in
  // subscription/account instead of a configured API key. Add a provider
  // here (plus its <option> in the 4 scene-provider selects above) when
  // wiring up another web app in web_video_sidecar.py.
  const SUBSCRIPTION_PROVIDER_HINTS = {
    antigravity_image: 'Antigravity sẽ dùng gói AI đã đăng nhập để tạo ảnh và tự gắn vào storyboard. Cần bật sidecar YT Factory một lần trong Antigravity.',
    gflow_cli: 'Google Flow/Veo sẽ dùng gói Google đã đăng ký qua gflow-cli. App tự chạy worker, nhận MP4 và gắn vào timeline; không cần Extension.',
    gflow_image: 'Google Flow sẽ tạo ảnh/GIF qua profile riêng của gflow-cli; không dùng credit Veo và không cần Extension.',
    flow_image: 'Google Flow sẽ tạo ảnh ngay trong Cốc Cốc đang đăng nhập qua Extension YT Factory; không dùng credit Veo.',
    flow_veo: 'Flow Extension (legacy) giữ lại làm dự phòng. Cần Extension trình duyệt đang kết nối.',
    meta_ai_video: 'Meta AI (Vibes) sẽ dùng tài khoản Facebook/Instagram đã đăng nhập để tạo video miễn phí và tự gắn vào storyboard. Cần chạy `python web_video_sidecar.py --provider meta_ai_video` và đăng nhập một lần.',
    gemini_web_image: 'Gemini (web) sẽ dùng gói Google AI Pro/Ultra đã đăng nhập để tạo ảnh qua giao diện chat, không cần API key. Cần chạy `python web_video_sidecar.py --provider gemini_web_image --login` và đăng nhập Google một lần.',
    chatgpt_web_image: 'ChatGPT (web) sẽ dùng tài khoản ChatGPT Plus/Pro đã đăng nhập để tạo ảnh qua giao diện chat, không cần API key. Cần chạy `python web_video_sidecar.py --provider chatgpt_web_image --login` và đăng nhập một lần.',
  };
  const SUBSCRIPTION_PROVIDER_SHORT = {
    antigravity_image: 'Antigravity sẽ dùng gói đã đăng nhập.',
    gflow_cli: 'Google Flow/Veo sẽ dùng gói Google đã đăng ký qua gflow-cli.',
    gflow_image: 'Google Flow ảnh sẽ dùng profile gflow-cli đã đăng nhập.',
    flow_image: 'Google Flow ảnh sẽ dùng phiên Cốc Cốc đã đăng nhập.',
    flow_veo: 'Flow Extension legacy sẽ dùng gói Google đã đăng nhập.',
    meta_ai_video: 'Meta AI (Vibes) sẽ dùng tài khoản Facebook/Instagram đã đăng nhập (miễn phí).',
    gemini_web_image: 'Gemini (web) sẽ dùng gói Google AI Pro/Ultra đã đăng nhập.',
    chatgpt_web_image: 'ChatGPT (web) sẽ dùng tài khoản ChatGPT Plus/Pro đã đăng nhập.',
  };
  const isSubscriptionProvider = (provider) => provider in SUBSCRIPTION_PROVIDER_HINTS;

  async function sidecarWarningText(provider) {
    // Open archives need no login, no extension and no sidecar to poll.
    if (provider === 'stock_footage' || provider === 'motion_graphics') return '';
    if (!isSubscriptionProvider(provider)) return '';
    if (provider === 'gflow_cli' || provider === 'gflow_image') {
      const ready = Boolean(state.integrations?.find((item) => item.key === 'gflow_cli')?.ready);
      const mediaKind = provider === 'gflow_image' ? 'ảnh/GIF' : 'video';
      return ready ? '' : `⚠ gflow-cli chưa sẵn sàng. Cần cài tool và đăng nhập Google Flow một lần trước khi tạo ${mediaKind}.`;
    }
    try {
      const status = await api('/api/scene-sidecar-status');
      const info = status[provider];
      if (info && !info.alive && !info.extension_connected) {
        const seenText = info.seconds_ago == null ? 'chưa từng thấy poll lần nào kể từ khi mở app'
          : `lần poll gần nhất cách đây ${Math.round(info.seconds_ago)}s`;
        const startHint = provider === 'antigravity_image'
          ? 'bật sidecar trong Antigravity'
          : 'mở Cốc Cốc và bật Extension YT Factory';
        return `⚠ Sidecar chưa chạy (${seenText}) — job sẽ nằm chờ mãi ở "queued", tiến độ sẽ không nhích. Hãy ${startHint} trước khi bấm tạo.`;
      }
    } catch { /* status check is best-effort; don't block the hint on it */ }
    return '';
  }

  async function sidecarWarningHtml(provider) {
    const text = await sidecarWarningText(provider);
    return text ? `<br><b style="color:#c0392b">${text}</b>` : '';
  }

  async function updateStudioSceneGenerationAvailability() {
    const hasProject = Boolean(state.studioProjectId);

    const imageButton = $('studioGenerateImagesButton');
    const imageHint = $('studioSceneImageHint');
    if (imageButton) {
      const provider = $('studioSceneImageProviderSelect')?.value || 'gemini_image';
      const integrationKey = provider.startsWith('gemini_') ? 'google_gemini' : 'openai_gpt';
      const providerReady = isSubscriptionProvider(provider) || Boolean(state.integrations?.find((item) => item.key === integrationKey)?.ready);
      // Keep this action clickable: when the key is absent, a click guides
      // the user to the exact connection card instead of looking broken.
      imageButton.disabled = !hasProject;
      if (imageHint) {
        imageHint.innerHTML = isSubscriptionProvider(provider)
          ? SUBSCRIPTION_PROVIDER_HINTS[provider]
          : providerReady
          ? 'Google Gemini/OpenAI sẽ tạo một ảnh kể chuyện cho mỗi cảnh; FFmpeg tạo chuyển động nhẹ khi dựng video.'
          : `Cần kết nối <b>${provider.startsWith('gemini_') ? 'Google Gemini API' : 'OpenAI GPT + Image API'}</b> trước. Vào Công cụ & kết nối, dán API key rồi bấm “Lưu & bật”.`;
        void sidecarWarningHtml(provider).then((warning) => { if (warning) imageHint.innerHTML += warning; });
      }
    }

    const planVisualsButton = $('studioPlanVisualsButton');
    if (planVisualsButton) planVisualsButton.disabled = !hasProject;
    const planEditButton = $('studioPlanEditButton');
    if (planEditButton) planEditButton.disabled = !hasProject;

    const videoButton = $('studioGenerateVideosButton');
    const videoHint = $('studioSceneVideoHint');
    if (videoButton) {
      const provider = $('studioSceneVideoProviderSelect')?.value || 'gflow_cli';
      const providerReady = provider === 'gflow_cli'
        ? Boolean(state.integrations?.find((item) => item.key === 'gflow_cli')?.ready)
        : isSubscriptionProvider(provider) || Boolean(state.integrations?.find((item) => item.key === 'google_gemini')?.ready);
      videoButton.disabled = !hasProject;
      if (videoHint) {
        videoHint.innerHTML = provider === 'motion_graphics'
          ? 'Cảnh sẽ được vẽ bằng motion graphics: biểu đồ động, thẻ số liệu, tiêu đề chuyển động, cảnh terminal. Không tốn credit và không cần API key. Hợp với cảnh trình bày số liệu — thứ không có footage nào quay được.'
          : provider === 'stock_footage'
          ? 'Cảnh sẽ dùng footage thật public-domain từ Archive.org và NASA, cắt đúng thời lượng. Không tốn credit và không cần API key; nguồn từng clip được ghi vào NGUON_FOOTAGE.json trong thư mục dự án.'
          : isSubscriptionProvider(provider)
          ? SUBSCRIPTION_PROVIDER_HINTS[provider]
          : providerReady
          ? 'Google Veo sẽ tạo clip video thật cho mỗi cảnh (chậm hơn và tốn credits hơn). Video hoàn tất sẽ hiện trong storyboard.'
          : 'Cần kết nối <b>Google Gemini API</b> trước. Vào Công cụ & kết nối, dán API key rồi bấm “Lưu & bật”.';
        void sidecarWarningHtml(provider).then((warning) => { if (warning) videoHint.innerHTML += warning; });
      }
    }
  }

  const VISUAL_KIND_LABELS = {image: 'Ảnh tĩnh', gif: 'Ảnh động (GIF)', video: 'Video'};
  const TRANSITION_LABELS = {cut: 'Cắt thẳng', fade: 'Mờ dần'};
  const EFFECT_LABELS = {zoom_in: 'Đẩy vào', zoom_out: 'Kéo lui', static: 'Đứng yên'};

  function planSelect(segmentId, field, value, labels) {
    const options = Object.entries(labels)
      .map(([key, label]) => `<option value="${key}"${key === value ? ' selected' : ''}>${esc(label)}</option>`)
      .join('');
    return `<select class="plan-select" data-segment="${segmentId}" data-field="${field}">${options}</select>`;
  }

  async function saveScenePlanField(segmentId, field, value) {
    const body = {};
    body[field] = field === 'visual_fps' ? Number(value) : value;
    try {
      await api(`/api/timeline/${segmentId}/plan`, {method: 'PATCH', body: JSON.stringify(body)});
      setMessage('Đã lưu thay đổi cho cảnh.', 'success');
    } catch (error) { setMessage(`Không lưu được: ${error.message}`, 'error'); }
  }

  function bindPlanSelects(container) {
    container.querySelectorAll('.plan-select').forEach((select) => {
      select.addEventListener('change', () => void saveScenePlanField(
        select.dataset.segment, select.dataset.field, select.value,
      ));
    });
  }

  async function planStudioVisuals() {
    if (!state.studioProjectId) return setMessage('Chưa có project.', 'error');
    const policy = $('studioMotionPolicySelect')?.value || 'balanced';
    const button = $('studioPlanVisualsButton');
    const target = $('studioVisualPlan');
    if (button) button.disabled = true;
    if (target) target.innerHTML = '<div class="studio-empty">AI đang đọc kịch bản để quyết định từng cảnh...</div>';
    setMessage('Đang phân tích loại hình cho từng cảnh...');
    try {
      const result = await api(
        `/api/projects/${state.studioProjectId}/timeline/plan-visuals?motion_policy=${policy}`,
        {method: 'POST'},
      );
      renderStudioVisualPlan(result);
      const summary = Object.entries(result.by_kind || {})
        .map(([kind, count]) => `${count} ${VISUAL_KIND_LABELS[kind] || kind}`).join(' · ');
      setMessage(`Đã lên kế hoạch ${result.scenes?.length || 0} cảnh: ${summary}`, 'success');
    } catch (error) {
      if (target) target.innerHTML = '';
      setMessage(`Không phân tích được: ${error.message}`, 'error');
    } finally { if (button) button.disabled = false; }
  }

  function renderStudioVisualPlan(result) {
    const target = $('studioVisualPlan');
    if (!target) return;
    const scenes = result.scenes || [];
    if (!scenes.length) return void (target.innerHTML = '<div class="studio-empty">Chưa có cảnh nào được lên kế hoạch.</div>');
    const rows = scenes.map((scene) => `<tr>
      <td>${esc(scene.segment_index)}</td>
      <td>${planSelect(scene.segment_id, 'visual_kind', scene.kind, VISUAL_KIND_LABELS)}</td>
      <td>${scene.fps ? `${esc(scene.fps)} fps` : '—'}</td>
      <td class="plan-reason">${esc(scene.reason || '')}</td>
    </tr>`).join('');
    target.innerHTML = `<div class="studio-result-card"><h3>Loại hình từng cảnh</h3>
      <p class="hint">AI quyết định dựa trên kịch bản; đổi ở đây nếu bạn thấy chưa đúng, thay đổi được lưu ngay.</p>
      <div class="plan-table-wrap"><table class="plan-table"><thead><tr>
      <th>Cảnh</th><th>Loại hình</th><th>FPS</th><th>Lý do</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
    bindPlanSelects(target);
  }

  async function planStudioEdit() {
    if (!state.studioProjectId) return setMessage('Chưa có project.', 'error');
    const button = $('studioPlanEditButton');
    const target = $('studioEditPlan');
    if (button) button.disabled = true;
    if (target) target.innerHTML = '<div class="studio-empty">AI đang lên kế hoạch dựng...</div>';
    setMessage('Đang lập kế hoạch dựng...');
    try {
      const result = await api(`/api/projects/${state.studioProjectId}/edit-plan`, {method: 'POST'});
      renderStudioEditPlan(result);
      setMessage(`Đã lên kế hoạch dựng cho ${result.scenes?.length || 0} cảnh.`, 'success');
    } catch (error) {
      if (target) target.innerHTML = '';
      setMessage(`Không lập được kế hoạch dựng: ${error.message}`, 'error');
    } finally { if (button) button.disabled = false; }
  }

  function renderStudioEditPlan(result) {
    const target = $('studioEditPlan');
    if (!target) return;
    const scenes = result.scenes || [];
    if (!scenes.length) return void (target.innerHTML = '<div class="studio-empty">Chưa có cảnh nào trong kế hoạch dựng.</div>');
    const CLEANUP_LABELS = {logo: 'Logo', watermark: 'Watermark', subtitle: 'Phụ đề gốc', other: 'Khác'};
    const METHOD_LABELS = {blur: 'làm mờ', delogo: 'xoá', crop: 'cắt mép'};
    const trimText = (scene) => {
      const head = Number(scene.trim_head_seconds || 0);
      const tail = Number(scene.trim_tail_seconds || 0);
      if (!head && !tail) return '—';
      return [head ? `đầu ${head}s` : '', tail ? `cuối ${tail}s` : ''].filter(Boolean).join(', ');
    };
    const cleanupText = (scene) => {
      const items = (scene.cleanups || []).map((item) =>
        `${CLEANUP_LABELS[item.kind] || item.kind} · ${METHOD_LABELS[item.method] || item.method}`);
      if (scene.needs_extra_visual) items.push(`⊕ thiếu hình: ${scene.extra_visual_note || ''}`);
      return items.length ? items.map((item) => esc(item)).join('<br>') : '—';
    };
    const rows = scenes.map((scene) => `<tr>
      <td>${esc(scene.segment_index)}</td>
      <td>${planSelect(scene.segment_id, 'transition', scene.transition, TRANSITION_LABELS)}</td>
      <td>${planSelect(scene.segment_id, 'effect', scene.effect, EFFECT_LABELS)}</td>
      <td>${esc(trimText(scene))}</td>
      <td>${cleanupText(scene)}</td>
      <td class="plan-reason">${esc(scene.note || '')}</td>
    </tr>`).join('');
    const header = [result.pacing, result.music_mood].filter(Boolean).map(esc).join(' · ');
    target.innerHTML = `<div class="studio-result-card"><h3>Kế hoạch dựng</h3>
      ${header ? `<p class="hint">${header}</p>` : ''}
      <p class="hint">Áp dụng khi render: chuyển cảnh, hiệu ứng, cắt bỏ phần thừa đầu/cuối, và xoá/làm mờ logo · watermark · phụ đề gốc còn dính trong hình.</p>
      <div class="plan-table-wrap"><table class="plan-table"><thead><tr>
      <th>Cảnh</th><th>Chuyển cảnh</th><th>Hiệu ứng</th><th>Cắt thừa</th><th>Dọn hình</th><th>Ghi chú</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
    bindPlanSelects(target);
  }

  // WF Lồng tiếng gọi đúng những endpoint mà panel Dự án vẫn gọi. Khác biệt
  // duy nhất: không gọi openProjectDetail, vì làm vậy sẽ kéo người dùng ra
  // khỏi wizard giữa chừng một bước.
  function studioProjectVideoId() {
    const project = state.projects?.find((item) => Number(item.id) === Number(state.studioProjectId));
    return project?.youtube_video_id || state.studioVideoId || '';
  }

  // Used for generic source/clip jobs.  The storyboard watcher below has
  // voice-specific post-processing and must remain separate.
  async function watchStudioQueueJob(jobId, jobType) {
    for (let attempt = 0; attempt < 1200; attempt += 1) {
      try {
        const job = await api(`/api/jobs/${jobId}`);
        if (job.status === 'completed') {
          setStudioProgress(100, `${jobType} đã hoàn tất.`, 'success');
          setMessage(`${jobType} đã hoàn tất.`, 'success');
          return job;
        }
        if (job.status === 'error') {
          setStudioProgress(0, `${jobType} thất bại.`, 'error');
          setMessage(`${jobType} thất bại: ${job.error || 'Lỗi không xác định.'}`, 'error');
          return job;
        }
        if (attempt % 4 === 0) setStudioProgress(50, `${jobType} đang xử lý... (${job.status})`);
      } catch (error) {
        setMessage(`Không đọc được trạng thái ${jobType}: ${error.message}`, 'error');
        return null;
      }
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
    setMessage(`${jobType} chạy quá lâu; mở thẻ Dự án để xem trạng thái.`, 'error');
    return null;
  }

  async function queueStudioProductionJob(jobType, provider, label) {
    if (!state.studioProjectId) return setMessage('Chưa có project.', 'error');
    setStudioProgress(10, `Đang đưa ${label} vào worker...`);
    setMessage(`Đang đưa ${label} vào worker...`);
    try {
      const response = await api(`/api/projects/${state.studioProjectId}/jobs`, {
        method: 'POST',
        body: JSON.stringify({job_type: jobType, provider, confirmed: true}),
      });
      if (response.job?.id) return await watchStudioQueueJob(response.job.id, label);
      return response;
    } catch (error) {
      setStudioProgress(0, `${label} thất bại: ${error.message}`, 'error');
      setMessage(error.message, 'error');
      return null;
    }
  }

  async function downloadStudioSource() {
    const videoId = studioProjectVideoId();
    if (!videoId) return setMessage('Chưa chọn video nguồn.', 'error');
    if (!confirm('Tải video gốc về máy để cắt hình cho các cảnh? App không dùng cookie hay tài khoản YouTube.')) return;
    const button = $('studioDownloadSourceButton');
    if (button) button.disabled = true;
    setStudioProgress(10, 'Đang tải video gốc về máy...');
    setMessage('Đang tải video gốc; thời gian phụ thuộc độ dài video và kết nối.');
    try {
      const result = await api(`/api/videos/${encodeURIComponent(videoId)}/download?media_type=video&confirmed=true`, {method: 'POST'});
      setStudioProgress(100, 'Đã tải xong video gốc.', 'success');
      setMessage(`Đã tải video gốc: ${result.path}`, 'success');
    } catch (error) {
      setStudioProgress(0, `Tải video gốc thất bại: ${error.message}`, 'error');
      setMessage(error.message, 'error');
    } finally { if (button) button.disabled = false; }
  }

  async function cutStudioScenesByDialogue() {
    if (!state.studioProjectId) return setMessage('Chưa có project.', 'error');
    const button = $('studioCutByDialogueButton');
    if (button) button.disabled = true;
    setMessage('Đang chọn mốc hình trong video gốc cho từng câu của storyboard; voice và cảnh hiện có sẽ được giữ nguyên...');
    try {
      const before = await refreshStudioStoryboard();
      const timeline = before?.latest_timeline || [];
      if (!timeline.length) throw new Error('Chưa có storyboard. Hãy tạo storyboard từ kịch bản trước.');
      const voiceCount = timeline.filter((item) => String(item.audio_path || '').trim()).length;
      const plan = await api(`/api/projects/${state.studioProjectId}/timeline/plan-source-cues`, {method: 'POST'});
      renderStudioSourceCuePlan(plan);
      if (Number(plan.planned || 0) !== timeline.length) {
        throw new Error(`Mới chọn được ${plan.planned || 0}/${timeline.length} mốc hình. Hãy chạy lại bước này trước khi cắt clip.`);
      }
      const currentVoices = (state.timeline || []).filter((item) => String(item.audio_path || '').trim()).length;
      if (currentVoices < voiceCount) throw new Error('Voice trong storyboard ít hơn trước khi chọn mốc; app đã dừng để tránh xuất video thiếu tiếng. Hãy bấm “Khôi phục voice đã tạo”.');
      setMessage(`Đã chọn mốc hình cho ${plan.planned}/${timeline.length} cảnh. Bấm “3. Cắt clip theo các mốc đã chọn” để tạo video cảnh.`, 'success');
    } catch (error) { setMessage(`Không cắt được: ${error.message}`, 'error'); }
    finally { if (button) button.disabled = false; }
  }

  async function planStudioSourceCues() {
    if (!state.studioProjectId) return setMessage('Chưa có project.', 'error');
    const button = $('studioPlanSourceCuesButton');
    const target = $('studioSourceCuePlan');
    if (button) button.disabled = true;
    if (target) target.innerHTML = '<div class="studio-empty">AI đang đọc lời video gốc để chọn đoạn hình...</div>';
    setMessage('Đang chọn đoạn hình từ video gốc cho từng cảnh...');
    try {
      const result = await api(`/api/projects/${state.studioProjectId}/timeline/plan-source-cues`, {method: 'POST'});
      renderStudioSourceCuePlan(result);
      setMessage(`Đã chọn ${result.planned}/${result.total_segments} cảnh, ${result.distinct_cues} mốc khác nhau.`, 'success');
    } catch (error) {
      if (target) target.innerHTML = '';
      setMessage(`Không chọn được đoạn nguồn: ${error.message}`, 'error');
    } finally { if (button) button.disabled = false; }
  }

  function renderStudioSourceCuePlan(result) {
    const target = $('studioSourceCuePlan');
    if (!target) return;
    const scenes = result.scenes || [];
    if (!scenes.length) return void (target.innerHTML = '<div class="studio-empty">Chưa chọn được cảnh nào.</div>');
    const clock = (seconds) => {
      const total = Math.max(0, Math.round(Number(seconds) || 0));
      return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
    };
    const rows = scenes.map((scene) => `<tr>
      <td>${esc(scene.segment_index)}</td>
      <td>${clock(scene.source_start_seconds)}</td>
      <td class="plan-reason">${esc(scene.reason || '')}</td>
    </tr>`).join('');
    const warning = Number(result.distinct_cues) < scenes.length
      ? '<p class="hint" style="color:#c0392b">Có cảnh trùng mốc — nên chạy lại hoặc sửa tay trước khi cắt.</p>'
      : '';
    target.innerHTML = `<div class="studio-result-card"><h3>Đoạn hình lấy từ video gốc</h3>
      <p class="hint">AI đọc lời video gốc kèm mốc thời gian rồi khớp với từng câu bình luận.</p>${warning}
      <div class="plan-table-wrap"><table class="plan-table"><thead><tr>
      <th>Cảnh</th><th>Mốc trong video gốc</th><th>Lý do</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
  }

  async function cutStudioSourceScenes() {
    if (!state.studioProjectId) return setMessage('Chưa có project.', 'error');
    try {
      const before = await refreshStudioStoryboard();
      const timeline = before?.latest_timeline || [];
      if (!timeline.length) throw new Error('Chưa có storyboard để cắt clip.');
      const missingVoice = timeline.filter((item) => !String(item.audio_path || '').trim());
      if (missingVoice.length) throw new Error(`Còn ${missingVoice.length}/${timeline.length} cảnh chưa có voice. Hãy tạo voice trước để clip được cắt đúng thời lượng lời đọc.`);
      const unplanned = timeline.filter((item) => {
        const sourceStart = Number(item.source_start_seconds);
        return !Number.isFinite(sourceStart) || sourceStart < 0;
      });
      if (unplanned.length) throw new Error(`Còn ${unplanned.length}/${timeline.length} cảnh chưa có mốc hình. Hãy bấm “2. Chọn mốc hình theo lời thoại” trước.`);
      const voiceCount = timeline.length;
      const job = await queueStudioProductionJob('source_visuals', 'source_video', 'Cắt clip từ video gốc');
      if (!job || job.status === 'error') throw new Error(job?.error || 'Không cắt được clip từ video gốc.');
      const after = await refreshStudioStoryboard();
      const afterTimeline = after?.latest_timeline || [];
      const attachedVoices = afterTimeline.filter((item) => String(item.audio_path || '').trim()).length;
      const attachedVisuals = afterTimeline.filter((item) => String(item.visual_path || '').trim()).length;
      if (attachedVoices !== voiceCount) throw new Error('Clip đã cắt nhưng số voice bị thay đổi; app đã dừng để tránh xuất video thiếu tiếng.');
      if (attachedVisuals !== afterTimeline.length) throw new Error(`Mới cắt được ${attachedVisuals}/${afterTimeline.length} clip. Xem lỗi job và thử lại.`);
      setMessage(`Đã gắn ${attachedVisuals} clip nguồn vào storyboard, giữ nguyên ${attachedVoices} voice.`, 'success');
    } catch (error) { setMessage(`Không cắt được clip: ${error.message}`, 'error'); }
  }

  async function renderStudioReup() {
    await queueStudioProductionJob('render', 'ffmpeg_builtin', 'Dựng MP4');
  }

  async function checkStudioFidelity() {
    if (!state.studioProjectId) return setMessage('Chưa có project.', 'error');
    setMessage('AI đang đối chiếu bản kể lại với nội dung video gốc...');
    try {
      const result = await api(`/api/projects/${state.studioProjectId}/script/fidelity-check`, {method: 'POST'});
      const group = (title, items) => items.length
        ? `<p class="hint"><b>${title}</b></p><ul>${items.map((item) => `<li>${esc(item)}</li>`).join('')}</ul>`
        : '';
      const target = $('studioScriptResult');
      if (target) {
        const card = document.createElement('div');
        card.className = 'studio-result-card';
        card.innerHTML = `<h3>Soát đúng nội dung gốc · ${esc(result.score)}/10 · ${result.faithful ? 'đúng nội dung' : 'CÓ SAI LỆCH'}</h3>
          ${result.ending_verdict ? `<p class="hint"><b>Kết cục:</b> ${esc(result.ending_verdict)}</p>` : ''}
          ${group('Tên riêng KHÔNG có trong nguồn (máy đối chiếu)', result.unsourced_names || [])}
          ${group('Con số KHÔNG có trong nguồn (máy đối chiếu)', result.unsourced_numbers || [])}
          ${group('AI tự nghĩ ra (nặng nhất)', result.invented || [])}
          ${group('Bị đổi so với gốc', result.altered || [])}
          ${group('Thiếu so với gốc', result.missing || [])}`;
        target.prepend(card);
      }
      const faults = (result.invented || []).length + (result.altered || []).length
        + (result.unsourced_names || []).length + (result.unsourced_numbers || []).length;
      setMessage(result.faithful
        ? `Bản kể lại đúng nội dung gốc (${result.score}/10).`
        : `${faults} chỗ sai lệch so với nội dung gốc (${result.score}/10). Xem chi tiết phía trên kịch bản.`,
        result.faithful ? 'success' : 'error');
    } catch (error) { setMessage(`Không soát được: ${error.message}`, 'error'); }
  }

  async function translateStudioNarration() {
    if (!state.studioProjectId) return setMessage('Chưa có project.', 'error');
    const language = $('studioTranslateLanguage')?.value || 'vi';
    setMessage('AI đang dịch lời bình từng cảnh...');
    try {
      const result = await api(
        `/api/projects/${state.studioProjectId}/script/translate?target_language=${encodeURIComponent(language)}`,
        {method: 'POST'},
      );
      const leftover = (result.missing_segments || []).length;
      if (leftover) {
        setMessage(`Đã dịch ${result.translated}/${result.total} cảnh; còn ${leftover} cảnh chưa dịch được. ${(result.errors || [])[0] || ''}`, 'error');
      } else {
        setMessage(`Đã dịch xong ${result.translated}/${result.total} cảnh sang ${language}.`, 'success');
      }
      await refreshStudioStoryboard();
    } catch (error) { setMessage(`Không dịch được: ${error.message}`, 'error'); }
  }

  async function editStudioScene(shotId, segmentId) {
    const shot = findStudioShot(shotId);
    if (!shot) return setMessage('Không tìm thấy cảnh cần sửa.', 'error');
    const timelineSegment = (state.timeline || []).find((item) => Number(item.id) === Number(segmentId));
    const narration = prompt(`Lời AI đọc · Cảnh ${shot.shot_index || ''}`, timelineSegment?.voice_text || shot.narration || '');
    if (narration === null) return;
    const visualPrompt = prompt(`Mô tả hình ảnh · Cảnh ${shot.shot_index || ''}`, shot.visual_prompt || '');
    if (visualPrompt === null) return;
    const durationValue = prompt(`Thời lượng (giây) · Cảnh ${shot.shot_index || ''}`, String(shot.duration_seconds || 8));
    if (durationValue === null) return;
    const duration = Number(durationValue);
    if (!Number.isFinite(duration) || duration < 1 || duration > 3600) return setMessage('Thời lượng cần là số giây hợp lệ.', 'error');
    try {
      await api(`/api/shots/${shotId}`, {method: 'PATCH', body: JSON.stringify({narration, visual_prompt: visualPrompt, duration_seconds: duration})});
      if (segmentId) {
        await api(`/api/timeline/${segmentId}`, {method: 'PATCH', body: JSON.stringify({voice_text: narration, subtitle_text: narration, visual_prompt: visualPrompt, duration_seconds: duration, audio_path: ''})});
      }
      const bundle = await api(`/api/projects/${state.studioProjectId}`);
      state.shots = bundle.latest_shots || [];
      renderStudioStoryboard(state.shots, bundle.latest_timeline || []);
      setMessage('Đã lưu cảnh này. Giọng cũ của riêng cảnh vừa sửa đã được bỏ; quay lại bước 4 và bấm tạo giọng để tạo lại.', 'success');
    } catch (error) { setMessage(`Không lưu được cảnh: ${error.message}`, 'error'); }
  }

  async function generateStudioStoryboard() {
    if (!state.studioProjectId) return setMessage('Hãy tạo và lưu kịch bản trước khi tạo storyboard.', 'error');
    const button = $('studioGenerateStoryboardButton');
    button.disabled = true;
    setStudioProgress(10, 'AI đang chia kịch bản thành các cảnh...');
    setMessage('AI đang chia kịch bản thành storyboard...');
    try {
      const response = await api(`/api/projects/${state.studioProjectId}/shots/generate`, {method: 'POST', body: JSON.stringify({force: false})});
      const shots = response.shots || [];
      if ($('studioShotSummary')) $('studioShotSummary').textContent = `${shots.length} cảnh`;
      // Drawing with an empty timeline hid every player: scenes that already
      // had voice attached came back reading "no narration yet", which looked
      // exactly like a voiceover that had failed.
      const storyboardBundle = await api(`/api/projects/${state.studioProjectId}`).catch(() => null);
      state.timeline = storyboardBundle?.latest_timeline || state.timeline || [];
      renderStudioStoryboard(shots, state.timeline);
      if ($('studioOpenProjectButton')) $('studioOpenProjectButton').disabled = false;
      updateStudioSceneGenerationAvailability();
      setStudioProgress(100, `Storyboard ${shots.length} cảnh đã hoàn tất.`);
      setMessage(`Đã tạo storyboard gồm ${shots.length} cảnh. Bạn có thể tiếp tục chọn giọng hoặc mở chỉnh sửa chi tiết.`, 'success');
    } catch (error) { setStudioProgress(0, `Tạo storyboard thất bại: ${error.message}`, 'error'); setMessage(error.message, 'error'); }
    finally { button.disabled = false; }
  }

  async function saveStudioVoiceSettings() {
    if (!state.studioProjectId) return setMessage('Hãy tạo project từ bước kịch bản trước.', 'error');
    const button = $('studioSaveVoiceButton');
    button.disabled = true;
    try {
      setStudioProgress(20, 'Đang lưu giọng đọc và phụ đề...');
      await saveRenderSettings(state.studioProjectId);
      if ($('studioVoiceSummary')) $('studioVoiceSummary').innerHTML = `<div class="studio-check"><b>✓</b><span>Đã lưu ${esc($('studioVoiceProviderSelect').selectedOptions[0]?.textContent || '')} · ${esc($('studioVoiceModelSelect').selectedOptions[0]?.textContent || '')} · phụ đề ${esc($('studioSubtitleModelSelect').selectedOptions[0]?.textContent || '')} · ${esc($('studioPublishLanguageSelect').selectedOptions[0]?.textContent || '')}</span></div>`;
      if ($('studioGenerateTimelineButton')) $('studioGenerateTimelineButton').disabled = false;
      if ($('studioGenerateVoiceoverButton')) $('studioGenerateVoiceoverButton').disabled = false;
      setStudioProgress(100, 'Đã lưu cấu hình giọng đọc và phụ đề.');
      setMessage('Đã lưu model giọng, phụ đề và ngôn ngữ cho project.', 'success');
    } catch (error) { setStudioProgress(0, `Lưu cấu hình thất bại: ${error.message}`, 'error'); setMessage(error.message, 'error'); }
    finally { button.disabled = false; }
  }

  async function generateStudioVoiceover() {
    if (!state.studioProjectId) return setMessage('Hãy tạo project và kịch bản trước khi tạo giọng đọc.', 'error');
    // Giọng mẫu là thứ giữ cho mọi cảnh cùng một người đọc; thiếu nó thì
    // VoxCPM sinh một giọng khác cho từng đoạn. Nhưng lựa chọn đã lưu nằm ở
    // cấu hình dự án, còn ô ẩn này rỗng sau mỗi lần tải lại trang — đọc mỗi
    // ô đó là chặn oan người đã chọn giọng từ trước.
    if ($('studioVoiceProviderSelect')?.value === 'voxcpm' && !$('studioVoiceReferenceAsset')?.value) {
      let saved = null;
      try {
        const bundle = await api(`/api/projects/${state.studioProjectId}`);
        saved = bundle.render_settings?.voice_reference_asset_id || null;
      } catch (_) { /* không đọc được thì xử như chưa chọn */ }
      if (!saved) {
        return setMessage('VoxCPM cần giọng mẫu để giữ cùng một người đọc cho mọi cảnh. Hãy chọn một giọng mẫu, hoặc tải file WAV/MP3 sạch 10–20 giây ở bước này.', 'error');
      }
      if ($('studioVoiceReferenceAsset')) $('studioVoiceReferenceAsset').value = String(saved);
    }
    const button = $('studioGenerateVoiceoverButton');
    button.disabled = true;
    try {
      setStudioProgress(10, 'Đang lưu cấu hình giọng đọc...');
      await saveRenderSettings(state.studioProjectId);
      setStudioProgress(18, 'Đang chuẩn bị các cảnh và timeline từ kịch bản...');
      let rebuiltStoryboard = false;
      let shotsResult = await api(`/api/projects/${state.studioProjectId}/shots/generate`, {method: 'POST', body: JSON.stringify({force: false})});
      if (shotsResult?.stale) {
        // The Voice action means "read the current script".  Do not leave a
        // stale storyboard as an optional branch: that used to let a new TTS
        // job read old Vietnamese cards after the script had become English.
        setStudioProgress(20, 'Kịch bản mới hơn storyboard; đang đồng bộ cảnh theo kịch bản hiện tại...');
        shotsResult = await api(`/api/projects/${state.studioProjectId}/shots/generate`, {method: 'POST', body: JSON.stringify({force: true})});
        rebuiltStoryboard = true;
      }
      const timelineResult = await api(`/api/projects/${state.studioProjectId}/timeline/generate`, {method: 'POST', body: JSON.stringify({force: rebuiltStoryboard})});
      // Without force an existing timeline comes back untouched. After a
      // script rewrite that means the old scenes stay and the voice is then
      // generated from them - the button appears to work while nothing it
      // produces has anything to do with the new script.
      if (timelineResult?.stale) {
        setStudioProgress(22, 'Timeline cũ không khớp kịch bản; đang đồng bộ lời đọc hiện tại...');
        await api(`/api/projects/${state.studioProjectId}/timeline/generate`, {method: 'POST', body: JSON.stringify({force: true})});
      }
      setStudioProgress(25, 'Đang đưa toàn bộ lời dẫn vào hàng đợi tạo giọng đọc...');
      const provider = $('studioVoiceProviderSelect')?.value || 'edge_tts';
      const response = await api(`/api/projects/${state.studioProjectId}/jobs`, {method: 'POST', body: JSON.stringify({job_type: 'voiceover', provider, confirmed: true})});
      if (!response.job?.id) throw new Error('Không tạo được job giọng đọc.');
      $('studioVoiceSummary').innerHTML = `<div class="studio-check"><b>→</b><span>Đang tạo giọng đọc cho toàn bộ cảnh (job #${esc(response.job.id)}).</span></div>`;
      setMessage('Đang tạo giọng đọc cho các cảnh. Bạn có thể tiếp tục làm việc trong lúc chờ.', 'success');
      void watchStudioProductionJob(response.job.id, 'voiceover');
    } catch (error) {
      setStudioProgress(0, `Tạo giọng đọc thất bại: ${error.message}`, 'error');
      setMessage(error.message, 'error');
    } finally { button.disabled = false; }
  }

  async function generateStudioTimeline() {
    if (!state.studioProjectId) return setMessage('Hãy tạo project từ bước kịch bản trước.', 'error');
    const button = $('studioGenerateTimelineButton');
    button.disabled = true;
    setStudioProgress(10, 'Đang chuẩn bị lời đọc, thời lượng và phụ đề...');
    setMessage('Đang tạo timeline từ storyboard và lời thoại...');
    try {
      await saveRenderSettings(state.studioProjectId);
      setStudioProgress(45, 'Đã lưu cấu hình, đang ghép timeline...');
      const response = await api(`/api/projects/${state.studioProjectId}/timeline/generate`, {method: 'POST', body: JSON.stringify({force: false})});
      const count = response.timeline?.length || 0;
      if ($('studioRenderSummary')) $('studioRenderSummary').innerHTML = `<div class="studio-summary-card"><label>Timeline</label><strong>${count} đoạn · ${Number(response.total_duration_seconds || 0).toFixed(1)} giây</strong></div><div class="studio-summary-card"><label>Voice</label><strong>${esc($('studioVoiceModelSelect').selectedOptions[0]?.textContent || 'Đã chọn')}</strong></div><div class="studio-summary-card"><label>Đầu ra</label><strong>${esc($('studioOutputProfileSelect').selectedOptions[0]?.textContent || '')}</strong></div>`;
      if ($('studioQueueRenderButton')) $('studioQueueRenderButton').disabled = false;
      setStudioProgress(100, `Timeline ${count} đoạn đã hoàn tất.`);
      setMessage(`Đã tạo timeline gồm ${count} đoạn. Có thể bắt đầu dựng video.`, 'success');
    } catch (error) { setStudioProgress(0, `Tạo timeline thất bại: ${error.message}`, 'error'); setMessage(error.message, 'error'); }
    finally { button.disabled = false; }
  }

  async function runStudioSceneBatch(provider, isVeo, buttonId, variant = 'long') {
    if (!state.studioProjectId) return setMessage('Hãy tạo storyboard trước.', 'error');
    const integrationKey = provider.startsWith('gemini_') ? 'google_gemini' : 'openai_gpt';
    const providerReady = isSubscriptionProvider(provider) || Boolean(state.integrations?.find((item) => item.key === integrationKey)?.ready);
    if (!providerReady) {
      setWorkspace('settings');
      $('integrationBody')?.scrollIntoView({behavior: 'smooth', block: 'start'});
      setStudioProgress(0, 'Cần kết nối API trước khi tạo cảnh.', 'error');
      return setMessage(`Hãy nhập ${provider.startsWith('gemini_') ? 'GEMINI_API_KEY tại thẻ Google Gemini Image + Veo' : 'OPENAI_API_KEY tại thẻ OpenAI GPT + Image API'}, bấm “Lưu & bật”, sau đó quay lại Storyboard.`, 'error');
    }
    const sidecarWarning = await sidecarWarningText(provider);
    if (!confirm(`${isVeo ? 'Tạo video từ ảnh storyboard' : 'Tạo ảnh AI'} bằng ${sceneProviderLabel(provider)} cho các cảnh? ${isVeo ? 'Cảnh chưa có ảnh sẽ được tạo ảnh trước; video không bao giờ tự chuyển sang text-to-video. ' : ''}${isSubscriptionProvider(provider) ? SUBSCRIPTION_PROVIDER_SHORT[provider] : 'Việc này dùng API cloud và có thể phát sinh chi phí.'}${sidecarWarning ? `\n\n${sidecarWarning}` : ''}`)) return;
    const button = $(buttonId);
    if (button) button.disabled = true;
    setStudioProgress(5, `Đang tạo timeline trước khi gửi ${isVeo ? 'video' : 'ảnh'} sang ${sceneProviderLabel(provider)}...`);
    setMessage(`Đang tạo timeline và đưa các cảnh sang ${sceneProviderLabel(provider)}...`);
    try {
      await api(`/api/projects/${state.studioProjectId}/timeline/generate`, {
        method: 'POST', body: JSON.stringify({force: false, variant}),
      });
      setStudioProgress(15, 'Timeline đã sẵn sàng, đang xếp hàng tạo cảnh...');
      const ratio = variant === 'short' ? '720:1280' : ($('studioSceneRatioSelect')?.value || '1280:720');
      const selectedImageProvider = $('studioSceneImageProviderSelect')?.value || 'flow_image';
      const referenceImageProvider = selectedImageProvider === 'auto_parallel' ? 'flow_image' : selectedImageProvider;
      const result = await api(`/api/projects/${state.studioProjectId}/scene-jobs/batch`, {
        method: 'POST', body: JSON.stringify({
          ...batchProviderPayload(provider, isVeo), duration_seconds: isVeo ? 8 : 5, ratio,
          requires_reference_image: isVeo, reference_image_provider: referenceImageProvider,
          variant, confirmed: true,
        }),
      });
      const jobs = result.jobs || [];
      if (!jobs.length) {
        setStudioProgress(100, 'Các cảnh đã có hình ảnh.');
        setMessage('Các cảnh đã có visual hoặc chưa có prompt. Kiểm tra lại ngay trong Storyboard.', 'success');
        return;
      }
      state.studioSceneProgress = { total: jobs.length, finished: new Set(), failed: 0, providerLabel: sceneProviderLabel(provider) };
      setStudioProgress(15, `Đã xếp hàng 0/${jobs.length} cảnh AI...`);
      setMessage(`Đã gửi ${jobs.length} cảnh sang ${sceneProviderLabel(provider)}. Kết quả sẽ tự hiện trong storyboard.`, 'success');
      jobs.forEach((job) => { if (job.id) void watchStudioSceneGenerationJob(job.id, variant); });
    } catch (error) { setStudioProgress(0, `Tạo ${isVeo ? 'video' : 'ảnh'} AI thất bại: ${error.message}`, 'error'); setMessage(`Không tạo được ${isVeo ? 'video' : 'ảnh'} AI: ${error.message}`, 'error'); }
    finally { updateStudioSceneGenerationAvailability(); }
  }

  async function generateStudioSceneImagesBatch() {
    const provider = $('studioSceneImageProviderSelect')?.value || 'gemini_image';
    await runStudioSceneBatch(provider, false, 'studioGenerateImagesButton');
  }

  async function generateStudioSceneVideosBatch() {
    const provider = $('studioSceneVideoProviderSelect')?.value || 'gflow_cli';
    await runStudioSceneBatch(provider, true, 'studioGenerateVideosButton');
  }

  async function watchStudioSceneGenerationJob(jobId, variant = 'long') {
    for (let attempt = 0; attempt < 300; attempt += 1) {
      try {
        const job = await api(`/api/scene-jobs/${jobId}`);
        if (job.status === 'completed' || job.status === 'error') {
          const progress = state.studioSceneProgress;
          if (progress && !progress.finished.has(jobId)) {
            progress.finished.add(jobId);
            if (job.status === 'error') progress.failed += 1;
            const completed = progress.finished.size;
            const percent = Math.round(15 + (85 * completed / progress.total));
            const outcome = progress.failed ? ` · ${progress.failed} cảnh lỗi` : '';
            setStudioProgress(percent, `Đã xử lý ${completed}/${progress.total} cảnh ${progress.providerLabel || sceneProviderLabel(job.provider)}${outcome}.`, progress.failed ? 'error' : '');
          }
          if (variant === 'short') {
            await loadShortLane();
          } else {
            const bundle = await api(`/api/projects/${state.studioProjectId}`);
            state.narrationSource = bundle.narration_source || state.narrationSource;
      renderStudioStoryboard(bundle.latest_shots || [], bundle.latest_timeline || []);
          }
          if (job.status === 'error') setMessage(`Một cảnh AI thất bại: ${job.error || 'Lỗi không xác định'}`, 'error');
          return job;
        }
      } catch (error) { setStudioProgress(0, `Không đọc được trạng thái ảnh AI: ${error.message}`, 'error'); setMessage(`Không đọc được trạng thái cảnh AI: ${error.message}`, 'error'); return null; }
      await new Promise((resolve) => setTimeout(resolve, 3000));
    }
    setMessage('Cảnh AI đang chạy lâu; bạn có thể làm mới trang để xem video đã hoàn tất.', 'error');
    return null;
  }

  async function queueStudioRender() {
    if (!state.studioProjectId) return setMessage('Chưa có project để dựng video.', 'error');
    syncStudioRenderProvider();
    if (state.productionQueue?.gpu_only && !state.productionQueue?.nvenc_available) {
      return setMessage('Chế độ GPU-only đang bật nhưng không tìm thấy NVIDIA NVENC. Hãy kiểm tra driver/GPU trước khi dựng.', 'error');
    }
    if (!confirm('Bắt đầu dựng video hoàn chỉnh bằng engine đã chọn?')) return;
    const button = $('studioQueueRenderButton');
    button.disabled = true;
    setStudioProgress(5, 'Đang kiểm tra cảnh, giọng đọc và thiết lập dựng...');
    setMessage('Đang đưa video vào hàng đợi dựng...');
    try {
      const bundle = await api(`/api/projects/${state.studioProjectId}`);
      const timeline = bundle.latest_timeline || [];
      const missingVisuals = timeline.filter((segment) => !String(segment.visual_path || '').trim());
      const missingAudio = timeline.filter((segment) => !String(segment.audio_path || '').trim());
      const draftVisuals = timeline.filter((segment) => String(segment.visual_path || '').replaceAll('\\', '/').includes('director_draft_visuals'));
      if (!timeline.length) {
        setStudioStep(6);
        throw new Error('Chưa có timeline. Hãy bấm “Tạo timeline” trước khi dựng video.');
      }
      if (missingVisuals.length) {
        setStudioStep(4);
        throw new Error(`Còn ${missingVisuals.length}/${timeline.length} cảnh chưa có hình hoặc video thật. Hãy quay lại Storyboard, tạo ảnh/video AI cho các cảnh hoặc gắn asset vào timeline rồi mới render.`);
      }
      if (draftVisuals.length) {
        setStudioStep(4);
        throw new Error(`Còn ${draftVisuals.length} visual draft nội bộ. Hãy thay bằng video AI hoặc ảnh/video thật trong storyboard trước khi render bản xuất bản.`);
      }
      if (missingAudio.length) {
        setStudioStep(5);
        throw new Error(`Còn ${missingAudio.length}/${timeline.length} cảnh chưa có giọng đọc. Hãy bấm “Tạo giọng đọc cho các cảnh” trước khi dựng video.`);
      }
      await saveRenderSettings(state.studioProjectId);
      setStudioProgress(20, 'Đã kiểm tra xong, đang đưa video vào hàng đợi dựng...');
      const provider = state.productionQueue?.gpu_only ? 'ffmpeg_builtin' : ($('studioRenderProviderSelect').value || 'ffmpeg_builtin');
      const response = await api(`/api/projects/${state.studioProjectId}/jobs`, {method: 'POST', body: JSON.stringify({job_type: 'render', provider, confirmed: true})});
      setStudioStep(7);
      setStudioProgress(25, 'Video đã vào hàng đợi dựng.');
      $('studioFinalResult').innerHTML = `<div class="studio-result-card"><h3>Đã bắt đầu dựng video</h3><p>Job #${esc(response.job?.id || '—')} đang chạy. Bạn có thể tiếp tục làm việc, app sẽ cập nhật trạng thái.</p></div>`;
      setMessage('Đã đưa video vào hàng đợi dựng.', 'success');
      if (response.job?.id) void watchStudioProductionJob(response.job.id, 'render');
    } catch (error) { setStudioProgress(0, `Dựng video thất bại: ${error.message}`, 'error'); setMessage(error.message, 'error'); }
    finally { button.disabled = false; }
  }

  async function watchStudioProductionJob(jobId, jobType) {
    for (let attempt = 0; attempt < 1200; attempt += 1) {
      try {
        const job = await api(`/api/jobs/${jobId}`);
        if (job.status === 'completed') {
          if (jobType === 'voiceover') {
            const bundle = await refreshStudioStoryboard();
            const voiceTimeline = bundle?.latest_timeline || [];
            const missingAudio = voiceTimeline.filter((segment) => !String(segment.audio_path || '').trim());
            if (missingAudio.length) {
              setStudioProgress(0, `Tạo voice xong nhưng chưa gắn được ${missingAudio.length}/${voiceTimeline.length} cảnh.`, 'error');
              setMessage(`Voice job hoàn tất nhưng ${missingAudio.length} cảnh chưa có audio trong storyboard. Không chuyển sang cắt cảnh; hãy thử tạo lại voice.`, 'error');
              return job;
            }
            const actualSeconds = voiceTimeline.reduce((total, segment) => total + Number(segment.duration_seconds || 0), 0);
            const targetSeconds = Number(bundle.writer_content?.result?.target_duration_seconds || 0);
            const actualLabel = formatStudioDuration(actualSeconds);
            const targetLabel = targetSeconds ? ` · mục tiêu ${formatStudioDuration(targetSeconds)}` : '';
            const deviation = targetSeconds ? Math.abs(actualSeconds - targetSeconds) / targetSeconds : 0;
            const durationNote = targetSeconds && deviation > 0.05
              ? ` Thời lượng voice hiện là ${actualLabel}${targetLabel}; lệch ${Math.round(deviation * 100)}%. Hãy quay lại Kịch bản để viết dài hơn/ngắn hơn trước khi dựng.`
              : ` Thời lượng voice: ${actualLabel}${targetLabel}.`;
            if ($('studioVoiceSummary')) $('studioVoiceSummary').innerHTML = `<div class="studio-check"><b>✓</b><span>Đã tạo giọng đọc cho toàn bộ cảnh.${esc(durationNote)}</span></div>`;
            setStudioStep(5);
            setStudioProgress(100, `Đã tạo xong giọng đọc · ${actualLabel}.`);
            setMessage(`Đã tạo xong giọng đọc. Bạn có thể nghe và sửa từng cảnh trong Storyboard.${durationNote}`, targetSeconds && deviation > 0.05 ? 'error' : 'success');
            return job;
          }
          const finalUrl = `/api/projects/${state.studioProjectId}/final-video`;
          $('studioFinalResult').innerHTML = `<div class="studio-result-card"><h3>✓ Video đã dựng xong</h3><p>Job #${esc(jobId)} đã hoàn tất. Bạn có thể xem và tải file MP4 ngay tại đây.</p><video controls preload="metadata" style="width:100%;max-width:900px;margin-top:10px;border-radius:10px" src="${finalUrl}"></video><div class="studio-actions" style="margin-top:10px"><a class="btn primary" href="${finalUrl}" target="_blank" rel="noreferrer">Mở / tải MP4</a><button class="btn ghost" onclick="setStudioStep(6)">Quay lại xưởng dựng</button></div></div>`;
          setStudioProgress(100, 'Video đã dựng xong.');
          setMessage('Video đã dựng xong.', 'success');
          return job;
        }
        if (job.status === 'error') {
          $('studioFinalResult').innerHTML = `<div class="studio-result-card"><h3>Dựng video thất bại</h3><p>${esc(job.error || 'Lỗi không xác định')}</p></div>`;
          setStudioProgress(0, `${jobType} thất bại: ${job.error || 'Lỗi không xác định'}`, 'error');
          setMessage(`${jobType} thất bại.`, 'error');
          return job;
        }
        if (attempt % 4 === 0) {
          const percent = job.status === 'queued' ? 25 : 60;
          setStudioProgress(percent, `${jobType} đang xử lý (${job.status})...`);
          setMessage(`${jobType} đang xử lý... (${job.status})`);
        }
      } catch (error) { setMessage(`Không đọc được trạng thái render: ${error.message}`, 'error'); return null; }
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
    setMessage('Render đang chạy lâu; mở project để xem trạng thái chi tiết.', 'error');
    return null;
  }

  async function writeStudioScript() {
    if (!state.studioVideoId) return setMessage('Hãy chọn video trước khi viết kịch bản.', 'error');
    const provider = $('studioWriterProviderSelect').value || 'codex_cli';
    const button = $('studioWriteButton');
    button.disabled = true;
    // WF Lồng tiếng kể lại đúng nội dung nguồn, nên nó không đi qua chế độ
    // sáng tác lại - chế độ đó được viết để ĐỔI nhân vật và tình tiết.
    // Chế độ viết thuộc về định nghĩa WF, không suy ra bằng so chuỗi ở đây.
    const flow = currentWorkflow();
    const retelling = flow.script_mode === 'faithful_retell';
    setStudioProgress(10, retelling
      ? 'AI đang viết lại cách dẫn chuyện, giữ nguyên nội dung gốc...'
      : 'AI đang viết câu chuyện mới từ ý tưởng của bạn...');
    setMessage(retelling
      ? 'Đang kể lại đúng nội dung video gốc bằng một cách dẫn khác...'
      : 'Đang viết một câu chuyện mới và blueprint cảnh AI...');
    try {
      const prompt = $('studioScriptInstructionInput')?.value || $('studioCreativeDirectionInput')?.value || '';
      const durationInput = $('studioTargetDurationSeconds')?.value.trim() || '';
      const localDuration = parseStudioDuration(durationInput);
      if (durationInput && !localDuration) return setMessage('Không hiểu thời lượng. Nhập ví dụ: 00:12:00, 12:00, 12 phút hoặc 720 giây.', 'error');
      if (localDuration && (localDuration < 30 || localDuration > 1800)) return setMessage('Thời lượng cần nằm trong khoảng 00:00:30 đến 00:30:00.', 'error');
      const response = await api(`/api/videos/${encodeURIComponent(state.studioVideoId)}/writer`, {method: 'POST', body: JSON.stringify({provider, managed_channel_id: $('studioManagedChannelSelect')?.value ? Number($('studioManagedChannelSelect').value) : null, creative_direction: prompt, remake_mode: retelling ? flow.script_mode : ($('studioRemakeModeSelect')?.value || flow.script_mode || 'new_angle_same_topic'), output_language: $('studioScriptLanguage')?.value || 'vi', target_duration_seconds: null, target_duration_text: durationInput, use_web_research: flow.uses_web_research === false ? false : $('studioFolkloreResearchEnabled')?.checked !== false})});
      state.studioWriter = response;
      // The writer is told how long the video should be and its output is
      // already measured against that, but the answer went nowhere. A script
      // half the length of its source then quietly became a video half the
      // length, discovered only after a voiceover and a render.
      reportScriptLengthWarnings(response);
      setStudioProgress(60, 'Đã có câu chuyện mới, đang tạo dự án...');
      const projectResponse = await api(`/api/videos/${encodeURIComponent(state.studioVideoId)}/project`, {method: 'POST', body: JSON.stringify({managed_channel_id: $('studioManagedChannelSelect')?.value ? Number($('studioManagedChannelSelect').value) : null})});
      state.studioProjectId = projectResponse.project?.id || projectResponse.id || null;
      if (state.studioProjectId) {
        await api(`/api/projects/${state.studioProjectId}/workflow`, {
          method: 'PATCH', body: JSON.stringify({workflow: state.studioWorkflow}),
        }).catch(() => {});
      }
      const createStandaloneShort = Boolean($('studioCreateStandaloneShort')?.checked);
      const shortSeconds = Number($('studioInitialShortSeconds')?.value || 45);
      setStudioProgress(80, createStandaloneShort ? 'Đang tạo kịch bản dài và Short riêng từ cùng brief...' : 'Đang tạo kịch bản dài...');
      const scriptResponse = await api(`/api/projects/${state.studioProjectId}/script/draft`, {
        method: 'POST',
        body: JSON.stringify({
          create_standalone_short: createStandaloneShort,
          short_seconds: shortSeconds,
          short_direction: prompt,
        }),
      });
      renderStudioScript(scriptResponse.script, response);
      if (scriptResponse.short) renderShortScriptState(scriptResponse.short);
      else if (scriptResponse.short_error) setMessage(`Kịch bản dài đã tạo, nhưng Short riêng chưa tạo được: ${scriptResponse.short_error}`, 'error');
      setStudioStep(3);
      setStudioProgress(100, scriptResponse.short ? 'Đã tạo kịch bản dài và Short riêng.' : 'Kịch bản dài đã tạo xong.');
      if (scriptResponse.short) {
        setMessage(`Đã tạo kịch bản dài và Short riêng ${scriptResponse.short.estimated_seconds || shortSeconds}s từ cùng brief.`, 'success');
      } else if (!scriptResponse.short_error) {
        setMessage('Đã tạo kịch bản dài. Bạn có thể bật tạo Short rồi viết lại kịch bản tại bước này nếu cần.', 'success');
      }
      void Promise.all([loadSummary(), loadVideos(), loadProjects()]);
    } catch (error) { setStudioProgress(0, `Viết kịch bản thất bại: ${error.message}`, 'error'); setMessage(error.message, 'error'); }
    finally { button.disabled = false; }
  }

  function parseStudioDuration(value) {
    const text = String(value || '').trim().toLowerCase();
    if (!text) return null;
    if (/^\d+$/.test(text)) return Number(text);
    const clock = text.match(/^(\d{1,2}):([0-5]\d)(?::([0-5]\d))?$/);
    if (clock) return clock[3] === undefined ? Number(clock[1]) * 60 + Number(clock[2]) : Number(clock[1]) * 3600 + Number(clock[2]) * 60 + Number(clock[3]);
    const hour = text.match(/\b(\d{1,2})\s*(?:giờ|gio|hours?|hrs?|h)/i);
    const minute = text.match(/\b(\d{1,3})\s*(?:phút|phut|minutes?|mins?|m)/i);
    const second = text.match(/\b(\d{1,4})\s*(?:giây|giay|seconds?|secs?|s)/i);
    if (hour || minute || second) return (hour ? Number(hour[1]) * 3600 : 0) + (minute ? Number(minute[1]) * 60 : 0) + (second ? Number(second[1]) : 0);
    return null;
  }

  function formatStudioDuration(totalSeconds) {
    const total = Math.round(Number(totalSeconds) || 0);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = total % 60;
    return hours ? `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}` : `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  }

  function updateStudioDurationHint() {
    const input = $('studioTargetDurationSeconds');
    const hint = $('studioDurationHint');
    if (!input || !hint) return;
    const seconds = parseStudioDuration(input.value);
    if (!input.value.trim()) { hint.textContent = 'Nhập giờ : phút : giây, phút : giây, hoặc chữ. Ví dụ: 01:12:30 · 12:00 · 12 phút 30 giây.'; return; }
    if (!seconds) { hint.textContent = 'Chưa hiểu định dạng. Ví dụ hợp lệ: 00:12:00 · 12:00 · 12 phút · 720 giây.'; return; }
    hint.textContent = seconds >= 30 && seconds <= 1800 ? `AI sẽ tạo khoảng ${formatStudioDuration(seconds)} (${seconds} giây).` : 'Thời lượng cần từ 00:00:30 đến 00:30:00.';
  }

  function inferStudioDurationFromPrompt() {
    const input = $('studioTargetDurationSeconds');
    const prompt = $('studioScriptInstructionInput')?.value || '';
    if (!input || input.value.trim()) return;
    const minutes = prompt.match(/\b(\d{1,2})\s*(?:phút|phut|mins?|minutes?)\b/i);
    const seconds = prompt.match(/\b(\d{2,4})\s*(?:giây|giay|secs?|seconds?)\b/i);
    const clock = prompt.match(/\b(\d{1,2})\s*:\s*(\d{2})\b/);
    const inferred = minutes ? Number(minutes[1]) * 60 : seconds ? Number(seconds[1]) : clock ? Number(clock[1]) * 60 + Number(clock[2]) : 0;
    if (inferred >= 30 && inferred <= 1800) { input.value = formatStudioDuration(inferred); updateStudioDurationHint(); }
  }

  function studioScriptPayload(status = null) {
    const payload = {
      script_title: $('studioScriptTitleInput')?.value || '',
      hook: $('studioScriptHookInput')?.value || '',
      intro: $('studioScriptIntroInput')?.value || '',
      main_content: $('studioScriptMainInput')?.value || '',
      cta: $('studioScriptCtaInput')?.value || '',
    };
    if (status) payload.status = status;
    return payload;
  }

  async function saveStudioScript(status = null) {
    if (!state.scriptId) return;
    try {
      const response = await api(`/api/scripts/${state.scriptId}`, {method: 'PATCH', body: JSON.stringify(studioScriptPayload(status))});
      renderStudioScript(response.script, state.studioWriter);
      setMessage(`Đã lưu kịch bản v${response.script.version}.`, 'success');
      await loadProjects();
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function aiReviewStudioScript() {
    if (!state.studioProjectId) return setMessage('Chưa có project.', 'error');
    setMessage('AI đang đọc lại kịch bản...');
    try {
      const result = await api(`/api/projects/${state.studioProjectId}/script/review`, {method: 'POST'});
      const review = result.review || {};
      const issues = (review.issues || []).map((item) => `<li>${esc(item)}</li>`).join('');
      const suggestions = (review.suggestions || []).map((item) => `<li>${esc(item)}</li>`).join('');
      const target = $('studioScriptResult');
      if (target) {
        const card = document.createElement('div');
        card.className = 'studio-result-card';
        card.innerHTML = `<h3>AI duyệt kịch bản · ${esc(review.score ?? '—')}/10${review.should_rewrite ? ' · nên viết lại' : ''}</h3>
          ${review.hook_verdict ? `<p class="hint"><b>Hook:</b> ${esc(review.hook_verdict)}</p>` : ''}
          ${issues ? `<p class="hint"><b>Vấn đề</b></p><ul>${issues}</ul>` : ''}
          ${suggestions ? `<p class="hint"><b>Đề xuất</b></p><ul>${suggestions}</ul>` : ''}`;
        target.prepend(card);
      }
      setMessage(`AI chấm ${review.score ?? '—'}/10. Kịch bản chuyển sang chờ duyệt.`, 'success');
      await loadProjects();
    } catch (error) { setMessage(`Không duyệt được kịch bản: ${error.message}`, 'error'); }
  }

  async function reviewStudioVoiceover() {
    if (!state.studioProjectId) return setMessage('Chưa có project.', 'error');
    const button = $('studioReviewVoiceButton');
    if (button) button.disabled = true;
    setMessage('AI đang nghe lại từng đoạn giọng đọc và đối chiếu với lời thoại...');
    try {
      const result = await api(`/api/projects/${state.studioProjectId}/voice/review`, {method: 'POST'});
      const bad = (result.segments || []).filter((item) => item.status === 'ok' && !item.matches);
      if (!bad.length) {
        setMessage(`Đã nghe lại ${result.checked} đoạn, không đoạn nào đọc sai lệch ý.`, 'success');
      } else {
        const detail = bad.map((item) => `cảnh ${item.segment_index} (${item.score}/10)`).join(', ');
        setMessage(`${bad.length}/${result.checked} đoạn đọc lệch so với kịch bản: ${detail}. Xem chi tiết trong storyboard.`, 'error');
      }
    } catch (error) { setMessage(`Không kiểm tra được giọng đọc: ${error.message}`, 'error'); }
    finally { if (button) button.disabled = false; }
  }

  async function reviewStudioScript() { await saveStudioScript('review'); }

  async function approveStudioScript() {
    if (!state.scriptId || !confirm('Duyệt kịch bản này để chuyển sang bước dựng?')) return;
    try {
      const response = await api(`/api/scripts/${state.scriptId}/approve`, {method: 'POST'});
      renderStudioScript(response.script, state.studioWriter);
      setMessage('Đã duyệt kịch bản.', 'success');
    } catch (error) { setMessage(error.message, 'error'); }
  }

  async function chatStudioScript() {
    if (!state.studioProjectId) return setMessage('Chưa có project để chỉnh sửa kịch bản.', 'error');
    const message = $('studioChatMessage')?.value.trim();
    if (!message) return setMessage('Hãy nhập yêu cầu chỉnh sửa cho AI.', 'error');
    const button = $('studioChatButton');
    button.disabled = true;
    setMessage('AI đang chỉnh sửa kịch bản theo yêu cầu...');
    try {
      const response = await api(`/api/projects/${state.studioProjectId}/script/chat`, {method: 'POST', body: JSON.stringify({provider: $('studioChatProviderSelect').value || 'codex_cli', message})});
      renderStudioScript(response.script, state.studioWriter);
      $('studioChatMessage').value = '';
      setMessage(`Đã tạo phiên bản kịch bản mới bằng ${response.provider}.`, 'success');
      await loadProjects();
    } catch (error) { setMessage(error.message, 'error'); }
    finally { button.disabled = false; }
  }

  async function resumeStudioProject(projectId) {
    let project = state.projects.find((item) => Number(item.id) === Number(projectId));
    if (!project) {
      await loadProjects();
      project = state.projects.find((item) => Number(item.id) === Number(projectId));
    }
    if (!project) return setMessage('Không tìm thấy dự án cần tiếp tục.', 'error');
    if (!state.videoCatalog.some((item) => item.youtube_video_id === project.youtube_video_id)) await loadVideos();
    if (!state.videoCatalog.some((item) => item.youtube_video_id === project.youtube_video_id)) return setMessage('Không tải được video nguồn của dự án.', 'error');
    setWorkspace('dashboard');
    state.studioSourceChannelId = state.channels.some((item) => item.youtube_channel_id === project.youtube_channel_id)
      ? (project.youtube_channel_id || '') : '';
    populateStudioSourceChannelSelect();
    populateStudioVideoSelect();
    $('studioVideoSelect').value = project.youtube_video_id;
    await selectStudioVideo(project.id);
    setMessage(`Đã quay lại luồng tạo video của dự án “${project.title || project.source_title || project.youtube_video_id}”.`, 'success');
    $('studioWizard')?.scrollIntoView({behavior: 'smooth', block: 'start'});
  }

  async function openStudioProject() {
    if (!state.studioProjectId) return setMessage('Hãy viết và lưu kịch bản trước.', 'error');
    await saveStudioScript();
    if ($('studioManagedChannelSelect')?.value) {
      await api(`/api/projects/${state.studioProjectId}`, {method: 'PATCH', body: JSON.stringify({managed_channel_id: Number($('studioManagedChannelSelect').value)})});
    }
    setStudioStep(6);
    setMessage('Xưởng dựng đã nằm ở bước 6 của luồng tạo video.', 'success');
  }

  function populateChannelSelect(select) {
    const selected = select.value;
    select.innerHTML = '<option value="">Tất cả kênh</option>' + state.channels.map((channel) => `<option value="${esc(channel.youtube_channel_id)}">${esc(channel.title || channel.youtube_channel_id)}</option>`).join('');
    if (state.channels.some((channel) => channel.youtube_channel_id === selected)) select.value = selected;
  }

  function channelGroupName(channel) {
    return String(channel?.group_name || '').trim() || 'Chưa gắn nhãn';
  }
