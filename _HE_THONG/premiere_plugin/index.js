/* global document, console, setTimeout */

const { entrypoints } = require("uxp");
const { localFileSystem, domains } = require("uxp").storage;
const app = require("premierepro");

let selectedPackage = null;
let mounted = false;
let running = false;

function $(id) {
  return document.getElementById(id);
}

function setStatus(message, tone = "info") {
  const node = $("status");
  if (!node) return;
  node.textContent = message;
  node.className = `status ${tone}`;
}

function setBusy(value) {
  running = value;
  const button = $("createDraft");
  if (button) {
    button.disabled = value || !selectedPackage;
    button.textContent = value ? "Đang dựng trong Premiere..." : "Tạo bản dựng tự động";
  }
  const choose = $("choosePackage");
  if (choose) choose.disabled = value;
}

function normalizePath(value) {
  return String(value || "").replace(/\\/g, "/").toLowerCase();
}

function relativeParts(relativePath) {
  return String(relativePath || "")
    .replace(/\\/g, "/")
    .split("/")
    .filter(Boolean);
}

async function findEntry(folder, relativePath) {
  let current = folder;
  for (const part of relativeParts(relativePath)) {
    if (!current || !current.isFolder) return null;
    const entries = await current.getEntries();
    current = entries.find((entry) => entry.name === part);
    if (!current) return null;
  }
  return current && current.isFile ? current : null;
}

async function readPackageFolder(folder) {
  const manifestEntry = await findEntry(folder, "premiere_manifest.json");
  if (!manifestEntry) {
    throw new Error("Không tìm thấy premiere_manifest.json trong thư mục đã chọn.");
  }
  const raw = await manifestEntry.read();
  const manifest = JSON.parse(String(raw));
  if (!manifest || !Array.isArray(manifest.segments)) {
    throw new Error("Manifest không có danh sách segments hợp lệ.");
  }

  const resolvedSegments = [];
  for (const segment of manifest.segments) {
    const audioEntry = segment.audio_file ? await findEntry(folder, segment.audio_file) : null;
    const visualEntry = segment.visual_file ? await findEntry(folder, segment.visual_file) : null;
    resolvedSegments.push({
      manifest: segment,
      audioEntry,
      visualEntry,
    });
  }

  let sourceEntry = null;
  if (manifest.source_video && manifest.source_video.relative_path) {
    sourceEntry = await findEntry(folder, manifest.source_video.relative_path);
  }

  return { folder, manifest, manifestEntry, resolvedSegments, sourceEntry };
}

