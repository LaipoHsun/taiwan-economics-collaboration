"""載入 map_explorer.html 背後的全部資料，給分析用。

HTML 是由 input/ 裡這幾張表算出來的（pipeline.build_html_payload），HTML 裡的資料是
縮短過的版本（題名截斷、欄位縮寫、沒有作者的 14 篇論文不放）。分析請用這裡讀到的完整表。

    import sys; sys.path.insert(0, 'final_plan/code/analysis')
    from load_data import load, graph

    d = load()                      # 全部的表（pandas DataFrame）
    d.nodes                         # 4,111 個節點：421 位名冊教師 + 3,690 位外部作者（2026-10-15 起不含沒有論文的外部節點）
    d.papers / d.projects           # 5,099 篇論文 / 1,975 筆計畫年度
    d.paper_edges / d.project_edges # 一列 = 一次合作事件，帶 year

    G = graph(d, layer='pub', year_from=2020, year_to=2023)   # 對應 HTML 的篩選器

需要 pandas、networkx。**所有資料都只從 final_plan/input/ 讀**（不讀快取、不碰前置data處理），
input/ 由 final_plan/build.py 產生；流程見 final_plan/資料流程.md。

    g = load_grants()               # 國科會計畫（含核定金額），input/project/grants.csv
"""
import json
import os
import sys
from types import SimpleNamespace

import pandas as pd

FINAL = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INPUT = os.path.join(FINAL, 'input')
YEARS = list(range(2015, 2027))


def _read(*p):
    return pd.read_csv(os.path.join(INPUT, *p), dtype={'teacher_id': str, 'institution_code': str,
                                                       'source_teacher_id': str, 'target_teacher_id': str},
                       keep_default_na=False, na_values=[''], encoding='utf-8-sig')


def _parse_json_cols(df):
    """`*_json` 欄位從字串轉成 Python list/dict，空值變成空 list。"""
    for c in df.columns:
        if c.endswith('_json'):
            df[c] = df[c].map(lambda s: json.loads(s) if isinstance(s, str) and s else [])
    return df


def load(with_places=False):
    """回傳 SimpleNamespace，屬性如下（都是 DataFrame）：

    nodes            全部網路節點（authors_master.csv）。node_type = roster / external
                     名冊教師另外併入性別、博士學歷、JEL 領域欄位（gender, gender_source,
                     phd_school, phd_country, phd_field, phd_year, phd_confidence, jel_primary…）
    roster_gender    性別：gender = M / F / 空白，gender_source = manual / nstc_basic
    roster_phd       博士學歷：phd_school, phd_country, phd_field, phd_year, phd_confidence, phd_evidence_url
    roster_jel       專長文字對應的 JEL 主類與全部類別
    roster_inactive  在名冊但 2015–2026 沒有任何紀錄的 99 位教師
    papers           論文，一列一篇；edge_eligible=1 才有建邊
    paper_authors    論文 × 作者節點（由 author_node_ids_json 展開），含作者順序 position
    projects         計畫年度，一列一個 project_key
    paper_edges      共著邊事件；layer='pub'
    project_edges    共同計畫邊事件；layer='proj'
    edges            兩層合併，多一欄 layer
    institutions     27 個名冊機構與座標
    professor_geo    名冊教師 → 機構、縣市、經緯度
    places           with_places=True 時才有：外部作者 → 機構座標與第三機構標記（input/map/external_places.csv，同 HTML 地圖）
    external_departments  外部作者 → 從署名拆出的系所（input/professor_demo/external_departments.csv）
    """
    d = SimpleNamespace()
    d.nodes = _parse_json_cols(_read('professor_demo', 'authors_master.csv'))
    d.roster_inactive = _parse_json_cols(_read('professor_demo', 'professors_inactive.csv'))
    d.papers = _parse_json_cols(_read('paper', 'papers_all.csv'))
    d.projects = _parse_json_cols(_read('project', 'projects_all.csv'))
    d.paper_edges = _parse_json_cols(_read('network', 'paper_network_edges.csv')).assign(layer='pub')
    d.project_edges = _parse_json_cols(_read('network', 'project_network_edges.csv')).assign(layer='proj')
    d.edges = pd.concat([d.paper_edges, d.project_edges], ignore_index=True)
    # 名冊補充屬性（roster_attributes.py 產生）：各自一張表，同時併進 nodes；外部作者這些欄位是空的
    for attr, fn in (('roster_gender', 'roster_gender.csv'), ('roster_phd', 'roster_phd.csv'),
                     ('roster_jel', 'roster_field_jel.csv')):
        t = _read('professor_demo', fn) if os.path.exists(os.path.join(INPUT, 'professor_demo', fn)) \
            else pd.DataFrame(columns=['teacher_id'])
        setattr(d, attr, t)
        new = ['teacher_id'] + [c for c in t.columns if c not in d.nodes.columns]
        d.nodes = d.nodes.merge(t[new], on='teacher_id', how='left')
    d.institutions = _read('map', 'institutions.csv')
    d.professor_geo = _read('map', 'professor_geo.csv')

    pa = d.papers[['paper_id', 'year', 'pub_category', 'author_node_ids_json']].explode('author_node_ids_json')
    pa = pa.dropna(subset=['author_node_ids_json']).rename(columns={'author_node_ids_json': 'node_id'})
    pa['position'] = pa.groupby('paper_id').cumcount() + 1
    d.paper_authors = pa.reset_index(drop=True)

    if with_places:
        d.places = external_places(d)
    d.external_departments = _read('professor_demo', 'external_departments.csv')
    d.build = build_info()
    if not _ANNOUNCED:
        print(f'[load_data] input/ 建置於 {d.build.get("built_at", "未知（沒有 BUILD.json，請跑 final_plan/build.py）")}',
              file=sys.stderr)
        _ANNOUNCED.append(1)
    return d


