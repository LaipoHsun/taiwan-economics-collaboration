"""09 合作關係的延續：每對合作的合著論文數與持續年數；固定核心合作者（3 篇以上）的比例；合作最多的幾對。

含外部作者的網路，至少一端是名冊學者的合作對（名冊學者之間的對只算一次）。2015–2025。
持續年數 = 最後一篇年份 − 第一篇年份 + 1（只看這 11 年，左右都被截斷）。
"""
import numpy as np
import pandas as pd

from _common import (COLLAB_COLOR, COLLAB_ORDER, COUNTRY_ZH, INK, INK2, LIGHTGREY, MUTED, ego_ties, load_all,
                     person_collab, plt, save, section)

d = load_all()
r = person_collab(d)
t = ego_ties(d)
t['key'] = [tuple(sorted(x)) for x in zip(t.ego, t.alter)]
pairs = t.drop_duplicates('key').copy()
pairs['span'] = pairs.last_year - pairs.first_year + 1
pairs['core'] = pairs['count'] >= 3
nodes = d.nodes.set_index('node_id')
pl = d.places.set_index('node_id')


def nm(n):
    x = nodes.loc[n]
    if x.node_type == 'roster':
        return f'{x.name_zh}（{r.loc[n, "inst_short_2026"]}）'
    name = x.name_zh if isinstance(x.name_zh, str) and x.name_zh else (x.name_en_canonical if isinstance(x.name_en_canonical, str) else x.name_en)
    cc = pl.country.get(n)
    where = '名冊校' if pl.place_type.get(n) == 'roster' else (COUNTRY_ZH.get(cc, cc) if isinstance(cc, str) else '位置未知')
    return f'{name}〔外部・{where}〕'


fig = plt.figure(figsize=(18, 10.5))
gs = fig.add_gridspec(2, 2, width_ratios=[1, 1.25], height_ratios=[1, 1], wspace=0.62, hspace=0.5)
a1, a2, a3 = fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[1, 0]), fig.add_subplot(gs[:, 1])

# ---- A：合著篇數分布，依合作者類別 ----
BINS = [(1, 1, '1 篇'), (2, 2, '2 篇'), (3, 4, '3–4 篇'), (5, 9, '5–9 篇'), (10, 999, '10 篇以上')]
SH = ['#e7e6e1', '#c2c9d3', '#8d9db3', '#4f6a8f', '#1d3557']
y = np.arange(len(COLLAB_ORDER) + 1)
groups = ['全部'] + COLLAB_ORDER
stats_txt = []
for yi, g in zip(y, groups):
    s = pairs if g == '全部' else pairs[pairs.main == g]
    left = 0
    for (lo, hi, lab), c in zip(BINS, SH):
        v = s['count'].between(lo, hi).mean() * 100
        a1.barh(yi, v, left=left, color=c, height=0.66, edgecolor='white', label=lab if yi == 0 else None)
        if v >= 5:
            a1.text(left + v / 2, yi, f'{v:.0f}', ha='center', va='center', fontsize=8.3,
                    color='white' if c in SH[3:] else INK)
        left += v
    stats_txt.append(f'{len(s):,} 對｜核心 {s.core.mean():.0%}')
a1.set_yticks(y, [f'{a}\n{b}' for a, b in zip(['全部'] + [f'名冊學者–{g}' if g != '名冊內' else '名冊學者之間' for g in COLLAB_ORDER],
                                                 stats_txt)], fontsize=9.3)
for tl, g in zip(a1.get_yticklabels(), groups):
    if g in COLLAB_COLOR and g != '未知':
        tl.set_color({'名冊內': '#0f7a52', '國內外部': '#a87200', '國外': '#c2477a'}[g])
a1.set_ylim(len(groups) - 0.4, -0.6)
a1.set_xlim(0, 100)
a1.set_xlabel('合作對的比例（%）')
a1.tick_params(axis='y', length=0)
a1.spines['left'].set_visible(False)
a1.legend(loc='upper center', bbox_to_anchor=(0.5, -0.2), ncol=5, fontsize=8.8, handlelength=1.1, title='合著論文數',
          title_fontsize=8.8)
a1.set_title('A　每對合作寫了幾篇（標籤下：對數｜核心 = 3 篇以上的比例）', fontsize=12)

# ---- B：持續年數 ----
rep = pairs[pairs['count'] >= 2]
for g, c in (('名冊內', COLLAB_COLOR['名冊內']), ('外部', MUTED)):
    s = rep[rep.main == '名冊內'] if g == '名冊內' else rep[rep.main != '名冊內']
    vc = s.span.value_counts(normalize=True).reindex(range(1, 12), fill_value=0) * 100
    off = -0.2 if g == '名冊內' else 0.2
    a2.bar(np.arange(1, 12) + off, vc.values, width=0.4, color=c,
           label=f'{"名冊學者之間" if g == "名冊內" else "名冊學者–外部作者"}（{len(s):,} 對，中位數 {s.span.median():.0f} 年）')
