"""產生地圖：互動版 HTML（預設）或靜態網路圖 PNG。

    python3 code/html/build_map.py                      # → output/html/map_explorer.html（只讀 input/）
    python3 code/html/build_map.py --map --layer both   # 靜態圖，參數同 pipeline.py --map

繪圖邏輯寫在 code/pipeline/pipeline.py 裡（stage8_map、stage9_html），這支只是入口。
HTML 只讀 input/（含第 8 階段寫入的外部作者位置、系所與底圖），不讀快取、不碰上游資料。
平常請用 final_plan/build.py 一次重建資料與 HTML。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pipeline'))
import pipeline  # noqa: E402

if __name__ == '__main__':
    args = sys.argv[1:]
    if not {'--map', '--all', '--html'} & set(args):
        args = ['--html'] + args
    sys.argv = [sys.argv[0]] + args
    pipeline.main()
