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

  // Tải file lên làm nguồn nằm trong tab NGUỒN (library.js, importSourceFiles).

  // Nút này và AI điều phối chạy CÙNG một bước: POST /api/projects/{id}/steps/analyze.
  // Bước đó tự lấy transcript, khung hình, nội dung bài hay trang sản phẩm tuỳ loại nguồn.
  async function analyzeStudioVideo() {
    if (!state.studioVideoId && !state.studioProjectId) return setMessage('Hãy chọn một nguồn trước.', 'error');
    // Nút "Phân tích lại" trong thông báo không bị khoá như nút chính.
    if (state.studioAnalyzing) return;
    const provider = $('studioAnalysisProviderSelect')?.value || 'auto';
    state.studioAnalyzing = true;
    state.studioAnalyzeError = '';
    renderStudioVideoPreview();
    setStudioProgress(10, 'Đang phân tích nguồn...');
    let projectId = state.studioProjectId;
    let following = false;
    const current = () => Number(state.studioProjectId) === Number(projectId);
    try {
      if (!projectId) {
        const created = await api(`/api/videos/${encodeURIComponent(state.studioVideoId)}/project`, {
          method: 'POST', body: JSON.stringify({managed_channel_id: null}),
        });
        projectId = state.studioProjectId = created.project?.id || created.id || null;
      }
      if (!projectId) throw new Error('Không tạo được dự án cho nguồn này.');
      const options = provider && provider !== 'auto' ? {provider} : {};
      state.studioAnalyzeRequest = projectId;
      const response = await api(`/api/projects/${projectId}/steps/analyze`, {
        method: 'POST', body: JSON.stringify({options}),
      });
      // Người dùng đã sang nguồn khác: kết quả đã lưu trên server, mở lại là thấy.
      if (!current()) return;
      const brief = response.result?.result || {};
      const analysis = {status: 'completed', provider: brief.provider || '', result: brief, created_at: new Date().toISOString()};
      state.studioAnalysis = analysis;
      state.studioReference = analysis;
      renderStudioAnalysis(analysis);
      setStudioProgress(100, 'Đã phân tích.');
      setMessage('Đã phân tích nguồn.', 'success');
      void Promise.all([loadSummary(), loadVideos(), loadProjects()]);
    } catch (error) {
      state.studioAnalyzeRequest = null;
      // Request kết thúc nhưng lượt phân tích vẫn chạy (mất kết nối, hoặc tab
      // khác / AI điều phối đã chạy trước và server từ chối lượt thứ hai):
      // theo dõi lượt server đang có.
      if (!current()) return;
      if (projectId && await followStudioAnalyze(projectId)) { following = true; return; }
      state.studioAnalyzeError = studioAnalyzeErrorText(error);
      setStudioProgress(0, 'Không phân tích được.', 'error');
      setMessage(state.studioAnalyzeError, 'error');
    } finally {
      state.studioAnalyzeRequest = null;
      if (!following && current()) {
        state.studioAnalyzing = false;
        renderStudioVideoPreview();
      }
    }
  }

  // Phân tích chạy vài phút trên server. Tải lại trang chỉ bỏ request, không
  // bỏ việc, nên "đang chạy" đọc từ server (GET /api/projects/{id}/steps),
  // không giữ trong bộ nhớ trang. Chỉ hỏi lại khi có lượt đang chạy mà trang
  // này không còn chờ request của nó; tab đang ẩn hỏi thưa hơn và hỏi ngay
  // khi được mở lại.
  const STUDIO_ANALYZE_POLL_MS = 5000;
  const STUDIO_ANALYZE_HIDDEN_POLL_MS = 30000;

  document.addEventListener('visibilitychange', () => {
    const watch = state.studioAnalyzeWatch;
    if (document.hidden || !watch?.tick) return;
    clearTimeout(watch.timer);
    void watch.tick();
  });

  async function studioAnalyzeRun(projectId) {
    const body = await api(`/api/projects/${projectId}/steps`);
    return (body.steps || []).find((row) => row.key === 'analyze') || null;
  }

  function stopStudioAnalyzeWatch() {
    clearTimeout(state.studioAnalyzeWatch?.timer);
    state.studioAnalyzeWatch = null;
  }

  // true khi server đang phân tích dự án này; khi đó trang theo dõi tới lúc xong.
  async function followStudioAnalyze(projectId) {
    if (!projectId) return false;
    let row = null;
    try { row = await studioAnalyzeRun(projectId); } catch (_) { return false; }
    if (Number(state.studioProjectId) !== Number(projectId) || row?.state !== 'running') return false;
    state.studioAnalyzing = true;
    state.studioAnalyzeError = '';
    setStudioProgress(10, 'Đang phân tích nguồn...');
    renderStudioVideoPreview();
    // Request của chính trang này còn mở: câu trả lời của nó sẽ báo kết quả.
    if (Number(state.studioAnalyzeRequest) === Number(projectId)) return true;
    if (Number(state.studioAnalyzeWatch?.projectId) === Number(projectId)) return true;
    stopStudioAnalyzeWatch();
    const watch = {projectId, timer: null, tick: null};
    state.studioAnalyzeWatch = watch;
    const later = () => setTimeout(watch.tick, document.hidden ? STUDIO_ANALYZE_HIDDEN_POLL_MS : STUDIO_ANALYZE_POLL_MS);
    watch.tick = async () => {
      // Một lượt hỏi mỗi lúc: mở lại tab giữa chừng không sinh chuỗi hỏi thứ hai.
      if (state.studioAnalyzeWatch !== watch || watch.busy) return;
      watch.busy = true;
      let now = null;
      try { now = await studioAnalyzeRun(projectId); } catch (_) { /* app tạm không trả lời: hỏi lại sau */ }
      watch.busy = false;
      if (state.studioAnalyzeWatch !== watch) return;
      if (!now || now.state === 'running') {
        watch.timer = later();
        return;
      }
      state.studioAnalyzeWatch = null;
      await finishStudioAnalyze(projectId, now.last_run);
    };
    watch.timer = later();
    return true;
  }

  async function finishStudioAnalyze(projectId, last) {
    if (Number(state.studioProjectId) !== Number(projectId)) return;
    if (last?.status === 'failed') {
      state.studioAnalyzeError = studioAnalyzeErrorText({status: last.status_code, message: last.error});
      setStudioProgress(0, 'Không phân tích được.', 'error');
    } else {
      try {
        const bundle = await api(`/api/projects/${projectId}`);
        const analysis = bundle.reference_analysis || bundle.metadata_analysis;
        if (analysis?.result && Number(state.studioProjectId) === Number(projectId)) {
          state.studioAnalysis = analysis;
          state.studioReference = bundle.reference_analysis || null;
          state.studioAnalyzing = false;
          renderStudioAnalysis(analysis);
          setStudioProgress(100, 'Đã phân tích.');
        }
      } catch (error) {
        state.studioAnalyzeError = studioAnalyzeErrorText(error);
      }
      void Promise.all([loadSummary(), loadVideos(), loadProjects()]);
    }
    if (Number(state.studioProjectId) !== Number(projectId)) return;
    state.studioAnalyzing = false;
    renderStudioVideoPreview();
  }

  // Lỗi viết lại bằng lời thường: không mã HTTP, không tên phiên/extension,
  // không mã task, không tham số kỹ thuật.
  function studioPlainText(text) {
    return String(text || '')
      .replace(/HTTP\s*\d{3}\s*:?\s*/gi, '')
      .replace(/\((?:task|agt_)[^)]*\)/gi, '')
      .replace(/\b(?:agt_[0-9a-f]+|extension:[\w.-]+|profile:[\w.-]+|session:[\w:.-]+|options\.[\w.]+)\b/gi, '')
      .replace(/\b(?:UNAVAILABLE|NEED_LOGIN|NEED_HUMAN_VERIFY|FAILED)\b:?\s*/g, '')
      .replace(/\s{2,}/g, ' ')
      .trim();
  }

  function studioAnalyzeErrorText(error) {
    const status = Number(error?.status || 0);
    if (status === 400) return 'AI đã chọn không phân tích được loại nguồn này. Chọn AI khác trong Nâng cao.';
    if (status === 502) return 'AI phân tích chưa chạy được lúc này. Thử lại sau, hoặc chọn AI khác trong Nâng cao.';
    if (status === 422) return 'Kết quả chưa khớp với nguồn. Bấm Phân tích lại.';
    if (status === 424) return 'Chưa đọc được trang nguồn. Kiểm tra kết nối trong Công cụ & kết nối.';
    if (!status && /fetch|network/i.test(String(error?.message || ''))) return 'Không kết nối được app. Hãy mở lại app rồi thử lại.';
    return studioPlainText(error?.message).slice(0, 200) || 'Có lỗi khi phân tích. Thử lại sau.';
  }

  // ---- Kết quả phân tích ngay trong Bước 1, dựng theo loại nguồn ----

  function studioCard(title, body, extra = '') {
    return body ? `<div class="studio-result-card ${extra}"><h3>${esc(title)}</h3>${body}</div>` : '';
  }

  // The AI's own prose sometimes repeats how the page was read ("qua
  // session:extension:coccoc", a raw ISO time); the reader needs neither.
  function studioProse(text) {
    return String(text || '')
      .replace(/\s*\([^()]*\b(?:session|extension|profile):[^()]*\)/gi, '')
      .replace(/\b(?:session|extension|profile):[\w:.-]+/gi, '')
      .replace(/\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?/g, (stamp) => {
        const at = new Date(stamp);
        return Number.isNaN(at.getTime()) ? stamp
          : at.toLocaleString('vi-VN', {hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit', year: 'numeric'});
      })
      .replace(/[ \t]{2,}/g, ' ')
      .trim();
  }

  function studioLongText(text, limit = 420) {
    const value = studioProse(text);
    if (!value) return '';
    if (value.length <= limit) return `<p>${esc(value)}</p>`;
    return `<p>${esc(value.slice(0, limit).replace(/\s+\S*$/, ''))}…</p>
      <details class="studio-more"><summary>Xem toàn bộ</summary><p>${esc(value)}</p></details>`;
  }

  function studioList(items, {ordered = true, limit = 6} = {}) {
    const rows = (items || []).map((item) => studioProse(item)).filter(Boolean);
    if (!rows.length) return '';
    const tag = ordered ? 'ol' : 'ul';
    const head = rows.slice(0, limit).map((item) => `<li>${esc(item)}</li>`).join('');
    const rest = rows.slice(limit);
    return `<${tag} class="studio-result-list">${head}</${tag}>`
      + (rest.length ? `<details class="studio-more"><summary>Xem thêm ${rest.length}</summary><${tag} class="studio-result-list" start="${limit + 1}">${rest.map((item) => `<li>${esc(item)}</li>`).join('')}</${tag}></details>` : '');
  }

  function studioChips(items) {
    const rows = (items || []).map((item) => String(item?.keyword || item || '').trim()).filter(Boolean);
    return rows.length ? `<div class="keyword-list">${rows.slice(0, 16).map((item) => `<span class="keyword">${esc(item)}</span>`).join('')}</div>` : '';
  }

  function studioUncertain(result) {
    const rows = (result.limitations || []).map((item) => studioPlainText(item)).filter(Boolean);
    return rows.length
      ? `<details class="studio-result-card studio-more-card"><summary>Chỗ chưa chắc chắn (${rows.length})</summary>${studioList(rows, {ordered: false, limit: 50})}</details>`
      : '';
  }

  function studioMoney(value, text) {
    // TikTok Shop writes "₫ 9.999"; show every price the same way.
    if (text) return String(text).trim().replace(/^₫\s*(.+)$/, '$1₫');
    const amount = Number(String(value || '').replace(/[^\d.]/g, ''));
    return amount ? `${Math.round(amount).toLocaleString('vi-VN')}₫` : '';
  }

  function studioVideoSections(result) {
    const summary = [result.topic ? `<p><b>${esc(result.topic)}</b></p>` : '', studioLongText(result.content_summary)].join('');
    const transcript = String(result.source_text || '').trim();
    const words = transcript ? transcript.split(/\s+/).length : 0;
    const dialogue = (result.dialogue || []).map((item) => {
      const at = Number.isFinite(Number(item.start_seconds)) && item.start_seconds !== undefined
        ? `${formatStudioDuration(Number(item.start_seconds))} · ` : '';
      return `${at}${item.speaker || 'Không rõ'}: ${item.line || ''}`;
    });
    return [
      studioCard('Tóm tắt', summary),
      studioCard('Transcript', transcript ? `<p>${words.toLocaleString('vi-VN')} từ</p>
        <details class="studio-more"><summary>Xem transcript</summary><pre class="studio-transcript">${esc(transcript)}</pre></details>` : ''),
      studioCard('Cấu trúc nội dung', studioList((result.scene_map || []).map((item) => item.what_happens))),
      studioCard(`Lời thoại chính · ${dialogue.length} câu`, dialogue.length ? studioList(dialogue, {ordered: false, limit: 4}) : ''),
      studioCard('Nhân vật', studioList((result.characters || []).map((item) => `${item.name || ''} — ${item.role || ''}`), {ordered: false})),
      studioCard('Hình ảnh / phong cách', studioLongText(result.visual_style, 300)),
      studioCard('Điểm đáng chú ý', studioChips(result.keywords)),
    ];
  }

  function studioProductSections(result, video) {
    const facts = result.source_facts || {};
    const image = (facts.images || [])[0] || video?.thumbnail || '';
    const price = studioMoney(facts.price, facts.price_text);
    const original = studioMoney(facts.original_price, facts.original_price_text);
    const read = facts.captured_at ? new Date(facts.captured_at) : null;
    const standing = [
      facts.rating ? `${esc(facts.rating)}★${facts.review_count ? ` (${esc(facts.review_count)})` : ''}` : '',
      facts.sold_count ? `${esc(facts.sold_count)} đã bán` : '',
    ].filter(Boolean).join(' · ');
    const {platform} = studioSourceKind(video, result);
    const link = facts.canonical_url || facts.url || video?.video_url || '';
    const card = `<div class="studio-product-card">
        ${image ? `<img src="${esc(image)}" alt="">` : ''}
        <div>
          <div class="primary-text">${esc(facts.name || result.topic || video?.title || '')}</div>
          <div class="studio-price-row">${price ? `<span class="studio-price">${esc(price)}</span>` : '<span class="secondary-text">Chưa đọc được giá</span>'}
            ${original ? `<span class="studio-price-old">${esc(original)}</span>` : ''}
            ${facts.discount ? `<span class="tag orange">${esc(facts.discount)}</span>` : ''}</div>
          ${facts.seller ? `<div class="secondary-text">Shop: ${esc(facts.seller)}</div>` : ''}
          ${standing ? `<div class="secondary-text">${standing}</div>` : ''}
          ${read && !Number.isNaN(read.getTime()) ? `<div class="secondary-text">Đọc giá lúc ${esc(read.toLocaleString('vi-VN', {hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit', year: 'numeric'}))}</div>` : ''}
          ${link ? `<a class="studio-source-link" href="${esc(link)}" target="_blank" rel="noopener">Xem trên ${esc(platform || 'trang bán')} ↗</a>` : ''}
        </div>
      </div>`;
    return [
      studioCard('Sản phẩm', card, 'studio-wide'),
      studioCard('Thông tin chính', [studioLongText(result.content_summary), studioList((result.scene_map || []).map((item) => item.what_happens), {ordered: false})].join('')),
      studioCard('Từ khoá', studioChips(result.keywords)),
    ];
  }

  function studioArticleSections(result, video) {
    const host = studioSourceHost(video);
    const head = `<p><b>${esc(video?.title || result.topic || '')}</b></p>${host ? `<p class="secondary-text">Nguồn: ${esc(host)}${video?.video_url ? ` · <a class="studio-source-link" href="${esc(video.video_url)}" target="_blank" rel="noopener">Mở bài ↗</a>` : ''}</p>` : ''}`;
    return [
      studioCard('Bài viết', head),
      studioCard('Tóm tắt', studioLongText(result.content_summary)),
      studioCard('Ý chính', studioList((result.scene_map || []).map((item) => item.what_happens))),
      studioCard('Dữ kiện & từ khoá', studioChips(result.keywords)),
      studioCard('Hình ảnh', studioLongText(result.visual_style, 300)),
    ];
  }

  function studioImageSections(result) {
    return [
      studioCard('Ảnh đã xem', '<div id="studioResultImages" class="studio-thumbs"></div>'),
      studioCard('Mô tả', studioLongText(result.content_summary)),
      studioCard('Vật thể / nhân vật', studioList((result.characters || []).map((item) => `${item.name || ''} — ${item.role || ''}`), {ordered: false})),
      studioCard('Phong cách', studioLongText(result.visual_style, 300)),
      studioCard('Bố cục / màu sắc', studioList((result.scene_map || []).map((item) => item.what_happens), {ordered: false})),
      studioCard('Yếu tố đáng chú ý', studioChips(result.keywords)),
    ];
  }

  function studioIdeaSections(result) {
    return [
      studioCard('Tóm tắt', [result.topic ? `<p><b>${esc(result.topic)}</b></p>` : '', studioLongText(result.content_summary)].join('')),
      studioCard('Ý chính', studioList((result.scene_map || []).map((item) => item.what_happens))),
      studioCard('Từ khoá', studioChips(result.keywords)),
    ];
  }

  // Khi trang bán hàng chưa đọc được: một dòng và việc cần làm, không chi tiết kỹ thuật.
  function studioReadNotice(result, video) {
    const facts = result.source_facts || {};
    const status = String(facts.read_status || '');
    if (!status || status === 'OK') return '';
    const {platform} = studioSourceKind(video, result);
    const name = platform || 'trang bán';
    const line = status === 'NEED_HUMAN_VERIFY'
      ? `${name} yêu cầu xác minh – mở ${name} trong trình duyệt và xác minh.`
      : status === 'NEED_LOGIN'
        ? `Chưa đọc được ${name} – cần kết nối tài khoản.`
        : `Chưa đọc được trang ${name}.`;
    return `<div class="studio-analyze-notice">⚠ ${esc(line)}
      <div class="studio-actions" style="margin-top:8px"><button class="btn small ghost" type="button" onclick="setWorkspace('settings')">Mở Công cụ & kết nối</button>
      <button class="btn small primary" type="button" onclick="analyzeStudioVideo()">Phân tích lại</button></div></div>`;
  }

  function studioResultNotes(result) {
    const notes = [];
    for (const raw of result.warnings || []) {
      const text = String(raw || '');
      if (/Đã giao cho AI điều phối|Chưa đọc được trang sản phẩm/.test(text)) continue;
      if (/Không đọc được giá/.test(text)) { notes.push('Không đọc được giá – kịch bản sẽ không nêu giá.'); continue; }
      const plain = studioPlainText(text);
      if (plain) notes.push(plain);
    }
    return [...new Set(notes)];
  }

  function renderStudioStep1Result(payload) {
    const box = $('studioStep1Result');
    const next = $('studioStep1NextButton');
    const json = $('studioAnalysisJson');
    if (!box) return;
    const result = payload?.result || payload || {};
    const real = Boolean(result.content_summary || result.source_facts || (Array.isArray(result.scene_map) && result.scene_map.length));
    if (!payload || !real) {
      box.hidden = true;
      box.innerHTML = '';
      if (next) next.disabled = true;
      if (json) json.hidden = true;
      return;
    }
    const video = studioSelectedVideo();
    const {kind, label} = studioSourceKind(video, result);
    const sections = kind === 'product' ? studioProductSections(result, video)
      : kind === 'article' || kind === 'web' ? studioArticleSections(result, video)
        : kind === 'images' ? studioImageSections(result)
          : kind === 'idea' ? studioIdeaSections(result)
            : studioVideoSections(result);
    const notes = studioResultNotes(result);
    box.innerHTML = `
      <div class="studio-result-head"><b>Kết quả phân tích</b><span class="secondary-text">${esc(label || '')}</span></div>
      ${studioReadNotice(result, video)}
      ${notes.length ? `<div class="studio-result-notes">${notes.map((item) => `<div>• ${esc(item)}</div>`).join('')}</div>` : ''}
      <div class="studio-result-grid">${sections.join('')}</div>
      ${studioUncertain(result)}`;
    box.hidden = false;
    if (next) next.disabled = false;
    // The saved analysis arrives after the source card was drawn.
    const button = $('studioAnalyzeButton');
    if (button && !state.studioAnalyzing) button.textContent = 'Phân tích lại';
    renderStudioAnalyzeState();
    const media = document.querySelector('#studioVideoPreview .studio-source-media');
    const picture = (result.source_facts?.images || [])[0];
    if (media && picture && !media.querySelector('img, iframe, video')) media.innerHTML = `<img src="${esc(picture)}" alt="">`;
    if (json) {
      json.hidden = false;
      json.querySelector('pre').textContent = JSON.stringify(result, null, 2);
    }
    if (kind === 'images' && state.studioProjectId) {
      api(`/api/projects/${state.studioProjectId}/assets`).then((assets) => {
        const target = $('studioResultImages');
        if (!target) return;
        target.innerHTML = (assets || []).filter((item) => item.asset_type === 'image').slice(0, 12)
          .map((item) => `<img src="/api/assets/${item.id}/download" alt="${esc(item.original_name || '')}">`).join('');
      }).catch(() => {});
    }
  }

  function renderStudioAnalysis(payload) {
    renderStudioStep1Result(payload);
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

  // ---- Bước 2 · Kế hoạch ----
  //
  // Một bước với người dùng. Bên trong, server đi qua nghiên cứu → insight →
  // góc nội dung → kế hoạch → kiểm tra khả thi; trang chỉ vẽ lại điều server trả về:
  //   GET  /api/projects/{id}/steps        dòng "plan": đang chạy hay không, và `outcome`
  //   GET  /api/projects/{id}/plan         kế hoạch, nghiên cứu, insight, `resources`
  //   POST /api/projects/{id}/steps/plan   {mode, settings, primary_angle_id}
  // Không có luật khả thi, tài nguyên hay độ liên quan nào ở đây: thứ gì "thiếu",
  // thứ gì "cần quyết định" là do server nói.
  const STUDIO_PLAN_POLL_MS = 5000;
  const STUDIO_PLAN_HIDDEN_POLL_MS = 30000;
  const STUDIO_PLAN_STATUS = {
    none: ['', 'Chưa lập kế hoạch'],
    draft: ['', 'Chưa lập kế hoạch'],
    running: ['cyan', 'Đang lập kế hoạch…'],
    completed: ['green', 'Sẵn sàng'],
    needs_user_decision: ['orange', 'Cần bạn quyết định'],
    blocked: ['red', 'Chưa thể thực hiện'],
    stale: ['orange', 'Kế hoạch đã cũ'],
    failed: ['red', 'Chưa lập được kế hoạch'],
  };
  // Lập lại theo góc hoặc theo cài đặt: server dùng lại nghiên cứu và insight đã
  // lưu, chỉ lập phần kế hoạch. Ba bước này khi đó không chạy.
  const STUDIO_PLAN_KEPT_STAGES = ['research', 'insights', 'angles'];
  const STUDIO_PLAN_PLATFORMS = {youtube: 'YouTube', tiktok: 'TikTok', instagram: 'Instagram', facebook: 'Facebook'};
  const STUDIO_PLAN_LANGUAGES = {vi: 'Tiếng Việt', en: 'Tiếng Anh'};
  const STUDIO_PLAN_MEDIA = {
    source_footage: 'Cảnh quay từ nguồn', product_images: 'Ảnh sản phẩm', source_images: 'Ảnh từ nguồn',
    screenshots: 'Ảnh chụp màn hình', b_roll: 'B-roll', ai_media: 'Hình AI', diagrams: 'Sơ đồ', graphics: 'Đồ hoạ',
  };
  const STUDIO_PLAN_INSIGHTS = {
    audience_need: 'Nhu cầu người xem', audience_question: 'Câu hỏi của người xem', pain_point: 'Điều gây khó chịu',
    objection: 'Điều khiến người mua e ngại', positive_signal: 'Điều được khen', channel_pattern: 'Cách làm của kênh nguồn',
    competitor_pattern: 'Cách làm của nội dung tương tự', performance_pattern: 'Điểm chung ở nội dung nhiều lượt xem',
    content_gap: 'Khoảng trống nội dung', opportunity: 'Cơ hội', selling_point: 'Điểm bán hàng', product_risk: 'Rủi ro về sản phẩm',
    fact: 'Dữ kiện', disputed_fact: 'Dữ kiện còn tranh cãi', uncertainty: 'Điều chưa rõ',
  };
  const STUDIO_PLAN_FACT_STATUS = {
    confirmed: 'đã xác nhận', reported: 'mới một nguồn đưa', disputed: 'các nguồn nói khác nhau', unknown: 'chưa xác nhận',
  };
  const STUDIO_PLAN_SOURCES = {
    source: 'Nguồn của dự án', video_meta: 'Video tương tự', channel_stats: 'Hồ sơ kênh nguồn', comment_sample: 'Bình luận mẫu',
    article: 'Bài viết', official: 'Trang chính thức', product_page: 'Trang sản phẩm', review: 'Bài đánh giá',
    search_result: 'Kết quả tìm kiếm (chưa mở trang)', transcript: 'Phụ đề của video tương tự',
  };

  document.addEventListener('visibilitychange', () => {
    const watch = state.studioPlan?.watch;
    if (document.hidden || !watch?.tick) return;
    clearTimeout(watch.timer);
    void watch.tick();
  });

  function studioPlanState(projectId = state.studioProjectId) {
    if (!state.studioPlan || Number(state.studioPlan.projectId) !== Number(projectId)) {
      clearTimeout(state.studioPlan?.watch?.timer);
      // runKind: lượt đang chạy là gì, khi chính trang này bắt đầu nó ('replan' | 'full');
      // null khi lượt chạy được tìm thấy trên server. seen: các bước trang đã thấy chạy.
      state.studioPlan = {projectId: projectId || null, row: null, bundle: null, error: '', running: false, requesting: false,
        watch: null, runKind: null, seen: []};
    }
    return state.studioPlan;
  }

  // Đổi nguồn hoặc dự án: bỏ mọi thứ đang giữ về kế hoạch của dự án trước.
  function resetStudioPlan() {
    clearTimeout(state.studioPlan?.watch?.timer);
    state.studioPlan = null;
    renderStudioPlan();
  }

  async function studioPlanRow(projectId) {
    const body = await api(`/api/projects/${projectId}/steps`);
    return (body.steps || []).find((row) => row.key === 'plan') || null;
  }

  // Đọc trạng thái và kế hoạch từ server. Trả true khi dự án đã có kế hoạch
  // hoặc đang lập, để lúc mở lại dự án biết dừng ở Bước 2.
  async function loadStudioPlan(projectId = state.studioProjectId) {
    if (!projectId) { renderStudioPlan(); return false; }
    const plan = studioPlanState(projectId);
    let row = null;
    let bundle = null;
    try {
      [row, bundle] = await Promise.all([studioPlanRow(projectId), api(`/api/projects/${projectId}/plan`)]);
    } catch (error) {
      if (state.studioPlan !== plan) return false;
      if (!plan.bundle) plan.error = studioPlanErrorText(error);
      renderStudioPlan();
      return false;
    }
    if (state.studioPlan !== plan) return false;
    plan.row = row;
    plan.bundle = bundle;
    // Một lượt chạy từ trước khi tải lại trang, từ tab khác hay từ AI điều phối.
    if (row?.state === 'running') {
      plan.running = true;
      noteStudioPlanStage(plan, row);
      watchStudioPlan(projectId);
    } else if (!plan.requesting) {
      plan.running = false;
      plan.runKind = null;
      plan.seen = [];
    }
    renderStudioPlan();
    return row?.state === 'running' || Boolean(row?.outcome && row.outcome.status !== 'draft');
  }

  // Chỉ bước nào trang thật sự thấy server đang chạy mới được coi là đã chạy.
  function noteStudioPlanStage(plan, row) {
    const stage = row?.run?.stage;
    if (stage && !plan.seen.includes(stage)) plan.seen.push(stage);
  }

  // "Đang chạy" đọc từ server, không giữ trong trang: tải lại trang chỉ bỏ
  // request, không bỏ việc. Tab đang ẩn hỏi thưa hơn và hỏi ngay khi mở lại.
  function watchStudioPlan(projectId) {
    const plan = studioPlanState(projectId);
    if (plan.watch) return;
    const watch = {timer: null, tick: null, busy: false};
    plan.watch = watch;
    const later = () => setTimeout(watch.tick, document.hidden ? STUDIO_PLAN_HIDDEN_POLL_MS : STUDIO_PLAN_POLL_MS);
    watch.tick = async () => {
      if (state.studioPlan !== plan || plan.watch !== watch || watch.busy) return;
      watch.busy = true;
      let row = null;
      try { row = await studioPlanRow(projectId); } catch (_) { /* app tạm không trả lời: hỏi lại sau */ }
      watch.busy = false;
      if (state.studioPlan !== plan || plan.watch !== watch) return;
      if (!row || row.state === 'running') {
        if (row) { plan.row = row; noteStudioPlanStage(plan, row); renderStudioPlanHead(); }
        watch.timer = later();
        return;
      }
      plan.watch = null;
      // Request của chính trang này còn mở: câu trả lời của nó sẽ kết thúc lượt chạy.
      if (plan.requesting) return;
      plan.running = false;
      if (row.last_run?.status === 'failed') {
        plan.error = studioPlanErrorText({status: row.last_run.status_code, message: row.last_run.error});
      }
      await loadStudioPlan(projectId);
      announceStudioPlan();
    };
    watch.timer = later();
  }

  function stopStudioPlanWatch(plan) {
    clearTimeout(plan?.watch?.timer);
    if (plan) plan.watch = null;
  }

  // Một lần lập kế hoạch. `options` đi nguyên vào POST …/steps/plan.
  async function runStudioPlan(options = {}) {
    const projectId = state.studioProjectId;
    if (!projectId) return setMessage('Hãy chọn nguồn và phân tích ở Bước 1 trước.', 'error');
    const plan = studioPlanState(projectId);
    if (plan.running) return;
    plan.running = true;
    plan.requesting = true;
    plan.error = '';
    plan.runKind = options.primary_angle_id || options.mode === 'replan' ? 'replan' : 'full';
    plan.seen = [];
    renderStudioPlan();
    watchStudioPlan(projectId);
    let failure = null;
    try {
      await api(`/api/projects/${projectId}/steps/plan`, {method: 'POST', body: JSON.stringify({options})});
    } catch (error) {
      failure = error;
    }
    if (state.studioPlan !== plan) return;
    plan.requesting = false;
    if (failure) {
      // Request hỏng nhưng server vẫn đang lập (một lượt khác đã chạy trước,
      // hoặc mất kết nối giữa chừng): theo dõi lượt đang có.
      let row = null;
      try { row = await studioPlanRow(projectId); } catch (_) { /* không hỏi được: coi như lượt này đã dừng */ }
      if (state.studioPlan !== plan) return;
      if (row?.state === 'running') {
        // Lượt đang chạy là của nơi khác: trang không biết nó thuộc loại nào.
        plan.row = row;
        plan.runKind = null;
        plan.seen = [];
        noteStudioPlanStage(plan, row);
        watchStudioPlan(projectId);
        renderStudioPlanHead();
        if (Number(failure.status) === 409) setMessage('Đang có một lần lập kế hoạch khác.', 'error');
        return;
      }
      plan.error = studioPlanErrorText(failure);
    }
    stopStudioPlanWatch(plan);
    plan.running = false;
    await loadStudioPlan(projectId);
    announceStudioPlan();
  }

  function announceStudioPlan() {
    const plan = state.studioPlan;
    if (!plan) return;
    if (plan.error) return setMessage(plan.error, 'error');
    const status = studioPlanStatus(plan);
    if (status === 'completed') setMessage('Đã lập kế hoạch.', 'success');
    else if (status === 'needs_user_decision') setMessage('Đã lập kế hoạch. Còn điểm cần bạn quyết định.');
    else if (status === 'blocked') setMessage('Kế hoạch chưa thể thực hiện.', 'error');
  }

  // Lỗi viết bằng lời thường; không mã HTTP, không tên chế độ, không traceback.
  function studioPlanErrorText(error) {
    const status = Number(error?.status || 0);
    const text = String(error?.message || '');
    if (status === 409 && /đang chạy/i.test(text)) return 'Đang có một lần lập kế hoạch khác.';
    if (status === 409 && /insight|nghiên cứu/i.test(text)) return 'Dữ liệu của kế hoạch đã thay đổi. Bấm “Lập lại kế hoạch” rồi thử lại.';
    if (status === 409) return 'Chưa phân tích nguồn. Hãy làm Bước 1 trước.';
    if (status === 400 && /góc nội dung|primary_angle/i.test(text)) return 'Góc này không còn trong danh sách. Hãy chọn một góc đang hiển thị, hoặc lập lại kế hoạch.';
    if (status === 502) return 'AI lập kế hoạch chưa chạy được lúc này. Thử lại sau ít phút.';
    if (!status && /fetch|network/i.test(text)) return 'Không kết nối được app. Hãy mở lại app rồi thử lại.';
    return studioPlainText(text).replace(/\bmode=\w+\b/g, '').slice(0, 200) || 'Có lỗi khi lập kế hoạch. Thử lại sau.';
  }

  // Trạng thái là của server: `outcome.status` trên dòng "plan" của GET …/steps.
  function studioPlanStatus(plan = state.studioPlan) {
    if (!plan) return 'none';
    if (plan.running || plan.row?.state === 'running') return 'running';
    const status = String(plan.row?.outcome?.status || '');
    if (STUDIO_PLAN_STATUS[status]) return status;
    return plan.error ? 'failed' : 'none';
  }

  // Lập mới, lập lại, thử lại: cùng một lượt đầy đủ. Server tự dùng lại nghiên
  // cứu còn mới và giữ các cài đặt đã chọn.
  function startStudioPlan() { return runStudioPlan({mode: 'auto'}); }

  // Đổi góc: server lập lại từ nghiên cứu và insight đã lưu, không nghiên cứu lại.
  function chooseStudioPlanAngle(angleId) {
    if (!angleId) return null;
    return runStudioPlan({primary_angle_id: String(angleId)});
  }

  // Đổi thời lượng / định dạng: chỉ gửi điều người dùng thật sự đổi.
  function applyStudioPlanSettings() {
    const plan = state.studioPlan;
    const stored = plan?.bundle?.plan?.plan || {};
    const settings = {};
    const profile = $('studioPlanProfile')?.value || '';
    const seconds = Math.round(Number($('studioPlanSeconds')?.value || 0));
    if (profile && profile !== stored.output_profile) settings.output_profile = profile;
    if (seconds > 0 && seconds !== Number(stored.target_duration_seconds || 0)) settings.target_duration_seconds = seconds;
    if (!Object.keys(settings).length) return setMessage('Chưa đổi thời lượng hay định dạng.', 'error');
    // Kế hoạch đã cũ thì phải lập lại đầy đủ; còn dùng được thì chỉ lập lại phần kế hoạch.
    const mode = studioPlanStatus(plan) === 'stale' ? 'auto' : 'replan';
    return runStudioPlan({mode, settings});
  }

  function scrollStudioPlan(id) {
    $(id)?.scrollIntoView({behavior: 'smooth', block: 'start'});
  }

  function studioPlanText(value) { return esc(studioProse(value)); }

  function studioPlanItems(items, limit = 5) {
    const rows = (items || []).map((item) => studioProse(item)).filter(Boolean);
    if (!rows.length) return '';
    const line = (item) => `<li>${esc(item)}</li>`;
    const rest = rows.slice(limit);
    return `<ul class="studio-result-list">${rows.slice(0, limit).map(line).join('')}</ul>`
      + (rest.length ? `<details class="studio-more"><summary>Xem thêm ${rest.length}</summary><ul class="studio-result-list">${rest.map(line).join('')}</ul></details>` : '');
  }

  function studioPlanField(label, value) {
    const text = studioProse(value);
    return text ? `<div class="studio-plan-field"><span>${esc(label)}</span><p>${esc(text)}</p></div>` : '';
  }

  function studioPlanWhen(value) {
    const at = value ? new Date(value) : null;
    return at && !Number.isNaN(at.getTime())
      ? at.toLocaleString('vi-VN', {hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit'}) : '';
  }

  function studioPlanFormat(profile) {
    return (typeof PUBLISH_PROFILE_LABELS === 'object' && PUBLISH_PROFILE_LABELS[profile]) || String(profile || '');
  }

  // ---- Phần đầu: nguồn, trạng thái, nút. Vẽ lại mỗi lần hỏi server. ----
  function studioPlanActions(status, plan) {
    const busy = status === 'running';
    const button = (label, action, kind = 'primary') =>
      `<button class="btn ${kind}" type="button" ${busy ? 'disabled' : ''} onclick="${action}">${esc(label)}</button>`;
    if (busy) return `<button class="btn primary" type="button" disabled>${esc(studioPlanRunningLabel(plan))}</button>`;
    if (status === 'completed') return button('Chọn góc khác', "scrollStudioPlan('studioPlanAngles')", 'ghost') + button('Lập lại kế hoạch', 'startStudioPlan()', 'ghost');
    if (status === 'needs_user_decision') return button('Giải quyết vấn đề', "scrollStudioPlan('studioPlanDecisions')") + button('Lập lại kế hoạch', 'startStudioPlan()', 'ghost');
    if (status === 'blocked' || status === 'failed') return button('Thử lại', 'startStudioPlan()');
    if (status === 'stale') return button('Lập lại kế hoạch', 'startStudioPlan()');
    return studioPlanNeedsAnalysis(plan)
      ? '<button class="btn primary" type="button" onclick="setStudioStep(1)">Phân tích nguồn trước</button>'
      : button('Lập kế hoạch', 'startStudioPlan()');
  }

  // Kế hoạch lập từ nguồn đã phân tích: chưa có dự án, hoặc server nói còn thiếu bước Phân tích.
  function studioPlanNeedsAnalysis(plan = state.studioPlan) {
    return !state.studioProjectId || (plan?.row?.missing || []).includes('analyze');
  }

  // Đã có kế hoạch thì lượt chạy là lập lại.
  function studioPlanRunningLabel(plan) {
    return (plan?.bundle?.plan?.plan?.content_structure || []).length ? 'Đang lập lại kế hoạch…' : 'Đang lập kế hoạch…';
  }

  // Dòng các bước nói đúng điều đã xảy ra, không suy ra từ thứ tự: bước đang chạy
  // (server báo), bước trang đã thấy chạy, và - khi chính trang này gọi lập lại
  // theo góc / cài đặt - ba bước server giữ nguyên không chạy.
  function studioPlanRunning(plan) {
    const run = plan.row?.run || {};
    const stages = run.stages || plan.bundle?.stages || [];
    const replan = plan.runKind === 'replan';
    const started = run.started_at ? new Date(run.started_at) : null;
    const elapsed = started && !Number.isNaN(started.getTime()) ? Math.max(0, Math.round((Date.now() - started.getTime()) / 1000)) : 0;
    const chips = stages.map((item) => {
      const kept = replan && STUDIO_PLAN_KEPT_STAGES.includes(item.key);
      const mark = item.key === run.stage ? 'now' : kept ? 'kept' : (plan.seen || []).includes(item.key) ? 'past' : '';
      return `<span class="studio-plan-stage ${mark}">${esc(item.label)}${mark === 'kept' ? ' · giữ nguyên' : ''}</span>`;
    }).join('');
    const timing = `${run.stage_label ? `${esc(run.stage_label)} · ` : ''}${elapsed ? `đã chạy ${formatStudioDuration(elapsed)} · ` : ''}`;
    return `<div class="studio-plan-running" aria-live="polite">
        <div class="studio-plan-stages">${chips}</div>
        ${replan ? '<div class="studio-plan-note">Nghiên cứu và insight hiện tại được giữ nguyên; app chỉ lập lại phần kế hoạch.</div>' : ''}
        <div class="studio-plan-note">${timing}${replan ? 'thường mất khoảng 1 phút' : 'thường mất 2–3 phút'}. Có thể rời trang, việc vẫn chạy.</div>
      </div>`;
  }

  function studioPlanReason(status, plan) {
    const outcome = plan?.row?.outcome || {};
    if (status === 'stale') {
      return `<div class="studio-analyze-notice">Kế hoạch này được lập trước khi dữ liệu thay đổi${outcome.reason ? `: ${studioPlanText(outcome.reason)}` : ''}. Hãy lập lại kế hoạch.</div>`;
    }
    if (!studioSelectedVideo()) {
      return '<div class="studio-empty">Chưa chọn nguồn. Chọn nguồn trong Nguồn tham khảo rồi phân tích ở Bước 1.</div>';
    }
    if ((status === 'none' || status === 'failed') && studioPlanNeedsAnalysis(plan)) {
      return '<div class="studio-empty">Chưa có kết quả phân tích. Kế hoạch được lập từ nguồn đã phân tích ở Bước 1.</div>';
    }
    if (status === 'none' || status === 'draft') {
      return '<div class="studio-empty">Chưa có kế hoạch cho nguồn này. Bấm “Lập kế hoạch”: app sẽ tìm hiểu thêm về chủ đề, đề xuất vài góc nội dung và lập kế hoạch cho video.</div>';
    }
    return '';
  }

  function renderStudioPlanHead() {
    const box = $('studioPlanHead');
    if (!box) return;
    const plan = state.studioPlan;
    const status = studioPlanStatus(plan);
    const [tone, named] = STUDIO_PLAN_STATUS[status];
    const label = status === 'running' ? studioPlanRunningLabel(plan) : named;
    const video = studioSelectedVideo();
    const source = video ? studioSourceKind(video) : null;
    const stored = plan?.bundle?.plan;
    const updated = stored && status !== 'none' && status !== 'draft' ? studioPlanWhen(stored.created_at) : '';
    box.innerHTML = `
      <div class="studio-plan-head">
        <div class="studio-plan-source">
          <div class="primary-text">${esc(video?.title || 'Chưa chọn nguồn')}</div>
          <div class="secondary-text">${esc([source?.label, source?.platform].filter(Boolean).join(' · '))}${updated ? ` · kế hoạch cập nhật ${esc(updated)}` : ''}</div>
        </div>
        <span class="status-badge ${tone}">${esc(label)}</span>
        <div class="studio-plan-actions">${video ? studioPlanActions(status, plan) : ''}</div>
      </div>
      ${status === 'running' ? studioPlanRunning(plan) : ''}
      ${plan?.error && status !== 'running' ? `<div class="studio-analyze-notice">⚠ ${esc(plan.error)}</div>` : ''}
      ${studioPlanReason(status, plan)}`;
    syncStudioPlanStep(status);
  }

  // Tab Bước 2 và nút sang Bước 3 nói đúng trạng thái: chỉ "Sẵn sàng" mới là xong.
  function syncStudioPlanStep(status = studioPlanStatus()) {
    const tab = document.querySelector('[data-studio-tab="2"]');
    if (tab) {
      tab.dataset.planState = status;
      tab.classList.toggle('done', status === 'completed' && Number(state.studioStep) > 2);
    }
    const next = $('studioToScriptButton');
    if (next) {
      next.disabled = status !== 'completed';
      next.title = status === 'completed' ? '' : 'Kế hoạch chưa sẵn sàng';
    }
    syncStudioScriptGate();
  }

  // ---- Phần thân: vẽ lại khi kế hoạch đổi, không vẽ lại theo từng lần hỏi. ----
  function studioPlanDecisions(status, plan) {
    const outcome = plan.row?.outcome || {};
    const feasibility = plan.bundle?.plan?.feasibility || {};
    if (!['completed', 'needs_user_decision', 'blocked'].includes(status)) return '';
    const mark = {ok: '✓', adjusted: '✓', needs_attention: '!', blocked: '✕'};
    const checks = (feasibility.checks || []).map((item) =>
      `<li class="studio-plan-check ${esc(item.status)}"><b>${mark[item.status] || '·'}</b> ${studioPlanText(item.detail)}</li>`).join('');
    const adjusted = (feasibility.adjustments || []).map((item) => studioProse(item.why)).filter(Boolean);
    const decisions = (outcome.decisions || []).map((item) => `
      <div class="studio-plan-decision">
        <p>${studioPlanText(item.detail)}</p>
        ${(item.options || []).length ? `<div class="studio-plan-note">Bạn có thể:</div>${studioPlanItems(item.options, 6)}` : ''}
      </div>`).join('');
    const head = status === 'completed'
      ? '<p>Kế hoạch làm được với những gì dự án đang có.</p>'
      : status === 'blocked'
        ? '<p><b>Chưa thể thực hiện kế hoạch này.</b> Bước 2 chưa xong cho tới khi xử lý các điểm dưới đây.</p>'
        : '<p><b>Cần bạn quyết định.</b> App không tự chọn thay bạn; Bước 2 chưa xong cho tới khi các điểm dưới đây được xử lý.</p>';
    const next = status === 'completed' ? '' : `
      <div class="studio-actions">
        <button class="btn small ghost" type="button" onclick="scrollStudioPlan('studioPlanAdjust')">Đổi thời lượng / định dạng</button>
        <button class="btn small ghost" type="button" onclick="scrollStudioPlan('studioPlanAngles')">Chọn góc khác</button>
        <button class="btn small ghost" type="button" onclick="startStudioPlan()">Lập lại kế hoạch</button>
      </div>`;
    return `<section id="studioPlanDecisions" class="studio-work-card studio-plan-card ${esc(status)}">
        <div class="studio-card-head"><div><b>Khả năng thực hiện</b></div></div>
        ${head}${decisions}
        ${adjusted.length ? `<div class="studio-plan-note">App đã điều chỉnh nhỏ: ${esc(adjusted.join(' '))}</div>` : ''}
        ${next}
        ${checks ? `<details class="studio-more"><summary>Các điểm đã kiểm tra</summary><ul class="studio-plan-checks">${checks}</ul></details>` : ''}
      </section>`;
  }

  // Một dòng về nguồn, theo loại nguồn mà server ghi trên kế hoạch (source_kind).
  function studioPlanSourceLine(kind, analysis) {
    const video = studioSelectedVideo();
    const seconds = Number(video?.duration_seconds || 0);
    if (kind === 'product') {
      const facts = analysis?.source_facts || {};
      const price = studioMoney(facts.price, facts.price_text);
      const read = studioPlanWhen(facts.captured_at);
      return price ? `giá ${price}${read ? ` (đọc lúc ${read})` : ''}` : 'chưa đọc được giá';
    }
    if (kind === 'article' || kind === 'web') return studioSourceHost(video);
    if (kind === 'audio') return seconds ? `âm thanh ${formatStudioDuration(seconds)}, không có hình` : 'âm thanh, không có hình';
    if (kind === 'video') return seconds ? `video ${formatStudioDuration(seconds)}` : '';
    return '';
  }

  function studioPlanSummary(stored, analysis, locked) {
    const seconds = Number(stored.target_duration_seconds || 0);
    const length = seconds ? `${formatStudioDuration(seconds)} ${stored.target_duration_from === 'project' ? '(bạn đặt)' : '(app đề xuất)'}` : '';
    const facts = [
      ['Nền tảng', STUDIO_PLAN_PLATFORMS[stored.platform] || stored.platform],
      ['Loại video', stored.video_type],
      ['Thời lượng', length],
      ['Khung hình', stored.aspect_ratio],
      ['Ngôn ngữ', STUDIO_PLAN_LANGUAGES[stored.language] || stored.language],
    ].filter(([, value]) => String(value || '').trim());
    const topic = studioProse(analysis?.topic || '');
    const source = studioPlanSourceLine(stored.source_kind, analysis);
    const profiles = typeof PUBLISH_PROFILE_LABELS === 'object' ? Object.keys(PUBLISH_PROFILE_LABELS) : [];
    return `<section class="studio-work-card studio-plan-card">
        <div class="studio-card-head"><div><b>Định hướng</b></div></div>
        ${topic ? `<div class="studio-plan-note">Từ nguồn đã phân tích: ${esc(topic)}${source ? ` · ${esc(source)}` : ''}</div>` : ''}
        <div class="studio-plan-columns">
          ${studioPlanField('Mục tiêu nội dung', stored.goal)}
          ${studioPlanField('Dành cho', stored.target_audience)}
        </div>
        <div class="studio-plan-facts">${facts.map(([name, value]) => `<div><span>${esc(name)}</span><b>${esc(value)}</b></div>`).join('')}</div>
        <details id="studioPlanAdjust" class="studio-more studio-plan-adjust">
          <summary>Đổi thời lượng / định dạng</summary>
          <div class="studio-plan-adjust-row">
            <label>Định dạng<select id="studioPlanProfile">${profiles.map((key) =>
              `<option value="${esc(key)}" ${key === stored.output_profile ? 'selected' : ''}>${esc(studioPlanFormat(key))}</option>`).join('')}</select></label>
            <label>Thời lượng (giây)<input id="studioPlanSeconds" type="number" min="8" max="3600" step="1" value="${esc(seconds || '')}"></label>
            <button class="btn small primary" type="button" ${locked ? 'disabled' : ''} onclick="applyStudioPlanSettings()">Lập lại với cài đặt này</button>
          </div>
          <div class="studio-plan-note">Góc đang chọn được giữ nguyên và app không nghiên cứu lại.</div>
        </details>
      </section>`;
  }

  // Các góc là những lựa chọn ngang nhau: không xếp hạng, không điểm.
  function studioPlanAngles(stored, insight, status) {
    const chosen = stored.primary_angle || {};
    const angles = [chosen, ...(stored.alternative_angles || [])].filter((item) => item?.id)
      .sort((a, b) => String(a.id).localeCompare(String(b.id), undefined, {numeric: true}));
    if (!angles.length) return '';
    const statements = Object.fromEntries((insight?.insights || []).map((item) => [item.id, item.statement]));
    const locked = status === 'running' || status === 'stale';
    const cards = angles.map((angle) => {
      const current = angle.id === chosen.id;
      const support = (angle.supporting_insight_ids || []).map((id) => statements[id]).filter(Boolean);
      return `<article class="studio-plan-angle ${current ? 'current' : ''}" data-angle="${esc(angle.id)}">
          ${current ? '<span class="tag green">GÓC ĐANG CHỌN</span>' : ''}
          <h4>${studioPlanText(angle.statement)}</h4>
          ${studioPlanField('Dành cho', angle.target_audience)}
          ${studioPlanField('Nhu cầu / vấn đề', angle.need_or_problem)}
          ${studioPlanField('Điểm khác biệt', angle.differentiation)}
          ${studioPlanField('Hợp nền tảng', angle.platform_fit)}
          ${(angle.risks || []).length ? `<div class="studio-plan-field"><span>Rủi ro</span>${studioPlanItems(angle.risks, 3)}</div>` : ''}
          ${support.length ? `<details class="studio-more"><summary>Dựa trên ${support.length} điều app tìm hiểu được</summary>${studioPlanItems(support, 8)}</details>` : ''}
          ${current || !/^[\w-]+$/.test(String(angle.id)) ? '' : `<button class="btn small primary" type="button" ${locked ? 'disabled' : ''} onclick="chooseStudioPlanAngle('${esc(angle.id)}')">Chọn góc này</button>`}
        </article>`;
    }).join('');
    const note = status === 'stale' ? 'Kế hoạch đã cũ: lập lại kế hoạch trước khi chọn góc.'
      : 'Chọn góc khác thì app lập lại kế hoạch theo góc đó, không nghiên cứu lại.';
    return `<section id="studioPlanAngles" class="studio-work-card studio-plan-card">
        <div class="studio-card-head"><div><b>Góc nội dung</b><span>${esc(note)}</span></div></div>
        <div class="studio-plan-angles">${cards}</div>
      </section>`;
  }

  function studioPlanStructure(stored) {
    const sections = stored.content_structure || [];
    if (!sections.length && !stored.hook_strategy) return '';
    const total = sections.reduce((sum, item) => sum + Number(item.estimated_seconds || 0), 0);
    const target = Number(stored.target_duration_seconds || 0);
    let at = 0;
    const rows = sections.map((item) => {
      const from = at;
      at += Number(item.estimated_seconds || 0);
      return `<div class="studio-plan-section">
          <div class="studio-plan-time">${formatStudioDuration(from)}–${formatStudioDuration(at)}</div>
          <div><b>${studioPlanText(item.name)}</b>
            ${item.purpose ? `<p>Mục tiêu: ${studioPlanText(item.purpose)}</p>` : ''}
            ${studioPlanItems(item.key_points, 6)}</div>
        </div>`;
    }).join('');
    const bar = total ? `<div class="studio-plan-bar">${sections.map((item) =>
      `<span style="flex:${Math.max(1, Number(item.estimated_seconds || 0))}" title="${esc(item.name)}"></span>`).join('')}</div>` : '';
    return `<section class="studio-work-card studio-plan-card">
        <div class="studio-card-head"><div><b>Kế hoạch nội dung</b><span>Tổng ${formatStudioDuration(total)}${target ? ` · mục tiêu ${formatStudioDuration(target)}` : ''}</span></div></div>
        ${stored.hook_strategy ? `<div class="studio-plan-hook"><span>HOOK</span><p>${studioPlanText(stored.hook_strategy)}</p></div>` : ''}
        ${bar}${rows}
      </section>`;
  }

  function studioPlanProduction(stored) {
    const media = stored.media_strategy || {};
    const edit = stored.edit_direction || {};
    const names = (items) => (items || []).map((key) => STUDIO_PLAN_MEDIA[key] || key).join(', ');
    const shot = Number(edit.average_shot_length_seconds || 0);
    const groups = [
      ['Hình ảnh / media', [
        studioPlanField('Tư liệu chính', names(media.primary_sources)),
        studioPlanField('Tư liệu hỗ trợ', names(media.supporting_sources)),
        studioPlanField('Cách dùng', media.notes),
      ]],
      ['Dựng', [
        studioPlanField('Nhịp', edit.pacing),
        studioPlanField('Kiểu cắt', edit.cut_style),
        studioPlanField('Chuyển cảnh', edit.transitions),
        studioPlanField('Chữ và điểm nhấn', [edit.text_animation, edit.callouts].filter(Boolean).join(' ')),
        studioPlanField('Phóng / zoom', edit.zoom_punch_in),
        studioPlanField('B-roll và đồ hoạ', [edit.broll_usage, edit.graphics].filter(Boolean).join(' ')),
        shot ? studioPlanField('Độ dài cảnh trung bình', `${shot} giây`) : '',
      ]],
      ['Phụ đề', [studioPlanField('Cách làm', stored.subtitle_strategy), studioPlanField('Kiểu chữ', edit.subtitle_style)]],
      ['Âm thanh', [studioPlanField('Nhạc', stored.music_strategy), studioPlanField('Hiệu ứng', stored.sfx_strategy)]],
      ['Lời kêu gọi', [studioPlanField('CTA', stored.cta)]],
    ].map(([title, fields]) => [title, fields.filter(Boolean).join('')]).filter(([, body]) => body);
    if (!groups.length) return '';
    return `<section class="studio-work-card studio-plan-card">
        <div class="studio-card-head"><div><b>Chiến lược sản xuất</b><span>Ở mức định hướng; cảnh và lời cụ thể thuộc các bước sau.</span></div></div>
        <div class="studio-plan-grid">${groups.map(([title, body]) => `<div class="studio-result-card"><h3>${esc(title)}</h3>${body}</div>`).join('')}</div>
      </section>`;
  }

  function studioPlanCautions(stored) {
    const groups = [
      ['Phải giữ đúng', stored.factual_guardrails],
      ['Không được nói', stored.claims_to_avoid],
      ['Cần thêm bằng chứng trước khi nói', stored.claims_needing_proof],
    ].filter(([, items]) => (items || []).length);
    if (!groups.length) return '';
    return `<section class="studio-work-card studio-plan-card">
        <div class="studio-card-head"><div><b>Lưu ý khi làm nội dung</b></div></div>
        <div class="studio-plan-grid">${groups.map(([title, items]) =>
          `<div class="studio-result-card"><h3>${esc(title)}</h3>${studioPlanItems(items, 4)}</div>`).join('')}</div>
      </section>`;
  }

  // Bốn nhóm do server chia sẵn (`resources`); trang không tự xét thứ gì thiếu.
  function studioPlanResources(resources) {
    if (!resources) return '';
    const group = (icon, title, tone, rows, empty) => `
      <div class="studio-plan-resource ${rows.length ? tone : ''}">
        <h3>${icon} ${esc(title)}</h3>
        ${rows.length ? `<ul class="studio-result-list">${rows.join('')}</ul>` : `<div class="studio-plan-note">${esc(empty)}</div>`}
      </div>`;
    const available = (resources.available || []).map((item) => `<li><b>${esc(item.label)}</b> — ${studioPlanText(item.detail)}</li>`);
    const made = (resources.app_generates || []).map((item) => `<li>${studioPlanText(item.label)}</li>`);
    const missing = (resources.missing || []).map((item) =>
      `<li><b>${studioPlanText(item.asset)}</b>${item.required ? ' <span class="tag orange">BẮT BUỘC</span>' : ''}${item.why ? `<br>${studioPlanText(item.why)}` : ''}</li>`);
    const proposed = (resources.proposed || []).map((item) =>
      `<li><b>${studioPlanText(item.asset)}</b>${item.why ? `<br>${studioPlanText(item.why)}` : ''}</li>`);
    return `<section id="studioPlanResources" class="studio-work-card studio-plan-card">
        <div class="studio-card-head"><div><b>Tài nguyên</b></div></div>
        ${resources.reviewed === false ? '<div class="studio-plan-note">Kế hoạch này được lập trước khi app đối chiếu tài nguyên với dự án. Lập lại kế hoạch để có danh sách chính xác.</div>' : ''}
        <div class="studio-plan-grid">
          ${group('✓', 'Đã có', 'have', available, 'Dự án chưa có tư liệu nào của riêng nó.')}
          ${group('🤖', 'App sẽ tự tạo', 'made', made, 'Chưa có kế hoạch để biết app sẽ tạo gì.')}
          ${group('⚠', 'Cần bổ sung', 'need', missing, 'Không thiếu tư liệu nào.')}
          ${group('ℹ', 'Chưa xác minh — chỉ là đề xuất', 'idea', proposed, 'Không có đề xuất nào thêm.')}
        </div>
      </section>`;
  }

  // Nghiên cứu và insight không phải bước riêng: gấp lại, mở khi muốn xem.
  function studioPlanResearch(bundle) {
    const research = bundle.research_report?.report || {};
    const insight = bundle.insight_report?.report || {};
    const stored = bundle.plan?.plan || {};
    const coverage = research.coverage || {};
    const counted = [
      [coverage.videos, 'video'], [coverage.comments_sampled, 'bình luận mẫu'], [coverage.articles, 'bài viết đã đọc'],
      [coverage.product_pages, 'trang sản phẩm'],
    ].filter(([count]) => Number(count) > 0).map(([count, name]) => `${Number(count).toLocaleString('vi-VN')} ${name}`);
    const host = (url) => { try { return new URL(String(url)).hostname.replace(/^www\./, ''); } catch (_) { return ''; } };
    const used = Object.values(insight.evidence_index || {}).map((item) => {
      const name = studioProse(item.title) || host(item.source_url) || 'Nguồn';
      const kind = STUDIO_PLAN_SOURCES[item.source_kind] || '';
      const sample = Number(item.sample_size) ? ` · ${Number(item.sample_size)} bình luận` : '';
      const link = /^https?:/i.test(String(item.source_url || ''))
        ? `<a class="studio-source-link" href="${esc(item.source_url)}" target="_blank" rel="noopener">${esc(name)} ↗</a>` : esc(name);
      return `<li>${link}<span class="secondary-text"> ${esc(kind)}${esc(sample)}</span></li>`;
    });
    const byType = {};
    for (const item of insight.insights || []) {
      if (!byType[item.type]) byType[item.type] = [];
      byType[item.type].push(item);
    }
    const learned = Object.entries(byType).map(([type, items]) => `
      <div class="studio-plan-field"><span>${esc(STUDIO_PLAN_INSIGHTS[type] || 'Ghi nhận khác')}</span>
        <ul class="studio-result-list">${items.map((item) =>
          `<li>${studioPlanText(item.statement)}${item.fact_status ? ` <span class="secondary-text">(${esc(STUDIO_PLAN_FACT_STATUS[item.fact_status] || '')})</span>` : ''}</li>`).join('')}</ul>
      </div>`).join('');
    const guesses = (insight.hypotheses || []).map((item) => item.statement);
    const unread = [...new Set((research.failed_sources || [])
      .filter((item) => item.collector_status === 'blocked').map((item) => host(item.source)).filter(Boolean))];
    const limits = [
      ...(research.limitations || []).map((item) => studioPlainText(item)),
      ...(unread.length ? [`Không đọc được vì trang chặn hoặc không trả lời: ${unread.join(', ')}.`] : []),
    ].filter(Boolean);
    const blocks = [
      counted.length ? `<div class="studio-plan-field"><span>Dữ liệu đã thu thập</span><p>${esc(counted.join(' · '))}</p></div>` : '',
      used.length ? `<div class="studio-plan-field"><span>Nguồn được dùng cho kế hoạch</span><ul class="studio-result-list">${used.slice(0, 12).join('')}</ul>${used.length > 12 ? `<details class="studio-more"><summary>Xem thêm ${used.length - 12}</summary><ul class="studio-result-list">${used.slice(12).join('')}</ul></details>` : ''}</div>` : '',
      learned ? `<div class="studio-plan-field"><span>Điều app tìm hiểu được</span></div>${learned}` : '',
      guesses.length ? `<div class="studio-plan-field"><span>Phỏng đoán — chưa có bằng chứng, không dùng như sự thật</span>${studioPlanItems(guesses, 6)}</div>` : '',
      limits.length ? `<div class="studio-plan-field"><span>Giới hạn nghiên cứu</span>${studioPlanItems(limits, 6)}</div>` : '',
      (stored.limitations || []).length ? `<div class="studio-plan-field"><span>Giới hạn của kế hoạch</span>${studioPlanItems(stored.limitations, 6)}</div>` : '',
    ].filter(Boolean).join('');
    if (!blocks) return '';
    return `<details class="studio-option-card studio-plan-research">
        <summary>Chi tiết nghiên cứu</summary>
        ${blocks}
        <details class="studio-advanced-json"><summary>Nâng cao: dữ liệu kế hoạch (JSON)</summary><pre class="studio-json">${esc(JSON.stringify({outcome: bundle.outcome, plan: bundle.plan}, null, 2))}</pre></details>
      </details>`;
  }

  function renderStudioPlan() {
    renderStudioPlanHead();
    const body = $('studioPlanBody');
    if (!body) return;
    const plan = state.studioPlan;
    const bundle = plan?.bundle;
    const stored = bundle?.plan?.plan || {};
    const status = studioPlanStatus(plan);
    // Kế hoạch khung (chỉ có nghiên cứu) chưa phải kế hoạch để đọc.
    if (!bundle || !(stored.content_structure || []).length) {
      body.innerHTML = '';
      return;
    }
    // Trong lúc đang lập lại, kế hoạch cũ vẫn hiện với trạng thái của nó.
    const shown = status === 'running' ? String(plan.row?.outcome?.status || 'completed') : status;
    const feasibility = studioPlanDecisions(shown, plan);
    const waiting = shown === 'needs_user_decision' || shown === 'blocked';
    body.innerHTML = [
      waiting ? feasibility : '',
      studioPlanSummary(stored, state.studioAnalysis?.result, status === 'running'),
      studioPlanAngles(stored, bundle.insight_report?.report, status),
      studioPlanStructure(stored),
      studioPlanProduction(stored),
      studioPlanCautions(stored),
      studioPlanResources(bundle.resources),
      waiting ? '' : feasibility,
      studioPlanResearch({...bundle, outcome: plan.row?.outcome}),
    ].join('');
  }
  // ---- hết Bước 2 · Kế hoạch ----

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
        chỉ ${fromScript}% trùng kịch bản bạn đã viết — “Tạo mốc cắt theo lời thoại” đã thay chúng.
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
      // `force` is read from the JSON body (GenerateShotsRequest / GenerateTimelineRequest), never the query.
      await api(`/api/projects/${projectId}/shots/generate`, {method: 'POST', body: JSON.stringify({force: true})});
      await api(`/api/projects/${projectId}/timeline/generate`, {method: 'POST', body: JSON.stringify({force: true})});
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

  // ---- Bước 5 · EditDocument ----
  // A planned project's edit is its EditDocument (Bước 5.3 · T5): planned by
  // one POST to …/steps/edit_plan, applied only when the user confirms it
  // (confirmed_apply), and read back from GET …/edit-document. What the page
  // shows is what the server said: an HTTP 200 alone is never "done". A
  // project outside the plan workflow keeps the legacy Edit Plan below.
  const EDIT_DOC_SCENE_LABELS = {
    ready: 'đã lập',
    visual_review: 'đã lập · cần xem lại hình',
    needs_plan: 'chưa lập',
    stale_content: 'cũ: lời cảnh đã đổi, cần lập lại',
    stale_overlays: 'cũ: lớp chữ không còn hợp, cần lập lại',
    stale_timing: 'cũ: thời lượng đổi, cần lập lại',
  };
  const EDIT_DOC_APPLIED_LABELS = {
    applied: 'đã áp vào timeline',
    not_applied: 'chưa áp vào timeline',
    older: 'timeline còn bản cũ, chưa áp bản mới',
  };
  const EDIT_DOC_AUTO_APPLY_NOTE = 'Lưu ý: lần dựng lại storyboard/timeline kế tiếp cũng sẽ tự áp các cảnh đã lập.';
  let studioEditDocumentTicket = 0;
  let studioEditPlanRunning = false;

  // Read the EditDocument's state for the open project; the newest read wins.
  async function refreshStudioEditDocument() {
    const projectId = Number(state.studioProjectId || 0);
    if (!projectId) { state.studioEditDocument = null; return null; }
    const ticket = ++studioEditDocumentTicket;
    let answer;
    try {
      answer = await api(`/api/projects/${projectId}/edit-document`);
    } catch (error) {
      answer = {project_id: projectId, state: 'error', detail: error.message, scenes: []};
    }
    if (ticket !== studioEditDocumentTicket || Number(state.studioProjectId || 0) !== projectId) return state.studioEditDocument;
    state.studioEditDocument = answer;
    renderStudioEditDocument();
    return answer;
  }

  // 'plan' (EditDocument) | 'legacy' (legacy Edit Plan) | null (not known: nothing is planned).
  function studioEditFlow(doc = state.studioEditDocument) {
    if (!doc || Number(doc.project_id) !== Number(state.studioProjectId || 0) || !doc.mode) return null;
    return doc.mode === 'plan' ? 'plan' : 'legacy';
  }

  async function studioEditFlowNow() {
    await refreshStudioEditDocument();
    return studioEditFlow();
  }

  function studioEditFlowUnknown() {
    const detail = state.studioEditDocument?.detail;
    return setMessage(`Không đọc được trạng thái kế hoạch dựng${detail ? `: ${detail}` : ''}. Chưa lập gì; hãy thử lại.`, 'error');
  }

  function studioEditDocumentScene(segment, doc = state.studioEditDocument) {
    return (doc?.scenes || []).find((item) => item.segment_id != null && Number(item.segment_id) === Number(segment?.id)) || null;
  }

  function editDocumentSceneLine(segment, doc = state.studioEditDocument) {
    const id = Number(segment?.id || 0);
    const line = (text, extra = '', muted = true) => `<div class="storyboard-edit-summary${muted ? ' muted' : ''}"${extra}><b>Kế hoạch dựng:</b> ${text}</div>`;
    if (doc?.state === 'missing') return line('chưa lập (chưa có EditDocument). Bấm “1. Lập kế hoạch dựng”.', ' data-edit-doc-status="missing"');
    if (doc?.state === 'outdated') return line('EditDocument thuộc storyboard trước. Bấm “1. Lập kế hoạch dựng” để cập nhật theo storyboard hiện tại.', ' data-edit-doc-status="outdated"');
    if (doc?.state !== 'current') return line(`không đọc được EditDocument${doc?.detail ? `: ${esc(doc.detail)}` : ''}.`, ' data-edit-doc-status="error"');
    const scene = studioEditDocumentScene(segment, doc);
    if (!scene) return line('cảnh này không có trong EditDocument hiện tại.', ' data-edit-doc-status="absent"');
    const planned = scene.status === 'ready' || scene.status === 'visual_review';
    const text = esc(EDIT_DOC_SCENE_LABELS[scene.status] || scene.status || 'không rõ')
      + (scene.applied ? ` · ${esc(EDIT_DOC_APPLIED_LABELS[scene.applied] || scene.applied)}` : '');
    const button = `<button class="btn small ghost" type="button" onclick="planStudioSceneEdit(${id})">${planned ? 'Lập lại cảnh này' : 'Lập kế hoạch cảnh này'}</button>`;
    return line(`${text}. ${button}`, ` data-edit-doc-status="${esc(scene.status || '')}" data-edit-doc-applied="${esc(scene.applied || '')}"`, !planned);
  }

  // One scene's edit cell: the EditDocument's word for a planned project, the legacy edit beats otherwise.
  function storyboardEditCell(segment) {
    if (studioEditFlow() !== 'plan') return legacyStoryboardEditSummary(segment);
    const beats = editBeatsForSegment(segment);
    return editDocumentSceneLine(segment) + (beats.length ? legacyStoryboardEditSummary(segment, 'Nhịp dựng trên timeline') : '');
  }

  function editDocumentHeadline(doc = state.studioEditDocument) {
    if (!doc) return '';
    const gate = doc.gate && doc.gate !== 'current'
      ? ` Storyboard chưa ở trạng thái hiện hành (${esc(doc.gate)}): lập kế hoạch sẽ bị từ chối cho tới khi dựng lại storyboard.` : '';
    if (doc.state === 'missing') return `<b>Chưa lập kế hoạch dựng.</b> Chưa có EditDocument cho storyboard này.${gate}`;
    if (doc.state === 'outdated') return `<b>Kế hoạch dựng thuộc storyboard trước.</b> Lập kế hoạch dựng để cập nhật.${gate}`;
    if (doc.state !== 'current') return `<b>Không đọc được kế hoạch dựng.</b> ${esc(doc.detail || '')}`;
    const counts = doc.counts || {};
    const waiting = Number(counts.planned || 0) - Number(counts.applied || 0);
    return `<b>EditDocument:</b> ${Number(counts.planned || 0)}/${Number(counts.scenes || 0)} cảnh đã lập · ${Number(counts.applied || 0)} đã áp`
      + ` · ${Number(counts.needs_plan || 0)} chưa lập · ${Number(counts.stale || 0)} cũ.`
      + (waiting > 0 ? ` ${waiting} cảnh đã lập chưa áp: bấm “2. Áp dụng kế hoạch dựng”. ${EDIT_DOC_AUTO_APPLY_NOTE}` : '') + gate;
  }

  function renderStudioEditDocument() {
    if (typeof document !== 'undefined' && document.querySelectorAll) {
      document.querySelectorAll('#studioStoryboardResult [data-edit-doc-segment]').forEach((cell) => {
        const segment = (state.timeline || []).find((item) => Number(item.id) === Number(cell.dataset.editDocSegment));
        if (segment) cell.innerHTML = storyboardEditCell(segment);
      });
    }
    const box = $('studioEditPlanState');
    if (box && studioEditFlow() === 'plan') box.innerHTML = editDocumentHeadline();
  }

  // What a planning run came to, in the server's terms: {ok, type, text}. Only "planned" and "unchanged" are fine.
  function editPlanOutcome(result) {
    const planned = Array.isArray(result?.planned) ? result.planned.length : 0;
    const wanted = Array.isArray(result?.wanted) ? result.wanted.length : 0;
    const named = Object.entries(result?.problems || {}).slice(0, 3).map(([key, why]) => `${key}: ${why}`).join('; ');
    switch (result?.status) {
      case 'planned': return {ok: true, type: 'success', text: `Đã lập kế hoạch dựng cho ${planned} cảnh.`};
      case 'unchanged': return {ok: true, type: '', text: 'Không có cảnh nào cần lập: các cảnh đều đã có kế hoạch dựng hiện hành.'};
      case 'partial': return {ok: false, type: 'error', text: `Chỉ lập được ${planned}/${wanted} cảnh. Chưa lập: ${named || 'không rõ lý do'}.`};
      case 'blocked': return {ok: false, type: 'error', text: `Không lập được cảnh nào${named ? `: ${named}` : ''}.`};
      case 'not_current': return {ok: false, type: 'error', text: `Chưa lập kế hoạch dựng: ${result.detail || 'storyboard hoặc kịch bản không phải bản hiện hành'}. Hãy dựng lại storyboard trước.`};
      case 'needs_rebuild': return {ok: false, type: 'error', text: `Chưa lập kế hoạch dựng: ${result.detail || 'có giọng đọc làm với cấu hình cũ'}.`};
      case 'error': return {ok: false, type: 'error', text: `Lập kế hoạch dựng lỗi: ${result.planner_error || result.detail || 'không rõ lỗi'}.`};
      case 'not_applicable': return {ok: false, type: 'error', text: 'Dự án này không thuộc luồng Kế hoạch: không có EditDocument để lập.'};
      default: return {ok: false, type: 'error', text: `Máy chủ trả trạng thái không rõ (${result?.status ?? 'trống'}): không coi là đã lập.`};
    }
  }

  // What applying came to (T4 _apply_edit_document), or null when nothing was asked to be applied.
  function editApplyOutcome(applied) {
    if (!applied) return null;
    const counts = applied.counts || {};
    const skipped = Object.values(counts.skipped || {}).reduce((sum, value) => sum + Number(value || 0), 0);
    const left = `${Number(counts.conflicts || 0)} cảnh xung đột (hàng đã bị sửa ngoài EditDocument), ${skipped} cảnh bỏ qua`;
    switch (applied.status) {
      case 'applied': return {ok: true, type: 'success', text: `Đã áp ${Number(counts.applied || 0)} cảnh vào timeline.`};
      case 'unchanged': return {ok: true, type: '', text: 'Timeline đã có đúng các cảnh đã lập: không cần áp lại.'};
      case 'nothing_to_apply': return {ok: true, type: '', text: 'Không có cảnh đã lập nào để áp.'};
      case 'partial': return {ok: false, type: 'error', text: `Chỉ áp được ${Number(counts.applied || 0)} cảnh; ${left}.`};
      case 'blocked': return {ok: false, type: 'error', text: `Không áp được cảnh nào: ${left}.`};
      case 'not_current': return {ok: false, type: 'error', text: `Chưa áp: ${applied.detail || 'storyboard của kịch bản này không phải bản hiện hành'}.`};
      case 'no_document': return {ok: false, type: 'error', text: 'Chưa áp: dự án chưa có EditDocument.'};
      case 'error': return {ok: false, type: 'error', text: `Áp kế hoạch dựng lỗi: ${applied.detail || 'không rõ lỗi'}.`};
      default: return {ok: false, type: 'error', text: `Máy chủ trả trạng thái áp không rõ (${applied.status ?? 'trống'}): không coi là đã áp.`};
    }
  }

  // One POST to the step. `apply` asks for confirmed_apply - only ever from a click the user confirmed.
  async function runStudioEditDocumentPlan(options = {}, {apply = false} = {}) {
    const projectId = Number(state.studioProjectId || 0);
    if (!projectId) return setMessage('Chưa có project.', 'error');
    if (studioEditPlanRunning) return null;
    studioEditPlanRunning = true;
    const box = $('studioEditPlanState');
    if (box) box.innerHTML = apply ? '<b>Đang lập và áp kế hoạch dựng…</b>' : '<b>AI đang lập kế hoạch dựng…</b>';
    try {
      const body = {options: {...options}};
      if (apply) body.options.confirmed_apply = true;
      const response = await api(`/api/projects/${projectId}/steps/edit_plan`, {method: 'POST', body: JSON.stringify(body)});
      const result = response?.result || {};
      const plan = editPlanOutcome(result);
      const applied = editApplyOutcome(result.applied);
      let text = plan.text;
      if (applied) text += ` ${applied.text}`;
      else if (apply && plan.ok) text += ' Chưa áp: máy chủ không báo kết quả áp.';
      else if (!apply && result.status === 'planned') text += ` Chưa áp vào timeline: bấm “2. Áp dụng kế hoạch dựng” để áp. ${EDIT_DOC_AUTO_APPLY_NOTE}`;
      const ok = plan.ok && (apply ? Boolean(applied?.ok) : true);
      const type = ok ? ((applied || plan).type || plan.type) : 'error';
      await refreshStudioStoryboard();
      setMessage(text, type);
      if (box) box.innerHTML = `${editDocumentHeadline()}<div class="${ok ? 'secondary-text' : 'warning-text'}" style="margin-top:4px">${esc(text)}</div>`;
      return result;
    } catch (error) {
      if (box) box.innerHTML = `<b>Không lập được kế hoạch dựng.</b> ${esc(error.message)}`;
      setMessage(`Không lập được kế hoạch dựng: ${error.message}`, 'error');
      return null;
    } finally {
      studioEditPlanRunning = false;
    }
  }

  async function planStudioEditDocument(options = {}) {
    const what = options.scene_keys ? 'cảnh này' : 'các cảnh chưa có kế hoạch dựng hoặc đã cũ';
    if (!confirm(`AI sẽ lập kế hoạch dựng cho ${what} (EditDocument).\nChưa áp vào timeline cho tới khi bạn bấm “2. Áp dụng kế hoạch dựng”.\n\nTiếp tục?`)) return null;
    return runStudioEditDocumentPlan(options);
  }

  async function applyStudioEditDocument() {
    if (!confirm('Áp kế hoạch dựng vào timeline?\n\nCác cảnh đã lập trong EditDocument được ghi vào timeline; hình hiện có của cảnh được giữ. Cảnh chưa lập hoặc đã cũ sẽ được AI lập trước rồi áp luôn. Cảnh đã bị sửa ngoài EditDocument sẽ báo xung đột, không bị ghi đè.\n\nTiếp tục?')) return null;
    return runStudioEditDocumentPlan({}, {apply: true});
  }

  // A scene's own button: that scene alone, planned again even when its edit still holds.
  async function planStudioEditDocumentScene(segmentId) {
    const doc = state.studioEditDocument;
    const scene = doc?.state === 'current' ? studioEditDocumentScene({id: segmentId}, doc) : null;
    if (!scene) return setMessage('Cảnh này chưa có trong EditDocument hiện tại. Bấm “1. Lập kế hoạch dựng” trước.', 'error');
    return planStudioEditDocument({scene_keys: [scene.scene_key], replan: true});
  }
  // ---- hết Bước 5 · EditDocument ----

  function storyboardSceneFacts(shot, segment) {
    const hasVisual = Boolean(segment && String(segment.visual_path || '').trim());
    const hasAudio = Boolean(segment && String(segment.audio_path || '').trim());
    const fallback = hasVisual && String(segment.asset_type || '') === 'fallback';
    const draft = hasVisual && String(segment.visual_path || '').replaceAll('\\', '/').includes('director_draft_visuals');
    const missingVisual = !hasVisual;
    const missingAudio = !hasAudio;
    let state = 'ready';
    let label = 'Sẵn sàng';
    if (missingVisual && missingAudio) { state = 'missing_both'; label = 'Thiếu hình + tiếng'; }
    else if (missingVisual) { state = 'missing_visual'; label = 'Thiếu hình'; }
    else if (missingAudio) { state = 'missing_audio'; label = 'Thiếu tiếng'; }
    else if (draft) { state = 'draft'; label = 'Visual nháp'; }
    else if (fallback) { state = 'fallback'; label = 'Dự phòng'; }
    return {state, label, missingVisual, missingAudio, fallback, draft, ready: hasVisual && hasAudio && !draft};
  }

  function storyboardSceneState(shot, segment) {
    return storyboardSceneFacts(shot, segment).state;
  }

  function filterStudioStoryboard(filter = 'all') {
    document.querySelectorAll('#studioStoryboardResult .storyboard-card[data-scene-state]').forEach((card) => {
      const matches = filter === 'all'
        || (filter === 'missing_visual' && card.dataset.missingVisual === '1')
        || (filter === 'missing_audio' && card.dataset.missingAudio === '1')
        || (filter === 'ready' && card.dataset.ready === '1');
      card.hidden = !matches;
    });
    document.querySelectorAll('#studioStoryboardResult [data-storyboard-filter]').forEach((button) => {
      button.classList.toggle('primary', button.dataset.storyboardFilter === filter);
      button.classList.toggle('ghost', button.dataset.storyboardFilter !== filter);
    });
  }

  function editBeatsForSegment(segment) {
    return Array.isArray(segment?.edit_beats) ? segment.edit_beats : [];
  }

  function editBeatSelect(value, labels, className) {
    return `<select class="${className}">` + Object.entries(labels).map(([key, label]) =>
      `<option value="${key}"${String(value || '') === key ? ' selected' : ''}>${esc(label)}</option>`
    ).join('') + '</select>';
  }

  function storyboardEditSummary(segment) {
    if (!segment) return '';
    return `<div class="storyboard-edit-cell" data-edit-doc-segment="${Number(segment.id || 0)}">${storyboardEditCell(segment)}</div>`;
  }

  function legacyStoryboardEditSummary(segment, heading = 'Kế hoạch dựng') {
    if (!segment) return '';
    const beats = editBeatsForSegment(segment);
    const transition = segment.edit_transition || 'fade';
    const effect = segment.edit_effect || 'static';
    if (!beats.length) {
      return `<div class="storyboard-edit-summary muted"><b>Kế hoạch dựng:</b> chưa lập. <button class="btn small ghost" type="button" onclick="planStudioSceneEdit(${segment.id})">Lập kế hoạch cảnh này</button></div>`;
    }
    const inserts = beats.filter((beat) => String(beat.source_kind || '') !== 'primary').length;
    const needs = beats.filter((beat) => ['needs_asset', 'generating', 'error'].includes(String(beat.status || ''))).length;
    const sourceLabels = {primary: 'Clip/hình chính', source_frame: 'Frame từ clip gốc', ai_image: 'Ảnh AI phụ'};
    const effectLabels = {static: 'Giữ khung', zoom_in: 'Zoom vào', zoom_out: 'Zoom ra'};
    const transitionLabels = {cut: 'Cắt thẳng', fade: 'Mờ dần'};
    const labels = {
      ready: 'sẵn sàng',
      needs_asset: 'thiếu ảnh/frame',
      generating: 'đang tạo ảnh',
      error: 'lỗi tạo ảnh',
    };
    const statusText = needs
      ? `${needs} nhịp chưa xong`
      : 'đủ dữ liệu';
    const detail = beats.map((beat) => `${beat.beat_index || '?'}:${labels[beat.status] || beat.status || 'sẵn sàng'}`).join(' · ');
    const rows = beats.map((beat, index) => `
      <div class="storyboard-edit-beat-row" data-beat-id="${Number(beat.id || 0)}" data-asset-id="${Number(beat.asset_id || 0)}" data-visual-path="${esc(beat.visual_path || '')}">
        <span>${index + 1}</span>
        ${editBeatSelect(beat.source_kind || 'primary', sourceLabels, 'beat-source')}
        <input class="beat-duration" type="number" min="0.15" step="0.1" value="${Number(beat.duration_seconds || 1).toFixed(1)}" aria-label="Thời lượng nhịp">
        ${editBeatSelect(beat.effect || 'static', effectLabels, 'beat-effect')}
        ${editBeatSelect(beat.transition || 'cut', transitionLabels, 'beat-transition')}
        <input class="beat-prompt" value="${esc(beat.prompt || '')}" placeholder="Prompt ảnh phụ nếu chọn Ảnh AI">
        <em>${esc(labels[beat.status] || beat.status || 'sẵn sàng')}</em>
      </div>`).join('');
    return `<div class="storyboard-edit-summary" data-edit-segment="${segment.id}"><b>${esc(heading)}:</b> ${beats.length} nhịp · ${inserts} frame/ảnh phụ · ${esc(statusText)} · hiệu ứng ${esc(effect)} · chuyển ${esc(transition)}<div class="secondary-text">${esc(detail)}</div><details><summary>Sửa kế hoạch cảnh</summary><div class="storyboard-edit-beats">${rows}</div><div class="queue-controls" style="justify-content:flex-start;margin-top:7px;gap:6px;flex-wrap:wrap"><button class="btn small ghost" type="button" onclick="planStudioSceneEdit(${segment.id})">Lập lại kế hoạch cảnh</button><button class="btn small ghost" type="button" onclick="saveStudioSceneEditPlan(${segment.id})">Lưu kế hoạch cảnh</button><button class="btn small primary" type="button" onclick="applyStudioSceneEdit(${segment.id})">Áp dụng cảnh này</button></div></details></div>`;
  }

  async function studioEditBeatGenerationSettings(resolveProvider = true, forcedProvider = '') {
    let imageProvider = forcedProvider || $('studioEditPlanProviderSelect')?.value || 'phantom_canvas_image';
    if (resolveProvider) imageProvider = await resolveAutoSceneProvider(imageProvider, 'scene.image');
    return {
      image_provider: imageProvider,
      ratio: $('studioEditPlanRatioSelect')?.value || $('studioSceneRatioSelect')?.value || '1280:720',
      confirmed: true,
    };
  }

  function collectStudioSceneEditBeats(segmentId) {
    const segment = (state.timeline || []).find((item) => Number(item.id) === Number(segmentId));
    const host = document.querySelector(`[data-edit-segment="${segmentId}"]`);
    if (!segment || !host) return null;
    const beats = [...host.querySelectorAll('.storyboard-edit-beat-row')].map((row) => {
      const sourceKind = row.querySelector('.beat-source')?.value || 'primary';
      const assetId = sourceKind === 'primary' ? null : (Number(row.dataset.assetId || 0) || null);
      const visualPath = sourceKind === 'ai_image'
        ? String(row.dataset.visualPath || '')
        : String(segment.visual_path || '');
      return {
        asset_id: assetId,
        visual_path: visualPath,
        source_kind: sourceKind,
        duration_seconds: Number(row.querySelector('.beat-duration')?.value || 0),
        effect: row.querySelector('.beat-effect')?.value || 'static',
        transition: row.querySelector('.beat-transition')?.value || 'cut',
        prompt: row.querySelector('.beat-prompt')?.value || '',
        status: sourceKind === 'ai_image' && !visualPath ? 'needs_asset' : 'ready',
      };
    });
    if (beats.some((beat) => !Number.isFinite(beat.duration_seconds) || beat.duration_seconds < 0.15)) {
      setMessage('Thời lượng mỗi nhịp dựng phải từ 0.15 giây trở lên.', 'error');
      return null;
    }
    return beats;
  }

  async function saveStudioSceneEditPlan(segmentId, quiet = false) {
    const beats = collectStudioSceneEditBeats(segmentId);
    if (!beats) return null;
    try {
      const result = await api(`/api/timeline/${segmentId}/edit-beats`, {
        method: 'PUT', body: JSON.stringify({beats}),
      });
      await refreshStudioStoryboard();
      if (!quiet) setMessage(`Đã lưu kế hoạch dựng ${beats.length} nhịp cho cảnh này.`, 'success');
      return result;
    } catch (error) {
      if (!quiet) setMessage(`Không lưu được kế hoạch dựng: ${error.message}`, 'error');
      return null;
    }
  }

  async function planStudioSceneEdit(segmentId, options = {}) {
    if (!state.studioProjectId) return setMessage('Chưa có project.', 'error');
    if (options.flow !== 'legacy') {
      const flow = await studioEditFlowNow();
      if (flow === 'plan') return planStudioEditDocumentScene(segmentId);
      if (!flow) return studioEditFlowUnknown();
    }
    const segment = (state.timeline || []).find((item) => Number(item.id) === Number(segmentId));
    if (!segment) return setMessage('Không tìm thấy cảnh trong storyboard hiện tại.', 'error');
    const button = options.button || null;
    if (button) button.disabled = true;
    if (!options.quiet) setMessage(`AI đang lập kế hoạch dựng cảnh ${segment.segment_index || ''}...`);
    try {
      const plan = await api(`/api/timeline/${segmentId}/edit-beats/plan`, {
        method: 'POST', body: JSON.stringify({max_beats: 4}),
      });
      if (!options.skipRefresh) await refreshStudioStoryboard();
      if (!options.quiet) {
        setMessage(`Đã lập kế hoạch dựng cảnh ${segment.segment_index || ''}. Hãy xem/sửa rồi bấm Áp dụng.`, 'success');
      }
      return plan;
    } catch (error) {
      if (!options.quiet) setMessage(`Không lập được kế hoạch cảnh ${segment.segment_index || ''}: ${error.message}`, 'error');
      throw error;
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function applyStudioSceneEdit(segmentId, options = {}) {
    if (!state.studioProjectId) return setMessage('Chưa có project.', 'error');
    const segment = (state.timeline || []).find((item) => Number(item.id) === Number(segmentId));
    if (!segment) return setMessage('Không tìm thấy cảnh trong storyboard hiện tại.', 'error');
    const currentBeats = editBeatsForSegment(segment);
    if (!currentBeats.length) return setMessage('Cảnh này chưa có kế hoạch dựng. Hãy lập kế hoạch trước.', 'error');
    const saved = document.querySelector(`[data-edit-segment="${segmentId}"]`)
      ? await saveStudioSceneEditPlan(segmentId, true)
      : {beats: currentBeats};
    const beats = saved?.beats || currentBeats;
    const needsAi = beats.some((beat) =>
      String(beat.source_kind || '') === 'ai_image' && !String(beat.visual_path || '').trim()
    );
    if (needsAi && !options.confirmed && !confirm('Kế hoạch có ảnh AI phụ và có thể dùng hạn mức provider đã chọn. Áp dụng cảnh này?')) return null;
    try {
      const settings = await studioEditBeatGenerationSettings(needsAi, options.imageProvider || '');
      settings.confirmed = needsAi;
      const result = await api(`/api/timeline/${segmentId}/edit-beats/apply`, {
        method: 'POST', body: JSON.stringify(settings),
      });
      const jobs = result.queued_jobs || [];
      jobs.forEach((job) => { if (job.id) void watchStudioSceneGenerationJob(job.id, 'long'); });
      if (!options.skipRefresh) await refreshStudioStoryboard();
      if (!options.quiet) {
        const pending = jobs.length ? ` · gửi tạo ${jobs.length} ảnh AI phụ` : '';
        setMessage(`Đã áp dụng kế hoạch dựng cảnh ${segment.segment_index || ''}${pending}.`, 'success');
      }
      return {result, jobs};
    } catch (error) {
      if (!options.quiet) setMessage(`Không áp dụng được kế hoạch cảnh ${segment.segment_index || ''}: ${error.message}`, 'error');
      throw error;
    }
  }

  async function planAllStudioSceneEdits() {
    const flow = await studioEditFlowNow();
    if (flow === 'plan') return planStudioEditDocument();
    if (!flow) return studioEditFlowUnknown();
    const segments = (state.timeline || []).filter((segment) => Number(segment.id));
    if (!segments.length) return setMessage('Storyboard chưa có cảnh để lập kế hoạch dựng. Hãy tạo timeline/storyboard trước.', 'error');
    if (!confirm(`AI sẽ lập kế hoạch dựng cho ${segments.length} cảnh. Sau bước này bạn có thể mở từng thẻ cảnh để sửa nhịp hình, hiệu ứng, chuyển cảnh và prompt ảnh phụ trước khi áp dụng.\n\nTiếp tục?`)) return;
    const button = $('studioBuildEditPlanButton');
    const stateBox = $('studioEditPlanState');
    if (button) button.disabled = true;
    let planned = 0;
    const failed = [];
    try {
      for (let index = 0; index < segments.length; index += 1) {
        const segment = segments[index];
        const labelIndex = segment.segment_index || index + 1;
        const percent = Math.round(5 + (80 * index / Math.max(1, segments.length)));
        setStudioProgress(percent, `AI đang lập kế hoạch cảnh ${labelIndex} · ${index}/${segments.length} đã xong...`);
        if (stateBox) stateBox.innerHTML = `<b>Đang lập kế hoạch:</b> cảnh ${esc(labelIndex)} · ${index}/${segments.length} đã xong.`;
        try {
          await planStudioSceneEdit(Number(segment.id), {quiet: true, skipRefresh: true, flow: 'legacy'});
          planned += 1;
        } catch (error) {
          failed.push(`cảnh ${labelIndex}: ${error.message}`);
        }
      }
      await refreshStudioStoryboard();
      setStudioProgress(100, failed.length ? `Đã lập ${planned}/${segments.length} kế hoạch, còn lỗi.` : `Đã lập ${planned}/${segments.length} kế hoạch.`);
      const summary = failed.length
        ? `Đã lập ${planned}/${segments.length} kế hoạch. Lỗi: ${failed.slice(0, 3).join('; ')}`
        : `Đã lập kế hoạch dựng cho ${planned} cảnh. Hãy xem/sửa từng cảnh rồi bấm “Áp dụng kế hoạch dựng”.`;
      if (stateBox) stateBox.innerHTML = failed.length
        ? `<b>Cần kiểm tra:</b> ${esc(summary)}`
        : `<b>Đã lập kế hoạch.</b> ${esc(summary)}`;
      setMessage(summary, failed.length ? 'error' : 'success');
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function applyAllStudioSceneEdits() {
    const flow = await studioEditFlowNow();
    if (flow === 'plan') return applyStudioEditDocument();
    if (!flow) return studioEditFlowUnknown();
    const segments = (state.timeline || []).filter((segment) => Number(segment.id));
    if (!segments.length) return setMessage('Storyboard chưa có cảnh để áp dụng kế hoạch dựng.', 'error');
    const missingPlan = segments.filter((segment) => !editBeatsForSegment(segment).length);
    if (missingPlan.length) {
      return setMessage(`Còn ${missingPlan.length} cảnh chưa có kế hoạch dựng. Hãy bấm “Lập kế hoạch dựng” trước.`, 'error');
    }
    let provider = $('studioEditPlanProviderSelect')?.value || 'phantom_canvas_image';
    try {
      provider = await resolveAutoSceneProvider(provider, 'scene.image');
    } catch (error) {
      return setMessage(`Auto không chọn được provider ảnh phụ: ${error.message}`, 'error');
    }
    const warning = await sidecarWarningText(provider);
    const label = typeof sceneProviderLabel === 'function' ? sceneProviderLabel(provider) : provider;
    if (!confirm(`Áp dụng kế hoạch dựng cho ${segments.length} cảnh bằng ${label} nếu cần tạo ảnh phụ.\n\nBước này sẽ trích frame, gửi tạo ảnh AI phụ và render sau đó sẽ dùng trực tiếp các nhịp dựng đã lưu.${warning ? `\n\n${warning}` : ''}\n\nTiếp tục?`)) return;
    const button = $('studioApplyEditPlanToScenesButton');
    const stateBox = $('studioEditPlanState');
    if (button) button.disabled = true;
    let applied = 0;
    let queued = 0;
    const failed = [];
    try {
      for (let index = 0; index < segments.length; index += 1) {
        const segment = segments[index];
        const labelIndex = segment.segment_index || index + 1;
        const percent = Math.round(5 + (80 * index / Math.max(1, segments.length)));
        setStudioProgress(percent, `Đang áp dụng kế hoạch cảnh ${labelIndex} · ${index}/${segments.length} đã xong...`);
        if (stateBox) stateBox.innerHTML = `<b>Đang áp dụng:</b> cảnh ${esc(labelIndex)} · ${index}/${segments.length} đã xong.`;
        try {
          const result = await applyStudioSceneEdit(Number(segment.id), {quiet: true, skipRefresh: true, confirmed: true, imageProvider: provider});
          applied += 1;
          queued += (result?.jobs || []).length;
        } catch (error) {
          failed.push(`cảnh ${labelIndex}: ${error.message}`);
        }
      }
      await refreshStudioStoryboard();
      setStudioProgress(100, failed.length ? `Đã áp dụng ${applied}/${segments.length} cảnh, còn lỗi.` : `Đã áp dụng ${applied}/${segments.length} cảnh.`);
      const summary = failed.length
        ? `Đã áp dụng ${applied}/${segments.length} cảnh, gửi tạo ${queued} ảnh AI phụ. Lỗi: ${failed.slice(0, 3).join('; ')}`
        : `Đã áp dụng kế hoạch dựng cho ${applied} cảnh${queued ? ` và gửi tạo ${queued} ảnh AI phụ` : ''}.`;
      if (stateBox) stateBox.innerHTML = failed.length
        ? `<b>Cần kiểm tra:</b> ${esc(summary)}`
        : `<b>Đã áp dụng.</b> ${esc(summary)} Render sẽ dùng các nhịp dựng này.`;
      setMessage(summary, failed.length ? 'error' : 'success');
    } finally {
      if (button) button.disabled = false;
    }
  }

  function storyboardShotForSegment(segment, shots = state.shots || []) {
    return shots.find((shot) => Number(shot.id) === Number(segment?.shot_id))
      || shots.find((shot) => Number(shot.shot_index) === Number(segment?.segment_index))
      || null;
  }

  function storyboardSegmentForShot(shot, timeline = state.timeline || []) {
    return timeline.find((item) => Number(item.shot_id) === Number(shot?.id))
      || timeline.find((item) => Number(item.segment_index) === Number(shot?.shot_index))
      || null;
  }

  function renderStudioGraphicPlan(plan) {
    const target = $('studioGraphicPlanState');
    if (!target) return;
    const scenes = Array.isArray(plan?.scenes) ? plan.scenes : [];
    if (!scenes.length) { target.textContent = 'Chưa có kế hoạch đồ họa.'; return; }
    const rows = scenes.map((scene) => {
      const overlays = Array.isArray(scene.overlays) ? scene.overlays : [];
      const labels = overlays.length
        ? overlays.map((item) => `${esc(item.text || '')} · ${esc(item.style || 'clean')} / ${esc(item.animation || 'fade')} · ${Number(item.start_seconds || 0).toFixed(1)}–${Number(item.end_seconds || 0).toFixed(1)}s`).join('<br>')
        : 'Không cần chữ động';
      return `<div style="margin-top:6px"><b>Cảnh ${esc(scene.segment_index || '')}</b> · ${esc(scene.visual_strategy || '')}<br>${labels}</div>`;
    }).join('');
    // A plan the app filled in from a template looks exactly like an AI plan
    // once it is saved, so the one moment it can still be named is here.
    const fallbackNote = plan?.is_fallback
      ? `<div class="warning-text"><b>Đây KHÔNG phải kế hoạch của AI.</b> AI điều phối không chạy được nên app dùng mẫu dựng sẵn${plan.planner_error ? `: ${esc(plan.planner_error)}` : '.'}</div>`
      : '';
    target.innerHTML = `${fallbackNote}<b>Bản nháp ${scenes.length} cảnh.</b> Xem lớp chữ và lựa chọn visual trước khi áp dụng.<details><summary>Xem từng cảnh</summary>${rows}</details>`;
  }

  async function planStudioGraphics() {
    if (!state.studioProjectId) return setMessage('Hãy tạo storyboard trước.', 'error');
    const flow = await studioEditFlowNow();
    if (flow === 'plan') return planStudioEditDocument();
    if (!flow) return studioEditFlowUnknown();
    const target = $('studioGraphicPlanState');
    if (target) target.textContent = 'AI đang lập kế hoạch dựng và chữ động...';
    try {
      const plan = await api(`/api/projects/${state.studioProjectId}/edit-plan`, {method: 'POST'});
      renderStudioGraphicPlan(plan);
      if (plan?.is_fallback) {
        setMessage('AI điều phối không chạy được nên đây là kế hoạch mẫu của app, không phải bản dựng do AI quyết định.', 'error');
      } else {
        setMessage('Đã lập kế hoạch. Xem từng cảnh rồi bấm Duyệt và áp dụng.', 'success');
      }
    } catch (error) {
      if (target) target.textContent = `Không lập được kế hoạch: ${error.message}`;
      setMessage(`Không lập được kế hoạch: ${error.message}`, 'error');
    }
  }

  async function applyStudioGraphics() {
    if (!state.studioProjectId) return setMessage('Hãy tạo storyboard trước.', 'error');
    const flow = await studioEditFlowNow();
    if (flow === 'plan') return applyStudioEditDocument();
    if (!flow) return studioEditFlowUnknown();
    const base = `/api/projects/${state.studioProjectId}/edit-plan`;
    try {
      const current = await api(base);
      if (current.status === 'missing' || current.status === 'stale') {
        return setMessage('Kế hoạch chưa có hoặc đã cũ. Hãy lập lại.', 'error');
      }
      if (current.status === 'ready') {
        return setMessage('Kế hoạch này đã áp dụng. Hãy lập lại nếu muốn thay đổi.', 'success');
      }
      if (current.status === 'draft') await api(`${base}/approve`, {method: 'POST'});
      const result = await api(`${base}/apply`, {method: 'POST'});
      await refreshStudioStoryboard();
      const target = $('studioGraphicPlanState');
      if (target) target.textContent = `Đã áp dụng ${result.applied_scenes || 0} cảnh. Lớp chữ sẽ xuất hiện trong bản render tiếp theo.`;
      setMessage('Đã áp dụng kế hoạch dựng và chữ động.', 'success');
    } catch (error) {
      setMessage(`Không áp dụng được kế hoạch: ${error.message}`, 'error');
    }
  }

  function storyboardGraphicSummary(segment) {
    let graphics = segment?.overlays || [];
    try { if (typeof graphics === 'string') graphics = JSON.parse(graphics); } catch (_) { graphics = []; }
    if (!Array.isArray(graphics)) graphics = [];
    const rows = graphics.length
      ? graphics.map((item) => `<div>${esc(item.text || '')} · ${esc(item.style || 'clean')} / ${esc(item.animation || 'fade')} · ${Number(item.start_seconds || 0).toFixed(1)}–${Number(item.end_seconds || 0).toFixed(1)}s</div>`).join('')
      : '<div class="secondary-text">Chưa có lớp chữ động.</div>';
    return `<details class="storyboard-edit-summary"><summary>Chữ động: ${graphics.length} lớp</summary>${rows}<div class="queue-controls" style="justify-content:flex-start;margin-top:7px"><button class="btn small ghost" type="button" onclick="editStudioSceneOverlays(${Number(segment?.id || 0)})">Sửa chữ động</button></div></details>`;
  }

  function storyboardSoundCueSummary(segment) {
    let cues = segment?.sound_cues || [];
    try { if (typeof cues === 'string') cues = JSON.parse(cues); } catch (_) { cues = []; }
    if (!Array.isArray(cues)) cues = [];
    const rows = cues.length
      ? cues.map((item) => `<div>${esc(item.type || 'sfx')} · ${esc(item.intensity || 'medium')} · ${Number(item.start_seconds || 0).toFixed(1)}–${Number(item.end_seconds || 0).toFixed(1)}s</div>`).join('')
      : '<div class="secondary-text">Chưa có cue âm thanh.</div>';
    return `<details class="storyboard-edit-summary"><summary>Âm thanh nhấn nhịp: ${cues.length} cue</summary>${rows}<div class="queue-controls" style="justify-content:flex-start;margin-top:7px"><button class="btn small ghost" type="button" onclick="editStudioSceneSoundCues(${Number(segment?.id || 0)})">Sửa SFX</button></div></details>`;
  }

  function parseSceneJsonField(segment, key) {
    let value = segment?.[key] || [];
    try { if (typeof value === 'string') value = JSON.parse(value); } catch (_) { value = []; }
    return Array.isArray(value) ? value : [];
  }

  async function editStudioSceneJsonLayer(segmentId, key, label, emptyTemplate) {
    const segment = (state.timeline || []).find((item) => Number(item.id) === Number(segmentId));
    if (!segment) return setMessage('Không tìm thấy cảnh trong storyboard hiện tại.', 'error');
    const current = parseSceneJsonField(segment, key);
    const initial = JSON.stringify(current.length ? current : emptyTemplate, null, 2);
    const raw = window.prompt(`Sửa ${label} bằng JSON array. Để [] nếu không dùng.`, initial);
    if (raw == null) return;
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (error) {
      return setMessage(`${label} không phải JSON hợp lệ: ${error.message}`, 'error');
    }
    if (!Array.isArray(parsed)) return setMessage(`${label} phải là JSON array.`, 'error');
    try {
      await api(`/api/timeline/${segmentId}/plan`, {
        method: 'PATCH',
        body: JSON.stringify({[key]: parsed}),
      });
      await refreshStudioStoryboard();
      setMessage(`Đã lưu ${label} cho cảnh ${segment.segment_index || ''}.`, 'success');
    } catch (error) {
      setMessage(`Không lưu được ${label}: ${error.message}`, 'error');
    }
  }

  async function editStudioSceneOverlays(segmentId) {
    await editStudioSceneJsonLayer(segmentId, 'overlays', 'chữ động', [{
      kind: 'callout',
      text: 'Điểm chính',
      position: 'top_center',
      style: 'card',
      animation: 'pop',
      start_seconds: 0.2,
      end_seconds: 2.0,
    }]);
  }

  async function editStudioSceneSoundCues(segmentId) {
    await editStudioSceneJsonLayer(segmentId, 'sound_cues', 'SFX', [{
      type: 'whoosh',
      start_seconds: 0.2,
      end_seconds: 0.7,
      intensity: 'low',
    }]);
  }

  function renderStudioStoryboard(shots = [], timeline = [], containerId = 'studioStoryboardResult') {
    const result = $(containerId);
    if (!result) return;
    // The project-resume path used to pass the loaded timeline only to this
    // renderer.  The cards looked correct, but every action read an empty
    // state.timeline and reported “Storyboard chưa có cảnh”.  Keep the long
    // storyboard state in sync with exactly what is visible.  The Short lane
    // uses another container and must not replace the long timeline.
    if (containerId === 'studioStoryboardResult') {
      state.timeline = Array.isArray(timeline) ? timeline : [];
      state.studioEditDocumentLoad = refreshStudioEditDocument();
    }
    if (!shots.length) {
      result.innerHTML = '<div class="studio-empty">Chưa có cảnh. Hãy tạo storyboard hoặc mở chỉnh sửa chi tiết để thêm cảnh.</div>';
      return;
    }
    const summary = {ready: 0, missing_visual: 0, missing_audio: 0, fallback: 0, draft: 0};
    shots.forEach((shot) => {
      const segment = storyboardSegmentForShot(shot, timeline);
      const facts = storyboardSceneFacts(shot, segment);
      if (facts.ready) summary.ready += 1;
      if (facts.missingVisual) summary.missing_visual += 1;
      if (facts.missingAudio) summary.missing_audio += 1;
      if (facts.fallback) summary.fallback += 1;
      if (facts.draft) summary.draft += 1;
    });
    const summaryBar = containerId === 'studioStoryboardResult' ? `<div class="storyboard-status-bar">
      <b>${shots.length} cảnh</b><span class="status-ready">${summary.ready} sẵn sàng</span>
      <span>${summary.missing_visual} thiếu hình</span><span>${summary.missing_audio} thiếu tiếng</span>
      ${summary.fallback ? `<span>${summary.fallback} dự phòng</span>` : ''}
      <div class="storyboard-filter-row"><button class="btn small primary" data-storyboard-filter="all" onclick="filterStudioStoryboard('all')">Tất cả</button><button class="btn small ghost" data-storyboard-filter="missing_visual" onclick="filterStudioStoryboard('missing_visual')">Thiếu hình</button><button class="btn small ghost" data-storyboard-filter="missing_audio" onclick="filterStudioStoryboard('missing_audio')">Thiếu tiếng</button><button class="btn small ghost" data-storyboard-filter="ready" onclick="filterStudioStoryboard('ready')">Sẵn sàng</button></div>
    </div>` : '';
    result.innerHTML = narrationSourceNotice() + summaryBar + `<div class="storyboard-grid">${shots.map((shot, index) => {
      const segment = storyboardSegmentForShot(shot, timeline);
      const sceneFacts = storyboardSceneFacts(shot, segment);
      const sceneState = sceneFacts.state;
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
      const shotVisualPath = String(segment?.visual_path || '');
      const wantsVisual = String(shot.status || '') === 'needs_visual';
      const optionalMediaTools = `<details style="margin-top:9px"><summary class="secondary-text">Thay ảnh/video bằng AI (tùy chọn)</summary><div class="queue-controls" style="justify-content:flex-start;margin-top:7px;flex-wrap:wrap"><select id="studioShotSceneRatio-${shot.id}" aria-label="Định dạng kích thước"><option value="1280:720">Ngang 16:9</option><option value="720:1280">Dọc 9:16</option><option value="1024:1024">Vuông 1:1</option></select><select id="studioShotImageProvider-${shot.id}" aria-label="Engine tạo ảnh AI">${IMAGE_PROVIDER_OPTIONS}</select><button class="btn small primary" type="button" onclick="generateStudioShotImage(${shot.id})">Tạo ảnh AI</button><select id="studioShotVideoProvider-${shot.id}" aria-label="Engine tạo video AI">${VIDEO_PROVIDER_OPTIONS}</select><button class="btn small primary" type="button" onclick="generateStudioShotVideo(${shot.id})">${/\.(jpg|jpeg|png|webp|bmp|gif)$/i.test(shotVisualPath) ? 'Tạo video AI từ ảnh' : 'Cần tạo ảnh trước'}</button></div></details>`;
      return `
      <div class="storyboard-card" data-segment-id="${segment?.id || ''}" data-scene-state="${sceneState}" data-missing-visual="${sceneFacts.missingVisual ? '1' : '0'}" data-missing-audio="${sceneFacts.missingAudio ? '1' : '0'}" data-ready="${sceneFacts.ready ? '1' : '0'}"${wantsVisual ? ' style="outline:1px solid var(--danger,#e5484d)"' : ''}>
        <div class="storyboard-card-head"><span class="storyboard-card-title">Cảnh ${shot.shot_index || index + 1} · ${Number(shot.duration_seconds || 0).toFixed(1)} giây</span><span class="storyboard-state storyboard-state-${sceneState}">${sceneFacts.label}</span></div>
        <div class="storyboard-media">${preview}</div>
        <div class="storyboard-body"><div class="storyboard-narration"><b>Lời AI sẽ đọc</b>${esc(spokenText || 'Chưa có lời dẫn cho cảnh này.')}</div>${audioPreview}${voiceControls}<div class="storyboard-prompt">${wantsVisual ? '⊕ <b>Cảnh này thiếu hình minh hoạ.</b> ' : ''}${esc(shot.visual_prompt || 'Chưa có visual prompt')}</div>${storyboardEditSummary(segment)}${storyboardGraphicSummary(segment)}${storyboardSoundCueSummary(segment)}<div class="storyboard-summary"><span>${esc(shot.asset_type || 'generated')}</span></div><div class="queue-controls" style="justify-content:flex-start;margin-top:9px;flex-wrap:wrap"><button class="btn small ghost" onclick="editStudioScene(${shot.id}, ${segment?.id || 0})">Sửa cảnh</button><button class="btn small ghost" type="button" onclick="regenerateStudioShotVoice(${shot.id})">Tạo lại giọng</button></div>${optionalMediaTools}</div>
      </div>`;
    }).join('')}</div>`;
  }

  async function refreshStudioStoryboard() {
    if (!state.studioProjectId) return null;
    const bundle = await api(`/api/projects/${state.studioProjectId}`);
    state.studioProject = bundle.project || state.studioProject;
    state.shots = bundle.latest_shots || [];
    state.timeline = bundle.latest_timeline || [];
    state.projectAssets = bundle.project_assets || [];
    renderStudioStoryboard(state.shots, state.timeline);
    await state.studioEditDocumentLoad;
    return bundle;
  }

  function renderStudioRenderReadiness(check = {}) {
    const total = Number(check.total || 0);
    const missingVisual = Number(check.missing_visual || 0);
    const missingAudio = Number(check.missing_audio || 0);
    const draftVisual = Number(check.draft_visual || 0);
    const visualReady = Math.max(0, total - missingVisual - draftVisual);
    const audioReady = Math.max(0, total - missingAudio);
    const outputLabel = $('studioOutputProfileSelect')?.selectedOptions[0]?.textContent || 'Chưa chọn';
    const summary = $('studioRenderSummary');
    if (summary) summary.innerHTML = [
      `<div class="studio-summary-card"><label>Cảnh</label><strong>${total ? `${Number(check.ready || 0)}/${total} sẵn sàng` : 'Chưa có timeline'}</strong></div>`,
      `<div class="studio-summary-card"><label>Hình</label><strong>${total ? `${visualReady}/${total} hợp lệ` : '—'}</strong></div>`,
      `<div class="studio-summary-card"><label>Giọng đọc</label><strong>${total ? `${audioReady}/${total} đã gắn` : '—'}</strong></div>`,
      `<div class="studio-summary-card"><label>Đầu ra</label><strong>${esc(outputLabel)}</strong></div>`,
    ].join('');
    const note = $('studioRenderReadinessNote');
    const issues = Array.isArray(check.issues) ? check.issues : [];
    if (note) {
      note.className = `studio-model-note${check.can_render ? ' status-ready' : ''}`;
      note.innerHTML = check.can_render
        ? '<b>Sẵn sàng dựng.</b> Tất cả cảnh đã có hình thật và voice.'
        : total
          ? `<b>Chưa thể dựng:</b> ${esc(issues.join(' · ') || 'cảnh chưa hoàn chỉnh')}. Quay lại Storyboard và lọc cảnh thiếu để bổ sung.`
          : '<b>Chưa có timeline.</b> Hãy tạo storyboard trước.';
    }
    const renderButton = $('studioQueueRenderButton');
    if (renderButton) renderButton.disabled = !check.can_render;
  }

  async function refreshStudioRenderReadiness() {
    if (!state.studioProjectId) return null;
    try {
      const check = await api(`/api/projects/${state.studioProjectId}/render-readiness`);
      renderStudioRenderReadiness(check);
      return check;
    } catch (error) {
      const note = $('studioRenderReadinessNote');
      if (note) note.textContent = `Không kiểm tra được dữ liệu dựng: ${error.message}`;
      return null;
    }
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
  const NO_KEY_SCENE_PROVIDERS = new Set(['motion_graphics', 'stock_footage']);

  async function resolveAutoSceneProvider(provider, capability) {
    const selected = String(provider || '').trim() || 'auto';
    if (selected !== 'auto') return selected;
    const projectId = Number(state.studioProjectId || state.projectId || 0) || null;
    const route = await api('/api/providers/route', {
      method: 'POST',
      body: JSON.stringify({project_id: projectId, capability}),
    });
    if (!route?.selected_provider) throw new Error(route?.reason || 'Router chưa trả về provider phù hợp.');
    return route.selected_provider;
  }

  function sceneProviderReadiness(provider, isVeo = false) {
    if (provider === 'auto') {
      return {ready: true, integrationKey: '', message: 'AI điều phối sẽ tự chọn provider/tool đang sẵn sàng theo cảnh, quota và chi phí.'};
    }
    if (NO_KEY_SCENE_PROVIDERS.has(provider) || isSubscriptionProvider(provider)) {
      return {ready: true, integrationKey: '', message: ''};
    }
    const integrationKey = provider.startsWith('gemini_') ? 'google_gemini' : 'openai_gpt';
    const ready = Boolean(state.integrations?.find((item) => item.key === integrationKey)?.ready);
    const label = integrationKey === 'google_gemini' ? 'Google Gemini API' : 'OpenAI GPT + Image API';
    return {ready, integrationKey, label, message: ready ? '' : `Cần kết nối <b>${label}</b> trước. Vào Công cụ & kết nối, dán API key rồi bấm “Lưu & bật”.`};
  }

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
    const buildEditPlanButton = $('studioBuildEditPlanButton');
    const applyEditPlanButton = $('studioApplyEditPlanToScenesButton');
    if (buildEditPlanButton) buildEditPlanButton.disabled = !hasProject;
    if (applyEditPlanButton) applyEditPlanButton.disabled = !hasProject;

    const imageButton = $('studioGenerateImagesButton');
    const imageHint = $('studioSceneImageHint');
    if (imageButton) {
      const provider = $('studioSceneImageProviderSelect')?.value || 'gemini_image';
      const readiness = sceneProviderReadiness(provider, false);
      // Keep this action clickable: when the key is absent, a click guides
      // the user to the exact connection card instead of looking broken.
      imageButton.disabled = !hasProject;
      if (imageHint) {
        imageHint.innerHTML = provider === 'auto'
          ? 'Auto: AI điều phối sẽ chọn provider ảnh phù hợp nhất trong các tool đang sẵn sàng.'
          : isSubscriptionProvider(provider)
          ? SUBSCRIPTION_PROVIDER_HINTS[provider]
          : readiness.ready
          ? 'Google Gemini/OpenAI sẽ tạo một ảnh kể chuyện cho mỗi cảnh; FFmpeg tạo chuyển động nhẹ khi dựng video.'
          : readiness.message;
        void sidecarWarningHtml(provider).then((warning) => { if (warning) imageHint.innerHTML += warning; });
      }
    }

    const videoButton = $('studioGenerateVideosButton');
    const videoHint = $('studioSceneVideoHint');
    if (videoButton) {
      const provider = $('studioSceneVideoProviderSelect')?.value || 'gflow_cli';
      const readiness = sceneProviderReadiness(provider, true);
      videoButton.disabled = !hasProject;
      if (videoHint) {
        videoHint.innerHTML = provider === 'auto'
          ? 'Auto: AI điều phối sẽ chọn giữa Veo/Flow, stock footage hoặc motion graphics theo nội dung từng cảnh và tool đang sẵn sàng.'
          : provider === 'motion_graphics'
          ? 'Cảnh sẽ được vẽ bằng motion graphics: biểu đồ động, thẻ số liệu, tiêu đề chuyển động, cảnh terminal. Không tốn credit và không cần API key. Hợp với cảnh trình bày số liệu — thứ không có footage nào quay được.'
          : provider === 'stock_footage'
          ? 'Cảnh sẽ dùng footage thật public-domain từ Archive.org và NASA, cắt đúng thời lượng. Không tốn credit và không cần API key; nguồn từng clip được ghi vào NGUON_FOOTAGE.json trong thư mục dự án.'
          : isSubscriptionProvider(provider)
          ? SUBSCRIPTION_PROVIDER_HINTS[provider]
          : readiness.ready
          ? 'Google Veo sẽ tạo clip video thật cho mỗi cảnh (chậm hơn và tốn credits hơn). Video hoàn tất sẽ hiện trong storyboard.'
          : readiness.message;
        void sidecarWarningHtml(provider).then((warning) => { if (warning) videoHint.innerHTML += warning; });
      }
    }
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
      setMessage(`Đã tạo storyboard gồm ${shots.length} cảnh. Giọng đọc đã có sẵn nên bạn có thể gắn hình cho từng cảnh rồi sang Xưởng dựng.`, 'success');
    } catch (error) { setStudioProgress(0, `Tạo storyboard thất bại: ${error.message}`, 'error'); setMessage(error.message, 'error'); }
    finally { button.disabled = false; }
  }

  async function saveStudioVoiceSettings() {
    if (!state.studioProjectId) return setMessage('Chưa có dự án nào được mở. Thay đổi hiện tại chỉ là xem thử.', 'error');
    const button = $('studioSaveVoiceButton');
    button.disabled = true;
    button.dataset.busy = '1';
    button.textContent = 'Đang lưu…';
    try {
      // A Gemini voice is known only once its list has loaded and a voice is chosen;
      // saving before that would store the page's placeholder.
      if (GEMINI_TTS_PROVIDERS.includes($('studioVoiceProviderSelect')?.value)) await (state.geminiVoicesLoading || Promise.resolve());
      setStudioProgress(20, 'Đang lưu giọng đọc và phụ đề...');
      const saved = await saveRenderSettings(state.studioProjectId);
      // saveRenderSettings has already said why, in the server's words.
      if (!saved) { setStudioProgress(0, 'Lưu cấu hình thất bại.', 'error'); return; }
      if ($('studioVoiceSummary')) $('studioVoiceSummary').innerHTML = `<div class="studio-check"><b>✓</b><span>Đã lưu ${esc($('studioVoiceProviderSelect').selectedOptions[0]?.textContent || '')} · ${esc($('studioVoiceModelSelect').selectedOptions[0]?.textContent || '')} · phụ đề ${esc($('studioSubtitleModelSelect').selectedOptions[0]?.textContent || '')} · ${esc($('studioPublishLanguageSelect').selectedOptions[0]?.textContent || '')}</span></div>`;
      if ($('studioGenerateVoiceoverButton')) $('studioGenerateVoiceoverButton').disabled = false;
      setStudioProgress(100, 'Đã lưu cấu hình giọng đọc và phụ đề.');
      setMessage('Đã lưu model giọng, phụ đề và ngôn ngữ cho project.', 'success');
    } catch (error) { setStudioProgress(0, `Lưu cấu hình thất bại: ${error.message}`, 'error'); setMessage(error.message, 'error'); }
    finally {
      delete button.dataset.busy;
      button.disabled = false;
      if (typeof renderStudioVoiceDesk === 'function') renderStudioVoiceDesk();
    }
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

  async function runStudioSceneBatch(provider, isVeo, buttonId, variant = 'long') {
    if (!state.studioProjectId) return setMessage('Hãy tạo storyboard trước.', 'error');
    try {
      provider = await resolveAutoSceneProvider(provider, isVeo ? 'scene.video' : 'scene.image');
    } catch (error) {
      setStudioProgress(0, 'Auto chưa chọn được provider phù hợp.', 'error');
      return setMessage(`Auto không chọn được provider ${isVeo ? 'video' : 'ảnh'}: ${error.message}`, 'error');
    }
    const readiness = sceneProviderReadiness(provider, isVeo);
    if (!readiness.ready) {
      setWorkspace('settings');
      $('integrationBody')?.scrollIntoView({behavior: 'smooth', block: 'start'});
      setStudioProgress(0, 'Cần kết nối API trước khi tạo cảnh.', 'error');
      return setMessage(`Hãy nhập ${readiness.integrationKey === 'google_gemini' ? 'GEMINI_API_KEY tại thẻ Google Gemini Image + Veo' : 'OPENAI_API_KEY tại thẻ OpenAI GPT + Image API'}, bấm “Lưu & bật”, sau đó quay lại Storyboard.`, 'error');
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
      let referenceImageProvider = selectedImageProvider === 'auto_parallel' ? 'flow_image' : selectedImageProvider;
      if (referenceImageProvider === 'auto') referenceImageProvider = await resolveAutoSceneProvider('auto', 'scene.image');
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
            state.shots = bundle.latest_shots || [];
            state.timeline = bundle.latest_timeline || [];
            state.projectAssets = bundle.project_assets || [];
            renderStudioStoryboard(state.shots, state.timeline);
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
      const check = await api(`/api/projects/${state.studioProjectId}/render-readiness`);
      renderStudioRenderReadiness(check);
      if (!check.total) {
        setStudioStep(4);
        throw new Error('Chưa chia cảnh. Hãy bấm “1. Chia cảnh từ kịch bản” ở bước Giọng đọc trước khi dựng video.');
      }
      if (check.missing_visual) {
        setStudioStep(5);
        throw new Error(`Còn ${check.missing_visual}/${check.total} cảnh thiếu hình. Quay lại Storyboard, lọc “Thiếu hình” rồi gắn hoặc tạo hình cho các cảnh đó.`);
      }
      if (check.draft_visual) {
        setStudioStep(5);
        throw new Error(`Còn ${check.draft_visual} visual draft nội bộ. Hãy thay bằng video AI hoặc ảnh/video thật trước khi render bản xuất bản.`);
      }
      if (check.missing_audio) {
        setStudioStep(4);
        throw new Error(`Còn ${check.missing_audio}/${check.total} cảnh chưa có giọng đọc. Hãy tạo giọng đọc trước khi dựng video.`);
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
            setStudioStep(4);
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

  async function importStudioPastedScript() {
    const text = $('studioPasteScriptText')?.value || '';
    if (!text.trim()) return setMessage('Hãy dán nội dung kịch bản trước khi lưu.', 'error');
    const variant = $('studioPasteScriptVariant')?.value || 'long';
    const language = $('studioScriptLanguage')?.value || 'vi';
    const button = $('studioImportScriptButton');
    if (button?.disabled) return;
    if (button) button.disabled = true;
    setMessage('Đang lưu kịch bản đã dán và chia cảnh…');
    try {
      const result = await api('/api/scripts/import', {method: 'POST', body: JSON.stringify({
        project_id: state.studioProjectId || null, video_id: state.studioVideoId || '',
        title: $('studioPasteScriptTitle')?.value || '', text, variant, language,
        workflow: state.studioWorkflow || 'content',
      })});
      state.studioProjectId = result.project.id;
      state.studioVideoId = result.project.youtube_video_id;
      state.studioWorkflow = result.project.workflow || 'content';
      syncStudioNarrationLanguage(language);
      await saveRenderSettings(state.studioProjectId, {quiet: true});
      if (variant === 'long') {
        state.scriptId = result.script.id;
        state.shots = result.shots || [];
        state.timeline = result.timeline || [];
        // Server nói kịch bản đã lưu ở trạng thái nào (bản nháp đã kiểm theo Kế hoạch, hay kịch bản thường).
        await loadStudioScript(state.studioProjectId);
        renderStudioStoryboard(state.shots, state.timeline);
      } else {
        if ($('studioCreateStandaloneShort')) $('studioCreateStandaloneShort').checked = true;
        await loadShortLane();
        if ($('studioToRenderButton')) $('studioToRenderButton').disabled = false;
      }
      await Promise.all([loadChannels(), loadVideos(), loadProjects()]);
      saveStudioSession();
      setMessage(`Đã lưu kịch bản ${variant === 'short' ? 'Short' : 'video dài'} v${result.script.version} · ${(result.shots || []).length} cảnh. Có thể tiếp tục tạo giọng đọc.`, 'success');
    } catch (error) { setMessage(`Không lưu được kịch bản đã dán: ${error.message}`, 'error'); }
    finally { if (button) button.disabled = false; }
  }

  // ---- Bước 3 · Kịch bản ----
  //
  // Lời của video, viết từ Kế hoạch đã sẵn sàng. Trang chỉ vẽ lại điều server trả về:
  //   GET   /api/projects/{id}/steps          dòng "script": đang chạy hay không (run, last_run)
  //   GET   /api/projects/{id}/script         ScriptDocument, trạng thái, current, lý do bị chặn
  //   POST  /api/projects/{id}/steps/script   {create_standalone_short, short_seconds, provider}
  //   PATCH /api/scripts/{id}                 sửa lời; server kiểm lại theo Kế hoạch
  // Trạng thái (completed / stale / mismatch / invalid), "dùng tiếp được không"
  // và mọi lời từ chối là của server: trang không tự suy ra, không đặt lại câu chữ.
  // Không có writer cũ hay danh sách cảnh của nó ở đây: hình thuộc Storyboard (Bước 5).
  const STUDIO_SCRIPT_POLL_MS = 5000;
  const STUDIO_SCRIPT_HIDDEN_POLL_MS = 30000;
  const STUDIO_SCRIPT_STATUS = {
    none: ['', 'Chưa có kịch bản'],
    running: ['cyan', 'Đang viết kịch bản…'],
    completed: ['green', 'Sẵn sàng'],
    stale: ['orange', 'Kịch bản đã cũ'],
    mismatch: ['orange', 'Không khớp kế hoạch'],
    invalid: ['red', 'Không còn hợp lệ'],
    held: ['orange', 'Chưa dùng tiếp được'],
    no_plan: ['', 'Chưa có kế hoạch'],
    needs_user_decision: ['orange', 'Kế hoạch cần bạn quyết định'],
    blocked: ['red', 'Kế hoạch chưa thể thực hiện'],
    plan_stale: ['orange', 'Kế hoạch đã cũ'],
    failed: ['red', 'Chưa viết được kịch bản'],
  };
  // Kế hoạch chưa sẵn sàng (server nói qua current_plan.status) thì bước này mang trạng thái của Kế hoạch.
  const STUDIO_SCRIPT_PLAN_STATES = {needs_user_decision: 'needs_user_decision', blocked: 'blocked', stale: 'plan_stale'};
  const STUDIO_SCRIPT_WAITING_ON_PLAN = ['no_plan', 'needs_user_decision', 'blocked', 'plan_stale'];

  document.addEventListener('visibilitychange', () => {
    const watch = state.studioScript?.watch;
    if (document.hidden || !watch?.tick) return;
    clearTimeout(watch.timer);
    void watch.tick();
  });

  function studioScriptState(projectId = state.studioProjectId) {
    if (!state.studioScript || Number(state.studioScript.projectId) !== Number(projectId)) {
      clearTimeout(state.studioScript?.watch?.timer);
      state.studioScript = {projectId: projectId || null, row: null, body: null, error: '', running: false, requesting: false,
        watch: null, seen: [], editing: false};
    }
    return state.studioScript;
  }

  // Đổi nguồn hoặc dự án: bỏ mọi thứ đang giữ về kịch bản của dự án trước.
  function resetStudioScript() {
    clearTimeout(state.studioScript?.watch?.timer);
    state.studioScript = null;
    renderStudioScript();
  }

  async function studioScriptRow(projectId) {
    const body = await api(`/api/projects/${projectId}/steps`);
    return (body.steps || []).find((row) => row.key === 'script') || null;
  }

  // Đọc trạng thái và kịch bản từ server. Trả true khi dự án đã có kịch bản
  // hoặc đang viết, để lúc mở lại dự án biết dừng ở Bước 3.
  async function loadStudioScript(projectId = state.studioProjectId) {
    if (!projectId) { renderStudioScript(); return false; }
    const view = studioScriptState(projectId);
    let row = null;
    let body = null;
    try {
      [row, body] = await Promise.all([studioScriptRow(projectId), api(`/api/projects/${projectId}/script`)]);
    } catch (error) {
      if (state.studioScript !== view) return false;
      if (!view.body) view.error = studioScriptErrorText(error);
      renderStudioScript();
      return false;
    }
    if (state.studioScript !== view) return false;
    view.row = row;
    view.body = body;
    if (body?.id) state.scriptId = body.id;
    // Một lượt viết từ trước khi tải lại trang, từ tab khác hay từ AI điều phối.
    if (row?.state === 'running' || body?.generation?.status === 'running') {
      view.running = true;
      noteStudioScriptStage(view, row);
      watchStudioScript(projectId);
    } else if (!view.requesting) {
      view.running = false;
      view.seen = [];
    }
    renderStudioScript();
    return view.running || Boolean(body?.id);
  }

  // Chỉ bước nào trang thật sự thấy server đang chạy mới được coi là đã chạy.
  function noteStudioScriptStage(view, row) {
    const stage = row?.run?.stage;
    if (stage && !view.seen.includes(stage)) view.seen.push(stage);
  }

  // "Đang viết" đọc từ server, không giữ trong trang: tải lại trang chỉ bỏ
  // request, không bỏ việc. Tab đang ẩn hỏi thưa hơn và hỏi ngay khi mở lại.
  function watchStudioScript(projectId) {
    const view = studioScriptState(projectId);
    if (view.watch) return;
    const watch = {timer: null, tick: null, busy: false};
    view.watch = watch;
    const later = () => setTimeout(watch.tick, document.hidden ? STUDIO_SCRIPT_HIDDEN_POLL_MS : STUDIO_SCRIPT_POLL_MS);
    watch.tick = async () => {
      if (state.studioScript !== view || view.watch !== watch || watch.busy) return;
      watch.busy = true;
      let row = null;
      try { row = await studioScriptRow(projectId); } catch (_) { /* app tạm không trả lời: hỏi lại sau */ }
      watch.busy = false;
      if (state.studioScript !== view || view.watch !== watch) return;
      if (!row || row.state === 'running') {
        if (row) { view.row = row; noteStudioScriptStage(view, row); renderStudioScriptHead(); }
        watch.timer = later();
        return;
      }
      view.watch = null;
      // Request của chính trang này còn mở: câu trả lời của nó sẽ kết thúc lượt chạy.
      if (view.requesting) return;
      view.running = false;
      if (row.last_run?.status === 'failed') {
        view.error = studioScriptErrorText({status: row.last_run.status_code, message: row.last_run.error});
      }
      await loadStudioScript(projectId);
      announceStudioScript();
    };
    watch.timer = later();
  }

  function stopStudioScriptWatch(view) {
    clearTimeout(view?.watch?.timer);
    if (view) view.watch = null;
  }

  // Một lần viết. `options` đi nguyên vào POST …/steps/script - chỉ những gì
  // bước đó nhận. Góc, thời lượng, cấu trúc, CTA, nền tảng là của Kế hoạch.
  async function writeStudioScript() {
    const projectId = state.studioProjectId;
    if (!projectId) return setMessage('Hãy chọn nguồn và lập Kế hoạch ở Bước 2 trước.', 'error');
    const view = studioScriptState(projectId);
    // Đang viết (trang này, tab khác hay AI điều phối): không gửi lượt thứ hai.
    if (view.requesting || studioScriptStatus(view) === 'running') return;
    // Kế hoạch chưa sẵn sàng: nói đúng lời server và không gửi gì; không có cờ nào vượt qua được.
    if (view.body?.write_blocked_reason) return setMessage(view.body.write_blocked_reason, 'error');
    const createStandaloneShort = Boolean($('studioCreateStandaloneShort')?.checked);
    const shortSeconds = Number($('studioShortScriptSeconds')?.value || 45);
    const options = {create_standalone_short: createStandaloneShort, short_seconds: shortSeconds};
    const provider = $('studioWriterProviderSelect')?.value || 'auto';
    if (provider !== 'auto') options.provider = provider;
    view.running = true;
    view.requesting = true;
    view.error = '';
    view.editing = false;
    view.seen = [];
    renderStudioScript();
    watchStudioScript(projectId);
    let failure = null;
    let response = null;
    try {
      response = await api(`/api/projects/${projectId}/steps/script`, {method: 'POST', body: JSON.stringify({options})});
    } catch (error) {
      failure = error;
    }
    if (state.studioScript !== view) return;
    view.requesting = false;
    if (failure) {
      // Request hỏng nhưng server vẫn đang viết (một lượt khác đã chạy trước,
      // hoặc mất kết nối giữa chừng): theo dõi lượt đang có.
      let row = null;
      try { row = await studioScriptRow(projectId); } catch (_) { /* không hỏi được: coi như lượt này đã dừng */ }
      if (state.studioScript !== view) return;
      if (row?.state === 'running') {
        view.row = row;
        view.seen = [];
        noteStudioScriptStage(view, row);
        watchStudioScript(projectId);
        renderStudioScriptHead();
        setMessage(studioScriptErrorText(failure), 'error');
        return;
      }
      view.error = studioScriptErrorText(failure);
    }
    stopStudioScriptWatch(view);
    view.running = false;
    await loadStudioScript(projectId);
    announceStudioScript();
    if (!failure) await finishStudioScriptRun(projectId, response?.result || {});
  }

  // Sau một lượt viết thành công: giọng đọc theo ngôn ngữ của kịch bản, và Short nếu có viết kèm.
  async function finishStudioScriptRun(projectId, result) {
    const language = state.studioScript?.body?.document?.language || state.studioScript?.body?.language || '';
    if (language) {
      syncStudioNarrationLanguage(language);
      try { await saveRenderSettings(projectId, {quiet: true}); } catch (_) { /* cấu hình giọng lưu lại được ở Bước 4 */ }
    }
    if (result.short || result.short_error) await loadShortLane();
    if (result.short_error) setMessage(`Kịch bản dài đã viết xong, nhưng Short riêng chưa tạo được: ${result.short_error}`, 'error');
  }

  function announceStudioScript() {
    const view = state.studioScript;
    if (!view) return;
    if (view.error) return setMessage(view.error, 'error');
    const status = studioScriptStatus(view);
    if (status === 'completed') setMessage('Đã viết kịch bản từ Kế hoạch.', 'success');
    else if (view.body?.blocked_reason) setMessage(view.body.blocked_reason, 'error');
  }

  // Lời từ chối của server (409 của gate, 422 của bản nháp…) giữ nguyên câu chữ;
  // chỉ khi server không nói gì mới dùng lời của trang.
  function studioScriptErrorText(error) {
    const status = Number(error?.status || 0);
    const text = String(error?.message || '').trim();
    if (!status && /fetch|network/i.test(text)) return 'Không kết nối được app. Hãy mở lại app rồi thử lại.';
    if (!text || /^HTTP \d{3}$/.test(text)) return 'Có lỗi khi viết kịch bản. Thử lại sau.';
    return text;
  }

  // Trạng thái là của server: lượt chạy trên dòng "script" của GET …/steps, và
  // state / current / write_blocked_reason của GET …/script.
  function studioScriptStatus(view = state.studioScript) {
    if (!view) return 'none';
    if (view.running || view.row?.state === 'running' || view.body?.generation?.status === 'running') return 'running';
    const body = view.body;
    if (!body) return view.error ? 'failed' : 'none';
    if (body.write_blocked_reason) return STUDIO_SCRIPT_PLAN_STATES[String(body.current_plan?.status || '')] || 'no_plan';
    if (body.state === 'missing' || !body.id) return view.error ? 'failed' : 'none';
    if (body.state === 'invalid') return 'invalid';
    if (body.state === 'stale') return body.stale_kind === 'mismatch' ? 'mismatch' : 'stale';
    return body.state === 'completed' && body.current === true ? 'completed' : 'held';
  }

  // ---- Phần đầu: trạng thái, phiên bản, nút. Vẽ lại mỗi lần hỏi server. ----
  function studioScriptActions(status) {
    const button = (label, action, kind = 'primary') => `<button class="btn ${kind}" type="button" onclick="${action}">${esc(label)}</button>`;
    if (status === 'running') return '<button class="btn primary" type="button" disabled>Đang viết…</button>';
    if (STUDIO_SCRIPT_WAITING_ON_PLAN.includes(status)) return button('Xem lại Kế hoạch', 'setStudioStep(2)', 'ghost');
    if (status === 'completed') {
      return button('Chỉnh sửa', 'editStudioScript()') + button('Tạo Short', 'createStudioShort()', 'ghost')
        + button('Viết lại kịch bản', 'writeStudioScript()', 'ghost');
    }
    if (status === 'invalid') return button('Viết lại kịch bản', 'writeStudioScript()') + button('Sửa lại', 'editStudioScript()', 'ghost');
    if (['stale', 'mismatch', 'held'].includes(status)) return button('Viết lại kịch bản', 'writeStudioScript()');
    return button('Viết kịch bản', 'writeStudioScript()');
  }

  function studioScriptMeta(body) {
    if (!body?.id) return '';
    const parts = [`Phiên bản ${body.version}`];
    if (body.plan_version) parts.push(`viết theo Kế hoạch v${body.plan_version}`);
    const now = body.current_plan?.version;
    if (now && Number(now) !== Number(body.plan_version)) parts.push(`Kế hoạch hiện tại v${now}`);
    parts.push(body.approval_status === 'approved' ? 'đã duyệt' : 'chưa duyệt');
    return parts.join(' · ');
  }

  function studioScriptRunning(view) {
    const run = view.row?.run || view.body?.generation?.run || {};
    const started = run.started_at ? new Date(run.started_at) : null;
    const elapsed = started && !Number.isNaN(started.getTime()) ? Math.max(0, Math.round((Date.now() - started.getTime()) / 1000)) : 0;
    const chips = (run.stages || []).map((item) => {
      const mark = item.key === run.stage ? 'now' : (view.seen || []).includes(item.key) ? 'past' : '';
      return `<span class="studio-plan-stage ${mark}">${esc(item.label)}</span>`;
    }).join('');
    const timing = `${run.stage_label ? `${esc(run.stage_label)} · ` : ''}${elapsed ? `đã chạy ${formatStudioDuration(elapsed)} · ` : ''}`;
    return `<div class="studio-plan-running" aria-live="polite">
        ${chips ? `<div class="studio-plan-stages">${chips}</div>` : ''}
        <div class="studio-plan-note">${timing}thường mất 1–2 phút. Có thể rời trang, việc vẫn chạy.</div>
      </div>`;
  }

  function studioScriptList(items) {
    const rows = (items || []).map((item) => String(item || '').trim()).filter(Boolean);
    return rows.length ? `<ul class="studio-result-list">${rows.map((item) => `<li>${esc(item)}</li>`).join('')}</ul>` : '';
  }

  // Vì sao bước này chưa xong: đúng câu của server, kèm các lý do server liệt kê.
  function studioScriptReason(status, view) {
    const body = view?.body || {};
    if (STUDIO_SCRIPT_WAITING_ON_PLAN.includes(status)) return `<div class="studio-analyze-notice">${esc(body.write_blocked_reason)}</div>`;
    if (['stale', 'mismatch', 'held'].includes(status)) {
      return `<div class="studio-analyze-notice">${esc(body.blocked_reason)}${studioScriptList(body.stale_reasons)}</div>`;
    }
    if (status === 'invalid') return `<div class="studio-analyze-notice">${esc(body.blocked_reason)}${studioScriptList(body.validation_errors)}</div>`;
    if (status === 'none') {
      return '<div class="studio-empty">Chưa có kịch bản cho Kế hoạch này. Bấm “Viết kịch bản”: app viết lời theo đúng góc nội dung, thời lượng và cấu trúc của Kế hoạch.</div>';
    }
    return '';
  }

  // Lượt viết gần nhất hỏng ở nơi khác (tab khác, AI điều phối): nói lời của server.
  function studioScriptLastFailure(status, view) {
    const last = view?.body?.generation?.last_run;
    if (status === 'running' || view?.error || last?.status !== 'failed' || !last.error) return '';
    return `<div class="studio-analyze-notice">Lần viết gần nhất không thành công: ${esc(last.error)}</div>`;
  }

  function renderStudioScriptHead() {
    const box = $('studioScriptHead');
    if (!box) return;
    const view = state.studioScript;
    const status = studioScriptStatus(view);
    const [tone, label] = STUDIO_SCRIPT_STATUS[status] || STUDIO_SCRIPT_STATUS.none;
    const body = view?.body || {};
    box.innerHTML = `
      <div class="studio-plan-head">
        <div class="studio-plan-source">
          <div class="primary-text">${esc(body.document?.title || body.script_title || 'Kịch bản video dài')}</div>
          <div class="secondary-text">${esc(studioScriptMeta(body))}</div>
        </div>
        <span class="status-badge ${tone}">${esc(label)}</span>
        <div class="studio-plan-actions">${state.studioProjectId ? studioScriptActions(status) : ''}</div>
      </div>
      ${status === 'running' ? studioScriptRunning(view) : ''}
      ${view?.error && status !== 'running' ? `<div class="studio-analyze-notice">⚠ ${esc(view.error)}</div>` : ''}
      ${studioScriptLastFailure(status, view)}
      ${studioScriptReason(status, view)}`;
    syncStudioScriptStep(status);
  }

  // Các bước sau chỉ mở khi server nói kịch bản này dùng tiếp được (current).
  function syncStudioScriptStep(status = studioScriptStatus()) {
    const body = state.studioScript?.body || {};
    const usable = body.current === true && status !== 'running';
    const tab = document.querySelector('[data-studio-tab="3"]');
    if (tab) tab.dataset.scriptState = status;
    const next = $('studioToRenderButton');
    if (next) {
      next.disabled = !usable;
      next.title = usable ? '' : String(body.blocked_reason || body.write_blocked_reason || '');
    }
    const storyboard = $('studioGenerateStoryboardButton');
    if (storyboard) storyboard.disabled = !usable;
    const chat = $('studioChatBox');
    if (chat) chat.hidden = !(usable || status === 'invalid');
    if (usable) {
      if ($('studioProjectSummary')) $('studioProjectSummary').textContent = `#${state.studioProjectId}`;
      if ($('studioScriptSummary')) $('studioScriptSummary').textContent = `v${body.version || '1'}`;
    }
  }

  // ---- Phần thân: ScriptDocument đúng thứ tự của nó. ----
  function studioScriptLines(lines) {
    const rows = (lines || []).filter((line) => String(line?.text || '').trim());
    if (!rows.length) return '<p class="secondary-text">(không có lời)</p>';
    return rows.map((line) => {
      const speaker = line.speaker && line.speaker !== 'narrator' ? `<b>${esc(line.speaker)}:</b> ` : '';
      const price = line.price_captured_at ? ` <span class="secondary-text">(giá đọc lúc ${esc(studioPlanWhen(line.price_captured_at) || line.price_captured_at)})</span>` : '';
      return `<p>${speaker}${esc(line.text)}${price}</p>`;
    }).join('');
  }

  function studioScriptScreen(items) {
    const rows = (items || []).map((item) => String(item || '').trim()).filter(Boolean);
    return rows.length ? `<div class="studio-plan-field"><span>Chữ trên màn hình</span><p>${esc(rows.join(' · '))}</p></div>` : '';
  }

  // insight_ids / evidence_ids của mỗi phần: giữ lại, gập vào "Dựa trên".
  function studioScriptBasis(part) {
    const insights = part?.insight_ids || [];
    const evidence = part?.evidence_ids || [];
    if (!insights.length && !evidence.length) return '';
    return `<details class="studio-more"><summary>Dựa trên</summary>
        ${insights.length ? `<div class="studio-plan-field"><span>Insight</span><p>${esc(insights.join(', '))}</p></div>` : ''}
        ${evidence.length ? `<div class="studio-plan-field"><span>Bằng chứng</span><p>${esc(evidence.join(', '))}</p></div>` : ''}
      </details>`;
  }

  function studioScriptPart(label, part, title = '') {
    if (!part) return '';
    return `<div class="studio-plan-section">
        <div class="studio-plan-time">${esc(label)}</div>
        <div>${title}${studioScriptLines(part.spoken_lines)}${studioScriptScreen(part.on_screen_text)}${studioScriptBasis(part)}</div>
      </div>`;
  }

  function studioScriptFooter(body, status) {
    if (status !== 'completed') return '';
    const reup = state.studioWorkflow === 'reup' ? '' : 'hidden';
    return `<div class="studio-actions">
        ${body.approval_status === 'approved' ? '' : '<button class="btn small primary" type="button" onclick="approveStudioScript()">Duyệt kịch bản</button>'}
        <button class="btn small" type="button" onclick="aiReviewStudioScript()">AI đọc lại kịch bản</button>
        <span data-wf="reup" ${reup}><button class="btn small" type="button" onclick="checkStudioFidelity()">Soát đúng nội dung gốc</button><select id="studioTranslateLanguage" aria-label="Ngôn ngữ đích"><option value="vi">Dịch sang tiếng Việt</option><option value="en">Dịch sang tiếng Anh</option><option value="zh">Dịch sang tiếng Trung</option><option value="ja">Dịch sang tiếng Nhật</option><option value="ko">Dịch sang tiếng Hàn</option></select><button class="btn small primary" type="button" onclick="translateStudioNarration()">Dịch lời bình</button></span>
      </div>`;
  }

  function studioScriptDocument(body, status) {
    const doc = body.document;
    if (!doc) {
      // Một dòng kịch bản không do Bước 3 viết (trước khi có Kế hoạch): chỉ có các cột cũ.
      const field = (label, value) => (String(value || '').trim() ? `<div class="studio-plan-field"><span>${esc(label)}</span><p>${esc(value)}</p></div>` : '');
      return `<section class="studio-work-card studio-plan-card">
          <div class="studio-card-head"><div><b>Kịch bản</b><span>không do Bước 3 viết từ Kế hoạch</span></div></div>
          ${field('Hook', body.hook)}${field('Mở đầu', body.intro)}${field('Nội dung', body.main_content)}${field('CTA', body.cta)}
        </section>`;
    }
    const sections = doc.sections || [];
    const facts = [
      ['Ngôn ngữ', STUDIO_PLAN_LANGUAGES[doc.language] || doc.language || '—'],
      ['Thời lượng mục tiêu', doc.target_duration_seconds ? formatStudioDuration(doc.target_duration_seconds) : '—'],
      ['Ước tính khi đọc', doc.estimated_seconds ? formatStudioDuration(doc.estimated_seconds) : '—'],
      ['Phiên bản', `v${body.version}`],
      ['Kế hoạch', body.plan_version ? `v${body.plan_version}` : '—'],
    ].map(([label, value]) => `<div><span>${esc(label)}</span><b>${esc(value)}</b></div>`).join('');
    const rows = sections.map((section, index) => {
      const budget = section.budget_seconds ? ` / ${formatStudioDuration(section.budget_seconds)} theo kế hoạch` : '';
      const title = `<p><b>${esc(section.name || `Phần ${index + 1}`)}</b> <span class="secondary-text">· ${esc(section.plan_section_id || section.id || '')} · ${esc(formatStudioDuration(section.estimated_seconds || 0))}${esc(budget)}</span></p>`;
      return studioScriptPart(`Phần ${index + 1}`, section, title);
    }).join('');
    const notes = [...(doc.missing_information || []), ...(doc.limitations || [])];
    return `<section class="studio-work-card studio-plan-card">
        <div class="studio-card-head"><div><b>${esc(doc.title || body.script_title || 'Kịch bản')}</b><span>${sections.length} phần · ước tính ${esc(formatStudioDuration(doc.estimated_seconds || 0))}</span></div></div>
        <div class="studio-plan-facts">${facts}</div>
        ${studioScriptPart('HOOK', doc.hook)}
        ${rows}
        ${studioScriptPart('CTA', doc.cta)}
        ${notes.length ? `<details class="studio-more"><summary>Ghi chú của kịch bản</summary>${studioScriptList(notes)}</details>` : ''}
        ${studioScriptFooter(body, status)}
        <details class="studio-advanced-json"><summary>Nâng cao: dữ liệu kịch bản (JSON)</summary><pre class="studio-json">${esc(JSON.stringify(doc, null, 2))}</pre></details>
      </section>`;
  }

  // Ô sửa chỉ có lời: tiêu đề, hook, nội dung (mỗi dòng một câu đọc), CTA.
  // Không có ô nào cho plan_id, plan_version, góc, thời lượng, nền tảng hay tỉ lệ khung.
  function studioScriptEditor(body) {
    return `<section class="studio-work-card studio-plan-card studio-script">
        <div class="studio-card-head"><div><b>Sửa kịch bản · phiên bản ${esc(body.version)}</b><span>Mỗi dòng là một câu đọc. Góc nội dung, thời lượng và cấu trúc do Kế hoạch quyết định; sau khi lưu, app kiểm lại kịch bản theo Kế hoạch.</span></div></div>
        <div class="studio-field"><label for="studioScriptTitleInput">Tiêu đề</label><input id="studioScriptTitleInput" value="${esc(body.script_title || '')}"></div>
        <div class="studio-field"><label for="studioScriptHookInput">Hook</label><textarea id="studioScriptHookInput">${esc(body.hook || '')}</textarea></div>
        <div class="studio-field"><label for="studioScriptMainInput">Nội dung</label><textarea id="studioScriptMainInput" name="main_content" rows="14">${esc(body.main_content || '')}</textarea></div>
        <div class="studio-field"><label for="studioScriptCtaInput">CTA</label><textarea id="studioScriptCtaInput">${esc(body.cta || '')}</textarea></div>
        <div class="studio-actions"><button class="btn small primary" type="button" onclick="saveStudioScript()">Lưu và kiểm lại</button><button class="btn small ghost" type="button" onclick="cancelStudioScriptEdit()">Huỷ</button></div>
      </section>`;
  }

  function renderStudioScript() {
    renderStudioScriptHead();
    const box = $('studioScriptResult');
    if (!box) return;
    const view = state.studioScript;
    const body = view?.body;
    if (!body?.id) { box.innerHTML = ''; return; }
    box.innerHTML = view.editing ? studioScriptEditor(body) : studioScriptDocument(body, studioScriptStatus(view));
  }

  function editStudioScript() {
    const view = state.studioScript;
    if (!view?.body?.id) return;
    view.editing = true;
    renderStudioScript();
    $('studioScriptResult')?.scrollIntoView?.({behavior: 'smooth', block: 'start'});
  }

  function cancelStudioScriptEdit() {
    if (state.studioScript) state.studioScript.editing = false;
    renderStudioScript();
  }

  function studioScriptPayload() {
    return {
      script_title: $('studioScriptTitleInput')?.value || '',
      hook: $('studioScriptHookInput')?.value || '',
      main_content: $('studioScriptMainInput')?.value || '',
      cta: $('studioScriptCtaInput')?.value || '',
    };
  }

  // PATCH /api/scripts/{id}: server ghi lời vào ScriptDocument và kiểm lại.
  // Lưu được không có nghĩa là còn hợp lệ - trạng thái mới đọc lại từ server.
  async function saveStudioScript() {
    const view = state.studioScript;
    // Chỉ lưu khi đang sửa trên màn hình: không có ô sửa thì không gửi gì.
    if (!view?.editing || !view.body?.id || !$('studioScriptMainInput')) return;
    try {
      await api(`/api/scripts/${view.body.id}`, {method: 'PATCH', body: JSON.stringify(studioScriptPayload())});
    } catch (error) {
      return setMessage(studioScriptErrorText(error), 'error');
    }
    if (state.studioScript !== view) return;
    view.editing = false;
    await loadStudioScript(view.projectId);
    if (studioScriptStatus() === 'completed') setMessage('Đã lưu kịch bản. Kịch bản vẫn khớp Kế hoạch.', 'success');
    else setMessage(state.studioScript?.body?.blocked_reason || 'Đã lưu kịch bản.', 'error');
    void loadProjects();
  }

  async function approveStudioScript() {
    const view = state.studioScript;
    if (!view?.body?.id || !confirm('Duyệt kịch bản này để chuyển sang bước dựng?')) return;
    try {
      await api(`/api/scripts/${view.body.id}/approve`, {method: 'POST'});
    } catch (error) {
      return setMessage(studioScriptErrorText(error), 'error');
    }
    await loadStudioScript(view.projectId);
    setMessage('Đã duyệt kịch bản.', 'success');
  }

  async function aiReviewStudioScript() {
    if (!state.studioProjectId) return setMessage('Chưa có project.', 'error');
    setMessage('AI đang đọc lại kịch bản...');
    try {
      const result = await api(`/api/projects/${state.studioProjectId}/script/review`, {method: 'POST'});
      const review = result.review || {};
      const target = $('studioScriptResult');
      if (target) {
        const card = document.createElement('div');
        card.className = 'studio-result-card';
        card.innerHTML = `<h3>AI đọc lại kịch bản · ${esc(review.score ?? '—')}/10${review.should_rewrite ? ' · nên viết lại' : ''}</h3>
          ${review.hook_verdict ? `<p class="hint"><b>Hook:</b> ${esc(review.hook_verdict)}</p>` : ''}
          ${(review.issues || []).length ? `<p class="hint"><b>Vấn đề</b></p>${studioScriptList(review.issues)}` : ''}
          ${(review.suggestions || []).length ? `<p class="hint"><b>Đề xuất</b></p>${studioScriptList(review.suggestions)}` : ''}`;
        target.prepend(card);
      }
      setMessage(`AI chấm ${review.score ?? '—'}/10.`, 'success');
      void loadProjects();
    } catch (error) { setMessage(studioScriptErrorText(error), 'error'); }
  }

  // Chat là một lượt sửa (revision) của kịch bản hiện hành, giữ nguyên Kế hoạch; server kiểm lại.
  async function chatStudioScript() {
    const projectId = state.studioProjectId;
    if (!projectId) return setMessage('Chưa có project để chỉnh sửa kịch bản.', 'error');
    const message = $('studioChatMessage')?.value.trim();
    if (!message) return setMessage('Hãy nhập yêu cầu chỉnh sửa cho AI.', 'error');
    const button = $('studioChatButton');
    if (button) button.disabled = true;
    setMessage('AI đang chỉnh sửa kịch bản theo yêu cầu...');
    try {
      const response = await api(`/api/projects/${projectId}/script/chat`, {method: 'POST', body: JSON.stringify({provider: $('studioChatProviderSelect')?.value || 'codex_cli', message})});
      if ($('studioChatMessage')) $('studioChatMessage').value = '';
      await loadStudioScript(projectId);
      if (studioScriptStatus() === 'completed') setMessage(`Đã tạo phiên bản kịch bản mới${response.provider ? ` bằng ${response.provider}` : ''}.`, 'success');
      else setMessage(state.studioScript?.body?.blocked_reason || 'Đã lưu phiên bản mới.', 'error');
      void loadProjects();
    } catch (error) { setMessage(studioScriptErrorText(error), 'error'); }
    finally { if (button) button.disabled = false; }
  }

  // Short viết từ kịch bản hiện hành (POST …/short-script); server tự chặn khi kịch bản không dùng tiếp được.
  async function createStudioShort() {
    const body = state.studioScript?.body;
    if (body?.current !== true) return setMessage(body?.blocked_reason || body?.write_blocked_reason || 'Chưa có kịch bản dùng tiếp được.', 'error');
    await writeShortScript();
    setStudioLaneTab('short');
  }
  // ---- hết Bước 3 · Kịch bản ----

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

  // The target duration box takes one shape only, hh:mm:ss, and the colons
  // are the box's job rather than the user's: digits fill it left to right.
  function studioClock(totalSeconds) {
    const total = Math.max(0, Math.round(Number(totalSeconds) || 0));
    return [Math.floor(total / 3600), Math.floor((total % 3600) / 60), total % 60]
      .map((part) => String(part).padStart(2, '0')).join(':');
  }

  function maskStudioDurationInput() {
    const input = $('studioTargetDurationSeconds');
    if (!input) return;
    const digits = input.value.replace(/\D/g, '').slice(0, 6);
    input.value = [digits.slice(0, 2), digits.slice(2, 4), digits.slice(4, 6)].filter(Boolean).join(':');
  }

  // A part-typed value is completed with zeros on the right, so what was on
  // screen is what is kept: "00:12" becomes 00:12:00, not twelve seconds.
  function normaliseStudioDurationInput() {
    const input = $('studioTargetDurationSeconds');
    if (!input || !input.value.trim()) return;
    const padded = input.value.replace(/\D/g, '').slice(0, 6).padEnd(6, '0');
    input.value = `${padded.slice(0, 2)}:${padded.slice(2, 4)}:${padded.slice(4, 6)}`;
  }

  // A value saved before the box had one format ("12:00", "12 phút") is read
  // the way it was meant and rewritten, rather than re-read digit by digit.
  function restoreStudioDurationInput(value) {
    const input = $('studioTargetDurationSeconds');
    const text = String(value || '').trim();
    if (!input || !text) return;
    if (/^\d{2}:\d{2}:\d{2}$/.test(text)) { input.value = text; return; }
    const seconds = parseStudioDuration(text);
    input.value = seconds ? studioClock(seconds) : '';
  }

  function inferStudioDurationFromPrompt() {
    const input = $('studioTargetDurationSeconds');
    const prompt = $('studioScriptInstructionInput')?.value || '';
    if (!input || input.value.trim()) return;
    const minutes = prompt.match(/\b(\d{1,2})\s*(?:phút|phut|mins?|minutes?)\b/i);
    const seconds = prompt.match(/\b(\d{2,4})\s*(?:giây|giay|secs?|seconds?)\b/i);
    const clock = prompt.match(/\b(\d{1,2})\s*:\s*(\d{2})\b/);
    const inferred = minutes ? Number(minutes[1]) * 60 : seconds ? Number(seconds[1]) : clock ? Number(clock[1]) * 60 + Number(clock[2]) : 0;
    if (inferred >= 30 && inferred <= 1800) input.value = studioClock(inferred);
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
