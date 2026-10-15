"""08 生涯軌跡：第一次擔任專題研究計畫主持人的年份、新進人員計畫如何銜接一般研究計畫。

用全部年份（1991–2026）的主持人「專題研究計畫」紀錄，只看 421 位名冊學者。
A 第一次當主持人的年份，依第一筆的類別堆疊。1991 是資料最早年份（左設限），2026 只到 9 月。
B 第一筆是新進人員計畫的人：從第一筆新進到第一筆一般研究計畫隔幾年。
C 2015–2020 年第一次當主持人的人，每一列一人，畫出 2026 年以前的每筆主持人計畫（含非專題類）。
"""
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from _common import CAT_COLOR, CAT_ORDER, GREY, INK, INK2, LIGHTGREY, MUTED, cat_group, load, load_grants, plt, roster, save, section

d = load()
g = load_grants(d)
r = roster(d).set_index('node_id')
allpi = g[g.is_pi & g.node_id.isin(r.index)].copy()
allpi['cat'] = allpi.grant_category.map(cat_group)
q = allpi[allpi.grant_category.str.startswith('專題研究計畫')].sort_values(['node_id', 'year'])
first = q.groupby('node_id').agg(year=('year', 'min'))
first['cat'] = q.groupby('node_id').apply(lambda s: s[s.year == s.year.min()].cat.iloc[0], include_groups=False)
first['grp'] = first.cat.map(lambda c: c if c in ('新進人員', '一般研究') else '其他專題')
never = len(r) - len(first)

# B：新進 → 一般
nw = first[first.grp == '新進人員'].index
rows = []
for nid in nw:
    s = q[q.node_id == nid]
    y0 = s[s.cat == '新進人員'].year.min()
    gen = s[(s.cat == '一般研究') & (s.year >= y0)].year
    n_new = (s.cat == '新進人員').sum()
    rows.append(dict(node_id=nid, y0=y0, gap=(gen.min() - y0) if len(gen) else np.nan, n_new=n_new,
                     other_after=((s.year > y0) & ~s.cat.isin(['新進人員', '一般研究'])).any()))
tr = pd.DataFrame(rows).set_index('node_id')
tr_obs = tr[tr.y0 <= 2020]  # 至少有 5 年可以觀察

fig = plt.figure(figsize=(16, 21))
gs = fig.add_gridspec(2, 2, height_ratios=[1, 2.9], width_ratios=[1.35, 1], hspace=0.13, wspace=0.18)
ax = fig.add_subplot(gs[0, 0])
bx = fig.add_subplot(gs[0, 1])
cx = fig.add_subplot(gs[1, :])

# A
years = np.arange(1991, 2027)
GRP_COLOR = {'新進人員': CAT_COLOR['新進人員'], '一般研究': CAT_COLOR['一般研究'], '其他專題': CAT_COLOR['年輕學者獎勵']}
bottom = np.zeros(len(years))
for grp in ('新進人員', '一般研究', '其他專題'):
    v = first[first.grp == grp].year.value_counts().reindex(years, fill_value=0).values
    ax.bar(years, v, bottom=bottom, color=GRP_COLOR[grp], width=0.8, edgecolor='white', linewidth=0.5, label=f'第一筆是{grp}')
    bottom += v
ax.axvspan(2014.5, 2025.5, color='#f1f0ec', zorder=0, lw=0)
ax.text(2020, 21.3, '主要期間\n2015–2025', ha='center', va='top', fontsize=9, color=INK2)
ax.text(1991.2, 24.6, '1991 是資料最早年份，更早開始的人都算在 1991（左設限）；\n新進人員計畫 1998 年才開始。', va='top', fontsize=8.6,
        color=INK2)
ax.text(2026.5, 8.2, '2026\n只到\n9 月', ha='left', va='bottom', fontsize=7.5, color=INK2)
ax.set_xlim(1990, 2028.6)
ax.set_ylim(0, 25)
ax.set_ylabel('人數')
ax.set_xlabel('第一次擔任專題研究計畫主持人的年份')
ax.yaxis.grid(True)
ax.set_axisbelow(True)
ax.legend(loc='upper right', fontsize=9, bbox_to_anchor=(1.0, 0.8))
ax.set_title(f'A 第一次當主持人：{len(first)} 人，另 {never} 人從未擔任', pad=8)

# B
cap = 8
gap = tr_obs.gap.clip(upper=cap)
cnt = gap.value_counts().reindex(range(0, cap + 1), fill_value=0)
none = tr_obs.gap.isna().sum()
xs = list(range(0, cap + 1)) + [cap + 1.6]
vals = list(cnt.values) + [none]
cols = [CAT_COLOR['一般研究']] * (cap + 1) + [LIGHTGREY]
bx.bar(xs, vals, color=cols, width=0.75)
for x_, v in zip(xs, vals):
    bx.text(x_, v + 0.8, f'{v}', ha='center', fontsize=9, color=INK)
bx.set_xticks(xs, [str(i) for i in range(cap)] + [f'{cap}+', '尚未'])
bx.set_xlabel('從第一筆新進人員計畫到第一筆一般研究計畫（年）')
bx.set_ylabel('人數')
bx.yaxis.grid(True)
bx.set_axisbelow(True)
med_gap = tr_obs.gap.median()
within = (tr_obs.gap <= 4).mean()
bx.set_title(f'B 新進 → 一般：{len(tr_obs)} 人（新進起始 ≤ 2020）', pad=8)
bx.text(0.98, 0.95, f'中位數 {med_gap:.0f} 年；{within:.0%} 在 4 年內拿到一般計畫\n'
        f'{none / len(tr_obs):.0%} 到 2026 年仍未拿到一般計畫\n每人新進計畫中位數 {tr_obs.n_new.median():.0f} 筆（可連續申請）',
        transform=bx.transAxes, ha='right', va='top', fontsize=9.5, color=INK2)
