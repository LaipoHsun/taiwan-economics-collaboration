"""final_plan 的單一入口：從上游原始資料＋人工判斷重建 input/、HTML，並做驗收。

    python3 final_plan/build.py              # 離線重建（只用 raw_data/cache，不連網）
    python3 final_plan/build.py --online     # 允許連網補抓 OpenAlex／Wikidata（新增外部機構時才需要）
    python3 final_plan/build.py --check      # 只做驗收，不重建

順序（每一步都只讀前一步的產出，流程說明見 資料流程.md）：
  0. 備份 decisions/（和上一次備份不同時才存一份到 .local-backup/decisions_時間/）
  1. pipeline 第 1、2、3、4、6 階段：作者名單修正 → 主建置 → OpenAlex 補充 → 期刊機構 → 外部作者機構
  2. roster_attributes：名冊學者的性別、博士學歷、研究領域
  3. pipeline 第 8 階段：外部作者位置、系所、國科會經費 → input/
  4. HTML：output/html/map_explorer.html（只讀 input/）
  5. 驗收：人工判斷都有套用、沒有懸空的節點、input/ 該有的檔案都在
  6. 寫 input/BUILD.json：建置時間、各表筆數、decisions/ 每個檔案的雜湊值
任何一步失敗就停下，不寫 BUILD.json。
"""
import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime

FINAL = os.path.dirname(os.path.abspath(__file__))
INPUT = os.path.join(FINAL, 'input')
DEC = os.path.join(FINAL, 'decisions')
BACKUP = os.path.join(FINAL, '.local-backup')
PIPELINE = os.path.join(FINAL, 'code', 'pipeline', 'pipeline.py')
ROSTER_ATTR = os.path.join(FINAL, 'code', 'pipeline', 'roster_attributes.py')
HTML = os.path.join(FINAL, 'output', 'html', 'map_explorer.html')
GEN = os.path.join(FINAL, 'raw_data', 'generated')
UPSTREAM_NODES = os.path.join(os.path.dirname(FINAL), '前置data處理', 'collab_network', 'output',
                              'author_teacher_id_by_gpt.csv')

# 分析（load_data）與 HTML 會讀的全部檔案；少一個就驗收失敗
REQUIRED = [
    'professor_demo/authors_master.csv', 'professor_demo/professors_inactive.csv',
    'professor_demo/roster_gender.csv', 'professor_demo/roster_phd.csv', 'professor_demo/roster_field_jel.csv',
    'professor_demo/external_departments.csv',
    'paper/papers_all.csv', 'project/projects_all.csv', 'project/grants.csv',
    'network/paper_network_edges.csv', 'network/project_network_edges.csv',
    'map/institutions.csv', 'map/professor_geo.csv', 'map/external_places.csv',
    'map/basemap/tw_county.geojson', 'map/basemap/ne_50m_admin_0_countries.geojson',
]


