class LocalAssetStore {
  constructor() {
    this.dbName = "copyidea.editorAssets";
    this.storeName = "assets";
    this.dbPromise = null;
  }

  open() {
    if (this.dbPromise) {
      return this.dbPromise;
    }

    this.dbPromise = new Promise((resolve, reject) => {
      const request = window.indexedDB.open(this.dbName, 1);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(this.storeName)) {
          db.createObjectStore(this.storeName, { keyPath: "id" });
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });

    return this.dbPromise;
  }

  async putAsset(record) {
    const db = await this.open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(this.storeName, "readwrite");
      tx.objectStore(this.storeName).put(record);
      tx.oncomplete = () => resolve(record);
      tx.onerror = () => reject(tx.error);
    });
  }

  async getAsset(id) {
    const db = await this.open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(this.storeName, "readonly");
      const request = tx.objectStore(this.storeName).get(id);
      request.onsuccess = () => resolve(request.result || null);
      request.onerror = () => reject(request.error);
    });
  }

  async deleteAsset(id) {
    const db = await this.open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(this.storeName, "readwrite");
      tx.objectStore(this.storeName).delete(id);
      tx.oncomplete = () => resolve(true);
      tx.onerror = () => reject(tx.error);
    });
  }
}

class TimelineEditorAppV2 {
  constructor(root) {
    this.root = root;
    this.projectsKey = "copyidea.projects";
    this.activeProjectKey = "copyidea.activeProjectId";
    this.legacyPackageKey = "copyidea.contentPackage";
    this.assetStore = new LocalAssetStore();
    this.assetUrls = new Map();
    this.previewAssetId = null;
    this.previewRequestId = 0;
    this.durationSeconds = 60;
    this.playheadPercent = 18;
    this.selectedClipId = null;
    this.selectedAssetId = null;
    this.isPlaying = false;
    this.playTimer = null;
    this.undoStack = [];
    this.redoStack = [];
    this.dragClipState = null;

    const context = this.loadProjectContext();
    this.projectRecord = context.projectRecord;
    this.package = context.package;
    this.editorState = this.normalizeEditorState(this.projectRecord?.editorState);
    this.currentOutput = this.editorState.currentOutput;
    this.currentPreview = this.editorState.currentPreview;
    this.selectedAssetId = this.editorState.selectedAssetId || null;
    this.clips = this.editorState.clips.length
      ? this.clone(this.editorState.clips)
      : this.buildClipsFromPackage(this.package);

    this.cacheElements();
    this.bindEvents();
    this.render(true);
    window.addEventListener("beforeunload", () => this.disposeAssetUrls());
  }

  clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  createDefaultEditorState() {
    return {
      currentOutput: "Long 9:16",
      currentPreview: "Long 9:16",
      selectedAssetId: null,
      assets: [],
      clips: [],
    };
  }

  createFallbackPackage() {
    return {
      version: 1,
      projectTitle: "English Progress Stories",
      totalDurationSeconds: 60,
      totalLines: 2,
      sessions: [
        {
          id: "session-1",
          title: "Why progress feels invisible",
          start: 0,
          end: 60,
          durationSeconds: 60,
          lines: [
            { id: "line-1", speaker: "A", text: "Why is my English still not good enough", start: 0, end: 12 },
            { id: "line-2", speaker: "B", text: "Even if you do not see it yet.", start: 12, end: 24 }
          ]
        }
      ]
    };
  }

  normalizeOutputName(name) {
    if (name === "Short") {
      return "Shorts";
    }
    return name || "Long 9:16";
  }

  normalizeEditorState(editorState) {
    const fallback = this.createDefaultEditorState();
    return {
      currentOutput: this.normalizeOutputName(editorState?.currentOutput || fallback.currentOutput),
      currentPreview: this.normalizeOutputName(editorState?.currentPreview || editorState?.currentOutput || fallback.currentPreview),
      selectedAssetId: editorState?.selectedAssetId || fallback.selectedAssetId,
      assets: Array.isArray(editorState?.assets)
        ? editorState.assets.map((asset) => ({
            id: asset.id,
            name: asset.name || "Untitled asset",
            kind: asset.kind || "binary",
            type: asset.type || "application/octet-stream",
            size: Number(asset.size || 0),
            outputs: Array.isArray(asset.outputs) && asset.outputs.length
              ? asset.outputs.map((output) => this.normalizeOutputName(output))
              : [fallback.currentOutput],
            addedAt: asset.addedAt || new Date().toISOString(),
          }))
        : fallback.assets,
      clips: Array.isArray(editorState?.clips) ? this.clone(editorState.clips) : fallback.clips,
    };
  }

