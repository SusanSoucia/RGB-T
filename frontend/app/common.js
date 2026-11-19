/* ============================================================================
 * 公共逻辑：所有页面都先加载这个文件。
 *
 * 架构说明（重要）：
 * 本站是**多页应用（MPA）**，每个界面是一个独立的 HTML，各有自己的 URL：
 *
 *     index.html      → 判断登录态后跳转
 *     login.html      → 登录
 *     register.html   → 注册
 *     tasks.html      → 检测任务列表
 *     task.html?id=17 → 检测详情（视频播放 / 进度 / 报警帧）
 *     alerts.html     → 报警情况
 *
 * 页面之间用普通 <a href> 跳转，不依赖 hash 路由。
 * 共用的东西只放在这里：请求封装、鉴权、取图、格式化、顶栏。
 *
 * 两个必须遵守的约束：
 * 1. 取图/取视频必须用带 token 的 fetch 换 blob —— <img>/<video> 的 src
 *    带不了 Authorization 头，直连会 401。
 * 2. 前端跑在 5173、后端在 8000，属于跨域，后端已开 CORS（只放行这两个来源）。
 * ========================================================================== */

const API_BASE =
  localStorage.getItem('apiBase') || `${location.protocol}//${location.hostname}:8000`;

const AUTH = {
  token: localStorage.getItem('token') || '',
  user: null,
};

// blob 缓存：接口路径 -> objectURL，避免重复拉同一张图
const BLOB_CACHE = new Map();

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/* ---------------------------------------------------------------- 格式化 */

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function toast(msg, isErr = false) {
  let t = $('#toast');
  if (!t) {
    t = document.createElement('div');
    t.id = 'toast';
    t.className = 'toast';
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.className = 'toast show' + (isErr ? ' err' : '');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => { t.className = 'toast'; }, 3200);
}

/** 毫秒 → mm:ss（可选带毫秒） */
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

/** 时长的人类可读形式，如 "2 分 13 秒" */
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

async function api(path, { method = 'GET', body } = {}) {
  const headers = {};
  if (AUTH.token) headers.Authorization = `Bearer ${AUTH.token}`;
  let payload = body;
  if (body && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  const res = await fetch(API_BASE + '/api' + path, { method, headers, body: payload });

  if (res.status === 401) {
    logoutLocal();
    location.replace('login.html');
    throw new Error('登录已失效');
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

/** 带鉴权取二进制并转 objectURL（图片/视频都必须走这里） */
async function blobUrl(apiPath) {
  if (BLOB_CACHE.has(apiPath)) return BLOB_CACHE.get(apiPath);
  const res = await fetch(API_BASE + '/api' + apiPath, {
    headers: AUTH.token ? { Authorization: `Bearer ${AUTH.token}` } : {},
  });
  if (!res.ok) throw new Error(`资源加载失败 HTTP ${res.status}`);
  const url = URL.createObjectURL(await res.blob());
  BLOB_CACHE.set(apiPath, url);
  return url;
}

function clearBlobCache() {
  for (const url of BLOB_CACHE.values()) URL.revokeObjectURL(url);
  BLOB_CACHE.clear();
}

/** 本地登出：清 token + 清 blob 缓存。注意和 clearBlobCache 分开，
 *  否则登录成功时调清缓存会把刚存进去的 token 也删掉。 */
function logoutLocal() {
  AUTH.token = '';
  AUTH.user = null;
  localStorage.removeItem('token');
  clearBlobCache();
}

/* ---------------------------------------------------------------- 鉴权与顶栏 */

/**
 * 页面入口第一步：确认登录态。
 * 未登录直接 replace 到 login.html（用 replace 避免"后退"回到受保护页面）。
 */
async function requireAuth() {
  if (!AUTH.token) {
    location.replace('login.html');
    throw new Error('未登录');
  }
  try {
    AUTH.user = await api('/auth/me');
    return AUTH.user;
  } catch (err) {
    location.replace('login.html');
    throw err;
  }
}

/** 注入顶栏。active: logs | tasks | alerts */
function mountTopbar(active) {
  const host = $('#topbar');
  if (!host) return;
  const user = AUTH.user;
  host.innerHTML = `
    <header class="topbar">
      <div class="brand"><span class="logo">◤◢</span><span>反无人机检测与预警系统</span></div>
      <nav class="nav">
        <a href="tasks.html" class="${active === 'tasks' ? 'active' : ''}">检测任务</a>
        <a href="alerts.html" class="${active === 'alerts' ? 'active' : ''}">报警情况</a>
        <a href="upload.html" class="${active === 'upload' ? 'active' : ''}">上传素材</a>
      </nav>
      <div class="topbar-right">
        <span class="who">${user
          ? esc(`${user.display_name || user.username}（${user.role === 'admin' ? '管理员' : '用户'}）`)
          : ''}</span>
        <button class="btn ghost sm" id="btnLogout">退出</button>
      </div>
    </header>`;

  $('#btnLogout').onclick = async () => {
    try { await api('/auth/logout', { method: 'POST' }); } catch { /* 忽略 */ }
    logoutLocal();
    location.replace('login.html');
  };
}

/** 未登录页面（login/register）用：已登录就直接进业务页 */
async function redirectIfLoggedIn() {
  if (!AUTH.token) return false;
  try {
    AUTH.user = await api('/auth/me');
    location.replace('tasks.html');
    return true;
  } catch {
    AUTH.token = '';
    localStorage.removeItem('token');
    return false;
  }
}

/** 从 URL 取查询参数，如 task.html?id=17 */
function queryParam(name) {
  return new URLSearchParams(location.search).get(name);
}
