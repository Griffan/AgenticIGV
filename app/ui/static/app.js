const messages = document.getElementById("messages");
const messageInput = document.getElementById("messageInput");
const sendMessage = document.getElementById("sendMessage");
const svSummary = document.getElementById("svSummary");
const bamPathInput = document.getElementById("bamPath");
const fastaPathInput = document.getElementById("fastaPath");

// Set default paths for debugging/testing
if (bamPathInput && !bamPathInput.value) {
  bamPathInput.value = "resource/test.bam";
}
if (fastaPathInput && !fastaPathInput.value) {
  fastaPathInput.value = "resource/chr20.fa";
}
const regionInput = document.getElementById("region");
const currentRegionBadge = document.getElementById("currentRegionBadge");
const loadRegion = document.getElementById("loadRegion");
const igvContainer = document.getElementById("igv-container");

const pathInputs = document.getElementById("pathInputs");
const edgeInputs = document.getElementById("edgeInputs");
const edgeDropZone = document.getElementById("edgeDropZone");
const modeRadios = Array.from(document.querySelectorAll('input[name="runMode"]'));

const edgeBamFileInput = document.getElementById("edgeBamFile");
const edgeBaiFileInput = document.getElementById("edgeBaiFile");
const edgeFastaFileInput = document.getElementById("edgeFastaFile");
const edgeFaiFileInput = document.getElementById("edgeFaiFile");

let runMode = "path";
let igvBrowser = null;
let currentSourceKey = null;
let igvLocusListenerBound = false;

const edgeFiles = {
  bam: null,
  bai: null,
  fasta: null,
  fai: null,
};

function appendMessage(text, isUser = false) {
  const bubble = document.createElement("div");
  bubble.className = `message ${isUser ? "user" : ""}`;
  if (isUser) {
    bubble.textContent = text;
  } else {
    try {
      bubble.innerHTML = marked.parse(text);
    } catch (_e) {
      bubble.textContent = text;
    }
  }
  messages.appendChild(bubble);
  messages.scrollTop = messages.scrollHeight;
  return bubble;
}

function parseRegion(region) {
  const trimmed = (region || "").trim();
  if (!trimmed) return null;
  const rangeMatch = trimmed.match(/([^:]+):(\d+)[-.]{1,2}(\d+)/);
  if (rangeMatch) {
    return { contig: rangeMatch[1], start: Number(rangeMatch[2]), end: Number(rangeMatch[3]) };
  }
  const contigMatch = trimmed.match(/^([\w.-]+)$/);
  if (contigMatch) {
    return { contig: contigMatch[1], start: null, end: null };
  }
  return null;
}

function extractRegionFromText(text) {
  const rangeMatch = text.match(/(?:^|\s)([\w.-]+):(\d+)[-.]{1,2}(\d+)(?:\s|$)/);
  if (rangeMatch) {
    return `${rangeMatch[1]}:${rangeMatch[2]}-${rangeMatch[3]}`;
  }
  return null;
}

function extractPathFromText(text, extensions) {
  const extGroup = extensions.map((ext) => ext.replace(".", "\\.")).join("|");
  const pattern = new RegExp(`([^\\s"']+(?:${extGroup}))`, "ig");
  const matches = text.match(pattern) || [];
  if (!matches.length) return null;
  return matches.sort((a, b) => b.length - a.length)[0];
}

function updateModeUI() {
  const edge = runMode === "edge";
  pathInputs.classList.toggle("hidden", edge);
  edgeInputs.classList.toggle("hidden", !edge);
}

function setMode(mode) {
  runMode = mode === "edge" ? "edge" : "path";
  if (runMode === "path") {
    edgeFiles.bam = null;
    edgeFiles.bai = null;
    edgeFiles.fasta = null;
    edgeFiles.fai = null;
    if (edgeBamFileInput) edgeBamFileInput.value = "";
    if (edgeBaiFileInput) edgeBaiFileInput.value = "";
    if (edgeFastaFileInput) edgeFastaFileInput.value = "";
    if (edgeFaiFileInput) edgeFaiFileInput.value = "";
  }
  updateModeUI();
  setEdgeFile("bam", edgeFiles.bam);
}

