"""01 誰合作最多：2015–2025 合作者人數前 25 名（左）與合著論文數前 25 名（右）。

含外部作者的網路（external=True）。合作者依已記錄的位置分類；查不到 → 未知。機構、職級為 2026 年快照。
"""
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from _common import (AQUA, BIG_TEAM, FINE_COLOR, FINE_ORDER, GREY, INK, INK2, LIGHTGREY, eligible_papers, label_name,
                     load_all, person_collab, plt, save, section)

N = 25
d = load_all()
r = person_collab(d)

# 每人的合著論文中，有另一位名冊學者的篇數
p = eligible_papers(d)[['paper_id', 'n_authors', 'n_roster_authors']]
pa = d.paper_authors[['paper_id', 'node_id']].drop_duplicates().merge(p, on='paper_id')
r['coauth_roster'] = pa[(pa.n_authors >= 2) & (pa.n_roster_authors >= 2)].groupby('node_id').size().reindex(r.index, fill_value=0)
r['coauth_ext_only'] = r.coauth - r.coauth_roster

fig, (a1, a2) = plt.subplots(1, 2, figsize=(16, 10.5), gridspec_kw=dict(wspace=0.6))

# ---- 左：合作者人數 ----
t = r.sort_values(['n_collab', 'coauth'], ascending=False).head(N).iloc[::-1]
y = np.arange(len(t))
left = np.zeros(len(t))
cols = {'名冊內': 'n_名冊內', '名冊27校外部作者': 'n_名冊27校外部作者', '國內其他機構': 'n_國內其他機構', '國外': 'n_國外', '未知': 'n_未知'}
for c in FINE_ORDER:
    v = t[cols[c]].values
    a1.barh(y, v, left=left, color=FINE_COLOR[c], height=0.72, edgecolor='white', linewidth=0.6)
    left += v
a1.scatter(t.n_collab_small, y, marker='|', s=160, color=INK, lw=1.8, zorder=5)
for yi, v in zip(y, t.n_collab):
    a1.text(v + 3, yi, f'{v}', va='center', fontsize=8.5, color=INK2)
a1.set_yticks(y, [label_name(x) for x in t.itertuples()], fontsize=9.5)
a1.set_xlim(0, t.n_collab.max() * 1.1)
a1.set_xlabel('2015–2025 合作者人數（人，含外部作者）')
a1.set_title('合作者人數前 25 名\n（顏色：合作者的位置；黑色短線：排除 6 人以上論文後）', pad=10)

# ---- 右：合著論文數 ----
t2 = r.sort_values(['coauth', 'n_collab'], ascending=False).head(N).iloc[::-1]
a2.barh(y, t2.coauth_roster, color=FINE_COLOR['名冊內'], height=0.72, edgecolor='white', linewidth=0.6)
a2.barh(y, t2.coauth_ext_only, left=t2.coauth_roster, color=GREY, height=0.72, edgecolor='white', linewidth=0.6)
a2.barh(y, t2.solo, left=t2.coauth, color='white', height=0.72, edgecolor=LIGHTGREY, hatch='////', linewidth=0.6)
for yi, v, s in zip(y, t2.coauth, t2.solo):
    a2.text(v + s + 1.5, yi, f'{v}' + (f'（+{s} 獨著）' if s else ''), va='center', fontsize=8.5, color=INK2)
a2.set_yticks(y, [label_name(x) for x in t2.itertuples()], fontsize=9.5)
a2.set_xlim(0, (t2.coauth + t2.solo).max() * 1.22)
a2.set_xlabel('2015–2025 合著論文數（篇，2 位以上作者的可建邊著作）')
a2.set_title('合著論文數前 25 名\n（顏色：論文中是否有另一位名冊學者）', pad=10)

for ax in (a1, a2):
    ax.set_ylim(-0.6, len(t) - 0.4)
    ax.tick_params(axis='y', length=0)
    ax.xaxis.grid(True)
    ax.set_axisbelow(True)
    ax.spines['left'].set_visible(False)

h1 = [Patch(color=FINE_COLOR[c], label=f'合作者：{c}') for c in FINE_ORDER]
h1.append(Line2D([], [], marker='|', ls='', color=INK, ms=11, mew=1.8, label=f'排除 {BIG_TEAM} 人以上論文的合作者數'))
h2 = [Patch(color=AQUA, label='論文：有其他名冊學者'), Patch(color=GREY, label='論文：只有名冊外合作者'),
      Patch(facecolor='white', edgecolor=LIGHTGREY, hatch='////', label='單一作者論文（參考）')]
fig.legend(handles=h1 + h2, loc='lower center', ncol=5, bbox_to_anchor=(0.5, -0.01), fontsize=9.2, handlelength=1.3,
           columnspacing=1.3)
fig.suptitle('誰合作最多？2015–2025 合作者人數與合著論文數前 25 名（含外部作者的網路）', x=0.08, y=0.995, ha='left',
             fontsize=15, fontweight='bold')
fig.text(0.08, 0.955, '合作者「位置」只用資料中已記錄的機構國別，查不到的列為未知（不推論）。外部作者以姓名辨識，'
         '同一人可能被拆成多個節點、也可能不同人被合成一個。機構、職級為 2026 年快照。', fontsize=9.5, color=INK2)
fig.subplots_adjust(bottom=0.1, top=0.9)
save(fig, '01_top_collaborators.png')

section('數字')
print('有合作者的人', (r.n_collab > 0).sum(), '／', len(r), '｜合作者人數中位數', r.n_collab.median(), '平均', round(r.n_collab.mean(), 1))
print('前 25 名佔全部 ego-alter 關係', round(t.n_collab.sum() / r.n_collab.sum(), 3))
print('左：機構', t.inst_short_2026.value_counts().to_dict())
print('左：職級', t.rank_2026.value_counts().to_dict(), t.gender.value_counts().to_dict())
print('右：機構', t2.inst_short_2026.value_counts().to_dict())
print('兩份名單重疊', len(set(t.index) & set(t2.index)))
show = ['name_zh', 'inst_short_2026', 'rank_2026', 'n_collab', 'n_collab_small', 'n_名冊內', 'n_名冊27校外部作者',
        'n_國內其他機構', 'n_國外', 'n_未知', 'coauth', 'coauth_roster', 'solo', 'journal']
print(t.iloc[::-1][show].head(12).to_string())
print(t2.iloc[::-1][show].head(12).to_string())
tot = r[['n_名冊內', 'n_名冊27校外部作者', 'n_國內其他機構', 'n_國外', 'n_未知']].sum()
print('全部 ego-alter 組成', (tot / tot.sum()).round(3).to_dict())
tt = t[['n_名冊內', 'n_名冊27校外部作者', 'n_國內其他機構', 'n_國外', 'n_未知']].sum()
print('前 25 名組成', (tt / tt.sum()).round(3).to_dict())
print('前 25 名排除大團隊後的變化（中位數比例）', round((t.n_collab_small / t.n_collab).median(), 3))
