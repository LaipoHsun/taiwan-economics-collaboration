"""04 機構：名冊 27 個機構之間的合著論文數（左，名冊內網路）與各機構學者的合作對象組成（右，含外部作者的網路）。

左：格子 = 2015–2025 同時有兩機構名冊學者的論文篇數；對角線 = 有 2 位以上同校名冊學者的論文。
右：各機構學者的「學者–合作者」關係，依合作者位置分類（同校名冊、他校名冊、國內外部、國外、未知）。
機構為 2026 年快照。
"""
from itertools import combinations

import numpy as np
from matplotlib.colors import LogNorm, LinearSegmentedColormap
from matplotlib.patches import Patch

from _common import (AQUA, FINE_COLOR, INK, INK2, INST_TYPE_COLOR, INST_TYPE_ORDER, eligible_papers, ego_ties,
                     load_all, person_collab, plt, save, section)

d = load_all()
r = person_collab(d)
inst = r.inst_short_2026
itype = r.groupby('inst_short_2026').inst_type_2026.first()
n_sch = inst.value_counts()
ORDER = sorted(n_sch.index, key=lambda i: (INST_TYPE_ORDER.index(itype[i]), -n_sch[i]))
K = len(ORDER)
ix = {i: k for k, i in enumerate(ORDER)}

# ---- 機構 × 機構 論文數 ----
p = eligible_papers(d)
pa = d.paper_authors[['paper_id', 'node_id']].drop_duplicates()
pa = pa[pa.paper_id.isin(p.paper_id) & pa.node_id.isin(r.index)]
pa['inst'] = pa.node_id.map(inst)
M = np.zeros((K, K))
for pid, g in pa.groupby('paper_id'):
    vc = g.inst.value_counts()
    for i, c in vc.items():
        if c >= 2:
            M[ix[i], ix[i]] += 1
    for a, b in combinations(sorted(vc.index, key=ix.get), 2):
        M[ix[a], ix[b]] += 1
        M[ix[b], ix[a]] += 1
n_multi = pa.groupby('paper_id').size().ge(2).sum()  # 2 位以上名冊學者的論文

# ---- 合作對象組成 ----
t = ego_ties(d)
t['inst'] = t.ego.map(inst)
t['alter_inst'] = t.alter.map(inst)
t['cat'] = t.cls
t.loc[t.cls == '名冊內', 'cat'] = np.where(t.loc[t.cls == '名冊內', 'inst'] == t.loc[t.cls == '名冊內', 'alter_inst'],
                                           '同校名冊', '他校名冊')
t.loc[t.cls.isin(['名冊27校外部作者', '國內其他機構']), 'cat'] = '國內外部'
CATS = ['同校名冊', '他校名冊', '國內外部', '國外', '未知']
CCOL = {'同校名冊': '#0f7a52', '他校名冊': AQUA, '國內外部': FINE_COLOR['名冊27校外部作者'], '國外': FINE_COLOR['國外'],
        '未知': FINE_COLOR['未知']}
comp = t.groupby(['inst', 'cat']).size().unstack(fill_value=0).reindex(index=ORDER, columns=CATS, fill_value=0)
share = comp.div(comp.sum(axis=1), axis=0)

fig = plt.figure(figsize=(18, 11))
gs = fig.add_gridspec(1, 2, width_ratios=[1.35, 1], wspace=0.05)
a1, a2 = fig.add_subplot(gs[0]), fig.add_subplot(gs[1])

cmap = LinearSegmentedColormap.from_list('b', ['#eef4fb', '#2a78d6', '#0c2d5e'])
Mm = np.ma.masked_where(M == 0, M)
im = a1.imshow(Mm, cmap=cmap, norm=LogNorm(vmin=1, vmax=M.max()), aspect='auto')
for i in range(K):
    for j in range(K):
        if M[i, j] > 0:
            a1.text(j, i, f'{int(M[i, j])}', ha='center', va='center', fontsize=7,
                    color='white' if M[i, j] >= 12 else INK)
for i in range(K):
    a1.add_patch(plt.Rectangle((i - 0.5, i - 0.5), 1, 1, fill=False, ec=INK, lw=0.9))
labels = [f'{i}（{n_sch[i]}）' for i in ORDER]
a1.set_xticks(range(K), [i for i in ORDER], rotation=90, fontsize=9)
a1.set_yticks(range(K), labels, fontsize=9.5)
for tl, i in zip(a1.get_yticklabels(), ORDER):
    tl.set_color(INST_TYPE_COLOR[itype[i]])
