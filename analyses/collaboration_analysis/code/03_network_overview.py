"""03 網路全貌：2015–2025 名冊內共著網路（external=False），兩端都是名冊學者。

左：節點顏色 = 機構類型（2026），大小 = 期刊論文數，標出度數與 betweenness 最高的幾位。
右：同一個布局，顏色 = Leiden 社群（modularity，邊權 = 合著論文數，seed 20261012），標出主要社群的機構組成。
最大連通元件用 spring layout；其他小元件與孤立點排在下方。
"""
import igraph as ig
import leidenalg
import networkx as nx
import numpy as np

from _common import (INK, INK2, INST_TYPE_COLOR, INST_TYPE_ORDER, LIGHTGREY, MUTED, SEED, graph, load_all,
                     person_collab, plt, save, section)

d = load_all()
r = person_collab(d)
G = graph(d, layer='pub', year_from=2015, year_to=2025, external=False, include_isolates=True)
G.remove_nodes_from([n for n in list(G) if n not in r.index])

comps = sorted(nx.connected_components(G), key=len, reverse=True)
lcc = G.subgraph(comps[0]).copy()
small = [c for c in comps[1:] if len(c) > 1]
iso = [n for c in comps if len(c) == 1 for n in c]

deg = dict(G.degree())
btw = nx.betweenness_centrality(lcc)

# ---- Leiden（不含孤立點）----
H = G.subgraph([n for n in G if deg[n] > 0])
nodes = list(H)
idx = {n: i for i, n in enumerate(nodes)}
ih = ig.Graph(n=len(nodes), edges=[(idx[u], idx[v]) for u, v in H.edges()])
ih.es['weight'] = [H[u][v]['count'] for u, v in H.edges()]
part = leidenalg.find_partition(ih, leidenalg.ModularityVertexPartition, weights='weight', seed=SEED)
comm = {nodes[i]: c for i, c in enumerate(part.membership)}
Q = ih.modularity(part.membership, weights='weight')
sizes = np.bincount(part.membership)
order = np.argsort(-sizes)
rank_of = {c: k for k, c in enumerate(order)}
N_SHOW = 10
PAL = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948', '#5ab4e5', '#9c6b30']

# ---- 布局：先排社群（社群間邊數當權重），再在各社群內做 spring layout，避免中心擠成一團 ----
lcc_comms = sorted({comm[n] for n in lcc}, key=lambda c: -sizes[c])
M = nx.Graph()
M.add_nodes_from(lcc_comms)
for u, v in lcc.edges():
    cu, cv = comm[u], comm[v]
    if cu != cv:
        w = M.get_edge_data(cu, cv, {'weight': 0})['weight']
        M.add_edge(cu, cv, weight=w + 1)
rad = {c: 0.07 * np.sqrt(sizes[c]) for c in lcc_comms}
cen = nx.spring_layout(M, seed=SEED, weight='weight', k=1.2, iterations=500)
cen = {c: np.array(p) * 1.4 for c, p in cen.items()}
for _ in range(400):  # 圓形不重疊
    moved = False
    for i, a in enumerate(lcc_comms):
        for b in lcc_comms[i + 1:]:
            dv = cen[a] - cen[b]
            dist = np.linalg.norm(dv) + 1e-9
            need = rad[a] + rad[b] + 0.06
            if dist < need:
                push = (need - dist) / 2 * dv / dist
                cen[a] = cen[a] + push
                cen[b] = cen[b] - push
                moved = True
    if not moved:
        break
pos = {}
for c in lcc_comms:
    sub = lcc.subgraph([n for n in lcc if comm[n] == c])
    sp = nx.spring_layout(sub, seed=SEED, iterations=200) if len(sub) > 1 else {next(iter(sub)): np.zeros(2)}
    sp = {n: np.array(p) for n, p in sp.items()}
    m = max(np.linalg.norm(p) for p in sp.values()) or 1
    for n, p in sp.items():
        pos[n] = cen[c] + p / m * rad[c]
