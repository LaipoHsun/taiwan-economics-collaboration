"""05 時間：2015–2025 每年的合著論文數、團隊人數、名冊內合作佔比、國外合作佔比、新／重複合作對。

論文 = 至少一位名冊學者、edge_eligible == 1。2026 年資料不完整，只以灰色空心點標示，不連線。
「排除邱永和」的虛線：他一人佔合著論文的 3%、國外合作者的 18%（見 01），檢查趨勢是否由他主導。
"""
import numpy as np

from _common import (AQUA, BLUE, FINE_COLOR, GREY, INK, INK2, LIGHTGREY, MAGENTA, MUTED, ORANGE, YEARS, eligible_papers, load_all, node_class, plt, save, section)

d = load_all()
ALLY = YEARS + [2026]
cls = node_class(d)
roster_ids = set(d.nodes.node_id[d.nodes.node_type == 'roster'])
OUTLIER = d.nodes.loc[d.nodes.name_zh.eq('邱永和') & d.nodes.node_type.eq('roster'), 'node_id'].iloc[0]

p = eligible_papers(d, ALLY)[['paper_id', 'year', 'pub_category', 'n_authors']]
pa = d.paper_authors[['paper_id', 'node_id']].drop_duplicates().merge(p, on='paper_id')
pa['cls'] = pa.node_id.map(cls).fillna('未知')
g = pa.groupby('paper_id')
P = p.set_index('paper_id').assign(
    n_roster=g.cls.apply(lambda s: (s == '名冊內').sum()),
    foreign=g.cls.apply(lambda s: (s == '國外').any()),
    unknown=g.cls.apply(lambda s: (s == '未知').any()),
    outlier=g.node_id.apply(lambda s: OUTLIER in set(s)))
P = P.astype({'foreign': bool, 'unknown': bool, 'outlier': bool})
P = P[P.n_roster >= 1]
co = P[P.n_authors >= 2]

# 合作對：新（2015 起第一次出現）或重複
e = d.paper_edges[d.paper_edges.paper_id.isin(p.paper_id)].copy()
a = e[['source_node_id', 'target_node_id']].min(axis=1)
b = e[['source_node_id', 'target_node_id']].max(axis=1)
pairs = e.assign(u=a, v=b)[['u', 'v', 'year', 'both_roster']].drop_duplicates()
pairs = pairs[pairs.u.isin(roster_ids) | pairs.v.isin(roster_ids)]  # 至少一端是名冊學者
first = pairs.groupby(['u', 'v']).year.min().rename('first')
pairs = pairs.join(first, on=['u', 'v'])
pairs['new'] = pairs.year == pairs['first']


def series(df, f):
    return df.groupby('year').apply(f).reindex(ALLY)


fig, axs = plt.subplots(2, 3, figsize=(17, 9.5), gridspec_kw=dict(hspace=0.42, wspace=0.26))
X = np.array(YEARS)


def finish(ax, title, ylabel, ylim=None):
    ax.set_title(title, fontsize=12)
    ax.set_ylabel(ylabel)
    ax.set_xticks(ALLY, [str(y) if y % 2 else str(y) for y in ALLY], rotation=0, fontsize=8)
    ax.set_xlim(2014.4, 2026.6)
    if ylim:
        ax.set_ylim(*ylim)
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)
    ax.axvspan(2025.5, 2026.6, color='#f3f2ee', zorder=0)


def line(ax, s, color, label, ls='-', marker='o', lw=2):
    ax.plot(X, s.loc[YEARS].values, color=color, ls=ls, lw=lw, marker=marker, ms=4, label=label)
    ax.scatter([2026], [s.loc[2026]], facecolor='white', edgecolor=color, s=26, zorder=4)


# A 論文數
ax = axs[0, 0]
n_co = co.groupby('year').size().reindex(ALLY, fill_value=0)
n_solo = P[P.n_authors == 1].groupby('year').size().reindex(ALLY, fill_value=0)
n_co_j = co[co.pub_category == '期刊論文'].groupby('year').size().reindex(ALLY, fill_value=0)
ax.bar(ALLY, n_co, color=[BLUE] * len(YEARS) + [LIGHTGREY], width=0.72, label='合著論文（2 位以上作者）')
ax.bar(ALLY, n_solo, bottom=n_co, color='white', edgecolor=LIGHTGREY, hatch='////', width=0.72, label='單一作者')
line(ax, n_co_j, INK, '其中期刊論文', marker='o', lw=1.5)
ax.legend(fontsize=8.5, loc='upper right')
finish(ax, 'A　每年論文數', '篇', (0, 640))

