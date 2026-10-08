# ASTRA_REFACTOR_IMPLEMENTATION_PLAN

> **TÀI LIỆU LỊCH SỬ** (ghi chú 2026-10-08). Kế hoạch 20–22/09. Đã được thay bằng kế hoạch hợp nhất luồng, Bước 1–4 và thiết kế Bước 5 (EditDocument). Trạng thái hiện tại xem `HANDOFF_GPT_BUOC5.md` (mục 14: bản đồ tài liệu) và `PROJECT_STATUS.md`.

## Reality check & correction plan — 2026-09-22

### Why this update exists

Two recent "end-to-end" tests did not meet the intended product goal. They proved parts of the app pipeline and renderer, but they did **not** prove that an AI Orchestrator can autonomously rebuild a video from source, choose suitable models/tools, generate new media, apply a professional edit plan, review the result, and render a final video.

The target remains:

```text
User request
  -> Main AI Orchestrator
  -> App tool layer
  -> AI/script/media/edit tools selected per step
  -> New script + new storyboard + new media/assets + applied edit plan
  -> QC/revision loop
  -> final render
```

### Errors found in the last two tests

| Area | What happened | Why it is a problem | Required fix |
|---|---|---|---|
| Test scope | The first test rendered an existing timeline/project instead of rebuilding from source. | It did not exercise the AI Orchestrator workflow. | Test must start with script rewrite or director draft, then rebuild storyboard/timeline before media/edit/render. |
| Script | The old script stayed active. GPT/Antigravity was not used to rewrite it. | The result inherited the old weak narrative and had no fresh concept. | End-to-end must call a real writer provider first. Preferred order: `openai_gpt` when API key exists, otherwise Antigravity/Codex/Claude runtime. |
| AI routing | UI/project policy stores `astra`, `chatgpt_app`, `claude`, but the local JSON executor only understood `antigravity`, `codex_cli`, `claude_code_cli`. | Storyboard/edit planning produced "Không có AI được phép thực hiện công đoạn storyboard" and silently fell back. | Add a runtime mapping layer: `astra -> antigravity`, `claude -> claude_code_cli`, `chatgpt_app -> codex_cli` until MCP/API runtime exists. |
| Fallback behavior | Edit plan fallback ran after AI failed and was treated like a real AI plan. | This hides runtime failure and gives a false sense that AI edited the video. | Fallback may create a draft/preview, but UI/API must label it clearly as fallback and not report it as AI Orchestrator output. |
| Media generation | No new AI images/video inserts were generated. Required jobs were listed but not fulfilled. | Visuals stayed close to source/old assets; no professional creative rebuild happened. | End-to-end must create or attach assets for every `required_assets` entry before final render, or mark final render as incomplete. |
| Graphics | Basic overlay text appeared, but no rich motion graphics like the reference examples. | The edit layer is still too simple: it lacks strong text reveal, stickers/icons/cards, callouts, punch effects. | Expand `EditPlan v2` execution to create graphic cards/icons/callouts through motion graphics/canvas/FFmpeg templates. |
| Audio/SFX | Sound cues were planned, but quality/timing was weak and there were audio issues. | SFX must support timing, volume, ducking, and validation against scene duration. | Add SFX render verification and scene-level audio report; fix cue timing/normalization before render. |
| Blur cleanup | Auto blur was applied to Content workflow and produced a wrong horizontal blur band. | Content workflow should not blur a source video unless a source visual strategy is explicitly used. | Auto cleanup is now limited to `reup` or source-dependent strategies; continue testing. |
| Transition render | FFmpeg `xfade` failed due to timebase mismatch. | Professional transitions could break final render. | Renderer now normalizes FPS/timebase/audio before crossfade. Keep regression tests. |
| Antigravity status | `agy models` reported logged in, but the real call later failed with "Antigravity CLI chưa đăng nhập" from the app process. | Provider status and execution readiness can disagree. | Refresh Antigravity status on real calls and surface execution failure directly; do not fallback silently. |
| App as Orchestrator tool | The app has tools/endpoints, but the run did not follow the intended tool-by-tool orchestration contract. | The user needs an auditable report: model/tool used per step and result per step. | Add an orchestration run report recording every step, selected provider, tool call, output artifact, failure, fallback, and next action. |

### What has been completed

- Main Orchestrator setting defaults to Astra and fallback to Claude in settings/UI.
- Per-stage model settings expose Auto and user-selectable routing.
- Provider routing exists for image/video providers in parts of the app.
- AI Desktop MCP bridge exposes project, storyboard, edit plan, media generation, voice, render, and asset import tools.
- Edit plan now stores richer per-scene fields:
  - `visual_strategy`
  - `required_assets`
  - `overlays`
  - `sound_cues`
  - `edit_direction`
  - `transition`
  - `effect`
  - cleanup instructions
- Timeline render can apply overlay/SFX/effect fields.
- Render readiness now distinguishes technical readiness from creative readiness.
- Renderer transition bug fixed: crossfade inputs are normalized before `xfade/acrossfade`.
- Wrong auto blur in Content workflow limited: auto source mark cleanup should run only for `reup` or explicit source visual strategies.
- Targeted tests passed after these renderer/planner changes:
  - FFmpeg renderer tests
  - review/planning tests
  - scene plan override tests
  - graphic overlay tests
  - workflow UI tests

### What is not complete yet

- A true end-to-end AI Orchestrator run has **not** been completed.
- GPT API is not available in the current local environment because `OPENAI_API_KEY` is missing.
- ChatGPT app MCP tunnel is not confirmed ready, so `chatgpt_app` cannot yet be used as the actual ChatGPT desktop runtime.
- Antigravity execution is installed/logged-in according to status checks, but a real writer call failed once with login status mismatch.
- No complete "fresh rebuild" has been rendered from:
  1. AI-written script,
  2. AI-created storyboard,
  3. generated new assets,
  4. applied professional edit plan,
  5. QC revision,
  6. final render.
- Visual asset generation jobs for edit plan `required_assets` are not yet guaranteed to run before render.
- Motion graphics are still basic; they do not yet match the reference style with strong animated text, icon cards, diagrams, and social ad overlays.
- SFX/audio mix needs a real quality pass.
- The app still lacks a clear audit trail showing "AI/model/tool used for each step".

### Correct next implementation sequence

Do not continue testing by rendering the old timeline. The next run must be a clean rebuild:

1. **Provider readiness gate**
   - Check actual execution readiness, not just saved settings.
   - Report available text runtimes:
     - `openai_gpt` only if `OPENAI_API_KEY` exists.
     - `chatgpt_app` only if MCP tunnel is live.
     - `astra` mapped to Antigravity runtime until true Astra MCP exists.
     - `claude` mapped to Claude Code CLI until true Claude API/app runtime exists.
   - If a provider fails on real execution, mark that step failed and route fallback explicitly.

2. **Rewrite script first**
   - Start from source/project brief.
   - Call real writer provider:
     - preferred: `openai_gpt` when configured,
     - fallback: `antigravity`,
     - fallback: `claude_code_cli`,
     - fallback: `codex_cli`.
   - Save a new script version.
   - Rebuild shots and timeline from that new script.

3. **AI Director edit plan**
   - Call mapped Orchestrator runtime for storyboard/edit planning.
   - The plan must choose per scene:
     - visual type,
     - required media assets,
     - graphic overlays,
     - text animation,
     - SFX,
     - transition,
     - camera/effect,
     - source dependency/risk.
   - If AI call fails, stop or label fallback as fallback. Do not present fallback as AI output.

4. **Generate missing assets before render**
   - For every `required_assets` entry, create a scene generation job or local motion graphic asset.
   - Wait for completion or mark missing.
   - Attach generated assets to timeline/edit beats.

5. **Apply edit plan**
   - Apply only after the plan has been approved or auto-approved by the Orchestrator policy.
   - Persist overlays, SFX, direction, beats, transitions, effects, cleanup.

6. **Render preview**
   - Render a draft/preview.
   - Create contact sheet and technical media report.

7. **QC and revision**
   - AI reviews script cohesion, visual difference from source, graphics, audio/SFX, blur/cleanup, pacing.
   - Generate a `RevisionPlan`.
   - Apply targeted fixes.

8. **Final render**
   - Render final only after QC passes or user explicitly accepts draft quality.

### Required audit report format for every future end-to-end run

Every AI Orchestrator run must produce a report like:

| Step | Selected model/tool | Why selected | Input | Output artifact | Status | Fallback used |
|---|---|---|---|---|---|---|
| Script rewrite | e.g. Antigravity | GPT unavailable, Antigravity logged in | source transcript + brief | script id | success/fail | no/yes |
| Storyboard/edit plan | e.g. Antigravity | Astra mapped runtime | new script + source profile | edit plan id | success/fail | no/yes |
| Media generation | provider per scene | chosen by Provider Gateway | required assets | asset ids/jobs | success/fail | no/yes |
| Apply edit | app timeline tool | deterministic apply | edit plan | updated timeline | success/fail | n/a |
| Render | FFmpeg renderer | deterministic render | timeline/assets/audio | mp4 path | success/fail | n/a |
| QC | selected reviewer | quality gate | mp4/contact sheet | QC report | pass/fail | no/yes |

If this table cannot be filled with real model/tool calls, the run is not a valid end-to-end AI Orchestrator test.

## Implementation update — 2026-09-20

Completed first code pass for the "AI Orchestrator toolbox" direction:

