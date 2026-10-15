"""02 合作集中在少數人嗎：合作者人數、名冊內合作者數、合著論文數的 Lorenz 曲線與次數分布。

421 位名冊學者，2015–2025。合作者人數含外部作者；名冊內合作者數只算名冊學者之間。
"""
import numpy as np

from _common import (AQUA, BLUE, GREY, INK, INK2, MAGENTA, MUTED, ORANGE, gini, load_all, person_collab, plt, save,
                     section)

d = load_all()
r = person_collab(d)
N = len(r)

MEAS = [('n_collab', '合作者人數（含外部）', BLUE), ('n_collab_small', '合作者人數（排除 6 人以上論文）', GREY),
        ('roster_degree', '名冊內合作者數', AQUA), ('coauth', '合著論文數', ORANGE)]


def top_share(x, q):
    x = np.sort(np.asarray(x, float))[::-1]
    k = max(1, int(round(len(x) * q)))
    return x[:k].sum() / x.sum()


fig = plt.figure(figsize=(16, 6.4))
gs = fig.add_gridspec(1, 3, width_ratios=[1, 1, 1.05], wspace=0.32)
a1, a2, a3 = (fig.add_subplot(gs[i]) for i in range(3))

# ---- Lorenz ----
for col, lab, c in MEAS:
    x = np.sort(r[col].values.astype(float))
    cx = np.r_[0, np.arange(1, N + 1) / N]
    cy = np.r_[0, np.cumsum(x) / x.sum()]
    a1.plot(cx * 100, cy * 100, color=c, lw=2.2 if col != 'n_collab_small' else 1.4,
            ls='-' if col != 'n_collab_small' else '--', label=f'{lab}　Gini {gini(x):.2f}')
a1.plot([0, 100], [0, 100], color=MUTED, lw=0.8, ls=':')
a1.set_xlim(0, 100)
a1.set_ylim(0, 100)
a1.set_xlabel('名冊學者（由少到多累積，%）')
a1.set_ylabel('累積佔比（%）')
a1.legend(loc='upper left', fontsize=8.8)
a1.grid(True)
a1.set_title('A　Lorenz 曲線')

# ---- 互補累積分布（對數）----
for col, lab, c in MEAS:
    if col == 'n_collab_small':
        continue
    x = r[col].values
    x = np.sort(x[x > 0])
    ccdf = 1 - np.arange(len(x)) / len(x)
    a2.step(x, ccdf, where='post', color=c, lw=2, label=lab)
a2.set_xscale('log')
a2.set_yscale('log')
a2.set_xlabel('數值 k（人或篇，對數軸）')
a2.set_ylabel('至少有 k 的學者比例（對數軸，只含 > 0 的人）')
a2.grid(True, which='major')
a2.legend(loc='lower left', fontsize=8.8)
top = r.loc[r.n_collab.idxmax()]
a2.annotate(f'{top.name_zh}（{top.inst_short_2026}）\n{top.n_collab} 人／{top.coauth} 篇',
            xy=(top.n_collab, 1 / (r.n_collab > 0).sum()), xytext=(1.1, 0.075), fontsize=8.5, color=INK2,
            arrowprops=dict(arrowstyle='-', color=MUTED, lw=0.8))
from matplotlib.ticker import ScalarFormatter, FuncFormatter
a2.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f'{v:g}'))
a2.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f'{v:g}'))
a2.set_title('B　次數分布（互補累積）')

# ---- 前 1/5/10% 佔比 ----
qs = [0.01, 0.05, 0.10]
w = 0.2
for i, (col, lab, c) in enumerate(MEAS):
    v = [top_share(r[col], q) * 100 for q in qs]
    xs = np.arange(len(qs)) + (i - 1.5) * w
    a3.bar(xs, v, width=w * 0.92, color=c, label=lab, hatch='//' if col == 'n_collab_small' else None,
           edgecolor='white' if col != 'n_collab_small' else '#ffffff')
    for xx, vv in zip(xs, v):
        a3.text(xx, vv + 0.8, f'{vv:.0f}', ha='center', fontsize=8.3, color=INK2)
a3.set_xticks(range(3), [f'前 {int(q * 100)}%\n（{max(1, round(N * q))} 人）' for q in qs])
a3.set_ylabel('佔全體的比例（%）')
a3.set_ylim(0, 58)
a3.yaxis.grid(True)
a3.set_axisbelow(True)
a3.set_title('C　前 1%、5%、10% 的學者佔多少')
n_noroster = int((r.roster_degree == 0).sum())
n_solo_only = int(((r.coauth == 0) & (r.papers > 0)).sum())
n_none = int((r.papers == 0).sum())
a3.text(0.03, 0.97, f'名冊內沒有任何合作者：{n_noroster} 人（{n_noroster / N:.0%}）\n'
        f'有著作但全部是單一作者：{n_solo_only} 人\n2015–2025 沒有可建邊著作：{n_none} 人',
        transform=a3.transAxes, fontsize=9.5, color=INK, va='top', bbox=dict(fc='white', ec='#d6d5d0', boxstyle='round,pad=0.5'))

fig.suptitle('合作集中在少數人嗎？2015–2025，421 位名冊學者', x=0.08, y=1.02, ha='left', fontsize=15,
             fontweight='bold')
fig.text(0.08, 0.955, '合作者人數含外部作者（含外部作者的網路）；名冊內合作者數只算名冊學者之間（名冊內網路）。'
         '合著論文 = 2 位以上作者的可建邊著作。', fontsize=9.5, color=INK2)
save(fig, '02_concentration.png')

section('數字')
for col, lab, _ in MEAS:
    x = r[col]
    print(lab, 'Gini', round(gini(x), 3), '中位數', x.median(), '平均', round(x.mean(), 2), '最大', x.max(),
          '前1/5/10%', [round(top_share(x, q), 3) for q in qs])
print('名冊內 0 合作者', n_noroster, '｜只有獨著', n_solo_only, '｜沒有著作', n_none, '｜合作者 0', (r.n_collab == 0).sum())
ex = r.drop(r.n_collab.idxmax())
print('排除邱永和：合作者 Gini', round(gini(ex.n_collab), 3), '前10%', round(top_share(ex.n_collab, .1), 3))
print('只有獨著的人', r[(r.coauth == 0) & (r.papers > 0)][['name_zh', 'inst_short_2026', 'rank_2026', 'papers', 'journal']].to_string())
z = r[r.roster_degree == 0]
print('名冊內 0 合作者：職級', z.rank_group_2026.value_counts().to_dict(), '機構類型', z.inst_type_2026.value_counts().to_dict(),
      '聘任', z.appointment.value_counts().to_dict(), '外部合作者中位數', z.n_collab.median())
print('全體 機構類型', r.inst_type_2026.value_counts().to_dict(), '聘任', r.appointment.value_counts().to_dict())
