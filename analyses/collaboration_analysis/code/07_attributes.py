"""07 屬性：合作者人數依職級、性別、博士來源、研究領域的分布（上），名冊內網路的同質性（下）。

上：含外部作者的網路，每點一位學者，箱形圖 + 抖動點；標出各組最高的人。職級、機構為 2026 年快照。
下：名冊內網路（527 對）中，兩端屬性相同的比例，和「把屬性在有合作的學者之間隨機重排 1,000 次」（保留網路結構，
seed 20261012）比較。屬性缺漏的對不算。
"""
import networkx as nx
import numpy as np

from _common import (BLUE, GENDER_COLOR, GENDER_LABEL, GREY, INK, INK2, MUTED, ORANGE, PHD_ORDER, RANK_ORDER, SEED,
                     VIOLET, graph, load_all, person_collab, plt, save, section)

d = load_all()
r = person_collab(d)
r['gender_zh'] = r.gender.map(GENDER_LABEL)
TOPF = r.field.value_counts().head(8).index.tolist()
r['field8'] = r.field.where(r.field.isin(TOPF), '其他領域')

PANELS = [('rank_group_2026', RANK_ORDER, '職級（2026）', {'助理': '#7fb2ea', '副': BLUE, '正': '#174a8b'}),
          ('gender_zh', ['男', '女'], '性別', {'男': GENDER_COLOR['M'], '女': GENDER_COLOR['F']}),
          ('phd_origin', PHD_ORDER, '博士來源', {'國內': '#1baf7a', '美國': VIOLET, '其他國外': '#e87ba4'}),
          ('field8', TOPF + ['其他領域'], '研究領域（JEL 主類，前 8 + 其他）', None)]

fig = plt.figure(figsize=(18, 11.5))
gs = fig.add_gridspec(2, 4, width_ratios=[1, 0.75, 1, 2.4], height_ratios=[1.15, 1], hspace=0.5, wspace=0.28)
rng = np.random.default_rng(SEED)
for k, (col, order, title, cmap) in enumerate(PANELS):
    ax = fig.add_subplot(gs[0, k])
    data = [np.log10(r.loc[r[col] == g, 'n_collab'] + 1).values for g in order]
    ax.boxplot(data, positions=range(len(order)), widths=0.55, showfliers=False,
               medianprops=dict(color=INK, lw=1.6), boxprops=dict(color=MUTED), whiskerprops=dict(color=MUTED),
               capprops=dict(color=MUTED))
    for i, g in enumerate(order):
        v = data[i]
        c = cmap[g] if cmap else GREY
        ax.scatter(i + rng.uniform(-0.2, 0.2, len(v)), v, s=9, color=c, alpha=0.55, lw=0, zorder=3)
        sub = r[r[col] == g]
        if len(sub):
            top = sub.loc[sub.n_collab.idxmax()]
            ax.text(i + 0.08, np.log10(top.n_collab + 1) + 0.04, f'{top.name_zh}\n{top.n_collab}', fontsize=7.6,
                    color=INK2, ha='center', va='bottom')
    labels = [(g.replace(' ', '\n', 1) if col == 'field8' else g)
              + f'\nn={(r[col] == g).sum()}\n中位 {r.loc[r[col] == g, "n_collab"].median():.0f}' for g in order]
    ax.set_xticks(range(len(order)), labels, fontsize=8.4 if col == 'field8' else 9.5)
    ax.tick_params(axis='x', length=0)
    ticks = [0, 1, 2, 5, 10, 20, 50, 100, 200]
    ax.set_yticks(np.log10(np.array(ticks) + 1), [str(t) for t in ticks])
    ax.set_ylim(-0.05, 2.75)
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)
    if k == 0:
        ax.set_ylabel('2015–2025 合作者人數（人，含外部；對數軸）')
    ax.set_title(('A　' if k == 0 else '') + title, fontsize=11.5)
    miss = r[col].isna().sum() if col != 'field8' else r.field.isna().sum()
    if miss:
        ax.text(1.0, 1.0, f'缺 {miss} 人', transform=ax.transAxes, ha='right', va='top', fontsize=8, color=MUTED)

# ---- 同質性 ----
G = graph(d, layer='pub', year_from=2015, year_to=2025, external=False)
G.remove_nodes_from([n for n in list(G) if n not in r.index])
edges = list(G.edges())
nodes = list(G)
ATTR = [('gender', '性別'), ('phd_origin', '博士來源（國內／美國／其他）'), ('field', '研究領域（JEL 主類）'),
        ('rank_group_2026', '職級（2026）'), ('inst_type_2026', '機構類型（2026）'), ('institution_2026', '同一機構（2026）')]
NPERM = 1000
deg = dict(G.degree())
DBIN = {n: (1 if deg[n] == 1 else 2 if deg[n] == 2 else 3 if deg[n] <= 4 else 4 if deg[n] <= 8 else 5) for n in nodes}


def perm_test(arr, U, V, strata=None):
    sims = np.empty(NPERM)
    for i in range(NPERM):
        if strata is None:
            perm = rng.permutation(arr)
        else:
            perm = arr.copy()
            for ids in strata:
                perm[ids] = rng.permutation(arr[ids])
        sims[i] = np.mean(perm[U] == perm[V])
    return sims