- Astra is now the default main Orchestrator in settings.
- Claude is now the default fallback Orchestrator.
- ChatGPT app remains available as a secondary/specialist agent through MCP.
- The UI now has separate selectors for main Orchestrator and fallback Orchestrator.
- Per-stage agent assignments now expose Astra, ChatGPT app, and Claude.
- Analysis/writer/chat model selectors now support `Auto`, where the backend chooses an available text provider.
- Scene image/video provider selectors now support `Auto`, resolved through `/api/providers/route` before jobs are created.
- Scene edit apply now resolves `Auto` image provider before generating auxiliary AI images.
- Scene-level edit planning now stores renderable graphic overlays and sound cues, not only visual beats.
- Scene edit apply now materializes planned local SFX presets into project audio assets so FFmpeg can mix them during render.
- Storyboard cards now show planned dynamic text layers and sound cues.
- Astra/MCP tool layer now exposes scene edit beat planning and scene edit beat apply tools.
- The in-app Orchestrator action registry now includes `plan_scene_edits` and `apply_scene_edits`, so the AI coordinator can plan/apply professional scene edits from a plain-language intent.
- Timeline scene plan endpoint now supports manual overlay/SFX overrides, with validation against scene duration.
- Storyboard UI now exposes quick JSON editors for dynamic text overlays and SFX cues per scene.
- Integration status now shows Astra MCP and ChatGPT MCP tunnel readiness separately.
- Both `ASTRA_MCP_TUNNEL_ID` and `CHATGPT_MCP_TUNNEL_ID` can be saved from the dashboard integration settings.
- Basic validation passed:
  - Python compile for changed backend modules.
  - JS syntax check for changed frontend modules.
  - `_HE_THONG/app/tests/test_settings.py` passed.
  - Relevant targeted tests passed: settings, MCP, review/planning, scene plan override, FFmpeg renderer.

Remaining next steps:

- Wire a real Astra runtime/MCP tunnel for executing Orchestrator decisions from Astra itself, not just exposing the app-side MCP/tool contract.
- Extend the tool layer for the remaining production actions that are still only available through the UI.
- Add manual overlay/SFX editing controls if the user wants to hand-tune AI plans from the storyboard.
- Add integration tests for provider routing and edit-plan apply once the runtime choices are finalized.

## 0. Audit status

`CURRENT_APP_AUDIT.md` was requested as the primary input, but it is not present in the workspace or in the provided attachments at the time this plan was written.

Search performed:

- `F:\YouTube_AI_Factory\CURRENT_APP_AUDIT.md`: not found.
- `F:\YouTube_AI_Factory\**\*AUDIT*.md`: not found.
- `C:\Users\ADMIN\.codex\attachments\**\CURRENT_APP_AUDIT.md`: not found.

This plan therefore uses the current source code and existing project documentation as the audit basis, especially:

- `HUONG_DAN_SU_DUNG.md`
- `_HE_THONG/tai_lieu/KE_HOACH_DU_AN.md`
- `_HE_THONG/tai_lieu/STORYBOARD_EDITOR_CLEANUP_PLAN.md`
- `_HE_THONG/app/youtube_monitor/*`

When `CURRENT_APP_AUDIT.md` is added later, this plan should be reconciled against it before implementation.

## 1. Current State Summary

The app is not a blank editor. It already contains a substantial production pipeline and should be upgraded by reuse first.

Existing workflow:

1. Video nguồn
2. Phân tích
3. Kịch bản
4. Tạo giọng
5. Storyboard
6. Dựng
7. Xuất bản

Target product workflow after the 2026-09-20 Orchestrator update:

1. Video nguồn
2. Phân tích
3. Research & Ý tưởng
4. Kịch bản
5. Tạo giọng
6. Storyboard / Media
7. Dựng
8. Xuất bản

Existing backend and storage:

- FastAPI monolith in `_HE_THONG/app/youtube_monitor/main.py`.
- SQLite wrapper in `_HE_THONG/app/youtube_monitor/database.py`.
- Core tables already exist for channels, videos, transcripts, production projects, scripts, shots, timeline segments, edit beats, edit plans, jobs, publications, assets, thumbnails, render settings, scene generation jobs, provider usage, agent tasks, agent messages, approvals, and events.
- `project_timeline_segments` is the main production timeline.
- `project_timeline_edit_beats` already supports multi-beat edits inside one segment.
- `project_edit_plans` already separates draft edit proposals from live timeline state.

Existing source and ingestion capability:

- YouTube channel/video metadata through `youtube_client.py`, service routes, sync jobs.
- Local media import and project assets through project asset APIs.
- URL import for many sites through `source_links.py` using yt-dlp metadata without download.
- Video download for editing through `video_downloader.py`.
- Folder footage upload appears in the UI (`studioFolderUpload`) but should be verified as a complete backend path before relying on it.
- Article/product/prompt-first inputs are not first-class production sources yet.

Existing analysis capability:

- Metadata analysis via `analyzer.py` and `llm_analyzer.py`.
- Transcript via `transcriber.py`, transcript queue, manual transcript save, YouTube captions import.
- Reference analysis via `reference_analyzer.py`, focused on recording what the source contains.
- Source visual cutting and source cue planning through `source_visuals.py` and timeline source cue endpoints.
- Local asset transcript support through `project_asset_transcripts`.
- Some visual analysis exists around scene asset review, image analysis, burned mark detection, source visual previews, and contact sheets, but there is no unified "Astra context package" yet.

Existing script capability:

- `writer.py` has workflow-aware writing for content and faithful retell.
- `shot_planner.py` converts script and writer blueprints into storyboard shots.
- Script revision, approval, fidelity check, translation, and pasted script import already exist.

Existing voice capability:

- `production_worker.py` supports voiceover jobs.
- Edge TTS and VoxCPM paths exist, with voice previews and project voice library.
- Voice review endpoint exists and listens back to generated voice.

Existing storyboard/media capability:

- `project_shots`, `project_timeline_segments`, `scene_generation_jobs`, `project_assets`.
- Provider gateway exists in `_HE_THONG/app/youtube_monitor/providers`.
- Scene generation supports API providers, browser/sidecar providers, gflow, stock footage, and motion graphics.
- Existing Content workflow generates AI scenes.
- Existing Reup workflow cuts source clips from the downloaded source.

Existing editor/render capability:

- `ffmpeg_renderer.py` renders timeline with voice, visuals, subtitles, cleanup, motion, transitions, background music, and edit beats.
- `motion_graphics.py` renders Remotion motion graphics scenes.
- Premiere export pack exists through `premiere_export.py`.
- Draft edit planning exists around `/api/projects/{project_id}/edit-plan`.
- Recent in-progress files such as `scene_direction.py`, `scene_compositor.py`, and `scene_composer` are present in the workspace but should be treated as unreviewed until tested and reconciled.

Existing job/automation capability:

- `analysis_queue.py`, `transcript_queue.py`, `production_worker.py`, `scene_generator.py`, `publisher.py`.
- `agent_system.py` has role tasks: research, script, director, media, qc.
- Automation pipeline endpoints exist under `/api/automation/*`.
- Event bus and agent messages exist.

Existing publish capability:

- `publisher.py` supports YouTube upload only.
- Publication queue and manual package endpoints exist.
- Platform copy, publish checklist, copyright check, and OAuth routes exist.

Existing AI/tool bridge:

- `ai_desktop_mcp.py` exposes a local MCP bridge for ChatGPT Desktop.
- It already has tools for creating projects, starting pipeline, listing events/providers, generating media, building timeline, generating voice, rendering, getting storyboard, importing assets, and completing external scene jobs.
- This bridge is the closest current piece to the target "Astra operates the app" architecture, but it is still partial and should be normalized into a formal tool layer.

## 2. Target Architecture

Target runtime:

```text
User
  -> AI Orchestrator
  -> Video App Tool Layer
  -> Research Tools / AI Tools / Creative Tools / Production Tools
  -> Project / Assets / Timeline / Render
```

Roles:

- AI Orchestrator = the single main Director model for a project. Default target: Astra.
- Astra = primary Orchestrator by default: understand, reason, classify, decide, select tools, create plans, review tool results, request revisions, and move the project through the production pipeline.
- ChatGPT app = secondary/specialist model inside this app. It can do writing, brainstorming, review, tool-assisted work, and MCP tasks when the Orchestrator chooses it.
- Claude = fallback Orchestrator when configured and Astra is unavailable or unsuitable; Claude can also be used as a specialist text/review tool when Astra is active.
- App = collect, measure, execute, store, render, queue, retry, publish.
- GPT, Gemini, ChatGPT Web, Gemini Web, Google Flow, Meta AI, image/video providers, and similar integrations = specialist tools the Orchestrator can call. They are not peer project directors.
- Codex = development only. Codex is not part of runtime orchestration.

Principles:

- Move the product workflow from 7 steps to 8 steps by adding Research & Ý tưởng after Phân tích.
- Do not rewrite app from scratch.
- Do not duplicate systems already present.
- UI actions and Orchestrator tools must call the same service functions.
- Manual mode must continue to work.
- The active Orchestrator should call direct tools/services rather than using computer-use when a service exists.
- Do not hard-code "step X always uses model Y". Existing model settings become AI Tool / Capability Configuration.
- Orchestrator should see available tools, capabilities, cost/provider policy, and login/session state before choosing a tool.
- Keep user-facing model/provider selection for each step, but add `Auto` as the default option. In `Auto`, the Orchestrator chooses the best available AI/tool for that step.
- Keep user-facing selection of the main Orchestrator model. Default is Astra, with Claude as configured fallback.

## 3. Mapping 8 Steps To The New Architecture

| Step | Current app pieces to reuse | New Astra role | Main upgrade |
|---|---|---|---|
| 1. Video nguồn | `source_links.py`, `video_downloader.py`, upload/assets, YouTube metadata, project creation | Interpret user goal and source intent | Add unified `SourcePackage` summary on top of existing rows |
| 2. Phân tích | transcripts, reference analysis, metadata analysis, asset analysis, source visual helpers | Build `ContentProfile` and transformation constraints | Split technical analysis from semantic analysis |
| 3. Research & Ý tưởng | source links, existing research agent records, web/reference/provider adapters to be normalized | Decide if research is needed, call research tools, synthesize `ResearchPackage` and `ContentIdea` | Add source manager, research package, visual references, and content angle before script |
| 4. Kịch bản | `writer.py`, `shot_planner.py`, script APIs | Choose rewrite strategy and structured script intent from source + research + idea | Add transformation-aware script contract without breaking current script fields |
| 5. Tạo giọng | `production_worker.py`, voice settings, voice review | Choose tone, pacing, narrator style | Store voice direction separately from deterministic TTS execution |
| 6. Storyboard / Media | `project_shots`, timeline, scene jobs, provider gateway | Make Visual/Media Plan per scene using script, research, references, and existing assets | Storyboard becomes planning + media generation, not just static images |
| 7. Dựng | timeline, edit beats, edit plans, FFmpeg, motion graphics, Premiere export | Produce executable `EditPlan` and review preview | Add richer editor tools and review loop |
| 8. Xuất bản | publication queue, publisher, platform copy, checklist | Generate title/description/hashtags/thumbnail concept | Keep app responsible for actual upload and packaging |

