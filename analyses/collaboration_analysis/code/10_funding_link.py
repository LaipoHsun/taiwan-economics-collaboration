"""10 和經費對照（描述，不做因果）：經費前 25 名在合作網路中的位置；同樣產出、經費差很多的人，合作對象有什麼不同。

經費 = 2015–2025 起始、主持人的「個人研究計畫」（一般、新進、年輕學者獎勵、特約與其他專題），定義同 funding_analysis。
A：每位學者的個人研究經費 × 合作者人數。B：個人研究經費前 25 名，合作指標在 421 人中的百分位。
C：期刊論文 5 篇以上的人，依「經費相對於論文數」的殘差分四組，比較最高與最低四分之一的合作對象組成。
"""
import networkx as nx
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from scipy import stats

from _common import (COLLAB_COLOR, COLLAB_ORDER, INK, INK2, INST_TYPE_COLOR, INST_TYPE_ORDER, LIGHTGREY, MUTED, graph,
                     load_all, load_grants, person_collab, person_table, plt, repel, save, section)

d = load_all()
r = person_collab(d)
g = load_grants(d)
f = person_table(d, g)
r['funding'] = f.funding_research.reindex(r.index)
r['f_wan'] = r.funding / 1e4

G = graph(d, layer='pub', year_from=2015, year_to=2025, external=False, include_isolates=True)
btw = nx.betweenness_centrality(G)
r['btw'] = r.index.map(btw).fillna(0)
for c in COLLAB_ORDER:
    r[f's_{c}'] = r[f'n_{c}'] / r.n_collab.where(r.n_collab > 0)
from _common import ego_ties  # noqa: E402
t = ego_ties(d)
r['n_core'] = t[t['count'] >= 3].groupby('ego').size().reindex(r.index, fill_value=0)

fig = plt.figure(figsize=(20, 13))
gs = fig.add_gridspec(2, 2, width_ratios=[1, 0.95], height_ratios=[1.2, 1], wspace=0.42, hspace=0.45)
a1 = fig.add_subplot(gs[0, 0])
a2 = fig.add_subplot(gs[:, 1])
a3 = fig.add_subplot(gs[1, 0])

# ---- A ----
ZX, ZY = 4, 0.62
x = r.f_wan.where(r.f_wan > 0, ZX)
y = r.n_collab.where(r.n_collab > 0, ZY)
for tp in INST_TYPE_ORDER:
    m = r.inst_type_2026 == tp
    a1.scatter(x[m], y[m], s=28, color=INST_TYPE_COLOR[tp], alpha=0.7, edgecolor='white', lw=0.4, label=f'{tp}', zorder=3)
a1.set_xscale('log')
a1.set_yscale('log')
a1.set_xlim(3, 6000)
a1.set_ylim(0.5, 300)
a1.axvspan(3, 5.5, color='#f1f0ec', zorder=0)
a1.set_xticks([ZX, 10, 30, 100, 300, 1000, 3000], ['0', '10', '30', '100', '300', '1,000', '3,000'])
a1.set_yticks([ZY, 1, 3, 10, 30, 100], ['0', '1', '3', '10', '30', '100'])
a1.minorticks_off()
a1.grid(True)
a1.set_axisbelow(True)
a1.set_xlabel('2015–2025 個人研究計畫經費（萬元，主持人；對數軸）')
a1.set_ylabel('2015–2025 合作者人數（人，含外部；對數軸）')
top25 = r.nlargest(25, 'funding')
lab = list(top25.head(5).index) + list(r.nlargest(3, 'n_collab').index)
texts = []
for n in dict.fromkeys(lab):
    texts.append(a1.text(x[n] * 1.1, y[n] * 1.08, f'{r.loc[n, "name_zh"]}', fontsize=8.5, color=INK, zorder=5))
    a1.scatter(x[n], y[n], s=60, facecolor='none', edgecolor=INK, lw=1, zorder=4)
repel(a1, texts, move_x=True)
fund = r.funding > 0
rho_all = stats.spearmanr(r.funding, r.n_collab).statistic
rho_f = stats.spearmanr(r.funding[fund], r.n_collab[fund]).statistic
rho_r = stats.spearmanr(r.funding, r.roster_degree).statistic
a1.legend(loc='upper left', fontsize=9)
a1.set_title(f'A　經費 vs 合作者人數：Spearman ρ = {rho_all:.2f}（有經費者 {rho_f:.2f}）\n'
             f'名冊內合作者數 ρ = {rho_r:.2f}；灰色帶 = 沒有個人研究經費（{(~fund).sum()} 人）', fontsize=11.5)