def run(cmd):
    print('\n$ ' + ' '.join(os.path.relpath(c, FINAL) if c.startswith(FINAL) else c for c in cmd), flush=True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    r = subprocess.run(cmd, cwd=FINAL, env=env)
    if r.returncode:
        sys.exit(f'✗ 失敗（exit {r.returncode}）：{" ".join(cmd)}')


def md5(path):
    return hashlib.md5(open(path, 'rb').read()).hexdigest()


def rows(*p):
    with open(os.path.join(*p), newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def snapshot_decisions():
    """decisions/ 和最近一次備份不同時，複製一份到 .local-backup/decisions_YYYYmmdd_HHMMSS/。"""
    now = {f: md5(os.path.join(DEC, f)) for f in sorted(os.listdir(DEC)) if f.endswith('.csv')}
    snaps = sorted(d for d in os.listdir(BACKUP) if d.startswith('decisions_')) if os.path.isdir(BACKUP) else []
    if snaps:
        last = os.path.join(BACKUP, snaps[-1])
        prev = {f: md5(os.path.join(last, f)) for f in os.listdir(last) if f.endswith('.csv')}
        if prev == now:
            print(f'decisions/ 與上次備份（{snaps[-1]}）相同，不另存。')
            return
    dst = os.path.join(BACKUP, 'decisions_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
    shutil.copytree(DEC, dst)
    print(f'decisions/ 已備份 → {os.path.relpath(dst, FINAL)}')


def check():
    """驗收。回傳 (errors, warnings)。"""
    err, warn = [], []
    for f in REQUIRED:
        if not os.path.exists(os.path.join(INPUT, f)):
            err.append(f'input/{f} 不存在')
    if err:
        return err, warn
    master = {r['node_id']: r for r in rows(INPUT, 'professor_demo', 'authors_master.csv')}
    ext = {k: r for k, r in master.items() if r['node_type'] == 'external'}
    # 沒有論文的外部節點不應出現
    empty = [k for k, r in ext.items() if r['n_papers'] in ('', '0')]
    if empty:
        err.append(f'{len(empty)} 個外部節點沒有論文（例：{empty[:3]}）')
    # 節點合併：from 不該還在、to 必須存在
    for r in rows(DEC, 'external_node_merges.csv'):
        if r['from_node_id'] in master:
            err.append(f'合併表的 {r["from_node_id"]}（{r["name"]}）仍在主檔，合併沒有套用')
        if r['to_node_id'] not in master:
            err.append(f'合併表的目標 {r["to_node_id"]}（{r["name"]}）不在主檔')
    merged = {r['from_node_id']: r['to_node_id'] for r in rows(DEC, 'external_node_merges.csv')}
    upstream = {r['node_id'] for r in rows(UPSTREAM_NODES)} | {r['node_id'] for r in rows(GEN, 'new_external_nodes.csv')}
    # 逐人機構覆寫：節點必須存在且已套用；被合併掉的、因為沒有論文而不輸出的只提醒
    for r in rows(DEC, 'external_affiliations_manual.csv'):
        n = master.get(r['node_id'])
        if n is None:
            who = f'人工機構 {r["node_id"]}（{r["name"]}）'
            if r['node_id'] in merged:
                warn.append(f'{who}已併入 {merged[r["node_id"]]}，這列不再使用')
            elif r['node_id'] in upstream:
                warn.append(f'{who}沒有任何論文、不輸出，這列不再使用')
            else:
                err.append(f'{who}不在主檔，也不在上游節點表')
        elif n['affil_source'] != 'manual_verified' or n['affil_institution_norm'] != r['institution']:
            err.append(f'人工機構 {r["node_id"]}（{r["name"]}）沒有套用到主檔')
    # 地點裁定：名稱已經沒有任何外部作者在用的，只提醒
    used = {' '.join((r['affil_institution_norm'] or '').split()) for r in ext.values()}
    stale = [r['affil_name'] for r in rows(DEC, 'external_institution_geo.csv') if r['affil_name'] not in used]
    if stale:
        warn.append(f'external_institution_geo.csv 有 {len(stale)} 個機構名稱目前沒有外部作者使用（例：{stale[:3]}）')
    # input 之間的一致性
    for r in rows(INPUT, 'map', 'external_places.csv'):
        if r['node_id'] not in ext:
            err.append(f'external_places.csv 的 {r["node_id"]} 不在主檔')
            break
    for r in rows(INPUT, 'professor_demo', 'external_departments.csv'):
        if r['node_id'] not in ext:
            err.append(f'external_departments.csv 的 {r["node_id"]} 不在主檔')
            break
    for fn in ('paper_network_edges.csv', 'project_network_edges.csv'):
        bad = {x for r in rows(INPUT, 'network', fn) for x in (r['source_node_id'], r['target_node_id'])} - set(master)
        if bad:
            err.append(f'{fn} 有 {len(bad)} 個節點不在主檔')
    g = rows(INPUT, 'project', 'grants.csv')
    un = sum(r['aligned'] != 'True' for r in g)
    if un:
        warn.append(f'grants.csv 有 {un} 筆沒有對回原始網頁（沒有金額）')
    # HTML 要比 input 新
    if not os.path.exists(HTML):
        err.append('HTML 不存在')
    else:
        newest = max(os.path.getmtime(os.path.join(INPUT, f)) for f in REQUIRED)
        if os.path.getmtime(HTML) < newest:
            err.append('HTML 比 input/ 舊，請重建')
    return err, warn


def write_build_json():
    master = rows(INPUT, 'professor_demo', 'authors_master.csv')
    info = {
        'built_at': datetime.now().isoformat(timespec='seconds'),
        'counts': {
            'roster_nodes': sum(r['node_type'] == 'roster' for r in master),
            'external_nodes': sum(r['node_type'] == 'external' for r in master),
            'papers': len(rows(INPUT, 'paper', 'papers_all.csv')),
            'paper_edge_events': len(rows(INPUT, 'network', 'paper_network_edges.csv')),
            'project_edge_events': len(rows(INPUT, 'network', 'project_network_edges.csv')),
            'grant_records': len(rows(INPUT, 'project', 'grants.csv')),
            'external_places': len(rows(INPUT, 'map', 'external_places.csv')),
            'external_departments': len(rows(INPUT, 'professor_demo', 'external_departments.csv')),
        },
        'decisions_md5': {f: md5(os.path.join(DEC, f)) for f in sorted(os.listdir(DEC)) if f.endswith('.csv')},
        'input_md5': {f: md5(os.path.join(INPUT, f)) for f in REQUIRED},
    }
    with open(os.path.join(INPUT, 'BUILD.json'), 'w', encoding='utf-8') as f:
        json.dump(info, f, ensure_ascii=False, indent=1)
    print('\n已寫入 input/BUILD.json：', json.dumps(info['counts'], ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--online', action='store_true', help='允許連網補抓 OpenAlex／Wikidata')
    ap.add_argument('--check', action='store_true', help='只做驗收，不重建')
    a = ap.parse_args()
    if not a.check:
        snapshot_decisions()
        off = [] if a.online else ['--offline']
        run([sys.executable, PIPELINE, '--stage', '1', '2', '3', '4', '6'] + off)
        run([sys.executable, ROSTER_ATTR])
        run([sys.executable, PIPELINE, '--stage', '8'] + off)
        run([sys.executable, PIPELINE, '--html'] + off)
    err, warn = check()
    print('\n══ 驗收 ══')
    for w in warn:
        print('  ⚠ ' + w)
    for e in err:
        print('  ✗ ' + e)
    if err:
        sys.exit(f'驗收失敗：{len(err)} 項錯誤')
    print(f'  ✓ 通過（{len(warn)} 項提醒）')
    if not a.check:
        write_build_json()


if __name__ == '__main__':
    main()
