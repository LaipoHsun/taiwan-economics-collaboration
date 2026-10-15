"""02 集中程度：Lorenz 曲線與 Gini 係數。

母體：421 位有紀錄的名冊學者（沒有經費的算 0）；另列加入 99 位 2015–2026 無紀錄教師（520 人）的 Gini。
兩種經費定義：全部類別、只算個人研究計畫（見 01）。
"""
import numpy as np

from _common import BLUE, GREY, INK, INK2, LIGHTGREY, MUTED, ORANGE, gini, load, load_grants, person_table, plt, save, section

d = load()
g = load_grants(d)
r = person_table(d, g)
N_INACTIVE = len(d.roster_inactive)


def lorenz(x):
    x = np.sort(np.asarray(x, float))
    return np.r_[0, np.arange(1, len(x) + 1) / len(x)], np.r_[0, np.cumsum(x) / x.sum()]


def top_share(x, q):
    x = np.sort(np.asarray(x, float))[::-1]
    k = max(1, int(round(len(x) * q)))
    return x[:k].sum() / x.sum()


defs = [('funding', '全部類別', BLUE), ('funding_research', '只算個人研究計畫', ORANGE)]
stats = {}
for col, lab, _ in defs:
    x = r[col].values
    stats[col] = dict(gini=gini(x), gini520=gini(np.r_[x, np.zeros(N_INACTIVE)]), zero=int((x == 0).sum()),
                      top1=top_share(x, .01), top5=top_share(x, .05), top10=top_share(x, .10),
                      bottom50=1 - top_share(x, .50), median=np.median(x), mean=x.mean())
x_ex = r.funding.copy()
x_ex[r.funding.idxmax()] -= 134.9e6  # 扣掉人社中心設置運作計畫
stats['ex_center'] = dict(gini=gini(x_ex), top1=top_share(x_ex, .01), top10=top_share(x_ex, .10))

fig, (ax, bx) = plt.subplots(1, 2, figsize=(14.5, 6.6), gridspec_kw=dict(width_ratios=[1.05, 1], wspace=0.28))
ax.plot([0, 1], [0, 1], color=LIGHTGREY, lw=1.2, ls='--')
ax.text(0.40, 0.44, '完全平均', rotation=38, color=MUTED, fontsize=9)
for col, lab, c in defs:
    px, py = lorenz(r[col])
    ax.plot(px, py, color=c, lw=2.2, label=f'{lab}（Gini {stats[col]["gini"]:.2f}）')
# 沒有經費的人：曲線貼在 0 的區段
z = stats['funding']['zero'] / len(r)
ax.axvspan(0, z, color=LIGHTGREY, alpha=0.35, lw=0)
ax.text(z / 2, 0.42, f'{stats["funding"]["zero"]} 人\n（{z:.0%}）\n2015–2025\n沒有任何\n主持人經費', ha='center', va='center',
        fontsize=9, color=INK2)
# 前 10%、5%、1% 的位置（全部類別）
px, py = lorenz(r.funding)
for q, dy in ((.10, -0.12), (.05, -0.07), (.01, -0.02)):
    xq = 1 - q
    yq = np.interp(xq, px, py)
    ax.plot([xq, xq], [yq, 1], color=BLUE, lw=1, alpha=0.5)
    ax.scatter([xq], [yq], s=26, color=BLUE, zorder=3, edgecolor='white', linewidth=1)
    ax.annotate(f'前 {q:.0%} 拿 {1 - yq:.0%}', xy=(xq, yq), xytext=(xq - 0.33, yq + dy + 0.08), fontsize=9.5, color=INK,
                arrowprops=dict(arrowstyle='-', color=MUTED, lw=0.7))
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.set_xticks(np.linspace(0, 1, 6), [f'{v:.0%}' for v in np.linspace(0, 1, 6)])
ax.set_yticks(np.linspace(0, 1, 6), [f'{v:.0%}' for v in np.linspace(0, 1, 6)])
ax.set_xlabel('學者累積比例（由經費少到多排序，421 人）')
ax.set_ylabel('累積經費比例')
ax.legend(loc='upper left', fontsize=9.5)
ax.set_title('Lorenz 曲線', pad=8)
ax.grid(True)
ax.set_axisbelow(True)

# 右：各分位群組的佔比
groups = [('top1', '前 1%\n（4 人）'), ('top5', '前 5%\n（21 人）'), ('top10', '前 10%\n（42 人）'), ('bottom50', '後 50%\n（211 人）')]
yy = np.arange(len(groups))[::-1]
h = 0.36
for k, (col, lab, c) in enumerate(defs):
    vals = [stats[col][g_] for g_, _ in groups]
    bars = bx.barh(yy + (h / 2 if k == 0 else -h / 2), vals, height=h - 0.04, color=c, label=lab)
    for yv, v in zip(yy + (h / 2 if k == 0 else -h / 2), vals):
        bx.text(v + 0.008, yv, f'{v:.1%}', va='center', fontsize=9.5, color=INK)
bx.set_yticks(yy, [lab for _, lab in groups], fontsize=10)
bx.tick_params(axis='y', length=0)
bx.set_xlim(0, 0.6)
bx.set_xticks(np.arange(0, 0.61, 0.1), [f'{v:.0%}' for v in np.arange(0, 0.61, 0.1)])
bx.set_xlabel('佔 2015–2025 主持人經費總額的比例')
bx.xaxis.grid(True)
bx.set_axisbelow(True)
bx.spines['left'].set_visible(False)
bx.legend(loc='lower right', fontsize=9.5)
bx.set_title('各群組拿走多少', pad=8)
s, sr = stats['funding'], stats['funding_research']
bx.text(0.0, -0.95, f'Gini：全部 {s["gini"]:.2f}；個人研究 {sr["gini"]:.2f}；扣掉人社中心一筆 {stats["ex_center"]["gini"]:.2f}；'
        f'\n加入 {N_INACTIVE} 位無紀錄教師（520 人）全部 {s["gini520"]:.2f}。對照：Hsieh 等論文中 NSF 經濟學經費 0.59。',
        fontsize=8.8, color=INK2, transform=bx.get_yaxis_transform(), va='top')

fig.suptitle('經費有多集中？前 10% 的學者拿走將近一半', x=0.07, y=1.0, ha='left', fontsize=15, fontweight='bold')
fig.text(0.07, 0.945, f'2015–2025 主持人經費（起始年歸屬）。421 位有紀錄學者中，{s["zero"]} 人沒有任何主持人經費；'
         f'每人中位數 {s["median"] / 1e4:,.0f} 萬元、平均 {s["mean"] / 1e4:,.0f} 萬元。', fontsize=9.5, color=INK2)
fig.subplots_adjust(top=0.86, bottom=0.17)
save(fig, '02_concentration.png')

section('數字')
for k, v in stats.items():
    print(k, {a: (round(b, 3) if isinstance(b, float) else b) for a, b in v.items()})
pos = r.funding[r.funding > 0]
print('只看有經費的', len(pos), '人：Gini', round(gini(pos), 3), '｜研究計畫 >0：', round(gini(r.funding_research[r.funding_research > 0]), 3))