function setEdgeFile(kind, file) {
  edgeFiles[kind] = file || null;
  const bamStatus = document.getElementById("bamStatus");
  if (bamStatus) {
    if (runMode === "edge") {
      const bam = edgeFiles.bam ? edgeFiles.bam.name : "none";
      const bai = edgeFiles.bai ? edgeFiles.bai.name : "none";
      bamStatus.textContent = `Edge files: BAM=${bam}, BAI=${bai}`;
      bamStatus.className = edgeFiles.bam && edgeFiles.bai ? "status-tag enabled" : "status-tag disabled";
    } else {
      bamStatus.textContent = "Path mode";
      bamStatus.className = "status-tag";
    }
  }
}

function inferFileKind(fileName) {
  const lower = fileName.toLowerCase();
  if (lower.endsWith(".bam")) return "bam";
  if (lower.endsWith(".bai")) return "bai";
  if (lower.endsWith(".fasta") || lower.endsWith(".fa")) return "fasta";
  if (lower.endsWith(".fai")) return "fai";
  return null;
}

function handleDroppedFiles(files) {
  for (const file of files) {
    const kind = inferFileKind(file.name || "");
    if (!kind) continue;
    setEdgeFile(kind, file);
  }
}

async function initializeStatus() {
  const llmStatus = document.getElementById("llmStatus");
  try {
    const response = await fetch("/api/health");
    if (response.ok) {
      llmStatus.textContent = "API: OK";
      llmStatus.className = "status-tag enabled";
    } else {
      llmStatus.textContent = "API: ERROR";
      llmStatus.className = "status-tag disabled";
    }
  } catch (_error) {
    llmStatus.textContent = "API: ERROR";
    llmStatus.className = "status-tag disabled";
  }
  setEdgeFile("bam", edgeFiles.bam);
}

function getCurrentIgvRegion() {
  if (!igvBrowser) return null;
  if (typeof igvBrowser.currentLoci === "function") {
    const loci = igvBrowser.currentLoci();
    if (Array.isArray(loci) && loci.length > 0 && loci[0]) return loci[0];
  }

  const frames = igvBrowser.referenceFrameList;
  if (!Array.isArray(frames) || !frames.length) return null;
  const frame = frames[0];
  const contig = frame.chrName || frame.chr;
  if (!contig) return null;
  const start = Math.max(1, Math.floor((frame.start || 0) + 1));
  const end = frame.bpPerPixel
    ? Math.floor((frame.start || 0) + frame.bpPerPixel * (igvContainer.clientWidth || 1000))
    : null;
  if (!end || end <= start) return contig;
  return `${contig}:${start}-${end}`;
}

function syncRegionInputFromIgv(fallbackRegion = null) {
  const current = getCurrentIgvRegion() || fallbackRegion;
  if (current) {
    regionInput.value = current;
    currentRegionBadge.textContent = `Current IGV region: ${current}`;
    return current;
  }
  currentRegionBadge.textContent = "Current IGV region: not set";
  return null;
}

function updateSvSummary(data) {
  if (!svSummary) return;
  const hasAssessment = typeof data?.sv_present === "boolean";
  if (!hasAssessment) {
    svSummary.className = "sv-summary hidden";
    svSummary.textContent = "SV: not assessed";
    return;
  }
  const present = Boolean(data.sv_present);
  const svType = data.sv_type || "none";
  const confidence = typeof data.sv_confidence === "number" ? ` (${Math.round(data.sv_confidence * 100)}%)` : "";
  svSummary.className = `sv-summary ${present ? "present" : "absent"}`;
  svSummary.textContent = present
    ? `SV: present • type: ${svType}${confidence}`
    : `SV: no strong evidence${confidence}`;
}

