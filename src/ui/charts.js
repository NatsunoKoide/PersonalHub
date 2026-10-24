/* 手写 SVG 图表，不引 CDN、不联网。
   配色与 styles.css 的设计令牌保持一致，改风格时两边一起改。 */
(function (global) {
  'use strict';

  const PALETTE = [
    '#3567dc', '#7a5af0', '#15936d', '#d98324', '#d2453c',
    '#2e8fb8', '#8c6d4f', '#5b8def', '#98a2b3', '#b45fa0'
  ];

  const AXIS = '#e2e6ee';
  const GRID = '#edf0f5';
  const TEXT = '#4d5768';

  function escapeText(text) {
    return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function colorAt(index) {
    return PALETTE[index % PALETTE.length];
  }

  /** 环形进度，用于 OKR 完成度。 */
  function ring(percent, options) {
    const opts = options || {};
    const size = opts.size || 132;
    const stroke = opts.stroke || 12;
    const color = opts.color || '#3567dc';
    const value = Math.max(0, Math.min(100, Math.round(percent)));
    const radius = (size - stroke) / 2;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference * (1 - value / 100);

    return `<svg class="ring" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" role="img" aria-label="${value}%">
      <circle cx="${size / 2}" cy="${size / 2}" r="${radius}" fill="none" stroke="#edf0f5" stroke-width="${stroke}"/>
      <circle cx="${size / 2}" cy="${size / 2}" r="${radius}" fill="none" stroke="${color}" stroke-width="${stroke}"
        stroke-linecap="round" stroke-dasharray="${circumference.toFixed(2)}"
        stroke-dashoffset="${offset.toFixed(2)}"
        transform="rotate(-90 ${size / 2} ${size / 2})"/>
      <text x="50%" y="50%" text-anchor="middle" dy="0.36em" font-size="${Math.round(size * 0.24)}" font-weight="600" fill="#1a2130">${value}%</text>
    </svg>`;
  }

  function arcPath(cx, cy, outer, inner, start, end) {
    const large = end - start > Math.PI ? 1 : 0;
    const x1 = cx + outer * Math.cos(start);
    const y1 = cy + outer * Math.sin(start);
    const x2 = cx + outer * Math.cos(end);
    const y2 = cy + outer * Math.sin(end);
    const x3 = cx + inner * Math.cos(end);
    const y3 = cy + inner * Math.sin(end);
    const x4 = cx + inner * Math.cos(start);
    const y4 = cy + inner * Math.sin(start);
    return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${outer} ${outer} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`
      + ` L ${x3.toFixed(2)} ${y3.toFixed(2)} A ${inner} ${inner} 0 ${large} 0 ${x4.toFixed(2)} ${y4.toFixed(2)} Z`;
  }

  /** 饼图（甜甜圈），用于记账分类占比。 */
  function donut(items, options) {
    const opts = options || {};
    const size = opts.size || 220;
    const thickness = opts.thickness || 46;
    const cx = size / 2;
    const cy = size / 2;
    const outer = size / 2 - 4;
    const inner = outer - thickness;
    const total = items.reduce((sum, item) => sum + item.value, 0);

    if (!items.length || total <= 0) {
      return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
        <circle cx="${cx}" cy="${cy}" r="${(outer + inner) / 2}" fill="none" stroke="#edf0f5" stroke-width="${thickness}"/>
        <text x="50%" y="50%" text-anchor="middle" dy="0.36em" font-size="13" fill="#8b94a6">暂无数据</text>
      </svg>`;
    }

    let angle = -Math.PI / 2;
    let slices = '';
    items.forEach((item, index) => {
      const sweep = (item.value / total) * Math.PI * 2;
      const next = angle + sweep;
      // 单一分类占满时，整圆弧无法用一条弧线画出来，拆成两半
      if (sweep >= Math.PI * 2 - 1e-6) {
        slices += arcPath(cx, cy, outer, inner, angle, angle + Math.PI);
        slices += arcPath(cx, cy, outer, inner, angle + Math.PI, angle + Math.PI * 2);
      } else {
        slices += `<path d="${arcPath(cx, cy, outer, inner, angle, next)}" fill="${item.color || colorAt(index)}"/>`;
      }
      angle = next;
    });

    return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" role="img">${slices}</svg>`;
  }

  function donutLegend(items) {
    const total = items.reduce((sum, item) => sum + item.value, 0) || 1;
    return `<ul class="legend">${items.map((item, index) => {
      const percent = Math.round((item.value / total) * 100);
      return `<li>
        <span class="dot" style="background:${item.color || colorAt(index)}"></span>
        <span class="legend-label">${escapeText(item.label)}</span>
        <span class="legend-value">${escapeText(item.text || item.value.toFixed(2))}</span>
        <span class="legend-percent">${percent}%</span>
      </li>`;
    }).join('')}</ul>`;
  }

  /** 柱状图，用于近 12 个月支出趋势。 */
  function bars(items, options) {
    const opts = options || {};
    const width = opts.width || 640;
    const height = opts.height || 220;
    const padTop = 16;
    const padBottom = 28;
    const padLeft = 44;
    const plotHeight = height - padTop - padBottom;
    const max = Math.max(1, ...items.map((item) => item.value));
    const slot = (width - padLeft) / Math.max(1, items.length);
    const barWidth = Math.min(34, slot * 0.56);

    let grid = '';
    for (let step = 0; step <= 4; step += 1) {
      const y = padTop + (plotHeight / 4) * step;
      const value = max * (1 - step / 4);
      grid += `<line x1="${padLeft}" y1="${y.toFixed(1)}" x2="${width}" y2="${y.toFixed(1)}" stroke="${GRID}"/>`
        + `<text x="${padLeft - 8}" y="${(y + 4).toFixed(1)}" text-anchor="end" font-size="11" fill="${TEXT}">${formatShort(value)}</text>`;
    }

    const rects = items.map((item, index) => {
      const barHeight = (item.value / max) * plotHeight;
      const x = padLeft + slot * index + (slot - barWidth) / 2;
      const y = padTop + plotHeight - barHeight;
      const color = item.color || colorAt(0);
      return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${Math.max(barHeight, 1).toFixed(1)}" rx="4" fill="${color}">`
        + `<title>${escapeText(item.label)}：${item.value.toFixed(2)}</title></rect>`
        + `<text x="${(x + barWidth / 2).toFixed(1)}" y="${height - 8}" text-anchor="middle" font-size="11" fill="${TEXT}">${escapeText(item.label)}</text>`;
    }).join('');

    return `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" role="img">${grid}${rects}</svg>`;
  }

  /** 折线图，用于体重体脂。targets 是水平虚线。 */
  function lines(series, options) {
    const opts = options || {};
    const width = opts.width || 680;
    const height = opts.height || 240;
    const pad = { top: 16, right: 16, bottom: 28, left: 42 };
    const plotWidth = width - pad.left - pad.right;
    const plotHeight = height - pad.top - pad.bottom;

    const allPoints = series.reduce((list, s) => list.concat(s.points), []);
    if (!allPoints.length) {
      return `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}">
        <text x="50%" y="50%" text-anchor="middle" dy="0.36em" font-size="13" fill="#8b94a6">还没有记录</text></svg>`;
    }

    const values = allPoints.map((point) => point.y);
    let min = Math.min(...values);
    let max = Math.max(...values);
    (opts.targets || []).forEach((target) => {
      if (typeof target.value === 'number') {
        min = Math.min(min, target.value);
        max = Math.max(max, target.value);
      }
    });
    if (max - min < 1) {
      max = min + 1;
    }
    const span = max - min;

    const count = Math.max(1, series.reduce((n, s) => Math.max(n, s.points.length), 0) - 1);
    const xAt = (index) => pad.left + (plotWidth / count) * index;
    const yAt = (value) => pad.top + plotHeight - ((value - min) / span) * plotHeight;

    let grid = '';
    for (let step = 0; step <= 4; step += 1) {
      const y = pad.top + (plotHeight / 4) * step;
      const value = max - (span / 4) * step;
      grid += `<line x1="${pad.left}" y1="${y.toFixed(1)}" x2="${width - pad.right}" y2="${y.toFixed(1)}" stroke="${GRID}"/>`
        + `<text x="${pad.left - 8}" y="${(y + 4).toFixed(1)}" text-anchor="end" font-size="11" fill="${TEXT}">${value.toFixed(1)}</text>`;
    }

    let targetLines = '';
    (opts.targets || []).forEach((target) => {
      if (typeof target.value !== 'number') return;
      const y = yAt(target.value);
      targetLines += `<line x1="${pad.left}" y1="${y.toFixed(1)}" x2="${width - pad.right}" y2="${y.toFixed(1)}"`
        + ` stroke="${target.color || '#d98324'}" stroke-dasharray="5 4" stroke-width="1.5"/>`
        + `<text x="${width - pad.right}" y="${(y - 6).toFixed(1)}" text-anchor="end" font-size="11" fill="${target.color || '#d98324'}">${escapeText(target.label)}</text>`;
    });

    const paths = series.map((s, index) => {
      const color = s.color || colorAt(index);
      const coords = s.points.map((point, i) => `${xAt(i).toFixed(1)},${yAt(point.y).toFixed(1)}`).join(' ');
      const dots = s.points.map((point, i) =>
        `<circle cx="${xAt(i).toFixed(1)}" cy="${yAt(point.y).toFixed(1)}" r="3" fill="${color}">`
        + `<title>${escapeText(point.label || '')} ${point.y}</title></circle>`).join('');
      return `<polyline points="${coords}" fill="none" stroke="${color}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>${dots}`;
    }).join('');

    const labels = (opts.labels || []).map((label, i) =>
      `<text x="${xAt(i).toFixed(1)}" y="${height - 8}" text-anchor="middle" font-size="10" fill="${TEXT}">${escapeText(label)}</text>`).join('');

    return `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" role="img">${grid}${targetLines}${paths}${labels}</svg>`;
  }

  /** 年度热力图，GitHub 风格：53 列 x 7 行。 */
  function heatmap(entries, year, options) {
    const opts = options || {};
    const cell = opts.cell || 13;
    const gap = 3;
    const byDay = new Map(entries.map((entry) => [entry.day, entry.value]));
    const color = opts.color || '#3567dc';

    const janFirst = new Date(Date.UTC(year, 0, 1));
    const offset = (janFirst.getUTCDay() + 6) % 7; // 周日为 0，改成周一为 0
    const columns = 53;
    const width = columns * (cell + gap);
    const height = 7 * (cell + gap);
    const max = Math.max(1, ...entries.map((entry) => entry.value));

    let cells = '';
    for (let week = 0; week < columns; week += 1) {
      for (let weekday = 0; weekday < 7; weekday += 1) {
        const dayIndex = week * 7 + weekday - offset;
        const current = new Date(Date.UTC(year, 0, 1 + dayIndex));
        if (current.getUTCFullYear() !== year) continue;
        const key = current.toISOString().slice(0, 10);
        const value = byDay.get(key) || 0;
        const level = value <= 0 ? 0 : Math.min(4, Math.ceil((value / max) * 4));
        const fill = level === 0 ? '#edf0f5' : mix(color, level / 4);
        cells += `<rect x="${week * (cell + gap)}" y="${weekday * (cell + gap)}" width="${cell}" height="${cell}" rx="3" fill="${fill}">`
          + `<title>${key}：${opts.format ? opts.format(value) : value}</title></rect>`;
      }
    }

    const months = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月'];
    let labels = '';
    for (let month = 0; month < 12; month += 1) {
      const first = new Date(Date.UTC(year, month, 1));
      const dayIndex = Math.round((first - janFirst) / 86400000) + offset;
      labels += `<text x="${(Math.floor(dayIndex / 7) * (cell + gap)).toFixed(1)}" y="${height + 14}" font-size="10" fill="${TEXT}">${months[month]}</text>`;
    }

    return `<svg viewBox="0 0 ${width} ${height + 18}" width="100%" role="img">${cells}${labels}</svg>`;
  }

  function mix(hex, ratio) {
    const base = [237, 240, 245];
    const target = [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)];
    const blend = base.map((channel, index) => Math.round(channel + (target[index] - channel) * Math.min(1, Math.max(0.15, ratio))));
    return `rgb(${blend[0]}, ${blend[1]}, ${blend[2]})`;
  }

  function formatShort(value) {
    if (value >= 10000) return `${(value / 10000).toFixed(1)}万`;
    if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
    return Math.round(value).toString();
  }

  function progressBar(percent, options) {
    const opts = options || {};
    const color = opts.color || '#3567dc';
    const value = Math.max(0, Math.min(100, percent));
    return `<div class="progress"><div class="progress-fill" style="width:${value}%;background:${color}"></div></div>`;
  }

  global.Charts = {
    PALETTE, ring, donut, donutLegend, bars, lines, heatmap, progressBar, colorAt, formatShort, escapeText
  };
})(window);