_ANNOUNCED = []


def build_info():
    """input/BUILD.json：最近一次 build.py 的時間、各表筆數、decisions/ 與 input/ 檔案的雜湊值。"""
    path = os.path.join(INPUT, 'BUILD.json')
    return json.load(open(path, encoding='utf-8')) if os.path.exists(path) else {}


def external_places(d):
    """外部作者的機構位置：讀 input/map/external_places.csv（pipeline 第 8 階段產生，與 HTML 地圖同一份）。
    回傳 node_id, place_type, institution_code, place_key, label, country, city, lat, lon, src, org_type。
    place_type：roster = 落在名冊 27 校（座標用該校）；institution = 其他機構；查不到的不在表內。
    org_type：third = 人工標記的「第三機構」（企業、金融、醫療等非學術單位）；src = manual 表示人工確認的地址座標。"""
    p = _read('map', 'external_places.csv')
    for c in ('institution_code', 'place_key', 'label', 'city', 'org_type'):
        p[c] = p[c].fillna('')
    ll = d.institutions.set_index('institution_code')[['lat', 'lon']]
    r = p.place_type == 'roster'
    p.loc[r, 'lat'] = p.loc[r, 'institution_code'].map(ll.lat).values
    p.loc[r, 'lon'] = p.loc[r, 'institution_code'].map(ll.lon).values
    return p


def load_grants(d=None):
    """國科會計畫紀錄（含核定金額）：讀 input/project/grants.csv（pipeline 第 8 階段產生），一列一筆原始紀錄。
    欄位：原始欄位（record_id, teacher_id, roc_year, grant_category, project_title, role…）＋
    aligned（已對回原始網頁）, amount（核定經費，元）, year, is_pi（主持人）, marked（題名帶 (k/n)）, node_id,
    gap_next（同一主持人下一筆專題研究計畫相隔年數）, dur（推估執行年數，1–3）, amount_per_year。
    多年期計畫：2006 年後大多只列一筆、金額為全期總額，所以用 dur 平攤；共同主持人列的是整個計畫的金額，加總會重複。"""
    g = pd.read_csv(os.path.join(INPUT, 'project', 'grants.csv'), dtype=str, keep_default_na=False)
    for c in ('aligned', 'is_pi', 'marked'):
        g[c] = g[c] == 'True'
    for c in ('amount', 'gap_next', 'amount_per_year'):
        g[c] = pd.to_numeric(g[c].replace('', None), errors='coerce')
    g['year'] = pd.to_numeric(g['year'], errors='coerce')
    g['dur'] = g['dur'].astype(int)
    g['node_id'] = g['node_id'].replace('', None)
    return g


