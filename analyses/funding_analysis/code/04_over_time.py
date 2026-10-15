"""04 時間：每年經費總額（平攤到執行年）與執行中的主持人數，依計畫類別堆疊。

平攤：每筆主持人計畫的 amount_per_year 攤到 year … year+dur−1。2013–2014 起始、執行到 2015 以後的計畫也算進去。
上圖另畫「依起始年」的總額（未平攤）做對照。只畫 2015–2025；2026 年資料不完整。
"""
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from _common import (CAT_COLOR, CAT_ORDER, INK, INK2, MUTED, YEARS, cat_group, load, load_grants, plt, save, section)

d = load()
g = load_grants(d)
p = g[g.aligned & g.is_pi & g.year.between(2012, 2025)].copy()
p['cat'] = p.grant_category.map(cat_group)
p['apy'] = p.amount_per_year.fillna(0)
rows = []
for x in p.itertuples():
    for k in range(int(x.dur)):
        rows.append((x.year + k, x.cat, x.apy, x.node_id, x.record_id))
s = pd.DataFrame(rows, columns=['yr', 'cat', 'amt', 'node_id', 'record_id'])
s = s[s.yr.isin(YEARS)]
tab = s.pivot_table(index='yr', columns='cat', values='amt', aggfunc='sum', fill_value=0).reindex(YEARS, fill_value=0)
start = p[p.year.isin(YEARS)].groupby('year').amount.sum().reindex(YEARS)
n_pi = s.groupby('yr').node_id.nunique().reindex(YEARS)
n_pi_res = s[s.cat.isin(['一般研究', '新進人員', '年輕學者獎勵', '特約與其他專題'])].groupby('yr').node_id.nunique().reindex(YEARS)
n_new = s[s.cat == '新進人員'].groupby('yr').node_id.nunique().reindex(YEARS, fill_value=0)

fig, (ax, bx) = plt.subplots(2, 1, figsize=(14.5, 10), sharex=True, gridspec_kw=dict(height_ratios=[1.5, 1], hspace=0.18))
bottom = np.zeros(len(YEARS))
for c in CAT_ORDER:
    v = tab[c].values / 1e6 if c in tab else np.zeros(len(YEARS))
    ax.bar(YEARS, v, bottom=bottom, color=CAT_COLOR[c], width=0.72, edgecolor='white', linewidth=0.8, label=c)
    bottom += v
for x_, b in zip(YEARS, bottom):
    ax.text(x_, b + 3, f'{b:,.0f}', ha='center', fontsize=9, color=INK)
ax.plot(YEARS, start.values / 1e6, color=INK, lw=1.4, ls=(0, (3, 2)), marker='o', ms=4, label='依起始年（未平攤）')
ax.annotate('2015：人社中心設置運作計畫\n1.35 億全列在起始年', xy=(2015, start.loc[2015] / 1e6), xytext=(2016.0, 262),
            fontsize=9, color=INK2, arrowprops=dict(arrowstyle='-', color=MUTED, lw=0.8), va='center')
ax.annotate('2023–2025：淨零、包容智慧治理、\n社群網路等大型推動規劃計畫', xy=(2024, bottom[YEARS.index(2024)] - 20),
            xytext=(2019.2, 262), fontsize=9, color=INK2, arrowprops=dict(arrowstyle='-', color=MUTED, lw=0.8), va='center')
ax.axvspan(2023.5, 2025.5, color='#f1f0ec', zorder=0, lw=0)
ax.text(2024.5, 336, '末端偏高：最後一筆計畫\n無法推估年數，整筆算 1 年', ha='center', va='top', fontsize=8.5, color=INK2)
ax.set_ylabel('經費（百萬元／年）')
ax.set_ylim(0, 340)
ax.yaxis.grid(True)
ax.set_axisbelow(True)
ax.set_title('每年經費總額（多年期計畫平攤到執行年），依計畫類別', pad=8)
handles = [Patch(color=CAT_COLOR[c], label=c) for c in CAT_ORDER] + [
    Line2D([], [], color=INK, ls=(0, (3, 2)), marker='o', ms=4, label='依起始年（未平攤）')]
ax.legend(handles=handles, loc='upper left', ncol=1, fontsize=9.5, bbox_to_anchor=(1.01, 1.0))

bx.plot(YEARS, n_pi.values, color=INK, lw=2, marker='o', ms=5, label='執行中的主持人（全部類別）')
bx.plot(YEARS, n_pi_res.values, color=CAT_COLOR['一般研究'], lw=2, marker='o', ms=5, label='其中有個人研究計畫')
bx.plot(YEARS, n_new.values, color=CAT_COLOR['新進人員'], lw=2, marker='o', ms=5, label='其中有新進人員計畫')
for ser, va in ((n_pi, 'bottom'), (n_pi_res, 'top'), (n_new, 'center')):
    bx.text(2025.2, ser.loc[2025], f'{ser.loc[2025]:.0f}', va=va, fontsize=9, color=INK)
    bx.text(2014.8, ser.loc[2015], f'{ser.loc[2015]:.0f}', va=va, ha='right', fontsize=9, color=INK)
bx.set_ylim(0, 260)
bx.set_xlim(2014.3, 2025.7)
bx.set_ylabel('人數（421 位名冊學者）')
bx.yaxis.grid(True)
bx.set_axisbelow(True)
bx.legend(loc='upper left', fontsize=9.5, bbox_to_anchor=(1.01, 1.0))
bx.set_title('每年有執行中主持人計畫的人數', pad=8)
bx.set_xticks(YEARS)

fig.suptitle('每年 1.4–2.9 億元：一般研究計畫逐年增加，兩個高峰來自大型推動規劃計畫', x=0.07, y=0.985, ha='left',
             fontsize=15, fontweight='bold')
fig.text(0.07, 0.945, '2015–2025 主持人經費。多年期專題研究計畫的金額是全期總額，依推估執行年數（上限 3 年）平攤；'
         '2013–2014 起始、延續到 2015 後的也計入。2026 年資料不完整，不畫。', fontsize=9.5, color=INK2)
fig.subplots_adjust(top=0.9)
save(fig, '04_over_time.png')

section('數字')
out = tab.copy() / 1e6
out['total'] = out.sum(axis=1)
out['start'] = start / 1e6
out['n_pi'] = n_pi
out['n_pi_res'] = n_pi_res
out['n_new'] = n_new
print(out.round(1).to_string())
print('一般研究 平攤 2015–19 平均', round(out.loc[2015:2019, '一般研究'].mean(), 1), '2021–25', round(out.loc[2021:2025, '一般研究'].mean(), 1))
print('每位執行中主持人的一般研究年經費（萬）', (tab['一般研究'] / s[s.cat == '一般研究'].groupby('yr').node_id.nunique() / 1e4).round(1).to_dict())
print('dur of 2015 center grant', p.loc[p.amount.idxmax(), ['year', 'dur', 'amount']].to_dict())
