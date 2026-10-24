/* 状态、导航与交互。所有请求都走 api()，渲染都走 Views。 */
(function () {
  'use strict';

  const esc = (value) => Charts.escapeText(value === null || value === undefined ? '' : value);

  const state = {
    tab: 'home',
    boot: null,
    home: null,
    calendarCursor: { year: 0, month: 0 },
    okrYear: 0,
    ledgerMonth: '',
    dietDay: '',
    holidayYear: 0,
    yearView: 0,
    market: null,
    tasksIndex: {},
    pending: null
  };

  /* ---------------- 日期工具 ---------------- */

  function pad(value) { return String(value).padStart(2, '0'); }

  function isoOf(date) {
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  }

  function parseIso(text) {
    const parts = String(text).split('-').map(Number);
    return new Date(parts[0], parts[1] - 1, parts[2]);
  }

  function addDays(text, count) {
    const date = parseIso(text);
    date.setDate(date.getDate() + count);
    return isoOf(date);
  }

  function monthKeyOf(text) { return String(text).slice(0, 7); }

  function shiftMonth(month, delta) {
    const parts = month.split('-').map(Number);
    const date = new Date(parts[0], parts[1] - 1 + delta, 1);
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}`;
  }

  function monthBounds(month) {
    const parts = month.split('-').map(Number);
    const first = new Date(parts[0], parts[1] - 1, 1);
    const last = new Date(parts[0], parts[1], 0);
    return [isoOf(first), isoOf(last)];
  }

  /* ---------------- 与 Python 通信 ---------------- */

  function api(method) {
    const args = Array.prototype.slice.call(arguments, 1);
    /* 桥还没注入时等它，而不是当场拒绝——WebView2 冷启动时页面脚本
       可能跑在 Python 挂好接口之前，启动快慢全看机器当天的脸色。 */
    return waitForBridge().then(() => {
      const bridge = window.pywebview && window.pywebview.api;
      if (!bridge || !bridge[method]) {
        throw new Error(`接口还没就绪：${method}`);
      }
      return bridge[method].apply(bridge, args);
    });
  }

  function waitForBridge(timeoutMs) {
    const limit = timeoutMs || 30000; // 30 秒还等不到就该报错让人重试，不能无限转圈
    return new Promise((resolve, reject) => {
      if (window.pywebview && window.pywebview.api) {
        resolve();
        return;
      }
      let settled = false;
      const started = Date.now();
      const finish = (ok, err) => {
        if (settled) return;
        settled = true;
        clearInterval(timer);
        window.removeEventListener('pywebviewready', onReady);
        if (ok) resolve(); else reject(err);
      };
      // pywebview 在接口真正就绪时派发这个事件，比纯轮询更准、更早
      const onReady = () => finish(true);
      window.addEventListener('pywebviewready', onReady);
      const timer = setInterval(() => {
        if (window.pywebview && window.pywebview.api) {
          finish(true);
        } else if (Date.now() - started > limit) {
          finish(false, new Error('等了很久，Python 侧的接口一直没挂上来（可能启动被拦截或已在退出）'));
        }
      }, 60);
    });
  }

  /* ---------------- 渲染 ---------------- */

  const view = document.getElementById('view');

  function render() {
    const data = state[state.tab];
    if (!data) return;
    const renderer = {
      home: Views.home,
      calendar: Views.calendar,
      tasks: Views.tasks,
      okr: Views.okr,
      ledger: Views.ledger,
      diet: Views.diet,
      body: Views.body,
      year: Views.year,
      market: Views.market,
      settings: Views.settings
    }[state.tab];
    view.innerHTML = renderer(data);
  }

  function renderNudges() {
    const box = document.getElementById('nudges');
    if (!state.home) return;
    if (!state.home.nudges.length) {
      box.innerHTML = '<span class="nudge-clear">今天该做的都做完了</span>';
      return;
    }
    box.innerHTML = state.home.nudges
      .map((nudge) => `<span class="nudge">${esc(nudge.text)}</span>`)
      .join('');
  }

  async function reload() {
    await loadTab(state.tab);
    render();
  }

  /* ---------------- 各页签取数 ---------------- */

  async function loadHome() {
    const [categories, home] = await Promise.all([api('ledger_categories'), api('home')]);
    state.home = { ...home, categories };
    indexTasks(state.home.tasks.concat(state.home.overdue));
    renderNudges();
  }

  async function loadCalendar() {
    /* state.calendar 只放加载好的整月数据（渲染用）；正在看哪个月由
       state.calendarCursor 记住。两者分开，否则首次加载前游标会被
       当成整月数据去渲染（没有 weeks），直接抛异常、点击毫无反应。 */
    state.calendar = await api('calendar_month', state.calendarCursor.year, state.calendarCursor.month);
  }

  async function loadTasks() {
    const today = state.boot.today;
    const [monthStart, monthEnd] = monthBounds(monthKeyOf(today));
    const year = Number(today.slice(0, 4));

    const [past, upcoming, monthTasks, habitRows, overview] = await Promise.all([
      api('list_tasks_range', '2000-01-01', addDays(today, -1)),
      api('list_tasks_range', addDays(today, 1), addDays(today, 7)),
      api('list_tasks_range', monthStart, monthEnd),
      api('list_habits'),
      api('year_overview', year)
    ]);

    const overdue = past.filter((task) => !task.done);
    indexTasks([].concat(overdue, upcoming, monthTasks));
    state.tasks = {
      today,
      overdue,
      upcoming,
      month_tasks: monthTasks,
      habits: habitRows,
      year_task_rate: overview.tasks.rate,
      year_habit_rate: overview.habits.rate
    };
  }

  function indexTasks(items) {
    items.forEach((task) => { state.tasksIndex[String(task.id)] = task; });
  }

  async function loadOkr() {
    state.okr = await api('okr_overview', state.okrYear);
  }

  async function loadLedger() {
    const [month, year] = await Promise.all([
      api('ledger_month', state.ledgerMonth),
      api('ledger_year', Number(state.ledgerMonth.slice(0, 4)))
    ]);
    state.ledger = {
      ...month,
      year_months: year.months,
      default_day: state.boot.today.slice(0, 7) === state.ledgerMonth ? state.boot.today : `${state.ledgerMonth}-01`
    };
  }

  async function loadDiet() {
    state.diet = await api('diet_day', state.dietDay);
  }

  async function loadBody() {
    state.body = { ...(await api('body_status')), today: state.boot.today };
  }

  async function loadYear() {
    state.year_data = await api('year_overview', state.yearView);
    state.year = state.year_data;
  }

  /* 行情：本地数据秒开，对外取数全部在后台跑（ADR 0010）。
     overview 只读库不联网；refresh 踢后台同步立即返回。
     打开行情页进入「动态刷新」：
       - 同步进行中每 2 秒轻量轮询，落库即静默替换（仅内容有变化才重绘）；
       - 空闲时每 60 秒才踢一次新刷新（服务层有 60 秒节流，不会刷爆）；
       - 窗口隐藏时整段暂停，回前台再恢复——不盯屏就不耗任何资源；
       - 离开行情页立即停止轮询与心跳。
     网络全在独立后台线程，UI 线程零阻塞，2 秒轮询只是本地读 + 比对签名。 */
  let marketLive = null;  // { pollTimer, beatTimer }

  function stopMarketLive() {
    if (marketLive) {
      clearInterval(marketLive.pollTimer);
      clearInterval(marketLive.beatTimer);
      marketLive = null;
    }
  }

  // 行情数据的轻量指纹：行情日 + 同步状态 + 各报价，用于「没变化就不重绘」
  function marketSignature(m) {
    if (!m) return '';
    const prices = (m.indices || []).concat(m.crypto || []).concat(m.watch || [])
      .map((x) => `${x.code}:${x.price}:${x.change_pct}`)
      .join(',');
    return [m.day, m.syncing ? 1 : 0, prices].join('|');
  }

  function marketActive() {
    return state.tab === 'market' && !document.hidden;
  }

  function startMarketLive() {
    stopMarketLive();
    if (!marketActive()) return;

    // 2 秒轮询：本地读 overview，变化才重绘；同步结束就转由心跳维持
    const pollTimer = setInterval(async () => {
      if (!marketActive()) return;
      try {
        const fresh = await api('market_overview');
        if (!marketActive()) return;
        const sig = marketSignature(fresh);
        if (sig !== state._marketSig) {
          state.market = fresh;
          state._marketSig = sig;
          if (state.tab === 'market') render();
        }
      } catch (error) {
        /* 单轮失败不阻断，下一轮再试；绝不抛到外层卡住界面 */
      }
    }, 2000);

    // 60 秒心跳：踢一次新刷新（服务层节流，太频会被拒），新数据靠上面轮询接住
    const beatTimer = setInterval(async () => {
      if (!marketActive()) return;
      try {
        await api('market_refresh', false);
      } catch (error) {
        /* 忽略 */
      }
    }, 60000);

    marketLive = { pollTimer, beatTimer };
  }

  async function loadMarket(force) {
    stopMarketLive();
    state._marketSig = null;
    state.market = await api('market_overview');
    state._marketSig = marketSignature(state.market);
    render();
    if (state.market.net_enabled) {
      const kick = await api('market_refresh', !!force);
      state.market = { ...state.market, syncing: kick.syncing || state.market.syncing };
      render();
    }
    startMarketLive();
  }

  // 窗口隐藏时彻底停掉动态刷新（零资源占用），回前台且正在看行情再恢复
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      stopMarketLive();
    } else if (state.tab === 'market') {
      startMarketLive();
    }
  });

  async function loadSettings() {
    const [info, holidays, categories, net, foodTotal] = await Promise.all([
      api('data_info'),
      api('holidays_year', state.holidayYear),
      api('ledger_categories'),
      api('net_status'),
      api('food_total')
    ]);
    state.settings = {
      info,
      holidays,
      holiday_year: state.holidayYear,
      categories,
      net,
      food_total: foodTotal
    };
  }

  async function loadTab(tab) {
    switch (tab) {
      case 'home': await loadHome(); break;
      case 'calendar': await loadCalendar(); break;
      case 'tasks': await loadTasks(); break;
      case 'okr': await loadOkr(); break;
      case 'ledger': await loadLedger(); break;
      case 'diet': await loadDiet(); break;
      case 'body': await loadBody(); break;
      case 'year': await loadYear(); break;
      case 'market': await loadMarket(); break;
      case 'settings': await loadSettings(); break;
      default: break;
    }
  }

  /* ---------------- 导航 ---------------- */

  /* 每个页签的标题。加载占位要用和正式视图完全一致的文案，
     这样左侧高亮切过去的那一刻，右侧标题就已经对得上，不会出现
     「按钮是新的、标题还是旧的」这种错位。 */
  const TAB_TITLES = {
    home: () => '今天',
    calendar: () => `${state.calendarCursor.year} 年 ${state.calendarCursor.month} 月`,
    tasks: () => '任务与习惯',
    okr: () => `${state.okrYear} 年目标`,
    ledger: () => `${state.ledgerMonth} 账本`,
    diet: () => `${state.dietDay} 饮食`,
    body: () => '体重与体脂',
    year: () => `${state.yearView} 年度总览`,
    market: () => '行情',
    settings: () => '设置'
  };

  function renderLoading(tab) {
    view.innerHTML = `
      <div class="page-head">
        <div><h1 class="page-title">${esc(TAB_TITLES[tab] ? TAB_TITLES[tab]() : '')}</h1></div>
      </div>
      <div class="card loading-card">
        <span class="loading-spinner" aria-hidden="true"></span>
        <span class="muted">加载中…</span>
      </div>`;
  }

  /* 取数失败绝不许停在「加载中」：给一句人话和一个重试按钮，
     不然用户只会觉得应用卡死了（v1.5.2 的教训）。 */
  function renderTabError(tab, error) {
    const title = TAB_TITLES[tab] ? TAB_TITLES[tab]() : '';
    view.innerHTML = `
      <div class="page-head">
        <div><h1 class="page-title">${esc(title)}</h1></div>
      </div>
      <div class="card">
        <h2 class="card-title">这个页签没加载出来</h2>
        <p class="muted">${esc(String((error && error.message) || error))}</p>
        <div class="row" style="margin-top:12px">
          <button class="button button-primary" data-action="retry-tab">重试</button>
        </div>
      </div>`;
  }

  async function switchTab(tab) {
    // 离开行情页就停掉它的动态刷新：后台同步照跑，但没必要继续问进度
    stopMarketLive();
    state.tab = tab;
    document.querySelectorAll('.nav-item').forEach((item) => {
      item.classList.toggle('is-active', item.dataset.tab === tab);
    });
    view.scrollTop = 0;

    /* 先把界面动起来再取数：这个页签之前看过，直接渲染旧数据（标题当场对得上），
       数据回来后再刷新成新的；第一次看则显示加载占位。
       取数期间连着点几个页签也不会串内容——只有最后一次点击的那次渲染会生效。 */
    if (state[tab]) {
      render();
    } else {
      renderLoading(tab);
    }

    try {
      await loadTab(tab);
    } catch (error) {
      console.error(error);
      if (state.tab === tab) renderTabError(tab, error);
      return;
    }
    if (state.tab !== tab) return;
    render();
  }

  /* ---------------- 弹窗 ---------------- */

  function openModal(title, bodyHtml) {
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body').innerHTML = bodyHtml;
    document.getElementById('modal-backdrop').hidden = false;
  }

  function closeModal() {
    document.getElementById('modal-backdrop').hidden = true;
    state.pending = null;
  }

  function confirmAction(message, action, payload) {
    state.pending = { action, payload };
    openModal('确认', `<p>${esc(message)}</p>
      <div class="row" style="justify-content:flex-end;margin-top:16px">
        <button class="button" data-action="modal-cancel">取消</button>
        <button class="button button-primary" data-action="modal-confirm">确定</button>
      </div>`);
  }

  const MODAL_FORMS = {
    'save-task': (fields, payload) => api('update_task', Number(payload.id), fields.title, fields.due_date, fields.tag, Number(fields.priority)),
    'save-objective': (fields, payload) => (payload.id
      ? api('update_objective', Number(payload.id), fields.title, fields.cadence, Number(fields.year), fields.period_start, fields.period_end, fields.note, fields.manual_progress)
      : api('add_objective', fields.title, fields.cadence, Number(fields.year), fields.period_start, fields.period_end, fields.note)),
    'save-kr': (fields, payload) => (payload.id
      ? api('update_kr', Number(payload.id), fields.name, Number(fields.start_value), Number(fields.current_value), Number(fields.target_value), fields.unit, Number(fields.weight))
      : api('add_kr', Number(payload.objective_id), fields.name, Number(fields.start_value), Number(fields.current_value), Number(fields.target_value), fields.unit, Number(fields.weight))),
    'save-entry': (fields, payload) => api('update_entry', Number(payload.id), fields.day, Number(fields.amount), fields.direction, fields.category, fields.method, fields.note, fields.currency || 'CNY'),
    'save-holiday': (fields) => api('set_holiday', fields.day, fields.type, fields.name)
  };

  /* ---------------- 事件 ---------------- */

  document.getElementById('nav').addEventListener('click', (event) => {
    const button = event.target.closest('.nav-item');
    // 引导数据（state.boot）没就绪前点导航会拿一堆空年份/空月份去请求，
    // 除了制造「0 年 0 月」这种怪页面没有任何好处，直接忽略。
    if (button && state.boot) {
      switchTab(button.dataset.tab).catch((error) => {
        console.error(error);
        renderTabError(button.dataset.tab, error);
      });
    }
  });

  document.getElementById('open-data-home').addEventListener('click', () => api('open_data_home'));

  document.getElementById('modal-close').addEventListener('click', closeModal);

  document.getElementById('modal-backdrop').addEventListener('click', (event) => {
    if (event.target.id === 'modal-backdrop') closeModal();
  });

  document.addEventListener('click', async (event) => {
    const trigger = event.target.closest('[data-action]');
    if (!trigger || trigger.tagName === 'FORM') return;

    const action = trigger.dataset.action;
    try {
      await handleAction(action, trigger);
    } catch (error) {
      console.error(error);
      alert(`${action} 失败：${error.message || error}`);
    }
  });

  document.addEventListener('submit', async (event) => {
    const form = event.target;
    if (!form.dataset || !form.dataset.action) return;
    event.preventDefault();

    const action = form.dataset.action;
    try {
      await handleSubmit(action, form);
    } catch (error) {
      console.error(error);
      alert(`${action} 失败：${error.message || error}`);
    }
  });

  document.addEventListener('change', async (event) => {
    const input = event.target;

    if (input.dataset.action === 'objective-period') {
      fillObjectivePeriod(input);
      return;
    }

    if (input.dataset.action !== 'kr-value') return;
    try {
      await api('set_kr_value', Number(input.dataset.id), Number(input.value));
      await loadOkr();
      render();
    } catch (error) {
      console.error(error);
    }
  });

  async function handleAction(action, trigger) {
    const id = trigger.dataset.id;

    switch (action) {
      case 'modal-cancel': closeModal(); return;
      case 'retry-tab': {
        const tab = state.tab;
        state[tab] = null; // 清掉失败标记，switchTab 会重新显示加载占位再取数
        await switchTab(tab);
        return;
      }
      case 'modal-confirm': {
        const pending = state.pending;
        closeModal();
        if (pending) await pending.action(pending.payload);
        await reload();
        return;
      }

      case 'toggle-task': {
        const task = state.tasksIndex[String(id)];
        await api('set_task_done', Number(id), !task.done);
        await reload();
        return;
      }
      case 'postpone-task': {
        const task = state.tasksIndex[String(id)];
        await api('postpone_task', Number(id), addDays(task.due_date, 1));
        await reload();
        return;
      }
      case 'edit-task': {
        const task = state.tasksIndex[String(id)];
        openModal('编辑任务', `
          <form data-action="save-task" data-id="${id}">
            <div class="field"><span class="field-label">标题</span>
              <input type="text" name="title" value="${esc(task.title)}" required></div>
            <div class="row" style="margin-top:10px">
              <div class="field"><span class="field-label">日期</span>
                <input type="date" name="due_date" value="${esc(task.due_date)}"></div>
              <div class="field"><span class="field-label">标签</span>
                <input type="text" name="tag" value="${esc(task.tag)}"></div>
              <div class="field"><span class="field-label">优先级</span>
                <select name="priority">
                  <option value="2" ${task.priority === 2 ? 'selected' : ''}>高</option>
                  <option value="1" ${task.priority === 1 ? 'selected' : ''}>中</option>
                  <option value="0" ${task.priority === 0 ? 'selected' : ''}>低</option>
                </select></div>
            </div>
            <div class="row" style="justify-content:flex-end;margin-top:16px">
              <button type="button" class="button" data-action="modal-cancel">取消</button>
              <button class="button button-primary">保存</button>
            </div>
          </form>`);
        return;
      }
      case 'delete-task':
        confirmAction('删掉这条任务？删了就找不回来了。', async (payload) => {
          await api('delete_task', Number(payload.id));
        }, { id });
        return;

      case 'toggle-habit':
        await api('toggle_habit', Number(id), trigger.dataset.day);
        await reload();
        return;
      case 'delete-habit':
        confirmAction('删掉这个习惯？它的历史打勾也会一起消失。', async (payload) => {
          await api('delete_habit', Number(payload.id));
        }, { id });
        return;

      /* 日历 */
      case 'calendar-prev': {
        const date = new Date(state.calendarCursor.year, state.calendarCursor.month - 2, 1);
        state.calendarCursor = { year: date.getFullYear(), month: date.getMonth() + 1 };
        await reload();
        return;
      }
      case 'calendar-next': {
        const date = new Date(state.calendarCursor.year, state.calendarCursor.month, 1);
        state.calendarCursor = { year: date.getFullYear(), month: date.getMonth() + 1 };
        await reload();
        return;
      }
      case 'calendar-today': {
        const date = parseIso(state.boot.today);
        state.calendarCursor = { year: date.getFullYear(), month: date.getMonth() + 1 };
        await reload();
        return;
      }

      /* 行情 */
      case 'market-refresh':
        // 强制后台刷新：本地数据先渲染，进度走轮询，不阻塞其他页签
        await loadMarket(true);
        return;
      case 'watch-remove':
        confirmAction('把这个标的移出自选？历史快照保留。', async (payload) => {
          await api('market_watch_remove', Number(payload.id));
        }, { id });
        return;
      case 'open-day': {
        const day = await api('calendar_day', trigger.dataset.day);
        openModal(`${day.day} 这一天的全貌`, `
          <div class="row" style="gap:10px;align-items:center">
            <span class="small muted">繁忙度</span>
            <span class="busy-dots"><span class="on">${'●'.repeat(day.busy)}</span><span class="off">${'○'.repeat(4 - day.busy)}</span></span>
            ${day.holiday ? `<span class="small muted">${esc(day.holiday.name)}（${esc(day.holiday.type === 'holiday' ? '放假' : '调休上班')}）</span>` : ''}
          </div>
          <h4 style="margin:12px 0 4px">任务</h4>
          ${day.tasks.length
    ? day.tasks.map((task) => `<div class="check-item ${task.done ? 'is-done' : ''}">
              <span class="check ${task.done ? 'is-done' : ''}">${task.done ? '✓' : ''}</span>
              <span class="check-title">${esc(task.title)}</span></div>`).join('')
    : '<div class="empty" style="padding:6px">这天没有任务</div>'}
          <h4 style="margin:12px 0 4px">习惯</h4>
          ${day.habits.length
    ? day.habits.map((habit) => `<div class="habit-row">
              <span class="check ${habit.done ? 'is-done' : ''}">${habit.done ? '✓' : ''}</span>
              <span class="check-title">${esc(habit.name)}</span></div>`).join('')
    : '<div class="empty" style="padding:6px">没有习惯</div>'}
          <h4 style="margin:12px 0 4px">记账</h4>
          ${day.entries.length
    ? day.entries.map((entry) => `<div class="entry-row">
              <span class="chip">${esc(entry.category)}</span>
              <span class="money ${entry.direction === 'income' ? 'money-income' : 'money-expense'}">
                ${entry.direction === 'income' ? '+' : '-'}${Views.plainMoney(entry.amount)}</span>
              <span class="muted small" style="flex:1">${esc(entry.note)}</span></div>`).join('')
    : '<div class="empty" style="padding:6px">这天没有记账</div>'}
          <h4 style="margin:12px 0 4px">饮食</h4>
          ${day.diet.slots.map((slot) => `<div class="row" style="padding:2px 0">
              <span class="meal-name">${esc(slot.label)}</span>
              <span class="muted small">${esc(slot.content || '未记录')}</span></div>`).join('')}
          <div class="small muted" style="margin-top:6px">饮水 ${day.diet.water_cups} 杯${day.weighed ? ' · 称过体重' : ''}</div>
          <div class="row" style="justify-content:flex-end;margin-top:16px">
            <button class="button" data-action="modal-cancel">关闭</button>
          </div>`);
        return;
      }

      /* OKR */
      case 'okr-prev': state.okrYear -= 1; await reload(); return;
      case 'okr-next': state.okrYear += 1; await reload(); return;
      case 'new-objective':
        openObjectiveModal(null);
        return;
      case 'edit-objective':
        openObjectiveModal(id);
        return;
      case 'delete-objective':
        confirmAction('删掉这个目标？它下面的关键结果会一起消失。', async (payload) => {
          await api('delete_objective', Number(payload.id));
        }, { id });
        return;
      case 'add-kr':
        openKrModal(null, id);
        return;
      case 'edit-kr':
        openKrModal(id, null);
        return;
      case 'delete-kr':
        confirmAction('删掉这个关键结果？', async (payload) => {
          await api('delete_kr', Number(payload.id));
        }, { id });
        return;

      /* 记账 */
      case 'ledger-prev': state.ledgerMonth = shiftMonth(state.ledgerMonth, -1); await reload(); return;
      case 'ledger-next': state.ledgerMonth = shiftMonth(state.ledgerMonth, 1); await reload(); return;
      case 'ledger-today': state.ledgerMonth = monthKeyOf(state.boot.today); await reload(); return;
      case 'edit-entry': {
        const entry = state.ledger.entries.find((item) => String(item.id) === String(id));
        openModal('编辑流水', `
          <form data-action="save-entry" data-id="${id}">
            <div class="form-row">
              <div class="field"><span class="field-label">日期</span><input type="date" name="day" value="${esc(entry.day)}"></div>
              <div class="field"><span class="field-label">方向</span>
                <select name="direction">
                  <option value="expense" ${entry.direction === 'expense' ? 'selected' : ''}>支出</option>
                  <option value="income" ${entry.direction === 'income' ? 'selected' : ''}>收入</option>
                </select></div>
              <div class="field"><span class="field-label">金额</span><input type="number" step="0.01" name="amount" value="${entry.amount}"></div>
            </div>
            <div class="form-row" style="margin-top:10px">
              <div class="field"><span class="field-label">币种</span>
                <select name="currency">${(state.ledger.currencies || []).map((item) =>
    `<option value="${esc(item.code)}" ${item.code === (entry.currency || 'CNY') ? 'selected' : ''}>${esc(item.name)}</option>`).join('')}</select></div>
              <div class="field"><span class="field-label">分类</span>
                <select name="category">${state.ledger.categories.map((category) =>
    `<option ${category === entry.category ? 'selected' : ''}>${esc(category)}</option>`).join('')}</select></div>
              <div class="field"><span class="field-label">支付方式</span><input type="text" name="method" value="${esc(entry.method)}"></div>
            </div>
            <div class="field" style="margin-top:10px"><span class="field-label">备注</span>
              <input type="text" name="note" value="${esc(entry.note)}"></div>
            <div class="row" style="justify-content:flex-end;margin-top:16px">
              <button type="button" class="button" data-action="modal-cancel">取消</button>
              <button class="button button-primary">保存</button>
            </div>
          </form>`);
        return;
      }
      case 'delete-entry':
        confirmAction('删掉这笔流水？', async (payload) => {
          await api('delete_entry', Number(payload.id));
        }, { id });
        return;
      case 'clear-total-budget':
        confirmAction('清除本月总预算？', async () => {
          await api('delete_budget', Number(state.ledger.budget.total.id), state.ledgerMonth);
        }, {});
        return;
      case 'clear-category-budget':
        confirmAction(`清除「${trigger.dataset.category}」的预算？`, async (payload) => {
          const budget = state.ledger.budget.by_category.find((item) => item.category === payload.category);
          if (budget) await api('delete_budget', Number(budget.id), state.ledgerMonth);
        }, { category: trigger.dataset.category });
        return;

      /* 饮食 */
      case 'diet-prev': state.dietDay = addDays(state.dietDay, -1); await reload(); return;
      case 'diet-next': state.dietDay = addDays(state.dietDay, 1); await reload(); return;
      case 'diet-today': state.dietDay = state.boot.today; await reload(); return;
      case 'open-food-picker': {
        const slot = trigger.dataset.slot;
        state.foodSlot = slot;
        const foods = await api('food_search', '');
        openModal('从常见菜名挑', `
          <form class="row" data-action="food-search">
            <input type="text" name="keyword" placeholder="搜菜名，比如 米饭 / 鸡胸肉" style="flex:1">
            <button class="button">搜索</button>
          </form>
          <div id="food-list" style="margin-top:10px">${Views.foodPicker(foods, slot)}</div>
          <div class="row" style="justify-content:flex-end;margin-top:16px">
            <button type="button" class="button" data-action="modal-cancel">关闭</button>
          </div>`);
        return;
      }
      case 'add-food': {
        await api(
          'add_food_to_meal', state.diet.day, trigger.dataset.slot, trigger.dataset.name
        );
        closeModal();
        await loadDiet();
        render();
        return;
      }
      case 'insert-phrase': {
        const slot = state.diet.slots.find((item) => item.slot === trigger.dataset.slot);
        const textarea = view.querySelector(`form[data-action="save-meal"][data-slot="${trigger.dataset.slot}"] textarea`);
        const addition = trigger.dataset.text;
        textarea.value = `${textarea.value ? textarea.value + '、' : ''}${addition}`;
        await api('save_meal', state.dietDay, slot.slot, textarea.value);
        await reload();
        return;
      }
      case 'delete-phrase':
        await api('delete_phrase', Number(id));
        await reload();
        return;
      case 'go-diet':
        await switchTab('diet');
        return;
      case 'go-body':
        await switchTab('body');
        return;

      /* 身体 */
      case 'delete-weigh-in':
        confirmAction('删掉这次称量？', async (payload) => {
          await api('delete_weigh_in', payload.day);
        }, { day: trigger.dataset.day });
        return;

      /* 年度总览 */
      case 'year-prev': state.yearView -= 1; await reload(); return;
      case 'year-next': state.yearView += 1; await reload(); return;
      case 'heatmap': {
        document.getElementById('heatmap-body').innerHTML = Views.heatmapFor(state.year, trigger.dataset.source);
        document.querySelectorAll('[data-action="heatmap"]').forEach((button) => {
          button.classList.toggle('is-active', button === trigger);
        });
        const labels = {
          tasks: '任务完成情况', habits: '习惯打卡', expense: '每日花销', meals: '饮食记录', weigh: '称量记录'
        };
        document.getElementById('heatmap-label').textContent = labels[trigger.dataset.source] || '';
        return;
      }

      /* 设置 */
      case 'open-data-home': await api('open_data_home'); return;
      case 'backup-now': {
        const result = await api('backup_now');
        showSettingsStatus(`已备份到 ${result.path}（${result.size_human}）`);
        await reload();
        return;
      }
      case 'export-json': {
        const result = await api('export_json');
        showSettingsStatus(`已导出 ${result.path}（${result.size_human}）`);
        return;
      }
      case 'export-csv': {
        const result = await api('export_csv');
        showSettingsStatus(`已导出 ${result.path}（${result.size_human}）`);
        return;
      }
      case 'move-data-home': {
        const target = window.prompt('把数据家搬到哪里？填完整路径，例如 D:\\PersonalHubData');
        if (!target) return;
        await api('move_data_home', target);
        showSettingsStatus(`数据家已搬到 ${target}`);
        await loadSettings();
        render();
        refreshSidebar();
        return;
      }
      case 'holiday-prev': state.holidayYear -= 1; await reload(); return;
      case 'holiday-next': state.holidayYear += 1; await reload(); return;
      case 'add-holiday':
        openModal('添加节假日', `
          <form data-action="save-holiday">
            <div class="row">
              <div class="field"><span class="field-label">日期</span><input type="date" name="day" required></div>
              <div class="field"><span class="field-label">类型</span>
                <select name="type"><option value="holiday">放假</option><option value="workday">调休上班</option></select></div>
              <div class="field" style="flex:1"><span class="field-label">名称</span><input type="text" name="name" placeholder="国庆节" style="width:100%"></div>
            </div>
            <div class="row" style="justify-content:flex-end;margin-top:16px">
              <button type="button" class="button" data-action="modal-cancel">取消</button>
              <button class="button button-primary">保存</button>
            </div>
          </form>`);
        return;
      case 'delete-holiday':
        await api('delete_holiday', trigger.dataset.day);
        await reload();
        return;
      case 'delete-category':
        await api('delete_category', trigger.dataset.name);
        await reload();
        return;

      /* 联网 */
      case 'toggle-net':
        await api('set_net_enabled', trigger.checked);
        await loadSettings();
        render();
        return;
      case 'sync-now': {
        const results = await api('sync_now');
        await loadSettings();
        render();
        showSettingsStatus(describeSync(results));
        return;
      }
      case 'sync-holidays': {
        const result = await api('sync_holidays_now', Number(trigger.dataset.year));
        await loadSettings();
        render();
        showSettingsStatus(describeSync([result]));
        return;
      }

      default:
        return;
    }
  }

  /** 选了周期、年份、期号就把起止日期算出来，省得手敲。 */
  function fillObjectivePeriod(input) {
    const form = input.closest('form');
    if (!form) return;

    const cadence = form.querySelector('[name=cadence]').value;
    if (cadence === 'week') return; // 每周的区间自己填，周序号容易算错

    const year = Number(form.querySelector('[name=year]').value);
    const index = Number(form.querySelector('[name=period_index]').value || 1);

    let firstMonth = 1;
    let months = 12;
    if (cadence === 'quarter') {
      firstMonth = (index - 1) * 3 + 1;
      months = 3;
    } else if (cadence === 'month') {
      firstMonth = index;
      months = 1;
    }

    const start = `${year}-${pad(firstMonth)}-01`;
    const end = isoOf(new Date(year, firstMonth - 1 + months, 0));
    form.querySelector('[name=period_start]').value = start;
    form.querySelector('[name=period_end]').value = end;
  }

  function describeSync(results) {
    if (!results || !results.length) return '联网已关闭，一个请求都没发';
    return results.map((result) => {
      const label = result.source_label || result.source;
      if (!result.ok) return `${label}：${result.reason || '没拿到数据'}`;
      if (result.source === 'holidays') {
        const parts = [`${result.year} 年新增 ${result.added} 天`];
        if (result.updated) parts.push(`更新 ${result.updated} 天`);
        if (result.conflicts && result.conflicts.length) {
          parts.push(`${result.conflicts.length} 天与线上不一致（你手改过的没动）`);
        }
        return `${label}：${parts.join('，')}`;
      }
      return `${label}：${result.updated} 个币种`;
    }).join(' · ');
  }

  function showSettingsStatus(text) {
    const line = document.getElementById('settings-status');
    if (line) line.textContent = text;
  }

  function openObjectiveModal(objective_id) {
    const objective = objective_id ? state.okr.objectives.find((item) => String(item.id) === String(objective_id)) : null;
    const year = objective ? objective.year : state.okrYear;
    const periodIndex = objective && objective.period_start
      ? (objective.cadence === 'quarter'
        ? Math.floor((Number(objective.period_start.slice(5, 7)) - 1) / 3) + 1
        : Number(objective.period_start.slice(5, 7)))
      : 1;
    const cadences = state.okr && state.okr.cadences
      ? state.okr.cadences
      : [['year', '年度'], ['quarter', '季度'], ['month', '月度'], ['week', '每周']].map(([value, label]) => ({ cadence: value, label }));
    openModal(objective ? '编辑目标' : '新建目标', `
      <form data-action="save-objective" ${objective ? `data-id="${objective.id}"` : ''}>
        <div class="field"><span class="field-label">目标</span>
          <input type="text" name="title" value="${esc(objective ? objective.title : '')}" required></div>
        <div class="form-row" style="margin-top:10px">
          <div class="field"><span class="field-label">周期</span>
            <select name="cadence" data-action="objective-period">
              ${cadences.map((item) =>
    `<option value="${item.cadence}" ${objective && objective.cadence === item.cadence ? 'selected' : ''}>${esc(item.label)}</option>`).join('')}
            </select></div>
          <div class="field"><span class="field-label">年份</span>
            <input type="number" name="year" value="${year}" data-action="objective-period"></div>
          <div class="field"><span class="field-label">期号 <span class="field-hint">季度 1-4 / 月度 1-12</span></span>
            <input type="number" name="period_index" min="1" max="12" value="${periodIndex}" data-action="objective-period"></div>
        </div>
        <div class="form-row" style="margin-top:10px">
          <div class="field"><span class="field-label">开始</span><input type="date" name="period_start" value="${esc(objective && objective.period_start ? objective.period_start : '')}"></div>
          <div class="field"><span class="field-label">结束</span><input type="date" name="period_end" value="${esc(objective && objective.period_end ? objective.period_end : '')}"></div>
        </div>
        <div class="field" style="margin-top:10px"><span class="field-label">手动覆盖进度 <span class="field-hint">0-100，留空则按关键结果加权</span></span>
          <input type="number" name="manual_progress" min="0" max="100"
            value="${objective && objective.manual_progress !== null ? objective.manual_progress : ''}" style="width:110px"></div>
        <div class="field" style="margin-top:10px"><span class="field-label">备注</span>
          <textarea name="note">${esc(objective ? objective.note : '')}</textarea></div>
        <div class="row" style="justify-content:flex-end;margin-top:16px">
          <button type="button" class="button" data-action="modal-cancel">取消</button>
          <button class="button button-primary">保存</button>
        </div>
      </form>`);
  }

  function openKrModal(kr_id, objective_id) {
    let kr = null;
    if (kr_id) {
      state.okr.objectives.forEach((objective) => {
        const found = objective.key_results.find((item) => String(item.id) === String(kr_id));
        if (found) kr = found;
      });
    }
    openModal(kr ? '编辑关键结果' : '添加关键结果', `
      <form data-action="save-kr" ${kr ? `data-id="${kr.id}"` : `data-objective_id="${objective_id}"`}>
        <div class="field"><span class="field-label">名称</span>
          <input type="text" name="name" value="${esc(kr ? kr.name : '')}" required style="width:100%"></div>
        <div class="form-row" style="margin-top:10px">
          <div class="field"><span class="field-label">起始值</span>
            <input type="number" step="any" name="start_value" value="${kr ? kr.start_value : 0}"></div>
          <div class="field"><span class="field-label">当前值</span>
            <input type="number" step="any" name="current_value" value="${kr ? kr.current_value : 0}"></div>
          <div class="field"><span class="field-label">目标值</span>
            <input type="number" step="any" name="target_value" value="${kr ? kr.target_value : 100}"></div>
          <div class="field"><span class="field-label">单位</span>
            <input type="text" name="unit" value="${esc(kr ? kr.unit : '')}"></div>
          <div class="field"><span class="field-label">权重</span>
            <input type="number" step="any" name="weight" value="${kr ? kr.weight : 1}"></div>
        </div>
        <p class="small muted" style="margin-top:10px">反向目标（比如体重从 80 降到 70）直接填小一点的目标值即可，不用额外标记方向。</p>
        <div class="row" style="justify-content:flex-end;margin-top:16px">
          <button type="button" class="button" data-action="modal-cancel">取消</button>
          <button class="button button-primary">保存</button>
        </div>
      </form>`);
  }

  async function handleSubmit(action, form) {
    const fields = {};
    new FormData(form).forEach((value, key) => { fields[key] = value; });

    if (MODAL_FORMS[action]) {
      await MODAL_FORMS[action](fields, form.dataset);
      closeModal();
      await reload();
      return;
    }

    switch (action) {
      case 'add-task':
        await api('add_task', fields.title, fields.due_date, fields.tag || '', Number(fields.priority));
        form.reset();
        break;
      case 'add-habit':
        await api('add_habit', fields.name, fields.cadence);
        form.reset();
        break;
      case 'add-entry':
        await api('add_entry', fields.day, Number(fields.amount), fields.direction, fields.category, fields.method || '', fields.note || '', fields.currency || 'CNY');
        form.reset();
        break;
      case 'quick-entry':
        await api('add_entry', state.home.today, Number(fields.amount), 'expense', fields.category, '', fields.note || '');
        form.reset();
        break;
      case 'set-budget':
        await api('set_budget', fields.scope, fields.scope === 'total' ? '' : fields.category, state.ledgerMonth, Number(fields.limit_amount));
        form.reset();
        break;
      case 'save-meal':
        await api('save_meal', state.dietDay, form.dataset.slot, fields.content);
        break;
      case 'set-water':
        await api('set_water', state.dietDay, Number(fields.cups));
        break;
      case 'add-phrase':
        await api('add_phrase', fields.text);
        form.reset();
        break;
      case 'add-weigh-in':
        await api('save_weigh_in', fields.day, fields.weight, fields.body_fat, fields.note || '');
        form.reset();
        break;
      case 'save-targets':
        await api('save_body_targets', fields.target_weight, fields.target_body_fat);
        break;
      case 'import-holidays':
        await api('import_holidays', fields.text);
        form.reset();
        break;
      case 'watch-add':
        await api('market_watch_add', fields.code.trim());
        form.reset();
        break;
      case 'add-category':
        await api('add_category', fields.name);
        form.reset();
        break;
      case 'food-search': {
        const foods = await api('food_search', fields.keyword || '');
        const list = document.getElementById('food-list');
        if (list) list.innerHTML = Views.foodPicker(foods, state.foodSlot);
        return;
      }
      default:
        return;
    }

    await reload();
    if (state.tab === 'home') renderNudges();
  }

  /* ---------------- 主题（白天 / 黑夜一键切换） ---------------- */

  // 主题存在 html 的 data-theme 上；状态记 localStorage，首次运行跟随系统。
  function getStoredTheme() {
    try { return localStorage.getItem('ph-theme'); } catch (error) { return null; }
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    const button = document.getElementById('theme-toggle');
    if (button) button.textContent = theme === 'dark' ? '☀️' : '🌙';
  }

  function initTheme() {
    let theme = getStoredTheme();
    if (!theme) {
      const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
      theme = prefersDark ? 'dark' : 'light';
    }
    applyTheme(theme);

    const button = document.getElementById('theme-toggle');
    if (button) {
      button.addEventListener('click', () => {
        const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
        applyTheme(next);
        try { localStorage.setItem('ph-theme', next); } catch (error) { /* 隐私模式忽略 */ }
      });
    }
  }

  initTheme();

  /* ---------------- 启动 ---------------- */

  function refreshSidebar() {
    const info = state.boot;
    document.getElementById('brand-version').textContent = `v${info.app_version}`;
    document.getElementById('sidebar-data').innerHTML =
      `数据家 ${esc(info.data_home)}<br>占用 ${esc(info.db_size_human)} · 备份 ${info.backup_count} 份`;
    document.getElementById('today-label').textContent = `${info.today}`;
  }

  async function boot() {
    await waitForBridge();
    // 冷启动时接口可能刚挂上还没稳，多试几次自己缓过来，别一上来就甩失败页
    let info = null;
    for (let attempt = 1; attempt <= 4; attempt++) {
      try {
        info = await api('bootstrap');
        break;
      } catch (err) {
        if (attempt >= 4) throw err;
        await new Promise((resolve) => setTimeout(resolve, 250 * attempt));
      }
    }
    if (!info) throw new Error('bootstrap 调用失败');

    state.boot = info;
    const today = parseIso(state.boot.today);
    state.calendarCursor = { year: today.getFullYear(), month: today.getMonth() + 1 };
    state.okrYear = today.getFullYear();
    state.ledgerMonth = monthKeyOf(state.boot.today);
    state.dietDay = state.boot.today;
    state.holidayYear = today.getFullYear();
    state.yearView = today.getFullYear();

    refreshSidebar();
    await switchTab('home');
  }

  function renderBootError(error) {
    view.innerHTML = `<div class="card"><h2 class="card-title">启动失败</h2>
      <p class="muted">${esc(error.message || error)}</p>
      <div class="row" style="margin-top:12px">
        <button class="button button-primary" data-action="retry-boot">重试</button>
      </div></div>`;
  }

  boot().catch((error) => {
    console.error(error);
    renderBootError(error);
  });

  document.getElementById('view').addEventListener('click', (event) => {
    if (event.target.closest('[data-action="retry-boot"]')) {
      view.innerHTML = `
        <div class="card loading-card">
          <span class="loading-spinner" aria-hidden="true"></span>
          <span class="muted">正在重新连接…</span>
        </div>`;
      boot().catch((error) => {
        console.error(error);
        renderBootError(error);
      });
    }
  });
})();
