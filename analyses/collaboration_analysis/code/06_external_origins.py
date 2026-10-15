"""06 合作對象：外部（非名冊）合作者來自哪裡。

2015–2025 和名冊學者合寫過可建邊著作的外部作者。位置只用 d.places 已記錄的資料（最後已知機構）；
查不到 → 未知，不推論。A：各類別／國家的人數與論文數；B：台灣其他機構前 12；C：國外機構前 15。
B、C 標出「這個機構的合作者有一半以上來自同一位名冊學者」的情形。
"""
import numpy as np
import pandas as pd

from _common import (COUNTRY_ZH, FINE_COLOR, INK, INK2, MUTED, eligible_papers, ego_ties, load_all, plt, roster,
                     save, section)

d = load_all()
r = roster(d).set_index('node_id')
t = ego_ties(d)
ext = t[t.cls != '名冊內']
pl = d.places.set_index('node_id')

people = ext.groupby('alter').agg(cls=('cls', 'first')).join(pl[['country', 'label', 'place_type']])
people['group'] = people.cls
people.loc[people.cls == '國外', 'group'] = people.country.map(lambda c: COUNTRY_ZH.get(c, c))
N_EXT = len(people)

# 論文數：有這一類外部作者、且有名冊學者的論文
p = eligible_papers(d)
pa = d.paper_authors[['paper_id', 'node_id']].drop_duplicates()
pa = pa[pa.paper_id.isin(p.paper_id)]
roster_papers = set(pa.paper_id[pa.node_id.isin(r.index)])
pe = pa[pa.node_id.isin(people.index) & pa.paper_id.isin(roster_papers)].join(people.group, on='node_id')
n_pap = pe.groupby('group').paper_id.nunique()

TOPC = 12
fc = people[people.cls == '國外'].group.value_counts()
top_c = list(fc.index[:TOPC])
rows = ['名冊27校外部作者', '國內其他機構'] + top_c + ['其他國外', '未知']
people['row'] = people.group.where(people.group.isin(rows), '其他國外')
pe['row'] = pe.node_id.map(people.row)
cnt = people.row.value_counts().reindex(rows, fill_value=0)
pap = pe.groupby('row').paper_id.nunique().reindex(rows, fill_value=0)
col = {g: FINE_COLOR['國外'] for g in rows}
col.update({'名冊27校外部作者': FINE_COLOR['名冊27校外部作者'], '國內其他機構': FINE_COLOR['國內其他機構'], '未知': FINE_COLOR['未知']})

fig = plt.figure(figsize=(18, 10.5))
gs = fig.add_gridspec(2, 2, width_ratios=[1.05, 1], height_ratios=[1, 1.25], wspace=0.55, hspace=0.38)
a1 = fig.add_subplot(gs[:, 0])
a2 = fig.add_subplot(gs[0, 1])
a3 = fig.add_subplot(gs[1, 1])

y = np.arange(len(rows))
h = 0.38
a1.barh(y - h / 2, cnt.values, height=h, color=[col[g] for g in rows], edgecolor='white')
a1.barh(y + h / 2, pap.values, height=h, color='white', edgecolor=[col[g] if g != '未知' else MUTED for g in rows], hatch='///',
        lw=0.8)
for yi, a, b in zip(y, cnt.values, pap.values):
    a1.text(a + 12, yi - h / 2, f'{a:,} 人（{a / N_EXT:.0%}）' if a / N_EXT >= 0.01 else f'{a:,} 人（<1%）', va='center', fontsize=8.6, color=INK)
    a1.text(b + 12, yi + h / 2, f'{b:,} 篇', va='center', fontsize=8.3, color=INK2)
lab = {'名冊27校外部作者': '名冊 27 校（非名冊者）', '國內其他機構': '台灣其他機構', '其他國外': f'其他國外（{people[people.row == "其他國外"].country.nunique()} 國）',
       '未知': '未知（查不到位置）'}
a1.set_yticks(y, [lab.get(g, g) for g in rows], fontsize=10)
a1.set_ylim(len(rows) - 0.4, -0.6)
a1.set_xlim(0, max(cnt.max(), pap.max()) * 1.28)
a1.xaxis.grid(True)
a1.set_axisbelow(True)
a1.tick_params(axis='y', length=0)
a1.spines['left'].set_visible(False)
a1.axhline(1.5, color=MUTED, lw=0.7)
a1.axhline(len(rows) - 1.5, color=MUTED, lw=0.7)
a1.set_xlabel('外部合作者人數（實心）／涉及的論文數（斜線）')
a1.set_title(f'A　{N_EXT:,} 位外部合作者的位置（含外部作者的網路）', pad=8)