  getStoredProjects() {
    try {
      const raw = window.localStorage.getItem(this.projectsKey);
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      return [];
    }
  }

  setStoredProjects(projects) {
    window.localStorage.setItem(this.projectsKey, JSON.stringify(projects));
  }

  setActiveProjectId(projectId) {
    window.localStorage.setItem(this.activeProjectKey, projectId);
  }

  loadProjectContext() {
    const projects = this.getStoredProjects();
    const activeProjectId = window.localStorage.getItem(this.activeProjectKey);
    const activeRecord = projects.find((project) => project.id === activeProjectId) || projects[0] || null;

    if (activeRecord) {
      return {
        projectRecord: activeRecord,
        package: activeRecord.package || this.createFallbackPackage(),
      };
    }

    try {
      const legacyRaw = window.localStorage.getItem(this.legacyPackageKey);
      const legacyPackage = legacyRaw ? JSON.parse(legacyRaw) : this.createFallbackPackage();
      return {
        projectRecord: {
          id: `project-${Date.now()}`,
          title: legacyPackage.projectTitle || "Imported legacy project",
          updatedAt: new Date().toISOString(),
          contentState: null,
          package: legacyPackage,
          editorState: this.createDefaultEditorState(),
        },
        package: legacyPackage,
      };
    } catch (error) {
      return {
        projectRecord: {
          id: `project-${Date.now()}`,
          title: "Imported legacy project",
          updatedAt: new Date().toISOString(),
          contentState: null,
          package: this.createFallbackPackage(),
          editorState: this.createDefaultEditorState(),
        },
        package: this.createFallbackPackage(),
      };
    }
  }

  cacheElements() {
    this.trackBoardEl = this.root.querySelector("#track-board");
    this.playheadEl = this.root.querySelector("#playhead");
    this.previewTimeEl = this.root.querySelector("#preview-time");
    this.screenTitleEl = this.root.querySelector("#screen-title");
    this.screenSubtitleEl = this.root.querySelector("#screen-subtitle");
    this.screenMediaEl = this.root.querySelector("#screen-media");
    this.assetListEl = this.root.querySelector("#asset-list");
    this.assetDropzoneEl = this.root.querySelector("#asset-dropzone");
    this.assetInputEl = this.root.querySelector("#asset-input");
    this.importAssetsButton = this.root.querySelector("#import-assets-button");
    this.projectStatusEl = this.root.querySelector("#project-status");
    this.inspectorOutputEl = this.root.querySelector("#inspector-output");
    this.inspectorPlayheadEl = this.root.querySelector("#inspector-playhead");
    this.inspectorSelectionEl = this.root.querySelector("#inspector-selection");
    this.trackRows = {
      video: this.root.querySelector(".track-row[data-track='video']"),
      audio: this.root.querySelector(".track-row[data-track='audio']"),
      caption: this.root.querySelector(".track-row[data-track='caption']")
    };
    this.toolbarButtons = new Map(
      [...this.root.querySelectorAll("[data-action]")].map((button) => [button.dataset.action, button])
    );
    this.outputButtons = [...this.root.querySelectorAll("[data-output]")];
    this.previewButtons = [...this.root.querySelectorAll("[data-preview]")];
  }
  bindEvents() {
    this.toolbarButtons.forEach((button, action) => {
      button.addEventListener("click", () => this.handleAction(action));
    });

    this.outputButtons.forEach((button) => {
      button.addEventListener("click", () => this.setCurrentOutput(button.dataset.output));
    });

    this.previewButtons.forEach((button) => {
      button.addEventListener("click", () => this.setCurrentPreview(button.dataset.preview));
    });

    this.importAssetsButton.addEventListener("click", () => this.assetInputEl.click());
    this.assetDropzoneEl.addEventListener("click", () => this.assetInputEl.click());
    this.assetInputEl.addEventListener("change", (event) => {
      const files = [...(event.target.files || [])];
      event.target.value = "";
      void this.importFiles(files);
    });

    this.assetDropzoneEl.addEventListener("dragover", (event) => {
      event.preventDefault();
      this.assetDropzoneEl.classList.add("is-hover");
    });

    this.assetDropzoneEl.addEventListener("dragleave", () => {
      this.assetDropzoneEl.classList.remove("is-hover");
    });

    this.assetDropzoneEl.addEventListener("drop", (event) => {
      event.preventDefault();
      this.assetDropzoneEl.classList.remove("is-hover");
      const files = [...(event.dataTransfer?.files || [])];
      void this.importFiles(files);
    });

    this.trackBoardEl.addEventListener("click", (event) => {
      if (event.target.classList.contains("clip")) {
        return;
      }
      const rect = this.trackBoardEl.getBoundingClientRect();
      const relative = ((event.clientX - rect.left) / rect.width) * 100;
      this.playheadPercent = this.clamp(relative, 0, 100);
      this.renderPlayhead();
      this.renderPreview();
      this.renderInspector();
    });

    window.addEventListener("keydown", (event) => this.handleKeydown(event));
    window.addEventListener("pointermove", (event) => this.onClipPointerMove(event));
    window.addEventListener("pointerup", () => this.stopClipDrag());
  }

