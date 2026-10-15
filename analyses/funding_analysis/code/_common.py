"""經費分配分析共用的路徑、讀檔與畫圖設定（本身不是分析）。

資料一律經 final_plan/code/analysis/load_data.py 讀取（只讀 final_plan/input/）；經費用 load_data.load_grants()，
讀 final_plan/input/project/grants.csv。圖存到 ../output/，只輸出 PNG。
"""
import os
import sys

import matplotlib
import numpy as np

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                                # final_plan/analyses/<本資料夾>
FINAL = os.path.dirname(os.path.dirname(ROOT))              # final_plan
OUT = os.path.join(ROOT, 'output')
sys.path.insert(0, os.path.join(FINAL, 'code', 'analysis'))

from load_data import load, load_grants  # noqa: E402,F401

plt.rcParams.update({
    'font.family': ['Heiti TC', 'PingFang HK', 'Arial Unicode MS', 'sans-serif'],
    'axes.unicode_minus': False,
    'axes.spines.top': False,
    'axes.spines.right': False,
    'axes.edgecolor': '#8a8a86',
    'axes.labelcolor': '#2b2b2a',
    'xtick.color': '#52514e',
    'ytick.color': '#52514e',
    'grid.color': '#e4e3df',
    'grid.linewidth': 0.7,
    'figure.dpi': 110,
    'savefig.dpi': 160,
    'figure.facecolor': 'white',
    'axes.titlesize': 13,
    'axes.titleweight': 'bold',
    'axes.titlelocation': 'left',
    'axes.labelsize': 10,
    'legend.frameon': False,
})
# 配色：dataviz 參考色盤（已驗證色盲可辨）；文字一律用 INK 系列，不用系列色
INK, INK2, MUTED = '#0b0b0b', '#52514e', '#8a8a86'
GREY, LIGHTGREY = '#9aa3ad', '#d6d5d0'
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED = (
    '#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948')
ACCENT, ACCENT2 = BLUE, MAGENTA
GENDER_COLOR = {'M': BLUE, 'F': ORANGE}
GENDER_LABEL = {'M': '男', 'F': '女'}
YEARS = list(range(2015, 2026))  # 主要期間；2026 只收到 9 月

# ---- 計畫類別分組（顏色固定跟著類別，不跟排名） ----
CAT_ORDER = ['一般研究', '新進人員', '年輕學者獎勵', '特約與其他專題', '推動規劃', '人才培育與圖書', '延攬人才', '交流與會議']
CAT_COLOR = {'一般研究': BLUE, '新進人員': ORANGE, '年輕學者獎勵': YELLOW, '特約與其他專題': MAGENTA,
             '推動規劃': AQUA, '人才培育與圖書': GREEN, '延攬人才': VIOLET, '交流與會議': GREY}
# 「個人研究計畫」：前四類。推動規劃（中心、調查、學門規劃）、人才培育與圖書（博士生獎學金、圖書補助）多半是代管的機構性經費
RESEARCH_CATS = ['一般研究', '新進人員', '年輕學者獎勵', '特約與其他專題']
YOUNG = ('優秀年輕學者', '國際年輕傑出學者', '新秀學者', '愛因斯坦培植', '吳大猷先生紀念獎')


def cat_group(c):
    if not isinstance(c, str):
        return '交流與會議'
    if '一般研究計畫' in c:
        return '一般研究'
    if '新進人員' in c:
        return '新進人員'
    if '推動規劃' in c:
        return '推動規劃'
    if any(k in c for k in YOUNG):
        return '年輕學者獎勵'
    if '人才培育' in c or '圖書資料庫' in c:
        return '人才培育與圖書'
    if c.startswith('專題研究計畫'):
        return '特約與其他專題'
    if c.startswith('延攬科技人才'):
        return '延攬人才'
    return '交流與會議'


# ---- 機構 ----
INST_SHORT = {
    '國立臺灣大學': '臺大', '國立政治大學': '政大', '國立清華大學': '清大', '國立臺北大學': '臺北大',
    '國立中正大學': '中正', '國立中山大學': '中山', '國立成功大學': '成大', '國立中央大學': '中央',
    '國立高雄大學': '高雄大', '國立暨南國際大學': '暨南', '國立中興大學': '中興', '國立東華大學': '東華',
    '國立宜蘭大學': '宜蘭大', '國立臺灣海洋大學': '海大', '國立嘉義大學': '嘉義大',
    '中央研究院經濟研究所': '中研院經濟所', '中央研究院人文社會科學研究中心': '中研院人社中心',
    '淡江大學學校財團法人淡江大學': '淡江', '輔仁大學學校財團法人輔仁大學': '輔仁', '東吳大學': '東吳',
    '逢甲大學': '逢甲', '東海大學': '東海', '銘傳大學': '銘傳', '中國文化大學': '文化', '佛光大學': '佛光',
    '世新大學': '世新', '真理大學': '真理',
}
INST_TYPE_ORDER = ['中研院', '國立', '私立']
INST_TYPE_COLOR = {'中研院': VIOLET, '國立': BLUE, '私立': ORANGE}


def inst_type(s):
    if not isinstance(s, str):
        return None
    if s.startswith('中央研究院'):
        return '中研院'
    return '國立' if s.startswith('國立') else '私立'


def rank_group(rank):
    """職級三分：助理（助理教授、助研究員）、副（副教授、副研究員）、正（教授、研究員各類）。"""
    if not isinstance(rank, str):
        return None
    if rank.startswith('助'):
        return '助理'
    if rank.startswith('副'):
        return '副'
    return '正'