P = np.array(list(pos.values()))
lo, hi = P.min(0), P.max(0)
pos = {n: ((p[0] - lo[0]) / (hi[0] - lo[0]) * 2.0, (p[1] - lo[1]) / (hi[1] - lo[1]) * 1.45 + 0.58) for n, p in pos.items()}
# 小元件：一排；孤立點：網格
x0 = 0.0
for c in small:
    sub = G.subgraph(c)
    sp = nx.spring_layout(sub, seed=SEED, scale=0.035 * np.sqrt(len(c)))
    for n, p in sp.items():
        pos[n] = (x0 + 0.05 + p[0], 0.33 + p[1])
    x0 += 0.12 + 0.03 * len(c)
iso_sorted = sorted(iso, key=lambda n: (INST_TYPE_ORDER.index(r.loc[n, 'inst_type_2026']), -r.loc[n, 'journal']))
ncol = 34
for k, n in enumerate(iso_sorted):
    pos[n] = (0.03 + (k % ncol) * (1.95 / (ncol - 1)), 0.15 - (k // ncol) * 0.055)

size = {n: 10 + 9 * np.sqrt(r.loc[n, 'journal']) for n in G}
top_deg = sorted(lcc, key=lambda n: -deg[n])[:8]
top_btw = sorted(lcc, key=lambda n: -btw[n])[:8]
labeled = list(dict.fromkeys(top_deg + top_btw))


def draw(ax, colors):
    nx.draw_networkx_edges(G, pos, ax=ax, width=[0.4 + 0.5 * min(G[u][v]['count'], 6) for u, v in G.edges()],
                           edge_color='#b9b8b3', alpha=0.55)
    ns = list(G)
    ax.scatter([pos[n][0] for n in ns], [pos[n][1] for n in ns], s=[size[n] for n in ns], c=[colors[n] for n in ns],
               edgecolors='white', linewidths=0.6, zorder=3)
    ax.set_xlim(-0.05, 2.08)
    ax.set_ylim(-0.12, 2.2)
    ax.axis('off')
    ax.plot([0, 2.0], [0.24, 0.24], color=LIGHTGREY, lw=0.8)
    ax.text(0.0, 0.405, f'其他小元件（{len(small)} 個，共 {sum(len(c) for c in small)} 人）', fontsize=8.5, color=INK2)
    ax.text(0.0, 0.225, f'孤立點：名冊內沒有任何合作者（{len(iso)} 人，依機構類型排列）', fontsize=8.5, color=INK2, va='top')


fig, (a1, a2) = plt.subplots(1, 2, figsize=(19, 11), gridspec_kw=dict(wspace=0.04))
col_type = {n: INST_TYPE_COLOR.get(r.loc[n, 'inst_type_2026'], LIGHTGREY) for n in G}
draw(a1, col_type)
texts = []
for n in labeled:
    x, y = pos[n]
    tag = []
    if n in top_deg:
        tag.append(f'度 {deg[n]}')
    if n in top_btw:
        tag.append(f'B {btw[n]:.2f}')
    t = a1.text(x, y + 0.035, f'{r.loc[n, "name_zh"]}（{r.loc[n, "inst_short_2026"]}）\n{"・".join(tag)}', fontsize=8.6,
                ha='center', va='bottom', color=INK, zorder=6,
                bbox=dict(boxstyle='round,pad=0.15', fc='white', ec='none', alpha=0.75))
    texts.append(t)
for t in INST_TYPE_ORDER:
    a1.scatter([], [], s=60, color=INST_TYPE_COLOR[t], label=f'{t}（{(r.inst_type_2026 == t).sum()} 人）')
for j in (1, 10, 40):
    a1.scatter([], [], s=10 + 9 * np.sqrt(j), color=MUTED, label=f'期刊論文 {j} 篇')
a1.legend(loc='upper right', fontsize=9, ncol=2, bbox_to_anchor=(1.0, 1.0), handletextpad=0.3, columnspacing=1)
a1.set_title('A　節點顏色：機構類型（2026）；大小：2015–2025 期刊論文數\n標籤：度數前 8（度）與 betweenness 前 8（B）', pad=6)

col_comm = {n: (PAL[rank_of[comm[n]]] if n in comm and rank_of[comm[n]] < N_SHOW else LIGHTGREY) for n in G}
draw(a2, col_comm)
ctexts = []
for k in range(N_SHOW):
    c = order[k]
    mem = [n for n in comm if comm[n] == c]
    xs = np.array([pos[n] for n in mem])
    vc = r.loc[mem, 'inst_short_2026'].value_counts()
    top = '、'.join(f'{i} {v}' for i, v in vc.head(3).items())
    cx, cy = xs[:, 0].mean(), xs[:, 1].max() + 0.03
    ctexts.append(a2.text(cx, cy, f'C{k + 1}（{len(mem)} 人）\n{top}', fontsize=8.6, ha='center', va='bottom', color=INK,
                          zorder=6, bbox=dict(boxstyle='round,pad=0.25', fc='white', ec=PAL[k], lw=1.4, alpha=0.9)))
a2.set_title(f'B　節點顏色：Leiden 社群（前 {N_SHOW} 大，其餘灰色）；modularity {Q:.2f}\n'
             '方框：社群編號、人數、人數最多的三個機構', pad=6)

fig.canvas.draw()
from _common import repel  # noqa: E402
repel(a1, texts, move_x=True)
repel(a2, ctexts, move_x=True)

lcc_n = lcc.number_of_nodes()
fig.suptitle('名冊內共著網路的全貌（2015–2025，名冊內網路：兩端都是名冊學者）', x=0.06, y=0.995, ha='left',
             fontsize=15, fontweight='bold')
fig.text(0.06, 0.957, f'421 人、{G.number_of_edges()} 對合作（密度 {nx.density(G):.4f}）。最大連通元件 {lcc_n} 人（{lcc_n / 421:.0%}），'
         f'孤立點 {len(iso)} 人。邊的粗細 = 合著論文數。機構為 2026 年快照；名冊學者被當成外部作者時，'
         '這裡會少一條邊（Exploratory Analysis 18）。', fontsize=9.5, color=INK2)
save(fig, '03_network_overview.png')

section('數字')
print('節點', G.number_of_nodes(), '邊', G.number_of_edges(), '密度', round(nx.density(G), 4))
print('LCC', lcc_n, '第二大', len(comps[1]), '小元件', len(small), sum(len(c) for c in small), '孤立', len(iso))
print('LCC 平均距離', round(nx.average_shortest_path_length(lcc), 2), '直徑', nx.diameter(lcc),
      'transitivity', round(nx.transitivity(G), 3), '平均度', round(np.mean(list(deg.values())), 2))
print('Leiden 社群數', len(sizes), 'Q', round(Q, 3), '前 10 大', sorted(sizes, reverse=True)[:12])
for n in labeled:
    print(r.loc[n, 'name_zh'], r.loc[n, 'inst_short_2026'], r.loc[n, 'rank_2026'], '度', deg[n], 'B', round(btw[n], 3),
          '期刊', r.loc[n, 'journal'])
for k in range(N_SHOW):
    mem = [n for n in comm if comm[n] == order[k]]
    rr = r.loc[mem]
    print(f'C{k + 1}', len(mem), rr.inst_short_2026.value_counts().head(4).to_dict(), rr.field.value_counts().head(3).to_dict())
# 社群內同機構比例
same = np.mean([r.loc[u, 'institution_2026'] == r.loc[v, 'institution_2026'] for u, v in G.edges()])
print('名冊內合作對中同機構', round(same, 3))
print('孤立點 機構類型', r.loc[iso, 'inst_type_2026'].value_counts().to_dict())
