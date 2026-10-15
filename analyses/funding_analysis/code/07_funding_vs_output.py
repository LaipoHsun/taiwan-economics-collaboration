"""07 經費 vs 產出：2015–2025 期刊論文數 vs 個人研究計畫經費。

論文：d.papers 中 2015–2025、edge_eligible == 1、pub_category == 期刊論文，依名冊作者計數（不分作者順序）。
經費：個人研究計畫（同 06），對數軸；沒經費的人畫在底部帶狀區。
趨勢：有經費者的 log(經費) 對 log(1 + 期刊論文) 的最小平方線（只是描述）。標出殘差最大與最小的人，以及沒經費但論文多的人。
"""
import numpy as np
from matplotlib.lines import Line2D

from _common import (INK, INK2, INST_TYPE_COLOR, INST_TYPE_ORDER, LIGHTGREY, MUTED, load, load_grants, person_table, plt,
                     repel, save, section)

N_LAB = 6
d = load()
g = load_grants(d)
r = person_table(d, g)
r['v'] = r.funding_research / 1e4
pos = r[r.v > 0].copy()
lx, ly = np.log1p(pos.journal), np.log(pos.v)
b, a = np.polyfit(lx, ly, 1)
pos['resid'] = ly - (a + b * lx)
zero = r[r.v == 0]
ZERO_Y = 8  # 底部帶狀區的位置（萬元，只為了畫圖）

fig, ax = plt.subplots(figsize=(14, 9.5))
ax.axhspan(5.5, 11.5, color='#f1f0ec', lw=0, zorder=0)
rng = np.random.default_rng(20261012)
jx = lambda s: s.journal + rng.uniform(-0.18, 0.18, len(s)) * (s.journal > 0) + rng.uniform(0, 0.25, len(s)) * (s.journal == 0)  # noqa: E731
ax.scatter(jx(pos), pos.v, s=28, c=pos.inst_type_2026.map(INST_TYPE_COLOR), alpha=0.8, edgecolor='white', linewidth=0.5,
           zorder=2)
ax.scatter(jx(zero), ZERO_Y * np.exp(rng.uniform(-0.25, 0.25, len(zero))), s=22, c=zero.inst_type_2026.map(INST_TYPE_COLOR),
           alpha=0.6, edgecolor='white', linewidth=0.5, zorder=2)
xs = np.linspace(0, r.journal.max(), 200)
ax.plot(xs, np.exp(a + b * np.log1p(xs)), color=INK, lw=1.6, ls=(0, (4, 2)), zorder=3)
ax.text(150, np.exp(a + b * np.log1p(150)) * 0.5, f'趨勢：論文加倍 → 經費約 ×{2 ** b:.2f}', fontsize=9, color=INK2,
        ha='right')

hi = pos.nlargest(N_LAB, 'resid')
lo = pos[pos.journal >= 10].nsmallest(N_LAB, 'resid')
zr = zero.nlargest(5, 'journal')
topj = pos.nlargest(3, 'journal').drop(hi.index.union(lo.index), errors='ignore')
texts, anchors = [], []
for s, tag in ((hi, 'hi'), (lo, 'lo'), (topj, 'top')):
    for _, row in s.iterrows():
        texts.append(ax.text(row.journal * 1.04 + 0.15, row.v, f'{row.name_zh}（{row.inst_short_2026}）', fontsize=8.8,
                             color=INK, va='center'))
        anchors.append((row.journal, row.v))
        ax.scatter(row.journal, row.v, s=48, facecolor='none', edgecolor=INK, linewidth=1, zorder=4)
for _, row in zr.iterrows():
    texts.append(ax.text(row.journal * 1.04 + 0.15, ZERO_Y * 1.25, f'{row.name_zh}（{row.inst_short_2026}，{row.journal} 篇）',
                         fontsize=8.5, color=INK, va='bottom', rotation=0))
    anchors.append((row.journal, ZERO_Y))

