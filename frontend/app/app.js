/* ============================================================================
 * 反无人机检测与预警系统 · 前端
 *
 * 设计约束（重要）：
 * 1. 不引入任何框架和构建工具 —— 原生 ES + hash 路由，双击就能跑。
 *    前端组员后续要换 Vue，只需按同样的接口重写，接口契约见 docs/api.md。
 * 2. 前端跑在 5173，后端在 8000，**不同源**：
 *    - 后端已开 CORS（只放行 5173/8000）；
 *    - 取图/取视频必须用带 Authorization 的 fetch 换 blob，
 *      因为 <img>/<video> 的 src 带不了请求头。
 * ========================================================================== */

const API_BASE = localStorage.getItem('apiBase') || `${location.protocol}//${location.hostname}:8000`;

const S = {
  token: localStorage.getItem('token') || '',
  user: null,
  // blob 缓存：path -> objectURL，避免重复拉同一张图
  blobCache: new Map(),
};

const $ = (sel) => document.querySelector(sel);
const view = () => $('#view');

/* ---------------------------------------------------------------- 基础工具 */

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function toast(msg, isErr = false) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast show' + (isErr ? ' err' : '');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => { t.className = 'toast'; }, 3200);
}

/** 毫秒 -> mm:ss 或 h:mm:ss */
function fmtClock(ms, withMs = false) {
  if (ms == null || isNaN(ms)) return '--:--';
  const total = Math.max(0, ms) / 1000;
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = Math.floor(total % 60);
  const frac = Math.floor((total % 1) * 1000);
  const pad = (n, w = 2) => String(n).padStart(w, '0');
  const base = (h > 0 ? `${h}:${pad(m)}` : `${pad(m)}`) + `:${pad(s)}`;
  return withMs ? `${base}.${pad(frac, 3)}` : base;
}

/** 视频总时长的人类可读形式，如 "2分13秒" */
function fmtDuration(ms) {
  if (ms == null || isNaN(ms)) return '—';
  const sec = Math.round(ms / 1000);
  if (sec < 60) return `${sec} 秒`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return s ? `${m} 分 ${s} 秒` : `${m} 分`;
}

function fmtTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function statusTag(status) {
  const map = {
    succeeded: ['ok', '成功'],
    running: ['warn', '执行中'],
    pending: ['warn', '排队中'],
    failed: ['err', '失败'],
    timeout: ['err', '超时'],
  };
  const [cls, label] = map[status] || ['mut', status];
  return `<span class="tag ${cls}">${label}</span>`;
}

/* ---------------------------------------------------------------- HTTP */