# ---- B：前 25 名的百分位 ----
COLS = [('n_collab', '合作者\n人數'), ('n_collab_small', '排除\n大團隊'), ('roster_degree', '名冊內\n合作者'),
        ('btw', '名冊內\nbetweenness'), ('n_core', '核心\n合作者'), ('n_國外', '國外\n合作者'), ('journal', '期刊\n論文')]
pct = {c: r[c].rank(pct=True, method='average') * 100 for c, _ in COLS}
tb = top25.sort_values('funding', ascending=False)
M = np.array([[pct[c][n] for c, _ in COLS] for n in tb.index])
cmap = LinearSegmentedColormap.from_list('p', ['#f5f4f0', '#9cc2ec', '#2a78d6', '#0c2d5e'])
a2.imshow(M, cmap=cmap, vmin=0, vmax=100, aspect='auto')
for i, n in enumerate(tb.index):
    for j, (c, _) in enumerate(COLS):
        v = r.loc[n, c]
        s = f'{v:.2f}' if c == 'btw' else f'{int(v)}'
        a2.text(j, i, s, ha='center', va='center', fontsize=8.4, color='white' if M[i, j] >= 70 else INK)
a2.set_xticks(range(len(COLS)), [l for _, l in COLS], fontsize=9)
a2.xaxis.tick_top()
a2.set_yticks(range(len(tb)), [f'{r.loc[n, "name_zh"]}（{r.loc[n, "inst_short_2026"]}）{r.loc[n, "f_wan"]:,.0f} 萬'
                               for n in tb.index], fontsize=9.2)
for tl, n in zip(a2.get_yticklabels(), tb.index):
    tl.set_color(INST_TYPE_COLOR.get(r.loc[n, 'inst_type_2026'], INK))
a2.tick_params(length=0)
for s in a2.spines.values():
    s.set_visible(False)
med = {c: np.median(M[:, j]) for j, (c, _) in enumerate(COLS)}
a2.set_title('B　個人研究經費前 25 名在合作網路中的位置\n格內 = 數值；顏色 = 在 421 人中的百分位（越深越高）；名字顏色 = 機構類型',
             fontsize=11, pad=42)
a2.text(0.5, -0.025, '前 25 名的百分位中位數：' + '、'.join(f'{l.replace(chr(10), "")} {med[c]:.0f}' for c, l in COLS),
        transform=a2.transAxes, ha='center', va='top', fontsize=9, color=INK2, wrap=True)

# ---- C：同樣產出、經費差很多 ----
base = r[(r.journal >= 5)].copy()
bf = base[base.funding > 0]
sl, ic, *_ = stats.linregress(np.log10(bf.journal), np.log10(bf.funding))
base['resid'] = np.log10(base.funding.clip(lower=1e5)) - (ic + sl * np.log10(base.journal))
q = base.resid.quantile([0.25, 0.75])
hi = base[base.resid >= q[0.75]]
lo = base[base.resid <= q[0.25]]
grp = [('經費高於產出\n（最高四分之一）', hi), ('經費低於產出\n（最低四分之一）', lo)]
yy = np.arange(len(grp))
for yi, (name, s) in zip(yy, grp):
    tot = s[[f'n_{c}' for c in COLLAB_ORDER]].sum()
    left = 0
    for c in COLLAB_ORDER:
        v = tot[f'n_{c}'] / tot.sum() * 100
        a3.barh(yi, v, left=left, color=COLLAB_COLOR[c], height=0.55, edgecolor='white', label=c if yi == 0 else None)
        a3.text(left + v / 2, yi, f'{v:.0f}', ha='center', va='center', fontsize=9, color=INK)
        left += v
    it = s.inst_type_2026.value_counts()
    a3.text(0, yi + 0.42, f'{len(s)} 人；期刊中位數 {s.journal.median():.0f} 篇；經費中位數 {s.f_wan.median():,.0f} 萬；'
            f'合作者中位數 {s.n_collab.median():.0f} 人；名冊內 {s.roster_degree.median():.0f} 人；'
            + '、'.join(f'{k} {it.get(k, 0)}' for k in INST_TYPE_ORDER), fontsize=8.6, color=INK2, va='center')