ax.set_xscale('symlog', linthresh=2, linscale=0.6)
ax.set_xlim(-0.3, 200)
ax.set_xticks([0, 1, 2, 5, 10, 20, 50, 100, 150], ['0', '1', '2', '5', '10', '20', '50', '100', '150'])
ax.set_yscale('log')
ax.set_ylim(5.5, 7000)
ax.set_yticks([ZERO_Y, 30, 100, 300, 1000, 3000], ['沒有經費', '30', '100', '300', '1,000', '3,000'])
ax.minorticks_off()
ax.set_xlabel('2015–2025 期刊論文數（可建邊著作，對數軸）')
ax.set_ylabel('2015–2025 個人研究計畫經費（萬元，對數軸）')
ax.grid(True)
ax.set_axisbelow(True)
repel(ax, texts)
for t, (x0, y0) in zip(texts, anchors):
    x1, y1 = t.get_position()
    if abs(np.log(y1 / y0)) > 0.08:
        ax.plot([x0, x1], [y0, y1], color=MUTED, lw=0.6, zorder=1)
ax.text(1.0, 2600, '產出少、經費高\n（線的左上方）', fontsize=10, color=MUTED, ha='left')
ax.text(40, 40, '產出高、經費少\n（線的右下方）', fontsize=10, color=MUTED, ha='left')

rho_all = r.v.corr(r.journal, method='spearman')
rho_pos = pos.v.corr(pos.journal, method='spearman')
handles = [Line2D([], [], marker='o', ls='', color=INST_TYPE_COLOR[k], label=f'{k}（2026）', ms=7) for k in INST_TYPE_ORDER]
handles += [Line2D([], [], color=INK, ls=(0, (4, 2)), label='有經費者的對數趨勢線'),
            Line2D([], [], marker='o', ls='', mfc='none', mec=INK, label='離趨勢線最遠者', ms=8)]
fig.legend(handles=handles, loc='lower center', ncol=5, fontsize=9.5, bbox_to_anchor=(0.5, -0.01))
fig.suptitle(f'論文越多，經費越多，但同樣產出的經費可以差 10 倍以上（Spearman ρ = {rho_all:.2f}，421 人）', x=0.07, y=0.995,
             ha='left', fontsize=15, fontweight='bold')
fig.text(0.07, 0.955, f'有經費者 {len(pos)} 人 ρ = {rho_pos:.2f}。經費為個人研究計畫（不含推動規劃、人才培育等），論文為 d.papers 的期刊論文、'
        'edge_eligible == 1。左上與右下各標 6 位離趨勢最遠者（右下限 10 篇以上），底部標沒經費但論文最多的 5 位；\n另標期刊論文最多的 3 位。',
        fontsize=9.5, color=INK2, va='top')
fig.subplots_adjust(top=0.9, bottom=0.12)
save(fig, '07_funding_vs_output.png')

section('數字')
print('趨勢斜率 b', round(b, 3), '｜Spearman 全部', round(rho_all, 3), '有經費', round(rho_pos, 3))
print('論文數 by 有無經費', r.groupby(r.v > 0).journal.describe().round(1))
print('沒有期刊論文的人', (r.journal == 0).sum(), '｜其中沒經費', ((r.journal == 0) & (r.v == 0)).sum())
cols = ['name_zh', 'inst_short_2026', 'rank_2026', 'journal', 'v', 'resid', 'f_一般研究', 'f_年輕學者獎勵', 'f_特約與其他專題']
print('高於趨勢\n', hi[cols].round(2).to_string())
print('低於趨勢\n', lo[cols].round(2).to_string())
print('沒經費、論文多\n', zr[['name_zh', 'inst_short_2026', 'rank_2026', 'journal', 'funding']].to_string())
q = pos.assign(qj=np.minimum(pos.journal // 5 * 5, 40)).groupby('qj').v.agg(['size', 'median']).round(0)
print(q)
print('經費 per 論文（有經費且論文>0）中位數（萬）', round((pos.v / pos.journal.replace(0, np.nan)).median(), 1))