async function fetchPathChromosomes(bamPath) {
  const response = await fetch(`/api/bam/chromosomes?bam_path=${encodeURIComponent(bamPath)}`);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "Failed to read BAM header for reference metadata.");
  }
  const data = await response.json();
  const chromosomes = Array.isArray(data.chromosomes) ? data.chromosomes : [];
  if (!chromosomes.length) {
    throw new Error("BAM header did not contain any chromosome metadata.");
  }
  return chromosomes;
}

function buildChromosomeReference(referenceId, chromosomes) {
  return {
    id: referenceId,
    chromosomes: chromosomes.map((chromosome) => ({
      name: chromosome.name,
      bpLength: chromosome.length,
    })),
  };
}

function buildEdgeRegionReference(region) {
  const parsed = parseRegion(region);
  if (!parsed?.contig) {
    throw new Error("Edge mode without FASTA requires a concrete region to infer contig metadata.");
  }
  const inferredLength = parsed.end ? Math.max(parsed.end + 100000, parsed.end * 2) : 1000000;
  return buildChromosomeReference(`edge-region-${parsed.contig}`, [{ name: parsed.contig, length: inferredLength }]);
}

function computeSourceKey(region) {
  function fileIdentity(file) {
    if (!file) return "none";
    return `${file.name}:${file.size}:${file.lastModified}`;
  }

  if (runMode === "path") {
    return [
      "path",
      (bamPathInput.value || "").trim(),
      (fastaPathInput.value || "").trim(),
    ].join(":");
  }

  const parsedRegion = parseRegion(region || regionInput.value || "");
  const edgeReferenceKey = edgeFiles.fasta ? fileIdentity(edgeFiles.fasta) : `region:${parsedRegion?.contig || "none"}`;
  return [
    "edge",
    fileIdentity(edgeFiles.bam),
    fileIdentity(edgeFiles.bai),
    edgeReferenceKey,
    fileIdentity(edgeFiles.fai),
  ].join(":");
}

function getAlignmentTrack() {
  const trackView = (igvBrowser?.trackViews || []).find((tv) => tv?.track?.type === "alignment");
  return trackView?.track || null;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForAlignmentTrackReady(timeoutMs = 3000, intervalMs = 150) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const track = getAlignmentTrack();
    if (track && typeof track.getFeatures === "function") {
      return track;
    }
    await sleep(intervalMs);
  }
  throw new Error("IGV alignment track not ready for feature extraction yet. Try again in a moment.");
}

async function buildReferenceConfig(region) {
  if (runMode === "path") {
    const bamPath = (bamPathInput.value || "").trim();
    const fastaPath = (fastaPathInput.value || "").trim();
    if (fastaPath) {
      return {
        id: "custom",
        fastaURL: `/api/file?path=${encodeURIComponent(fastaPath)}`,
        indexURL: `/api/file?path=${encodeURIComponent(`${fastaPath}.fai`)}`,
      };
    }
    if (!bamPath) {
      throw new Error("Provide a BAM path before loading a region.");
    }
    const chromosomes = await fetchPathChromosomes(bamPath);
    return buildChromosomeReference(`path-bam-${bamPath}`, chromosomes);
  }

  if (!edgeFiles.fasta) {
    return buildEdgeRegionReference(region);
  }

  if (!edgeFiles.fai) {
    throw new Error("Edge FASTA mode requires a matching FAI index file.");
  }

  return {
    id: `edge-reference-${edgeFiles.fasta.name}`,
    fastaURL: edgeFiles.fasta,
    indexFile: edgeFiles.fai,
    indexed: true,
  };
}