a3.set_yticks(yy, [n for n, _ in grp], fontsize=9.6)
a3.set_ylim(1.75, -0.6)
a3.set_xlim(0, 100)
a3.set_xlabel('合作關係的組成（%，合作者人數加總）')
a3.tick_params(axis='y', length=0)
a3.spines['left'].set_visible(False)
a3.legend(loc='upper center', bbox_to_anchor=(0.5, -0.22), ncol=4, fontsize=9)
a3.set_title('C　同樣產出、經費差很多的人，合作對象有什麼不同？\n'
             '期刊 5 篇以上的人，依「個人研究經費相對於期刊論文數」的殘差分組', fontsize=11.5)

fig.suptitle('和經費對照：經費多的人在合作網路的哪裡？（描述，不是因果）', x=0.05, y=0.995, ha='left', fontsize=15,
             fontweight='bold')
fig.text(0.05, 0.958, '經費 = 2015–2025 起始、擔任主持人的個人研究計畫（一般、新進、年輕學者獎勵、特約與其他專題），定義同 funding_analysis，'
         '不含推動規劃、人才培育等機構性經費。\n合作指標來自含外部作者的網路；betweenness 來自名冊內網路（421 人一起正規化）。', fontsize=9.5, color=INK2)
save(fig, '10_funding_link.png')

section('數字')
print('Spearman 經費 vs 合作者', round(rho_all, 3), '有經費', round(rho_f, 3), 'n', fund.sum(), '｜vs 名冊內', round(rho_r, 3),
      '｜vs 排除大團隊', round(stats.spearmanr(r.funding, r.n_collab_small).statistic, 3),
      '｜vs 國外', round(stats.spearmanr(r.funding, r['n_國外']).statistic, 3),
      '｜vs btw', round(stats.spearmanr(r.funding, r.btw).statistic, 3))
print('partial：控制期刊', end=' ')
rk = r[['funding', 'n_collab', 'journal', 'roster_degree']].rank()
for c in ('n_collab', 'roster_degree'):
    ra = rk.funding - np.polyval(np.polyfit(rk.journal, rk.funding, 1), rk.journal)
    rb = rk[c] - np.polyval(np.polyfit(rk.journal, rk[c], 1), rk.journal)
    print(c, round(np.corrcoef(ra, rb)[0, 1], 3), end=' ')
print()
print('前 25 名百分位中位數', {c: round(v, 1) for c, v in med.items()})
show = ['name_zh', 'inst_short_2026', 'rank_2026', 'f_wan', 'n_collab', 'roster_degree', 'btw', 'n_core', 'n_國外', 'journal']
print(tb[show].round(2).to_string())
print('前 25 名 名冊內 0 合作者', (tb.roster_degree == 0).sum(), '｜在名冊內前 10% betweenness', (tb.btw >= r.btw.quantile(0.9)).sum())
print('前 25 名彼此之間的合作對', sum(1 for u, v in G.edges() if u in tb.index and v in tb.index))
print('C：迴歸斜率', round(sl, 3), 'n', len(base))
for name, s in grp:
    tot = s[[f'n_{c}' for c in COLLAB_ORDER]].sum()
    print(name.replace('\n', ''), len(s), '組成', (tot / tot.sum()).round(3).to_dict(), '中位合作者', s.n_collab.median(),
          '名冊內', s.roster_degree.median(), '國外', s['n_國外'].median(), '期刊', s.journal.median(), '經費', s.f_wan.median(),
          s.inst_type_2026.value_counts().to_dict(), '沒經費', (s.funding == 0).sum())
# 合作對象是否也是經費多的人：名冊內合作者的平均經費
fq = r.funding.rank(pct=True)
for name, s in grp:
    nb = [fq[v] for n in s.index if n in G for v in G.neighbors(n)]
    print(name.replace('\n', ''), '名冊內合作者的經費百分位平均', round(np.mean(nb), 3) if nb else None, '對數', len(nb))
print('經費低於產出：', lo.sort_values('resid')[['name_zh', 'inst_short_2026', 'journal', 'f_wan', 'n_collab', 'roster_degree']].head(10).to_string())
print('經費高於產出：', hi.sort_values('resid', ascending=False)[['name_zh', 'inst_short_2026', 'journal', 'f_wan', 'n_collab', 'roster_degree']].head(10).to_string())
