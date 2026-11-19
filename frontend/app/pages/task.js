/* 业务界面 2：检测详情（task.html?id=17）
 *
 * 三块内容：
 *   1) 基本信息（含模式选择原因）
 *   2) 播放器：自动播放 + 播放/暂停 + 逐帧 + 进度条跳看 + 报警帧红色标记
 *   3) 报警帧与全部处理帧的快捷跳转
 */
(async function () {
  await requireAuth();
  mountTopbar('tasks');

  const detailBox = $('#detailBox');
  const taskId = queryParam('id');
  if (!taskId) {
    detailBox.innerHTML = '<div class="card"><div class="empty">缺少任务 ID。</div></div>';
    return;
  }

  let task, frames, boxesByFrame, regionList;
  try {
    task = await api(`/detect-tasks/${taskId}`);
    frames = await api(`/detect-tasks/${taskId}/frames`);
    const allDets = await api(`/detect-tasks/${taskId}/detections`);
    // 警戒区域：播放时要叠在画面上，所以和检测结果一起加载
    regionList = await api(`/regions?media_id=${task.media_id}`);
    boxesByFrame = new Map();
    for (const d of allDets) {
      if (!boxesByFrame.has(d.frame_index)) boxesByFrame.set(d.frame_index, []);
      boxesByFrame.get(d.frame_index).push(d);
    }
  } catch (err) {
    detailBox.innerHTML = `<div class="card"><div class="empty">加载失败：${esc(err.message)}</div></div>`;
    return;
  }

  const media = task.media || {};
  const isVideo = media.media_type === 'video';
  const hotFrames = frames.filter((f) => f.intrusion_count > 0);
  const stride = media.frame_stride || 1;

  document.title = `${media.original_name || '检测任务 ' + task.id} · 检测详情`;

  detailBox.innerHTML = `
    <div class="detail-head">
      <a class="back" href="tasks.html">← 返回列表</a>
      <h1>${esc(media.original_name || '检测任务 ' + task.id)}</h1>
      ${statusTag(task.status)}
      <span class="tag mut">${task.requested_mode}${task.actual_mode ? ' → ' + task.actual_mode : ''}</span>
    </div>

    <div class="card">
      <h2>基本信息</h2>
      <div class="kv">
        <div><span class="k">分辨率</span><span class="v">${media.width && media.height ? `${media.width}×${media.height}` : '—'}</span></div>
        <div><span class="k">帧率</span><span class="v">${media.fps != null ? Number(media.fps).toFixed(2) + ' fps' : '—'}</span></div>
        <div><span class="k">总帧数</span><span class="v">${media.total_frames ?? '—'}</span></div>
        <div><span class="k">总时长</span><span class="v">${media.duration_ms != null ? fmtDuration(media.duration_ms) : '—'}</span></div>
        <div><span class="k">抽帧步长</span><span class="v">每 ${stride} 帧</span></div>
        <div><span class="k">处理帧数</span><span class="v">${task.frames_processed}</span></div>
        <div><span class="k">端到端</span><span class="v">${task.elapsed_ms != null ? task.elapsed_ms + ' ms' : '—'}</span></div>
        <div><span class="k">推理累计</span><span class="v">${task.inference_ms_total != null ? task.inference_ms_total + ' ms' : '—'}</span></div>
      </div>
      <div class="reason"><b>模式选择原因：</b>${esc(task.decision_reason || '—')}</div>
    </div>

    <div class="card">
      <h2>画面与进度</h2>
      <div class="player-tools">
        <label class="chk">
          <input type="checkbox" id="chkRegions" ${regionList.length ? 'checked' : 'disabled'} />
          显示警戒区域${regionList.length ? `（${regionList.length} 个）` : '（未设置）'}
        </label>
        <span class="spacer"></span>
        ${isVideo ? '<button class="btn sm" id="btnDownload">下载标注视频</button>' : ''}
      </div>
      <div class="player">
        <div class="media-box">
          <div class="fit" id="fitBox">
            ${isVideo
              ? '<video id="vid" muted playsinline preload="auto"></video>'
              : '<img class="frame" id="still" alt="检测帧" />'}
            <canvas class="overlay" id="overlay"></canvas>
          </div>
        </div>
      </div>

      ${isVideo ? `
      <div class="seek" id="seek" title="点击或拖动跳看">
        <div class="track"></div>
        <div class="fill" id="seekFill"></div>
        <div class="knob" id="seekKnob"></div>
        ${hotFrames.filter((f) => f.frame_ts_ms != null).map((f) => {
          const dur = media.duration_ms || 0;
          const pct = dur ? (f.frame_ts_ms / dur) * 100 : 0;
          return `<div class="mark" style="left:${Math.min(100, Math.max(0, pct))}%"
                    title="第 ${f.frame_index} 帧 · 侵入 ${f.intrusion_count} 个"></div>`;
        }).join('')}
      </div>

      <div class="controls">
        <button class="btn sm" id="btnPlay">暂停</button>
        <button class="btn sm" id="btnPrevFrame">◀ 上一帧</button>
        <button class="btn sm" id="btnNextFrame">下一帧 ▶</button>
        <span class="time" id="clock">00:00 / ${fmtClock(media.duration_ms || 0)}</span>
        <span class="spacer"></span>
        <span class="muted-small">自动播放（已静音）</span>
        <span class="frame-badge" id="frameBadge">—</span>
      </div>
      ` : `
      <div class="controls">
        <span class="frame-badge" id="frameBadge">—</span>
        <span class="spacer"></span>
        <span class="muted-small">静态图片，无时间轴</span>
      </div>
      `}
    </div>

    <div class="card">
      <h2>报警帧（共 ${hotFrames.length} 帧，点击快速跳转）</h2>
      ${hotFrames.length
        ? `<div class="frame-chips">${hotFrames.map((f) =>
            `<button class="chip hot" data-ts="${f.frame_ts_ms ?? ''}">
              帧 ${f.frame_index}${f.frame_ts_ms != null ? ' · ' + fmtClock(f.frame_ts_ms) : ''} · 侵入${f.intrusion_count}
             </button>`).join('')}</div>`
        : '<div class="empty" style="padding:18px">该任务没有产生侵入告警。检查是否设置了警戒区域，或目标是否落在区域外。</div>'}
    </div>

    <div class="card">
      <h2>全部处理帧（每 ${stride} 帧一个）</h2>
      <div class="frame-chips">
        ${frames.map((f) => `<button class="chip ${f.intrusion_count ? 'hot' : ''}"
            data-ts="${f.frame_ts_ms ?? ''}">帧 ${f.frame_index}${f.intrusion_count ? ' ⚠' : ''}</button>`).join('')
          || '<span class="muted-small">无</span>'}
      </div>
    </div>`;

  const fitBox = $('#fitBox');
  const overlay = $('#overlay');
  const badge = $('#frameBadge');

  // 是否叠加显示警戒区域（有区域时默认开）
  let showRegions = regionList.length > 0;
  // 由「图片 / 视频」两个分支各自赋值，供开关和下载后重绘使用
  let redraw = () => {};

  const chkRegions = $('#chkRegions');
  if (chkRegions) {
    chkRegions.onchange = () => { showRegions = chkRegions.checked; redraw(); };
  }

  /* 下载标注视频：区域轮廓 + 检测框烧进画面，后端渲染成 WebM。
     注意下载要带 token，不能用 <a href> 直连，所以走 fetch → blob → 临时链。 */
  const btnDownload = $('#btnDownload');
  if (btnDownload) {
    btnDownload.onclick = async () => {
      const old = btnDownload.textContent;
      btnDownload.disabled = true;
      btnDownload.textContent = '渲染中…';
      try {
        const res = await fetch(`${API_BASE}/api/detect-tasks/${task.id}/render`, {
          headers: AUTH.token ? { Authorization: `Bearer ${AUTH.token}` } : {},
        });
        if (!res.ok) {
          let detail = '';
          try { detail = (await res.json()).message || ''; } catch { /* 非 JSON */ }
          throw new Error(detail || `HTTP ${res.status}`);
        }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `task${task.id}_annotated.webm`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 5000);
        toast('标注视频已开始下载（WebM 格式）');
      } catch (err) {
        toast('导出失败：' + err.message, true);
      } finally {
        btnDownload.disabled = false;
        btnDownload.textContent = old;
      }
    };
  }

  /* ---------------------------------------------------------- 叠加绘制 */

  /**
   * 把归一化框画到 canvas 上。
   * 关键点：视频/图片按 object-fit 等比缩放后会有留黑边，
   * 所以要先算出"实际显示区域"（缩放比 + 偏移），否则框会整体偏移。
   */


  function renderFrameBoxes(frameIndex, natW, natH) {
    const boxes = boxesByFrame.get(frameIndex) || [];
    const f = frames.find((x) => x.frame_index === frameIndex);
    const count = f ? f.intrusion_count : 0;

    badge.textContent = `帧 ${frameIndex} · 目标 ${boxes.length} 个` + (count ? ` · 侵入 ${count}` : '');

    // 多点侵入就逐个标红；这里按顺序取前 count 个
    const host = fitBox.getBoundingClientRect();
    overlay.width = Math.max(1, Math.round(host.width));
    overlay.height = Math.max(1, Math.round(host.height));
    const ctx = overlay.getContext('2d');
    ctx.clearRect(0, 0, overlay.width, overlay.height);
    if (!natW || !natH) return;

    const scale = Math.min(overlay.width / natW, overlay.height / natH);
    const dw = natW * scale, dh = natH * scale;
    const ox = (overlay.width - dw) / 2, oy = (overlay.height - dh) / 2;
    ctx.lineWidth = 2;
    ctx.font = '12px ui-monospace, Consolas, monospace';

    // ---- 警戒区域：半透明填充 + 橙色轮廓，画在检测框下层 ----
    if (showRegions) {
      for (const r of regionList) {
        const rp = r.points;
        if (!rp || rp.length < 3) continue;

        ctx.beginPath();
        ctx.moveTo(ox + rp[0][0] * dw, oy + rp[0][1] * dh);
        for (let k = 1; k < rp.length; k++) ctx.lineTo(ox + rp[k][0] * dw, oy + rp[k][1] * dh);
        ctx.closePath();

        ctx.fillStyle = 'rgba(245,158,11,.14)';
        ctx.fill();
        ctx.lineWidth = 2;
        ctx.strokeStyle = '#f59e0b';
        ctx.stroke();

        // 区域名（canvas 能用系统字体，中文正常显示）
        const nm = r.name || `区域${r.id}`;
        ctx.font = '12px ui-monospace, Consolas, monospace';
        const nw = ctx.measureText(nm).width;
        const nx = ox + rp[0][0] * dw, ny = oy + rp[0][1] * dh;
        ctx.fillStyle = 'rgba(180,83,9,.92)';
        ctx.fillRect(nx, ny, nw + 8, 16);
        ctx.fillStyle = '#fff';
        ctx.fillText(nm, nx + 4, ny + 12);

        ctx.lineWidth = 2;
        ctx.font = '12px ui-monospace, Consolas, monospace';
      }
    }

    boxes.forEach((b, i) => {
      const inside = i < count;
      const x = ox + b.x1 * dw, y = oy + b.y1 * dh;
      const w = (b.x2 - b.x1) * dw, h = (b.y2 - b.y1) * dh;
      ctx.strokeStyle = inside ? '#ef4444' : '#22c55e';
      ctx.strokeRect(x, y, w, h);

      const label = b.score.toFixed(2) + (inside ? ' 侵入' : '');
      const tw = ctx.measureText(label).width;
      ctx.fillStyle = inside ? 'rgba(239,68,68,.88)' : 'rgba(34,197,94,.88)';
      ctx.fillRect(x, Math.max(0, y - 15), tw + 8, 15);
      ctx.fillStyle = '#fff';
      ctx.fillText(label, x + 4, Math.max(11, y - 4));
    });
  }

  /* ---------------------------------------------------------- 静态图片 */
  if (!isVideo) {
    const still = $('#still');
    const firstIdx = frames.length ? frames[0].frame_index : 0;
    redraw = () => {
      if (still.naturalWidth) renderFrameBoxes(firstIdx, still.naturalWidth, still.naturalHeight);
    };
    try {
      still.src = await blobUrl(`/media/${task.media_id}/frames/${firstIdx}`);
      still.onload = redraw;
    } catch (err) {
      fitBox.innerHTML = `<div class="empty" style="color:#aab">${esc(err.message)}</div>`;
    }
    window.addEventListener('resize', () => redraw());
    return;
  }

  /* ---------------------------------------------------------- 视频 */
  const vid = $('#vid');
  const seek = $('#seek');
  const fillEl = $('#seekFill');
  const knob = $('#seekKnob');
  const clock = $('#clock');
  const btnPlay = $('#btnPlay');
  let durationMs = media.duration_ms || 0;
  let currentFrame = frames.length ? frames[0].frame_index : 0;
  let drawn = false;   // 首帧是否已经绘制过（见 updateOverlay 里的说明）

  function showVideoError(reason) {
    badge.textContent = '';
    fitBox.innerHTML = `
      <div style="padding:34px 20px;text-align:center;color:#cbd5e1">
        <div style="font-size:14px;margin-bottom:6px">浏览器无法播放该视频</div>
        <div style="font-size:12px;color:#94a3b8;line-height:1.7">
          ${esc(reason)}<br>
          最常见的原因是文件使用了 <b>MPEG-4 Part 2（mp4v）</b> 编码，Chromium 内核不支持。<br>
          请用 ffmpeg 转成 H.264 后重新上传：
          <code style="color:#e2e8f0">ffmpeg -i in.mp4 -c:v libx264 -pix_fmt yuv420p out.mp4</code>
        </div>
      </div>`;
  }

  badge.textContent = '正在加载视频…';
  try {
    vid.src = await blobUrl(`/media/${task.media_id}/video`);
  } catch (err) {
    fitBox.innerHTML = `<div class="empty" style="color:#aab">视频加载失败：${esc(err.message)}</div>`;
    return;
  }

  // 6 秒内拿不到元数据就认为解不了，避免无限等待
  const watchdog = setTimeout(() => {
    if (!vid.videoWidth) showVideoError('加载超时（无法解析视频头）。');
  }, 6000);
  vid.addEventListener('error', () => { clearTimeout(watchdog); showVideoError('视频解码失败。'); }, { once: true });

  /** 找时间上最接近当前播放位置的"已处理帧" */
  function nearestFrame(ms) {
    let best = null, bestD = Infinity;
    for (const f of frames) {
      if (f.frame_ts_ms == null) continue;
      const d = Math.abs(f.frame_ts_ms - ms);
      if (d < bestD) { bestD = d; best = f; }
    }
    return best;
  }

  function updateOverlay(force = false) {
    if (!vid.videoWidth) return;
    const f = nearestFrame(vid.currentTime * 1000);
    if (!f) return;
    // 不能只用"帧号变了"来判断是否重绘：currentFrame 初始就是第一帧，
    // 首次调用会因"没变化"而跳过，导致首帧框画不出来、角标停在"正在加载视频…"。
    if (force || !drawn || f.frame_index !== currentFrame) {
      currentFrame = f.frame_index;
      renderFrameBoxes(f.frame_index, vid.videoWidth, vid.videoHeight);
      drawn = true;
    }
  }

  function updateProgress() {
    const total = durationMs || (vid.duration ? vid.duration * 1000 : 0);
    const pct = total ? Math.min(100, (vid.currentTime * 1000 / total) * 100) : 0;
    fillEl.style.width = pct + '%';
    knob.style.left = pct + '%';
    clock.textContent = `${fmtClock(vid.currentTime * 1000)} / ${fmtClock(total)}`;
  }

  vid.addEventListener('loadedmetadata', () => {
    clearTimeout(watchdog);
    if (!durationMs && vid.duration) durationMs = vid.duration * 1000;
    clock.textContent = `00:00 / ${fmtClock(durationMs)}`;
    updateProgress();
    updateOverlay();

    // ---- 自动播放 ----
    // 浏览器策略：静音才允许自动播放（本项目的视频没有音轨，静音无感）
    vid.muted = true;
    const p = vid.play();
    if (p && p.catch) {
      p.catch(() => {
        // 被拦截时退回手动，并提示
        btnPlay.textContent = '播放';
        toast('浏览器拦截了自动播放，请点「播放」');
      });
    }
  });
  vid.addEventListener('timeupdate', () => { updateProgress(); updateOverlay(); syncPlayBtn(); });
  // 按钮文案按实际状态推导，避免 play/pause/ended 的事件顺序问题
  function syncPlayBtn() {
    btnPlay.textContent = vid.ended ? '重播' : (vid.paused ? '播放' : '暂停');
  }
  vid.addEventListener('play', syncPlayBtn);
  vid.addEventListener('pause', syncPlayBtn);
  vid.addEventListener('ended', syncPlayBtn);
  vid.addEventListener('seeked', updateOverlay);

  btnPlay.onclick = () => {
    if (vid.ended) { vid.currentTime = 0; vid.play().catch(() => {}); return; }
    if (vid.paused) vid.play().catch(() => toast('无法播放', true));
    else vid.pause();
  };

  const step = media.fps ? 1 / media.fps : 1 / 25;
  $('#btnPrevFrame').onclick = () => {
    vid.pause();
    vid.currentTime = Math.max(0, vid.currentTime - step);
  };
  $('#btnNextFrame').onclick = () => {
    vid.pause();
    vid.currentTime = Math.min(vid.duration || 1e9, vid.currentTime + step);
  };

  // 进度条：点击/拖动跳看
  let dragging = false;
  function seekTo(clientX) {
    const r = seek.getBoundingClientRect();
    const pct = Math.min(1, Math.max(0, (clientX - r.left) / r.width));
    const total = durationMs || (vid.duration ? vid.duration * 1000 : 0);
    if (total) vid.currentTime = (pct * total) / 1000;
  }
  seek.addEventListener('mousedown', (e) => { dragging = true; vid.pause(); seekTo(e.clientX); e.preventDefault(); });
  window.addEventListener('mousemove', (e) => { if (dragging) seekTo(e.clientX); });
  window.addEventListener('mouseup', () => { dragging = false; });

  // 报警帧 / 全部处理帧 的快捷跳转
  $$('.chip').forEach((btn) => {
    btn.onclick = () => {
      const ts = btn.dataset.ts;
      if (ts === '') { toast('该帧没有时间戳', true); return; }
      vid.pause();
      vid.currentTime = Number(ts) / 1000;
      fitBox.scrollIntoView({ behavior: 'smooth', block: 'center' });
      // 手动跳转后自动恢复播放，方便连续查看
      setTimeout(() => { vid.play().catch(() => {}); }, 250);
    };
  });

  redraw = () => {
    if (vid.videoWidth) renderFrameBoxes(currentFrame, vid.videoWidth, vid.videoHeight);
  };
  window.addEventListener('resize', () => redraw());
})();
