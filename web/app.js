/* DropBridge Studio — interface logic */
(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  const CHAIN = ["radio", "bridge", "netd", "awdld", "receiver"];
  const CHAIN_LABEL = {
    radio: "无线电", bridge: "管道", netd: "网络", awdld: "AWDL", receiver: "接收器",
  };
  const PHASE = {
    idle: { text: "未启动", tone: "idle", title: "未启动", hint: "点「启动接收」后，在 iPhone 上打开隔空投送，选中这台电脑即可发送。" },
    starting: { text: "启动中", tone: "starting", title: "正在建立链路", hint: "正在初始化 RTL8821CU 并启动 AWDL 服务，请稍候。" },
    ready: { text: "接收就绪", tone: "ready", title: "接收就绪", hint: "在 iPhone 上打开「隔空投送」，选中这台电脑即可发送。传输时请保持窗口开启。" },
    error: { text: "链路异常", tone: "error", title: "链路异常", hint: "后端进程退出了，点「重启」重新拉起链路，或到「诊断」页查看原因。" },
  };

  let api = null;
  let state = null;
  let view = "overview";
  let logSrc = "all";
  let logPaused = false;
  let logRenderedKey = "";
  let transferFilter = "";
  let doctorData = null;
  const thumbs = new Map();
  const seriesHistory = [];
  let settingsLoaded = false;

  /* ---------------------------------------------------------------- utils */
  const esc = (text) => String(text ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function fmtBytes(bytes) {
    const n = Number(bytes) || 0;
    if (n < 1024) return `${n} B`;
    const units = ["KB", "MB", "GB", "TB"];
    let value = n / 1024;
    let index = 0;
    while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1; }
    return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[index]}`;
  }

  function fmtSpeed(bytes) {
    const n = Number(bytes) || 0;
    if (n < 1024) return "0 KB/s";
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB/s`;
    return `${(n / 1024 / 1024).toFixed(1)} MB/s`;
  }

  function fmtDuration(seconds) {
    const s = Math.max(0, Math.floor(seconds || 0));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`
             : `${m}:${String(sec).padStart(2, "0")}`;
  }

  function fmtClock(ts) {
    const date = new Date((ts || 0) * 1000);
    return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}:${String(date.getSeconds()).padStart(2, "0")}`;
  }

  function ago(ts) {
    if (!ts) return "等待设备";
    const diff = Date.now() / 1000 - ts;
    if (diff < 60) return "刚刚";
    if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
    return `${Math.floor(diff / 3600)} 小时前`;
  }

  function toast(message, tone = "") {
    const node = document.createElement("div");
    node.className = `toast ${tone}`;
    node.textContent = message;
    $("#toasts").appendChild(node);
    setTimeout(() => {
      node.classList.add("out");
      setTimeout(() => node.remove(), 220);
    }, 3200);
  }

  /* ---------------------------------------------------------------- boot */
  window.addEventListener("pywebviewready", start);
  if (window.pywebview && window.pywebview.api) start();

  async function start() {
    if (api) return;
    api = window.pywebview.api;
    wire();
    renderChain();
    await refresh();
    const wanted = (location.hash || "").replace("#", "");
    if (wanted && document.getElementById(`view-${wanted}`)) switchView(wanted);
    setInterval(refresh, 900);
    setInterval(() => { if (view === "logs") pollLogs(); }, 900);
  }

  /* 调试用：外部可以 window.__studio.open("logs") 切页 */
  window.__studio = {
    open: (name) => switchView(name),
    state: () => state,
    api: () => api,
  };

  /* ---------------------------------------------------------------- events */
  function wire() {
    $$(".rail-btn").forEach((button) => {
      button.addEventListener("click", () => switchView(button.dataset.view));
    });

    $("#btnStart").addEventListener("click", async () => {
      $("#btnStart").disabled = true;
      try {
        await api.start();
        toast("正在建立链路…");
      } catch (error) { toast(`启动失败：${error}`, "bad"); }
      setTimeout(() => { $("#btnStart").disabled = false; }, 1200);
    });

    $("#btnStop").addEventListener("click", async () => {
      await api.stop();
      toast("已停止");
    });

    $("#btnRestart").addEventListener("click", async () => {
      toast("正在重启链路…");
      await api.restart();
    });

    $("#btnOpenOutdir").addEventListener("click", () => api.open_outdir());
    $("#btnOpenOutdir2").addEventListener("click", () => api.open_outdir());

    $("#btnClearTransfers").addEventListener("click", async () => {
      await api.clear_transfers();
      toast("列表已清空（文件仍在磁盘上）");
      refresh();
    });

    $("#btnRefreshTransfers").addEventListener("click", refresh);
    $("#transferSearch").addEventListener("input", (event) => {
      transferFilter = event.target.value.trim().toLowerCase();
      renderTransfers();
    });

    $$("#logTabs button").forEach((button) => {
      button.addEventListener("click", () => {
        logSrc = button.dataset.src;
        $$("#logTabs button").forEach((b) => b.classList.toggle("active", b === button));
        logRenderedKey = "";
        pollLogs();
      });
    });
    $("#logSearch").addEventListener("input", () => { logRenderedKey = ""; pollLogs(); });
    $("#logPause").addEventListener("change", (event) => { logPaused = event.target.checked; });

    function setupWelcome() {
    const box = $("#welcome");
    if (!box) return;
    const close = () => {
      box.hidden = true;
      api.settings_update({ welcome_seen: true });
    };
    api.state().then((snap) => {
      if (!(snap.settings && snap.settings.welcome_seen)) box.hidden = false;
    });
    $("#btnWelcomeStart").addEventListener("click", async () => { close(); await api.start(); });
    $("#btnWelcomeTest").addEventListener("click", () => {
      close();
      switchView("doctor");
      toast("就绪后点「自测接收」，会往接收目录投一个测试文件");
    });
    $("#btnWelcomeClose").addEventListener("click", close);
  }

  $("#btnDoctor").addEventListener("click", runDoctor);
  setupWelcome();
    $("#btnCapture").addEventListener("click", async () => {
      toast("正在打包…");
      const result = await api.capture_bundle();
      if (result.ok) {
        const name = result.path.split("\\").pop();
        toast(`实测包已生成：${name}（这一份就够我判断了）`, "ok");
        await api.reveal(result.path);
      } else toast(result.error || "打包失败", "bad");
    });

  $("#btnExportReport").addEventListener("click", async () => {
      const result = await api.export_report();
      if (result.ok) {
        toast(`诊断报告已导出：${result.path.split("\\").pop()}（把这份发我就行）`, "ok");
        await api.reveal(result.path);
      } else toast(result.error || "导出失败", "bad");
    });

    $("#btnPickOutdir").addEventListener("click", async () => {
      const path = await api.pick_folder($("#setOutdir").value);
      if (path) $("#setOutdir").value = path;
    });
    $("#btnPickRoot").addEventListener("click", async () => {
      const path = await api.pick_folder($("#setRoot").value);
      if (path) $("#setRoot").value = path;
    });
    $("#btnSaveSettings").addEventListener("click", saveSettings);

    $("#setAutostart").addEventListener("change", async (event) => {
      const wanted = event.target.checked;
      const result = await api.autostart(wanted);
      event.target.checked = !!result.enabled;
      toast(result.enabled ? "已设为开机自动启动" : "已取消开机自动启动");
    });

    $("#btnSelfTest").addEventListener("click", async () => {
      const panel = $("#selfTestPanel");
      panel.hidden = false;
      panel.innerHTML = `<div class="st-head">正在用模拟发送端投一个文件…</div>`;
      const result = await api.self_test();
      if (result.error && !result.steps.length) {
        panel.innerHTML = `<div class="st-head bad">${esc(result.error)}</div>`;
        return;
      }
      const rows = (result.steps || []).map((item) => `
        <div class="st-row"><span class="dot ${item.ok ? "ok" : "bad"}"></span>
        <b>${esc(item.label)}</b><span>${esc(item.detail || "")}</span></div>`).join("");
      panel.innerHTML = `
        <div class="st-head ${result.ok ? "ok" : "bad"}">
          ${result.ok ? "电脑这端完全正常：TLS、发现、协商、上传、落盘全通"
                      : "自测没通过，看下面哪一步断了"}</div>
        ${rows}
        ${result.file ? `<div class="st-file">文件已进「传输」页：${esc(result.file)}</div>` : ""}
        ${result.error ? `<div class="st-file bad">${esc(result.error)}</div>` : ""}`;
      if (result.ok) toast("自测通过，本机接收链路正常");
      refresh();
    });
  }

  function switchView(next) {
    view = next;
    $$(".rail-btn").forEach((button) => button.classList.toggle("active", button.dataset.view === next));
    $$(".view").forEach((section) => section.classList.toggle("active", section.id === `view-${next}`));
    if (next === "logs") pollLogs();
    if (next === "doctor") runDoctor();
    if (next === "settings") {
      fillSettings();
      api.autostart().then((result) => { $("#setAutostart").checked = !!result.enabled; });
    }
  }

  /* ---------------------------------------------------------------- refresh */
  async function refresh() {
    if (!api) return;
    try {
      state = await api.state();
    } catch (error) {
      return;
    }
    renderStatus();
    renderHero();
    renderStats();
    renderChainState();
    renderTransfers();
    if (view === "settings" && !settingsLoaded) fillSettings();
    if (view === "doctor" && doctorData) {
      renderEnv(state.env);
      renderDiscovery(state.discovery);
    }
  }

  function renderStatus() {
    const phase = state.phase || "idle";
    const info = PHASE[phase] || PHASE.idle;
    const pill = $("#statusPill");
    pill.dataset.state = info.tone;
    pill.querySelector("span").textContent = info.text;

    const running = phase === "starting" || phase === "ready";
    $("#btnStart").hidden = running;
    $("#btnStop").hidden = !running;
    $("#topbarSub").textContent = phase === "ready"
      ? `${state.settings.device_name} · 信道 ${state.settings.channel} · ${state.env.driver?.bound ? "WinUSB 已绑定" : "驱动未就绪"}`
      : "让 Windows 直接接收 iPhone 的隔空投送";
  }

  function renderHero() {
    const phase = state.phase || "idle";
    const info = PHASE[phase] || PHASE.idle;
    const title = $("#heroTitle");
    const hint = $("#heroHint");
    title.textContent = phase === "error" && state.last_error ? "链路异常" : info.title;
    hint.textContent = phase === "error" && state.last_error ? state.last_error : info.hint;
    $("#heroEyebrow").textContent = phase === "ready" ? "正在监听" : "当前状态";

    const radar = $("#radar");
    radar.classList.toggle("on", phase === "ready");
    radar.classList.toggle("busy", phase === "starting");

    $("#tagChannel").textContent = `信道 ${state.settings.channel} · ${state.settings.width}MHz`;
    $("#tagName").textContent = state.settings.device_name;
    $("#tagAddr").textContent = `AWDL ${state.address || "—"}`;

    const beacon = state.beacon || {};
    const tagBeacon = $("#tagBeacon");
    tagBeacon.textContent = `信标 ${ {ok: "已在广播", wait: "启动中", error: "异常", off: "未启用"}[beacon.state] || "—" }`;
    tagBeacon.classList.toggle("bad", beacon.state === "error");
    tagBeacon.classList.toggle("warn", beacon.state === "wait");
    tagBeacon.title = beacon.text || "蓝牙信标";

    const receiver = state.stats.receiver || {};
    $("#statDiscover").textContent = receiver.discovers ?? 0;
    $("#statAsk").textContent = receiver.asks ?? 0;
    $("#statLast").textContent = receiver.last_event || "—";
    $("#statLastTime").textContent = receiver.last_event_at ? ago(receiver.last_event_at) : "等待设备";

    const guide = $("#askGuide");
    if (guide) {
      const stuck = (receiver.discovers || 0) > 0 && (receiver.asks || 0) === 0;
      guide.hidden = !stuck;
    }
  }

  function renderStats() {
    const radio = state.stats.radio || {};
    $("#statFps").textContent = Math.round(radio.fps || 0);
    $("#statPeers").textContent = state.stats.netd?.peers ?? radio.peers ?? 0;
    $("#statUptime").textContent = fmtDuration(state.uptime);
    $("#statRestarts").textContent = `自动重启 ${state.restarts || 0} 次`;
    $("#statMaster").textContent = state.master
      ? (state.master === state.address ? "同步主节点（本机）" : `主节点 ${state.master}`)
      : "同步主节点 —";

    const files = state.transfers || [];
    $("#statFiles").textContent = files.length;
    $("#statBytes").textContent = fmtBytes(files.reduce((sum, f) => sum + (f.size || 0), 0));

    document.documentElement.style.setProperty("--scan", "0");
    drawSpark();
  }

  function drawSpark() {
    const canvas = $("#spark");
    if (!canvas) return;
    const series = (state.series || []).slice(-60);
    const value = series.length ? Math.max(...series.map((p) => p.fps || 0), 6) : 6;
    const rect = canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(rect.width, 120);
    const height = 44;
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    if (series.length < 2) return;
    const step = width / Math.max(series.length - 1, 1);
    const points = series.map((point, index) => [
      index * step,
      height - 4 - (Math.min(point.fps || 0, value) / value) * (height - 8),
    ]);
    const gradient = ctx.createLinearGradient(0, 0, width, 0);
    gradient.addColorStop(0, "rgba(91,140,255,.95)");
    gradient.addColorStop(1, "rgba(160,107,255,.95)");
    ctx.beginPath();
    points.forEach(([x, y], index) => (index ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.strokeStyle = gradient;
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.stroke();
    ctx.lineTo(width, height);
    ctx.lineTo(0, height);
    ctx.closePath();
    const fill = ctx.createLinearGradient(0, 0, 0, height);
    fill.addColorStop(0, "rgba(91,140,255,.28)");
    fill.addColorStop(1, "rgba(91,140,255,0)");
    ctx.fillStyle = fill;
    ctx.fill();
  }

  function renderChain() {
    $("#chain").innerHTML = CHAIN.map((name, index) => `
      <div class="node" data-node="${name}">
        <div class="dot">${index + 1}</div>
        <div class="name">${CHAIN_LABEL[name]}</div>
        <div class="meta">${name}</div>
      </div>`).join("");
  }

  function renderChainState() {
    const byName = new Map((state.children || []).map((child) => [child.name, child]));
    let previousOk = true;
    CHAIN.forEach((name) => {
      const node = document.querySelector(`.node[data-node="${name}"]`);
      if (!node) return;
      const child = byName.get(name);
      const alive = !!child?.running;
      const ready = !!child?.ready;
      node.classList.toggle("on", ready);
      node.classList.toggle("done", ready && previousOk);
      node.classList.toggle("err", !alive && (state.phase === "error" || (state.phase === "ready")));
      node.querySelector(".meta").textContent = child?.pid ? `pid ${child.pid}` : (alive ? "启动中" : "未运行");
      previousOk = previousOk && ready;
    });
    $("#chainMessage").textContent = state.message || "等待启动";
  }

  function fileIcon(kind, thumb) {
    if (thumb) return `<img src="${thumb}" alt="">`;
    if (kind === "image") {
      return `<svg viewBox="0 0 24 24"><path d="M4 5h16v14H4z" fill="none" stroke="currentColor" stroke-width="1.7"/><circle cx="9" cy="10" r="1.6"/><path d="M5 17l5-5 4 4 3-3 2 2" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>`;
    }
    return `<svg viewBox="0 0 24 24"><path d="M6 3h8l4 4v14H6z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M14 3v4h4" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>`;
  }

  function rowTemplate(file) {
    const thumb = thumbs.get(file.path);
    const status = file.status === "done"
      ? `<span class="state done">已保存</span>`
      : `<span class="state receiving">接收中</span>`;
    const speed = file.status === "receiving" && file.speed ? ` · ${fmtSpeed(file.speed)}` : "";
    return `
      <div class="row">
        <div class="fileicon">${fileIcon(file.kind, thumb)}</div>
        <div class="meta">
          <div class="name" title="${esc(file.path)}">${esc(file.name)}</div>
          <div class="sub"><span>${fmtBytes(file.size)}${speed}</span><span>${ago(file.mtime)}</span></div>
        </div>
        ${status}
        <div class="acts">
          <button class="icon-btn" data-act="open" data-path="${esc(file.path)}" title="打开文件">
            <svg viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
          <button class="icon-btn" data-act="reveal" data-path="${esc(file.path)}" title="在文件夹中显示">
            <svg viewBox="0 0 24 24"><path d="M3 7h7l2 2h9v10H3z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>
          </button>
          <button class="icon-btn" data-act="copy" data-path="${esc(file.path)}" title="复制路径">
            <svg viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3" fill="none" stroke="currentColor" stroke-width="1.7"/></svg>
          </button>
        </div>
      </div>`;
  }

  function bindRows(container) {
    container.querySelectorAll(".icon-btn").forEach((button) => {
      button.addEventListener("click", async () => {
        const { act, path } = button.dataset;
        if (act === "open") await api.open_path(path);
        if (act === "reveal") await api.reveal(path);
        if (act === "copy") {
          const result = await api.copy_path(path);
          toast(result.ok ? "路径已复制" : "复制失败", result.ok ? "" : "bad");
        }
      });
    });
  }

  function renderTransfers() {
    const files = state.transfers || [];
    const recent = files.slice(0, 3);
    const recentList = $("#recentList");
    recentList.innerHTML = recent.length ? recent.map(rowTemplate).join("")
      : `<div class="empty">还没有收到文件</div>`;
    bindRows(recentList);
    requestThumbs(recent);

    const filtered = transferFilter
      ? files.filter((file) => file.name.toLowerCase().includes(transferFilter))
      : files;
    $("#transferCount").textContent = files.length;
    const list = $("#transferList");
    list.innerHTML = filtered.length ? filtered.map(rowTemplate).join("")
      : `<div class="empty">${files.length ? "没有匹配的文件" : "还没有收到文件"}</div>`;
    bindRows(list);
    requestThumbs(filtered.slice(0, 40));
    renderTimeline();
  }

  function renderTimeline() {
    const box = $("#timeline");
    if (!box) return;
    const items = (state.events || []).slice(-8).reverse();
    if (!items.length) {
      box.innerHTML = `<div class="empty">还没有事件</div>`;
      return;
    }
    box.innerHTML = items.map((item) => `
      <div class="tl-row ${item.kind}${item.historic ? " historic" : ""}">
        <span class="tl-time">${item.t || ""}</span>
        <span class="tl-dot"></span>
        <span class="tl-text">${esc(item.text || "")}</span>
      </div>`).join("");
  }

  async function requestThumbs(files) {
    for (const file of files) {
      if (file.kind !== "image" || thumbs.has(file.path)) continue;
      try {
        const data = await api.thumb(file.path);
        if (data) {
          thumbs.set(file.path, data);
          const target = document.querySelector(`.row .name[title="${CSS.escape(file.path)}"]`);
          const icon = target?.closest(".row")?.querySelector(".fileicon");
          if (icon) icon.innerHTML = `<img src="${data}" alt="">`;
        }
      } catch (error) { /* ignore */ }
    }
  }

  /* ---------------------------------------------------------------- logs */
  async function pollLogs() {
    if (!api || logPaused) return;
    const query = $("#logSearch").value.trim().toLowerCase();
    let rows = [];
    try {
      rows = await api.logs(logSrc, 500);
    } catch (error) { return; }
    if (query) rows = rows.filter((row) => row.text.toLowerCase().includes(query));
    const key = rows.length ? `${rows[0].t}:${rows.length}:${rows[rows.length - 1].text}` : "empty";
    if (key === logRenderedKey) return;
    logRenderedKey = key;

    const consoleEl = $("#logConsole");
    const atBottom = consoleEl.scrollHeight - consoleEl.scrollTop - consoleEl.clientHeight < 60;
    consoleEl.innerHTML = rows.map((row) => {
      const text = esc(row.text);
      let tone = "";
      if (/(\[E\]|\bERROR\b|failed|拒绝)/i.test(row.text)) tone = "err";
      else if (/(\[W\]|\bWARN\b)/i.test(row.text)) tone = "warn";
      else if (/ready|connected|receiving as|advertis|connected;|ok\b/i.test(row.text)) tone = "ok";
      return `<div class="ln ${tone}"><span class="ts">${fmtClock(row.t)}</span><span class="src">${esc(row.src)}</span><span class="msg">${text}</span></div>`;
    }).join("") || `<div class="ln"><span class="msg">暂无日志</span></div>`;
    if (atBottom) consoleEl.scrollTop = consoleEl.scrollHeight;
  }

  /* ---------------------------------------------------------------- doctor */
  async function runDoctor() {
    if (!api) return;
    $("#checks").innerHTML = `<div class="empty">正在检测…</div>`;
    doctorData = await api.doctor();
    const checks = doctorData.checks || [];
    $("#checks").innerHTML = checks.map((check) => `
      <div class="check ${check.ok ? "ok" : "bad"}">
        <span class="badge"></span>
        <div class="body">
          <div class="title">${esc(check.title)}</div>
          <div class="detail">${esc(check.detail || "")}</div>
        </div>
        ${check.ok || !check.fix ? "" : `<button class="btn ghost sm" data-fix="${esc(check.fix)}">修复</button>`}
      </div>`).join("");
    $("#checks").querySelectorAll("[data-fix]").forEach((button) => {
      button.addEventListener("click", async () => {
        button.disabled = true;
        const result = await api.fix(button.dataset.fix);
        if (result.ok) toast(result.message || "已处理");
        else toast(result.error || result.message || "操作失败", "bad");
        if (result.log) console.log(result.log);
        runDoctor();
      });
    });
    renderEnv(doctorData.env);
    renderDiscovery(state && state.discovery);
  }

  function renderDiscovery(discovery) {
    const box = $("#discoveryTable");
    if (!box) return;
    if (!discovery) {
      box.innerHTML = `<div class="empty">链路没启动，暂时没有发现层数据</div>`;
      return;
    }
    const mdns = discovery.mdns || {};
    const peer = Number(discovery.awdl_peers || 0);
    const queries = Number(mdns.total_queries || 0);
    const verdict = discovery.verdict || "未启动";
    const VERDICT = {
      "未启动": ["链路没启动", "先点「启动接收」"],
      "await-peer": ["等不到 AWDL 对端", "手机没和这台电脑同步上，先确认手机 AirDrop 已打开、屏幕别锁"],
      "await-query": ["有对端，但没有设备来查询", "对方连上了却没开始找接收端，多半是它把 AirDrop 设成了「仅联系人」"],
      "queried": ["有设备在查询了", "对方找到了但没走协商，看一眼最近的 Ask"],
      "ok": ["发现层正常", "有设备查询并完成协商"],
    };
    const [title, advice] = VERDICT[verdict] || [verdict, ""];
    if (mdns.listening === false) {
      // 旁听关掉时没有查询计数，不能把它当成「没有设备在找我们」。
      box.innerHTML = [
        ["结论", peer > 0 ? `${peer} 个设备已同步（旁听统计未启用）` : "链路就绪，等设备出现"],
        ["AWDL 对端", peer > 0 ? `${peer} 个设备已同步` : "还没有设备同步上"],
        ["mDNS 查询", "旁听未启用，不计数（不影响接收）"],
        ["怎么开", "设置里打开「发现层统计」后重启链路；排障用，平时保持关闭"],
      ].map(([key, value]) => `
      <div class="env-row"><span>${esc(key)}</span><span>${value}</span></div>`).join("");
      return;
    }
    const names = (mdns.names || [])
      .map((item) => (typeof item === "string" ? esc(item) : `${esc(item.name)} ×${Number(item.count || 0)}`))
      .join("<br>") || "—";
    const lastAsk = discovery.last_ask && discovery.last_ask.name
      ? `${esc(discovery.last_ask.name)}${discovery.last_ask.model ? ` · ${esc(discovery.last_ask.model)}` : ""}`
      : "还没有设备确认过";
    const recent = (mdns.recent || []).map((item) => {
      const when = item.ago === undefined ? "" : `（${Number(item.ago).toFixed(0)}s 前）`;
      return `${esc(item.type || "?")} ${esc(item.name || "")}${when}`;
    }).join("<br>") || "—";
    const rows = [
      ["结论", `${esc(title)}${advice ? ` —— ${esc(advice)}` : ""}`],
      ["AWDL 对端", peer > 0 ? `${peer} 个设备已同步` : "还没有设备同步上"],
      ["mDNS 查询", queries > 0 ? `共 ${queries} 次（最近 1 分钟 ${Number(mdns.this_minute || 0)} 次）` : "一次都没收到"],
      ["在找什么名字", names],
      ["最近一条", recent],
      ["最近 Ask", lastAsk],
      ["旁听状态", mdns.error ? `异常：${esc(mdns.error)}` : `正常（监听 ${Number(mdns.port || 0)}，转发到 15353）`],
    ];
    box.innerHTML = rows.map(([key, value]) => `
      <div class="env-row"><span>${esc(key)}</span><span>${value}</span></div>`).join("");
  }

  function renderEnv(env) {
    if (!env) return;
    const rail = $("#railVersion");
    if (rail && env.app) rail.textContent = `v${env.app}`;
    const rows = [
      ["应用版本", `DropBridge Studio ${env.app}`],
      ["后端版本", env.backend_version || "—"],
      ["安装目录", env.root || "未设置"],
      ["驱动状态", env.driver?.bound ? "WinUSB 已绑定 (MI_02)" : (env.driver?.present ? `未绑定（${env.driver.service || "无"}）` : "未检测到设备")],
      ["运行环境", `Windows · Python ${env.python}`],
      ["主机", env.hostname],
      ["占用端口", env.ports.join(" / ")],
    ];
    $("#envTable").innerHTML = rows.map(([key, value]) => `
      <div class="env-row"><span>${esc(key)}</span><span>${esc(value)}</span></div>`).join("");
  }

  /* ---------------------------------------------------------------- settings */
  function fillSettings() {
    if (!state) return;
    const s = state.settings;
    $("#setName").value = s.device_name || "";
    $("#setModel").value = s.model || "";
    $("#setChannel").value = s.channel ?? 149;
    $("#setWidth").value = s.width ?? 20;
    $("#setChanseq").value = s.chanseq || "social";
    $("#setFlags").value = s.flags || "0x3fb";
    $("#setOutdir").value = state.app.outdir || "";
    $("#setRoot").value = state.app.root || "";
    $("#setBeacon").checked = !!s.beacon;
    $("#setAutoConnect").checked = !!s.auto_connect;
    $("#setAutoRestart").checked = !!s.auto_restart;
    $("#setVerbose").checked = !!s.radio_verbose;
    $("#setTray").checked = s.close_to_tray !== false;
    $("#setMinimized").checked = !!s.start_minimized;
    $("#setObserve").checked = !!s.mdns_observe;
    $("#setObserve").checked = !!s.mdns_observe;
    settingsLoaded = true;
  }

  async function saveSettings() {
    const patch = {
      device_name: $("#setName").value.trim() || "DropBridge",
      model: $("#setModel").value.trim() || "MacBookPro18,3",
      channel: Number($("#setChannel").value) || 149,
      width: Number($("#setWidth").value) || 20,
      chanseq: $("#setChanseq").value,
      flags: $("#setFlags").value.trim() || "0x3fb",
      outdir: $("#setOutdir").value,
      root: $("#setRoot").value,
      beacon: $("#setBeacon").checked,
      auto_connect: $("#setAutoConnect").checked,
      auto_restart: $("#setAutoRestart").checked,
      radio_verbose: $("#setVerbose").checked,
      close_to_tray: $("#setTray").checked,
      start_minimized: $("#setMinimized").checked,
      mdns_observe: $("#setObserve").checked,
      mdns_observe: $("#setObserve").checked,
    };
    await api.settings_update(patch);
    settingsLoaded = false;
    toast("设置已保存");
    refresh();
  }
})();