async function api(path, { method = 'GET', body, raw = false } = {}) {
  const headers = {};
  if (S.token) headers.Authorization = `Bearer ${S.token}`;
  let payload = body;
  if (body && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  const res = await fetch(API_BASE + '/api' + path, { method, headers, body: payload });

  if (res.status === 401) {
    S.token = '';
    localStorage.removeItem('token');
    S.user = null;
    if (!location.hash.startsWith('#/login')) location.hash = '#/login';
    throw new Error('登录已失效，请重新登录');
  }
  if (raw) {
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res;
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const err = new Error((data && (data.message || data.detail)) || `HTTP ${res.status}`);
    err.code = data && data.code;
    err.status = res.status;
    throw err;
  }
  return data;
}

/**
 * 取二进制资源（图片/视频）并转成 objectURL。
 *
 * 为什么不直接把 URL 塞给 <img src>：
 * 这些接口要求 Authorization 头，而标签发起的请求带不了头，会直接 401。
 */
async function blobUrl(apiPath) {
  if (S.blobCache.has(apiPath)) return S.blobCache.get(apiPath);
  const res = await fetch(API_BASE + '/api' + apiPath, {
    headers: S.token ? { Authorization: `Bearer ${S.token}` } : {},
  });
  if (!res.ok) throw new Error(`资源加载失败 HTTP ${res.status}`);
  const url = URL.createObjectURL(await res.blob());
  S.blobCache.set(apiPath, url);
  return url;
}

function clearBlobCache() {
  for (const url of S.blobCache.values()) URL.revokeObjectURL(url);
  S.blobCache.clear();
}

/* ---------------------------------------------------------------- 布局 */

function renderNav(active) {
  document.querySelectorAll('#nav a').forEach((a) => {
    a.classList.toggle('active', a.dataset.nav === active);
  });
  const showNav = !!S.user;
  $('#nav').style.visibility = showNav ? 'visible' : 'hidden';
  $('#who').textContent = S.user
    ? `${S.user.display_name || S.user.username}（${S.user.role === 'admin' ? '管理员' : '用户'}）`
    : '';
  $('#btnLogout').hidden = !S.user;
}

/* ---------------------------------------------------------------- 登录 */

function viewLogin() {
  renderNav('login');
  view().innerHTML = `
    <div class="auth-wrap">
      <form class="auth-card" id="loginForm">
        <h1>登录</h1>
        <p class="sub">反无人机检测与预警系统</p>

        <label class="fld">账号</label>
        <input type="text" id="username" autocomplete="username" placeholder="请输入用户名" />
        <label class="fld">密码</label>
        <input type="password" id="password" autocomplete="current-password" placeholder="请输入密码" />
        <div id="loginErr"></div>

        <div style="margin-top:18px">
          <button class="btn primary" type="submit" style="width:100%">登 录</button>
        </div>

        <div class="auth-foot">
          <span>还没有账号？</span>
          <button class="btn sm" type="button" id="toRegister">注册</button>
        </div>
      </form>
    </div>`;

  $('#toRegister').onclick = () => { location.hash = '#/register'; };

  $('#loginForm').onsubmit = async (e) => {
    e.preventDefault();
    const errBox = $('#loginErr');
    errBox.innerHTML = '';
    const username = $('#username').value.trim();
    const password = $('#password').value;
    if (!username || !password) {
      errBox.innerHTML = '<div class="form-err">请填写账号和密码</div>';
      return;
    }
    try {
      const data = await api('/auth/login', { method: 'POST', body: { username, password } });
      S.token = data.access_token;
      S.user = data.user;
      localStorage.setItem('token', S.token);
      clearBlobCache();
      toast('登录成功');
      location.hash = '#/tasks';
    } catch (err) {
      errBox.innerHTML = `<div class="form-err">${esc(err.message)}</div>`;
    }
  };
}

/* ---------------------------------------------------------------- 注册 */

function viewRegister() {
  renderNav('register');
  view().innerHTML = `
    <div class="auth-wrap">
      <form class="auth-card" id="regForm">
        <h1>注册</h1>
        <p class="sub">创建普通用户账号</p>

        <label class="fld">账号</label>
        <input type="text" id="rUser" placeholder="3~64 个字符" autocomplete="username" />
        <label class="fld">密码</label>
        <input type="password" id="rPwd" placeholder="至少 6 位" autocomplete="new-password" />
        <label class="fld">显示名称（可选）</label>
        <input type="text" id="rName" placeholder="留空则用账号名" />
        <div id="regMsg"></div>

        <div style="margin-top:18px">
          <button class="btn primary" type="submit" style="width:100%">注 册</button>
        </div>

        <div class="auth-foot">
          <span>已有账号？</span>
          <button class="btn sm" type="button" id="toLogin">返回登录</button>
        </div>
      </form>
    </div>`;

  $('#toLogin').onclick = () => { location.hash = '#/login'; };

  $('#regForm').onsubmit = async (e) => {
    e.preventDefault();
    const msg = $('#regMsg');
    msg.innerHTML = '';
    const username = $('#rUser').value.trim();
    const password = $('#rPwd').value;
    const display_name = $('#rName').value.trim() || null;

    if (username.length < 3) { msg.innerHTML = '<div class="form-err">账号至少 3 个字符</div>'; return; }
    if (password.length < 6) { msg.innerHTML = '<div class="form-err">密码至少 6 位</div>'; return; }

    try {
      await api('/auth/register', { method: 'POST', body: { username, password, display_name } });
      msg.innerHTML = '<div class="form-ok">注册成功，正在跳转登录…</div>';
      setTimeout(() => { location.hash = '#/login'; }, 900);
    } catch (err) {
      // 后端默认关闭自主注册（需求 FR-01），这里给出可操作的提示
      const tip = err.code === 'REGISTER_DISABLED'
        ? '本系统不开放自主注册，请联系管理员开通账号。'
        : err.message;
      msg.innerHTML = `<div class="form-err">${esc(tip)}</div>`;
    }
  };
}

/* ---------------------------------------------------------------- 界面1：检测任务 */

async function viewTasks() {
  renderNav('tasks');
  view().innerHTML = `
    <div class="toolbar">
      <h2 style="margin:0;font-size:16px">检测任务</h2>
      <span class="spacer"></span>
      <button class="btn sm" id="refreshTasks">刷新</button>
    </div>
    <div class="card" style="padding:0">
      <div id="tasksBox"><div class="empty">加载中…</div></div>
    </div>
    <p style="color:#6b7480;font-size:12px">双击任意一行查看该任务的检测详情。</p>`;

  const load = async () => {
    const box = $('#tasksBox');
    box.innerHTML = '<div class="empty">加载中…</div>';
    try {
      const page = await api('/detect-tasks?page=1&page_size=100');
      if (!page.items.length) {
        box.innerHTML = '<div class="empty">还没有检测任务。先在「检测任务 → 上传」里创建，或用 MVP 控制台跑一次检测。</div>';
        return;
      }
      box.innerHTML = `
        <div class="table-wrap">
          <table class="grid">
            <thead>
              <tr>
                <th>ID</th><th>媒体文件</th><th>分辨率</th><th>帧率</th>
                <th>总帧数</th><th>总时长</th><th>模式</th><th>状态</th>
                <th>处理帧数</th><th>耗时</th><th>创建时间</th>
              </tr>
            </thead>
            <tbody>
              ${page.items.map((t) => {
                const m = t.media || {};
                const res = m.width && m.height ? `${m.width}×${m.height}` : '—';
                const fps = m.fps != null ? `${Number(m.fps).toFixed(2)} fps` : '—';
                const frames = m.total_frames != null ? m.total_frames : '—';
                const dur = m.duration_ms != null ? fmtDuration(m.duration_ms) : '—';
                const mode = `${t.requested_mode}${t.actual_mode && t.actual_mode !== t.requested_mode
                  ? ' → ' + t.actual_mode : ''}`;
                return `<tr data-id="${t.id}">
                  <td class="mono">${t.id}</td>
                  <td class="name">${esc(m.original_name || '(未知媒体)')}</td>
                  <td class="mono">${res}</td>
                  <td class="mono">${fps}</td>
                  <td class="mono">${frames}</td>
                  <td class="mono">${dur}</td>
                  <td class="mono">${mode}</td>
                  <td>${statusTag(t.status)}</td>
                  <td class="mono">${t.frames_processed}</td>
                  <td class="mono">${t.elapsed_ms != null ? t.elapsed_ms + ' ms' : '—'}</td>
                  <td class="mono">${fmtTime(t.created_at)}</td>
                </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>`;

      // 双击进入详情（单击不跳，避免误触）
      box.querySelectorAll('tbody tr').forEach((tr) => {
        tr.ondblclick = () => { location.hash = `#/task/${tr.dataset.id}`; };
      });
    } catch (err) {
      box.innerHTML = `<div class="empty">加载失败：${esc(err.message)}</div>`;
    }
  };

  $('#refreshTasks').onclick = load;
  await load();
}