a2.set_xticks(range(1, 12))
a2.set_xlabel('持續年數（第一篇到最後一篇，含頭尾；年）')
a2.set_ylabel('合作對的比例（%）')
a2.yaxis.grid(True)
a2.set_axisbelow(True)
a2.legend(fontsize=8.8, loc='upper right')
a2.set_title('B　合寫 2 篇以上的合作對，持續了幾年', fontsize=12)

# ---- C：合作最多的 20 對 ----
TOP = 20
top = pairs.sort_values(['count', 'span'], ascending=False).head(TOP).iloc[::-1]
yy = np.arange(len(top))
a3.barh(yy, top['count'], color=[COLLAB_COLOR[m] if m != '未知' else '#b9b8b3' for m in top.main], height=0.68)
for yi, (_, x) in zip(yy, top.iterrows()):
    a3.text(x['count'] + 0.4, yi, f'{x["count"]} 篇　{x.first_year}–{x.last_year}', va='center', fontsize=8.6, color=INK2)
a3.set_yticks(yy, [f'{nm(x.ego)} ─ {nm(x.alter)}' for _, x in top.iterrows()], fontsize=9)
a3.set_xlim(0, top['count'].max() * 1.35)
a3.set_ylim(-0.6, len(top) - 0.4)
a3.tick_params(axis='y', length=0)
a3.spines['left'].set_visible(False)
a3.xaxis.grid(True)
a3.set_axisbelow(True)
a3.set_xlabel('2015–2025 合著論文數（篇）')
a3.set_title(f'C　合作最多的 {TOP} 對（顏色：合作者類別；右：篇數與年份）', fontsize=12)
from matplotlib.patches import Patch  # noqa: E402
a3.legend(handles=[Patch(color=COLLAB_COLOR[g] if g != '未知' else '#b9b8b3', label=g) for g in COLLAB_ORDER],
          loc='lower right', fontsize=9)

fig.suptitle('合作關係能延續多久？2015–2025（含外部作者的網路）', x=0.06, y=0.995, ha='left', fontsize=15,
             fontweight='bold')
fig.text(0.06, 0.957, '合作對 = 一位名冊學者和一位合作者（名冊學者之間的對只算一次）。資料只涵蓋 2015–2025，'
         '持續年數左右都被截斷。外部作者的類別只用已記錄的位置。', fontsize=9.5, color=INK2)
save(fig, '09_tie_persistence.png')

section('數字')
print('合作對', len(pairs), '｜1 篇', round((pairs['count'] == 1).mean(), 3), '｜2 篇以上', round((pairs['count'] >= 2).mean(), 3),
      '｜核心 3+', round(pairs.core.mean(), 3), '｜10+', (pairs['count'] >= 10).sum())
print(pairs.groupby('main').agg(n=('count', 'size'), rep=('count', lambda s: (s >= 2).mean()), core=('core', 'mean'),
                                mean=('count', 'mean')).round(3))
print('2 篇以上 持續年數中位數', rep.span.median(), '｜名冊內', rep[rep.main == '名冊內'].span.median(),
      '｜外部', rep[rep.main != '名冊內'].span.median(), '｜>= 8 年', (rep.span >= 8).sum())
print('2 篇以上 同一年', round((rep.span == 1).mean(), 3))
cols = ['ego', 'alter', 'count', 'first_year', 'last_year', 'span', 'main']
tt = pairs.sort_values(['count', 'span'], ascending=False).head(TOP)
print('\n'.join(f'{nm(x.ego)} — {nm(x.alter)}  {x["count"]} 篇 {x.first_year}-{x.last_year} {x.main}' for _, x in tt.iterrows()))
ls = pairs[pairs['count'] >= 3].sort_values(['span', 'count'], ascending=False).head(12)
print('最久（3 篇以上）')
print('\n'.join(f'{nm(x.ego)} — {nm(x.alter)}  {x["count"]} 篇 {x.first_year}-{x.last_year} {x.main}' for _, x in ls.iterrows()))
# 每人核心合作者
cp = t[t['count'] >= 3].groupby('ego').size().reindex(r.index, fill_value=0)
print('有核心合作者的學者', (cp > 0).sum(), '核心合作者數中位數（有的人）', cp[cp > 0].median(),
      '佔合作者比例中位數（合作者>=5）', round((cp / r.n_collab)[r.n_collab >= 5].median(), 3))
top_people = cp.sort_values(ascending=False).head(8)
print('核心合作者最多', [(r.loc[i, 'name_zh'], v) for i, v in top_people.items()])