  derivePackageAssets() {
    return [
      {
        id: "built-in-final-audio",
        name: "final_audio.wav",
        kind: "audio",
        type: "audio/wav",
        size: 0,
        outputs: ["Long 16:9", "Long 9:16", "Shorts"],
        addedAt: this.projectRecord?.updatedAt || new Date().toISOString(),
        builtIn: true,
        meta: `${this.package.totalLines || 0} dialogue rows from Create Workspace`
      },
      {
        id: "built-in-speaker-timeline",
        name: "speaker_timeline.json",
        kind: "caption",
        type: "application/json",
        size: 0,
        outputs: ["Long 16:9", "Long 9:16", "Shorts"],
        addedAt: this.projectRecord?.updatedAt || new Date().toISOString(),
        builtIn: true,
        meta: `${this.package.sessions?.length || 0} sessions with speaker timing`
      },
      {
        id: "built-in-package",
        name: `${this.package.projectTitle || "project"}.json`,
        kind: "package",
        type: "application/json",
        size: 0,
        outputs: ["Long 16:9", "Long 9:16", "Shorts"],
        addedAt: this.projectRecord?.updatedAt || new Date().toISOString(),
        builtIn: true,
        meta: "content package from Create Workspace"
      }
    ];
  }

  getAllAssets() {
    return [...this.derivePackageAssets(), ...this.editorState.assets];
  }

  getAssetById(assetId) {
    return this.getAllAssets().find((asset) => asset.id === assetId) || null;
  }

  matchesOutput(outputs, targetOutput) {
    const normalized = this.normalizeOutputName(targetOutput);
    return (outputs || []).map((output) => this.normalizeOutputName(output)).includes(normalized);
  }

  buildClipsFromPackage(pkg) {
    const duration = Math.max(30, pkg.totalDurationSeconds || 60);
    this.durationSeconds = duration;
    const toPercent = (seconds) => (seconds / duration) * 100;

    const clips = [
      { id: "visual-master", track: "video", label: "Visual master", start: 0, length: 100, color: "blue", assetId: null },
      { id: "audio-master", track: "audio", label: "final_audio.wav", start: 0, length: 100, color: "rose", assetId: "built-in-final-audio" }
    ];

    (pkg.sessions || []).forEach((session, index) => {
      const start = toPercent(session.start ?? 0);
      const length = Math.max(8, toPercent(session.durationSeconds || ((session.end ?? 0) - (session.start ?? 0)) || 8));
      clips.push({
        id: `caption-${index + 1}`,
        track: "caption",
        label: session.title || `Session ${index + 1}`,
        start,
        length,
        color: index % 2 === 0 ? "teal" : "orange",
        assetId: "built-in-speaker-timeline"
      });
    });

    return clips;
  }

