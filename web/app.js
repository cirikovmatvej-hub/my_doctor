/* Мой Доктор — веб-версия бота. Тот же набор разделов и тот же чат с кнопками,
   что и в Telegram; данные берутся из того же API. Любой текст с сервера
   вставляется как текст (textContent) — разметка из строк не собирается. */
(() => {
  'use strict';

  const TOKEN_KEY = 'md_token';
  const $ = (id) => document.getElementById(id);

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode: stay signed in for this tab only */ } },
    del(k) { try { localStorage.removeItem(k); } catch { /* ignore */ } },
  };

  let token = store.get(TOKEN_KEY);
  let me = null;

  // ── Small helpers ────────────────────────────────────────────────────────

  function el(tag, props = {}, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === 'class') n.className = v;
      else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v);
    }
    n.append(...kids);
    return n;
  }

  /** "**bold**" → <strong>, everything else plain text. */
  function rich(text) {
    const frag = document.createDocumentFragment();
    String(text).split('**').forEach((part, i) => {
      if (!part) return;
      if (i % 2) frag.append(el('strong', {}, part));
      else frag.append(document.createTextNode(part));
    });
    return frag;
  }

  function safeUrl(u) {
    try {
      const x = new URL(u);
      return x.protocol === 'https:' || x.protocol === 'http:' ? x.href : null;
    } catch { return null; }
  }

  const pad = (n) => String(n).padStart(2, '0');
  function localDate(d = new Date()) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }
  function fmtDate(iso) { const [y, m, d] = String(iso).slice(0, 10).split('-'); return `${d}.${m}.${y}`; }

  // ── API ──────────────────────────────────────────────────────────────────

  class ApiError extends Error {
    constructor(status, message) { super(message); this.status = status; }
  }

  function errorText(data, status) {
    const d = data && data.detail;
    if (typeof d === 'string') return d;
    if (Array.isArray(d)) return 'Проверьте введённые данные.';
    if (status >= 500) return 'Что-то пошло не так на сервере. Попробуйте позже.';
    return 'Не удалось выполнить запрос.';
  }

  async function api(path, { method = 'GET', body } = {}) {
    const headers = {};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (token) headers.Authorization = `Bearer ${token}`;
    let res;
    try {
      res = await fetch(path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
    } catch {
      throw new ApiError(0, 'Нет соединения. Проверьте интернет и попробуйте ещё раз.');
    }
    let data = null;
    try { data = await res.json(); } catch { /* empty body */ }
    if (!res.ok) {
      if (res.status === 401 && token && !path.startsWith('/auth/')) logout(true);
      throw new ApiError(res.status, errorText(data, res.status));
    }
    return data;
  }

  // ── Chat primitives ──────────────────────────────────────────────────────

  const msgs = $('messages');
  const input = $('composer-input');
  const sendBtn = $('composer-send');
  let flowId = 0;
  let textHandler = null;

  function scrollDown() { msgs.scrollTop = msgs.scrollHeight; }

  function addMsg(role, content, cls = '') {
    const m = el('div', { class: `msg ${role} ${cls}`.trim() });
    if (typeof content === 'string') m.append(rich(content));
    else if (content) m.append(content);
    msgs.append(m);
    scrollDown();
    return m;
  }
  const say = (text, cls) => addMsg('bot', text, cls);
  const sayUser = (text) => addMsg('user', text);

  function typing() {
    const m = addMsg('bot', el('span', { class: 'typing', 'aria-label': 'Печатает' }, el('i'), el('i'), el('i')));
    return () => m.remove();
  }

  function reportError(e) {
    say(`⚠️ ${e instanceof ApiError ? e.message : 'Что-то пошло не так. Попробуйте ещё раз.'}`, 'notice');
  }

  function stopText() {
    textHandler = null;
    input.disabled = true;
    sendBtn.disabled = true;
    input.value = '';
    input.placeholder = 'Выберите действие в меню ниже';
  }

  function awaitText(placeholder, handler) {
    textHandler = handler;
    input.disabled = false;
    sendBtn.disabled = false;
    input.placeholder = placeholder;
    input.value = '';
    input.focus({ preventScroll: true });
  }

  function newFlow() { flowId += 1; stopText(); return flowId; }

  $('composer').addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || !textHandler) return;
    input.value = '';
    sayUser(text);
    try { await textHandler(text); } catch (err) { reportError(err); }
  });

  /**
   * Inline keyboard under a bubble. rows: [[{label, onClick | href, danger}]].
   * Default: after a click the other buttons lock and the chosen one gets a ✓
   * (like picking in Telegram). `sticky` keeps everything live (repeatable
   * actions). `flow` ties it to the flow that created it, so a stale menu from
   * an earlier screen can't act on the current one.
   */
  function keyboard(msg, rows, { flow, sticky = false } = {}) {
    const kb = el('div', { class: 'ikb' });
    const buttons = [];
    rows.forEach((row) => {
      const r = el('div', { class: 'irow' });
      row.forEach((b) => {
        if (b.href) {
          const u = safeUrl(b.href);
          if (u) r.append(el('a', { class: 'ibtn', href: u, target: '_blank', rel: 'noopener noreferrer' }, b.label));
          return;
        }
        const btn = el('button', { class: `ibtn${b.danger ? ' danger' : ''}`, type: 'button' }, b.label);
        buttons.push(btn);
        btn.addEventListener('click', async () => {
          if (flow !== undefined && flow !== flowId) { btn.textContent = 'Устарело'; btn.disabled = true; return; }
          if (!sticky) buttons.forEach((x) => { x.disabled = true; });
          try {
            await b.onClick(btn);
            if (!sticky) btn.textContent = `✓ ${b.label}`;
          } catch (e) {
            reportError(e);
            if (!sticky) buttons.forEach((x) => { x.disabled = false; });
          }
        });
        r.append(btn);
      });
      if (r.children.length) kb.append(r);
    });
    msg.append(kb);
    scrollDown();
    return kb;
  }

  async function run(fn) { try { await fn(); } catch (e) { reportError(e); } }

  // ── Sign-in ──────────────────────────────────────────────────────────────

  const emailForm = $('email-form');
  const codeForm = $('code-form');
  const emailInput = $('email');
  const consent = $('consent');
  const codeInput = $('code');
  const loginError = $('login-error');
  let resendTimer = null;
  let loginEmail = '';

  const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/;

  function showLoginError(text) { loginError.textContent = text; loginError.hidden = !text; }

  function syncLoginButtons() {
    $('send-code').disabled = !(EMAIL_RE.test(emailInput.value.trim()) && consent.checked);
    $('verify-code').disabled = codeInput.value.length !== 6;
  }

  function startResendCountdown(seconds = 60) {
    clearInterval(resendTimer);
    const btn = $('resend');
    let left = seconds;
    const tick = () => {
      btn.disabled = left > 0;
      btn.textContent = left > 0 ? `Отправить ещё раз (${left})` : 'Отправить ещё раз';
      left -= 1;
      if (left < 0) clearInterval(resendTimer);
    };
    tick();
    resendTimer = setInterval(tick, 1000);
  }

  function resetLoginForm() {
    clearInterval(resendTimer);
    codeForm.hidden = true;
    emailForm.hidden = false;
    codeInput.value = '';
    showLoginError('');
    syncLoginButtons();
  }

  function showLogin() {
    $('chat').hidden = true;
    $('login').hidden = false;
    resetLoginForm();
  }

  function logout(expired = false) {
    token = null;
    me = null;
    store.del(TOKEN_KEY);
    flowId += 1;
    stopText();
    showLogin();
    if (expired) showLoginError('Сессия истекла. Войдите снова.');
  }

  async function requestCode() {
    showLoginError('');
    const email = emailInput.value.trim();
    $('send-code').disabled = true;
    try {
      await api('/auth/email/request', { method: 'POST', body: { email } });
    } catch (e) {
      showLoginError(e.message);
      // "code already sent" — a valid code may exist, so let them enter it.
      if (e.status !== 429) { syncLoginButtons(); return; }
    }
    loginEmail = email;
    $('sent-to').textContent = email;
    emailForm.hidden = true;
    codeForm.hidden = false;
    codeInput.value = '';
    startResendCountdown(60);
    codeInput.focus();
    syncLoginButtons();
  }

  emailForm.addEventListener('submit', (e) => { e.preventDefault(); if (!$('send-code').disabled) requestCode(); });
  emailInput.addEventListener('input', syncLoginButtons);
  consent.addEventListener('change', syncLoginButtons);

  codeInput.addEventListener('input', () => {
    codeInput.value = codeInput.value.replace(/\D/g, '').slice(0, 6);
    syncLoginButtons();
  });

  codeForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if ($('verify-code').disabled) return;
    showLoginError('');
    $('verify-code').disabled = true;
    try {
      const r = await api('/auth/email/verify', { method: 'POST', body: { email: loginEmail, code: codeInput.value } });
      token = r.access_token;
      store.set(TOKEN_KEY, token);
      await boot();
    } catch (err) {
      showLoginError(err.message);
      codeInput.select();
      syncLoginButtons();
    }
  });

  $('resend').addEventListener('click', async () => {
    showLoginError('');
    $('resend').disabled = true;
    try {
      await api('/auth/email/request', { method: 'POST', body: { email: loginEmail } });
      startResendCountdown(60);
    } catch (e) {
      showLoginError(e.message);
      startResendCountdown(30);
    }
  });

  $('change-email').addEventListener('click', resetLoginForm);

  // ── Main menu ────────────────────────────────────────────────────────────

  const MENU = [
    ['🤖 Консультация с ИИ', () => startConsultation(), 'wide'],
    ['💊 Подбор БАД', () => startAdvisor()],
    ['📊 Мой трекер', () => showTracker()],
    ['📔 Дневник', () => showDiary()],
    ['📋 История', () => showHistory()],
    ['👨‍👩‍👧 Семья', () => showFamily()],
    ['⚙️ Мой профиль', () => showProfile()],
  ];
  const menu = $('menu');
  MENU.forEach(([label, fn, cls]) => {
    menu.append(el('button', {
      type: 'button', class: cls || '',
      onclick: () => { sayUser(label); newFlow(); run(fn); },
    }, label));
  });
  const setMenuVisible = (v) => { menu.hidden = !v; };

  const WELCOME =
    '👋 Привет! Я **Мой Доктор** — ваш персональный помощник по здоровью.\n\n' +
    'Что я умею:\n' +
    '🤖 **Консультация с ИИ** — отвечу на вопросы о здоровье и помогу разобраться\n' +
    '💊 **Подбор БАД** — безопасные рекомендации под вашу цель\n' +
    '📊 **Трекер курса** — помогу вести курс приёма добавок и отмечать приёмы\n' +
    '📔 **Дневник** — слежу за вашим самочувствием в динамике\n\n' +
    '⚠️ Важно: я не ставлю диагнозы и не заменяю очного врача.';

  async function boot() {
    $('login').hidden = true;
    $('chat').hidden = false;
    msgs.replaceChildren();
    newFlow();
    try {
      me = await api('/me');
    } catch (e) {
      if (e.status !== 401) { showLogin(); showLoginError(e.message); }
      return;
    }
    say(WELCOME);
    if (!me.gender || !me.age_range) { setMenuVisible(false); beginOnboarding(); }
    else if (!me.onboarding_done) { setMenuVisible(false); startQuestionnaire('me'); }
    else { setMenuVisible(true); say('Выберите действие 👇'); }
  }

  // ── Profile questionnaire (same questions and answers as the bot) ────────

  const GENDERS = [['male', '👨 Мужской'], ['female', '👩 Женский']];
  const AGES = [['under_18', 'До 18 лет'], ['18_30', '18–30 лет'], ['31_45', '31–45 лет'], ['46_60', '46–60 лет'], ['60_plus', '60+ лет']];
  const GENDER_LABEL = { male: 'Мужской', female: 'Женский' };
  const AGE_LABEL = { under_18: 'до 18 лет', '18_30': '18–30 лет', '31_45': '31–45 лет', '46_60': '46–60 лет', '60_plus': '60+ лет' };
  const PREGNANCY_LABEL = { pregnant: 'беременность', lactating: 'лактация', no: 'нет' };
  const SMOKING_LABEL = { never: 'не курит', former: 'бросил(а)', light: 'курит изредка', heavy: 'курит регулярно' };
  const ALCOHOL_LABEL = { never: 'не употребляет', rarely: 'редко', moderate: 'умеренно', frequent: 'часто' };
  const ACTIVITY_LABEL = {
    sedentary: 'сидячий образ жизни', light: 'лёгкая активность',
    moderate: 'умеренная активность', high: 'высокая активность',
  };

  const NONE = 'Нет';
  const QUESTIONS = [
    { key: 'chronic_diseases', icon: '1️⃣', title: 'Хронические заболевания?', hint: 'Диабет, гипертония, заболевания почек, сердца, щитовидной железы…', kind: 'text', none: NONE, value: 'нет' },
    { key: 'allergies', icon: '2️⃣', title: 'Аллергии?', hint: 'Лекарственные, пищевые, на пыльцу, латекс…', kind: 'text', none: NONE, value: 'нет' },
    { key: 'medications', icon: '3️⃣', title: 'Постоянно принимаемые лекарства?', hint: 'Гормоны, антикоагулянты, антидепрессанты, антибиотики…', kind: 'text', none: NONE, value: 'нет' },
    {
      key: 'pregnancy', icon: '4️⃣', title: 'Беременность или лактация?', kind: 'choice', femaleOnly: true,
      options: [['pregnant', '🤰 Да, беременна'], ['lactating', '🤱 Лактация'], ['no', '❌ Нет / Не применимо']],
    },
    { key: 'past_surgeries', icon: '5️⃣', title: 'Перенесённые операции или госпитализации?', hint: 'Операции на сердце, ЖКТ, суставах; серьёзные травмы…', kind: 'text', none: NONE, value: 'нет' },
    { key: 'hereditary_diseases', icon: '6️⃣', title: 'Наследственные заболевания в семье?', hint: 'Диабет, рак, болезни сердца, инсульт у близких родственников…', kind: 'text', none: NONE, value: 'нет' },
    {
      key: 'smoking', icon: '7️⃣', title: 'Курение?', kind: 'choice',
      options: [['never', '🚭 Не курю'], ['former', '🕰 Бросил(а)'], ['light', '🚬 Иногда (до 5/день)'], ['heavy', '🚬 Регулярно (5+/день)']],
    },
    {
      key: 'alcohol', icon: '8️⃣', title: 'Алкоголь?', kind: 'choice',
      options: [['never', '🚫 Не употребляю'], ['rarely', '🥂 Редко (по праздникам)'], ['moderate', '🍷 Умеренно (1–2р/нед)'], ['frequent', '🍺 Часто (почти каждый день)']],
    },
    {
      key: 'physical_activity', icon: '9️⃣', title: 'Уровень физической активности?', kind: 'choice',
      options: [['sedentary', '🛋 Сидячий (почти нет движения)'], ['light', '🚶 Лёгкая (прогулки, зарядка)'], ['moderate', '🏃 Умеренная (3–4 тренировки/нед)'], ['high', '💪 Высокая (ежедневные нагрузки)']],
    },
    { key: 'height_weight', icon: '🔟', title: 'Рост и вес?', hint: 'Например: 175 / 70', kind: 'text', none: 'Пропустить', value: 'не указано' },
  ];
  const MAX_ANSWER = 500;

  /** Gender, then age, then onCompleted(gender, age). */
  function askGenderAge(flow, onCompleted) {
    const m = say('👤 **Укажите пол:**');
    keyboard(m, [GENDERS.map(([k, label]) => ({
      label,
      onClick: () => {
        const m2 = say(`👤 Пол: **${GENDER_LABEL[k]}**\n\n📅 **Укажите возраст:**`);
        const btn = ([a, label2]) => ({
          label: label2,
          onClick: () => {
            say(`📅 Возраст: **${AGE_LABEL[a]}**`);
            onCompleted(k, a);
          },
        });
        keyboard(m2, [AGES.slice(0, 2).map(btn), AGES.slice(2, 4).map(btn), AGES.slice(4).map(btn)], { flow });
      },
    }))], { flow });
  }

  /** Runs the health questionnaire; calls onDone(answers) with the bot's stored values. */
  function runQuestionnaire(flow, gender, onDone) {
    const qs = QUESTIONS.filter((q) => !(q.femaleOnly && gender !== 'female'));
    const total = gender === 'female' ? 10 : 9;
    const answers = {};
    let current = -1;

    const step = (i) => {
      if (flow !== flowId) return;
      current = i;
      if (i >= qs.length) { stopText(); onDone(answers); return; }
      const q = qs[i];
      const orig = QUESTIONS.indexOf(q) + 1;
      const n = gender === 'female' || orig <= 4 ? orig : orig - 1;   // men skip question 4
      const text = `${q.icon} **${q.title}** (${n}/${total})` +
        (q.hint ? `\n${q.hint}` : '') +
        (q.kind === 'text' ? `\n\nНапишите или нажмите «${q.none}».` : '');
      const m = say(text);

      if (q.kind === 'choice') {
        stopText();
        keyboard(m, q.options.map(([k, label]) => [{
          label, onClick: () => { if (current === i) { answers[q.key] = k; step(i + 1); } },
        }]), { flow });
      } else {
        keyboard(m, [[{
          label: q.none,
          onClick: () => { if (current === i) { answers[q.key] = q.value; step(i + 1); } },
        }]], { flow });
        awaitText('Ваш ответ…', (t) => {
          if (current !== i) return;
          answers[q.key] = t.slice(0, MAX_ANSWER);
          step(i + 1);
        });
      }
    };
    step(0);
  }

  function beginOnboarding() {
    const flow = newFlow();
    say('👤 Прежде чем начать — несколько коротких вопросов.');
    askGenderAge(flow, (gender, age) => {
      say('🏥 **Анкета здоровья**\nЗаполняется один раз. Помогает давать безопасные и точные рекомендации.');
      runQuestionnaire(flow, gender, (answers) => saveMyProfile(gender, age, answers));
    });
  }

  function startQuestionnaire() {
    const flow = newFlow();
    say('🏥 **Анкета здоровья**\nЗаполняется один раз. Помогает давать безопасные и точные рекомендации.');
    runQuestionnaire(flow, me.gender, (answers) => saveMyProfile(me.gender, me.age_range, answers));
  }

  async function saveMyProfile(gender, age, answers) {
    try {
      me = await api('/me/profile', { method: 'PUT', body: { gender, age_range: age, ...answers } });
    } catch (e) {
      reportError(e);
      say('Анкету не удалось сохранить. Откройте «⚙️ Мой профиль», чтобы заполнить её снова.');
      return;
    }
    say('✅ **Анкета здоровья заполнена!**\n\nТеперь мои рекомендации будут максимально точными и безопасными для вас.\n\n' +
        'Обновить данные можно в любое время — кнопка «⚙️ Мой профиль» в меню.');
    setMenuVisible(true);
    say('Выберите действие 👇');
  }

  // ── ⚙️ Профиль ───────────────────────────────────────────────────────────

  function profileSummary(p) {
    const v = (x) => { const s = (x || '').trim(); return s && s !== 'нет' && s !== 'не указано' ? s : '—'; };
    const lines = [
      '👤 **Ваш профиль здоровья**\n',
      `Пол: ${GENDER_LABEL[p.gender] || '—'}   Возраст: ${AGE_LABEL[p.age_range] || '—'}`,
      '',
      `🏥 Хронические болезни: ${v(p.chronic_diseases)}`,
      `⚠️ Аллергии: ${v(p.allergies)}`,
      `💊 Лекарства: ${v(p.medications)}`,
    ];
    if (p.gender === 'female') lines.push(`🤰 Беременность/лактация: ${PREGNANCY_LABEL[p.pregnancy] || '—'}`);
    lines.push(
      `🔪 Операции: ${v(p.past_surgeries)}`,
      `🧬 Наследственность: ${v(p.hereditary_diseases)}`,
      `🚬 Курение: ${SMOKING_LABEL[p.smoking] || '—'}`,
      `🍷 Алкоголь: ${ALCOHOL_LABEL[p.alcohol] || '—'}`,
      `🏃 Активность: ${ACTIVITY_LABEL[p.physical_activity] || '—'}`,
      `⚖️ Рост/вес: ${v(p.height_weight)}`,
    );
    return lines.join('\n');
  }

  async function showProfile() {
    const flow = flowId;
    me = await api('/me');
    if (!me.onboarding_done) {
      say('📋 Анкета здоровья ещё не заполнена.\n\nДавайте заполним её сейчас!');
      if (!me.gender || !me.age_range) beginOnboarding(); else startQuestionnaire();
      return;
    }
    const m = say(profileSummary(me));
    keyboard(m, [
      [{ label: '✏️ Обновить анкету', onClick: () => startQuestionnaire() }],
      [{ label: '📚 Источники рекомендаций', onClick: () => showSources() }],
      [{ label: '🚪 Выйти', onClick: () => logout() }],
      [{ label: '🗑 Удалить аккаунт', danger: true, onClick: () => confirmDeleteAccount() }],
    ], { flow });
  }

  function confirmDeleteAccount() {
    const flow = flowId;
    const m = say('🗑 **Удалить аккаунт?**\n\nБудут безвозвратно удалены профиль, консультации, курсы, дневник и семья. Отменить это нельзя.');
    keyboard(m, [
      [{
        label: 'Да, удалить навсегда', danger: true,
        onClick: async () => {
          await api('/me', { method: 'DELETE' });
          logout();
          showLoginError('Аккаунт и все данные удалены.');
        },
      }],
      [{ label: 'Отмена', onClick: () => { say('Хорошо, ничего не удаляю.'); } }],
    ], { flow });
  }

  async function showSources() {
    const data = await api('/sources');
    const frag = document.createDocumentFragment();
    frag.append(rich('📚 **Источники рекомендаций**\n'));
    const group = (title, groups) => {
      if (!groups.length) return;
      frag.append(rich(`\n**${title}**\n`));
      groups.forEach((g) => {
        frag.append(rich(`${g.names.join(', ')}\n`));
        g.sources.forEach((s) => {
          const u = s.url && safeUrl(s.url);
          frag.append(document.createTextNode('• '));
          frag.append(u ? el('a', { href: u, target: '_blank', rel: 'noopener noreferrer' }, s.title) : document.createTextNode(s.title));
          frag.append(document.createTextNode('\n'));
        });
      });
    };
    group('Продукты каталога', data.catalog || []);
    group('Другие добавки (только справочно)', data.other || []);
    addMsg('bot', frag);
  }

  // ── 🤖 Консультация ──────────────────────────────────────────────────────

  const ASSISTANT_NOTE = '⚠️ Я не ставлю диагнозы и не заменяю очного врача. В экстренной ситуации звоните 112 или 103.';

  async function startConsultation() {
    const flow = flowId;
    const members = await api('/family');
    if (!members.length) { await beginConsultation(flow, null, null); return; }
    const m = say('Для кого консультация?');
    keyboard(m, [
      [{ label: '👤 Для себя', onClick: () => beginConsultation(flow, null, null) }],
      ...members.map((f) => [{ label: `👥 ${f.name} (${f.relation})`, onClick: () => beginConsultation(flow, f.id, f.name) }]),
    ], { flow });
  }

  async function beginConsultation(flow, memberId, memberName) {
    const s = await api('/consultations', { method: 'POST', body: { family_member_id: memberId } });
    if (flow !== flowId) return;
    say(`🤖 **Консультация с ИИ**${memberName ? ` — для ${memberName}` : ''}\n\n${s.opening_prompt}\n\n${ASSISTANT_NOTE}`);
    let sending = false;
    awaitText('Опишите, что вас беспокоит…', async (text) => {
      if (sending) return;
      sending = true;
      const done = typing();
      try {
        const r = await api(`/consultations/${s.session_id}/messages`, { method: 'POST', body: { text } });
        done();
        if (flow !== flowId) return;
        renderAnswer(flow, r);
        if (r.session_status === 'completed') {
          stopText();
          say('Консультация завершена. Если появятся новые вопросы — начните новую через «🤖 Консультация с ИИ».');
        }
      } catch (e) {
        done();
        reportError(e);
        if (e.status === 409 || e.status === 404) stopText();
      } finally {
        sending = false;
      }
    });
  }

  function renderAnswer(flow, r) {
    if (r.type === 'emergency') { say(`🚨 **Внимание!**\n\n${r.text}`, 'emergency'); return; }
    say(r.text || '…');
    if (r.type === 'question') return;

    if (r.doctor) {
      const m = say(`👨‍⚕️ Рекомендуемый специалист: **${r.doctor.name}**`);
      keyboard(m, [[{ label: 'Записаться', href: r.doctor.url }]], { sticky: true });
    }
    if (r.bad) {
      const m = say(`💊 **${r.bad.name}**\n${r.bad.description}`);
      keyboard(m, [
        [{ label: '🛒 Купить', href: r.bad.url }],
        [{ label: '▶️ Начать курс', onClick: () => startCourse(r.bad.key, r.bad.name) }],
      ]);
    }
    if (r.general_supplement) {
      const m = say(`💡 Также стоит обратить внимание на: **${r.general_supplement}**`);
      keyboard(m, [[{ label: '📊 Отслеживать приём', onClick: () => askCustomCourse(r.general_supplement) }]]);
    }
    if (r.safety_warnings && r.safety_warnings.length) {
      say(`⚠️ **Важно знать:**\n${r.safety_warnings.map((w) => `• ${w}`).join('\n')}`, 'notice');
    }
    if (r.disclaimer) say(r.disclaimer, 'notice');
  }

  async function startCourse(key, name) {
    await api('/tracker', { method: 'POST', body: { product_key: key, date: localDate() } });
    say(`✅ Курс **${name}** начат. Отмечать приёмы можно в разделе «📊 Мой трекер».`);
  }

  /** A supplement we don't sell: needs a name and a course length. */
  function askCustomCourse(presetName) {
    const flow = newFlow();
    const askDays = (name) => {
      say(`На сколько дней курс **${name}**? Напишите число от 1 до 365.`);
      awaitText('Например: 30', async (t) => {
        const days = Number(t.trim());
        if (!Number.isInteger(days) || days < 1 || days > 365) { say('Нужно целое число от 1 до 365.'); return; }
        stopText();
        try {
          await api('/tracker', { method: 'POST', body: { product_key: name, course_days: days, date: localDate() } });
          if (flow === flowId) say(`✅ Курс **${name}** на ${days} дн. начат. Отмечать приёмы можно в «📊 Мой трекер».`);
        } catch (e) { reportError(e); }
      });
    };
    if (presetName) { askDays(presetName.slice(0, 100)); return; }
    say('Как называется добавка?');
    awaitText('Название', (t) => {
      const name = t.trim().slice(0, 100);
      if (!name) return;
      askDays(name);
    });
  }

  // ── 💊 Подбор БАД ────────────────────────────────────────────────────────

  async function startAdvisor() {
    const flow = flowId;
    const goals = await api('/bad-goals');
    const m = say('💊 **Подбор БАД**\n\nКакая у вас цель? ⭐ — подходит под ваш профиль.');
    keyboard(m, goals.map((g) => [{
      label: `${g.suggested ? '⭐ ' : ''}${g.label}`,
      onClick: () => pickGoal(flow, g),
    }]), { flow });
  }

  function pickGoal(flow, goal) {
    if (!goal.clarify) return checkGoal(goal, null);
    const m = say(goal.clarify.question);
    keyboard(m, goal.clarify.options.map((o) => [{ label: o.label, onClick: () => checkGoal(goal, o.key) }]), { flow });
    return undefined;
  }

  async function checkGoal(goal, option) {
    const flow = flowId;
    const done = typing();
    let r;
    try {
      r = await api('/bad-advisor/check', { method: 'POST', body: { goal_key: goal.key, clarify_option: option } });
    } finally { done(); }
    if (flow !== flowId) return;

    say(`🎯 **${r.goal_label}**`);
    if (r.blocked_notes.length) say(`🚫 **Не подходит вам:**\n${r.blocked_notes.map((n) => `• ${n}`).join('\n')}`, 'notice');
    if (r.warnings.length) say(`⚠️ **Обратите внимание:**\n${r.warnings.map((n) => `• ${n}`).join('\n')}`, 'notice');
    if (r.extra_note) say(r.extra_note);

    r.bads.forEach((b) => {
      const lines = [
        `${b.emoji} **${b.full_name}**`,
        `Цель: ${b.goal}`,
        `Дозировка: ${b.dosage}`,
        `Курс: ${b.course_days} дн. · лучше принимать: ${b.best_time}${b.with_food ? ', во время еды' : ''}`,
      ];
      if (b.notes) lines.push(b.notes);
      if (b.synergies.length) lines.push(`🤝 ${b.synergies.join(' ')}`);
      const m = say(lines.join('\n'));
      keyboard(m, [
        [{ label: '🛒 Купить', href: b.url }],
        [{ label: '▶️ Начать курс', onClick: () => startCourse(b.key, b.full_name) }],
      ]);
    });

    r.general_supplements.forEach((g) => {
      const m = say(`💡 **${g.label}**\n${g.goal}${g.notes ? `\n${g.notes}` : ''}\n\nЭто справочная информация: такой добавки в нашем каталоге нет.`);
      keyboard(m, [[{ label: '📊 Отслеживать приём', onClick: () => askCustomCourse(g.label) }]]);
    });

    if (r.lifestyle_tips) say(`🌿 **Образ жизни**\n${r.lifestyle_tips}`);
    const last = say('Выбрать другую цель?');
    keyboard(last, [[{ label: '↩️ Другая цель', onClick: () => startAdvisor() }]], { flow });
  }

  // ── 📊 Трекер ────────────────────────────────────────────────────────────

  const bar = (days, total) => {
    const raw = Math.round((days / Math.max(total, 1)) * 10);
    const filled = Math.max(days > 0 ? 1 : 0, Math.min(10, raw));   // one taken day always shows
    return '▓'.repeat(filled) + '░'.repeat(10 - filled);
  };

  async function showTracker() {
    const flow = flowId;
    const list = await api('/tracker');
    if (!list.length) {
      const m = say('📊 **Мой трекер**\n\nАктивных курсов пока нет. Подберите добавку — и начните курс.');
      trackerFooter(m, flow);
      return;
    }
    say('📊 **Мой трекер**\nВ веб-версии напоминаний нет — заходите и отмечайте приём.');
    list.forEach((c) => renderCourse(c, flow));
    const m = say('Что ещё?');
    trackerFooter(m, flow);
  }

  function trackerFooter(m, flow) {
    keyboard(m, [
      [{ label: '💊 Подбор БАД', onClick: () => startAdvisor() }],
      [{ label: '➕ Своя добавка', onClick: () => askCustomCourse(null) }],
      [{ label: '📜 История курсов', onClick: () => showCourseHistory() }],
    ], { flow, sticky: true });
  }

  function renderCourse(c, flow) {
    const m = addMsg('bot', '', 'wide');
    const paint = (days, state) => {
      m.replaceChildren(
        rich(`${c.emoji} **${c.full_name}**\n`),
        el('span', { class: 'bar' }, bar(days, c.course_days)),
        document.createTextNode(`\nПринято дней: ${days} из ${c.course_days}\nСтарт: ${fmtDate(c.start_date)}`),
      );
      if (state === 'done') { m.append(rich('\n\n🎉 **Курс завершён!** Он перенесён в историю курсов.')); return; }
      if (state === 'stopped') { m.append(rich('\n\n🛑 Курс остановлен.')); return; }
      if (state === 'confirm') {
        m.append(rich('\n\nОстановить курс? Отметки о приёме сохранятся в истории.'));
        keyboard(m, [[
          { label: 'Да, остановить', danger: true, onClick: async () => {
            await api(`/tracker/${c.id}?date=${localDate()}`, { method: 'DELETE' });
            paint(days, 'stopped');
          } },
          { label: 'Отмена', onClick: () => paint(days, null) },
        ]], { flow, sticky: true });
        return;
      }
      const intake = (status) => async () => {
        const r = await api(`/tracker/${c.id}/intake`, { method: 'POST', body: { status, slot: '1', date: localDate() } });
        paint(r.days_taken, r.course_completed ? 'done' : null);
      };
      keyboard(m, [
        [{ label: '✅ Принял(а) сегодня', onClick: intake('taken') }, { label: '⏭ Пропустил(а)', onClick: intake('skip') }],
        [{ label: '🛑 Остановить курс', danger: true, onClick: () => paint(days, 'confirm') }],
      ], { flow, sticky: true });
    };
    paint(c.days_taken, null);
  }

  async function showCourseHistory() {
    const rows = await api('/tracker/history');
    if (!rows.length) { say('📜 История курсов пока пуста.'); return; }
    const status = { completed: '✅ завершён', stopped: '🛑 остановлен' };
    say('📜 **История курсов**\n\n' + rows.map((h) =>
      `${h.emoji} ${h.full_name} — ${status[h.status] || h.status}\n   ${fmtDate(h.start_date)} · принято ${h.days_taken} из ${h.course_days} дн.`).join('\n\n'));
  }

  // ── 📔 Дневник ───────────────────────────────────────────────────────────

  const RATING_WORDS = {
    false: { 1: 'Плохо', 2: 'Слабо', 3: 'Средне', 4: 'Хорошо', 5: 'Отлично' },
    true: { 1: 'Низкий', 2: 'Слабый', 3: 'Средний', 4: 'Высокий', 5: 'Сильный' },
  };
  const RATING_EMOJI = {
    false: { 1: '😞', 2: '😕', 3: '😐', 4: '🙂', 5: '😄' },
    true: { 1: '😌', 2: '🙂', 3: '😐', 4: '😟', 5: '😰' },
  };
  const METRIC_LABEL = { sleep: 'Сон', energy: 'Энергия', stress: 'Стресс' };
  const METRIC_COLOR = { sleep: '#4C72B0', energy: '#DD8452', stress: '#C44E52' };

  function ratingRows(onPick, reverse) {
    const b = [1, 2, 3, 4, 5].map((i) => ({
      label: `${RATING_EMOJI[reverse][i]} ${RATING_WORDS[reverse][i]}`, onClick: () => onPick(i),
    }));
    return [b.slice(0, 2), b.slice(2, 4), b.slice(4)];
  }

  async function showDiary() {
    const flow = flowId;
    const entries = await api('/diary?limit=30');
    const today = localDate();
    if (entries.length && entries[0].entry_date === today) {
      const e = entries[0];
      say('📔 **Дневник самочувствия**\n\nЗапись на сегодня уже есть ✅\n\n' +
        `😴 Сон: ${RATING_WORDS[false][e.sleep_quality]}\n⚡ Энергия: ${RATING_WORDS[false][e.energy_level]}\n` +
        `😤 Стресс: ${RATING_WORDS[true][e.stress_level]}\n💊 БАД: ${e.bads_taken ? '✅' : '❌'}`);
      await sendTrend(flow);
      return;
    }
    const v = {};
    const m1 = say('📔 **Новая запись в дневник**\n\n😴 **Качество сна прошлой ночью?**');
    keyboard(m1, ratingRows((sleep) => {
      v.sleep = sleep;
      const m2 = say(`😴 Сон: ${RATING_WORDS[false][sleep]}\n\n⚡ **Уровень энергии сегодня?**`);
      keyboard(m2, ratingRows((energy) => {
        v.energy = energy;
        const m3 = say(`⚡ Энергия: ${RATING_WORDS[false][energy]}\n\n😤 **Уровень стресса сегодня?**`);
        keyboard(m3, ratingRows((stress) => {
          v.stress = stress;
          const m4 = say(`😤 Стресс: ${RATING_WORDS[true][stress]}\n\n💊 **Принимали ли вы БАД сегодня?**`);
          keyboard(m4, [[
            { label: '✅ Да', onClick: () => saveDiary(flow, v, true) },
            { label: '❌ Нет', onClick: () => saveDiary(flow, v, false) },
          ]], { flow });
        }, true), { flow });
      }, false), { flow });
    }, false), { flow });
  }

  async function saveDiary(flow, v, bads) {
    await api('/diary/today', {
      method: 'PUT',
      body: { sleep_quality: v.sleep, energy_level: v.energy, stress_level: v.stress, bads_taken: bads, date: localDate() },
    });
    say('✅ **Запись сохранена!**\n\n' +
      `😴 Сон: ${RATING_WORDS[false][v.sleep]}\n⚡ Энергия: ${RATING_WORDS[false][v.energy]}\n` +
      `😤 Стресс: ${RATING_WORDS[true][v.stress]}\n💊 БАД: ${bads ? '✅ Да' : '❌ Нет'}\n\n` +
      'Продолжайте вести дневник — наблюдение за динамикой поможет заметить реальный прогресс от приёма БАД!');
    await sendTrend(flow);
  }

  async function sendTrend(flow) {
    const entries = await api('/diary?limit=30');
    if (entries.length < 2 || flow !== flowId) return;
    const chrono = [...entries].reverse();
    const insights = await api('/diary/insights');

    const m = addMsg('bot', '', 'wide');
    m.append(rich('📈 **Динамика за последние дни**'));
    const canvas = el('canvas', { class: 'chart', role: 'img', 'aria-label': 'График сна, энергии и стресса за последние дни' });
    m.append(canvas);
    m.append(el('div', { class: 'legend' }, ...Object.keys(METRIC_LABEL).map((k) =>
      el('span', {}, el('i', { class: `dot ${k}` }), METRIC_LABEL[k]))));

    const started = (insights.courses || []).map((c) => {
      const suffix = c.status === 'completed' ? ', ✅ завершён' : c.status === 'stopped' ? ', 🛑 остановлен' : '';
      return `• ${c.full_name} — начат ${fmtDate(c.start_date)}${suffix}${c.ended_at ? ` ${fmtDate(c.ended_at)}` : ''}`;
    });
    if (started.length) m.append(rich(`\n\n📅 **Начало курсов:**\n${started.join('\n')}`));

    const corr = (insights.correlations || []).map((c) =>
      `**${c.full_name}**: ` + c.changes.map((x) =>
        `${METRIC_LABEL[x.metric]} ${x.before.toFixed(1)}→${x.after.toFixed(1)} ${x.after > x.before ? '📈' : '📉'}`).join(', '));
    if (corr.length) {
      m.append(rich('\n\n📊 **Что изменилось с начала курса** (по вашим же записям в дневнике, не медицинский вывод):\n' + corr.join('\n')));
    }
    scrollDown();
    drawChart(canvas, chrono);
  }

  function drawChart(canvas, entries) {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    const css = getComputedStyle(document.documentElement);
    const muted = css.getPropertyValue('--muted').trim() || '#666';
    const grid = css.getPropertyValue('--line').trim() || '#ccc';
    const P = { l: 28, r: 10, t: 10, b: 24 };
    const day = (s) => Date.parse(`${s}T00:00:00`);
    const t0 = day(entries[0].entry_date);
    const t1 = day(entries[entries.length - 1].entry_date);
    const x = (s) => P.l + ((t1 === t0 ? 0.5 : (day(s) - t0) / (t1 - t0))) * (w - P.l - P.r);
    const y = (val) => P.t + (1 - (val - 0.5) / 5) * (h - P.t - P.b);

    ctx.font = '11px system-ui, sans-serif';
    ctx.fillStyle = muted;
    ctx.strokeStyle = grid;
    ctx.lineWidth = 1;
    for (let v = 1; v <= 5; v += 1) {
      ctx.beginPath(); ctx.moveTo(P.l, y(v)); ctx.lineTo(w - P.r, y(v)); ctx.stroke();
      ctx.fillText(String(v), 8, y(v) + 4);
    }
    const ticks = Math.min(5, entries.length);
    for (let i = 0; i < ticks; i += 1) {
      const e = entries[Math.round((i * (entries.length - 1)) / Math.max(ticks - 1, 1))];
      const [, mm, dd] = e.entry_date.split('-');
      const tx = x(e.entry_date);
      ctx.textAlign = i === 0 ? 'left' : i === ticks - 1 ? 'right' : 'center';
      ctx.fillText(`${dd}.${mm}`, tx, h - 6);
    }
    ctx.textAlign = 'left';

    const fields = { sleep: 'sleep_quality', energy: 'energy_level', stress: 'stress_level' };
    Object.entries(fields).forEach(([metric, field]) => {
      ctx.strokeStyle = METRIC_COLOR[metric];
      ctx.fillStyle = METRIC_COLOR[metric];
      ctx.lineWidth = 2;
      ctx.beginPath();
      entries.forEach((e, i) => { const px = x(e.entry_date); const py = y(e[field]); if (i) ctx.lineTo(px, py); else ctx.moveTo(px, py); });
      ctx.stroke();
      entries.forEach((e) => { ctx.beginPath(); ctx.arc(x(e.entry_date), y(e[field]), 3, 0, Math.PI * 2); ctx.fill(); });
    });
  }

  // ── 📋 История ───────────────────────────────────────────────────────────

  async function showHistory() {
    const flow = flowId;
    const rows = await api('/history?limit=10');
    if (!rows.length) { say('📋 Консультаций пока не было. Начните первую — «🤖 Консультация с ИИ».'); return; }
    say('📋 **История консультаций**');
    rows.forEach((h) => {
      const who = h.family_member_name ? ` · ${h.family_member_name}` : '';
      const m = say(`**${fmtDate(h.created_at)}**${who}\n${h.complaint || 'Без описания'}` +
        (h.summary ? `\n\n${h.summary.slice(0, 300)}${h.summary.length > 300 ? '…' : ''}` : ''));
      keyboard(m, [[{
        label: 'Открыть переписку',
        onClick: async () => {
          const t = await api(`/consultations/${h.session_id}`);
          say(t.turns.map((x) => `${x.role === 'user' ? 'Вы' : 'Доктор'}: ${x.text}`).join('\n\n') || 'Переписка пуста.');
        },
      }]], { flow, sticky: true });
    });
  }

  // ── 👨‍👩‍👧 Семья ───────────────────────────────────────────────────────────

  const RELATIONS = ['сын', 'дочь', 'муж', 'жена', 'мама', 'папа', 'брат', 'сестра', 'другое'];

  async function showFamily() {
    const flow = flowId;
    const members = await api('/family');
    const m = say(members.length
      ? '👨‍👩‍👧 **Семья**\n\nВыберите человека или добавьте нового. Для каждого можно вести консультации с учётом его анкеты.'
      : '👨‍👩‍👧 **Семья**\n\nЗдесь можно добавить близких и получать консультации с учётом их здоровья.');
    keyboard(m, [
      ...members.map((f) => [{ label: `👤 ${f.name} (${f.relation})`, onClick: () => viewMember(flow, f.id) }]),
      [{ label: '➕ Добавить человека', onClick: () => addMember(flow) }],
    ], { flow, sticky: true });
  }

  async function viewMember(flow, id) {
    const f = await api(`/family/${id}`);
    const summary = f.onboarding_done
      ? profileSummary(f).replace('**Ваш профиль здоровья**', `**${f.name}** (${f.relation})`)
      : `👤 **${f.name}** (${f.relation})\n\nАнкета ещё не заполнена.`;
    const m = say(summary);
    keyboard(m, [
      [{ label: `🤖 Консультация для ${f.name}`, onClick: () => { newFlow(); return beginConsultation(flowId, f.id, f.name); } }],
      [{ label: '✏️ Заполнить анкету', onClick: () => fillMemberProfile(f.id, f.name) }],
      [{ label: '🗑 Удалить', danger: true, onClick: () => confirmRemoveMember(flow, f) }],
    ], { flow, sticky: true });
  }

  function fillMemberProfile(memberId, name) {
    const flow = newFlow();
    say(`🏥 **Анкета: ${name}**`);
    askGenderAge(flow, (gender, age) => {
      runQuestionnaire(flow, gender, async (answers) => {
        try {
          await api(`/family/${memberId}/profile`, { method: 'PUT', body: { gender, age_range: age, ...answers } });
          say(`✅ Анкета для **${name}** сохранена.`);
        } catch (e) { reportError(e); }
      });
    });
  }

  function addMember() {
    const flow = newFlow();
    say('Как зовут этого человека?\nНапример: Ваня, Мама, Бабушка');
    awaitText('Имя', (t) => {
      const name = t.trim().slice(0, 100);
      if (!name) return;
      stopText();
      const m = say(`Кем вам приходится **${name}**?`);
      const btn = (r) => ({
        label: r,
        onClick: async () => {
          const f = await api('/family', { method: 'POST', body: { name, relation: r } });
          say(`✅ **${f.name}** добавлен(а).`);
          fillMemberProfile(f.id, f.name);
        },
      });
      keyboard(m, [RELATIONS.slice(0, 3).map(btn), RELATIONS.slice(3, 6).map(btn), RELATIONS.slice(6).map(btn)], { flow });
    });
  }

  function confirmRemoveMember(flow, f) {
    const m = say(`Удалить **${f.name}** и все его данные?`);
    keyboard(m, [[
      { label: 'Да, удалить', danger: true, onClick: async () => { await api(`/family/${f.id}`, { method: 'DELETE' }); say(`🗑 ${f.name} удалён(а).`); } },
      { label: 'Отмена', onClick: () => {} },
    ]], { flow });
  }

  // ── Start ────────────────────────────────────────────────────────────────

  window.addEventListener('unhandledrejection', (e) => { e.preventDefault(); if (!$('chat').hidden) reportError(e.reason); });

  stopText();
  if (token) boot(); else showLogin();
})();
