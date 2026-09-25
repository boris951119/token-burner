# -*- coding: utf-8 -*-
"""首页形状对判分环的影响——零 LLM 本地验证（不随包走）。

两种交付形态各起一个 Flask 服，喂同一份官方题面编译出的验收清单：
  A = 模块目录页当首页（v41 实交付的形状：/workbook/ /cell/ ... 的链接列表）
  B = 业务主页当首页（含题面逐字事实：Q3 Sales / East / North / Sheet1 / Region）
看自家判分环各自的 passed/failed，回答「这条死法我们的闸看不看得见」。
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask

TASK = Path.home() / "Developer/token-burner-taskdata/hackathon-req-0924-v2/hackathon--sheet"

DOC = ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
       '<title>Workbook Workspace</title></head><body>{}</body></html>')


def doc(inner: str) -> str:
    return DOC.format(inner)


NAV = doc("""<h1>Workbook Workspace</h1>
<nav>
<a href="/workbook/">Workbooks</a> | <a href="/worksheet/">Worksheets</a> |
<a href="/cell/">Cells</a> | <a href="/formula/">Formulas</a> |
<a href="/sortfilter/">Sort and Filter Rules</a> | <a href="/pivot/">Pivot Tables</a> |
<a href="/validation/">Data Validation</a> | <a href="/database/">Database</a>
</nav>""")

SUB_TPL = """<h2>{t}</h2><table><tr><th>id</th><th>name</th></tr>
<tr><td>1</td><td>Workspace item</td></tr></table>"""

HOME_B = doc("""<h1>Q3 Sales</h1>
<div>Sheet1</div>
<table>
<tr><th>Region</th><th>East</th><th>North</th></tr>
<tr><td>Q3 Sales</td><td>East</td><td>North</td></tr>
</table>
<form><label>Workbook name</label><input name="name"><button>Create</button></form>
<nav><a href="/workbook/">Workbooks</a> | <a href="/worksheet/">Worksheets</a></nav>""")


def build(home_html: str) -> Flask:
    app = Flask("app")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/")
    def home():
        return home_html

    for slug, title in (("workbook", "Workbooks"), ("worksheet", "Worksheets"),
                        ("cell", "Cells"), ("formula", "Formulas"),
                        ("sortfilter", "Sort and Filter Rules"),
                        ("pivot", "Pivot Tables"), ("validation", "Data Validation"),
                        ("database", "Database")):
        def view(t=title):
            return doc(SUB_TPL.format(t=t))
        app.add_url_rule(f"/{slug}/", slug, view)
    return app


def serve(app: Flask, port: int):
    threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, debug=False,
                              use_reloader=False),
        daemon=True).start()


def main() -> int:
    from app.utils.acceptance_judge import judge_requirements

    if not (TASK / "requirements.yaml").is_file():
        print(f"缺题面: {TASK}", file=sys.stderr)
        return 2
    for label, html, port in (("A 模块目录页当首页", NAV, 3401),
                              ("B 业务主页当首页", HOME_B, 3402)):
        serve(build(html), port)
    import time

    time.sleep(2.5)
    for label, port in (("A 模块目录页当首页", 3401), ("B 业务主页当首页", 3402)):
        base = f"http://127.0.0.1:{port}"
        r = judge_requirements(TASK, base)
        print(f"\n=== {label} ===")
        print(f"  nodes={r.get('nodes')} passed={r['passed']} failed={r['failed']} "
              f"total={r['total']}")
        for f in (r.get("failures") or [])[:6]:
            print("   红:", f[:150])
    return 0


if __name__ == "__main__":
    sys.exit(main())
