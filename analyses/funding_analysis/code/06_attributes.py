"""06 屬性：個人研究計畫經費依職級（2026）、性別、博士來源、研究領域（JEL 主領域）的分布。

經費：2015–2025 主持人的個人研究計畫（一般、新進、年輕學者獎勵、特約與其他專題），起始年歸屬。
排除推動規劃、人才培育等機構性經費，避免少數大計畫主導分組比較（全部類別的數字印在下方，寫進 note）。
點：有經費的人（對數軸），顏色為 2026 年機構類型；箱形為有經費者的四分位。沒有經費的人數另外標示。
"""
import numpy as np
from matplotlib.lines import Line2D

from _common import (GENDER_LABEL, INK, INK2, INST_TYPE_COLOR, INST_TYPE_ORDER, LIGHTGREY, MUTED, PHD_ORDER, RANK_ORDER,
                     load, load_grants, person_table, plt, repel, save, section)

COL = 'funding_research'
rng = np.random.default_rng(20261012)

d = load()
g = load_grants(d)
r = person_table(d, g)
r['gender_lab'] = r.gender.map(GENDER_LABEL)
r['v'] = r[COL] / 1e4  # 萬元

fields = r.field.value_counts()
FIELD_ORDER = [f for f in fields.index if fields[f] >= 10]
r['field_g'] = r.field.where(r.field.isin(FIELD_ORDER), '其他（<10人）')
FIELD_ORDER = list(r[r.field_g != '其他（<10人）'].groupby('field_g').v.median().sort_values(ascending=False).index) + ['其他（<10人）']

YMIN, YMAX = 20, 6000


def panel(ax, col, order, title, n_label=2, label_low=False):
    texts, ticks = [], []
    for i, k in enumerate(order):
        s = r[r[col] == k]
        pos = s[s.v > 0]
        x = i + rng.uniform(-0.28, 0.28, len(pos))
        ax.scatter(x, pos.v, s=16, c=pos.inst_type_2026.map(INST_TYPE_COLOR), alpha=0.75, edgecolor='white',
                   linewidth=0.4, zorder=2)
        if len(pos) >= 5:
            q1, md, q3 = pos.v.quantile([.25, .5, .75])
            ax.add_patch(plt.Rectangle((i - 0.36, q1), 0.72, q3 - q1, fill=False, edgecolor=INK, lw=1.1, zorder=3))
            ax.plot([i - 0.36, i + 0.36], [md, md], color=INK, lw=2, zorder=3)
        ticks.append(f'{k}\nn={len(s)}\n0 經費 {(s.v == 0).mean():.0%}\n中位數 {s.v.median():,.0f}')
        top = pos.nlargest(n_label, 'v')
        for xi, (nid, row) in zip(x[np.argsort(-pos.v.values)][:n_label], top.iterrows()):
            texts.append(ax.text(xi + 0.05, row.v, row.name_zh, fontsize=8.5, color=INK, va='center'))
    ax.set_yscale('log')
    ax.set_ylim(YMIN, YMAX)
    ax.set_yticks([30, 100, 300, 1000, 3000], ['30', '100', '300', '1,000', '3,000'])
    ax.minorticks_off()
    ax.set_xticks(range(len(order)), ticks, fontsize=8.5)
    ax.set_xlim(-0.6, len(order) - 0.4)
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)
    ax.set_title(title, pad=6)
    ax.tick_params(axis='x', length=0, pad=4)
    repel(ax, texts)
    return texts


fig = plt.figure(figsize=(16, 12))
gs = fig.add_gridspec(2, 3, height_ratios=[1, 1], hspace=0.42, wspace=0.18)
a1 = fig.add_subplot(gs[0, 0])
a2 = fig.add_subplot(gs[0, 1], sharey=a1)
a3 = fig.add_subplot(gs[0, 2], sharey=a1)
a4 = fig.add_subplot(gs[1, :])
panel(a1, 'rank_group_2026', RANK_ORDER, '職級（2026 年）')
panel(a2, 'gender_lab', ['男', '女'], '性別')
panel(a3, 'phd_origin', PHD_ORDER, '博士來源')
panel(a4, 'field_g', FIELD_ORDER, '研究領域（JEL 主領域，依中位數（含 0）排序）', n_label=1)
a1.set_ylabel('個人研究計畫經費（萬元，對數軸）')
a4.set_ylabel('個人研究計畫經費（萬元，對數軸）')
for a in (a2, a3):
    plt.setp(a.get_yticklabels(), visible=False)

handles = [Line2D([], [], marker='o', ls='', color=INST_TYPE_COLOR[k], label=f'{k}（2026）', ms=6) for k in INST_TYPE_ORDER]
handles += [Line2D([], [], color=INK, lw=2, label='有經費者的中位數與四分位')]
fig.legend(handles=handles, loc='upper right', ncol=4, bbox_to_anchor=(0.91, 0.955), fontsize=9.5)
fig.suptitle('職級與機構差距最大；女性拿到計畫的比例和男性一樣，但金額較低', x=0.07, y=0.995, ha='left', fontsize=15,
             fontweight='bold')
fig.text(0.07, 0.962, '2015–2025 主持人的個人研究計畫經費（不含推動規劃、人才培育等機構性經費）。每點一人，只畫有經費者；'
         '圖下為各組人數、沒經費比例、含 0 的中位數（萬元）。\n姓名標每組經費最高者。', fontsize=9.5, color=INK2, va='top')
fig.subplots_adjust(top=0.9, bottom=0.1)
save(fig, '06_attributes.png')

section('數字（萬元）')
for col in ('rank_group_2026', 'gender', 'phd_origin', 'inst_type_2026', 'field_g'):
    t = r.groupby(col).agg(n=('v', 'size'), zero=('v', lambda s: (s == 0).mean()), med=('v', 'median'),
                           med_pos=('v', lambda s: s[s > 0].median()), mean=('v', 'mean'),
                           med_all=('funding', lambda s: s.median() / 1e4), mean_all=('funding', lambda s: s.mean() / 1e4))
    print(t.round(2).to_string(), '\n')
# 性別差在職級內是否還在
print(r.groupby(['rank_group_2026', 'gender']).v.agg(['size', 'median', lambda s: (s == 0).mean()]).round(2))
print(r.groupby(['inst_type_2026', 'gender']).v.agg(['size', 'median', lambda s: (s == 0).mean()]).round(2))
print(r.groupby(['inst_type_2026', 'phd_origin']).v.agg(['size', 'median', lambda s: (s == 0).mean()]).round(2))
print(r.groupby(['inst_type_2026', 'rank_group_2026']).size().unstack())
