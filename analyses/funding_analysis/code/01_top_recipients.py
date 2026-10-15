"""01 誰拿最多：2015–2025 主持人經費前 25 名（左：全部類別；右：只算個人研究計畫）。

經費依計畫起始年歸屬（全期總額），只算主持人。機構、職級為 2026 年快照。
"""
import numpy as np
from matplotlib.patches import Patch

from _common import (CAT_COLOR, CAT_ORDER, INK, INK2, MUTED, RESEARCH_CATS, load, load_grants, person_table, plt, save,
                     section)

N = 25
CLIP = 75e6  # 左圖截斷位置（元）；超過的長條畫斷口並標出實際金額

d = load()
g = load_grants(d)
r = person_table(d, g)


def panel(ax, col, cats, title, clip=None):
    t = r.sort_values(col, ascending=False).head(N).iloc[::-1]
    y = np.arange(len(t))
    left = np.zeros(len(t))
    for c in cats:
        v = t[f'f_{c}'].values.astype(float)
        draw = v.copy()
        if clip is not None:
            draw = np.clip(left + v, None, clip) - np.clip(left, None, clip)
        ax.barh(y, draw / 1e4, left=(left if clip is None else np.clip(left, None, clip)) / 1e4, color=CAT_COLOR[c], height=0.72,
                edgecolor='white', linewidth=0.8)
        left += v
    total = t[col].values
    xmax = (clip if clip else total.max()) / 1e4
    for yi, v in zip(y, total):
        if clip is not None and v > clip:
            ax.plot([xmax * 0.965, xmax * 0.985], [yi - 0.42, yi + 0.42], color='white', lw=3.5)
            ax.text(xmax * 1.01, yi, f'{v / 1e4:,.0f}', va='center', fontsize=8.5, color=INK, fontweight='bold')
        else:
            ax.text(v / 1e4 + xmax * 0.01, yi, f'{v / 1e4:,.0f}', va='center', fontsize=8.5, color=INK2)
    labels = [f'{n}　{i}・{k}' for n, i, k in zip(t.name_zh, t.inst_short_2026, t.rank_2026)]
    ax.set_yticks(y, labels, fontsize=9.5)
    ax.tick_params(axis='y', length=0)
    ax.set_xlim(0, xmax * 1.13)
    ax.set_ylim(-0.6, len(t) - 0.4)
    ax.xaxis.grid(True)
    ax.set_axisbelow(True)
    ax.spines['left'].set_visible(False)
    ax.set_xlabel('2015–2025 主持人經費（萬元，計畫起始年歸屬）')
    ax.set_title(title, pad=10)
    return t


fig, (a1, a2) = plt.subplots(1, 2, figsize=(16, 10.5), gridspec_kw=dict(wspace=0.62))
t1 = panel(a1, 'funding', CAT_ORDER, '全部計畫類別\n（含推動規劃、人才培育等機構性經費）', clip=CLIP)
top = r.loc[r.funding.idxmax()]
a1.annotate('王泓仁：含「人文社會科學研究中心\n設置及運作計畫」一筆 13,490 萬元\n（2015，推動規劃；長條截斷）', xy=(CLIP / 1e4 * 0.97, N - 1),
            xytext=(CLIP / 1e4 * 0.55, N - 10.5), fontsize=8.5, color=INK2)
t2 = panel(a2, 'funding_research', RESEARCH_CATS, '只算個人研究計畫\n（一般、新進、年輕學者獎勵、特約與其他專題）')

handles = [Patch(color=CAT_COLOR[c], label=c) for c in CAT_ORDER]
fig.legend(handles=handles, loc='lower center', ncol=8, bbox_to_anchor=(0.5, 0.0), fontsize=9.5, handlelength=1.2,
           columnspacing=1.4)
fig.suptitle('誰拿最多國科會經費？2015–2025 主持人經費前 25 名', x=0.08, y=0.995, ha='left', fontsize=15,
             fontweight='bold')
fig.text(0.08, 0.955, '左圖前幾名多由推動規劃（研究中心、大型調查、議題導向計畫）與人才培育（博士生獎學金）撐起；'
         '只看個人研究計畫，名單換成以中研院經濟所、臺大為主的研究型學者。機構、職級為 2026 年快照。',
         fontsize=9.5, color=INK2)
fig.subplots_adjust(bottom=0.08, top=0.9)
save(fig, '01_top_recipients.png')

section('數字')
tot = r.funding.sum()
print('總額（億）', round(tot / 1e8, 2), '｜個人研究計畫總額', round(r.funding_research.sum() / 1e8, 2))
print('前 25 名（全部）佔', round(t1.funding.sum() / tot, 3), '｜前 25 名（研究）佔研究總額', round(t2.funding_research.sum() / r.funding_research.sum(), 3))
print('兩份名單重疊', len(set(t1.index) & set(t2.index)))
for nm, t, col in (('全部', t1, 'funding'), ('研究', t2, 'funding_research')):
    tt = t.iloc[::-1]
    print(nm, tt.inst_short_2026.value_counts().to_dict())
    print(nm, tt.rank_2026.value_counts().to_dict(), tt.gender.value_counts().to_dict())
    print(tt[['name_zh', 'inst_short_2026', 'rank_2026', col, 'n_pi']].assign(**{col: lambda x: (x[col] / 1e4).round()}).head(10).to_string())
