/* 界面 2：注册 */
(async function () {
  if (await redirectIfLoggedIn()) return;

  const form = $('#regForm');
  form.onsubmit = async (e) => {
    e.preventDefault();
    const msg = $('#regMsg');
    msg.innerHTML = '';

    const username = $('#rUser').value.trim();
    const password = $('#rPwd').value;
    const display_name = $('#rName').value.trim() || null;

    if (username.length < 3) {
      msg.innerHTML = '<div class="form-err">账号至少 3 个字符</div>';
      return;
    }
    if (password.length < 6) {
      msg.innerHTML = '<div class="form-err">密码至少 6 位</div>';
      return;
    }

    const btn = $('#btnReg');
    btn.disabled = true;
    btn.textContent = '提交中…';
    try {
      await api('/auth/register', { method: 'POST', body: { username, password, display_name } });
      msg.innerHTML = '<div class="form-ok">注册成功，正在跳转登录…</div>';
      setTimeout(() => { location.replace('login.html'); }, 900);
    } catch (err) {
      // 后端默认关闭自主注册（需求 FR-01），给出可操作提示
      const tip = err.code === 'REGISTER_DISABLED'
        ? '本系统不开放自主注册，请联系管理员开通账号。'
        : err.message;
      msg.innerHTML = `<div class="form-err">${esc(tip)}</div>`;
      btn.disabled = false;
      btn.textContent = '注 册';
    }
  };
})();