res = []
for col, lab in ATTR:
    val = r[col].reindex(nodes)
    known = val.notna()
    kn = val[known]
    ek = [(u, v) for u, v in edges if known[u] and known[v]]
    obs = np.mean([val[u] == val[v] for u, v in ek])
    idx = {n: i for i, n in enumerate(kn.index)}
    U = np.array([idx[u] for u, _ in ek])
    V = np.array([idx[v] for _, v in ek])
    arr = kn.values
    bins = np.array([DBIN[n] for n in kn.index])
    s1 = perm_test(arr, U, V)
    s2 = perm_test(arr, U, V, [np.where(bins == b)[0] for b in np.unique(bins)])
    res.append(dict(lab=lab, obs=obs, n=len(ek), mean=s1.mean(), lo=np.percentile(s1, 2.5), hi=np.percentile(s1, 97.5),
                    p=(np.sum(s1 >= obs) + 1) / (NPERM + 1), mean_s=s2.mean(), lo_s=np.percentile(s2, 2.5),
                    hi_s=np.percentile(s2, 97.5), p_s=(np.sum(s2 >= obs) + 1) / (NPERM + 1)))

ax = fig.add_subplot(gs[1, :3])
yy = np.arange(len(res))[::-1]
for y, z in zip(yy, res):
    ax.plot([z['lo'] * 100, z['hi'] * 100], [y + 0.17] * 2, color='#d6d5d0', lw=6, solid_capstyle='round', zorder=1)
    ax.plot([z['lo_s'] * 100, z['hi_s'] * 100], [y - 0.17] * 2, color='#8fa3b8', lw=6, solid_capstyle='round', zorder=1)
    sig = z['obs'] > z['hi_s']
    ax.scatter(z['obs'] * 100, y, s=85, color=ORANGE if sig else MUTED, zorder=3, edgecolor='white')
    ax.text(max(z['obs'], z['hi'], z['hi_s']) * 100 + 2, y, f'觀察 {z["obs"]:.0%}｜隨機 {z["mean"]:.0%}｜同度數組 '
            f'{z["mean_s"]:.0%}（{z["obs"] / z["mean_s"]:.1f} 倍）', va='center', fontsize=9,
            color=INK if sig else MUTED)
ax.set_yticks(yy, [z['lab'] for z in res], fontsize=10)
ax.set_xlim(0, 100)
ax.set_xlabel('兩端屬性相同的合作對比例（%）')
ax.xaxis.grid(True)
ax.set_axisbelow(True)
ax.tick_params(axis='y', length=0)
ax.spines['left'].set_visible(False)
ax.set_title('B　名冊內網路的同質性：合作對中兩人屬性相同的比例\n'
             '淺灰帶 = 全部隨機重排的 95% 區間；藍灰帶 = 只在同度數組內重排；橘點 = 高於藍灰帶', fontsize=11.5)

ax2 = fig.add_subplot(gs[1, 3])
ax2.axis('off')
txt = ('怎麼看 B\n'
       '・在「有名冊內合作者」的 321 人之間交換屬性 1,000 次，\n'
       '  網路結構不變（seed 20261012）。\n'
       '・淺灰：全部人一起重排。\n'
       '・藍灰：只在名冊內合作者數相近的人之間重排\n'
       '  （1、2、3–4、5–8、9 人以上），保留「哪一組人\n'
       '  合作者較多」。女性、助理級的名冊內合作者較少，\n'
       '  只用淺灰會把這種差異誤當成同質性。\n'
       '・同一機構的隨機比例很低，是因為機構多、每校人少。\n\n'
       '注意\n'
       '・屬性是 2026 快照（機構、職級），不是合作當時的。\n'
       '・研究領域由專長文字對應，約 30% 和計畫學門不一致。\n'
       '・同質性是描述，不代表「因為相同才合作」；\n'
       '  同校的人本來就比較可能同領域、同博士來源。')
ax2.text(0.02, 0.95, txt, va='top', fontsize=9.6, color=INK2, linespacing=1.55)

fig.suptitle('合作和學者屬性有什麼關係？2015–2025', x=0.06, y=0.995, ha='left', fontsize=15, fontweight='bold')
fig.text(0.06, 0.958, 'A：含外部作者的網路，一點一位名冊學者，標出各組合作者最多的人（姓名下為人數）。'
         'B：名冊內網路。職級、機構為 2026 年快照；博士來源依博士學校國別。', fontsize=9.5, color=INK2)
save(fig, '07_attributes.png')

section('數字')
for col, order, title, _ in PANELS:
    g = r.groupby(col).n_collab.agg(['size', 'median', 'mean'])
    g['國外中位'] = r.groupby(col)['n_國外'].median()
    g['名冊內中位'] = r.groupby(col)['n_名冊內'].median()
    g['top'] = r.groupby(col).apply(lambda x: f'{x.loc[x.n_collab.idxmax(), "name_zh"]} {x.n_collab.max()}')
    print(title, '\n', g.reindex(order).round(1).to_string())
for z in res:
    print(z['lab'], {k: round(float(v), 3) for k, v in z.items() if k != 'lab'})
print('有名冊內合作者的人', len(nodes))
# 同性別細看：女女、男男
gm = r.gender.reindex(nodes)
ff = np.mean([(gm[u] == 'F') and (gm[v] == 'F') for u, v in edges])
print('女–女比例', round(ff, 3), '女性佔', round((gm == 'F').mean(), 3))
