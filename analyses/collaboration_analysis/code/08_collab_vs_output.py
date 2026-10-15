"""08 合作 vs 產出：合作者人數（含外部，對數軸）× 2015–2025 期刊論文數（對數軸）。

每點一位名冊學者，顏色 = 機構類型（2026）。趨勢線：兩者都 > 0 的人，log(期刊) 對 log(合作者) 的最小平方線（只用來描述）。
標出離趨勢最遠的人：「合作多、期刊少」「期刊多、合作少」各 6 人（限期刊 5 篇以上或合作者 20 人以上，避免只是數量少），
以及期刊 10 篇以上、單一作者著作佔 60% 以上的人。0 畫在軸外的灰色帶。
"""
import numpy as np
from scipy import stats

from _common import (INK, INK2, INST_TYPE_COLOR, INST_TYPE_ORDER, LIGHTGREY, MUTED, load_all, person_collab, plt, repel,
                     save, section)

d = load_all()
r = person_collab(d)
ZERO = 0.62
r['x'] = r.n_collab.where(r.n_collab > 0, ZERO)
r['y'] = r.journal.where(r.journal > 0, ZERO)
both = r[(r.n_collab > 0) & (r.journal > 0)]
lx, ly = np.log10(both.n_collab), np.log10(both.journal)
slope, icpt, rr, pv, _ = stats.linregress(lx, ly)
r['resid'] = np.where((r.n_collab > 0) & (r.journal > 0), np.log10(r.y) - (icpt + slope * np.log10(r.x)), np.nan)
rho = stats.spearmanr(r.n_collab, r.journal).statistic
r['solo_share'] = r.solo / r.papers.where(r.papers > 0)

big = r[(r.journal >= 5) | (r.n_collab >= 20)]
hi = big.nlargest(6, 'resid')      # 期刊多、合作少
lo = big.nsmallest(6, 'resid')     # 合作多、期刊少
solo = r[(r.journal >= 10) & (r.solo_share >= 0.6)]

fig, ax = plt.subplots(figsize=(13, 9.5))
for t in INST_TYPE_ORDER:
    s = r[r.inst_type_2026 == t]
    ax.scatter(s.x, s.y, s=34, color=INST_TYPE_COLOR[t], alpha=0.75, edgecolor='white', lw=0.5,
               label=f'{t}（{len(s)} 人）', zorder=3)
xs = np.logspace(0, np.log10(250), 50)
ax.plot(xs, 10 ** (icpt + slope * np.log10(xs)), color=INK, lw=1.4, ls='--', zorder=2,
        label=f'趨勢（斜率 {slope:.2f}）')
ax.set_xscale('log')
ax.set_yscale('log')
ax.set_xlim(0.5, 300)
ax.set_ylim(0.5, 200)
ticks = [1, 2, 5, 10, 20, 50, 100, 200]
ax.set_xticks([ZERO] + ticks, ['0'] + [str(t) for t in ticks])
ax.set_yticks([ZERO] + ticks[:-1], ['0'] + [str(t) for t in ticks[:-1]])
ax.minorticks_off()
ax.axvspan(0.5, 0.78, color='#f1f0ec', zorder=0)
ax.axhspan(0.5, 0.78, color='#f1f0ec', zorder=0)
ax.grid(True, which='major')
ax.set_axisbelow(True)
ax.set_xlabel('2015–2025 合作者人數（人，含外部作者；對數軸）')
ax.set_ylabel('2015–2025 期刊論文數（篇，對數軸）')

texts = []
anchors = []


def tag(rows, color, fmt, dy=1.08):
    for _, x in rows.iterrows():
        ax.scatter(x.x, x.y, s=80, facecolor='none', edgecolor=color, lw=1.5, zorder=4)
        texts.append(ax.text(x.x * 1.12, x.y * dy, fmt(x), fontsize=8.6, color=color, zorder=5, va='center'))
        anchors.append((x.x, x.y, color))