RANK_ORDER = ['助理', '副', '正']
PHD_ORDER = ['國內', '美國', '其他國外']


def phd_origin(c):
    if not isinstance(c, str) or not c:
        return None
    return '國內' if c == 'TW' else ('美國' if c == 'US' else '其他國外')


JEL_ZH = {'A': '一般經濟', 'B': '思想史', 'C': '計量與數理', 'D': '個體', 'E': '總體貨幣', 'F': '國際',
          'G': '財務', 'H': '公共', 'I': '健康教育福利', 'J': '勞動人口', 'K': '法律經濟', 'L': '產業組織',
          'M': '企管行銷', 'N': '經濟史', 'O': '發展成長', 'P': '政治經濟', 'Q': '農業環境',
          'R': '區域都市', 'Z': '其他'}


def save(fig, name):
    os.makedirs(OUT, exist_ok=True)
    fig.savefig(os.path.join(OUT, name), bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'[figure] {name}')


def section(title):
    print(f'\n=== {title} ===')


def wan(x):
    """新台幣元 → 萬元字串。"""
    return f'{x / 1e4:,.0f}'


def gini(x):
    x = np.sort(np.asarray(x, float))
    n = len(x)
    return (2 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum())


def pi_grants(g, years=YEARS):
    """主持人、已對回、起始年在 years 內的計畫；加上類別分組。"""
    p = g[g.aligned & g.is_pi & g.year.isin(years)].copy()
    p['cat'] = p.grant_category.map(cat_group)
    return p


def roster(d):
    r = d.nodes[d.nodes.node_type == 'roster'].copy()
    r['rank_group_2026'] = r['rank'].map(rank_group)
    r['rank_2026'] = r['rank']
    r['institution_2026'] = r['institution_zh']
    r['inst_short_2026'] = r.institution_zh.map(INST_SHORT).fillna(r.institution_zh)
    r['inst_type_2026'] = r.institution_zh.map(inst_type)
    r['phd_origin'] = r.phd_country.map(phd_origin)
    r['field'] = r.jel_primary.map(lambda j: f'{j} {JEL_ZH[j]}' if isinstance(j, str) and j in JEL_ZH else None)
    return r


def papers_per_person(d, years=YEARS):
    """2015–2025、edge_eligible == 1 的著作：每位名冊學者的期刊論文數與全部著作數。"""
    p = d.papers[(d.papers.edge_eligible == 1) & d.papers.year.isin(years)][['paper_id', 'pub_category']]
    pa = d.paper_authors[['paper_id', 'node_id']].drop_duplicates().merge(p, on='paper_id')
    return pd.DataFrame({'journal': pa[pa.pub_category == '期刊論文'].groupby('node_id').size(),
                         'papers': pa.groupby('node_id').size()})


def person_table(d, g):
    """一列一位名冊學者（421 人）：屬性 + 2015–2025 主持人經費（起始年歸屬，元）+ 產出。"""
    r = roster(d).set_index('node_id')
    p = pi_grants(g)
    amt = p.assign(amount=p.amount.fillna(0))
    r['funding'] = amt.groupby('node_id').amount.sum().reindex(r.index, fill_value=0)
    by_cat = amt.pivot_table(index='node_id', columns='cat', values='amount', aggfunc='sum', fill_value=0)
    for c in CAT_ORDER:
        r[f'f_{c}'] = by_cat[c].reindex(r.index, fill_value=0) if c in by_cat else 0
    r['funding_research'] = r[[f'f_{c}' for c in RESEARCH_CATS]].sum(axis=1)
    r['n_pi'] = p.groupby('node_id').size().reindex(r.index, fill_value=0)
    pp = papers_per_person(d)
    r['journal'] = pp.journal.reindex(r.index).fillna(0).astype(int)
    r['papers'] = pp.papers.reindex(r.index).fillna(0).astype(int)
    return r


def repel(ax, texts, iters=300, pad=2.0, move_x=False):
    """簡單的標籤避讓：反覆把重疊的文字框在垂直方向（可選水平）推開。texts 為 ax.text 物件。"""
    fig = ax.figure
    fig.canvas.draw()
    inv = ax.transData.inverted()
    for _ in range(iters):
        r = fig.canvas.get_renderer()
        boxes = [t.get_window_extent(r).expanded(1.0, 1.0) for t in texts]
        moved = False
        for i in range(len(texts)):
            for j in range(i + 1, len(texts)):
                a, b = boxes[i], boxes[j]
                if a.x0 < b.x1 + pad and b.x0 < a.x1 + pad and a.y0 < b.y1 + pad and b.y0 < a.y1 + pad:
                    dy = (min(a.y1, b.y1) - max(a.y0, b.y0) + pad) / 2 + 0.5
                    sy = 1 if (a.y0 + a.y1) >= (b.y0 + b.y1) else -1
                    dx = (min(a.x1, b.x1) - max(a.x0, b.x0) + pad) / 4 if move_x else 0
                    sx = 1 if (a.x0 + a.x1) >= (b.x0 + b.x1) else -1
                    bb = ax.bbox
                    for t, s in ((texts[i], 1), (texts[j], -1)):
                        x, y = ax.transData.transform(t.get_position())
                        x = min(max(x + s * sx * dx, bb.x0), bb.x1)
                        y = min(max(y + s * sy * dy, bb.y0 + 6), bb.y1 - 6)
                        t.set_position(inv.transform((x, y)))
                    moved = True
                    boxes = [t.get_window_extent(r) for t in texts]
        if not moved:
            break


pd.set_option('display.width', 180)