bx.set_ylim(0, max(vals) * 1.35)

# C：2015–2020 新進入者的軌跡
coh = first[first.year.between(2015, 2020)].copy()
coh['name'] = r.loc[coh.index, 'name_zh']
coh['inst'] = r.loc[coh.index, 'inst_short_2026']
coh['rank'] = r.loc[coh.index, 'rank_2026']
coh = coh.sort_values(['year', 'grp', 'name'], ascending=[False, True, True])
for i, nid in enumerate(coh.index):
    s = allpi[(allpi.node_id == nid) & (allpi.year >= 2010)]
    yr0 = coh.at[nid, 'year']
    cx.plot([yr0, 2026], [i, i], color=LIGHTGREY, lw=0.8, zorder=1)
    for x in s.itertuples():
        amt = x.amount if x.amount == x.amount else 5e5
        if x.cat in ('新進人員', '一般研究', '年輕學者獎勵', '特約與其他專題', '推動規劃'):
            w = max(int(x.dur), 1) if x.year >= 2006 else 1
            cx.plot([x.year - 0.38, x.year - 0.38 + w - 0.24], [i, i], color=CAT_COLOR[x.cat], lw=4.2, solid_capstyle='butt',
                    zorder=2, alpha=0.9)
        else:
            cx.scatter(x.year, i, s=22, marker='D', color=CAT_COLOR[x.cat], zorder=3, edgecolor='white', linewidth=0.5)
    pre = s[s.year < yr0]
    cx.text(2009.4, i, f'{coh.at[nid, "name"]}　{coh.at[nid, "inst"]}・{coh.at[nid, "rank"]}', ha='right', va='center',
            fontsize=8.3, color=INK)
# 依起始年分隔
for y_ in range(2015, 2021):
    idx = np.flatnonzero(coh.year.values == y_)
    if len(idx):
        cx.axhline(idx.max() + 0.5, color=MUTED, lw=0.6)
        cx.text(2026.6, idx.mean(), f'{y_} 首次\n（{len(idx)} 人）', va='center', fontsize=9, color=INK2)
cx.set_ylim(len(coh) - 0.5, -0.8)
cx.set_xlim(2009.5, 2026.5)
cx.set_yticks([])
cx.set_xticks(range(2010, 2027))
cx.xaxis.grid(True)
cx.set_axisbelow(True)
cx.spines['left'].set_visible(False)
cx.axvspan(2025.5, 2026.5, color='#f1f0ec', zorder=0, lw=0)
cx.set_title(f'C 2015–2020 年第一次當主持人的 {len(coh)} 人：每列一人，橫條長度＝推估執行年數，◆ 為延攬、交流等短期計畫'
             '（姓名後為 2026 年機構與職級）', pad=30)
handles = [Patch(color=CAT_COLOR[c], label=c) for c in ('新進人員', '一般研究', '年輕學者獎勵', '特約與其他專題', '推動規劃')]
handles += [Line2D([], [], marker='D', ls='', color=CAT_COLOR[c], label=c, ms=6) for c in ('延攬人才', '交流與會議', '人才培育與圖書')]
cx.legend(handles=handles, loc='lower left', ncol=8, fontsize=9, bbox_to_anchor=(0.0, 1.0), frameon=False)

fig.suptitle('八成的人從新進人員計畫起步，連拿幾年後，約第 5–6 年轉到一般研究計畫', x=0.07, y=0.995, ha='left',
             fontsize=15, fontweight='bold')
fig.text(0.07, 0.979, '主持人專題研究計畫的全部紀錄（1991–2026）。名冊學者 421 人；職級、機構為 2026 年快照。', fontsize=9.5,
         color=INK2)
fig.subplots_adjust(top=0.96, bottom=0.02)
save(fig, '08_career_trajectory.png')

section('數字')
print('曾任專題研究主持人', len(first), '｜從未', never, '｜第一筆類別', first.grp.value_counts().to_dict())
print('2015–2025 首次', first.year.between(2015, 2025).sum(), '｜by grp', first[first.year.between(2015, 2025)].grp.value_counts().to_dict())
print('2006 後首次 by grp', first[first.year >= 2006].grp.value_counts(normalize=True).round(3).to_dict())
print('B 觀察', len(tr_obs), '｜gap 分布', tr_obs.gap.value_counts(dropna=False).sort_index().to_dict(), '｜中位數', med_gap,
      '｜4 年內', round(within, 3), '｜尚未', none)
print('新進件數分布', tr_obs.n_new.value_counts().sort_index().to_dict())
# C 的後續：首次之後每年有執行中計畫的比例
act = []
for nid in coh.index:
    s = q[q.node_id == nid]
    yrs = set()
    for x in s.itertuples():
        yrs.update(range(int(x.year), int(x.year + max(x.dur, 1))))
    y0 = coh.at[nid, 'year']
    act.append(np.mean([y in yrs for y in range(y0, 2026)]))
print('C：首次後到 2025 年有執行中專題計畫的年份比例，中位數', round(np.median(act), 2), '｜平均', round(np.mean(act), 2))
print('C：首次後斷掉 3 年以上的人', sum(1 for nid in coh.index if (q[q.node_id == nid].year.diff() > 3).any()))
print(coh.groupby('year').size().to_dict(), coh.grp.value_counts().to_dict())
print(coh['rank'].value_counts().to_dict())