async function ensureBrowser(region) {
  if (!window.igv) throw new Error("IGV.js failed to load.");

  const sourceKey = computeSourceKey(region);
  if (!sourceKey || sourceKey.endsWith(":")) {
    throw new Error("No BAM source configured for selected mode.");
  }

  if (igvBrowser && currentSourceKey !== sourceKey) {
    if (igvBrowser._locusPollInterval) clearInterval(igvBrowser._locusPollInterval);
    if (typeof igvBrowser.destroy === "function") igvBrowser.destroy();
    igvBrowser = null;
    igvLocusListenerBound = false;
    igvContainer.innerHTML = "";
  }

  if (igvBrowser && currentSourceKey === sourceKey) return igvBrowser;

  const track = {
    type: "alignment",
    format: "bam",
    name: "Alignments",
    height: 500,
    autoHeight: false,
    displayMode: "SQUISHED",
    viewAsPairs: false,
    showSoftClips: true,
  };

  if (runMode === "path") {
    const bamPath = (bamPathInput.value || "").trim();
    track.url = `/api/file?path=${encodeURIComponent(bamPath)}`;
    track.indexURL = `/api/index?bam_path=${encodeURIComponent(bamPath)}`;
  } else {
    if (!edgeFiles.bam || !edgeFiles.bai) {
      throw new Error("Edge mode requires both BAM and BAI files.");
    }
    track.localFile = edgeFiles.bam;
    track.indexFile = edgeFiles.bai;
  }

  const options = {
    locus: region || undefined,
    showNavigation: true,
    showRuler: true,
    showCenterGuide: true,
    showCursorTrackingGuide: true,
    tracks: [track],
  };

  const referenceConfig = await buildReferenceConfig(region);
  if (referenceConfig) {
    options.reference = referenceConfig;
  }

  igvContainer.innerHTML = "";
  igvBrowser = await igv.createBrowser(igvContainer, options);

  if (!igvLocusListenerBound && typeof igvBrowser.on === "function") {
    igvBrowser.on("locuschange", (loci) => {
      const resolved = Array.isArray(loci) && loci.length ? loci[0] : getCurrentIgvRegion();
      if (resolved) {
        regionInput.value = resolved;
        currentRegionBadge.textContent = `Current IGV region: ${resolved}`;
      }
    });
    igvLocusListenerBound = true;
  }

  if (!igvBrowser._locusPollInterval) {
    igvBrowser._locusPollInterval = setInterval(() => {
      const polled = getCurrentIgvRegion();
      if (polled && polled !== regionInput.value) {
        regionInput.value = polled;
        currentRegionBadge.textContent = `Current IGV region: ${polled}`;
      }
    }, 500);
  }

  currentSourceKey = sourceKey;
  syncRegionInputFromIgv(region);
  return igvBrowser;
}

function parseCigarSignal(cigar) {
  if (!cigar || typeof cigar !== "string") {
    return { soft_clip_bases: 0, insertion_bases: 0, deletion_bases: 0 };
  }
  const re = /(\d+)([MIDNSHP=X])/g;
  let match;
  let softClip = 0;
  let ins = 0;
  let del = 0;
  while ((match = re.exec(cigar)) !== null) {
    const len = Number(match[1]);
    const op = match[2];
    if (op === "S") softClip += len;
    if (op === "I") ins += len;
    if (op === "D") del += len;
  }
  return { soft_clip_bases: softClip, insertion_bases: ins, deletion_bases: del };
}

function normalizeMateStrand(mate) {
  if (!mate) return null;
  const raw = mate.strand;
  if (raw === "+" || raw === true) return "+";
  if (raw === "-" || raw === false) return "-";
  return null;
}

function computePairOrientation(feature) {
  const isPaired = Boolean(feature.isPaired || feature.mate);
  if (!isPaired) return "SINGLE";
  if (feature.mate?.isUnmapped || feature.mate?.unmapped) return "UNKNOWN";

  const readStrand = feature.strand === "-" || feature.isReverseStrand ? "-" : "+";
  const mateStrand = normalizeMateStrand(feature.mate);
  if (!mateStrand) return "UNKNOWN";

  if (readStrand === "+" && mateStrand === "+") return "LL";
  if (readStrand === "-" && mateStrand === "-") return "RR";
  if (readStrand === "+" && mateStrand === "-") return "LR";
  return "RL";
}

