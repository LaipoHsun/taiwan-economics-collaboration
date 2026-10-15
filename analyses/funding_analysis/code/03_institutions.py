"""03 機構：各機構 2015–2025 主持人經費總額與人均經費。

機構為 2026 年快照（institution_2026）：學者 2015–2025 年間的經費全部算在他 2026 年所在的機構。
人均 = 總額 / 該機構 2026 年名冊中有紀錄的人數（含沒經費的人）。
"""
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from _common import (INK, INK2, INST_TYPE_COLOR, INST_TYPE_ORDER, LIGHTGREY, MUTED, load, load_grants, person_table, plt,
                     save, section)

d = load()
g = load_grants(d)
r = person_table(d, g)
r['f_inst'] = r.funding - r.funding_research

t = r.groupby('inst_short_2026').agg(type=('inst_type_2026', 'first'), n=('funding', 'size'), total=('funding', 'sum'),
                                     research=('funding_research', 'sum'), inst=('f_inst', 'sum'),
                                     mean=('funding', 'mean'), median=('funding', 'median'),
                                     mean_r=('funding_research', 'mean'), zero=('funding', lambda s: (s == 0).mean()))
t = t.sort_values('total')
y = np.arange(len(t))

fig, (ax, bx, cx) = plt.subplots(1, 3, figsize=(16, 10), sharey=True,
                                 gridspec_kw=dict(width_ratios=[1.25, 1, 0.55], wspace=0.08))
cols = t.type.map(INST_TYPE_COLOR)
ax.barh(y, t.research / 1e6, color=cols, height=0.7, edgecolor='white', linewidth=0.6)
ax.barh(y, t.inst / 1e6, left=t.research / 1e6, color=cols, alpha=0.35, height=0.7, edgecolor='white', linewidth=0.6,
        hatch='////')
for yi, tot, share in zip(y, t.total, t.total / t.total.sum()):
    ax.text(tot / 1e6 + 6, yi, f'{tot / 1e6:,.0f}（{share:.0%}）', va='center', fontsize=8.5, color=INK2)
ax.set_xlabel('經費總額（百萬元）')
ax.set_xlim(0, t.total.max() / 1e6 * 1.22)
ax.set_yticks(y, [f'{i}（{n} 人）' for i, n in zip(t.index, t.n)], fontsize=9.5)
ax.tick_params(axis='y', length=0)
ax.xaxis.grid(True)
ax.set_axisbelow(True)
ax.set_title('經費總額', pad=8)

# 中：人均（平均）與中位數
for yi, m, md, mr, c in zip(y, t['mean'], t['median'], t.mean_r, cols):
    bx.plot([md / 1e4, m / 1e4], [yi, yi], color=LIGHTGREY, lw=2, zorder=1)
    bx.scatter(m / 1e4, yi, s=55, color=c, zorder=3, edgecolor='white', linewidth=1)
    bx.scatter(md / 1e4, yi, s=48, facecolor='white', edgecolor=c, linewidth=1.6, zorder=3)
bx.set_xlim(-30, 1350)
bx.set_xticks([0, 250, 500, 750, 1000, 1250], ['0', '250', '500', '750', '1,000', '1,250'])
bx.set_xlabel('每人 2015–2025 經費（萬元，含沒經費的人）')
bx.xaxis.grid(True)
bx.set_axisbelow(True)
bx.set_title('人均經費：● 平均　○ 中位數', pad=8)
bx.spines['left'].set_visible(False)
bx.tick_params(axis='y', length=0)

# 右：沒有經費的比例
cx.barh(y, t.zero, color=cols, height=0.6, alpha=0.85)
for yi, z in zip(y, t.zero):
    cx.text(z + 0.02, yi, f'{z:.0%}', va='center', fontsize=8.5, color=INK2)
cx.set_xlim(0, 1.0)
cx.set_xticks([.25, .5, .75, 1], ['25%', '50%', '75%', '100%'])
cx.set_xlabel('沒有主持人經費的比例')
cx.xaxis.grid(True)
cx.set_axisbelow(True)
cx.set_title('沒拿到的比例', pad=8)
cx.spines['left'].set_visible(False)
cx.tick_params(axis='y', length=0)

handles = [Patch(color=INST_TYPE_COLOR[k], label=k) for k in INST_TYPE_ORDER]
handles += [Patch(facecolor=MUTED, label='個人研究計畫'),
            Patch(facecolor=MUTED, alpha=0.35, hatch='////', label='推動規劃、人才培育、延攬、交流')]
fig.legend(handles=handles, loc='lower center', ncol=5, bbox_to_anchor=(0.5, 0.0), fontsize=9.5)
grp = r.groupby('inst_type_2026').funding.agg(['size', 'sum', 'mean', 'median'])
fig.suptitle('經費集中在中研院經濟所與臺大；私立學校人均不到國立的一半', x=0.07, y=0.995, ha='left', fontsize=15,
             fontweight='bold')
sub = '；'.join(f'{k} {grp.at[k, "size"]} 人、總額 {grp.at[k, "sum"] / 1e8:.1f} 億、每人中位數 {grp.at[k, "median"] / 1e4:,.0f} 萬'
               for k in INST_TYPE_ORDER)
fig.text(0.07, 0.957, f'2015–2025 主持人經費，依學者 2026 年所屬機構歸類。{sub}。', fontsize=9.5, color=INK2)
fig.subplots_adjust(top=0.91, bottom=0.08)
save(fig, '03_institutions.png')

section('數字')
print(grp.assign(share=grp['sum'] / grp['sum'].sum()).round(3))
print(r.groupby('inst_type_2026').funding_research.agg(['mean', 'median']).round(-3))
print(r.groupby('inst_type_2026').funding.apply(lambda s: (s == 0).mean()).round(3))
tt = t.iloc[::-1]
print((tt.assign(total=tt.total / 1e6, mean=tt['mean'] / 1e4, median=tt['median'] / 1e4, share=tt.total / tt.total.sum())
       [['type', 'n', 'total', 'share', 'mean', 'median', 'zero']]).round(2).to_string())
