#!/usr/bin/env python3
"""Final *original graphic* university graph test (no synthetic drawings).

Each image is rasterized directly from a public university PDF. OCR/vision,
the complete model answer and user-specified question are all preserved.
A correct regex/number is NEVER considered sufficient proof of visual topology.
Sources marked as lecture examples/solutions are not falsely called exam papers.
"""
import argparse, hashlib, json, os, re, time
from pathlib import Path
import requests
from university_discrete_benchmark import pdf_crop, post_image, post_chat

CASES=[
 dict(id="MIT05_P3",institution="MIT",country="US",origin="2005 6.042J Problem Set 4 Problem 3, actual diagram",
  url="https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/587366ef0ee07f57ed41715559224224_ps4.pdf",
  page=1,box=(.19,.065,.82,.29),
  question="只根据图中 A 到 H 的黑点与连线，求该无向图的直径及色数，并解释。相交线段若没有黑点，不构成顶点。",
  gold_note="A-H, 8 vertices, 9 edges; diameter 5; chromatic number 3",
  markers=[r"(?<!\d)5(?!\d)|五",r"(?<!\d)3(?!\d)|三"],
  visual_gold=dict(vertices=list("ABCDEFGH"),
   edges=["AB","BC","BH","CD","CE","DE","EF","EH","FG"])),
 dict(id="MIT05_FOUR",institution="MIT",country="US",origin="2005 6.042J lecture 13 Problem 1, four graph drawings",
  url="https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/6bd335dd854ae40a03066127fae962ab_cp5f.pdf",
  page=1,box=(.065,.12,.935,.825),
  question="观察Figure 1至4四张图。哪几组图作为无向图同构？请列出每图顶点、边，并解释平面画法的区别。",
  gold_note="Figures 1,2 identical abstract graph on a,b,c,d; figures 3,4 identical graph on a,b,c,d,e; cross-group nonisomorphic",
  markers=[r"1.{0,50}2|图\s*1.{0,35}图\s*2",r"3.{0,50}4|图\s*3.{0,35}图\s*4"]),
 dict(id="STANFORD_TREE6",institution="Stanford University",country="US",origin="Math 108 Homework 1 solutions Problem 2A figure (original university graphic with teacher gold)",
  url="https://web.stanford.edu/class/math108/files/hw1sol.pdf",
  page=2,box=(.25,.115,.82,.39),
  question="图中有几棵互不同构的六顶点树？逐图判断顶点数、边数，并说明为什么它们分属不同同构类。不要借助图中以外的推测。",
  gold_note="Six nonisomorphic trees on six vertices, 5 edges each; some share degree sequence",
  markers=[r"(?<!\d)6(?!\d)|六",r"(?<!\d)5(?!\d)|五"]),
 dict(id="HKUST_PETERSEN",institution="HKUST",country="China (Hong Kong)",origin="MATH4821B Planar Graphs lecture Example 1.3 Figure 4, not exam",
  url="https://www.math.hkust.edu.hk/~mabfchen/Math4821B/Planar-Graphs.pdf",
  page=2,box=(.30,.10,.70,.335),
  question="只看图中的 Petersen 图：顶点总数、边总数、每个顶点度数各是多少？是否平面图？尤其注意交叉线没有黑点时不是顶点。",
  gold_note="Petersen graph has 10 vertices, 15 edges, all degree 3, nonplanar",
  markers=[r"(?<!\d)10(?!\d)|十个",r"(?<!\d)15(?!\d)|十五",r"(?<!\d)3(?!\d)|三度",
           r"非平面|不是平面|不能.*平面|不可.*平面"]),
 dict(id="HKUST_POLY",institution="HKUST",country="China (Hong Kong)",origin="MATH4821B planar graph lecture Figure 3 three polyhedra, not exam",
  url="https://www.math.hkust.edu.hk/~mabfchen/Math4821B/Planar-Graphs.pdf",
  page=1,box=(.065,.025,.94,.213),
  question="请分别识别从左到右三张图，求各图的顶点数与边数；不要将图中线条交叉当作新顶点。",
  gold_note="Octahedron 6 vertices 12 edges; dodecahedron 20 vertices 30 edges; icosahedron 12 vertices 30 edges",
  markers=[r"八面体|Octahedron",r"十二面体|Dodecahedron",r"二十面体|Icosahedron"]),
 dict(id="INDIA_BITMESRA_ISO",institution="Birla Institute of Technology Mesra",country="India",origin="2018 IT3021 end-semester exam Q6(a), real paired graph drawings",
  url="https://bitmesra.ac.in/UploadedDocuments/adminexam/files/MO2018%20QP/IT3021-DISCRETE%20MATHEMATICS%20AND%20GRAPH%20THEORY%20%28END_MO2018%29.pdf",
  page=0,box=(.255,.71,.81,.845),
  question="只看第6(a)题两张图：分别写出顶点及边的数量，判断是否同构，并给出一一对应。右图两条对角线的交叉点没有实心点，不是顶点。",
  gold_note="Two drawings of K4; each has exactly 4 vertices and 6 edges, isomorphic",
  markers=[r"同构",r"(?<!\\d)4(?!\\d)|四个",r"(?<!\\d)6(?!\\d)|六条"]),
 dict(id="NJU_DIRECTED",institution="Nanjing University",country="China",origin="2019 Discrete Mathematics GraphPS3 Problem 1, actual directed figures",
  url="https://cs.nju.edu.cn/shiyh/DM2019/parts/GraphPS3.pdf",
  page=0,box=(.06,.025,.94,.72),
  question="判断原图第1题中的三幅有向图是否强连通；不强连通的再判断是否弱连通。逐图列出依据，不能忽略箭头方向。",
  gold_note="Figure 1 weakly but not strongly connected; 2 neither weak nor strong (separate components); 3 weakly but not strongly connected",
  markers=[r"强连通|强连接",r"弱连通|弱连接"]),
 dict(id="EDINBURGH_CLIQUES",institution="University of Edinburgh",country="UK",origin="2022 tutorial 2 solutions Exercise 2 Figure 1 undirected graphical model",
  url="https://www.inf.ed.ac.uk/teaching/courses/pmr/21-22/assets/tutorials/tutorial02-sol.pdf",
  page=1,box=(.075,.02,.93,.58),
  question="按图1求无向图的全部最大团（maximal cliques）。只给出顶点集合以及必要解释。",
  gold_note="Four maximal cliques {x1,x2,x4}, {x1,x3,x4}, {x3,x4,x5}, {x4,x5,x6}",
  markers=[r"x_?\{?1\}?",r"x_?\{?4\}?",r"x_?\{?6\}?"]),
]