async function extractEdgeSignals(region) {
  if (!igvBrowser) return { coverage: [], reads: [] };
  const parsed = parseRegion(region);
  if (!parsed || !parsed.start || !parsed.end) return { coverage: [], reads: [] };

  const track = await waitForAlignmentTrackReady();
  if (typeof track.getFeatures !== "function") {
    throw new Error("IGV track API is incompatible with Edge extraction (missing getFeatures).");
  }

  const features = await track.getFeatures(parsed.contig, parsed.start - 1, parsed.end, 1);
  const coverageBins = new Map();
  const reads = [];
  const maxReads = 200;

  for (const feature of features || []) {
    const start = Number(feature.start || 0) + 1;
    const end = Number(feature.end || start);
    const cigar = feature.cigar || feature.cigarString || "";
    const cigarSignal = parseCigarSignal(cigar);
    const strand = feature.strand === "-" || feature.isReverseStrand ? "-" : "+";
    const mateChr = feature.mate?.chr || feature.mate?.chromosome || feature.nextReferenceName || "UNMAPPED";
    const insertSize = Math.abs(Number(feature.fragmentLength || feature.templateLength || 0));

    if (reads.length < maxReads) {
      reads.push({
        name: feature.readName || feature.name || `read-${reads.length + 1}`,
        start,
        end,
        cigar,
        strand,
        mapq: Number(feature.mq || feature.mapQ || feature.mappingQuality || 0),
        is_paired: Boolean(feature.isPaired || feature.mate),
        mate_chromosome: mateChr,
        mate_start: feature.mate?.position ? Number(feature.mate.position) + 1 : null,
        insert_size: insertSize,
        pair_orientation: computePairOrientation(feature),
        soft_clip_bases: cigarSignal.soft_clip_bases,
        insertion_bases: cigarSignal.insertion_bases,
        deletion_bases: cigarSignal.deletion_bases,
        has_soft_clip: cigarSignal.soft_clip_bases > 0,
      });
    }

    const clampedStart = Math.max(parsed.start, start);
    const clampedEnd = Math.min(parsed.end, end);
    for (let pos = clampedStart; pos <= clampedEnd; pos += 1) {
      coverageBins.set(pos, (coverageBins.get(pos) || 0) + 1);
    }
  }

  const regionLength = Math.max(1, parsed.end - parsed.start + 1);
  const step = Math.max(1, Math.floor(regionLength / 2000));
  const coverage = [];
  for (let pos = parsed.start; pos <= parsed.end; pos += step) {
    coverage.push({ pos, depth: coverageBins.get(pos) || 0 });
  }

  return { coverage, reads };
}

function applyExtractedInputs(message) {
  const extracted = {
    bamPath: extractPathFromText(message, [".bam"]),
    fastaPath: extractPathFromText(message, [".fa", ".fasta", ".fa.gz", ".fasta.gz"]),
    region: extractRegionFromText(message),
  };

  if (runMode === "path") {
    if (extracted.bamPath) bamPathInput.value = extracted.bamPath;
    if (extracted.fastaPath) fastaPathInput.value = extracted.fastaPath;
  }
  if (extracted.region) regionInput.value = extracted.region;
  return extracted;
}