## 4. KEEP Matrix

| Area | Keep | Reason |
|---|---|---|
| 8-step workflow | Yes | User explicitly wants Research & Ý tưởng added between analysis and script |
| Current UI as main UI | Yes | Target says no ChatGPT app embedding in this phase |
| SQLite project schema | Yes | Already covers production state |
| `production_projects` | Yes | Central project entity |
| `project_scripts` | Yes | Existing script versions and approval flow |
| `project_shots` | Yes | Existing storyboard scene structure |
| `project_timeline_segments` | Yes | Main render timeline |
| `project_timeline_edit_beats` | Yes | Good base for per-segment edit decisions |
| `project_edit_plans` | Yes | Already separates draft plan from applied state |
| `project_assets` | Yes | Existing media library |
| `scene_generation_jobs` | Yes | Provider jobs already queue/retry |
| Provider Gateway | Yes | Correct abstraction for image/video providers |
| `production_worker.py` | Yes | Existing voice/render/source visuals worker |
| `ffmpeg_renderer.py` | Yes | Deterministic render engine |
| `motion_graphics.py` | Yes | Existing Remotion graphics scene provider |
| `quality_check.py` | Yes | Base technical QC |
| `publisher.py` | Yes | YouTube publish integration exists |
| `ai_desktop_mcp.py` | Keep and refactor | Closest current bridge for Orchestrator tools |
| `agent_system.py` | Reuse selectively | Durable A2A/task state exists, but runtime should become Astra-led |

## 5. REFACTOR Matrix

| Current area | Problem | Refactor target |
|---|---|---|
| FastAPI route logic in `main.py` | Too much orchestration inside route handlers | Move reusable operations into service/tool modules |
| MCP bridge | Tool list mixes old automation and direct production operations | Promote into formal `tools` package with schemas, permissions, state summaries |
| Writer/director/media tasks | Multiple AI roles are runtime agents | Convert role logic into capabilities Astra can invoke or replace |
| Edit plan | Exists but not yet a full professional executable edit contract | Expand into scene direction, graphics, SFX, beats, revision data |
| Storyboard | Mixes visual prompt, timeline, generation, manual edits | Split Shot/Scene intent from Media Plan and execution jobs |
| Project state | Multiple endpoints expose pieces | Add compact `ProjectContext` for Astra |
| QC | Mostly technical and provider review | Add content-type-aware Astra review rubric |
| UI | Current flow is busy and feature scattered | Move to 8-step navigation, add AI Director panel and state-aware actions |

## 6. NEW Capabilities Matrix

| Capability | Why needed | Add as |
|---|---|---|
| `SourcePackage` | Normalize video, image, folder, article, product, prompt sources | Thin schema over existing video/project/assets |
| `TechnicalContext` | Give Astra measured facts | Read-only service output |
| `ResearchPackage` | Store facts, source links, visual references, uncertainties, and opportunities | New director artifact or existing analysis/artifact JSON first |
| `SourceManager` | Track research source metadata and rights/use status | New service over assets/links/artifacts; table later if needed |
| `ContentIdea` | Bridge source/research to script with angle, audience, tone, and value | New plan artifact consumed by writer/storyboard |
| `ContentProfile` | Classify content and factual constraints | Astra plan object stored with project/script |
| `TransformationStrategy` | Decide Preserve/Reframe/Expand/Rebuild/Full recreate | Astra plan object |
| `VisualMediaPlan` | Decide per scene source/generated/graphic/B-roll | Extends storyboard and scene jobs |
| `CharacterProfile` | Keep generated people consistent | New project-level entity or project asset metadata |
| `EditPlan v2` | Executable professional edit instructions | Extends `project_edit_plans` and timeline fields |
| `PreviewReviewReport` | Let Astra inspect output and revise | New review artifact tied to project job |
| `RevisionPlan` | Apply targeted fixes without rerunning all | New plan object using existing patch endpoints |
| Tool permission metadata | READ/PLAN/EXECUTE/RENDER side-effect clarity | Tool registry |
| Tool capability discovery | Let Orchestrator pick only available specialist tools | Tool registry state and provider/session status |

## 7. Components To Deprecate Or Limit

| Component | Decision |
|---|---|
| Runtime path `Astra -> Codex -> Video App` | Do not build |
| Multiple AI agents as simultaneous primary runtime directors | Do not build |
| Director router where Astra/Claude/Gemini are equal active project directors | Do not make core architecture |
| User-selected primary Orchestrator with Claude fallback | Keep. This is a failover policy, not a peer-director architecture |
| Hard-coded model per production step | Replace with capability-based AI Tool Settings |
| Computer-use for app internals | Avoid when direct service/tool exists |
| Browser sidecar providers | Keep for media generation where provider has no API |
| Premiere/CapCut as core renderer | Keep as export/optional automation, not first rendering backbone |
| New database parallel to current project schema | Avoid |
| Manual mode | Must not deprecate |

## 8. Astra Orchestrator Design

Astra should be represented as the default AI Director orchestrator with tool access. The app must still let the user choose the primary Orchestrator model. One active project has one active Orchestrator at a time. Claude can be configured as fallback when Astra is unavailable, but that fallback is a controlled failover, not a second Director running in parallel. Other AI systems are specialist tools called by the active Orchestrator.

Core responsibilities:

- Interpret natural user goals.
- Request project context.
- Classify content.
- Decide whether research is needed and how much.
- Choose transformation strategy.
- Choose specialist tools by capability, availability, quality, cost, and task fit.
- Decide what to keep/change/rebuild.
- Produce structured script/media/edit/revision plans.
- Trigger app tools.
- Read specialist tool results.
- Review generated text, images, videos, previews, and reports.
- Decide whether to accept, revise, regenerate, use another tool, or ask the user.

Runtime shape:

```text
Active Orchestrator session
  reads ProjectContext
  calls READ tools
  creates or updates ResearchPackage and ContentIdea when needed
  writes PLAN artifacts
  calls EXECUTE/RENDER tools when allowed by mode
  reviews PreviewPackage
  writes RevisionPlan
```

Implementation target:

- New module: `youtube_monitor/astra_orchestrator.py`
- New module: `youtube_monitor/tool_layer/registry.py`
- New module: `youtube_monitor/tool_layer/context.py`
- New module: `youtube_monitor/research_package.py`
- New module: `youtube_monitor/source_manager.py`
- Existing `ai_desktop_mcp.py` becomes a transport adapter for the same tool registry.

## 8A. Model Control And Auto Tool Selection

The current app already has model/provider settings for analysis, writing, image generation, video generation, voice, render, orchestrator, and automation agents. Keep these controls.

Add one consistent option to step-level model/provider controls:

```text
Auto
```

When a step is set to `Auto`, the active Orchestrator chooses the best available AI/tool for that task by reading:

- requested task and current step
- project context
- available tool capabilities
- provider login/API-key/session state
- quota and cooldown state
- user policy for paid API/subscription/local tools
- quality fit for the content type
- expected cost and time

When a step is manually set to a specific provider/model, the Orchestrator should respect that choice unless the selected provider is unavailable or blocked. If blocked, it should report the reason and either ask in Assist/Manual mode or choose another allowed tool in Auto mode according to policy.

Orchestrator model settings:

- Primary Orchestrator: default `Astra`, user-selectable in app settings.
- Secondary model: `ChatGPT app`, used as specialist/subtask model and MCP-capable assistant inside the app.
- Fallback Orchestrator: `Claude`, used only when the primary Orchestrator is unavailable, over quota, or explicitly switched by the user.

Fallback rules:

- Preserve project state before failover.
- Record which Orchestrator handled the turn.
- Do not let fallback bypass tool policy, cost policy, or approval gates.
- When Astra becomes available again, continue with Astra unless the user has changed the primary Orchestrator selection.

## 8B. AI ORCHESTRATOR + RESEARCH WORKFLOW UPDATE

This section records the 2026-09-20 planning update. It changes the product architecture and roadmap only; it does not imply an implementation change by itself.

Primary architecture:

```text
User
  -> AI Orchestrator
  -> Video App Tool Layer
  -> Research Tools / AI Tools / Creative Tools / Production Tools
  -> Project / Assets / Timeline / Render
```

The active Orchestrator is the only project Director. GPT, Gemini, ChatGPT app, ChatGPT Web, Gemini Web, Google Flow, Meta AI, image generators, video generators, and similar providers are tools with capabilities. Claude is the configured fallback Orchestrator when Astra is unavailable, and can also be used as a specialist text/review tool while Astra is active. Specialist tools can help with text, reasoning, vision, image, video, prompt generation, review, and synthesis, but they do not own the project state or declare the project finished.

The app becomes the Orchestrator's production environment. A manual UI button and an Orchestrator tool call must use the same underlying service whenever they do the same operation. For example, `generate_voice()` should not have one implementation for the UI and another implementation for the Orchestrator.

Research & Ý tưởng becomes Step 3 in the product workflow. The Orchestrator decides whether to research, how much to research, and which sources or references matter. Comic/image story projects may need LOW or NONE. History, documentary, news, article, and product projects usually need MEDIUM or HIGH. Survival/outdoor projects depend on whether the task is a faithful rebuild or an expanded educational video.

