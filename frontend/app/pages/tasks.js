/* 业务界面 1：检测任务列表 */
(async function () {
  await requireAuth();
  mountTopbar('tasks');

  const box = $('#tasksBox');

  async function load() {
    box.innerHTML = '<div class="empty">加载中…</div>';
    try {
      const page = await api('/detect-tasks?page=1&page_size=100');
      if (!page.items.length) {
        box.innerHTML = '<div class="empty">还没有检测任务。先到「检测任务 → 上传」或用 MVP 控制台跑一次检测。</div>';
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
              ${page.items.map(rowHtml).join('')}
            </tbody>
          </table>
        </div>`;

      // 双击进入详情（单击不跳，避免误触）
      $$('tbody tr', box).forEach((tr) => {
        tr.ondblclick = () => { location.href = `task.html?id=${tr.dataset.id}`; };
      });
    } catch (err) {
      box.innerHTML = `<div class="empty">加载失败：${esc(err.message)}</div>`;
    }
  }

  function rowHtml(t) {
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
  }

  $('#refreshTasks').onclick = load;
  await load();
})();