function applyIgvParams(params) {
  if (!igvBrowser || !Array.isArray(igvBrowser.trackViews)) {
    console.warn("[applyIgvParams] igvBrowser not ready");
    return false;
  }
  let dataReloadNeeded = false;

  // Browser-level params: apply once, not per-track
  for (const [key, value] of Object.entries(params)) {
    if (key === "showCenterGuide") {
      igvBrowser.config.showCenterGuide = !!value;
      igvBrowser.showCenterGuide = !!value;
      console.log("[applyIgvParams] showCenterGuide →", !!value);
      if (typeof igvBrowser.repaint === "function") igvBrowser.repaint();

    } else if (key === "showNavigation") {
      igvBrowser.config.showNavigation = !!value;
      console.log("[applyIgvParams] showNavigation →", !!value);
      const navEl = document.getElementById("igvNavigation") || (igvBrowser.navbar && igvBrowser.navbar.container);
      if (navEl) navEl.style.display = !!value ? "" : "none";

    } else if (key === "showRuler") {
      igvBrowser.config.showRuler = !!value;
      console.log("[applyIgvParams] showRuler →", !!value);
      igvBrowser.trackViews.forEach(rtv => {
        (rtv.viewports || []).forEach(vp => {
          if (vp.rulerSweeper && vp.rulerSweeper.container) {
            vp.rulerSweeper.container.style.display = !!value ? "" : "none";
          }
        });
      });
    }
  }

  igvBrowser.trackViews.forEach(tv => {
    const track = tv.track;
    if (!track) return;
    console.log("[applyIgvParams] track.type =", track.type, "params =", params);

    for (const [key, value] of Object.entries(params)) {
      if (key === "trackHeight") {
        if (typeof tv.setTrackHeight === "function") {
          tv.setTrackHeight(Number(value));
          console.log("[applyIgvParams] setTrackHeight →", value);
        }
        if (typeof tv.repaintViews === "function") tv.repaintViews();

      } else if (track.type === "alignment") {
        if (key === "viewAsPairs") {
          track.viewAsPairs = !!value;
          track.config.viewAsPairs = !!value;
          if (track.featureSource && typeof track.featureSource.setViewAsPairs === "function") {
            track.featureSource.setViewAsPairs(!!value);
            console.log("[applyIgvParams] featureSource.setViewAsPairs →", !!value);
          }
          // Try in-memory re-pair first (works when data is already loaded)
          const containers = (tv.viewports || []).map(vp => vp.cachedFeatures);
          console.log("[applyIgvParams] containers:", containers);
          let repairedInMemory = false;
          containers.forEach(container => {
            if (container && typeof container.setViewAsPairs === "function") {
              container.setViewAsPairs(!!value);
              repairedInMemory = true;
              console.log("[applyIgvParams] container.setViewAsPairs →", !!value);
            }
          });
          if (repairedInMemory && typeof tv.repaintViews === "function") {
            tv.repaintViews();
          } else {
            // Data not yet loaded — flag for reload
            dataReloadNeeded = true;
          }

        } else if (key === "showSoftClips") {
          track.showSoftClips = !!value;
          track.config.showSoftClips = !!value;
          if (track.featureSource && typeof track.featureSource.setShowSoftClips === "function") {
            track.featureSource.setShowSoftClips(!!value);
          }
          dataReloadNeeded = true;

        } else if (key === "showReadNames") {
          track.showReadNames = !!value;
          track.config.showReadNames = !!value;
          if (typeof tv.repaintViews === "function") tv.repaintViews();

        } else if (key === "colorByStrand") {
          track.colorBy = value ? "strand" : "none";
          track.config.colorBy = value ? "strand" : "none";
          if (typeof tv.repaintViews === "function") tv.repaintViews();

        } else if (key === "minMapQuality") {
          track.config.minMapQuality = Number(value);
          if (typeof tv.repaintViews === "function") tv.repaintViews();

        } else if (key === "maxInsertSize") {
          track.config.maxInsertSize = Number(value);
          console.log("[applyIgvParams] maxInsertSize →", Number(value));
          dataReloadNeeded = true;

        } else if (key === "coverageThreshold") {
          track.config.coverageThreshold = Number(value);
          console.log("[applyIgvParams] coverageThreshold →", Number(value));
          dataReloadNeeded = true;
        }
      }
    }
  });
  return dataReloadNeeded;
}

