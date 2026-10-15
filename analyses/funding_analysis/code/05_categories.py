"""05 類別：各計畫類別的件數、每件金額（中位數與四分位距）、總額。

2015–2025 主持人計畫。每件金額為列示金額（多年期專題研究計畫為全期總額）；另畫平攤後的「每年」中位數。
細類別取總額前 16 名，其餘併入「其他」。顏色依 01 的 8 組分類。
"""
import re

import numpy as np
from matplotlib.patches import Patch

from _common import CAT_COLOR, CAT_ORDER, GREY, INK, INK2, LIGHTGREY, load, load_grants, pi_grants, plt, save, section

TOP = 16

d = load()
g = load_grants(d)
p = pi_grants(g)


def short(c):
    m = re.match(r'^(.*?)\s*\((.*)\)$', c)
    s = m.group(2) if m else c
    s = s.replace('人才培育補助計畫(博士生研究獎學金)', '博士生研究獎學金').replace('補助國內專家學者出席國際學術會議', '出席國際會議')
    s = s.replace('補助科學與技術人員國外短期研究', '國外短期研究').replace('邀請國際科技人士短期訪問', '邀請國際人士短訪')
    return re.sub(r'計畫$', '', s) or c


t = p.groupby('grant_category').agg(cat=('cat', 'first'), n=('amount', 'size'), med=('amount', 'median'),
                                    q1=('amount', lambda s: s.quantile(.25)), q3=('amount', lambda s: s.quantile(.75)),
                                    med_py=('amount_per_year', 'median'), total=('amount', 'sum'),
                                    n_pi=('node_id', 'nunique'), multi=('dur', lambda s: (s > 1).mean()))
t = t.sort_values('total', ascending=False)
top, rest = t.head(TOP).copy(), t.iloc[TOP:]
other = dict(cat=None, n=rest.n.sum(), med=np.nan, q1=np.nan, q3=np.nan, med_py=np.nan, total=rest.total.sum(),
             n_pi=p[p.grant_category.isin(rest.index)].node_id.nunique(), multi=np.nan)
top.loc[f'其他 {len(rest)} 類'] = other
top['label'] = [short(c) if not c.startswith('其他 ') else c for c in top.index]
top = top.iloc[::-1]
y = np.arange(len(top))
cols = [CAT_COLOR.get(c, LIGHTGREY) if isinstance(c, str) else LIGHTGREY for c in top.cat]

fig, (ax, bx, cx) = plt.subplots(1, 3, figsize=(16, 9.5), sharey=True, gridspec_kw=dict(width_ratios=[0.8, 1.25, 1], wspace=0.07))
ax.barh(y, top.n, color=cols, height=0.7)
for yi, n, k in zip(y, top.n, top.n_pi):
    ax.text(n + 12, yi, f'{n:,}（{k} 人）', va='center', fontsize=8.5, color=INK2)
ax.set_xlim(0, top.n.max() * 1.45)
ax.set_xlabel('件數（主持人人數）')
ax.set_title('件數', pad=8)

for yi, r_, c in zip(y, top.itertuples(), cols):
    if np.isnan(r_.med):
        continue
    bx.plot([r_.q1 / 1e4, r_.q3 / 1e4], [yi, yi], color=c, lw=5, alpha=0.35, solid_capstyle='round')
    bx.scatter(r_.med / 1e4, yi, s=60, color=c, zorder=3, edgecolor='white', linewidth=1)
    bx.scatter(r_.med_py / 1e4, yi, s=34, marker='|', color=INK, zorder=4, linewidth=1.6)
    bx.text(r_.q3 / 1e4 * 1.12 if r_.q3 > 0 else 1, yi, f'{r_.med / 1e4:,.0f}', va='center', fontsize=8.5, color=INK2)
bx.set_xscale('log')
bx.set_xlim(30, 2500)
bx.set_xticks([30, 50, 100, 200, 500, 1000, 2000], ['30', '50', '100', '200', '500', '1,000', '2,000'])
bx.minorticks_off()
bx.set_xlabel('每件金額（萬元，對數軸）')
bx.set_title('每件金額：● 中位數　▬ 四分位距　| 平攤後每年中位數', pad=8)

cx.barh(y, top.total / 1e6, color=cols, height=0.7)
tot = p.amount.sum()
for yi, v in zip(y, top.total):
    cx.text(v / 1e6 + 10, yi, f'{v / 1e6:,.0f}（{v / tot:.0%}）', va='center', fontsize=8.5, color=INK2)
cx.set_xlim(0, top.total.max() / 1e6 * 1.3)
cx.set_xlabel('總額（百萬元）')
cx.set_title('總額', pad=8)

for a in (ax, bx, cx):
    a.xaxis.grid(True)
    a.set_axisbelow(True)
    a.tick_params(axis='y', length=0)
for a in (bx, cx):
    a.spines['left'].set_visible(False)
ax.set_yticks(y, top.label, fontsize=9.5)

handles = [Patch(color=CAT_COLOR[c], label=c) for c in CAT_ORDER]
fig.legend(handles=handles, loc='lower center', ncol=8, bbox_to_anchor=(0.5, 0.0), fontsize=9.5)
gen = t.loc['專題研究計畫 (一般研究計畫)']
fig.suptitle(f'一般研究計畫佔一半金額；推動規劃件數少、每件金額是一般計畫的 5 倍', x=0.07, y=0.995, ha='left',
             fontsize=15, fontweight='bold')
fig.text(0.07, 0.955, f'2015–2025 主持人計畫 {len(p):,} 件、{tot / 1e8:.1f} 億元。每件金額為列示金額：多年期專題研究計畫是全期總額，'
         f'所以另標平攤後的每年中位數（|）。顏色為 01 的 8 組分類。', fontsize=9.5, color=INK2)
fig.subplots_adjust(top=0.9, bottom=0.1)
save(fig, '05_categories.png')

section('數字')
out = t.assign(share=t.total / tot, med=t.med / 1e4, med_py=t.med_py / 1e4, q1=t.q1 / 1e4, q3=t.q3 / 1e4, total=t.total / 1e6)
print(out.head(20).round(2).to_string())
grp = p.groupby('cat').agg(n=('amount', 'size'), med=('amount', 'median'), med_py=('amount_per_year', 'median'),
                           total=('amount', 'sum'), n_pi=('node_id', 'nunique'))
print(grp.assign(share=grp.total / tot).round(3).to_string())
gr = p[p.cat == '一般研究']
print('一般研究：每件中位數 by dur', gr.groupby('dur').amount.median().to_dict(), '｜每年中位數 by 年', gr.groupby('year').amount_per_year.median().to_dict())
nw = p[p.cat == '新進人員']
print('新進人員 by dur', nw.groupby('dur').amount.median().to_dict(), nw.dur.value_counts().to_dict())