def inst_panel(ax, sub, n, title, color_by_country):
    vc = sub.label.value_counts().head(n)
    yy = np.arange(len(vc))
    cc = [FINE_COLOR['國外'] if color_by_country else FINE_COLOR['國內其他機構']] * len(vc)
    ax.barh(yy, vc.values, color=cc, height=0.7)
    labels = []
    for yi, (inst, v) in zip(yy, vc.items()):
        ids = sub.index[sub.label == inst]
        egos = ext[ext.alter.isin(ids)].groupby('ego').alter.nunique().sort_values(ascending=False)
        top_ego, top_n = egos.index[0], egos.iloc[0]
        note = f'{r.loc[top_ego, "name_zh"]} {top_n} 人' if top_n / v >= 0.5 else f'{len(egos)} 位名冊學者'
        ax.text(v + 0.5, yi, f'{v}　（{note}）', va='center', fontsize=8.3, color=INK2)
        cn = COUNTRY_ZH.get(sub.loc[ids[0], 'country'], sub.loc[ids[0], 'country'])
        labels.append(f'{inst}' + (f'（{cn}）' if color_by_country else ''))
    ax.set_yticks(yy, labels, fontsize=8.8)
    ax.set_ylim(len(vc) - 0.4, -0.6)
    ax.set_xlim(0, vc.max() * 1.6)
    ax.tick_params(axis='y', length=0)
    ax.spines['left'].set_visible(False)
    ax.xaxis.grid(True)
    ax.set_axisbelow(True)
    ax.set_xlabel('外部合作者人數（人）')
    ax.set_title(title, pad=6, fontsize=12)
    return vc


v2 = inst_panel(a2, people[people.cls == '國內其他機構'], 12,
                'B　台灣其他機構（名冊 27 校以外）前 12 名\n括號：一半以上來自同一位名冊學者時標出姓名，否則標名冊學者人數', False)
v3 = inst_panel(a3, people[people.cls == '國外'], 15, 'C　國外機構前 15 名', True)

fig.suptitle('外部合作者來自哪裡？2015–2025（含外部作者的網路）', x=0.06, y=0.995, ha='left', fontsize=15,
             fontweight='bold')
fig.text(0.06, 0.955, '位置 = 外部作者的最後已知機構（d.places），不一定是合作當時的機構；查不到的列為未知，不推論。'
         '外部作者以姓名辨識，同一人可能被拆成多個節點。「名冊 27 校（非名冊者）」可能是系外同事、研究生、博士後，資料無法區分。',
         fontsize=9.5, color=INK2)
save(fig, '06_external_origins.png')

section('數字')
print('外部合作者', N_EXT)
print(pd.DataFrame({'人': cnt, '比例': (cnt / N_EXT).round(3), '篇': pap}).to_string())
print('國外總人數', (people.cls == '國外').sum(), '國家數', people[people.cls == '國外'].country.nunique())
print('國外前 5 國', fc.head(8).to_dict())
print('國內其他前 12', v2.to_dict())
print('國外前 15', v3.to_dict())
# 每位外部作者合作的名冊學者數、篇數，依類別
deg = ext.groupby('alter').agg(n_ego=('ego', 'nunique'), n_pap=('count', 'max')).join(people.cls)
print(deg.groupby('cls').agg(n=('n_ego', 'size'), 多位名冊=('n_ego', lambda s: (s >= 2).mean()), 平均篇=('n_pap', 'mean')).round(3))
# 國外合作者集中在哪些名冊學者
fe = ext[ext.cls == '國外'].groupby('ego').size().sort_values(ascending=False)
print('國外合作者 前 10 名學者', [(r.loc[i, 'name_zh'], v) for i, v in fe.head(10).items()], '前 10 佔', round(fe.head(10).sum() / fe.sum(), 3),
      '有國外合作者的學者', len(fe))
cn = ext[ext.cls == '國外'].join(people.country, on='alter')
cn_c = cn[cn.country == 'CN'].groupby('ego').size().sort_values(ascending=False)
print('中國合作者', cn_c.sum(), [(r.loc[i, 'name_zh'], v) for i, v in cn_c.head(5).items()])
us = cn[cn.country == 'US'].groupby('ego').size().sort_values(ascending=False)
print('美國合作者', us.sum(), [(r.loc[i, 'name_zh'], v) for i, v in us.head(5).items()], '學者數', len(us))