UNCERTAIN=re.compile(r"图形结构待核对|需要.*核对|无法.*确定|无法.*准确识别|不能.*确定|识别.*不确定|图.*不清晰")
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--base",default=os.environ.get("DMATE_BENCH_URL","https://dmate.zeabur.app"))
    ap.add_argument("--output",default="curated_university_diagram_results.json")
    ap.add_argument("--delay",type=int,default=14)
    ap.add_argument("--timeout",type=int,default=110)
    ap.add_argument("--only",action="append",default=[])
    opts=ap.parse_args()
    session=requests.Session()
    out={"purpose":"real university graphs with verifiable topology, not synthetic",
         "started_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"cases":[]}
    dest=Path("curated_university_graph_samples")
    dest.mkdir(exist_ok=True)
    for c in CASES:
        if opts.only and c["id"] not in opts.only:continue
        row=dict(c)
        try:
            data=pdf_crop(session,c["url"],c["page"],c["box"])
            row["image_sha256"]=hashlib.sha256(data).hexdigest()
            (dest/(c["id"]+".png")).write_bytes(data)
            ocr_status,ocr=post_image(session,opts.base.rstrip("/"),data,opts.timeout)
            row["ocr_http"]=ocr_status
            row["ocr_text"]=str(ocr.get("text",""))
            row["visual_text"]=str(ocr.get("visual_text",""))
            row["review"]=ocr.get("review")
            row["warnings"]=ocr.get("warnings")
            row["graph_structures"]=ocr.get("graph_structures")
            row["ocr_error"]=ocr.get("error")
            if ocr_status!=200:
                row["verdict"]="OCR_HTTP_FAILURE"
            else:
                time.sleep(opts.delay)
                prompt=("【题目文字】\n"+row["ocr_text"]+
                        "\n【图形信息】\n"+row["visual_text"]+
                        "\n【我的要求】\n请直接给出最终答案并简要解释。"+c["question"])
                answer_status,ans=post_chat(session,opts.base.rstrip("/"),prompt,opts.timeout)
                reply=str(ans.get("reply",""))
                row["answer_http"]=answer_status
                row["answer"]=reply
                row["answer_error"]=ans.get("error")
                row["markers_present"]=[bool(re.search(m,reply,re.I|re.S)) for m in c["markers"]]
                if answer_status!=200:
                    row["verdict"]="ANSWER_HTTP_FAILURE"
                elif UNCERTAIN.search(reply) or "【图形结构待核对】" in row["visual_text"]:
                    row["verdict"]="SAFE_UNCERTAIN_REVIEW"
                elif all(row["markers_present"]):
                    row["verdict"]="GOLD_TOKENS_PRESENT_NEEDS_EDGE_REVIEW"
                else:
                    row["verdict"]="ANSWER_SUSPECT_REVIEW"
                if c["id"]=="INDIA_BITMESRA_ISO" and answer_status==200:
                    if re.search(r"不同构|非同构|不是同构",reply):
                        row["verdict"]="CONFIRMED_WRONG_ISOMORPHISM"
                    # A claim of an extra node at an unlabeled crossing is wrong.
                    if re.search(r"(?:5|五)\\s*(?:个)?\\s*顶点|(?:顶点|节点).*?(?:5|五)\\s*个",reply):
                        row["verdict"]="CONFIRMED_WRONG_GRAPH_VERTEX_COUNT"
                if c["id"]=="MIT05_P3" and answer_status==200:
                    # Automated check: do not mark wrong just for differing wording.
                    row["known_graph_gold"]=c["visual_gold"]
                    if (re.search(r"(?:直径|diameter).{0,12}(?:为|是|=|：|:)\s*\$?\s*[46789]\b",reply,re.I)
                      or re.search(r"(?:色数|chromatic number).{0,12}(?:为|是|=|：|:)\s*\$?\s*[2456789]\b",reply,re.I)):
                        row["verdict"]="CONFIRMED_WRONG_NUMERIC_CLAIM"
        except Exception as exc:
            row["verdict"]="SOURCE_OR_RUNTIME_FAILURE"
            row["exception"]=repr(exc)
        print("CURATED_IMAGE",row["id"],row["verdict"],row.get("ocr_http"),row.get("answer_http"),flush=True)
        out["cases"].append(row)
        Path(opts.output).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
        time.sleep(opts.delay)
    out["completed_at"]=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())
    Path(opts.output).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    counts={v:sum(c["verdict"]==v for c in out["cases"])
            for v in sorted({c["verdict"] for c in out["cases"]})}
    print("CURATED_COUNTS",json.dumps(counts,ensure_ascii=False),flush=True)
    failures=[r["id"] for r in out["cases"] if r["verdict"] in
             ("OCR_HTTP_FAILURE","ANSWER_HTTP_FAILURE","SOURCE_OR_RUNTIME_FAILURE",
              "CONFIRMED_WRONG_NUMERIC_CLAIM","CONFIRMED_WRONG_ISOMORPHISM","CONFIRMED_WRONG_GRAPH_VERTEX_COUNT","ANSWER_SUSPECT_REVIEW")]
    print("CURATED_FAILURES",failures,flush=True)
    return 1 if failures else 0
if __name__=="__main__":
    raise SystemExit(main())
