#!/usr/bin/env python3
"""Global original university graph-PDF image OCR benchmark.

Real unmodified public university PDFs, page crops stored as evidence.
A request succeeding is NOT graph-topology accuracy. For Cornell Q10 we have
independently checked 9-edge graph-isomorphism gold. All other original page
samples require manual verification before accuracy can be reported.
"""
import argparse, json, time, re, hashlib
from pathlib import Path
import requests
from university_discrete_benchmark import pdf_crop, post_image, post_chat

SOURCES=[
 {"id":"US_CORNELL_ISO","country":"美国","institution":"Cornell University",
  "type":"original final exam","url":"https://www.cs.cornell.edu/courses/cs2800/2016fa/handouts/2800final-16sp.pdf",
  "page":1,"box":[.11,.177,.90,.372],"topic":"crossing-edge graph isomorphism",
  "gold":"ISOMORPHIC"},
 {"id":"US_CORNELL_DFA","country":"美国","institution":"Cornell University",
  "type":"original final exam","url":"https://www.cs.cornell.edu/courses/cs2800/2016fa/handouts/2800final-16sp.pdf",
  "page":1,"box":[.16,.50,.86,.69],"topic":"directed state-transition graph"},
 {"id":"CN_NJU_DIRECTED","country":"中国","institution":"Nanjing University",
  "type":"2019 original directed graph homework","url":"https://cs.nju.edu.cn/shiyh/DM2019/parts/GraphPS3.pdf",
  "page":0,"box":[.06,.025,.94,.72],"topic":"original three arrow diagrams strong/weak connectivity"},
 {"id":"IN_BITMESRA_K4","country":"印度","institution":"Birla Institute of Technology Mesra",
  "type":"2018 original end-semester exam Q6a","url":"https://bitmesra.ac.in/UploadedDocuments/adminexam/files/MO2018%20QP/IT3021-DISCRETE%20MATHEMATICS%20AND%20GRAPH%20THEORY%20%28END_MO2018%29.pdf",
  "page":0,"box":[.255,.71,.81,.845],"topic":"two K4 drawings graph isomorphism with crossing"},
 {"id":"US_MIT_GRAPH","country":"美国","institution":"Massachusetts Institute of Technology",
  "type":"2005 6.042J original graph problem-set 4 Q3","url":"https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/587366ef0ee07f57ed41715559224224_ps4.pdf",
  "page":1,"box":[.19,.065,.82,.29],"topic":"eight-vertex crossed-edges graph diameter and chromatic number"},
]
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base",default="https://dmate.zeabur.app")
    p.add_argument("--timeout",type=int,default=110)
    p.add_argument("--delay",type=int,default=12)
    p.add_argument("--limit",type=int,default=0)
    p.add_argument("--output",default="global_graph_image_results.json")
    a=p.parse_args()
    session=requests.Session()
    out={"cases":[],"source_note":"public university PDF pages; no claims about visual accuracy without manual graph-edge audit"}
    sample_dir=Path("global_graph_image_samples");sample_dir.mkdir(exist_ok=True)
    selected=SOURCES[:a.limit] if a.limit else SOURCES
    for i,case in enumerate(selected):
        row=dict(case)
        try:
            url=row["url"]
            # Every source above is a vetted direct PDF URL, not an HTML listing.
            raw=pdf_crop(session,url,row["page"],row["box"])
            row["sha256"]=hashlib.sha256(raw).hexdigest()
            (sample_dir/(row["id"]+".png")).write_bytes(raw)
            status,result=post_image(session,a.base.rstrip("/"),raw,a.timeout)
            row["ocr_http"]=status
            row["ocr_text"]=str(result.get("text",""))
            row["visual_text"]=str(result.get("visual_text",""))
            row["graph_structures"]=result.get("graph_structures")
            row["review"]=result.get("review")
            row["error"]=result.get("error")
            row["verdict"]="OCR_RETURNED_NEEDS_GRAPH_EDGE_AUDIT" if status==200 else "OCR_HTTP_FAILURE"
            if status==200 and row.get("gold")=="ISOMORPHIC":
                # An answer without a validated edge set is never a proof.
                time.sleep(a.delay)
                q=("这是 Cornell 大学期末考试图同构原题的OCR结果，请严格按图形邻接关系"
                   "判定两个图是否同构。无法确定每条边时应明确说无法确定，不能猜测。\n"
                   +row["ocr_text"]+"\n"+row["visual_text"])
                chat_status,reply=post_chat(session,a.base.rstrip("/"),q,a.timeout)
                row["chat_http"]=chat_status
                row["chat_reply"]=str(reply.get("reply",""))
                if chat_status!=200:
                    row["verdict"]="ANSWER_HTTP_FAILURE"
                elif re.search(r"不同构|非同构|不是同构",row["chat_reply"]):
                    row["verdict"]="CONFIRMED_WRONG_ANSWER"
                elif re.search(r"同构",row["chat_reply"]):
                    row["verdict"]="ANSWER_MAY_BE_CORRECT_NEEDS_EDGE_AUDIT"
                else:
                    row["verdict"]="ANSWER_UNCERTAIN_NEEDS_REVIEW"
        except Exception as exc:
            row["verdict"]="SOURCE_OR_TEST_FAILURE"
            row["exception"]=repr(exc)
        out["cases"].append(row)
        print("GRAPH_IMAGE",row["id"],row["verdict"],row.get("ocr_http"),flush=True)
        if i+1<len(selected):time.sleep(a.delay)
    out["finished_utc"]=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())
    Path(a.output).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    failed=[r["id"] for r in out["cases"] if r["verdict"] in
            ("CONFIRMED_WRONG_ANSWER","SOURCE_OR_TEST_FAILURE","OCR_HTTP_FAILURE","ANSWER_HTTP_FAILURE")]
    print("GLOBAL_GRAPH_FAILURES",failed,flush=True)
    if failed:return 1
    return 0
if __name__=="__main__":
    raise SystemExit(main())