tag(hi, '#0f5ea8', lambda x: f'{x.name_zh}（{x.inst_short_2026}）{x.journal} 篇／{x.n_collab} 人')
tag(lo, '#b8481d', lambda x: f'{x.name_zh}（{x.inst_short_2026}）{x.n_collab} 人／{x.journal} 篇', dy=0.84)
tag(solo[~solo.index.isin(hi.index)], '#4a3aa7', lambda x: f'{x.name_zh}（{x.inst_short_2026}）獨著 {x.solo_share:.0%}')
top = r.loc[r.n_collab.idxmax()]
texts.append(ax.text(top.x * 0.55, top.y * 1.15, f'{top.name_zh}（{top.inst_short_2026}）{top.n_collab} 人／{top.journal} 篇',
                     fontsize=8.6, color=INK, zorder=5))
anchors.append((top.x, top.y, INK))
repel(ax, texts, move_x=True)
fig.canvas.draw()
rend = fig.canvas.get_renderer()
inv = ax.transData.inverted()
for t, (x0, y0, c) in zip(texts, anchors):
    bb = t.get_window_extent(rend)
    px, py = ax.transData.transform((x0, y0))
    tx = bb.x0 if px < bb.x0 else (bb.x1 if px > bb.x1 else px)
    ty = (bb.y0 + bb.y1) / 2
    if np.hypot(tx - px, ty - py) > 14:
        ax.plot(*zip((x0, y0), inv.transform((tx, ty))), color=c, lw=0.6, alpha=0.7, zorder=4)

ax.text(0.015, 0.8, '藍字：期刊多、合作少（趨勢線上方最遠）\n橘字：合作多、期刊少（趨勢線下方最遠）\n'
        '紫字：期刊 10 篇以上，單一作者著作佔 60% 以上', transform=ax.transAxes, ha='left', va='top', fontsize=9,
        color=INK2, bbox=dict(fc='white', ec=LIGHTGREY, boxstyle='round,pad=0.5'))
ax.legend(loc='upper left', fontsize=9.5)
ax.set_title(f'合作越多、論文越多，但很分散（Spearman ρ = {rho:.2f}）', pad=10, fontsize=12)
fig.suptitle('合作 vs 產出：2015–2025 合作者人數與期刊論文數（421 位名冊學者）', x=0.06, y=0.995, ha='left',
             fontsize=15, fontweight='bold')
fig.text(0.06, 0.935, '合作者人數來自含外部作者的網路（全部可建邊著作）；期刊論文 = edge_eligible == 1、期刊論文，名冊學者是作者之一就算。'
         '\n灰色帶 = 0。機構類型為 2026 年快照。趨勢線只用兩者都大於 0 的人。', fontsize=9.5, color=INK2)
fig.subplots_adjust(top=0.87)
save(fig, '08_collab_vs_output.png')

section('數字')
print('Spearman 全部', round(rho, 3), '｜兩者 >0', round(stats.spearmanr(both.n_collab, both.journal).statistic, 3),
      '｜斜率', round(slope, 3), 'R2', round(rr ** 2, 3), 'n', len(both))
print('期刊 0', (r.journal == 0).sum(), '｜合作者 0', (r.n_collab == 0).sum())
show = ['name_zh', 'inst_short_2026', 'rank_2026', 'n_collab', 'n_collab_small', 'journal', 'papers', 'solo', 'roster_degree',
        'n_國外', 'n_未知', 'resid']
print('期刊多合作少\n', hi[show].round(2).to_string())
print('合作多期刊少\n', lo[show].round(2).to_string())
print('獨著為主\n', solo[show + ['solo_share']].round(2).to_string())
print('依機構類型 Spearman', {t: round(stats.spearmanr(g.n_collab, g.journal).statistic, 2) for t, g in r.groupby('inst_type_2026')})
print('排除大團隊 Spearman', round(stats.spearmanr(r.n_collab_small, r.journal).statistic, 3),
      '名冊內合作者 Spearman', round(stats.spearmanr(r.roster_degree, r.journal).statistic, 3))