Research is not only for script writing. It can feed Storyboard / Media with maps, product references, archive references, diagrams, visual examples, location references, clothing/period references, and prompt material for generating new assets.

Video and image search are reference tools first. Search results are not assumed to be publishable footage. Every found item should be classified as `REFERENCE_ONLY`, `USABLE_ASSET`, `FACT_SOURCE`, `VISUAL_REFERENCE`, or `GENERATE_FROM_REFERENCE`.

`ResearchPackage` target shape:

```text
ResearchPackage
  topic
  research_goal
  verified_facts[]
  supporting_sources[]
  conflicting_information[]
  timeline[]
  entities[]
  product_specs[]
  comparisons[]
  quotes_or_key_points[]
  visual_references[]
  video_references[]
  potential_broll[]
  source_urls[]
  uncertainties[]
  content_opportunities[]
  research_notes
```

`SourceItem` target shape:

```text
SourceItem
  id
  type
  url
  title
  publisher
  retrieved_at
  used_for
  reliability_status
  rights_use_status
  notes
```

`ContentIdea` target shape:

```text
ContentIdea
  target_audience
  core_angle
  storytelling_style
  hook_direction
  emotional_tone
  new_value
  structure
  intended_duration
  visual_direction
```

## 9. Context Strategy

Do not send raw project state every time.

Context levels:

| Context | Contents | Use |
|---|---|---|
| `ProjectContextCompact` | project, workflow, current step, script summary, timeline status, job status, warnings | Every Astra turn |
| `SourceContext` | source metadata, transcript summary, reference analysis, technical facts | Strategy and script |
| `ResearchContext` | research package summary, sources, references, uncertainties, content opportunities | Research, idea, script, storyboard/media |
| `SceneContext` | one scene, nearby transcript, keyframes, assets, edit plan | Scene work |
| `PreviewContext` | rendered preview path, sample frames, audio metrics, issue list | Review |
| `ToolResultContext` | compact outputs from recent tool calls | Continuation |

Heavy data policy:

- Keep raw transcript in DB/files.
- Give Astra relevant ranges.
- Use keyframes/contact sheets instead of full video.
- Use asset IDs and paths, not binary data.
- Cache summaries with revision hashes.

## 10. Tool Layer Design

Tool categories:

| Category | Side effect | Examples |
|---|---|---|
| READ | None | get project context, get source package, list assets, get transcript range, get timeline, list tool capabilities |
| RESEARCH | Reads web/provider/reference sources; may store draft research artifacts | web search, article fetch, video search, image search, official source lookup |
| AI_TEXT_VISION | Calls specialist reasoning/vision/text tools | GPT ask, Gemini ask, Claude ask, summarize, classify, brainstorm, translate, review |
| CREATIVE_MEDIA | Calls image/video provider tools | GPT image, Gemini image, Meta image, Flow video, image-to-video, video-to-video where verified |
| PLAN | Writes draft artifacts only | create research package, create content idea, create content profile, create transformation strategy, create media plan, create edit plan |
| EXECUTE | Mutates project/jobs/assets | generate media, attach asset, update scene, apply revision |
| RENDER | Expensive media output | render preview, render final, render short |
| PUBLISH | External distribution or package prep | prepare metadata, package upload, upload/publish with policy gate |

Tool layer rules:

- UI and Astra use the same implementation.
- Tool returns must be compact and structured.
- Every side-effect tool records event bus entries.
- Every expensive tool supports status polling.
- Confirmation policy lives outside the core implementation so AUTO/ASSIST/MANUAL can share it.
- Tool registry must expose current capability state: `AVAILABLE`, `DISABLED`, `LOGIN_REQUIRED`, `CONFIG_REQUIRED`, `QUOTA_LIMITED`, `ERROR`, or `UNKNOWN`.
- Orchestrator can request a capability such as "high-quality image-to-video with character reference"; the tool layer may route that to a provider-specific tool without changing Orchestrator logic.
- A specialist AI tool can produce drafts or assets, but the Orchestrator reviews and decides whether to use them.

Initial tools to normalize from existing endpoints:

- `get_project_context`
- `get_source_package`
- `run_technical_analysis`
- `list_tool_capabilities`
- `research_web_search`
- `research_fetch_source`
- `research_video_search`
- `research_image_search`
- `save_research_package`
- `save_content_idea`
- `save_content_profile`
- `save_transformation_strategy`
- `ai_text_ask`
- `ai_vision_review`
- `ai_image_generate`
- `ai_video_generate`
- `save_script_plan`
- `build_storyboard`
- `save_visual_media_plan`
- `queue_scene_generation`
- `build_timeline`
- `save_edit_plan`
- `apply_edit_plan`
- `render_preview`
- `review_preview`
- `apply_revision_plan`
- `render_final`
- `prepare_publication`

## 11. Technical Analysis Design

Reuse existing app modules:

- Metadata: existing video/channel service and `analyzer.py`.
- Transcript: `transcriber.py`, `transcript_queue.py`, captions import.
- Reference content reading: `reference_analyzer.py`.
- Source clip cue/cut analysis: `source_visuals.py`.
- Media probing: `media_probe.py`, `ffmpeg_renderer.media_duration_seconds`.
- Quality metrics: `quality_check.py`.
- Burned marks and cleanup: `burned_in_marks.py`, timeline cleanup endpoints.
- Face/person/OCR detection: verify actual current coverage before adding. If absent, add later as technical analyzers, not inside Astra.

Output target:

```text
TechnicalContext
  source metadata
  transcript availability and ranges
  scene/dialogue map if available
  media duration, fps, size, orientation
  keyframes/contact sheet references
  source clip availability
  audio loudness/silence notes
  visual safety areas and detected marks
  asset inventory
```

## 11A. Research & Idea Design

Research sits between technical/semantic analysis and script writing.

The Orchestrator should decide the research level from `ContentProfile`, source type, user request, and risk:

| Content type | Default research level | Notes |
|---|---|---|
| Comic / image story | LOW or NONE | Preserve story unless user asks to add new context. Focus on narration, pacing, voice, animation, effects, transitions, and sound design. |
| History / documentary | HIGH | Use multiple sources, chronology, maps/archive/reference, and fact verification. Do not invent events. |
| News / article | HIGH | Compare sources, fetch latest context, track attribution and conflicting reports. |
| Product | MEDIUM/HIGH | Use manufacturer specs, reviews/comparisons, complaints, use cases, and product visuals. Claims must be supported. |
| Survival / outdoor | LOW to HIGH | Faithful rebuild may skip research. Educational expansion needs context and safety checks. |
| Talking head / explainer | LOW/MEDIUM | Research only if the video needs added facts, examples, or updated context. |

Research tool group:

- `web.search`
- `web.fetch`
- `article.search`
- `news.search`
- `video.search`
- `image.search`
- `official_source.lookup`
- `documentation.search`
- `archive.search`
- `product_spec.search`
- `map_location.lookup`

Research output should feed:

- `ContentIdea` before script.
- `ScriptPlan` with verified facts and uncertainties.
- `VisualMediaPlan` with visual references and allowed asset strategies.
- `EditPlan` when research implies graphics, maps, diagrams, comparisons, or stat cards.

End-to-end example: article URL.

```text
Input article
  -> extract article
  -> analyze topic
  -> research supporting and official sources
  -> ResearchPackage
  -> ContentIdea / angle
  -> script
  -> voice
  -> Storyboard / MediaPlan
  -> image/video/graphic tools
  -> edit
  -> preview
  -> Orchestrator review
  -> publish package
```

End-to-end example: video URL.

```text
Input video
  -> technical analysis
  -> semantic analysis
  -> content classification
  -> decide research need
  -> optional ResearchPackage
  -> TransformationPlan
  -> script
  -> media plan and required assets
  -> edit
  -> preview/review/final
```

## 12. Content Classification Design

Add `ContentProfile`, produced by Astra after technical context.

Fields:

- `content_type`: comic_image_story, historical_documentary, product, survival_outdoor, news_article, explainer, talking_head, tutorial, other.
- `factuality_requirement`: low, medium, high.
- `story_integrity`: loose, preserve_beats, strict.
- `source_dependency`: none, transcript_only, visual_reference, source_footage_required.
- `creative_freedom`: low, medium, high.
- `must_keep`: people, names, numbers, events, chronology, ending, product claims.
- `may_change`: wording, hook, pacing, visuals, examples, CTA, music, graphics.
- `must_avoid`: invented facts, changed names, unsupported claims, face reuse, copied watermark.
- `evidence`: references to transcript ranges, source analysis, metadata.

Storage:

- Phase 1 can store in `project_edit_plans.plan_json` or `video_analyses` as a new analysis type.
- Later add `project_director_artifacts` if multiple plan types need first-class versioning.

## 13. Transformation Strategy Design

Modes:

- `PRESERVE`: keep story/content; improve pacing, voice, typography, SFX.
- `REFRAME`: same facts/story, new angle/hook/order within allowed limits.
- `EXPAND`: add context, examples, graphics, B-roll where allowed.
- `REBUILD_SELECTED`: replace selected scenes while preserving continuity.
- `FULL_RECREATE`: create new video inspired by source style/topic, only when source allows.

Mode selection by content:

- Comic/image story: usually `PRESERVE` or `REFRAME`; protect story integrity.
- Historical/documentary/news: `PRESERVE`, `REFRAME`, or controlled `EXPAND`; protect facts.
- Product: `REFRAME`, `EXPAND`, or `FULL_RECREATE`; claims must remain supported.
- Survival/outdoor: `PRESERVE` or `REBUILD_SELECTED`; protect action continuity.
- Explainer/talking head: `REFRAME` with strong graphics and typography.

Store strategy with:

- chosen mode
- rationale
- risk level
- required human approval points
- affected scenes
- allowed media generation types

## 14. Script Design

Current script schema should be preserved:

- `project_scripts.script_title`
- `hook`
- `intro`
- `main_content`
- `cta`
- version/status/approval

Add structured script layer without breaking old fields:

