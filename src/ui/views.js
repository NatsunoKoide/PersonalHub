/* 各页签的 HTML 渲染。交互一律通过 data-action 交给 app.js 处理。 */
(function (global) {
  'use strict';

  const esc = (value) => Charts.escapeText(value === null || value === undefined ? '' : value);

  function money(value) {
    const amount = Number(value || 0);
    return '¥' + amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function plainMoney(value) {
    return Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function pct(rate) {
    return Math.round((rate || 0) * 100) + '%';
  }

  const PRIORITY_CHIP = { 2: 'chip-high', 1: 'chip-mid', 0: 'chip-low' };
  const PRIORITY_TEXT = { 2: '高', 1: '中', 0: '低' };

  /* ---------------- 任务与习惯的共用片段 ---------------- */

  function taskItem(task) {
    return `<div class="check-item ${task.done ? 'is-done' : ''}">
      <button class="check ${task.done ? 'is-done' : ''}" data-action="toggle-task" data-id="${task.id}" title="核销">${task.done ? '✓' : ''}</button>
      <span class="check-title">${esc(task.title)}</span>
      ${task.tag ? `<span class="chip">${esc(task.tag)}</span>` : ''}
      <span class="chip ${PRIORITY_CHIP[task.priority]}">${PRIORITY_TEXT[task.priority]}</span>
      <button class="icon-button" data-action="postpone-task" data-id="${task.id}" title="顺延到明天">»</button>
      <button class="icon-button" data-action="edit-task" data-id="${task.id}" title="编辑">✎</button>
      <button class="icon-button" data-action="delete-task" data-id="${task.id}" title="删除">×</button>
    </div>`;
  }

  function taskList(items, emptyText) {
    if (!items.length) return `<div class="empty">${esc(emptyText || '这里空空如也')}</div>`;
    return items.map(taskItem).join('');
  }

  function habitItem(habit, day) {
    return `<div class="habit-row">
      <button class="check ${habit.done ? 'is-done' : ''}" data-action="toggle-habit" data-id="${habit.id}" data-day="${day}">${habit.done ? '✓' : ''}</button>
      <span class="check-title ${habit.done ? '' : 'soft'}">${esc(habit.name)}</span>
      <span class="chip">${habit.cadence === 'weekly' ? '每周' : '每日'}</span>
      <span class="streak">🔥 ${habit.streak || 0}</span>
      <span class="muted small">本月 ${habit.done_count}/${habit.expected}</span>
      <button class="icon-button" data-action="delete-habit" data-id="${habit.id}" title="删除">×</button>
    </div>`;
  }

  function habitList(items, day) {
    if (!items.length) return '<div class="empty">还没有习惯，加一个每天要坚持的事</div>';
    return items.map((habit) => habitItem(habit, day)).join('');
  }

  /* ---------------- 概览 ---------------- */

  function home(data) {
    const taskRows = data.tasks.map(taskItem).join('');
    const habitRows = habitList(data.habits, data.today);

    return `
      <div class="page-head">
        <div>
          <h1 class="page-title">今天</h1>
          <p class="page-sub">${esc(data.today_label)}</p>
        </div>
        <div class="row">
          <span class="chip chip-ok">习惯 ${data.habit_today.done}/${data.habit_today.total}</span>
          <span class="chip">今日花销 ${money(data.today_expense)}</span>
        </div>
      </div>

      <div class="grid-2">
        <div class="card">
          <div class="card-head"><h2 class="card-title">今日待办</h2>
            <span class="card-hint">${data.tasks.filter((t) => !t.done).length} 项未完成</span></div>
          ${taskRows || '<div class="empty">今天没有安排，加一条试试</div>'}
          <form class="row" style="margin-top:12px" data-action="add-task">
            <input type="text" name="title" placeholder="要做的事" required style="flex:1">
            <input type="date" name="due_date" value="${data.today}" style="width:132px">
            <select name="priority"><option value="1">中</option><option value="2">高</option><option value="0">低</option></select>
            <button class="button button-primary">添加</button>
          </form>
        </div>

        <div class="card">
          <div class="card-head"><h2 class="card-title">今日习惯</h2>
            <span class="card-hint">本月坚持率 ${pct(averageRate(data.habits))}</span></div>
          ${habitRows}
          <form class="row" style="margin-top:12px" data-action="add-habit">
            <input type="text" name="name" placeholder="每天要坚持的事" required style="flex:1">
            <select name="cadence"><option value="daily">每日</option><option value="weekly">每周</option></select>
            <button class="button">添加</button>
          </form>
        </div>
      </div>

      <div class="grid-3">
        <div class="card">
          <div class="card-head"><h2 class="card-title">今日花销</h2></div>
          <div class="stat-block">
            <span class="stat-value money">${money(data.today_expense)}</span>
            <span class="stat-label">今天记的账</span>
          </div>
          <form class="row" style="margin-top:12px" data-action="quick-entry">
            <input type="number" step="0.01" name="amount" placeholder="金额" required style="width:88px">
            <select name="category">${data.categories ? data.categories.map((c) => `<option>${esc(c)}</option>`).join('') : '<option>其他</option>'}</select>
            <input type="text" name="note" placeholder="备注" style="flex:1">
            <button class="button button-primary">记一笔</button>
          </form>
        </div>

        <div class="card">
          <div class="card-head"><h2 class="card-title">今日饮食</h2>
            <span class="card-hint">${data.diet.recorded ? '已记 ' + data.diet.recorded + ' 餐' : '还没记录'}</span></div>
          ${data.diet.slots.map((slot) => `<div class="row" style="padding:3px 0">
              <span class="meal-name">${esc(slot.label)}</span>
              <span class="muted small" style="flex:1">${esc(slot.content || '未记录')}</span>
            </div>`).join('')}
          <div class="row" style="margin-top:10px">
            <span class="small muted">饮水 ${data.diet.water_cups} 杯</span>
            <span class="spacer"></span>
            <button class="button" data-action="go-diet">去记录</button>
          </div>
        </div>

        <div class="card">
          <div class="card-head"><h2 class="card-title">本周身体</h2>
            <span class="chip ${data.body.logged_this_week ? 'chip-ok' : 'chip-warn'}">${data.body.logged_this_week ? '已称重' : '未称重'}</span></div>
          ${data.body.latest
      ? `<div class="stat-block"><span class="stat-value">${data.body.latest.weight !== null ? data.body.latest.weight + ' kg' : '—'}</span>
              <span class="stat-label">${esc(data.body.latest.day)} 记录
              ${data.body_targets.target_weight ? '　目标 ' + data.body_targets.target_weight + ' kg' : ''}</span></div>
            <div class="small muted" style="margin-top:8px">体脂 ${data.body.latest.body_fat !== null ? data.body.latest.body_fat + '%' : '—'}</div>`
      : '<div class="empty">还没有称量记录</div>'}
          <div class="row" style="margin-top:10px">
            <button class="button" data-action="go-body">去记录</button>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-head"><h2 class="card-title">30 天内到期的目标</h2></div>
        ${data.upcoming_objectives.length
      ? data.upcoming_objectives.map((objective) => `<div class="row" style="padding:6px 0">
              <span style="flex:1">${esc(objective.title)}</span>
              <span class="chip">${esc(objective.cadence_label)}</span>
              <span class="small muted">${esc(objective.period_end)}</span>
              ${Charts.progressBar(objective.progress_percent)}
              <span class="small strong">${objective.progress_percent}%</span>
            </div>`).join('')
      : '<div class="empty">近 30 天没有到期的目标</div>'}
      </div>`;
  }

  function averageRate(items) {
    if (!items.length) return 0;
    return items.reduce((sum, item) => sum + (item.rate || 0), 0) / items.length;
  }

  /* ---------------- 日历 ---------------- */

  function calendar(data) {
    const weekdays = ['一', '二', '三', '四', '五', '六', '日'];
    const cells = data.weeks.map((week) => week.map((day) => {
      const classes = ['day-cell'];
      if (!day.in_month) classes.push('is-outside');
      if (day.is_today) classes.push('is-today');
      if (day.kind === 'holiday') classes.push('is-holiday');
      if (day.kind === 'workday') classes.push('is-workday');
      if (day.busy) classes.push(`is-busy-${day.busy}`);

      let flag = '';
      if (day.kind === 'holiday') flag = `<span class="day-flag">${esc(day.holiday_name)}</span>`;
      if (day.kind === 'workday') flag = '<span class="day-flag-work">调休上班</span>';

      const marks = [];
      if (day.tasks.total) marks.push(`<span class="mark-dot"></span>${day.tasks.done}/${day.tasks.total}`);
      if (day.habits_total) marks.push(`🔥${day.habits_done}/${day.habits_total}`);
      if (day.expense) marks.push(`<span class="mark-expense">${Charts.formatShort(day.expense)}</span>`);
      if (day.meals) marks.push(`<span class="mark-expense">🍽${day.meals}</span>`);
      if (day.weighed) marks.push('⚖');

      return `<button class="${classes.join(' ')}" data-action="open-day" data-day="${day.day}">
        <span class="day-number">${day.day_number}</span>
        ${flag}
        <span class="day-marks">${marks.join(' ')}</span>
      </button>`;
    }).join('')).join('');

    return `
      <div class="page-head">
        <div><h1 class="page-title">${data.year} 年 ${data.month} 月</h1>
          <p class="page-sub">点任意一天看当天全貌</p></div>
        <div class="row">
          <button class="button" data-action="calendar-prev">← 上月</button>
          <button class="button" data-action="calendar-today">回到今天</button>
          <button class="button" data-action="calendar-next">下月 →</button>
        </div>
      </div>
      <div class="card">
        <div class="calendar-grid">
          ${weekdays.map((name) => `<div class="calendar-weekday">${name}</div>`).join('')}
        </div>
        <div class="calendar-grid" style="margin-top:2px">${cells}</div>
        <div class="calendar-legend">
          <span class="small muted">繁忙度</span>
          <span class="heat-swatch heat-0"></span>
          <span class="heat-swatch heat-1"></span>
          <span class="heat-swatch heat-2"></span>
          <span class="heat-swatch heat-3"></span>
          <span class="heat-swatch heat-4"></span>
          <span class="small muted">颜色越深，当天越忙；点任意一天看明细</span>
        </div>
      </div>`;
  }

  /* ---------------- 任务与习惯 ---------------- */

  function tasks(data) {
    return `
      <div class="page-head">
        <div><h1 class="page-title">任务与习惯</h1>
          <p class="page-sub">任务是一次性的，习惯是重复的，两者的完成率分开统计</p></div>
        <div class="row">
          <span class="chip">今年任务 ${pct(data.year_task_rate)}</span>
          <span class="chip">今年习惯 ${pct(data.year_habit_rate)}</span>
        </div>
      </div>

      <div class="card">
        <div class="card-head"><h2 class="card-title">逾期未核销</h2>
          <span class="card-hint">${data.overdue.length} 项</span></div>
        ${taskList(data.overdue, '没有逾期，节奏不错')}
      </div>

      <div class="card">
        <div class="card-head"><h2 class="card-title">未来七天</h2></div>
        ${groupByDay(data.upcoming).map((group) => `
          <div style="margin-bottom:10px">
            <div class="small strong soft" style="margin-bottom:2px">${esc(group.day)}</div>
            ${group.items.map(taskItem).join('')}
          </div>`).join('') || '<div class="empty">未来七天还很空</div>'}
      </div>

      <div class="card">
        <div class="card-head"><h2 class="card-title">本月全部任务</h2>
          <span class="card-hint">共 ${data.month_tasks.length} 项</span></div>
        ${taskList(data.month_tasks, '本月还没有任务')}
      </div>

      <div class="card">
        <div class="card-head"><h2 class="card-title">习惯</h2>
          <span class="card-hint">本月坚持率 ${pct(averageRate(data.habits))}</span></div>
        ${habitList(data.habits, data.today)}
      </div>`;
  }

  function groupByDay(items) {
    const groups = [];
    items.forEach((item) => {
      let group = groups.find((candidate) => candidate.day === item.due_date);
      if (!group) {
        group = { day: item.due_date, items: [] };
        groups.push(group);
      }
      group.items.push(item);
    });
    return groups;
  }

  /* ---------------- OKR ---------------- */

  function okrView(data) {
    const rings = data.cadences.map((cadence, index) => `
      <div class="stat-block" style="align-items:center">
        ${Charts.ring(cadence.progress_percent, { size: 104, color: Charts.colorAt(index) })}
        <span class="stat-label">${esc(cadence.label)}目标 ${cadence.count} 个</span>
      </div>`).join('');

    const sections = data.cadences.map((cadence) => {
      const label = cadence.label;
      const items = data.objectives.filter((objective) => objective.cadence === cadence.cadence);
      return `<div class="card">
        <div class="card-head"><h2 class="card-title">${label}目标</h2>
          <span class="card-hint">${items.length} 个</span></div>
        <!-- 周期名称只有一处来源：后端 cadence_overview 给的 label -->
        ${items.length ? items.map(objectiveCard).join('')
    : `<div class="empty">还没有${label}目标</div>`}
      </div>`;
    }).join('');

    return `
      <div class="page-head">
        <div><h1 class="page-title">${data.year} 年目标</h1>
          <p class="page-sub">进度由关键结果按权重算出，也可手动覆盖</p></div>
        <div class="row">
          <button class="button" data-action="okr-prev">← ${data.year - 1}</button>
          <button class="button" data-action="okr-next">${data.year + 1} →</button>
          <button class="button button-primary" data-action="new-objective">新建目标</button>
        </div>
      </div>

      <div class="card"><div class="ring-row" style="justify-content:space-between">${rings}</div></div>
      ${sections}`;
  }

  function objectiveCard(objective) {
    return `<div class="objective" style="padding:12px 0;border-bottom:1px solid var(--line-2)">
      <div class="row">
        <span class="strong" style="flex:1">${esc(objective.title)}</span>
        ${objective.manual_progress !== null ? '<span class="chip chip-warn">手动覆盖</span>' : ''}
        <span class="chip">${esc(objective.cadence_label)}</span>
        <span class="small muted">${esc(objective.period_start || '')} → ${esc(objective.period_end || '')}</span>
        <button class="icon-button" data-action="edit-objective" data-id="${objective.id}">✎</button>
        <button class="icon-button" data-action="delete-objective" data-id="${objective.id}">×</button>
      </div>
      <div class="row" style="margin-top:6px">
        <div style="flex:1">${Charts.progressBar(objective.progress_percent)}</div>
        <span class="small strong" style="width:40px;text-align:right">${objective.progress_percent}%</span>
      </div>
      ${objective.key_results.length ? `<table class="table" style="margin-top:8px">
        <thead><tr><th>关键结果</th><th style="width:96px">当前</th><th style="width:110px">起始 → 目标</th><th style="width:52px">权重</th><th style="width:78px">进度</th><th style="width:56px"></th></tr></thead>
        <tbody>${objective.key_results.map((kr) => `<tr>
          <td>${esc(kr.name)}</td>
          <td><input type="number" step="any" value="${kr.current_value}" data-action="kr-value" data-id="${kr.id}" style="width:84px"></td>
          <td class="muted small">${kr.start_value} → ${kr.target_value} ${esc(kr.unit)}</td>
          <td class="muted small">${kr.weight}</td>
          <td class="small">${Math.round(kr.progress * 100)}%</td>
          <td>
            <button class="icon-button" data-action="edit-kr" data-id="${kr.id}">✎</button>
            <button class="icon-button" data-action="delete-kr" data-id="${kr.id}">×</button>
          </td>
        </tr>`).join('')}</tbody></table>`
      : '<div class="empty" style="padding:8px">还没有关键结果</div>'}
      <div class="row" style="margin-top:6px">
        <button class="button-ghost small" data-action="add-kr" data-id="${objective.id}">+ 关键结果</button>
      </div>
    </div>`;
  }

  /* ---------------- 记账 ---------------- */

  function ledgerView(data) {
    const summary = data.summary;
    const previous = data.previous;
    const delta = summary.expense - previous.expense;
    const items = summary.by_category.map((item, index) => ({
      label: item.category, value: item.amount, color: Charts.colorAt(index)
    }));
    const currencies = data.currencies && data.currencies.length
      ? data.currencies
      : [{ code: 'CNY', name: '人民币' }];

    return `
      <div class="page-head">
        <div><h1 class="page-title">${esc(data.month)} 账本</h1>
          <p class="page-sub">${data.entries.length} 笔记录</p></div>
        <div class="row">
          <button class="button" data-action="ledger-prev">←</button>
          <button class="button" data-action="ledger-today">本月</button>
          <button class="button" data-action="ledger-next">→</button>
        </div>
      </div>

      <div class="grid-3">
        <div class="card"><div class="stat-block">
          <span class="stat-value money money-expense">${money(summary.expense)}</span>
          <span class="stat-label">本月支出</span>
          <span class="small ${delta > 0 ? 'money-expense' : 'money-income'}">
            ${delta >= 0 ? '↑' : '↓'} 较上月 ${money(Math.abs(delta))}</span>
        </div></div>
        <div class="card"><div class="stat-block">
          <span class="stat-value money money-income">${money(summary.income)}</span>
          <span class="stat-label">本月收入</span>
        </div></div>
        <div class="card"><div class="stat-block">
          <span class="stat-value money">${money(summary.income - summary.expense)}</span>
          <span class="stat-label">结余</span>
        </div></div>
      </div>

      <div class="grid-2">
        <div class="card">
          <div class="card-head"><h2 class="card-title">分类占比</h2></div>
          <div class="row" style="align-items:flex-start;gap:18px">
            ${Charts.donut(items, { size: 200, thickness: 40 })}
            <div style="flex:1">${Charts.donutLegend(items.map((item) => ({
    ...item, text: plainMoney(item.value)
  })))}</div>
          </div>
        </div>

        <div class="card">
          <div class="card-head"><h2 class="card-title">近 12 个月支出</h2></div>
          ${Charts.bars(data.year_months.map((month) => ({ label: month.label, value: month.expense })))}
        </div>
      </div>

      <div class="card">
        <div class="card-head"><h2 class="card-title">记一笔</h2></div>
        <form class="row row-wrap" data-action="add-entry">
          <input type="date" name="day" value="${data.default_day}" style="width:132px">
          <select name="direction"><option value="expense">支出</option><option value="income">收入</option></select>
          <input type="number" step="0.01" name="amount" placeholder="金额" required style="width:100px">
          <select name="currency" title="选了外币会自动按汇率折成人民币">
            ${currencies.map((item) => `<option value="${esc(item.code)}">${esc(item.name)}</option>`).join('')}
          </select>
          <select name="category">${data.categories.map((category) => `<option>${esc(category)}</option>`).join('')}</select>
          <input type="text" name="method" placeholder="支付方式" style="width:110px">
          <input type="text" name="note" placeholder="备注" style="flex:1;min-width:120px">
          <button class="button button-primary">添加</button>
        </form>
      </div>

      <div class="card">
        <div class="card-head"><h2 class="card-title">本月明细</h2>
          <span class="card-hint">共 ${data.entries.length} 笔</span></div>
        ${data.entries.length ? data.entries.map((entry) => `<div class="entry-row">
            <span class="small muted" style="width:88px">${esc(entry.day)}</span>
            <span class="chip ${entry.direction === 'income' ? 'chip-ok' : 'chip-low'}"
              style="width:44px;justify-content:center">${entry.direction === 'income' ? '收入' : '支出'}</span>
            <span class="chip" style="width:44px;justify-content:center">${esc(entry.category)}</span>
            <span class="money ${entry.direction === 'income' ? 'money-income' : 'money-expense'}" style="width:150px">
              ${entry.direction === 'income' ? '+' : '-'}${plainMoney(entry.amount_cny)}
              ${entry.currency && entry.currency !== 'CNY'
    ? `<span class="small muted" style="margin-left:6px">${esc(entry.currency)} ${plainMoney(entry.amount)}</span>`
    : ''}</span>
            <span class="muted small" style="flex:1">${esc(entry.note)}</span>
            <button class="icon-button" data-action="edit-entry" data-id="${entry.id}">✎</button>
            <button class="icon-button" data-action="delete-entry" data-id="${entry.id}">×</button>
          </div>`).join('') : '<div class="empty">本月还没有记账</div>'}
      </div>

      <div class="card">
        <div class="card-head"><h2 class="card-title">预算</h2>
          <span class="card-hint">只在填了预算时才提示超支</span></div>
        ${data.budget.total ? `<div class="budget-row">
            <span style="width:60px">总额</span>
            <div style="flex:1">${Charts.progressBar(Math.min(100, data.budget.total.rate * 100), { color: data.budget.total.over ? 'var(--danger)' : 'var(--brand)' })}</div>
            <span class="small ${data.budget.total.over ? 'text-danger strong' : 'muted'}" style="width:150px;text-align:right">
              ${plainMoney(data.budget.total.used)} / ${plainMoney(data.budget.total.limit)}</span>
            <button class="button-ghost small" data-action="clear-total-budget">清除</button>
          </div>` : '<div class="empty" style="padding:6px">还没有设置本月总预算</div>'}
        ${data.budget.by_category.map((budget) => `<div class="budget-row">
            <span style="width:60px">${esc(budget.category)}</span>
            <div style="flex:1">${Charts.progressBar(Math.min(100, budget.rate * 100), { color: budget.over ? 'var(--danger)' : 'var(--brand)' })}</div>
            <span class="small ${budget.over ? 'text-danger strong' : 'muted'}" style="width:150px;text-align:right">
              ${plainMoney(budget.used)} / ${plainMoney(budget.limit)}</span>
            <button class="button-ghost small" data-action="clear-category-budget" data-category="${esc(budget.category)}">清除</button>
          </div>`).join('')}
        <form class="row" style="margin-top:10px" data-action="set-budget">
          <select name="scope"><option value="total">总额</option><option value="category">分类</option></select>
          <select name="category">${data.categories.map((category) => `<option>${esc(category)}</option>`).join('')}</select>
          <input type="number" step="0.01" name="limit_amount" placeholder="上限" required style="width:110px">
          <button class="button">保存预算</button>
        </form>
      </div>`;
  }

  /* ---------------- 饮食 ---------------- */

  function foodPicker(foods, slot) {
    if (!foods.length) {
      return '<div class="empty">没找到，换个词试试</div>';
    }
    return foods.map((food) => `<div class="food-item">
      <span class="strong" style="flex:1">${esc(food.name)}</span>
      <span class="small muted">${esc(food.portion_label)}</span>
      <button class="button button-primary" data-action="add-food"
        data-slot="${slot}" data-name="${esc(food.name)}">填入</button>
    </div>`).join('');
  }

  function dietView(data) {
    return `
      <div class="page-head">
        <div><h1 class="page-title">${esc(data.day)} 饮食</h1>
          <p class="page-sub">四餐加饮水，随手记，不用算热量</p></div>
        <div class="row">
          <button class="button" data-action="diet-prev">← 前一天</button>
          <button class="button" data-action="diet-today">今天</button>
          <button class="button" data-action="diet-next">后一天 →</button>
        </div>
      </div>

      <div class="card">
        <div class="card-head"><h2 class="card-title">三餐与加餐</h2>
          <span class="card-hint">已记 ${data.recorded} 餐 · 饮水 ${data.water_cups} 杯</span></div>
        ${data.slots.map((slot) => `
          <div class="meal-slot">
            <div class="meal-head"><span class="meal-name">${esc(slot.label)}</span></div>
            <form data-action="save-meal" data-slot="${slot.slot}">
              <textarea name="content" placeholder="吃了什么">${esc(slot.content)}</textarea>
              <div class="row" style="margin-top:6px">
                <span class="spacer"></span>
                <button class="button button-primary">保存</button>
              </div>
            </form>
            ${data.phrases.length ? `<div class="phrase-list" style="margin-top:6px">
              ${data.phrases.map((phrase) => `<button class="phrase" data-action="insert-phrase"
                data-slot="${slot.slot}" data-text="${esc(phrase.text)}">${esc(phrase.text)}</button>`).join('')}
            </div>` : ''}
            <div class="row" style="margin-top:6px">
              <button class="button-ghost small" data-action="open-food-picker"
                data-slot="${slot.slot}">＋ 从常见菜名挑</button>
            </div>
          </div>`).join('')}
      </div>

      <div class="grid-2">
        <div class="card">
          <div class="card-head"><h2 class="card-title">饮水</h2>
            <span class="card-hint">今天 ${data.water_cups} 杯</span></div>
          <form class="row" data-action="set-water">
            <input type="number" name="cups" value="${data.water_cups}" min="0" style="width:88px">
            <button class="button">更新</button>
          </form>
        </div>
        <div class="card">
          <div class="card-head"><h2 class="card-title">快捷短语</h2>
            <span class="card-hint">常吃的东西，一点就插进去</span></div>
          <div class="phrase-list">
            ${data.phrases.length ? data.phrases.map((phrase) => `<span class="phrase" style="display:inline-flex;align-items:center;gap:6px">
              ${esc(phrase.text)}
              <button class="icon-button" data-action="delete-phrase" data-id="${phrase.id}">×</button></span>`).join('')
    : '<span class="muted small">还没有短语</span>'}
          </div>
          <form class="row" style="margin-top:10px" data-action="add-phrase">
            <input type="text" name="text" placeholder="比如 燕麦 40g" required style="flex:1">
            <button class="button">添加</button>
          </form>
        </div>
      </div>`;
  }

  /* ---------------- 身体 ---------------- */

  function bodyView(data) {
    const weightPoints = data.series.filter((item) => item.weight !== null);
    const fatPoints = data.series.filter((item) => item.body_fat !== null);
    const targets = [
      data.targets.target_weight ? { value: data.targets.target_weight, label: '目标体重', color: '#3567dc' } : null,
      data.targets.target_body_fat ? { value: data.targets.target_body_fat, label: '目标体脂', color: '#d98324' } : null
    ].filter(Boolean);

    return `
      <div class="page-head">
        <div><h1 class="page-title">体重与体脂</h1>
          <p class="page-sub">每周记录一次就够了</p></div>
        <div class="row">
          <span class="chip ${data.week.logged_this_week ? 'chip-ok' : 'chip-warn'}">
            ${data.week.logged_this_week ? '本周已称重' : '本周还没称重'}</span>
        </div>
      </div>

      <div class="card">
        <div class="card-head"><h2 class="card-title">记录一次称量</h2></div>
        <form class="row row-wrap" data-action="add-weigh-in">
          <input type="date" name="day" value="${data.today}" style="width:132px">
          <input type="number" step="0.1" name="weight" placeholder="体重 kg" required style="width:110px">
          <input type="number" step="0.1" name="body_fat" placeholder="体脂 %" style="width:100px">
          <input type="text" name="note" placeholder="备注" style="flex:1;min-width:120px">
          <button class="button button-primary">保存</button>
        </form>
      </div>

      <div class="card">
        <div class="card-head"><h2 class="card-title">曲线</h2>
          <span class="card-hint">${data.series.length} 次记录</span></div>
        ${Charts.lines([
    {
      points: weightPoints.map((item) => ({ y: item.weight, label: item.day })),
      color: '#3567dc'
    },
    {
      points: fatPoints.map((item) => ({ y: item.body_fat, label: item.day })),
      color: '#15936d'
    }
  ], { targets, labels: weightPoints.map((item) => item.day.slice(5)) })}
        <div class="row" style="margin-top:8px">
          <span class="chip" style="background:var(--brand-soft);color:var(--brand-strong)">体重 kg</span>
          <span class="chip" style="background:var(--down-soft);color:#0f7a5a">体脂 %</span>
        </div>
      </div>

      <div class="card">
        <div class="card-head"><h2 class="card-title">身体目标</h2>
          <span class="card-hint">曲线上的虚线就是它</span></div>
        <form class="row row-wrap" data-action="save-targets">
          <input type="number" step="0.1" name="target_weight" placeholder="目标体重 kg" value="${data.targets.target_weight === null ? '' : data.targets.target_weight}" style="width:140px">
          <input type="number" step="0.1" name="target_body_fat" placeholder="目标体脂 %" value="${data.targets.target_body_fat === null ? '' : data.targets.target_body_fat}" style="width:130px">
          <button class="button button-primary">保存</button>
        </form>
      </div>

      <div class="card">
        <div class="card-head"><h2 class="card-title">历史记录</h2></div>
        ${data.series.length ? `<table class="table">
          <thead><tr><th>日期</th><th>体重</th><th>变化</th><th>体脂</th><th>变化</th><th>备注</th><th></th></tr></thead>
          <tbody>${data.series.slice().reverse().map((item) => `<tr>
            <td>${esc(item.day)}</td>
            <td>${item.weight === null ? '—' : item.weight + ' kg'}</td>
            <td class="small ${item.weight_delta === null ? 'muted' : item.weight_delta <= 0 ? 'money-income' : 'money-expense'}">
              ${item.weight_delta === null ? '—' : (item.weight_delta > 0 ? '+' : '') + item.weight_delta}</td>
            <td>${item.body_fat === null ? '—' : item.body_fat + '%'}</td>
            <td class="small ${item.body_fat_delta === null ? 'muted' : item.body_fat_delta <= 0 ? 'money-income' : 'money-expense'}">
              ${item.body_fat_delta === null ? '—' : (item.body_fat_delta > 0 ? '+' : '') + item.body_fat_delta}</td>
            <td class="muted small">${esc(item.note)}</td>
            <td><button class="icon-button" data-action="delete-weigh-in" data-day="${item.day}">×</button></td>
          </tr>`).join('')}</tbody></table>`
      : '<div class="empty">还没有称量记录</div>'}
      </div>`;
  }

  /* ---------------- 年度总览 ---------------- */

  function yearView(data) {
    return `
      <div class="page-head">
        <div><h1 class="page-title">${data.year} 年度总览</h1>
          <p class="page-sub">一年下来，事情做完多少、钱花在哪、身体往哪走</p></div>
        <div class="row">
          <button class="button" data-action="year-prev">← ${data.year - 1}</button>
          <button class="button" data-action="year-next">${data.year + 1} →</button>
        </div>
      </div>

      <div class="card">
        <div class="card-head"><h2 class="card-title">各类事情的年度完成度</h2></div>
        <div class="ring-row" style="justify-content:space-between">
          ${data.okr.filter((cadence) => cadence.count > 0).map((cadence, index) => `<div class="stat-block" style="align-items:center">
            ${Charts.ring(cadence.progress_percent, { size: 100, color: Charts.colorAt(index) })}
            <span class="stat-label">${esc(cadence.label)}目标</span></div>`).join('')}
          <div class="stat-block" style="align-items:center">
            ${Charts.ring(Math.round(data.tasks.rate * 100), { size: 100, color: '#15936d' })}
            <span class="stat-label">任务完成率</span></div>
          <div class="stat-block" style="align-items:center">
            ${Charts.ring(Math.round(data.habits.rate * 100), { size: 100, color: '#7a5af0' })}
            <span class="stat-label">习惯坚持率</span></div>
        </div>
        ${data.okr.filter((cadence) => cadence.count === 0).length
    ? `<p class="small muted" style="margin-top:10px">
          还没有${data.okr.filter((cadence) => cadence.count === 0).map((cadence) => cadence.label).join('、')}目标，
          这些周期不参与统计，也不算 0%。</p>`
    : ''}
      </div>

      <div class="card">
        <div class="card-head"><h2 class="card-title">${data.year} 年热力图</h2>
          <span class="card-hint" id="heatmap-label">任务完成情况</span></div>
        <div class="row" style="margin-bottom:10px">
          <button class="button small is-active" data-action="heatmap" data-source="tasks">任务</button>
          <button class="button small" data-action="heatmap" data-source="habits">习惯</button>
          <button class="button small" data-action="heatmap" data-source="expense">花销</button>
          <button class="button small" data-action="heatmap" data-source="meals">饮食</button>
          <button class="button small" data-action="heatmap" data-source="weigh">称量</button>
        </div>
        <div id="heatmap-body">${heatmapFor(data, 'tasks')}</div>
      </div>

      <div class="grid-2">
        <div class="card">
          <div class="card-head"><h2 class="card-title">全年收支</h2></div>
          <div class="row">
            <div class="stat-block"><span class="stat-value money money-expense">${money(data.ledger.expense)}</span><span class="stat-label">支出</span></div>
            <div class="stat-block"><span class="stat-value money money-income">${money(data.ledger.income)}</span><span class="stat-label">收入</span></div>
          </div>
          <div style="margin-top:12px">${Charts.bars(data.months.map((month) => ({ label: month.label, value: month.expense })), { height: 180 })}</div>
        </div>
        <div class="card">
          <div class="card-head"><h2 class="card-title">任务与习惯</h2></div>
          <div class="row" style="padding:4px 0"><span style="width:110px">任务完成</span>
            <div style="flex:1">${Charts.progressBar(data.tasks.rate * 100)}</div>
            <span class="small strong" style="width:110px;text-align:right">${data.tasks.done}/${data.tasks.total}</span></div>
          <div class="row" style="padding:4px 0"><span style="width:110px">习惯坚持</span>
            <div style="flex:1">${Charts.progressBar(data.habits.rate * 100, { color: '#7a5af0' })}</div>
            <span class="small strong" style="width:110px;text-align:right">${data.habits.done}/${data.habits.expected}</span></div>
        </div>
      </div>`;
  }

  function heatmapFor(data, source) {
    const entries = data.heatmap[source] || [];
    const options = {
      tasks: { color: '#3567dc', format: (value) => `${value} 项完成` },
      habits: { color: '#7a5af0', format: (value) => `打了 ${value} 个勾` },
      expense: { color: '#d2453c', format: (value) => `花了 ${plainMoney(value)}` },
      meals: { color: '#d98324', format: (value) => `记了 ${Math.round(value)} 餐` },
      weigh: { color: '#15936d', format: () => '称过体重' }
    }[source] || {};
    return Charts.heatmap(entries, data.year, options);
  }

  /* ---------------- 设置 ---------------- */

  function settingsView(data) {
    const net = data.net || {};
    const syncedYears = net.synced_years || [];
    const holidayRows = [
      ['上次同步', net.last_sync_at ? esc(net.last_sync_at) : '<span class="muted">还没同步过</span>'],
      ['节假日', syncedYears.length
        ? `已同步 ${syncedYears.join('、')} 年`
        : '<span class="muted">还没有</span>'],
      ['汇率', net.fx_count
        ? `${net.fx_count} 个币种${net.fx_updated_at ? `，${esc(net.fx_updated_at)}` : ''}`
        : '<span class="muted">还没有，外币记账需要先同步一次</span>'],
      ['常见菜名表', `${data.food_total} 种常见菜与食材，内置，离线可用`]
    ];

    return `
      <div class="page-head">
        <div><h1 class="page-title">设置</h1>
          <p class="page-sub">数据家、节假日与分类都在这里</p></div>
      </div>

      <div class="card">
        <div class="card-head"><h2 class="card-title">数据家</h2>
          <span class="card-hint">更新版本时只换代码，这里纹丝不动</span></div>
        <table class="table">
          <tbody>
            <tr><td style="width:120px">位置</td><td>${esc(data.info.data_home)}</td></tr>
            <tr><td>数据库文件</td><td>${esc(data.info.database_path)}</td></tr>
            <tr><td>占用</td><td class="strong">${esc(data.info.db_size_human)}</td></tr>
            <tr><td>备份</td><td>${data.info.backup_count} 份，共 ${esc(data.info.backups_size_human)}</td></tr>
            <tr><td>记录条数</td><td>任务 ${data.info.counts.tasks} · 习惯记录 ${data.info.counts.habit_logs} · 目标 ${data.info.counts.objectives} · 流水 ${data.info.counts.ledger_entries} · 饮食 ${data.info.counts.meals} · 称量 ${data.info.counts.weigh_ins} · 节假日 ${data.info.counts.holidays}</td></tr>
          </tbody>
        </table>
        <div class="row" style="margin-top:12px">
          <button class="button" data-action="open-data-home">打开数据家</button>
          <button class="button" data-action="backup-now">立刻备份</button>
          <button class="button" data-action="export-json">导出 JSON</button>
          <button class="button" data-action="export-csv">导出记账 CSV</button>
          <button class="button" data-action="move-data-home">搬到别处</button>
        </div>
        <div class="small muted" style="margin-top:8px" id="settings-status"></div>
      </div>

      <div class="card">
        <div class="card-head"><h2 class="card-title">联网</h2>
          <span class="card-hint">同步节假日、汇率和行情，关掉就彻底不联网</span></div>
        <div class="row">
          <label class="small" style="display:flex;align-items:center;gap:6px">
            <input type="checkbox" data-action="toggle-net" ${net.enabled ? 'checked' : ''}>
            允许联网
          </label>
          <span class="spacer"></span>
          <button class="button" data-action="sync-now" ${net.enabled ? '' : 'disabled'}>立即同步</button>
        </div>
        <table class="table" style="margin-top:10px">
          <tbody>${holidayRows.map(([label, value]) => `<tr>
            <td style="width:120px">${label}</td><td>${value}</td></tr>`).join('')}</tbody>
        </table>
        <p class="small muted" style="margin-top:8px">
          节假日 ${esc(net.holiday_url || '')} · 汇率 ${esc(net.fx_url || '')} · 行情 腾讯财经与东方财富，都免密钥。
          取不到就继续用本地数据，界面不会有任何异样。</p>
      </div>

      <div class="card">
        <div class="card-head"><h2 class="card-title">节假日与调休</h2>
          <span class="card-hint">可在线同步，也可自己补</span></div>
        <div class="row">
          <button class="button" data-action="holiday-prev">←</button>
          <span class="strong">${data.holiday_year} 年</span>
          <button class="button" data-action="holiday-next">→</button>
          <span class="spacer"></span>
          <button class="button" data-action="sync-holidays" data-year="${data.holiday_year}"
            ${net.enabled ? '' : 'disabled'}>同步这一年</button>
          <button class="button" data-action="add-holiday">添加一天</button>
        </div>
        <table class="table" style="margin-top:10px">
          <thead><tr><th style="width:130px">日期</th><th style="width:90px">类型</th><th>名称</th><th style="width:60px"></th></tr></thead>
          <tbody>${data.holidays.length ? data.holidays.map((item) => `<tr>
            <td>${esc(item.day)}</td>
            <td><span class="chip ${item.type === 'holiday' ? 'chip-high' : 'chip-low'}">${esc(item.type_label)}</span></td>
            <td>${esc(item.name)}</td>
            <td><button class="icon-button" data-action="delete-holiday" data-day="${esc(item.day)}">×</button></td>
          </tr>`).join('') : '<tr><td colspan="4" class="empty">这一年还没有记录</td></tr>'}</tbody>
        </table>
        <form data-action="import-holidays" style="margin-top:12px">
          <div class="field">
            <span class="field-label">批量导入，每行一条：2026-01-01~2026-01-03 放假 元旦</span>
            <textarea name="text" placeholder="2026-01-01~2026-01-03 放假 元旦&#10;2026-01-04 上班"></textarea>
          </div>
          <button class="button" style="margin-top:8px">导入</button>
        </form>
      </div>

      <div class="card">
        <div class="card-head"><h2 class="card-title">记账分类</h2>
          <span class="card-hint">删掉分类不会删流水，历史流水会落到「其他」</span></div>
        <div class="phrase-list">
          ${data.categories.map((category) => `<span class="phrase" style="display:inline-flex;align-items:center;gap:6px">
            ${esc(category)}
            <button class="icon-button" data-action="delete-category" data-name="${esc(category)}">×</button></span>`).join('')}
        </div>
        <form class="row" style="margin-top:10px" data-action="add-category">
          <input type="text" name="name" placeholder="新分类" required style="width:160px">
          <button class="button">添加</button>
        </form>
      </div>

      <div class="card">
        <div class="card-head"><h2 class="card-title">关于</h2></div>
        <table class="table"><tbody>
          <tr><td style="width:120px">版本</td><td>${esc(data.info.app_version)}</td></tr>
          <tr><td>数据库结构版本</td><td>schema ${data.info.schema_version}</td></tr>
        </tbody></table>
        <p class="small muted" style="margin-top:8px">想加功能直接改 src 下的代码，表结构变化就在 src/migrations 追加一个新编号的 .sql，
          启动时会自动补跑，不用迁移数据。</p>
      </div>`;
  }

  /* ---------------- 行情 ---------------- */

  /* 涨跌方向：国内习惯红涨绿跌，零值和没数据用中性色 */
  function chg(value) {
    if (value === null || value === undefined || value === '') {
      return { text: '—', cls: '', arrow: '' };
    }
    const number = Number(value);
    if (!number) return { text: '0.00%', cls: '', arrow: '' };
    return {
      text: `${number > 0 ? '+' : ''}${number.toFixed(2)}%`,
      cls: number > 0 ? 'money-income' : 'money-expense',
      arrow: number > 0 ? '▲' : '▼'
    };
  }

  function indexCard(index) {
    const move = chg(index.change_pct);
    return `<div class="card index-card">
      <div class="index-name">${esc(index.name)}</div>
      <div class="index-price money">${plainMoney(index.price)}</div>
      <div class="index-change ${move.cls}">${move.arrow} ${move.text}</div>
    </div>`;
  }

  function sectorRows(items) {
    if (!items.length) return '<div class="empty">这会儿没拿到板块数据</div>';
    return items.map((item) => {
      const move = chg(item.pct);
      return `<div class="row" style="padding:5px 0">
        <span style="flex:1">${esc(item.name)}</span>
        <span class="money ${move.cls}" style="width:78px;text-align:right">${move.text}</span>
      </div>`;
    }).join('');
  }

  function benchmarkCard(title, benchmark, width) {
    let hint = '最近 30 个交易日';
    let chart = '<div class="empty">数据积累中，至少两个交易日才有走势</div>';
    if (benchmark && benchmark.series.length >= 2) {
      const first = benchmark.series[0].price;
      const last = benchmark.series[benchmark.series.length - 1].price;
      if (first) {
        const move = chg(((last - first) / first) * 100);
        hint = `区间 ${move.text}`;
      }
      const points = benchmark.series.map((row) => ({ y: row.price, label: row.day }));
      const labels = benchmark.series.map((row, i) =>
        (i % 5 === 0 || i === benchmark.series.length - 1 ? row.day.slice(5) : ''));
      chart = Charts.lines([{ color: Charts.colorAt(0), points }], {
        width: width || 340, height: 180, labels
      });
    }
    return `<div class="card">
      <div class="card-head"><h2 class="card-title">${esc(title)}</h2>
        <span class="card-hint">${hint}</span></div>
      ${chart}
    </div>`;
  }

  /* 市场温度卡：0-100，冷（恐慌）走绿、热（贪婪）走红，与涨跌方向色一致 */
  function tempCard(item) {
    const tone = item.value >= 75 ? 'money-income'
      : item.value <= 25 ? 'money-expense' : '';
    return `<div class="card temp-card">
      <div class="temp-head">
        <span class="temp-market">${esc(item.market_label)}</span>
        ${item.estimated ? '<span class="temp-tag">估算</span>' : ''}
      </div>
      <div class="temp-value ${tone}">${item.value}</div>
      <div class="temp-label ${tone}">${esc(item.label)}</div>
      <div class="temp-gauge"><span class="temp-dot" style="left:${item.value}%"></span></div>
      <div class="temp-source">${esc(item.source)}</div>
    </div>`;
  }

  /* 币圈卡片：和指数卡同款，名字后面挂代码与 UTC 归日 */
  function coinCard(coin) {
    const move = chg(coin.change_pct);
    return `<div class="card index-card">
      <div class="index-name">${esc(coin.name)}
        <span class="small muted" style="margin-left:4px">${esc(coin.code)}</span></div>
      <div class="index-price money">$${plainMoney(coin.price)}</div>
      <div class="index-change ${move.cls}">${move.arrow} ${move.text}</div>
    </div>`;
  }

  function market(data) {
    const limits = data.limits || {};
    const watchRows = data.watch.map((item) => {
      const move = chg(item.change_pct);
      const window = chg(item.window_pct);
      return `<tr>
        <td><span class="strong">${esc(item.name)}</span>
          <span class="small muted" style="margin-left:6px">${esc(item.code)}</span></td>
        <td class="money" style="text-align:right">${item.price === null ? '—' : plainMoney(item.price)}</td>
        <td class="money ${move.cls}" style="text-align:right">${move.arrow} ${move.text}</td>
        <td class="money ${window.cls}" style="text-align:right">${window.text}</td>
        <td style="text-align:right;width:40px">
          <button class="icon-button" data-action="watch-remove" data-id="${item.id}" title="移出自选">×</button></td>
      </tr>`;
    }).join('');

    const sub = data.syncing
      ? (data.day ? `${esc(data.day)} · 后台同步中…` : '正在获取行情数据…')
      : (data.day
        ? `${esc(data.day)}${data.net_enabled ? ' 收盘' : ' 本地快照（联网已关）'}`
        : '还没有数据，联网后自动同步');

    // 实时状态条：同步中显示脉冲点；空闲显示最后更新时间（动态刷新的体感）
    const liveBadge = data.syncing
      ? '<span class="live-badge is-live"><span class="live-dot"></span>实时同步中</span>'
      : (data.last_updated
        ? `<span class="live-badge"><span class="live-dot is-idle"></span>最后更新 ${esc(data.last_updated.slice(11))}</span>`
        : '<span class="live-badge muted">尚未同步</span>');

    const temperature = data.temperature || [];
    const coins = data.crypto || [];
    const coinDay = coins.length ? coins[0].day : '';

    return `
      <div class="page-head">
        <div><h1 class="page-title">行情</h1>
          <p class="page-sub">${sub}</p>
          <div class="live-row">${liveBadge}</div></div>
        <div class="row">
          <button class="button" data-action="market-refresh" ${data.syncing ? 'disabled' : ''}>${data.syncing ? '同步中…' : '刷新'}</button>
        </div>
      </div>

      <p class="group-label">市场温度 · 恐慌指数</p>
      <div class="temp-grid">
        ${temperature.map(tempCard).join('') || '<div class="card empty">温度数据积累中，联网后自动刷新</div>'}
      </div>

      <p class="group-label">股票指数</p>
      <div class="index-grid">
        ${data.indices.map(indexCard).join('') || '<div class="card empty">还没有指数数据</div>'}
      </div>

      <p class="group-label">币圈${coinDay ? ` · UTC ${esc(coinDay)}` : ''}</p>
      <div class="index-grid">
        ${coins.map(coinCard).join('') || '<div class="card empty">还没有币圈数据</div>'}
      </div>

      <div class="grid-3">
        <div class="card">
          <div class="card-head"><h2 class="card-title">市场情绪</h2>
            <span class="card-hint">A股涨跌停</span></div>
          <div class="row" style="gap:28px;padding:8px 0">
            <div class="stat-block">
              <span class="stat-value money-income">${limits.up ?? '—'}</span>
              <span class="stat-label">涨停（家）</span>
            </div>
            <div class="stat-block">
              <span class="stat-value money-expense">${limits.down ?? '—'}</span>
              <span class="stat-label">跌停（家）</span>
            </div>
          </div>
        </div>
        <div class="card">
          <div class="card-head"><h2 class="card-title">板块领涨</h2>
            <span class="card-hint">A股行业前 5</span></div>
          ${sectorRows(data.sectors_up)}
        </div>
        <div class="card">
          <div class="card-head"><h2 class="card-title">板块领跌</h2>
            <span class="card-hint">A股行业后 5</span></div>
          ${sectorRows(data.sectors_down)}
        </div>
      </div>

      <div class="grid-2" style="margin-top:var(--sp-4)">
        <div class="card">
          <div class="card-head"><h2 class="card-title">板块领涨</h2>
            <span class="card-hint">美股行业前 5 · SPDR 行业 ETF</span></div>
          ${sectorRows(data.us_sectors_up)}
        </div>
        <div class="card">
          <div class="card-head"><h2 class="card-title">板块领跌</h2>
            <span class="card-hint">美股行业后 5 · SPDR 行业 ETF</span></div>
          ${sectorRows(data.us_sectors_down)}
        </div>
      </div>

      <div class="grid-2" style="margin-top:var(--sp-4)">
        <div class="card">
          <div class="card-head"><h2 class="card-title">板块领涨</h2>
            <span class="card-hint">币圈 24h 前 5 · 市值 ≥ $10 亿</span></div>
          ${sectorRows(data.crypto_sectors_up)}
        </div>
        <div class="card">
          <div class="card-head"><h2 class="card-title">板块领跌</h2>
            <span class="card-hint">币圈 24h 后 5 · 市值 ≥ $10 亿</span></div>
          ${sectorRows(data.crypto_sectors_down)}
        </div>
      </div>

      <div class="card" style="margin-top:var(--sp-4)">
        <div class="card-head"><h2 class="card-title">自选</h2>
          <span class="card-hint">A股 6 位 · 港股如 00700 · 美股如 AAPL · 币圈如 BTC</span></div>
        <form class="row" style="margin-bottom:12px" data-action="watch-add">
          <input type="text" name="code" placeholder="输入代码添加自选" required style="flex:1">
          <button class="button button-primary">添加</button>
        </form>
        ${data.watch.length
    ? `<table class="table">
            <thead><tr><th>名称</th><th style="text-align:right">现价</th>
              <th style="text-align:right">当日</th><th style="text-align:right">30 日</th><th></th></tr></thead>
            <tbody>${watchRows}</tbody></table>`
    : '<div class="empty">还没有自选，上面输入代码添加</div>'}
      </div>

      <div class="grid-3" style="margin-top:var(--sp-4)">
        ${benchmarkCard('上证指数', data.benchmarks.find((item) => item.code === 'sh000001'), 300)}
        ${benchmarkCard('纳斯达克', data.benchmarks.find((item) => item.code === 'usIXIC'), 300)}
        ${benchmarkCard('比特币', data.benchmarks.find((item) => item.code === 'BTCUSDT'), 300)}
      </div>

      <p class="small muted" style="margin-top:4px">数据来自腾讯财经、东方财富、Binance、CoinGecko、Yahoo 与
        Alternative.me 的公开接口，每次打开自动刷新；A股与港股的恐慌指数没有免费官方来源，
        界面标注「估算」的温度由涨跌停与指数涨跌推算；美股行业用 SPDR 行业 ETF 代理。
        仅供参考，不构成投资建议。</p>`;
  }

  global.Views = {
    home, calendar, tasks, okr: okrView, ledger: ledgerView,
    diet: dietView, body: bodyView, year: yearView, settings: settingsView,
    market, foodPicker, money, plainMoney, pct, heatmapFor
  };
})(window);
