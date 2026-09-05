// core.js - shared state, helpers, api, session
//
// Part of one page split into ordered files. These are classic
// scripts sharing a single global scope and running in document
// order, so this is a move rather than a rewrite: the files
// concatenated in order are byte for byte the block they came from,
// which is what the test asserts.

  const $ = (id) => document.getElementById(id);
  const state = { channels: [], managedChannels: [], workflowReferences: [], videos: [], videoCatalog: [], videoGroupFilter: '', videoChannelFilter: '', projects: [], jobs: [], productionJobs: [], assets: [], integrations: [], queue: null, transcriptQueue: null, productionQueue: null, toolStatus: [], modelCatalog: [], transcriptVideoId: null, projectView: 'overview', projectId: null, scriptId: null, shots: [], timeline: [], oauth: null, selectedVideoIds: new Set(), studioStep: 1, studioSourceChannelId: '', studioVideoId: '', studioAnalysis: null, studioReference: null, studioWriter: null, studioProjectId: null, studioWorkflow: 'content', usageLimits: [], workspace: 'dashboard', automationProjectId: null, automationStatus: null, automationProjects: [], automationApprovals: [], providerCatalog: [] };
  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const number = (value) => value == null ? '—' : Number(value).toLocaleString('vi-VN');
  const date = (value) => value ? new Date(value).toLocaleString('vi-VN', {dateStyle:'short', timeStyle:'short'}) : '—';
  const channelName = (id) => { const item = state.channels.find((c) => c.youtube_channel_id === id); return item?.title || id || 'Chưa rõ nguồn'; };
  const setMessage = (text, type = '') => {
    if ($('message')) { $('message').textContent = text; $('message').className = `message ${type}`; }
    if ($('studioMessage')) { $('studioMessage').textContent = text; $('studioMessage').className = `message ${type}`; }
  };
  const setStudioProgress = (percent, label, type = '') => {
    const panel = $('studioProgress');
    const bar = $('studioProgressBar');
    const percentLabel = $('studioProgressPercent');
    const text = $('studioProgressLabel');
    if (!panel || !bar || !percentLabel || !text) return;
    const value = Math.max(0, Math.min(100, Math.round(Number(percent) || 0)));
    panel.hidden = false;
    panel.classList.toggle('error', type === 'error');
    bar.style.width = `${value}%`;
    percentLabel.textContent = `${value}%`;
    text.textContent = label || 'Đang xử lý...';
  };

  const studioSessionStorageKey = 'ytFactory.studioSession.v1';

  function studioSessionSnapshot() {
    return {
      studioStep: state.studioStep,
      sourceChannelId: state.studioSourceChannelId,
      videoId: state.studioVideoId,
      projectId: state.studioProjectId,
      detailProjectId: state.projectId,
      projectView: state.projectView,
      workspace: localStorage.getItem('ytFactory.workspace') || 'dashboard',
      creativeDirection: $('studioCreativeDirectionInput')?.value || '',
      scriptInstruction: $('studioScriptInstructionInput')?.value || '',
      targetDuration: $('studioTargetDurationSeconds')?.value || '',
      createStandaloneShort: Boolean($('studioCreateStandaloneShort')?.checked),
      standaloneShortSeconds: $('studioInitialShortSeconds')?.value || '',
      remakeMode: $('studioRemakeModeSelect')?.value || '',
      analysisLanguage: $('studioAnalysisLanguage')?.value || '',
      scriptLanguage: $('studioScriptLanguage')?.value || '',
      managedChannelId: $('studioManagedChannelSelect')?.value || '',
      writerProvider: $('studioWriterProviderSelect')?.value || '',
      voiceProvider: $('studioVoiceProviderSelect')?.value || '',
      voiceModel: $('studioVoiceModelSelect')?.value || '',
      voiceRate: $('studioVoiceRateSelect')?.value || '',
      voiceReferenceAsset: $('studioVoiceReferenceAsset')?.value || '',
      voicePromptText: $('studioVoicePromptText')?.value || '',
      savedAt: new Date().toISOString(),
    };
  }

  function saveStudioSession() {
    if (!state.studioVideoId && !state.studioProjectId) return;
    try { localStorage.setItem(studioSessionStorageKey, JSON.stringify(studioSessionSnapshot())); } catch (_) {}
  }

  function savedStudioSession() {
    try {
      const saved = JSON.parse(localStorage.getItem(studioSessionStorageKey) || 'null');
      return saved && typeof saved === 'object' ? saved : null;
    } catch (_) { return null; }
  }

  // Mỗi WF là một file ở phía app (youtube_monitor/workflows/). Trình duyệt
  // nạp đúng file đó thay vì giữ một bản mô tả thứ hai — bản sao thứ hai chính
  // là cách WF Reup từng bị phân tích bằng quy tắc remake của WF Content.
  const WORKFLOWS = {};
  // The page reloads before a non-reload server imports new workflow modules.
  // Keep the companion Short visible in both workflows during that short gap.
  const SHORT_FLOW_FALLBACKS = {
    content: {
      steps: {2: 'Kịch bản + Short', 3: 'Giọng đọc + Short', 5: 'Xưởng dựng + Short'},
      summary: 'Luồng Short: tạo từ cùng brief ở bước Kịch bản, tạo giọng ở bước Giọng đọc, rồi tạo cảnh AI và dựng riêng ở Xưởng dựng.',
      shortFlow: 'Short dùng cùng brief và cấu hình giọng với video dài; cảnh Short được tạo theo workflow AI của WF Content.',
    },
    reup: {
      steps: {2: 'Lời bình + Short', 3: 'Giọng đọc + Short', 5: 'Xưởng dựng + Short'},
      summary: 'Luồng Short: tạo từ cùng lời bình ở bước Kịch bản, tạo giọng ở bước Giọng đọc, rồi cắt cảnh nguồn và dựng riêng ở Xưởng dựng.',
      shortFlow: 'Short giữ đúng nội dung nguồn của WF Reup, dùng cùng cấu hình giọng và cắt cảnh từ video nguồn thay vì tạo ảnh AI.',
    },
  };

  function withVisibleShortFlow(flow) {
    const fallback = SHORT_FLOW_FALLBACKS[flow?.key];
    if (!fallback) return flow;
    const steps = [...(flow.steps || [])];
    Object.entries(fallback.steps).forEach(([index, label]) => {
      const position = Number(index);
      if (steps[position] && !steps[position].includes('Short')) steps[position] = label;
    });
    const notes = [...(flow.notes || [])];
    if (!notes.some((note) => String(note).includes('Short'))) notes.push(fallback.summary);
    return {...flow, steps, notes, short_flow: flow.short_flow || fallback.shortFlow};
  }

  // Danh sách giọng trước đây được viết tay trong trang: 7 giọng, trong khi
  // Microsoft công bố 322. Hỏi thẳng edge-tts để không ai phải đoán.
  async function loadEdgeVoices() {
    const group = $('studioEdgeVoiceGroup');
    if (!group) return;
    try {
      const result = await api('/api/tts/voices');
      const chosen = $('studioVoiceModelSelect')?.value || '';
      group.innerHTML = (result.voices || []).map((voice) => {
        const gender = voice.gender === 'Female' ? 'Nữ' : voice.gender === 'Male' ? 'Nam' : '';
        const name = String(voice.short_name || '').replace(/Neural$/, '').split('-').slice(2).join('-');
        return `<option value="${esc(voice.short_name)}">${esc(voice.locale)} · ${esc(name)}${gender ? ' · ' + gender : ''}</option>`;
      }).join('');
      group.label = `Edge TTS · ${result.total} giọng, ${result.locales} ngôn ngữ`;
      const select = $('studioVoiceModelSelect');
      if (select && chosen) select.value = chosen;
      state.edgeVoiceCount = result.total;
    } catch (_) { /* giữ hai giọng tiếng Việt mặc định nếu không hỏi được */ }
  }

  async function loadWorkflows() {
    try {
      const result = await api('/api/workflows');
      const signature = JSON.stringify(result);
      if (state.workflowSignature === signature) return;
      state.workflowSignature = signature;
      Object.keys(WORKFLOWS).forEach((key) => delete WORKFLOWS[key]);
      (result.workflows || []).forEach((flow) => { WORKFLOWS[flow.key] = withVisibleShortFlow(flow); });
      if (!WORKFLOWS[state.studioWorkflow]) state.studioWorkflow = result.default || 'content';
      renderWorkflowsPanel();
      setStudioStep(state.studioStep || 1);
    } catch (_) { /* giữ định nghĩa đang có nếu không nạp được */ }
  }

  function currentWorkflow() {
    return WORKFLOWS[state.studioWorkflow] || Object.values(WORKFLOWS)[0] || {steps: [], label: ''};
  }

  function renderStudioShortWorkflowNote() {
    const note = $('studioShortWorkflowNote');
    if (!note) return;
    const flow = currentWorkflow();
    note.textContent = flow.short_flow || 'Luồng Short sẽ đi cùng Kịch bản, Giọng đọc và Xưởng dựng của workflow đang chọn.';
  }

  function setStudioWorkflow(key, jump = true) {
    state.studioWorkflow = WORKFLOWS[key] ? key : 'content';
    renderWorkflowsPanel();
    setStudioStep(state.studioStep || 1);
    if (state.studioProjectId) {
      void api(`/api/projects/${state.studioProjectId}/workflow`, {
        method: 'PATCH', body: JSON.stringify({workflow: state.studioWorkflow}),
      }).catch(() => {});
    }
    try { localStorage.setItem('ytFactory.workflow', state.studioWorkflow); } catch (_) {}
    if (jump) {
      setMessage(`Đang dùng ${WORKFLOWS[state.studioWorkflow].label}.`, 'success');
      setWorkspace('dashboard');
    }
  }

  function renderWorkflowsPanel() {
    const target = $('workflowsList');
    if (!target) return;
    target.innerHTML = Object.entries(WORKFLOWS).map(([key, flow]) => {
      const active = key === state.studioWorkflow;
      const steps = (flow.steps || []).map((label, index) => `<span class="wf-step">${index + 1}. ${esc(label)}</span>`).join('');
      const notes = (flow.notes || []).map((note) => `<li>${esc(note)}</li>`).join('');
      return `<div class="studio-result-card${active ? ' wf-active' : ''}">
        <h3>${esc(flow.label)}${active ? ' · đang dùng' : ''}</h3>
        <p class="hint"><b>${esc(flow.state || '')}</b> — ${esc(flow.summary)}</p>
        <div class="wf-steps">${steps}</div>
        <ul class="hint">${notes}</ul>
        <div class="studio-actions">
          <button class="btn ${active ? 'ghost' : 'primary'}" onclick="setStudioWorkflow('${key}')">
            ${active ? 'Mở tab Tạo video' : 'Dùng WF này'}
          </button>
        </div>
      </div>`;
    }).join('');
  }

  const workspaces = {
    dashboard: {
      label: 'Tạo video', eyebrow: 'WIZARD 7 BƯỚC', title: 'Tạo một video mới',
      description: 'Chọn nguồn, chọn model ở từng bước, rồi đi theo nút Tiếp tục đến khi có video hoàn chỉnh.',
      panels: ['studioWizard'],
    },
    source: {
      label: 'Video tham khảo', eyebrow: 'CHỌN VIDEO MẪU', title: 'Chọn video tham khảo',
      description: 'Thêm kênh hoặc một URL video, sau đó bấm “Dựng lại video”. Không cần vào Dự án khi làm video đầu tiên.',
      panels: ['addChannelPanel', 'sourceSplit', 'transcriptQueue', 'videos', 'analysisDetail', 'transcriptDetail', 'writerDetail'],
    },
    managed: {
      label: 'Kênh của tôi', eyebrow: 'QUẢN LÝ ĐÍCH XUẤT BẢN', title: 'Kênh của tôi & workflow tham khảo',
      description: 'Tạo danh sách kênh cá nhân và gắn từng kênh với một kênh YouTube đang theo dõi để làm mẫu phong cách.',
      panels: ['managedChannelsPanel'],
    },
    production: {
      label: 'Dự án', eyebrow: 'CHỈNH SỬA CHI TIẾT', title: 'Dự án và xưởng dựng',
      description: 'Mỗi dự án gom toàn bộ kịch bản, audio, tài nguyên, Premiere và video cuối vào một nơi.',
      panels: ['projects', 'projectDetail'],
    },
    workflows: {
      label: 'WorkFlow', eyebrow: 'CHỌN WORKFLOW', title: 'WorkFlow sản xuất',
      description: 'Nơi lưu các WorkFlow. Chọn một WF thì tab Tạo video sẽ áp dụng đúng WF đó.',
      panels: ['workflowsPanel'],
    },
    orchestration: {
      label: 'Điều phối AI', eyebrow: 'AI ORCHESTRATION', title: 'Điều phối, nghiệm thu và phục hồi',
      description: 'Giao một mục tiêu cấp cao, theo dõi AI thực hiện/nghiệm thu chéo, xử lý điểm dừng và duyệt kết quả cuối.',
      panels: ['automationCommandCenter', 'automationPipeline', 'orchestratorSettings', 'providerCatalogPanel', 'automationPolicyPanel'],
    },
    settings: {
      label: 'Cài đặt', eyebrow: 'HỆ THỐNG', title: 'Công cụ, model và kết nối',
      description: 'Kết nối Codex, GPU, Whisper, TTS, FFmpeg và các AI cloud khi cần.',
      panels: ['toolStatusPanel', 'modelCatalogPanel', 'integrations', 'providerCatalogPanel'],
    },
  };

  function setWorkspace(name, persist = true) {
    const workspace = workspaces[name] || workspaces.dashboard;
    state.workspace = workspaces[name] ? name : 'dashboard';
    document.querySelectorAll('.workspace-panel').forEach((panel) => {
      panel.hidden = !workspace.panels.includes(panel.id);
    });
    document.querySelectorAll('[data-workspace-nav]').forEach((button) => {
      button.classList.toggle('active', button.dataset.workspaceNav === name);
    });
    $('workspaceCrumb').innerHTML = `<strong>YOUTUBE AI FACTORY</strong><span> / </span> ${workspace.label}`;
    $('workspaceEyebrow').textContent = workspace.eyebrow;
    $('workspaceTitle').textContent = workspace.title;
    $('workspaceDescription').textContent = workspace.description;
    if (persist) {
      try { localStorage.setItem('ytFactory.workspace', name); } catch (_) {}
      saveStudioSession();
    }
    if (state.workspace === 'orchestration') void loadOrchestrationWorkspace();
    if (state.workspace === 'settings') void loadProviderCatalog();
    window.scrollTo({top: 0, behavior: 'smooth'});
  }

  const AUTOMATION_ROLE_LABELS = {
    research: 'Research', script: 'Script', director: 'Director', media: 'Media', qc: 'QC',
  };

  const AUTOMATION_STATUS_LABELS = {
    queued: 'Đang chờ', running: 'Đang làm', review_required: 'Chờ AI nghiệm thu',
    completed: 'Đã đạt', failed: 'Thất bại', cancelled: 'Đã huỷ', not_started: 'Chưa giao',
  };

  function automationUsageText(usage = []) {
    if (!usage.length) return 'chưa phát sinh lượt provider';
    const providers = new Map((state.providerCatalog || []).map((item) => [item.key, item]));
    const groups = {api: {count: 0, cost: 0}, subscription: {count: 0, cost: 0}, local: {count: 0, cost: 0}, unknown: {count: 0, cost: 0}};
    usage.forEach((item) => {
      const mode = providers.get(item.provider)?.billing_mode || 'unknown';
      const group = groups[mode] || groups.unknown;
      group.count += 1;
      group.cost += Math.max(Number(item.actual_cost || 0), Number(item.estimated_cost || 0));
    });
    const parts = [];
    if (groups.api.count) parts.push(`API trả phí: ${groups.api.count} lượt · dự chi $${groups.api.cost.toFixed(2)}`);
    if (groups.subscription.count) parts.push(`gói đã đăng ký: ${groups.subscription.count} lượt · không tính phí phát sinh`);
    if (groups.local.count) parts.push(`local: ${groups.local.count} lượt · không tính phí phát sinh`);
    if (groups.unknown.count) parts.push(`chưa phân loại: ${groups.unknown.count} lượt`);
    return parts.join(' · ');
  }

  function renderAutomationStageFlow(data) {
    const target = $('automationStageFlow');
    if (!target) return;
    const tasks = data?.agent_tasks || [];
    target.innerHTML = Object.entries(AUTOMATION_ROLE_LABELS).map(([role, label]) => {
      const task = tasks.find((item) => item.role === role);
      const status = task?.status || 'not_started';
      const execution = task?.output?._execution || {};
      const executor = execution.executor || task?.assigned_agent || 'chờ điều phối';
      const reviewer = execution.reviewer || task?.reviewer_agent || '';
      return `<div class="pipeline-stage ${esc(status)}">
        <div class="pipeline-stage-name">${esc(label)}</div>
        <div class="pipeline-stage-state">${esc(AUTOMATION_STATUS_LABELS[status] || status)}</div>
        <div class="pipeline-stage-agent">${esc(executor)}${reviewer ? ` → ${esc(reviewer)}` : ''}</div>
      </div>`;
    }).join('');
  }

  function renderAutomationMedia(data) {
    const board = $('automationMediaBoard');
    const summary = $('automationMediaSummary');
    const renders = $('automationRenderJobs');
    if (!board || !summary || !renders) return;
    const timeline = [...(data?.timeline || [])].sort((a, b) => Number(a.segment_index) - Number(b.segment_index));
    const latestJobs = new Map();
    (data?.scene_jobs || []).forEach((job) => {
      const key = Number(job.timeline_segment_id);
      if (!latestJobs.has(key)) latestJobs.set(key, job);
    });
    const visualReady = timeline.filter((item) => String(item.visual_path || '').trim()).length;
    const voiceReady = timeline.filter((item) => String(item.audio_path || '').trim()).length;
    const subtitleReady = timeline.filter((item) => String(item.subtitle_path || item.subtitle_text || '').trim()).length;
    const qcPassed = timeline.filter((item) => ['pass', 'approved'].includes(String(latestJobs.get(Number(item.id))?.review_status || ''))).length;
    summary.textContent = timeline.length
      ? `${timeline.length} cảnh · visual ${visualReady}/${timeline.length} · voice ${voiceReady}/${timeline.length} · subtitle ${subtitleReady}/${timeline.length} · QC cảnh ${qcPassed}/${timeline.length}`
      : 'Chưa có timeline. Director/Media Agent sẽ tạo bảng này khi pipeline đến bước dựng cảnh.';
    if (!timeline.length) {
      board.innerHTML = '<div class="empty">Pipeline chưa tạo cảnh.</div>';
    } else {
      const kindLabels = {image: 'Ảnh', gif: 'GIF', video: 'Video'};
      board.innerHTML = `<div class="media-board-head"><span>Cảnh</span><span>Nội dung</span><span>Provider / media</span><span>Asset</span><span>Voice</span><span>QC</span></div>` + timeline.map((item) => {
        const job = latestJobs.get(Number(item.id));
        const kind = kindLabels[job?.job_kind] || item.asset_type || 'chưa chọn';
        const jobState = job?.status || (item.visual_path ? 'completed' : 'not_started');
        const statusClass = jobState === 'completed' ? 'green' : jobState === 'failed' ? 'red' : ['running', 'queued', 'waiting'].includes(jobState) ? 'orange' : 'cyan';
        const review = String(job?.review_status || '');
        const reviewClass = ['pass', 'approved'].includes(review) ? 'green' : review === 'fail' ? 'red' : 'cyan';
        const reviewText = review ? `${review}${job?.review_score ? ` ${job.review_score}/10` : ''}` : 'chưa chấm';
        return `<div class="media-scene-row">
          <b>#${esc(item.segment_index)}</b>
          <span class="media-scene-copy" title="${esc(item.visual_prompt || item.voice_text || '')}">${esc(item.visual_prompt || item.voice_text || 'Chưa có mô tả')}</span>
          <span>${esc(job?.provider || '—')}<br><span class="tag ${statusClass}">${esc(kind)} · ${esc(AUTOMATION_STATUS_LABELS[jobState] || jobState)}</span></span>
          <span class="tag ${item.visual_path ? 'green' : 'orange'}">${item.visual_path ? 'ĐÃ GẮN' : 'THIẾU'}</span>
          <span class="tag ${item.audio_path ? 'green' : 'orange'}">${item.audio_path ? 'CÓ' : 'THIẾU'}</span>
          <span class="tag ${reviewClass}">${esc(reviewText)}</span>
        </div>`;
      }).join('');
    }
    const jobs = data?.production_jobs || [];
    renders.innerHTML = jobs.slice(0, 12).map((job) => {
      const statusClass = job.status === 'completed' ? 'green' : job.status === 'failed' ? 'red' : ['running', 'queued'].includes(job.status) ? 'orange' : 'cyan';
      return `<span class="tag ${statusClass}">${esc(job.job_type)} · ${esc(job.provider)} · ${esc(job.status)}</span>`;
    }).join('') || '<span class="secondary-text">Chưa có job voice/render.</span>';
  }

  function renderAutomationStatus(data) {
    const target = $('automationStatus');
    const summary = $('automationSummary');
    const tag = $('automationStateTag');
    if (!target || !summary || !tag || !data) return;
    const tasks = [...(data.agent_tasks || [])].reverse();
    const active = tasks.filter((task) => ['queued', 'running'].includes(task.status));
    const waitingReview = tasks.filter((task) => task.status === 'review_required');
    const failed = tasks.filter((task) => task.status === 'failed');
    const qc = [...tasks].reverse().find((task) => task.role === 'qc' && task.status === 'completed');
    const ready = Boolean(qc?.output?.ready_for_render);
    tag.className = `tag ${failed.length ? 'red' : (active.length || waitingReview.length) ? 'orange' : ready ? 'green' : 'cyan'}`;
    tag.textContent = failed.length ? 'CÓ TASK LỖI' : active.length ? `${active.length} ĐANG CHẠY` : waitingReview.length ? `${waitingReview.length} CHỜ AI NGHIỆM THU` : ready ? 'QC ĐÃ DUYỆT' : tasks.length ? 'PIPELINE ĐÃ DỪNG' : 'ĐANG KHỞI TẠO';
    summary.innerHTML = `Dự án <b>#${esc(data.project?.id)}</b> · ${esc(data.project?.title || '')} · ${tasks.length} task · ${data.agent_messages?.length || 0} message A2A · ${esc(automationUsageText(data.provider_usage || []))}
      <button class="btn small ghost" style="margin-left:8px" onclick="setWorkspace('production'); openProjectDetail(${Number(data.project?.id || 0)})">Mở dự án</button>`;
    target.innerHTML = tasks.map((task) => {
      const execution = task.output?._execution || {};
      const review = execution.review || {};
      const statusClass = task.status === 'completed' ? 'green' : task.status === 'failed' ? 'red' : ['running', 'review_required'].includes(task.status) ? 'orange' : 'cyan';
      const executor = execution.executor || task.assigned_agent || 'chờ điều phối';
      const reviewer = execution.reviewer || task.reviewer_agent || 'auto';
      const note = task.error || review.note || task.task_type || '';
      return `<div class="automation-task">
        <div class="automation-task-role">${esc(AUTOMATION_ROLE_LABELS[task.role] || task.role)}</div>
        <div><div>${esc(executor)} → nghiệm thu: ${esc(reviewer)}</div><div class="automation-task-meta">${esc(note)}</div></div>
        <span class="tag ${statusClass}">${esc(task.status)}</span>
      </div>`;
    }).join('') || '<div class="empty">Orchestrator đang tạo Research task đầu tiên...</div>';
    renderAutomationStageFlow(data);
    renderAutomationMedia(data);
  }

  // A pending approval is not a notice: `_automation_pause_active()` refuses to
  // queue any further media while one is open, so without a control here the
  // pipeline stays parked forever.
  const APPROVAL_LABELS = {
    provider_exhausted: 'Hết provider khả dụng',
    budget_exceeded: 'Chạm trần chi phí',
    final_publish: 'QC đã đạt — chờ bạn duyệt cuối',
    pipeline_exception: 'Pipeline chưa hoàn tất',
  };
  const BLOCKING_APPROVALS = ['provider_exhausted', 'budget_exceeded'];

  function approvalDetailText(approval) {
    const payload = approval.payload || {};
    const lines = [];
    if (payload.detail) lines.push(String(payload.detail));
    if (payload.error) lines.push(`Lỗi: ${payload.error}`);
    if (payload.capability) lines.push(`Loại media: ${payload.capability}`);
    if (payload.failed_provider) lines.push(`Provider lỗi: ${payload.failed_provider}`);
    if (payload.blocked_provider) lines.push(`Provider bị chặn: ${payload.blocked_provider}`);
    if (payload.score !== undefined && payload.score !== null) lines.push(`Điểm QC: ${payload.score}`);
    const issues = payload.issues || [];
    if (issues.length) lines.push(`Vấn đề: ${issues.slice(0, 5).join(' · ')}`);
    return lines.join(' · ');
  }

  function renderAutomationApprovals(data) {
    const target = $('automationApprovals');
    if (!target) return;
    const pending = (data?.approvals || []).filter((item) => item.status === 'pending');
    if (!pending.length) { target.innerHTML = ''; return; }
    target.innerHTML = pending.map((approval) => {
      const kind = String(approval.approval_type || '');
      const blocking = BLOCKING_APPROVALS.includes(kind);
      const label = APPROVAL_LABELS[kind] || kind;
      const detail = approvalDetailText(approval);
      return `<div class="approval-card ${blocking ? 'blocking' : ''}">
        <div class="approval-head">
          <span class="tag ${blocking ? 'red' : 'orange'}">${esc(label)}</span>
          <span class="approval-title">${esc(approval.title || label)}</span>
        </div>
        ${detail ? `<div class="approval-detail">${esc(detail)}</div>` : ''}
        <div class="approval-actions">
          <input id="approvalNote${approval.id}" type="text" placeholder="Ghi chú cho AI (bắt buộc khi yêu cầu sửa)" />
          <select id="approvalRole${approval.id}" aria-label="Chạy lại từ vai">
            <option value="media">Chạy lại từ Media</option>
            <option value="director">Chạy lại từ Director</option>
            <option value="script">Chạy lại từ Script</option>
            <option value="research">Chạy lại từ Research</option>
            <option value="qc">Chạy lại từ QC</option>
          </select>
          <button class="btn small primary" type="button" onclick="decideApproval(${approval.id}, 'approved')">Duyệt</button>
          <button class="btn small" type="button" onclick="decideApproval(${approval.id}, 'changes_requested')">Yêu cầu sửa</button>
          <button class="btn small ghost" type="button" onclick="decideApproval(${approval.id}, 'dismissed')">Bỏ qua</button>
        </div>
      </div>`;
    }).join('');
  }

  function renderAutomationInbox(approvals) {
    const target = $('automationInboxBody');
    if (!target) return;
    if (!approvals.length) {
      target.innerHTML = '<div class="empty">Không có quyết định nào đang chờ. Các AI có thể tiếp tục làm việc.</div>';
      return;
    }
    target.innerHTML = approvals.map((approval) => {
      const kind = String(approval.approval_type || '');
      const blocking = BLOCKING_APPROVALS.includes(kind);
      const label = APPROVAL_LABELS[kind] || kind;
      const project = approval.project || {};
      return `<div class="approval-card ${blocking ? 'blocking' : ''}">
        <div class="approval-head">
          <span class="tag ${blocking ? 'red' : 'orange'}">${esc(label)}</span>
          <span class="approval-title">#${esc(approval.project_id)} · ${esc(project.title || approval.title || '')}</span>
          <button class="btn small ghost" type="button" onclick="openAutomationProject(${Number(approval.project_id)})">Mở pipeline</button>
        </div>
        <div class="approval-detail">${esc(approvalDetailText(approval) || approval.title || '')}</div>
        <div class="approval-actions">
          <input id="inboxApprovalNote${approval.id}" type="text" placeholder="Ghi chú cho AI (bắt buộc khi yêu cầu sửa)" />
          <select id="inboxApprovalRole${approval.id}" aria-label="Chạy lại từ vai">
            <option value="media">Chạy lại từ Media</option><option value="director">Chạy lại từ Director</option>
            <option value="script">Chạy lại từ Script</option><option value="research">Chạy lại từ Research</option><option value="qc">Chạy lại từ QC</option>
          </select>
          <button class="btn small primary" type="button" onclick="decideApproval(${approval.id}, 'approved')">Duyệt</button>
          <button class="btn small" type="button" onclick="decideApproval(${approval.id}, 'changes_requested')">Yêu cầu sửa</button>
          <button class="btn small ghost" type="button" onclick="decideApproval(${approval.id}, 'dismissed')">Bỏ qua</button>
        </div>
      </div>`;
    }).join('');
  }

  async function loadAutomationInbox() {
    const target = $('automationInboxBody');
    try {
      const data = await api('/api/automation/approvals?status=pending');
      state.automationApprovals = data.approvals || [];
      renderAutomationInbox(state.automationApprovals);
      renderAutomationGlobalMetrics();
    } catch (error) {
      if (target) target.innerHTML = `<div class="empty">Không tải được hộp thư: ${esc(error.message)}</div>`;
    }
  }

  async function decideApproval(approvalId, decision) {
    const note = ($(`approvalNote${approvalId}`)?.value || $(`inboxApprovalNote${approvalId}`)?.value || '').trim();
    const resumeRole = $(`approvalRole${approvalId}`)?.value || $(`inboxApprovalRole${approvalId}`)?.value || 'media';
    if (decision === 'changes_requested' && !note) {
      setMessage('Hãy ghi rõ cần sửa gì trước khi giao lại cho AI.', 'error');
      return;
    }
    try {
      await api(`/api/automation/approvals/${approvalId}/decision`, {
        method: 'POST',
        body: JSON.stringify({decision, note, resume_role: resumeRole}),
      });
      setMessage('Đã ghi quyết định. Pipeline được mở lại.', 'success');
      await Promise.all([loadAutomationInbox(), loadAutomationProjectList()]);
      if (state.automationProjectId) await loadAutomationStatus();
    } catch (error) { setMessage(error.message, 'error'); }
  }

  // Why a provider is unusable is the question every stalled run raises.
  // The catalogue already carries the answer; nothing was reading it.
  const PROVIDER_BLOCK_REASONS = {
    gflow_not_logged_in: 'Chưa đăng nhập gflow-cli — chạy `gflow auth login` một lần',
    browser_extension_not_connected: 'Chỉ chạy được qua Extension YT Factory trong Cốc Cốc',
    no_browser_worker: 'Chưa có worker — chạy web_video_sidecar.py (Playwright, không cần extension) hoặc mở Extension',
    antigravity_sidecar_not_running: 'Antigravity đã đăng nhập nhưng sidecar chưa chạy',
    antigravity_not_ready: 'Antigravity CLI chưa đăng nhập',
    missing_api_key: 'Chưa nhập API key trong Kết nối AI',
    ffmpeg_not_available: 'Không tìm thấy FFmpeg trên máy',
    paid_api_disabled: 'Bị khoá bởi Automation Policy (API trả phí)',
    subscription_media_disabled: 'Bị khoá bởi Automation Policy (gói thuê bao)',
    usage_limit: 'Đã hết hạn mức, chờ tới giờ reset',
  };
  const BILLING_LABELS = {subscription: 'gói thuê bao', api: 'API trả phí', local: 'máy của bạn', unknown: 'không rõ'};

  async function loadProviderCatalog() {
    const target = $('providerCatalogBody');
    if (!target) return;
    try {
      const data = await api('/api/providers/catalog');
      state.providerCatalog = data.providers || [];
      const rows = state.providerCatalog.map((item) => {
        const runtime = item.runtime || {};
        const ok = runtime.available !== false;
        const why = PROVIDER_BLOCK_REASONS[runtime.reason] || runtime.reason || '';
        const cost = Number(item.estimated_unit_cost || 0);
        const money = cost > 0 ? `$${cost.toFixed(2)}/cảnh` : 'không tốn thêm';
        return `<div class="provider-row">
          <div><b>${esc(item.display_name || item.key)}</b>
            <div class="provider-why">${esc((item.capabilities || []).join(', '))} · ${esc(BILLING_LABELS[item.billing_mode] || item.billing_mode)} · ${esc(money)}${ok ? '' : ` · ${esc(why)}`}</div>
          </div>
          <span class="tag ${ok ? 'green' : 'orange'}">${ok ? 'DÙNG ĐƯỢC' : 'KHOÁ'}</span>
        </div>`;
      });
      target.innerHTML = rows.join('') || '<div class="empty">Chưa đăng ký provider nào.</div>';
      renderAutomationGlobalMetrics();
      if (state.automationStatus) renderAutomationStatus(state.automationStatus);
    } catch (error) {
      target.innerHTML = `<div class="empty">Không tải được danh mục: ${esc(error.message)}</div>`;
    }
  }

  function renderAutomationTrace(data) {
    const eventBox = $('automationEvents');
    if (eventBox) {
      const events = [...(data?.events || [])].reverse().slice(0, 60);
      eventBox.innerHTML = events.map((event) => {
        const when = String(event.created_at || '').slice(11, 19);
        return `<div class="trace-line"><b>${esc(event.event_type)}</b> · ${esc(event.source || 'app')} · ${esc(when)}</div>`;
      }).join('') || '<div class="empty">Chưa có sự kiện.</div>';
    }
    const messageBox = $('automationMessages');
    if (messageBox) {
      const messages = [...(data?.agent_messages || [])].reverse().slice(0, 60);
      messageBox.innerHTML = messages.map((message) => {
        const when = String(message.created_at || '').slice(11, 19);
        return `<div class="trace-line"><b>${esc(message.sender_agent)} → ${esc(message.recipient_agent)}</b> · ${esc(message.message_type)} · ${esc(when)}</div>`;
      }).join('') || '<div class="empty">Chưa có bàn giao.</div>';
    }
  }

  // Until now the only way back into a pipeline was the browser that started
  // it: the id lived in localStorage and nothing listed what else existed. A
  // run started from another machine, another browser, or the API was
  // invisible even though the server had every task, event and approval.
  async function loadAutomationProjectList() {
    const picker = $('automationProjectPicker');
    if (!picker) return;
    try {
      const data = await api('/api/automation/projects');
      state.automationProjects = data.projects || [];
      const current = String(state.automationProjectId || '');
      const options = state.automationProjects.map((entry) => {
        const project = entry.project || entry;
        const tasks = entry.agent_tasks || entry.tasks || [];
        const counts = entry.task_counts || {};
        const done = tasks.length ? tasks.filter((task) => task.status === 'completed').length : Number(counts.completed || 0);
        const total = tasks.length || Object.values(counts).reduce((sum, value) => sum + Number(value || 0), 0);
        const label = `#${project.id} · ${String(project.title || '').slice(0, 40)}${total ? ` · ${done}/${total} task` : ''}${entry.pending_approvals ? ` · ${entry.pending_approvals} chờ duyệt` : ''}`;
        return `<option value="${project.id}"${String(project.id) === current ? ' selected' : ''}>${esc(label)}</option>`;
      });
      picker.innerHTML = '<option value="">Mở lại chuỗi đã chạy...</option>' + options.join('');
      renderAutomationGlobalMetrics();
    } catch (_) { /* the picker is a convenience; its failure must not break the panel */ }
  }

  function renderAutomationGlobalMetrics() {
    const target = $('automationGlobalMetrics');
    if (!target) return;
    const projects = state.automationProjects || [];
    const active = projects.reduce((total, entry) => {
      const counts = entry.task_counts || {};
      return total + Number(counts.queued || 0) + Number(counts.running || 0) + Number(counts.review_required || 0);
    }, 0);
    const approvals = (state.automationApprovals || []).length;
    const readyProviders = (state.providerCatalog || []).filter((item) => item.runtime?.available !== false).length;
    const providerTotal = (state.providerCatalog || []).length;
    target.innerHTML = `
      <div class="orchestration-kpi"><label>Chuỗi đã tạo</label><strong>${number(projects.length)}</strong></div>
      <div class="orchestration-kpi"><label>Task đang chạy/chờ AI</label><strong>${number(active)}</strong></div>
      <div class="orchestration-kpi"><label>Chờ bạn phê duyệt</label><strong>${number(approvals)}</strong></div>
      <div class="orchestration-kpi"><label>Provider dùng được</label><strong>${number(readyProviders)}/${number(providerTotal)}</strong></div>`;
  }

  async function loadOrchestrationWorkspace() {
    await Promise.all([
      loadAutomationProjectList(), loadAutomationInbox(), loadProviderCatalog(),
      loadAutomationPolicy(), loadOrchestratorSettings(),
    ]);
    if (state.automationProjectId) await loadAutomationStatus(true);
  }

  async function openAutomationProject(projectId) {
    const id = Number(projectId || 0);
    if (!id) return;
    state.automationProjectId = id;
    try { localStorage.setItem('ytFactory.automationProjectId', String(id)); } catch (_) {}
    if ($('automationRefreshButton')) $('automationRefreshButton').disabled = false;
    await loadAutomationStatus();
  }

  // A scene holds a picture and a voice independently, but `status` can only
  // name one of them — and the voiceover job and the source cut each wrote
  // their own answer over the other's. Reading the paths says what is really
  // there, so finishing one half stops looking like losing the other.
  function segmentHaveBadges(segment) {
    const hasVisual = Boolean(String(segment.visual_path || '').trim());
    const hasVoice = Boolean(String(segment.audio_path || '').trim());
    return `<span class="have-badge ${hasVisual ? 'on' : 'off'}" title="${hasVisual ? esc(segment.visual_path) : 'Chưa có hình'}">${hasVisual ? '◉' : '○'} hình</span>`
      + `<span class="have-badge ${hasVoice ? 'on' : 'off'}" title="${hasVoice ? esc(segment.audio_path) : 'Chưa có giọng đọc'}">${hasVoice ? '◉' : '○'} tiếng</span>`;
  }

  function reportScriptLengthWarnings(writerResponse) {
    const box = $('studioWriterWarnings');
    const warnings = (writerResponse?.result || writerResponse)?.quality_warnings || [];
    if (!box) return;
    if (!warnings.length) { box.hidden = true; box.innerHTML = ''; return; }
    box.hidden = false;
    box.innerHTML = '<b>Kịch bản chưa đạt thời lượng mong muốn</b><br>'
      + warnings.map((line) => `· ${esc(line)}`).join('<br>')
      + '<br><span class="secondary-text">Sửa kịch bản dài thêm trước khi tạo giọng — số cảnh của storyboard bằng số đoạn trong kịch bản, và độ dài video bằng độ dài lời đọc.</span>';
  }

  async function applyTimelineCleanup(clear) {
    const projectId = Number(state.studioProjectId || state.projectId || 0);
    if (!projectId) { setMessage('Hãy mở một dự án trước.', 'error'); return; }
    const position = $('studioCleanupPosition')?.value || 'bottom_center';
    const method = $('studioCleanupMethod')?.value || 'blur';
    try {
      const result = await api(`/api/projects/${projectId}/timeline/cleanups`, {
        method: 'POST',
        body: JSON.stringify({position, method, clear: Boolean(clear)}),
      });
      renderCleanupState(result.cleanups, result.segments);
      setMessage(
        clear
          ? `Đã bỏ che trên ${result.segments} cảnh.`
          : `Đã đánh dấu che ${result.segments} cảnh. Render lại để áp dụng.`,
        'success');
    } catch (error) { setMessage(error.message, 'error'); }
  }

  // Short is a checkbox at the script step. Ticked, the AI writes it alongside
  // the long script and every step from there splits into two columns - the
  // long video on the left, the short beside it - so both are worked on in
  // view of each other rather than by switching back and forth. Unticked,
  // nothing about it shows: a project not making a short is not asked about one.
  const SHORT_LANE_PANES = ['studioStep3', 'studioStep4', 'studioStep5', 'studioStep6'];

  function shortLaneWanted() {
    return Boolean($('studioCreateStandaloneShort')?.checked) || Boolean(state.shortLane?.script);
  }
