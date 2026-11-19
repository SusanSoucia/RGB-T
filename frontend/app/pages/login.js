/* 界面 1：登录 */
(async function () {
  // 已登录就不该停在登录页
  if (await redirectIfLoggedIn()) return;

  const form = $('#loginForm');
  form.onsubmit = async (e) => {
    e.preventDefault();
    const errBox = $('#loginErr');
    errBox.innerHTML = '';

    const username = $('#username').value.trim();
    const password = $('#password').value;
    if (!username || !password) {
      errBox.innerHTML = '<div class="form-err">请填写账号和密码</div>';
      return;
    }

    const btn = $('#btnLogin');
    btn.disabled = true;
    btn.textContent = '登录中…';
    try {
      const data = await api('/auth/login', {
        method: 'POST',
        body: { username, password },
      });
      AUTH.token = data.access_token;
      AUTH.user = data.user;
      localStorage.setItem('token', AUTH.token);
      location.replace('tasks.html');
    } catch (err) {
      const msg = err.code === 'AUTH_ACCOUNT_DISABLED'
        ? '账户已被禁用，请联系管理员。'
        : err.message;
      errBox.innerHTML = `<div class="form-err">${esc(msg)}</div>`;
      btn.disabled = false;
      btn.textContent = '登 录';
    }
  };
})();