```text
ScriptPlan
  transformation_strategy_id
  narration_units[]
    scene_key
    speaker
    voice_text
    intent
    factual_evidence
    preserve_from_source
    rewrite_scope
  warnings[]
```

Implementation path:

- Extend `writer.py` prompts to accept `ContentProfile` and `TransformationStrategy`.
- Keep `scene_blueprints` for backward compatibility.
- Add validation that high-factuality content does not add unsupported names/numbers.
- Keep `shot_planner.py` as the fallback bridge from script to storyboard.

## 15. Voice Integration

Keep app deterministic:

- TTS remains in `production_worker.py`.
- Voice settings remain in `project_render_settings`.
- Voice review remains through current `/voice/review`.

Astra decides:

- narrator style
- pacing
- emotion
- speaker/character voice intent
- pause/beat notes

Suggested data:

```text
VoiceDirection
  narrator_style
  emotion
  pace
  emphasis[]
  per_scene_notes[]
```

Do not use Astra to synthesize audio directly when the app already has TTS providers.

## 16. Storyboard / Media Generation Redesign

Current storyboard should evolve into Visual Planning + Media Generation.

Reuse:

- `project_shots`
- `project_timeline_segments`
- `scene_generation_jobs`
- `project_assets`
- Provider Gateway
- `motion_graphics.py`
- `source_visuals.py`

Add:

```text
VisualMediaPlan
  scenes[]
    segment_id
    visual_role
    action: keep_source | trim_source | source_still | ai_image | ai_video | image_to_video | stock_footage | motion_graphics | screenshot | map | archive
    provider_policy
    prompt
    reference_asset_ids
    character_profile_ids
    duration
    acceptance_criteria
```

Workflow behavior:

- Content workflow can use AI image/video, stock footage, motion graphics.
- Reup workflow defaults to source clips, but can add source supplementary clips or generated inserts when user asks.
- Additional source clips are assets and can be selected by Astra, but the app should not search many clips by default for the current two workflows.

## 17. Character Consistency Design

Need: replace or generate multiple scenes with one consistent character.

Check current state:

- `project_assets` can store reference images/videos.
- `scene_generation_jobs.reference_asset_id` exists.
- There is no first-class `CharacterProfile` yet.

Add later:

```text
CharacterProfile
  id
  project_id
  name
  role
  description
  reference_asset_ids
  face_policy
  outfit
  body_type
  continuity_notes
  provider_instructions
```

Storage options:

- Phase 1: store in plan JSON and reference existing assets.
- Phase 2: add `project_character_profiles` table when generation reuse becomes stable.

## 18. EditPlan Design

Current:

- `project_edit_plans` stores plan JSON.
- `project_timeline_edit_beats` stores visual beats.
- `ffmpeg_renderer.py` can apply motion, cleanup, transitions, subtitles, overlays, and beats.

Target `EditPlan v2`:

```text
EditPlan
  version
  project_id
  script_id
  source_revision
  style
  scenes[]
    segment_id
    scene_goal
    pacing
    visual_beats[]
    graphic_layers[]
    audio_cues[]
    subtitles
    transitions
    cleanup
    review_notes
```

Graphic layer examples:

- kinetic title
- speech bubble
- icon flow
- brush label
- stat card
- lower third
- CTA card

Audio cue examples:

- pop
- whoosh
- chime
- tick
- rise
- soft impact

Important rule:

- EditPlan must be executable, not descriptive.
- If Astra says "make it dynamic", the plan is invalid unless it includes timing, preset, position, and asset references.

## 19. Editor Tool Design

Expose small, direct tools instead of requiring Astra to manipulate UI:

READ:

- `get_timeline`
- `get_scene`
- `get_edit_plan`
- `get_preview_report`

PLAN:

- `draft_edit_plan`
- `patch_scene_edit_plan`
- `draft_revision_plan`

EXECUTE:

- `apply_edit_plan`
- `replace_scene_visual`
- `insert_edit_beat`
- `attach_asset`
- `queue_media_generation`
- `apply_timeline_cleanup`

RENDER:

- `render_scene_preview`
- `render_project_preview`
- `render_final`

Existing endpoints/functions to reuse:

- `/api/projects/{project_id}/edit-plan`
- `/api/timeline/{segment_id}/edit-beats`
- `/api/projects/{project_id}/timeline/{segment_id}/edit-preview`
- `/api/projects/{project_id}/jobs`
- `database.replace_timeline_edit_beats`
- `ffmpeg_renderer.render_timeline_with_ffmpeg`

## 20. Preview / Review / Revision Loop

Current app has QC and scene review but no full Astra preview loop.

Target loop:

1. App renders low-cost preview.
2. App extracts:
   - sample frames
   - audio metrics
   - overlay manifest
   - duration and resolution
   - missing assets
   - scene job results
3. Astra reviews against rubric selected from `ContentProfile`.
4. Astra writes `RevisionPlan`.
5. App applies targeted changes.
6. Repeat with max loop count.

Default max loops:

- Assist mode: 1 suggested revision unless user asks more.
- Auto mode: 2 loops.
- Manual mode: none unless user triggers review.

Rubric by type:

- Comic: story integrity, emotional rhythm, panel presentation, voice acting, SFX.
- History/news: factual integrity, chronology, context clarity, unsupported visuals.
- Product: hook, benefit clarity, product visibility, CTA, claims.
- Survival/outdoor: action continuity, environment continuity, character consistency.
- Explainer/talking head: typography clarity, graphic timing, pacing, audio emphasis.

## 21. Job Engine Changes

Reuse:

- `project_jobs`
- `scene_generation_jobs`
- `analysis_jobs`
- workers and queue status endpoints
- event bus
- retry/cancel APIs

Add:

- Orchestrator step jobs can be represented as `agent_tasks` or new director artifacts.
- Tool calls should emit domain events.
- Long work should never block the UI or Astra turn.
- Retry should be scene/job scoped.

Production job chain:

```text
SOURCE
ANALYSIS
RESEARCH
IDEA
STRATEGY
SCRIPT
VOICE
MEDIA PLAN
MEDIA GENERATION
EDIT PLAN
PREVIEW
REVIEW
REVISION
FINAL
PUBLISH
```

UI should show the 8 product steps.

## 22. UI/UX Redesign

No UI redesign in the current planning phase.

Future UI target:

- Top: 8-step progress navigation: Video nguồn, Phân tích, Research & Ý tưởng, Kịch bản, Tạo giọng, Storyboard / Media, Dựng, Xuất bản.
- Left: projects, media/assets.
- Center: current step content, preview, timeline/editor.
- Right: AI Director panel with current context, plan, recommendations, actions.
- Research & Ý tưởng step: sources found, research status, key facts, visual references, ContentIdea/angle, user notes, and Ask Director.

AI Director panel requirements:

- Knows current project, step, scene, selected asset.
- Knows current source, current research package, current idea, and current plan when available.
- Can explain current plan.
- Can show pending actions and approvals.
- Can accept natural language such as "Cảnh này chưa ổn" using current selected scene.
- Can accept research/media directives such as "tìm thêm video tham khảo", "không sử dụng footage web trực tiếp", "dùng Flow tạo cảnh này", or "cảnh này chỉ cần ảnh + zoom".

Manual controls remain visible and usable.

## 23. Auto / Assist / Manual Mode

Modes:

| Mode | Behavior |
|---|---|
| AUTO | Active Orchestrator may progress through pipeline using allowed tools and policy gates. Step-level `Auto` lets it choose AI/tools. |
| ASSIST | Active Orchestrator proposes, user approves, app executes. Step-level `Auto` produces recommendations before execution when needed. |
| MANUAL | User uses current UI and selected models/providers; Orchestrator may answer or suggest but not execute automatically. |

All three modes must use the same tool layer.

Suggested default:

- New users: ASSIST.
- Existing manual workflow: MANUAL.
- Batch/autopipeline: AUTO with spending/provider policy gates.

Model/provider selection behavior:

- Every existing step-level model/provider dropdown remains.
- Add `Auto` to each step-level dropdown where a model/provider can be chosen.
- `Auto` delegates selection to the active Orchestrator.
- Manual provider choice overrides `Auto` for that step.
- Provider/tool availability is still enforced by the app; the Orchestrator cannot force a disabled, logged-out, over-quota, or policy-blocked provider.

## 24. Data / Schema Changes

Avoid schema churn early. Use JSON artifact storage first where existing structures allow it.

Near-term:

- Extend JSON artifact storage with `ResearchPackage`, `SourceItem`, `ContentIdea`, `ContentProfile`, `TransformationStrategy`, `VisualMediaPlan`, `EditPlan`.
- Extend render/timeline APIs to surface these plan artifacts.
- Add revision hash fields inside plan JSON, using current `source_revision` pattern.

Likely later tables:

- `project_director_artifacts`: versioned plan artifacts by type.
- `project_source_items`: source manager records, if existing link/asset rows are not enough.
- `project_character_profiles`: reusable generated character references.
- `project_preview_reviews`: preview review and revision artifacts.
- `project_tool_runs`: durable tool execution log, if event bus is not enough.

Do not add tables before the data contract stabilizes.

## 25. Migration Strategy

Migration goals:

- Old projects continue to open.
- Old Content/Reup workflows continue to render.
- Existing manual storyboard/timeline operations continue to work.
- No plan artifact should be required for final render.

Migration approach:

- If no `ResearchPackage`: treat research as not yet run; do not block existing video rebuild workflows.
- If no `ContentIdea`: derive a minimal angle from workflow, source title, and current script metadata.
- If no `ContentProfile`: infer minimal profile from workflow and source.
- If no `TransformationStrategy`: default Content to `REFRAME`, Reup to `PRESERVE`.
- If no `VisualMediaPlan`: use existing shot/timeline asset type.
- If no `EditPlan v2`: render current timeline unchanged.
- Keep old overlay/edit beat support while adding richer plan execution.

## 26. Backwards Compatibility

Compatibility rules:

- Do not block render just because a new AI plan is absent.
- Do not require research for every project.
- Do not force all scenes through AI media generation.
- Do not remove current source clip workflow.
- Do not remove existing script/shot/timeline endpoints.
- New tools must be wrappers around current functions where possible.
- Old MCP tool names can remain as aliases for one release cycle after tool layer normalization.

## 27. Test Strategy

Baseline tests:

- Run current unit tests before phase 1.
- Add focused tests before each refactor phase.

Test groups:

- Tool registry tests: schema, permission category, side effect labels.
- Tool capability tests: available/disabled/login-required/quota-limited tools are exposed correctly and the Orchestrator does not call unavailable providers.
- Project context tests: compact context excludes huge raw data and includes required state.
- Research package tests: sources, facts, uncertainties, visual references, and rights/use status are stored without assuming web media is publishable.
- Source manager tests: `REFERENCE_ONLY`, `USABLE_ASSET`, `FACT_SOURCE`, `VISUAL_REFERENCE`, and `GENERATE_FROM_REFERENCE` are preserved.
- Content idea tests: ResearchPackage can produce an angle/structure before script.
- Content classification tests: content type maps to correct strategy constraints.
- Script tests: high-factuality content preserves names/numbers/order.
- Media plan tests: Reup defaults to source clips; Content defaults to AI/media choices; Storyboard receives research context when available.
- Character profile tests: generated scene jobs reuse reference assets.
- EditPlan tests: invalid vague plans rejected; valid executable plans apply to timeline/edit beats.
- Render tests: existing no-plan render still works.
- Preview review tests: issue report creates targeted revision plan.
- UI tests: 8-step nav shows Research & Ý tưởng, mode selection works, AI Director panel shows current state.
- Migration tests: old projects without plan artifacts still load and render.

Acceptance scenarios added by the 2026-09-20 update:

1. Article URL: extract article, research supporting/official sources, create ContentIdea, write script, plan visuals/media, edit, and prepare publish package.
2. Existing video URL: analyze source, decide whether research is needed, create TransformationPlan, script, replacement/additional media plan, and edit plan.
3. Product link: extract product, research manufacturer/specs/reviews/comparisons, create advertising angle, script, product media plan, and edit.
4. Comic/image story: little or no external research unless needed; preserve story; improve narration, effects, transitions, and sound design.
5. History/documentary: high research, multi-source facts, no fabricated events, maps/archive/reference, documentary script.
6. Specialist AI text tool: Orchestrator asks GPT/Gemini/Claude for alternatives, reviews them, selects/edits one, and continues project state itself.
7. Flow/video tool: Orchestrator decides a scene needs generated video, Flow generates, Orchestrator reviews, regenerates or registers the asset and continues.

Do not run the app server in the background during tests unless explicitly requested.

## 28. Risks

| Risk | Mitigation |
|---|---|
| App becomes two systems: UI path and Astra path | Single tool/service layer shared by both |
| Astra writes nice prose but unusable plan | Strict executable schemas and validation |
| Token/context blowup | Compact ProjectContext and range-based transcript/keyframe access |
| Generated media lacks consistency | CharacterProfile and reference asset reuse |
| Reup factual/story drift | ContentProfile + strict TransformationStrategy + fidelity checks |
| Provider sidecars fail silently | Keep provider runtime states and event bus visible |
| Render regressions | Keep no-plan render path and add regression tests |
| `main.py` refactor breaks routes | Extract gradually, one service at a time |
| User loses manual control | Manual mode and existing controls remain |
| Cost runaway | Existing provider usage/billing policy reused and exposed to Astra |

## 29. Performance / Usage Considerations

Token usage:

- Use compact context by default.
- Use scene-scoped context for scene changes.
- Summarize transcripts and only pass relevant ranges.
- Store plans and revision hashes.

Compute:

- Reuse existing queues.
- Preview should render lower resolution or selected scenes first.
- Avoid rerendering full project after small revision.
- Cache keyframes, waveforms, speech timing, and preview reports.

Provider cost:

- Keep existing provider usage tracking.
- Route through Provider Gateway.
- Let Astra see provider availability and cost policy, but the app enforces it.

## 30. Implementation Phases

Updated phase map after the 2026-09-20 Orchestrator + Research update:

1. Existing tool/service normalization.
2. AI Orchestrator foundation.
3. Tool Registry and capability discovery.
4. Research Tool Layer.
5. ResearchPackage / Source Manager.
6. Research & Idea workflow.
7. AI specialist tools for text/reasoning/vision.
8. Web AI provider adapters for ChatGPT Web, Gemini Web, Google Flow, Meta AI, and similar providers.
9. Storyboard / MediaPlan integration with research context.
10. Editor tool integration and executable EditPlan v2.
11. Orchestrator review loop for specialist outputs, previews, and revisions.
12. UI 8-step workflow redesign with persistent AI Director panel.
13. Auto / Assist / Manual behavior using the shared tool layer.
14. Tests, migration, recovery, and provider failure handling.

The detailed phase sections below keep the earlier implementation notes, but their execution order should follow this updated map. Research phases now come before script/media planning; specialist AI providers are tools under the Orchestrator, not separate project directors.

### Phase 0 - Baseline And Audit Reconciliation

Goal:

Establish the real baseline and reconcile this plan with `CURRENT_APP_AUDIT.md` once available.

Existing modules reused:

- All current tests and docs.
- `HUONG_DAN_SU_DUNG.md`, `KE_HOACH_DU_AN.md`.

Files/modules likely affected:

- Test runner config only if needed.
- This plan.

New modules:

- None.

Existing modules modified:

- None.

Schema/data changes:

- None.

UI changes:

- None.

Tests:

- Run existing Python tests.
- Run existing JS/UI parse tests if present.

Migration concerns:

- None.

Definition of Done:

- Baseline test result recorded.
- Audit file absence or contents reconciled.
- Existing dirty worktree documented before implementation.

Dependencies:

- Audit file if provided.

Rollback:

- No runtime changes.

### Phase 1 - Service Boundary Inventory

Goal:

Identify which route logic can become reusable services without behavior change.

Existing modules reused:

- `database.py`, `main.py`, `writer.py`, `shot_planner.py`, `timeline_builder.py`, `production_worker.py`, `scene_generator.py`, `publisher.py`.

Files/modules likely affected:

- Documentation only in this phase.

New modules:

- None yet.

Existing modules modified:

- None.

Schema/data changes:

- None.

UI changes:

- None.

Tests:

- None beyond baseline.

Migration concerns:

- None.

Definition of Done:

- Final list of service extraction targets and route dependencies.

Dependencies:

- Phase 0.

Rollback:

- Documentation only.

### Phase 2 - Tool Layer Skeleton

Goal:

Create a formal tool registry used by UI adapters, MCP, and future Astra orchestration.

Existing modules reused:

- `ai_desktop_mcp.py` tool definitions.
- Existing endpoint/service logic.

Files/modules likely affected:

- `_HE_THONG/app/youtube_monitor/ai_desktop_mcp.py`
- New `tool_layer` package
- Tests for MCP/tool schemas

New modules:

- `youtube_monitor/tool_layer/__init__.py`
- `youtube_monitor/tool_layer/registry.py`
- `youtube_monitor/tool_layer/types.py`
- `youtube_monitor/tool_layer/context.py`

Existing modules modified:

- `ai_desktop_mcp.py` becomes transport adapter over registry.

Schema/data changes:

- None.

UI changes:

- None.

Tests:

- Tool registry exposes existing tool names.
- READ/PLAN/EXECUTE/RENDER metadata is present.
- Existing MCP behavior still works.

Migration concerns:

- Keep old tool names as aliases.

Definition of Done:

- MCP still exposes the same tools.
- New registry can call at least read project, build timeline, queue voice, queue render.

Dependencies:

- Phase 1.

Rollback:

- Revert adapter to previous direct implementation.

### Phase 3 - Project Context Normalization

Goal:

Give Astra a compact, stable view of project state.

Existing modules reused:

- `database.get_production_project_bundle`
- `list_project_timeline`
- `list_scene_generation_jobs`
- `list_project_jobs`
- `list_provider_usage`
- event bus APIs.

Files/modules likely affected:

- `tool_layer/context.py`
- `database.py` if small helper queries are needed
- `main.py` only to expose endpoint if UI needs it

New modules:

- `youtube_monitor/project_context.py`

Existing modules modified:

- `ai_desktop_mcp.py` to expose `youtube_factory_get_project_context`.

Schema/data changes:

- None.

UI changes:

- None.

Tests:

- Context excludes huge transcript by default.
- Context includes current step, workflow, active script, storyboard count, timeline readiness, job summary, provider blocks, latest errors.

Migration concerns:

- Old projects with missing timeline/scripts return partial context, not errors.

Definition of Done:

- Astra can understand project status from one compact tool call.

Dependencies:

- Phase 2.

Rollback:

- Disable new context tool.

### Phase 4 - Technical Analysis Package

Goal:

Normalize app-measured source facts for Astra.

Existing modules reused:

- `transcriber.py`
- `reference_analyzer.py`
- `source_visuals.py`
- `media_probe.py`
- `quality_check.py`
- `burned_in_marks.py`
- existing analysis queues.

Files/modules likely affected:

- `project_context.py`
- `tool_layer`
- maybe `database.py` helper accessors

New modules:

- `youtube_monitor/technical_context.py`

Existing modules modified:

- Minimal route/tool wiring.

Schema/data changes:

- Prefer storing as `video_analyses.analysis_type = "technical_context"` first.

UI changes:

- Optional debug summary in analysis step later.

Tests:

- Builds context with metadata only.
- Builds context with transcript.
- Builds context with local asset.
- Missing files produce warnings, not crashes.

Migration concerns:

- No required data for existing projects.

Definition of Done:

- `get_source_package` and `get_technical_context` tools exist.

Dependencies:

- Phase 3.

Rollback:

- Remove tool exposure; no schema rollback if using existing analyses table.

### Phase 5 - Content Profile And Transformation Strategy

Goal:

Let Astra classify content and choose transformation mode before script/media/edit decisions.

Existing modules reused:

- `reference_analyzer.py`
- `writer.py`
- workflow registry.

Files/modules likely affected:

- New `astra_orchestrator.py`
- `tool_layer`
- `writer.py` prompt inputs later

New modules:

- `youtube_monitor/content_profile.py`
- `youtube_monitor/transformation_strategy.py`

Existing modules modified:

- Tool/MCP exposure.

Schema/data changes:

- Store plan artifacts in `project_edit_plans.plan_json` or `video_analyses` first.

UI changes:

- Show content type/strategy in Analysis step later.

Tests:

- Comic/history/product/survival/news examples classify to expected constraints.
- High factuality strategy blocks unsupported expansion.

Migration concerns:

- Default profile inferred from workflow if absent.

Definition of Done:

- Astra can create and save `ContentProfile` and `TransformationStrategy`.

Dependencies:

- Phase 4.

Rollback:

- Ignore strategy artifacts; existing writer path remains.

### Phase 5A - Research Tool Layer, Source Manager, And Content Idea

Goal:

Add the new Step 3 foundation before script writing.

Existing modules reused:

- `source_links.py`
- existing research agent/task records
- provider status/configuration surfaces
- project assets and event bus

Files/modules likely affected:

- `tool_layer`
- `project_context.py`
- `database.py` helper accessors if needed
- optional `main.py` routes for UI read/write

New modules:

- `youtube_monitor/research_package.py`
- `youtube_monitor/source_manager.py`
- optional `youtube_monitor/content_idea.py`

Existing modules modified:

- Tool/MCP exposure for research and source package operations.
- Project context includes research status and latest ContentIdea summary.

Schema/data changes:

- Store first as `project_director_artifacts` or JSON in existing analysis/artifact storage.
- Add dedicated source item table only after the SourceItem contract stabilizes.

UI changes:

- Later Step 3 view: sources, facts, visual references, uncertainties, idea/angle, notes, and Ask Director.

Tests:

- Article/product/history/comic/survival research-level decisions.
- Source rights/use status is preserved.
- Web images/videos default to reference-only unless marked otherwise.
- ResearchPackage can feed ContentIdea and later ScriptPlan.

Definition of Done:

- Orchestrator can decide LOW/NONE/MEDIUM/HIGH research, save a ResearchPackage, save ContentIdea, and continue to script without manual model selection.

Dependencies:

- Phase 4 and Tool Registry capability discovery.

Rollback:

- Existing source -> script path still works without ResearchPackage.

### Phase 6 - Script Integration

Goal:

Make scripts transformation-aware without breaking current script storage.

Existing modules reused:

- `writer.py`
- `shot_planner.py`
- script review/fidelity endpoints.

Files/modules likely affected:

- `writer.py`
- `shot_planner.py`
- `main.py` script endpoints only if necessary
- tests for writer/shot planner

New modules:

- Optional `script_plan.py`

Existing modules modified:

- Writer prompt accepts profile/strategy.
- Shot planner reads structured narration units when present.

Schema/data changes:

- Store structured `ScriptPlan` in plan JSON or script-associated artifact.

UI changes:

- None required first.

Tests:

- Existing script generation still returns current schema.
- Reup faithful retell still preserves names/numbers/order.
- Rewrite version still overrides old writer blueprints.

Migration concerns:

- Old scripts produce shots through current fallback.

Definition of Done:

- Astra can request write/rewrite/preserve-narration-only using same script endpoints/tools.

Dependencies:

- Phase 5.

Rollback:

- Disable structured ScriptPlan consumption.

### Phase 7 - Visual / Media Plan

Goal:

Turn Storyboard into scene-level media planning while keeping current storyboard UI.

Existing modules reused:

- `project_shots`
- `project_timeline_segments`
- `scene_generation_jobs`
- Provider Gateway
- `source_visuals.py`
- `motion_graphics.py`

Files/modules likely affected:

- `scene_generator.py`
- `providers/gateway.py`
- `main.py` scene job endpoints
- `project-detail.js` for plan display later

New modules:

- `youtube_monitor/media_plan.py`

Existing modules modified:

- Batch scene generation can accept `VisualMediaPlan`.

Schema/data changes:

- Store plan first in JSON artifact.
- Later add plan table only if needed.

UI changes:

- Storyboard shows each scene action: source, AI image, AI video, stock, graphics, etc.

Tests:

- Reup defaults to source clips.
- Content can choose AI image/video/stock/motion.
- Additional source assets can be selected.
- Provider policy respected.

Migration concerns:

- Existing `asset_type` remains fallback.

Definition of Done:

- Astra can create media plan and queue only missing scene jobs.

Dependencies:

- Phase 6.

Rollback:

- Use existing scene job batch flow.

### Phase 8 - Character Consistency

Goal:

Support reusable characters/reference assets across generated scenes.

Existing modules reused:

- `project_assets`
- `scene_generation_jobs.reference_asset_id`
- asset upload/import.

Files/modules likely affected:

- `database.py`
- `scene_generator.py`
- provider prompt builders
- UI asset panel later

New modules:

- `youtube_monitor/character_profiles.py`

Existing modules modified:

- Provider request creation includes character profile references.

Schema/data changes:

- Add `project_character_profiles` after JSON prototype is proven.

UI changes:

- Add character/reference section in Storyboard or Assets.

Tests:

- Profile stores reference asset IDs.
- Scene job receives reference asset.
- Missing reference blocks or warns depending mode.

Migration concerns:

- Existing projects have no profiles and continue.

Definition of Done:

- Astra can create one character profile and reuse it across generated scenes.

Dependencies:

- Phase 7.

Rollback:

- Leave reference assets as ordinary assets.

### Phase 9 - EditPlan v2 And Editor Tools

Goal:

Make professional editing executable: graphics, text timing, SFX, visual beats, transitions.

Existing modules reused:

- `project_edit_plans`
- `project_timeline_edit_beats`
- `ffmpeg_renderer.py`
- `graphic_overlays.py`
- `motion_graphics.py`
- existing edit-plan endpoints.

Files/modules likely affected:

- `ffmpeg_renderer.py`
- `database.py`
- `main.py` edit-plan endpoints
- renderer tests

New modules:

- `youtube_monitor/edit_plan_v2.py`
- `youtube_monitor/graphics_compositor.py` if Remotion overlay path is kept

Existing modules modified:

- Existing edit plan validation and apply.
- Renderer reads new plan fields when present.

Schema/data changes:

- Prefer JSON inside `project_edit_plans`.
- Add columns only after v2 contract is stable.

UI changes:

- Storyboard/dựng step shows plan summary and scene-level edit details.

Tests:

- Invalid vague plans rejected.
- Valid plan applies to edit beats.
- Render still works without edit plan.
- Graphics and SFX appear in preview sample.

Migration concerns:

- No-plan render remains supported.

Definition of Done:

- Astra can create a plan that results in visible timed text/graphics/SFX in rendered preview.

Dependencies:

- Phase 7.

Rollback:

- Ignore v2 plan and render existing timeline.

### Phase 10 - Preview Review And Revision

Goal:

Close the loop: render preview, let Astra review, apply targeted fixes.

Existing modules reused:

- `quality_check.py`
- scene review logic
- render preview endpoints
- event bus
- project jobs.

Files/modules likely affected:

- `production_worker.py`
- `quality_check.py`
- `main.py`
- `tool_layer`

New modules:

- `youtube_monitor/preview_review.py`
- `youtube_monitor/revision_plan.py`

Existing modules modified:

- Add preview package generation.

Schema/data changes:

- Store `PreviewReviewReport` and `RevisionPlan` in plan JSON first.

UI changes:

- AI Director panel shows review findings and proposed fixes.

Tests:

- Preview package includes frames/report.
- Review produces bounded revision actions.
- Revision applies to one scene without rerunning all media.

Migration concerns:

- If no review, user can still manually render final.

Definition of Done:

- One preview loop can improve an EditPlan without rebuilding entire project.

Dependencies:

- Phase 9.

Rollback:

- Disable review loop; final render still works.

### Phase 11 - Job Engine And Automation Alignment

Goal:

Make AUTO mode run the full chain with durable state and limited loops.

Existing modules reused:

- `agent_system.py`
- `project_jobs`
- `scene_generation_jobs`
- event bus
- automation approvals.

Files/modules likely affected:

- `agent_system.py`
- `main.py` automation endpoints
- `database.py`
- `tool_layer`

New modules:

- `youtube_monitor/astra_pipeline.py`

Existing modules modified:

- Existing multi-agent role sequence becomes compatibility path or legacy auto pipeline.

Schema/data changes:

- Maybe add director artifact table if JSON storage becomes too cramped.

UI changes:

- Mode selector and pipeline status.

Tests:

- AUTO respects provider/cost policy.
- ASSIST stops for approval.
- Failed scene retries do not restart whole pipeline.

Migration concerns:

- Existing automation tasks remain readable.

Definition of Done:

- Astra-led AUTO can progress through a small project to preview.

Dependencies:

- Phase 10.

Rollback:

- Fall back to current automation pipeline.

### Phase 12 - AI Director UI Panel

Goal:

Add Astra Director into current UI without replacing the main workflow; navigation becomes the 8-step product flow.

Existing modules reused:

- `templates/index.html`
- `static/project-detail.js`
- `static/app.css`
- existing step navigation.

Files/modules likely affected:

- UI static files.
- New endpoints for context/tool calls if not already present.

New modules:

- None backend if tool layer is ready.

Existing modules modified:

- Add right-side panel.
- Add current selection context.

Schema/data changes:

- None.

UI changes:

- Right panel: chat, current plan, recommendations, current actions.
- Mode selector: AUTO/ASSIST/MANUAL.
- Top navigation includes Research & Ý tưởng as Step 3.
- Step 3 shows research status, sources, facts, references, ContentIdea, notes, and Director actions.

Tests:

- UI parse tests.
- Current scene selection is passed to Director panel.
- Manual controls still operate.