def edge_events(d, layer='pub', year_from=2015, year_to=2026, external=False,
                scope='all', strict_projects=False):
    """依 HTML 的篩選器取出邊事件（還沒聚合）。

    layer            'pub' 共著 / 'proj' 共同計畫 / 'both'
    external         False = 只留兩端都是名冊教師的邊（HTML 預設）；True = 含外部作者
    scope            'all' / 'within' 同機構 / 'across' 跨機構（只看兩端都有名冊機構的邊）
    strict_projects  True = 計畫層只留兩人同一年都有登錄的（both_recorded_this_year=1）
    """
    e = {'pub': d.paper_edges, 'proj': d.project_edges, 'both': d.edges}[layer]
    e = e[(e.year >= year_from) & (e.year <= year_to)]
    if strict_projects and 'both_recorded_this_year' in e:
        e = e[(e.layer != 'proj') | (e.both_recorded_this_year == 1)]
    if not external:
        e = e[e.both_roster == 1]
    if scope != 'all':
        inst = _node_institution(d)
        a, b = e.source_node_id.map(inst), e.target_node_id.map(inst)
        same = a.notna() & b.notna() & (a == b)
        e = e[same] if scope == 'within' else e[a.notna() & b.notna() & (a != b)]
    return e


def _node_institution(d):
    """node_id → 名冊機構代碼。名冊教師用名冊機構；外部作者只有落在名冊 27 校時才有。"""
    inst = dict(zip(d.professor_geo.teacher_id, d.professor_geo.institution_code))
    if hasattr(d, 'places'):
        r = d.places[d.places.place_type == 'roster']
        inst.update(zip(r.node_id, r.institution_code))
    return pd.Series(inst)


def aggregate(events):
    """把邊事件聚合成合作對：count = 合作次數（篇數或計畫年度數），另加兩種權重總和與年份。"""
    a = events[['source_node_id', 'target_node_id']].min(axis=1)
    b = events[['source_node_id', 'target_node_id']].max(axis=1)
    # 一篇論文 = paper_id；一個計畫年度 = 計畫家族:年份（跟 HTML 點邊時列出的單位一樣）
    pub = events.layer == 'pub'
    item = pd.Series('', index=events.index)
    if pub.any():
        item[pub] = events.loc[pub, 'paper_id']
    if (~pub).any():
        item[~pub] = events.loc[~pub, 'project_family_key'] + ':' + events.loc[~pub, 'year'].astype(str)
    g = events.assign(u=a, v=b, item=item).groupby(['u', 'v'])
    return g.agg(count=('item', 'nunique'), weight_1n=('weight_1n', 'sum'),
                 weight_pair=('weight_pair', 'sum'), first_year=('year', 'min'),
                 last_year=('year', 'max'), items=('item', lambda s: sorted(set(s)))).reset_index()


def graph(d, layer='pub', year_from=2015, year_to=2026, external=False, scope='all',
          min_count=1, strict_projects=False, include_isolates=False):
    """建 networkx 無向圖，邊屬性 count / weight_1n / weight_pair / items（合作的論文或計畫）。
    節點屬性取自 d.nodes（名字、機構、系所、國別、OpenAlex 指標…）。
    include_isolates=True 時把這段期間有活動但沒有邊的名冊教師也放進去。"""
    import networkx as nx
    pairs = aggregate(edge_events(d, layer, year_from, year_to, external, scope, strict_projects))
    pairs = pairs[pairs['count'] >= min_count]
    G = nx.Graph()
    for r in pairs.itertuples(index=False):
        G.add_edge(r.u, r.v, count=r.count, weight_1n=r.weight_1n, weight_pair=r.weight_pair,
                   first_year=r.first_year, last_year=r.last_year, items=r.items)
    if include_isolates:
        G.add_nodes_from(d.nodes.loc[d.nodes.node_type == 'roster', 'node_id'])
    attrs = d.nodes.set_index('node_id')[[
        'node_type', 'teacher_id', 'name_zh', 'name_en_canonical', 'name_en', 'institution_code',
        'institution_zh', 'department_zh', 'county', 'lat', 'lon', 'affil_institution_norm',
        'affil_country', 'identity_status', 'n_pubs_total', 'n_citations_total', 'oa_primary_field',
        'gender', 'phd_school', 'phd_country', 'phd_field', 'phd_year', 'jel_primary']]
    nx.set_node_attributes(G, attrs.reindex(list(G.nodes)).to_dict('index'))
    return G


if __name__ == '__main__':
    d = load()
    print('nodes', len(d.nodes), d.nodes.node_type.value_counts().to_dict())
    print('papers', len(d.papers), 'projects', len(d.projects))
    print('paper_edges', len(d.paper_edges), 'project_edges', len(d.project_edges))
    G = graph(d)
    print('roster co-authorship graph 2015–2026:', G.number_of_nodes(), 'nodes,', G.number_of_edges(), 'edges')