  saveProjectState(statusText = "Editor saved") {
    const projects = this.getStoredProjects();
    const currentId = this.projectRecord?.id || this.package.projectId || `project-${Date.now()}`;
    const currentIndex = projects.findIndex((project) => project.id === currentId);
    const existingRecord = currentIndex >= 0 ? projects[currentIndex] : null;

    this.editorState = {
      currentOutput: this.currentOutput,
      currentPreview: this.currentPreview,
      selectedAssetId: this.selectedAssetId,
      assets: this.editorState.assets,
      clips: this.clone(this.clips),
    };

    const record = {
      id: currentId,
      title: this.projectRecord?.title || this.package.projectTitle || existingRecord?.title || "Untitled Project",
      updatedAt: new Date().toISOString(),
      contentState: existingRecord?.contentState || this.projectRecord?.contentState || null,
      package: existingRecord?.package || this.projectRecord?.package || this.package,
      editorState: this.editorState,
    };

    if (currentIndex >= 0) {
      projects[currentIndex] = record;
    } else {
      projects.push(record);
    }

    this.projectRecord = record;
    this.package = record.package;
    this.setStoredProjects(projects);
    this.setActiveProjectId(record.id);
    window.localStorage.setItem(this.legacyPackageKey, JSON.stringify(record.package));
    this.projectStatusEl.textContent = `${record.title} - ${statusText}`;
  }

  handleAction(action) {
    if (action === "back") {
      this.movePlayhead(-5);
    }
    if (action === "forward") {
      this.movePlayhead(5);
    }
    if (action === "play") {
      this.play();
    }
    if (action === "pause") {
      this.pause();
    }
    if (action === "cut") {
      this.cutSelectedClip();
    }
    if (action === "undo") {
      this.undo();
    }
    if (action === "redo") {
      this.redo();
    }
    if (action === "delete") {
      this.deleteSelectedClip();
    }
  }

  handleKeydown(event) {
    if (event.ctrlKey && event.key.toLowerCase() === "z") {
      event.preventDefault();
      this.undo();
      return;
    }

    if (event.ctrlKey && event.key.toLowerCase() === "y") {
      event.preventDefault();
      this.redo();
      return;
    }

    if (event.key === "Delete") {
      event.preventDefault();
      this.deleteSelectedClip();
      return;
    }

    if (event.key === " ") {
      event.preventDefault();
      this.isPlaying ? this.pause() : this.play();
      return;
    }

    if (event.key === "ArrowLeft") {
      event.preventDefault();
      this.movePlayhead(-5);
      return;
    }

    if (event.key === "ArrowRight") {
      event.preventDefault();
      this.movePlayhead(5);
      return;
    }

    if (event.key.toLowerCase() === "c") {
      event.preventDefault();
      this.cutSelectedClip();
    }
  }

  setCurrentOutput(outputName, shouldSave = true) {
    this.currentOutput = this.normalizeOutputName(outputName);
    this.syncToolbarState();
    this.renderAssets();
    this.renderInspector();
    if (shouldSave) {
      this.saveProjectState("Output target updated");
    }
  }

  setCurrentPreview(outputName, shouldSave = true) {
    this.currentPreview = this.normalizeOutputName(outputName);
    this.syncToolbarState();
    this.renderPreview(true);
    if (shouldSave) {
      this.saveProjectState("Preview target updated");
    }
  }

  syncToolbarState() {
    this.outputButtons.forEach((button) => {
      button.classList.toggle("active", this.normalizeOutputName(button.dataset.output) === this.currentOutput);
    });
    this.previewButtons.forEach((button) => {
      button.classList.toggle("active", this.normalizeOutputName(button.dataset.preview) === this.currentPreview);
    });
  }
  getSnapshot() {
    return {
      clips: this.clone(this.clips),
      playheadPercent: this.playheadPercent,
      selectedClipId: this.selectedClipId,
      selectedAssetId: this.selectedAssetId,
    };
  }

  pushUndoState() {
    this.undoStack.push(this.getSnapshot());
    if (this.undoStack.length > 40) {
      this.undoStack.shift();
    }
    this.redoStack = [];
  }

  restoreSnapshot(snapshot) {
    this.clips = this.clone(snapshot.clips);
    this.playheadPercent = snapshot.playheadPercent;
    this.selectedClipId = snapshot.selectedClipId;
    this.selectedAssetId = snapshot.selectedAssetId;
    this.render(true);
  }