/* ---------------------------------------------------------------- 界面2：检测详情 */

async function viewTaskDetail(taskId) {
  renderNav('tasks');
  view().innerHTML = '<div class="card"><div class="empty">加载中…</div></div>';

  let task, frames, boxesByFrame;
  try {
    task = await api(`/detect-tasks/${taskId}`);
    frames = await api(`/detect-tasks/${taskId}/frames`);
    const allDets = await api(`/detect-tasks/${taskId}/detections`);
    boxesByFrame = new Map();
    for (const d of allDets) {
      if (!boxesByFrame.has(d.frame_index)) boxesByFrame.set(d.frame_index, []);
      boxesByFrame.get(d.frame_index).push(d);
    }
  } catch (err) {
    view().innerHTML = `<div class="card"><div class="empty">加载失败：${esc(err.message)}</div></div>`;
    return;
  }

  const media = task.media || {};
  const isVideo = media.media_type === 'video';
  const hotFrames = frames.filter((f) => f.intrusion_count > 0);
  const stride = media.frame_stride || 1;

  view().innerHTML = `
    <div class="detail-head">
      <a class="back" href="#/tasks">← 返回列表</a>
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
      <div style="margin-top:12px;font-size:13px;color:#495260">
        <b>模式选择原因：</b>${esc(task.decision_reason || '—')}
      </div>
    </div>

    <div class="card">
      <h2>画面与进度</h2>
      <div class="player">
        <div class="media-box">
          <div class="fit" id="fitBox">
            ${isVideo
              ? '<video id="vid" preload="auto" playsinline></video>'
              : '<img class="frame" id="still" alt="检测帧" />'}
            <canvas class="overlay" id="overlay"></canvas>
          </div>
        </div>
      </div>

      ${isVideo ? `
      <div class="seek" id="seek">
        <div class="track"></div>
        <div class="fill" id="seekFill"></div>
        <div class="knob" id="seekKnob"></div>
        ${frames.filter((f) => f.intrusion_count > 0 && f.frame_ts_ms != null).map((f) => {
          const dur = media.duration_ms || 0;
          const pct = dur ? (f.frame_ts_ms / dur) * 100 : 0;
          return `<div class="mark" style="left:${Math.min(100, Math.max(0, pct))}%"
                    title="第 ${f.frame_index} 帧 · 侵入 ${f.intrusion_count} 个"></div>`;
        }).join('')}
      </div>

      <div class="controls">
        <button class="btn sm" id="btnPlay">播放</button>
        <button class="btn sm" id="btnPrevFrame">◀ 上一帧</button>
        <button class="btn sm" id="btnNextFrame">下一帧 ▶</button>
        <span class="time" id="clock">00:00 / ${fmtClock(media.duration_ms || 0)}</span>
        <span class="spacer"></span>
        <span class="frame-badge" id="frameBadge">—</span>
      </div>
      ` : `
      <div class="controls">
        <span class="frame-badge" id="frameBadge">—</span>
        <span class="spacer"></span>
        <span class="time">静态图片（无时间轴）</span>
      </div>
      `}
    </div>

    <div class="card">
      <h2>报警帧（共 ${hotFrames.length} 帧，点击快速跳转）</h2>
      ${hotFrames.length
        ? `<div class="frame-chips">${hotFrames.map((f) =>
            `<button class="chip hot" data-frame="${f.frame_index}" data-ts="${f.frame_ts_ms ?? ''}">
              帧 ${f.frame_index}${f.frame_ts_ms != null ? ' · ' + fmtClock(f.frame_ts_ms) : ''} · 侵入${f.intrusion_count}
             </button>`).join('')}</div>`
        : '<div class="empty" style="padding:18px">该任务没有产生侵入告警。检查是否设置了警戒区域，或目标是否落在区域外。</div>'}
    </div>

    <div class="card">
      <h2>全部处理帧（每 ${stride} 帧一个）</h2>
      <div class="frame-chips">
        ${frames.map((f) => `<button class="chip ${f.intrusion_count ? 'hot' : ''}"
            data-frame="${f.frame_index}" data-ts="${f.frame_ts_ms ?? ''}">
            帧 ${f.frame_index}${f.intrusion_count ? ' ⚠' : ''}</button>`).join('') || '<span style="color:#6b7480">无</span>'}
      </div>
    </div>`;

  const fitBox = $('#fitBox');
  const overlay = $('#overlay');
  const badge = $('#frameBadge');

  /** 在 canvas 上按"视频实际显示区域"换算并绘制框（考虑留黑边） */
  function drawBoxes(boxes, natW, natH) {
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
    for (const b of boxes) {
      const x = ox + b.x1 * dw, y = oy + b.y1 * dh;
      const w = (b.x2 - b.x1) * dw, h = (b.y2 - b.y1) * dh;
      const inside = b._inside;
      ctx.strokeStyle = inside ? '#ef4444' : '#22c55e';
      ctx.strokeRect(x, y, w, h);
      const label = b.score.toFixed(2) + (inside ? ' 侵入' : '');
      const tw = ctx.measureText(label).width;
      ctx.fillStyle = inside ? 'rgba(239,68,68,.85)' : 'rgba(34,197,94,.85)';
      ctx.fillRect(x, Math.max(0, y - 15), tw + 8, 15);
      ctx.fillStyle = '#fff';
      ctx.fillText(label, x + 4, Math.max(11, y - 4));
    }
  }

  /** 判断每个框的中心是否落在任一区域里（仅用于染色，后端已算过告警） */
  function markInside(boxes, frameIndex) {
    // MVP 阶段前端不做几何判定，直接复用后端结论：
    // 该帧 intrusion_count > 0 时，把第一个框标红即可（详细归属以后端为准）
    const f = frames.find((x) => x.frame_index === frameIndex);
    const hot = f && f.intrusion_count > 0;
    return boxes.map((b, i) => ({ ...b, _inside: hot && i === 0 }));
  }

  function showFrame(frameIndex) {
    const boxes = boxesByFrame.get(frameIndex) || [];
    const f = frames.find((x) => x.frame_index === frameIndex);
    badge.textContent = `帧 ${frameIndex} · 目标 ${boxes.length} 个` +
      (f && f.intrusion_count ? ` · 侵入 ${f.intrusion_count}` : '');
    return markInside(boxes, frameIndex);
  }

  // ---------- 静态图片 ----------
  if (!isVideo) {
    const still = $('#still');
    try {
      const first = frames[0];
      const idx = first ? first.frame_index : 0;
      still.src = await blobUrl(`/media/${task.media_id}/frames/${idx}`);
      still.onload = () => {
        const boxes = showFrame(idx);
        drawBoxes(boxes, still.naturalWidth, still.naturalHeight);
      };
    } catch (err) {
      fitBox.innerHTML = `<div class="empty" style="color:#aab">${esc(err.message)}</div>`;
    }
    window.addEventListener('resize', () => {
      if (still.naturalWidth) {
        const boxes = showFrame(frames[0] ? frames[0].frame_index : 0);
        drawBoxes(boxes, still.naturalWidth, still.naturalHeight);
      }
    }, { once: true });
    return;
  }

  // ---------- 视频 ----------
  const vid = $('#vid');
  const seek = $('#seek');
  const fill = $('#seekFill');
  const knob = $('#seekKnob');
  const clock = $('#clock');
  const btnPlay = $('#btnPlay');
  let durationMs = media.duration_ms || 0;
  let currentFrame = frames.length ? frames[0].frame_index : 0;

  badge.textContent = '正在加载视频…';
  try {
    vid.src = await blobUrl(`/media/${task.media_id}/video`);
  } catch (err) {
    fitBox.innerHTML = `<div class="empty" style="color:#aab">视频加载失败：${esc(err.message)}</div>`;
    return;
  }

  /** 视频放不出来时给出可操作的提示，而不是一直显示"正在加载" */
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

  // 6 秒内拿不到元数据就认为解不了，避免无限等待
  const watchdog = setTimeout(() => {
    if (!vid.videoWidth) showVideoError('加载超时（无法解析视频头）。');
  }, 6000);
  vid.addEventListener('error', () => {
    clearTimeout(watchdog);
    showVideoError('视频解码失败。');
  }, { once: true });

  /** 找时间上最接近当前播放位置的"已处理帧" */
  function nearestFrame(ms) {
    let best = frames[0], bestD = Infinity;
    for (const f of frames) {
      if (f.frame_ts_ms == null) continue;
      const d = Math.abs(f.frame_ts_ms - ms);
      if (d < bestD) { bestD = d; best = f; }
    }
    return best;
  }

  function updateOverlay() {
    if (!vid.videoWidth) return;
    const f = nearestFrame(vid.currentTime * 1000);
    if (!f) return;
    if (f.frame_index !== currentFrame || overlay.width === 0) {
      currentFrame = f.frame_index;
      const boxes = showFrame(f.frame_index);
      drawBoxes(boxes, vid.videoWidth, vid.videoHeight);
    }
  }

  function updateProgress() {
    const total = durationMs || (vid.duration ? vid.duration * 1000 : 0);
    const pct = total ? Math.min(100, (vid.currentTime * 1000 / total) * 100) : 0;
    fill.style.width = pct + '%';
    knob.style.left = pct + '%';
    clock.textContent = `${fmtClock(vid.currentTime * 1000)} / ${fmtClock(total)}`;
  }

  vid.addEventListener('loadedmetadata', () => {
    clearTimeout(watchdog);
    if (!durationMs && vid.duration) durationMs = vid.duration * 1000;
    clock.textContent = `00:00 / ${fmtClock(durationMs)}`;
    updateProgress();
    updateOverlay();
  });
  vid.addEventListener('timeupdate', () => { updateProgress(); updateOverlay(); });
  vid.addEventListener('play', () => { btnPlay.textContent = '暂停'; });
  vid.addEventListener('pause', () => { btnPlay.textContent = '播放'; });
  vid.addEventListener('ended', () => { btnPlay.textContent = '播放'; });
  vid.addEventListener('seeked', updateOverlay);

  btnPlay.onclick = () => {
    if (vid.paused) vid.play().catch(() => toast('无法播放（浏览器可能不支持该编码）', true));
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

  // 报警帧快速跳转
  document.querySelectorAll('.chip').forEach((btn) => {
    btn.onclick = () => {
      const ts = btn.dataset.ts;
      if (ts === '') { toast('该帧没有时间戳（静态图或解析异常）', true); return; }
      vid.pause();
      vid.currentTime = Number(ts) / 1000;
      vid.scrollIntoView({ behavior: 'smooth', block: 'center' });
    };
  });

  window.addEventListener('resize', () => {
    if (vid.videoWidth) {
      const boxes = showFrame(currentFrame);
      drawBoxes(boxes, vid.videoWidth, vid.videoHeight);
    }
  }, { once: true });
}

/* ---------------------------------------------------------------- 界面3：报警情况 */

async function viewAlerts() {
  renderNav('alerts');
  view().innerHTML = `
    <div class="toolbar">
      <h2 style="margin:0;font-size:16px">报警情况</h2>
      <span class="spacer"></span>
      <select id="alertFilter" class="btn sm" style="padding:6px 8px">
        <option value="">全部状态</option>
        <option value="unconfirmed">未确认</option>
        <option value="confirmed">已确认</option>
      </select>
      <button class="btn sm" id="refreshAlerts">刷新</button>
    </div>
    <div id="alertsBox"><div class="card"><div class="empty">加载中…</div></div></div>`;

  const load = async () => {
    const box = $('#alertsBox');
    box.innerHTML = '<div class="card"><div class="empty">加载中…</div></div>';
    const status = $('#alertFilter').value;
    try {
      const page = await api(`/alerts?page=1&page_size=60${status ? '&status=' + status : ''}`);
      if (!page.items.length) {
        box.innerHTML = '<div class="card"><div class="empty">暂无报警记录。</div></div>';
        return;
      }
      box.innerHTML = `<div class="gallery">${page.items.map((a) => `
        <div class="thumb-card" data-task="${a.task_id}" data-frame="${a.frame_index}">
          <div class="thumb" data-src="${a.snapshot_url || ''}">
            <span class="ph">加载缩略图…</span>
          </div>
          <div class="info">
            <div class="t1">
              <span>${esc(a.media_name || '媒体 ' + a.media_id)}</span>
              <span>帧 ${a.frame_index}</span>
            </div>
            <div class="t2">${fmtTime(a.first_seen_at)}</div>
            <div class="t1" style="margin-top:4px">
              <span>分数 ${a.score_max.toFixed(3)}</span>
              <span>×${a.occurrence_count}</span>
            </div>
            <div class="row2">
              ${a.status === 'confirmed'
                ? '<span class="tag ok">已确认</span>'
                : '<span class="tag warn">未确认</span>'}
              ${a.status === 'confirmed'
                ? ''
                : `<button class="btn sm" data-confirm="${a.id}">确认</button>`}
            </div>
          </div>
        </div>`).join('')}</div>`;

      // 卡片点击 → 详情页对应帧；确认按钮单独处理
      box.querySelectorAll('.thumb-card').forEach((card) => {
        card.onclick = (e) => {
          if (e.target.closest('[data-confirm]')) return;
          location.hash = `#/task/${card.dataset.task}`;
        };
      });
      box.querySelectorAll('[data-confirm]').forEach((btn) => {
        btn.onclick = async (e) => {
          e.stopPropagation();
          try {
            await api(`/alerts/${btn.dataset.confirm}/confirm`, { method: 'POST' });
            toast('已确认');
            await load();
          } catch (err) {
            toast(err.message, true);
          }
        };
      });

      // 缩略图逐张异步加载（带 token 的 fetch → blob）
      box.querySelectorAll('.thumb').forEach(async (el) => {
        const src = el.dataset.src;
        if (!src) { el.innerHTML = '<span class="ph">无截图</span>'; return; }
        try {
          const url = await blobUrl(src);
          el.innerHTML = `<img alt="报警帧" src="${url}" />`;
        } catch {
          el.innerHTML = '<span class="ph">截图加载失败</span>';
        }
      });
    } catch (err) {
      box.innerHTML = `<div class="card"><div class="empty">加载失败：${esc(err.message)}</div></div>`;
    }
  };

  $('#refreshAlerts').onclick = load;
  $('#alertFilter').onchange = load;
  await load();
}

/* ---------------------------------------------------------------- 路由 */

function parseHash() {
  const h = location.hash.replace(/^#/, '') || '/tasks';
  const parts = h.split('/').filter(Boolean);
  return { path: '/' + (parts[0] || ''), arg: parts[1] };
}

async function boot() {
  $('#btnLogout').onclick = async () => {
    try { await api('/auth/logout', { method: 'POST' }); } catch { /* 忽略 */ }
    S.token = '';
    S.user = null;
    localStorage.removeItem('token');
    clearBlobCache();
    location.hash = '#/login';
  };

  if (S.token) {
    try { S.user = await api('/auth/me'); } catch { S.token = ''; localStorage.removeItem('token'); }
  }

  const route = () => {
    const { path, arg } = parseHash();
    const needAuth = !['/login', '/register'].includes(path);
    if (needAuth && !S.token) { location.hash = '#/login'; return; }
    if (!needAuth && S.token && path === '/login') { location.hash = '#/tasks'; return; }

    switch (path) {
      case '/login': return viewLogin();
      case '/register': return viewRegister();
      case '/tasks': return viewTasks();
      case '/task': return viewTaskDetail(arg);
      case '/alerts': return viewAlerts();
      default: location.hash = S.token ? '#/tasks' : '#/login';
    }
  };

  window.addEventListener('hashchange', route);
  if (!location.hash) location.hash = S.token ? '#/tasks' : '#/login';
  route();
}

boot();