# B 團隊人數
ax = axs[0, 1]
line(ax, series(co, lambda x: x.n_authors.mean()), BLUE, '全部合著論文')
line(ax, series(co[co.pub_category == '期刊論文'], lambda x: x.n_authors.mean()), INK, '只看期刊論文')
line(ax, series(co[co.n_authors < 6], lambda x: x.n_authors.mean()), GREY, '排除 6 人以上論文', ls='--')
ax.legend(fontsize=8.5, loc='upper left')
finish(ax, 'B　合著論文的平均作者數', '人', (2, 3.8))

# C 名冊內合作佔比
ax = axs[0, 2]
line(ax, series(co, lambda x: (x.n_roster >= 2).mean() * 100), AQUA, '全部合著論文')
line(ax, series(co[~co.outlier], lambda x: (x.n_roster >= 2).mean() * 100), AQUA, '排除邱永和的論文', ls='--', lw=1.4)
ax.legend(fontsize=8.5, loc='lower left')
finish(ax, 'C　有 2 位以上名冊學者的合著論文比例', '%', (0, 50))

# D 國外合作佔比
ax = axs[1, 0]
line(ax, series(co, lambda x: x.foreign.mean() * 100), MAGENTA, '有國外作者（下限）')
line(ax, series(co[~co.outlier], lambda x: x.foreign.mean() * 100), MAGENTA, '同上，排除邱永和的論文', ls='--', lw=1.4)
line(ax, series(co, lambda x: x.unknown.mean() * 100), MUTED, '有位置未知的作者')
ax.legend(fontsize=8.5, loc='lower right')
finish(ax, 'D　合著論文中有國外／未知作者的比例', '%', (0, 60))

# E 每年合作對數：新 vs 重複
ax = axs[1, 1]
nn = pairs[pairs.new].groupby('year').size().reindex(ALLY, fill_value=0)
nr = pairs[~pairs.new].groupby('year').size().reindex(ALLY, fill_value=0)
ax.bar(ALLY, nr, color=[ORANGE] * len(YEARS) + [LIGHTGREY], width=0.72, label='重複（以前合作過）')
ax.bar(ALLY, nn, bottom=nr, color=['#f6c3a8'] * len(YEARS) + ['#eeeeea'], width=0.72, label='新（2015 年以來第一次）')
ax.legend(fontsize=8.5, loc='upper left')
finish(ax, 'E　每年出現的合作對（至少一端是名冊學者）\n2015–2017 的「新」包含更早就合作過的對（暖身期）', '對', (0, 950))
pass

# F 新合作對比例
ax = axs[1, 2]
newsh = (nn / (nn + nr) * 100)
pr = pairs[pairs.both_roster == 1]
newr = pr.groupby('year').new.mean().reindex(ALLY) * 100
pe = pairs[pairs.both_roster == 0]
newe = pe.groupby('year').new.mean().reindex(ALLY) * 100
line(ax, newe, '#eda100', '名冊學者–外部作者')
line(ax, newr, AQUA, '名冊學者之間')
ax.axvspan(2014.4, 2017.5, color='#f3f2ee', zorder=0)
ax.text(2015.9, 3, '暖身期', fontsize=8.5, color=INK2, ha='center')
ax.legend(fontsize=8.5, loc='lower right')
finish(ax, 'F　當年合作對中「新」的比例', '%', (0, 100))

fig.suptitle('合作怎麼隨時間變化？2015–2025（含外部作者的網路；2026 不完整，灰色空心點）', x=0.06, y=0.995,
             ha='left', fontsize=15, fontweight='bold')
fig.text(0.06, 0.955, '論文 = 至少一位名冊學者的可建邊著作（期刊、研討會、專書等）。國外 = 已記錄國別為台灣以外；'
         '查不到國別的外部作者算未知，所以國外比例是下限。', fontsize=9.5, color=INK2)
save(fig, '05_over_time.png')

section('數字')
tab = dict(co=n_co, solo=n_solo, co_j=n_co_j,
           team=series(co, lambda x: x.n_authors.mean()), team_j=series(co[co.pub_category == '期刊論文'], lambda x: x.n_authors.mean()),
           roster=series(co, lambda x: (x.n_roster >= 2).mean()), foreign=series(co, lambda x: x.foreign.mean()),
           foreign_ex=series(co[~co.outlier], lambda x: x.foreign.mean()), unknown=series(co, lambda x: x.unknown.mean()),
           pairs=nn + nr, new_all=newsh / 100, new_roster=newr / 100, new_ext=newe / 100)
import pandas as pd  # noqa: E402
print(pd.DataFrame(tab).round(3).to_string())
print('2015–2025 合著', int(n_co.loc[YEARS].sum()), '獨著', int(n_solo.loc[YEARS].sum()))
print('合著論文中有國外（11 年）', round(co[co.year <= 2025].foreign.mean(), 3), '有名冊 2 人以上', round((co[co.year <= 2025].n_roster >= 2).mean(), 3))