async function fetchChat() {
  const message = messageInput.value.trim();
  if (!message) return;

  const extracted = applyExtractedInputs(message);
  const igvRegion = getCurrentIgvRegion();
  const region = (extracted.region || regionInput.value || igvRegion || "").trim();

  appendMessage(message, true);
  messageInput.value = "";
  updateSvSummary(null);
  const loadingMsg = appendMessage("Analyzing...", false);

  try {
    const payload = {
      message,
      mode: runMode,
      region,
    };

    if (runMode === "path") {
      payload.bam_path = (extracted.bamPath || bamPathInput.value || "").trim();
      payload.fasta_path = (extracted.fastaPath || fastaPathInput.value || "").trim();
    } else {
      if (!region) throw new Error("Provide a region for Edge mode chat analysis.");
      const browser = await ensureBrowser(region);
      await browser.search(region);
      const edgePayload = await extractEdgeSignals(region);
      if (!edgePayload.coverage.length && !edgePayload.reads.length) {
        throw new Error("No reads or coverage were found for the requested region in Edge mode.");
      }
      payload.edge_payload = edgePayload;
    }

    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    loadingMsg.remove();

    if (!response.ok) {
      appendMessage(`Request failed: ${data.detail || "Unknown error"}`);
      return;
    }

    updateSvSummary(data);
    appendMessage(data.response || "Done");

    // Show IGV feedback if present
    if (data.igv_feedback) {
      appendMessage(`<span class='igv-feedback'>${data.igv_feedback}</span>`);
    }

    // Optionally show preset info
    if (data.preset) {
      appendMessage(`<span class='igv-preset'>Preset: <b>${data.preset}</b></span>`);
    }

    const resolvedRegion = (data.region || region || igvRegion || "").trim();
    if (resolvedRegion) {
      regionInput.value = resolvedRegion;
    }

    if (runMode === "path" && resolvedRegion) {
      const browser = await ensureBrowser(resolvedRegion);

      if (data.igv_params && typeof data.igv_params === "object") {
        // Try in-memory re-pair first (works when data is already cached in viewports)
        const needsReload = applyIgvParams(data.igv_params);
        if (needsReload) {
          // featureSource already updated; fresh search() will fetch with new setting
          await browser.search(resolvedRegion);
          // After data reloads, apply in-memory re-pair on the freshly loaded containers
          applyIgvParams(data.igv_params);
        }
      } else {
        await browser.search(resolvedRegion);
      }
    }
  } catch (error) {
    loadingMsg.remove();
    appendMessage(`Error: ${error.message || "Failed to send message"}`);
  }
}

async function fetchRegion() {
  const region = regionInput.value.trim();
  if (!region) {
    appendMessage("Provide a region first.");
    return;
  }
  if (!parseRegion(region)) {
    appendMessage("Region format should look like chr1:100-200");
    return;
  }

  try {
    if (runMode === "path") {
      const bamPath = (bamPathInput.value || "").trim();
      if (!bamPath) {
        appendMessage("Provide a BAM path in Path mode.");
        return;
      }
    } else if (!edgeFiles.bam || !edgeFiles.bai) {
      appendMessage("Select BAM and BAI files in Edge mode first.");
      return;
    }

    const browser = await ensureBrowser(region);
    await browser.search(region);
    appendMessage(`Loaded ${region} in IGV.`);
  } catch (error) {
    appendMessage(error.message || "Failed to load IGV region.");
  }
}

modeRadios.forEach((radio) => {
  radio.addEventListener("change", () => setMode(radio.value));
});

edgeBamFileInput.addEventListener("change", (e) => setEdgeFile("bam", e.target.files[0] || null));
edgeBaiFileInput.addEventListener("change", (e) => setEdgeFile("bai", e.target.files[0] || null));
edgeFastaFileInput.addEventListener("change", (e) => setEdgeFile("fasta", e.target.files[0] || null));
edgeFaiFileInput.addEventListener("change", (e) => setEdgeFile("fai", e.target.files[0] || null));

if (edgeDropZone) {
  edgeDropZone.addEventListener("dragover", (event) => {
    event.preventDefault();
    edgeDropZone.classList.add("active");
  });
  edgeDropZone.addEventListener("dragleave", () => edgeDropZone.classList.remove("active"));
  edgeDropZone.addEventListener("drop", (event) => {
    event.preventDefault();
    edgeDropZone.classList.remove("active");
    const files = Array.from(event.dataTransfer.files || []);
    handleDroppedFiles(files);
  });
}

sendMessage.addEventListener("click", fetchChat);
messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") fetchChat();
});
loadRegion.addEventListener("click", fetchRegion);

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initializeStatus);
} else {
  initializeStatus();
}

setMode("path");