for tl, i in zip(a1.get_xticklabels(), ORDER):
    tl.set_color(INST_TYPE_COLOR[itype[i]])
# 類型分隔線
bounds = np.cumsum([sum(itype[i] == tp for i in ORDER) for tp in INST_TYPE_ORDER])[:-1]
for b in bounds:
    a1.axhline(b - 0.5, color=INK2, lw=1)
    a1.axvline(b - 0.5, color=INK2, lw=1)
a1.tick_params(length=0)
for s in a1.spines.values():
    s.set_visible(False)
cax = a1.inset_axes([0.62, -0.135, 0.36, 0.018])
cb = fig.colorbar(im, cax=cax, orientation='horizontal')
cb.set_ticks([1, 3, 10, 30], labels=['1', '3', '10', '30'])
cb.set_label('合著論文數（篇，對數色階）', fontsize=9)
a1.set_title('A　機構 × 機構：有兩機構名冊學者的論文數（名冊內網路）\n'
             '黑框對角線 = 同校；標籤顏色：紫 中研院、藍 國立、橘 私立；括號 = 名冊人數', pad=8)

y = np.arange(K)
left = np.zeros(K)
for c in CATS:
    v = share[c].values * 100
    a2.barh(y, v, left=left, color=CCOL[c], height=0.72, edgecolor='white', linewidth=0.5, label=c)
    for yi, l, vv in zip(y, left, v):
        if vv >= 7:
            a2.text(l + vv / 2, yi, f'{vv:.0f}', ha='center', va='center', fontsize=7.5,
                    color='white' if c in ('同校名冊', '國外') else INK)
    left += v
for yi, i in zip(y, ORDER):
    a2.text(101, yi, f'{comp.loc[i].sum()}', va='center', fontsize=8, color=INK2)
a2.text(101, -1.1, '關係數', fontsize=8, color=INK2)
a2.set_ylim(K - 0.5, -0.5)
a2.set_yticks(y, [])
a2.tick_params(axis='y', length=0)
a2.set_xlim(0, 100)
a2.set_xlabel('學者–合作者關係的組成（%）')
a2.spines['left'].set_visible(False)
a2.legend(loc='upper center', bbox_to_anchor=(0.5, -0.06), ncol=5, fontsize=9.2, handlelength=1.2)
a2.set_title('B　各機構學者的合作對象在哪裡（含外部作者的網路）\n同一位合作者和兩位同校學者合作，算兩次', pad=8)

fig.suptitle('機構之間怎麼合作？2015–2025 共著（機構為 2026 年快照）', x=0.06, y=0.985, ha='left', fontsize=15,
             fontweight='bold')
tot = comp.sum()
fig.text(0.06, 0.945, f'全體：同校名冊 {tot["同校名冊"] / tot.sum():.0%}、他校名冊 {tot["他校名冊"] / tot.sum():.0%}、'
         f'國內外部 {tot["國內外部"] / tot.sum():.0%}、國外 {tot["國外"] / tot.sum():.0%}、未知 {tot["未知"] / tot.sum():.0%}。'
         '外部作者的位置只用已記錄的機構國別，查不到列為未知；「國內外部」包含任職名冊 27 校、但不在名冊上的人。',
         fontsize=9.5, color=INK2)
save(fig, '04_institutions.png')

section('數字')
print('2 位以上名冊學者的論文', n_multi, '｜同校論文（對角線和）', int(np.trace(M)), '｜跨校格子和', int((M.sum() - np.trace(M)) / 2))
print('全體組成', (tot / tot.sum()).round(3).to_dict())
rp = t[t.cls == '名冊內']
print('名冊內關係中同校', round((rp.cat == '同校名冊').mean(), 3))
s2 = share.assign(n=n_sch.reindex(ORDER), rel=comp.sum(axis=1), within_of_roster=comp['同校名冊'] / (comp['同校名冊'] + comp['他校名冊']))
print(s2.round(3).to_string())
by_type = comp.groupby(itype.reindex(comp.index).values).sum()
print((by_type.div(by_type.sum(axis=1), axis=0)).round(3).to_string())
off = [(ORDER[i], ORDER[j], int(M[i, j])) for i in range(K) for j in range(i + 1, K)]
print('跨校最多', sorted(off, key=lambda x: -x[2])[:12])
print('同校最多', sorted([(ORDER[i], int(M[i, i])) for i in range(K)], key=lambda x: -x[1])[:10])