Migration concerns:

- Panel can be hidden/disabled.

Definition of Done:

- User can ask "cảnh này chưa ổn" and Astra receives selected scene context.

Dependencies:

- Phase 3 and Phase 10.

Rollback:

- Hide panel; old UI remains.

### Phase 13 - Publish Polish

Goal:

Let Astra assist publication metadata while app controls final upload.

Existing modules reused:

- `publisher.py`
- platform copy
- publish checklist
- thumbnail generator/selector
- OAuth routes.

Files/modules likely affected:

- `platform_copy.py`
- `thumbnail_prompt.py`
- publish endpoints
- UI publish panel

New modules:

- Optional `publish_plan.py`

Existing modules modified:

- Publication preparation can use Astra suggestions.

Schema/data changes:

- Store publish plan in publication row or artifact JSON.

UI changes:

- AI suggested title/description/hashtags/chapters/thumbnail concept.

Tests:

- YouTube-only upload guard remains.
- Scheduled/private/default privacy respected.
- Publication can be prepared without uploading.

Migration concerns:

- Current manual package and upload flow remain.

Definition of Done:

- Astra can prepare metadata, but final publish remains app/user controlled.

Dependencies:

- Phase 12.

Rollback:

- Use current publish form.

## 31. Recommended Implementation Sequence

Recommended order:

1. Phase 0 - Baseline and audit reconciliation.
2. Phase 1 - Existing tool/service boundary inventory.
3. Phase 2 - Tool layer skeleton and capability discovery.
4. Phase 3 - Project context normalization.
5. Phase 4 - Technical analysis package.
6. Phase 5A - Research Tool Layer, Source Manager, and ContentIdea.
7. Phase 5 - Content profile and transformation strategy.
8. Phase 6 - Script integration using ResearchPackage and ContentIdea.
9. Phase 7 - Visual/media plan with research references and provider capability routing.
10. Phase 9 - EditPlan v2 and editor tools.
11. Phase 10 - Preview/review/revision loop.
12. Phase 11 - Job engine alignment and Auto/Assist/Manual behavior.
13. Phase 12 - AI Director UI panel and 8-step navigation.
14. Phase 8 - Character consistency, if generated character work is a priority.
15. Phase 13 - Publish polish.

Reason for moving Character Consistency after EditPlan in the default order:

- The user priority is professional editing and Astra-directed production.
- Character consistency matters, but it becomes most valuable after VisualMediaPlan and EditPlan have a stable execution path.

## 32. Immediate Next Step After Plan Approval

Do not start implementation until this plan is reviewed.

Recommended first implementation batch after approval:

1. Add tool layer skeleton around existing MCP/app operations.
2. Add compact `ProjectContext`.
3. Add tool capability discovery so the Orchestrator can see available AI/research/media tools.
4. Add draft artifact storage for `ResearchPackage`, `SourceItem`, and `ContentIdea`.
5. Add `ContentProfile` and `TransformationStrategy` artifacts.
6. Update Astra/MCP bridge to use these tools.
7. Keep render behavior unchanged until EditPlan v2 is validated.

This batch creates the foundation for Astra to operate the app without risking the current production workflow.

## 33. Implementation Log

### 2026-09-20 - Batch 1: Astra foundation and edit-plan tool path

Implemented:

- Added `youtube_monitor.project_context` with compact `ProjectContext` and `SourcePackage` builders.
- Added `/api/projects/{project_id}/astra-context` and `/api/projects/{project_id}/source-package`.
- Added first `tool_layer` registry for Astra-facing tools.
- Exposed ProjectContext and SourcePackage through the local MCP bridge.
- Added edit-plan tools for Astra through MCP:
  - `youtube_factory_get_project_edit_plan`
  - `youtube_factory_plan_project_edit`
  - `youtube_factory_approve_project_edit_plan`
  - `youtube_factory_apply_project_edit_plan`
  - `youtube_factory_get_storyboard_required_jobs`
  - `youtube_factory_get_render_readiness`
- Added `sound_cues` as a planned scene-level edit artifact, stored on timeline segments alongside overlays, required assets, transitions and effects.
- Added FFmpeg SFX mixing for scene `sound_cues` when a cue has a real `asset_path`/`file_path`: each cue is delayed to its scene timestamp and mixed with narration/music.
- Extended `ProjectContext` so Astra can see edit-plan status, overlay counts, sound cue counts, required asset counts, edited segment counts and render readiness without loading heavy media.
- Kept render readiness based on real files only. Edit plan still does not block render.

Verified:

- `python -X utf8 -m py_compile _HE_THONG\app\youtube_monitor\project_context.py _HE_THONG\app\youtube_monitor\database.py _HE_THONG\app\youtube_monitor\main.py _HE_THONG\app\youtube_monitor\tool_layer\registry.py _HE_THONG\app\youtube_monitor\ai_desktop_mcp.py`
- `python -X utf8 -m pytest _HE_THONG\app\tests\test_project_context.py _HE_THONG\app\tests\test_ai_desktop_mcp.py _HE_THONG\app\tests\test_main.py _HE_THONG\app\tests\test_graphic_overlays.py _HE_THONG\app\tests\test_edit_plan_applied.py -q`
- Result: `50 passed in 17.75s`

Remaining for professional edit execution:

1. Mix real SFX files into `ffmpeg_renderer` from `sound_cues` after assets are selected or generated.
2. Add a dedicated SFX asset picker/provider or bundled safe local SFX presets.
3. Add Astra revision loop for edit plan: inspect context, revise scene plans, apply, then request render readiness.
4. Add preview endpoint for full edit plan or per-scene before final render without turning Storyboard into a manual timeline editor.

### 2026-09-20 - Planning update: AI Orchestrator + Research workflow

Updated plan only:

- Added the explicit architecture `User -> AI Orchestrator -> Video App Tool Layer -> Research/AI/Creative/Production Tools -> Project/Assets/Timeline/Render`.
- Clarified that Astra is the default primary Orchestrator, ChatGPT app is a secondary/specialist model, Claude is the configured fallback Orchestrator and optional specialist text/review tool, and GPT/Gemini/Flow/Meta/provider integrations are specialist tools.
- Updated workflow from 7 steps to 8 steps by adding Step 3: Research & Ý tưởng.
- Added `ResearchPackage`, `SourceItem`, Source Manager, and `ContentIdea` targets.
- Added content-type-based research policy for comic/image story, history/documentary, news/article, product, survival/outdoor, talking-head/explainer.
- Added tool categories for Research, AI Text/Vision, Creative Media, Render, Publish, and capability discovery states.
- Added acceptance scenarios for article, existing video, product link, comic, history, specialist AI tool, and Flow/video generation tool.
- Updated implementation phases and recommended sequence so research/source manager happens before script/storyboard/media planning.



### 2026-09-22 - Batch 2: Runtime readiness gate and per-step audit trail

Implements step 1 of the correction sequence ("Provider readiness gate") plus the
run-report requirement, and closes three rows of the error table: AI routing,
fallback labelling, and the missing audit trail.

Implemented:

- Added `youtube_monitor.orchestrator_runtime`, which owns:
  - the product-to-runtime mapping (`astra -> antigravity`, `claude -> claude_code_cli`,
    `chatgpt_app -> codex_cli`), previously buried in `main.py`;
  - real execution readiness per text runtime: `openai_gpt` and `anthropic_claude`
    only when the API key exists, the three CLIs only when installed **and** logged in,
    `chatgpt_app_mcp`/`claude_chat_mcp` only when the tunnel has actually called MCP
    recently. A configured tunnel id alone is never readiness;
  - a recorded usage limit outranking a green sign-in, with `resets_at`;
  - `writer_order()`, which is the plan's writer preference
    (`openai_gpt -> antigravity -> claude_code_cli -> codex_cli`) filtered by readiness;
  - `report_markdown()` / `report_summary()` producing the audit table the plan requires.
- `_call_orchestrator_json` now measures readiness before routing: runnable runtimes are
  attempted first, blocked ones last (a stale probe must not become an outage), and every
  attempt is recorded. When everything fails, the error names the missing sign-in instead
  of "Không có AI được phép thực hiện công đoạn storyboard".
- Added `orchestrator_steps` table and `record_orchestrator_step` / `list_orchestrator_steps`:
  one row per AI step with runtime, why, input, output, status, fallback flag and attempts.
- Edit plan and scene edit-beat planning now carry `planned_by` / `is_fallback`. A template
  plan is recorded as a `fallback` step and labelled in the UI as **not** AI output.
- New endpoints: `GET /api/orchestrator/runtimes` (the gate) and
  `GET /api/projects/{id}/orchestrator-report` (steps + summary + markdown table).
- New MCP tools so Astra can gate itself: `youtube_factory_get_ai_runtimes` and
  `youtube_factory_get_orchestrator_report`.
- UI: a "AI nào chạy được ngay bây giờ" table in the Orchestrator panel, an "AI nào đã làm
  bước nào" audit table in the project log panel, and a red banner on a fallback edit plan.

Verified:

- `python -X utf8 -m pytest tests/test_orchestrator_runtime.py -q` → 18 passed.
- `python -X utf8 -m pytest tests -q` → 1175 passed, 9 skipped, 6 failed.
- The 6 failures are pre-existing and unrelated to this batch (stale expectations from
  earlier work): MCP chat-agent endpoint rename, auto-cover now limited to reup,
  `agent_pipeline.start(external_agent=...)`, `claude_chat` added to `AGENT_IDS`,
  renderer fill/pad, and the `?v=` cache-busting query on the static script tags.

Still open before a valid end-to-end run:

1. Route the script rewrite through `writer_order()` so step 2 of the sequence uses the
   gate instead of its own provider argument.
2. Block or clearly mark the final render when `required_assets` have no generated asset.
3. Richer motion graphics and the SFX quality pass.
4. Record media generation, apply, render and QC as orchestrator steps too, so the report
   covers the whole run and not only the text-AI decisions.