  undo() {
    if (!this.undoStack.length) {
      return;
    }
    this.redoStack.push(this.getSnapshot());
    this.restoreSnapshot(this.undoStack.pop());
    this.saveProjectState("Undo applied");
  }

  redo() {
    if (!this.redoStack.length) {
      return;
    }
    this.undoStack.push(this.getSnapshot());
    this.restoreSnapshot(this.redoStack.pop());
    this.saveProjectState("Redo applied");
  }

  play() {
    if (this.isPlaying) {
      return;
    }
    this.isPlaying = true;
    this.updatePlaybackButtons();
    this.playTimer = window.setInterval(() => {
      this.playheadPercent += 0.6;
      if (this.playheadPercent >= 100) {
        this.playheadPercent = 100;
        this.pause();
      }
      this.renderPlayhead();
      this.renderPreview();
      this.renderInspector();
    }, 180);
  }

  pause() {
    this.isPlaying = false;
    if (this.playTimer) {
      window.clearInterval(this.playTimer);
      this.playTimer = null;
    }
    this.updatePlaybackButtons();
    this.renderPlayhead();
  }

  movePlayhead(deltaPercent) {
    this.playheadPercent = this.clamp(this.playheadPercent + deltaPercent, 0, 100);
    this.renderPlayhead();
    this.renderPreview();
    this.renderInspector();
  }

  selectClip(clipId) {
    this.selectedClipId = clipId;
    const selectedClip = this.clips.find((clip) => clip.id === clipId);
    if (selectedClip?.assetId) {
      this.selectedAssetId = selectedClip.assetId;
    }
    this.renderClips();
    this.renderInspector();
    this.renderPreview(true);
  }