function showPackageSummary(packageData) {
  const manifest = packageData.manifest;
  const segments = packageData.resolvedSegments;
  const audioCount = segments.filter((item) => item.audioEntry).length;
  const visualCount = segments.filter((item) => item.visualEntry).length;
  const missing = segments.length - Math.min(audioCount, visualCount);
  $("summaryCard").hidden = false;
  $("summaryText").innerHTML = `
    <div>${escapeHtml(manifest.project_title || manifest.sequence_name || "YouTube AI Factory")}</div>
    <div class="summary">
      <div class="metric"><span class="eyebrow">SEGMENTS</span><strong>${segments.length}</strong></div>
      <div class="metric"><span class="eyebrow">THỜI LƯỢNG</span><strong>${Number(manifest.timeline?.total_duration_seconds || 0)}s</strong></div>
      <div class="metric"><span class="eyebrow">AUDIO</span><strong>${audioCount}/${segments.length}</strong></div>
      <div class="metric"><span class="eyebrow">VISUAL</span><strong>${visualCount}/${segments.length}</strong></div>
    </div>
    ${missing ? `<p class="note">Có segment thiếu media. Plugin vẫn dựng phần có đủ file và thêm marker để bạn bổ sung.</p>` : ""}
  `;
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function choosePackage() {
  if (running) return;
  try {
    setStatus("Chọn thư mục chứa premiere_manifest.json...");
    const folder = await localFileSystem.getFolder({ initialDomain: domains.userDownloads });
    if (!folder) {
      setStatus("Đã huỷ chọn thư mục.");
      return;
    }
    const packageData = await readPackageFolder(folder);
    selectedPackage = packageData;
    $("packagePath").textContent = folder.nativePath;
    $("createDraft").disabled = false;
    showPackageSummary(packageData);
    setStatus(`Đã nạp manifest: ${packageData.manifest.segments.length} segment.`, "success");
  } catch (error) {
    console.error(error);
    selectedPackage = null;
    $("createDraft").disabled = true;
    setStatus(`Không đọc được gói Premiere: ${error.message || error}`, "error");
  }
}

async function collectProjectItems(folderItem) {
  const result = [];
  const items = await folderItem.getItems();
  for (const item of items) {
    result.push(item);
    if (typeof item.getItems === "function") {
      try {
        result.push(...await collectProjectItems(item));
      } catch (error) {
        console.debug("Bỏ qua bin không đọc được", error);
      }
    }
  }
  return result;
}

async function resolveImportedItem(allItems, entry) {
  if (!entry) return null;
  const expectedPath = normalizePath(entry.nativePath);
  const expectedName = entry.name;
  for (const item of allItems) {
    if (item.name !== expectedName && !expectedPath.endsWith(`/${normalizePath(item.name)}`)) continue;
    if (typeof item.getMediaFilePath === "function") {
      try {
        const mediaPath = await item.getMediaFilePath();
        if (normalizePath(mediaPath) === expectedPath) return item;
      } catch (error) {
        console.debug("Không đọc được media path", error);
      }
    }
  }
  return allItems.find((item) => item.name === expectedName) || null;
}

function executeAction(project, label, createAction) {
  project.lockedAccess(() => {
    project.executeTransaction((compoundAction) => {
      const action = createAction();
      if (action) compoundAction.addAction(action);
    }, label);
  });
}

async function getTrackItemAt(sequence, mediaType, trackIndex, startSeconds, projectItem) {
  const track = mediaType === "video"
    ? await sequence.getVideoTrack(trackIndex)
    : await sequence.getAudioTrack(trackIndex);
  if (!track) return null;
  const clips = track.getTrackItems(app.Constants.TrackItemType.CLIP, false) || [];
  const expectedId = typeof projectItem.getId === "function" ? projectItem.getId() : "";
  for (const clip of clips) {
    try {
      const start = await clip.getStartTime();
      const clipProjectItem = await clip.getProjectItem();
      const clipId = typeof clipProjectItem.getId === "function" ? clipProjectItem.getId() : "";
      if (Math.abs(Number(start.seconds) - Number(startSeconds)) < 0.08 && (!expectedId || clipId === expectedId)) {
        return clip;
      }
    } catch (error) {
      console.debug("Không đọc được track item", error);
    }
  }
  return null;
}

async function trimClip(project, sequence, mediaType, trackIndex, startSeconds, endSeconds, projectItem) {
  try {
    const clip = await getTrackItemAt(sequence, mediaType, trackIndex, startSeconds, projectItem);
    if (!clip) return false;
    const currentEnd = await clip.getEndTime();
    if (Number(currentEnd.seconds) <= Number(endSeconds) + 0.02) return true;
    executeAction(project, `AI Factory · Cắt ${mediaType} segment`, () => (
      clip.createSetEndAction(app.TickTime.createWithSeconds(Number(endSeconds)))
    ));
    return true;
  } catch (error) {
    console.debug("Không cắt được clip", error);
    return false;
  }
}

async function addSegmentMarker(project, markers, segment) {
  const start = Number(segment.start_seconds || 0);
  const duration = Math.max(0.1, Number(segment.duration_seconds || 1));
  try {
    executeAction(project, `AI Factory · Marker ${segment.segment_index}`, () => (
      markers.createAddMarkerAction(
        `AI ${String(segment.segment_index).padStart(3, "0")} · ${segment.section || "main"}`,
        "Comment",
        app.TickTime.createWithSeconds(start),
        app.TickTime.createWithSeconds(duration),
        String(segment.voice_text || segment.visual_prompt || "").slice(0, 180),
      )
    ));
  } catch (error) {
    console.debug("Không thêm được marker", error);
  }
}

async function createDraft() {
  if (!selectedPackage || running) return;
  setBusy(true);
  try {
    const { manifest, resolvedSegments, sourceEntry } = selectedPackage;
    const project = await app.Project.getActiveProject();
    if (!project) throw new Error("Chưa mở project Premiere nào.");
    const root = await project.getRootItem();

    const entries = [];
    for (const segment of resolvedSegments) {
      if (segment.audioEntry) entries.push(segment.audioEntry);
      if (segment.visualEntry) entries.push(segment.visualEntry);
    }
    if (sourceEntry) entries.push(sourceEntry);
    const uniqueEntries = Array.from(new Map(entries.map((entry) => [entry.nativePath, entry])).values());
    const paths = uniqueEntries.map((entry) => entry.nativePath);
    if (!paths.length) throw new Error("Gói không có audio/video/ảnh local để import.");

    setStatus(`Đang import ${paths.length} media vào Premiere...`);
    await project.importFiles(paths, true, root, false);
    await new Promise((resolve) => setTimeout(resolve, 700));
    const allItems = await collectProjectItems(root);
    const itemByPath = new Map();
    for (const entry of uniqueEntries) {
      const item = await resolveImportedItem(allItems, entry);
      if (item) itemByPath.set(normalizePath(entry.nativePath), item);
    }

    const resolved = resolvedSegments.map((segment) => ({
      ...segment,
      audioItem: segment.audioEntry ? itemByPath.get(normalizePath(segment.audioEntry.nativePath)) : null,
      visualItem: segment.visualEntry ? itemByPath.get(normalizePath(segment.visualEntry.nativePath)) : null,
    }));
    const firstItem = resolved.find((segment) => segment.visualItem)?.visualItem
      || resolved.find((segment) => segment.audioItem)?.audioItem;
    if (!firstItem) throw new Error("Premiere không nhận được media sau khi import.");

    let sequence = null;
    let createdNewSequence = false;
    if ($("sequenceMode").value === "active") {
      try {
        sequence = await project.getActiveSequence();
      } catch (error) {
        console.debug("Không có active sequence", error);
      }
    }
    if (!sequence) {
      const firstClipItem = typeof app.ClipProjectItem?.cast === "function"
        ? app.ClipProjectItem.cast(firstItem)
        : firstItem;
      sequence = await project.createSequenceFromMedia(
        manifest.sequence_name || manifest.project_title || "YouTube AI Factory Draft",
        [firstClipItem],
        root,
      );
      createdNewSequence = true;
      await project.setActiveSequence(sequence);
    }
    if (!sequence) throw new Error("Không tạo hoặc lấy được sequence Premiere.");

    const editor = app.SequenceEditor.getEditor(sequence);
    let markers = null;
    try {
      markers = await app.Markers.getMarkers(sequence);
    } catch (error) {
      console.debug("Premiere không hỗ trợ markers trong phiên bản hiện tại", error);
    }
    let preloadedConsumed = false;
    let placed = 0;
    let missing = 0;

    for (const segment of resolved) {
      const start = Number(segment.manifest.start_seconds || 0);
      const end = Number(segment.manifest.end_seconds || start + Number(segment.manifest.duration_seconds || 1));
      if (segment.visualItem) {
        const isPreloaded = createdNewSequence && !preloadedConsumed && segment.visualItem === firstItem && start === 0;
        if (isPreloaded) {
          preloadedConsumed = true;
        } else {
          executeAction(project, `AI Factory · Visual ${segment.manifest.segment_index}`, () => (
            editor.createOverwriteItemAction(
              segment.visualItem,
              app.TickTime.createWithSeconds(start),
              0,
              0,
            )
          ));
        }
        await new Promise((resolve) => setTimeout(resolve, 80));
        await trimClip(project, sequence, "video", 0, start, end, segment.visualItem);
        placed += 1;
      } else {
        missing += 1;
      }

      if (segment.audioItem) {
        executeAction(project, `AI Factory · Voiceover ${segment.manifest.segment_index}`, () => (
          editor.createOverwriteItemAction(
            segment.audioItem,
            app.TickTime.createWithSeconds(start),
            0,
            1,
          )
        ));
        await new Promise((resolve) => setTimeout(resolve, 80));
        await trimClip(project, sequence, "audio", 1, start, end, segment.audioItem);
      } else {
        missing += 1;
      }
      if (markers) await addSegmentMarker(project, markers, segment.manifest);
    }

    await project.save();
    setStatus(
      `Đã tạo bản dựng: ${sequence.name}\n` +
      `Đã đặt ${placed} visual segment, ${resolved.filter((item) => item.audioItem).length} voiceover segment.` +
      (missing ? `\nThiếu ${missing} media — xem marker và bổ sung thủ công.` : ""),
      missing ? "info" : "success",
    );
  } catch (error) {
    console.error(error);
    setStatus(`Dựng tự động thất bại: ${error.message || error}`, "error");
  } finally {
    setBusy(false);
  }
}

function mount() {
  if (mounted) return;
  mounted = true;
  $("choosePackage").addEventListener("click", choosePackage);
  $("createDraft").addEventListener("click", createDraft);
}

entrypoints.setup({
  panels: {
    mainPanel: {
      show() {
        mount();
      },
    },
  },
});