  startClipDrag(event, clipId) {
    event.preventDefault();
    const clip = this.clips.find((item) => item.id === clipId);
    if (!clip) {
      return;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    const edge = 10;
    let mode = "move";
    if (event.clientX - rect.left <= edge) {
      mode = "resize-left";
    } else if (rect.right - event.clientX <= edge) {
      mode = "resize-right";
    }
    this.pushUndoState();
    this.dragClipState = {
      clipId,
      mode,
      startX: event.clientX,
      start: clip.start,
      length: clip.length
    };
    this.selectClip(clipId);
  }

  onClipPointerMove(event) {
    if (!this.dragClipState) {
      return;
    }
    const boardRect = this.trackBoardEl.getBoundingClientRect();
    const deltaPercent = ((event.clientX - this.dragClipState.startX) / boardRect.width) * 100;
    const clip = this.clips.find((item) => item.id === this.dragClipState.clipId);
    if (!clip) {
      return;
    }

    if (this.dragClipState.mode === "move") {
      clip.start = this.clamp(this.dragClipState.start + deltaPercent, 0, 100 - clip.length);
    }

    if (this.dragClipState.mode === "resize-left") {
      const nextStart = this.clamp(this.dragClipState.start + deltaPercent, 0, this.dragClipState.start + this.dragClipState.length - 6);
      const nextLength = this.dragClipState.length + (this.dragClipState.start - nextStart);
      clip.start = nextStart;
      clip.length = Math.max(6, nextLength);
    }

    if (this.dragClipState.mode === "resize-right") {
      clip.length = this.clamp(this.dragClipState.length + deltaPercent, 6, 100 - clip.start);
    }

    this.renderClips();
    this.renderInspector();
  }

  stopClipDrag() {
    if (!this.dragClipState) {
      return;
    }
    this.dragClipState = null;
    this.saveProjectState("Timeline updated");
  }

  cutSelectedClip() {
    const clip = this.clips.find((item) => item.id === this.selectedClipId);
    if (!clip) {
      return;
    }

    const cutPoint = this.playheadPercent;
    const minLength = 6;
    if (cutPoint <= clip.start + minLength || cutPoint >= clip.start + clip.length - minLength) {
      return;
    }

    this.pushUndoState();

    const firstLength = cutPoint - clip.start;
    const secondLength = clip.length - firstLength;
    const baseId = `clip-${Date.now()}`;
    const newClips = [
      { ...clip, id: `${baseId}-a`, length: firstLength, label: `${clip.label} A` },
      { ...clip, id: `${baseId}-b`, start: cutPoint, length: secondLength, label: `${clip.label} B` }
    ];

    this.clips = this.clips.flatMap((item) => item.id === clip.id ? newClips : [item]);
    this.selectedClipId = `${baseId}-a`;
    this.render();
    this.saveProjectState("Clip cut");
  }

  deleteSelectedClip() {
    if (!this.selectedClipId) {
      return;
    }
    this.pushUndoState();
    this.clips = this.clips.filter((clip) => clip.id !== this.selectedClipId);
    this.selectedClipId = null;
    this.render();
    this.saveProjectState("Clip deleted");
  }

  formatSeconds(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = String(seconds % 60).padStart(2, "0");
    return `${String(mins).padStart(2, "0")}:${secs}`;
  }

  formatTimeFromPercent(percent) {
    const seconds = Math.round((percent / 100) * this.durationSeconds);
    return this.formatSeconds(seconds);
  }

  formatBytes(size) {
    if (!size) {
      return "package";
    }
    if (size < 1024) {
      return `${size} B`;
    }
    if (size < 1024 * 1024) {
      return `${(size / 1024).toFixed(1)} KB`;
    }
    return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  }

  updatePlaybackButtons() {
    const playButton = this.toolbarButtons.get("play");
    const pauseButton = this.toolbarButtons.get("pause");
    if (!playButton || !pauseButton) {
      return;
    }
    playButton.classList.toggle("active", this.isPlaying);
    pauseButton.classList.toggle("active", !this.isPlaying);
  }

  renderPlayhead() {
    this.playheadEl.style.left = `${this.playheadPercent}%`;
    const current = this.formatTimeFromPercent(this.playheadPercent);
    this.previewTimeEl.textContent = `${current} / ${this.formatSeconds(this.durationSeconds)}`;
    this.inspectorPlayheadEl.textContent = current;
  }

  findActiveTimeline() {
    const currentSecond = Math.round((this.playheadPercent / 100) * this.durationSeconds);
    const sessions = this.package.sessions || [];
    const activeSession = sessions.find((session) => currentSecond >= (session.start ?? 0) && currentSecond < (session.end ?? this.durationSeconds))
      || sessions.find((session) => currentSecond < (session.end ?? this.durationSeconds))
      || sessions[sessions.length - 1]
      || null;
    const activeLine = activeSession?.lines?.find((line) => currentSecond >= (line.start ?? 0) && currentSecond < (line.end ?? this.durationSeconds))
      || activeSession?.lines?.[0]
      || null;
    return { activeSession, activeLine };
  }

  getPreviewAsset() {
    const selectedClip = this.clips.find((clip) => clip.id === this.selectedClipId);
    if (selectedClip?.assetId) {
      return this.getAssetById(selectedClip.assetId);
    }

    if (this.selectedAssetId) {
      return this.getAssetById(this.selectedAssetId);
    }

    return this.editorState.assets.find((asset) => this.matchesOutput(asset.outputs, this.currentPreview) && ["image", "gif", "video"].includes(asset.kind))
      || this.editorState.assets.find((asset) => this.matchesOutput(asset.outputs, this.currentPreview))
      || this.derivePackageAssets()[0]
      || null;
  }

  async getAssetObjectUrl(asset) {
    if (!asset || asset.builtIn) {
      return null;
    }
    if (this.assetUrls.has(asset.id)) {
      return this.assetUrls.get(asset.id);
    }
    const storedAsset = await this.assetStore.getAsset(asset.id);
    if (!storedAsset?.blob) {
      return null;
    }
    const url = URL.createObjectURL(storedAsset.blob);
    this.assetUrls.set(asset.id, url);
    return url;
  }

  disposeAssetUrls() {
    this.assetUrls.forEach((url) => URL.revokeObjectURL(url));
    this.assetUrls.clear();
  }

  inferAssetKind(file) {
    const name = file.name.toLowerCase();
    if (name.endsWith(".gif")) {
      return "gif";
    }
    if (file.type.startsWith("image/")) {
      return "image";
    }
    if (file.type.startsWith("video/")) {
      return "video";
    }
    if (file.type.startsWith("audio/")) {
      return "audio";
    }
    if (name.endsWith(".srt") || name.endsWith(".vtt") || name.endsWith(".txt")) {
      return "caption";
    }
    if (name.endsWith(".json")) {
      return "package";
    }
    return "binary";
  }
  async importFiles(files) {
    if (!files.length) {
      return;
    }

    for (const file of files) {
      const assetId = `asset-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      await this.assetStore.putAsset({
        id: assetId,
        name: file.name,
        type: file.type,
        updatedAt: new Date().toISOString(),
        blob: file,
      });

      this.editorState.assets.unshift({
        id: assetId,
        name: file.name,
        kind: this.inferAssetKind(file),
        type: file.type || "application/octet-stream",
        size: file.size,
        outputs: [this.currentOutput],
        addedAt: new Date().toISOString(),
      });

      this.selectedAssetId = assetId;
    }

    this.render(true);
    this.saveProjectState(`${files.length} asset${files.length > 1 ? "s" : ""} imported`);
  }

  async deleteAsset(assetId) {
    const asset = this.editorState.assets.find((item) => item.id === assetId);
    if (!asset) {
      return;
    }

    this.editorState.assets = this.editorState.assets.filter((item) => item.id !== assetId);
    this.clips = this.clips.filter((clip) => clip.assetId !== assetId);
    if (this.selectedAssetId === assetId) {
      this.selectedAssetId = this.editorState.assets[0]?.id || "built-in-final-audio";
    }
    if (this.assetUrls.has(assetId)) {
      URL.revokeObjectURL(this.assetUrls.get(assetId));
      this.assetUrls.delete(assetId);
    }
    await this.assetStore.deleteAsset(assetId);
    this.render(true);
    this.saveProjectState("Asset deleted");
  }

  selectAsset(assetId) {
    this.selectedAssetId = assetId;
    this.renderAssets();
    this.renderPreview(true);
    this.renderInspector();
    this.saveProjectState("Asset selected");
  }

  addClipFromAsset(assetId) {
    const asset = this.getAssetById(assetId);
    if (!asset) {
      return;
    }

    this.pushUndoState();

    const track = asset.kind === "audio"
      ? "audio"
      : asset.kind === "caption" || asset.kind === "package"
        ? "caption"
        : "video";
    const color = asset.kind === "audio"
      ? "rose"
      : asset.kind === "video"
        ? "blue"
        : asset.kind === "gif"
          ? "orange"
          : asset.kind === "image"
            ? "teal"
            : "teal";
    const defaultLength = asset.kind === "audio"
      ? 28
      : asset.kind === "video"
        ? 24
        : asset.kind === "caption" || asset.kind === "package"
          ? 16
          : 18;
    const start = this.clamp(this.playheadPercent, 0, 100 - defaultLength);

    const clip = {
      id: `clip-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      track,
      label: asset.name,
      start,
      length: defaultLength,
      color,
      assetId: asset.id,
    };

    this.clips.push(clip);
    this.selectedClipId = clip.id;
    this.selectedAssetId = asset.id;
    this.render(true);
    this.saveProjectState("Track updated");
  }

  renderAssets() {
    const visibleAssets = this.getAllAssets().filter((asset) => this.matchesOutput(asset.outputs, this.currentOutput));
    this.assetListEl.innerHTML = "";

    visibleAssets.forEach((asset) => {
      const node = document.createElement("div");
      node.className = `asset-item${asset.id === this.selectedAssetId ? " is-selected" : ""}`;
      node.innerHTML = `
        <div class="asset-main">
          <strong>${asset.name}</strong>
          <span>${asset.meta || `${asset.kind} · ${this.formatBytes(asset.size)} · ${asset.outputs.join(", ")}`}</span>
        </div>
        <div class="asset-actions"></div>
      `;

      const actions = node.querySelector(".asset-actions");
      const addButton = document.createElement("button");
      addButton.type = "button";
      addButton.className = "tool";
      addButton.textContent = "Track";
      addButton.addEventListener("click", (event) => {
        event.stopPropagation();
        this.addClipFromAsset(asset.id);
      });
      actions.appendChild(addButton);

      if (!asset.builtIn) {
        const deleteButton = document.createElement("button");
        deleteButton.type = "button";
        deleteButton.className = "tool";
        deleteButton.textContent = "Delete";
        deleteButton.addEventListener("click", (event) => {
          event.stopPropagation();
          void this.deleteAsset(asset.id);
        });
        actions.appendChild(deleteButton);
      }

      node.addEventListener("click", () => this.selectAsset(asset.id));
      this.assetListEl.appendChild(node);
    });
  }

  renderPreview(forceMedia = false) {
    const { activeSession, activeLine } = this.findActiveTimeline();
    this.screenTitleEl.textContent = activeSession?.title || this.package.projectTitle || "Story Preview";
    this.screenSubtitleEl.textContent = activeLine?.text || "Import media, build clips, and refine the timing.";

    const nextAsset = this.getPreviewAsset();
    const nextAssetId = nextAsset?.id || null;
    if (!forceMedia && nextAssetId === this.previewAssetId) {
      return;
    }
    this.previewAssetId = nextAssetId;
    void this.mountPreviewAsset(nextAsset);
  }

  async mountPreviewAsset(asset) {
    const requestId = ++this.previewRequestId;
    this.screenMediaEl.className = "screen-media";
    this.screenMediaEl.innerHTML = "";

    if (!asset) {
      return;
    }

    if (asset.kind === "audio") {
      this.screenMediaEl.classList.add("audio-mode");
      const badge = document.createElement("div");
      badge.className = "screen-audio-badge";
      badge.textContent = asset.name;
      this.screenMediaEl.appendChild(badge);
      return;
    }

    if (asset.kind === "package" || asset.kind === "caption") {
      return;
    }

    const objectUrl = await this.getAssetObjectUrl(asset);
    if (requestId !== this.previewRequestId || !objectUrl) {
      return;
    }

    if (asset.kind === "video") {
      const video = document.createElement("video");
      video.src = objectUrl;
      video.muted = true;
      video.loop = true;
      video.autoplay = true;
      video.playsInline = true;
      this.screenMediaEl.appendChild(video);
      return;
    }

    const image = document.createElement("img");
    image.src = objectUrl;
    image.alt = asset.name;
    this.screenMediaEl.appendChild(image);
  }

  renderInspector() {
    const selected = this.clips.find((clip) => clip.id === this.selectedClipId);
    const selectedAsset = selected?.assetId ? this.getAssetById(selected.assetId) : this.getAssetById(this.selectedAssetId);
    this.inspectorOutputEl.textContent = `Target: ${this.currentOutput} | Preview: ${this.currentPreview}`;
    this.inspectorSelectionEl.textContent = selected
      ? `${selected.label} - ${selected.track} - ${selected.start.toFixed(1)}% - ${selectedAsset?.name || "no asset"}`
      : selectedAsset
        ? `Asset: ${selectedAsset.name} - ${selectedAsset.kind}`
        : "None selected";
  }

  renderClips() {
    Object.values(this.trackRows).forEach((row) => {
      row.innerHTML = "";
    });

    this.clips.forEach((clip) => {
      const node = document.createElement("button");
      node.type = "button";
      node.className = `clip ${clip.color}${clip.id === this.selectedClipId ? " is-selected" : ""}`;
      node.style.left = `${clip.start}%`;
      node.style.width = `${clip.length}%`;
      node.textContent = clip.label;
      node.addEventListener("pointerdown", (event) => this.startClipDrag(event, clip.id));
      node.addEventListener("click", (event) => {
        event.stopPropagation();
        this.selectClip(clip.id);
      });
      this.trackRows[clip.track].appendChild(node);
    });
  }

  render(forceMedia = false) {
    this.durationSeconds = Math.max(30, this.package.totalDurationSeconds || this.durationSeconds);
    this.projectStatusEl.textContent = `${this.projectRecord?.title || this.package.projectTitle || "Untitled Project"} - ready`;
    this.syncToolbarState();
    this.renderAssets();
    this.renderPreview(forceMedia);
    this.renderClips();
    this.renderPlayhead();
    this.renderInspector();
    this.updatePlaybackButtons();
  }

  clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }
}

new TimelineEditorAppV2(window.__copyIdeaWorkspaceRoot || document.getElementById("edit-workspace"));
