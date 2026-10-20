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
  "page":1,"box":[.11,.17,.90,.40],"topic":"crossing-edge graph isomorphism",
  "gold":"ISOMORPHIC"},
 {"id":"US_CORNELL_DFA","country":"美国","institution":"Cornell University",
  "type":"original final exam","url":"https://www.cs.cornell.edu/courses/cs2800/2016fa/handouts/2800final-16sp.pdf",
  "page":1,"box":[.16,.50,.86,.69],"topic":"directed state-transition graph"},
 {"id":"CN_NJU_GRAPH","country":"中国","institution":"Nanjing University",
  "type":"original graph-theory homework","url":"https://cs.nju.edu.cn/_upload/tpl/01/53/339/template339/DM2019/parts/GraphPS1.pdf",
  "page":0,"box":[.04,.03,.96,.96],"topic":"graph degree sequences and graph theory"},
 {"id":"IN_UTU_GRAPH","country":"印度","institution":"Uka Tarsadia University",
  "type":"university question bank","url":"https://www.utu.ac.in/DMathematics/download/2017-18/Documents/Sem5/QB_060090503.pdf",
  "page":0,"box":[.04,.03,.96,.96],"topic":"diagrammed graph subgraph/isomorphism"},
 {"id":"IN_ANNA_EXAM","country":"印度","institution":"Anna University exam paper hosted by JIT",
  "type":"original university question paper","url":"https://jit.ac.in/files/coe/University_Question_Papers/00_S%26H/R2021/Sem_03/MA3354/MA3354%20-%20Discrete%20Mathematics_R2021%20-%202023%20Nov.pdf",
  "page":0,"box":[.03,.03,.97,.97],"topic":"discrete math graph exam"},
 {"id":"US_MIT_GRAPH","country":"美国","institution":"Massachusetts Institute of Technology",
  "type":"graph-theory problem set","url":"https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/resources/ps4/",
  "page":0,"box":[.03,.03,.97,.97],"topic":"graph theory problem set"},
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
            # MIT OCW resource page is not PDF; resolve link via HTML.
            if "ocw.mit.edu" in url and not url.endswith(".pdf"):
                html=session.get(url,timeout=45)
                html.raise_for_status()
                links=re.findall(r'href="([^"]+\.pdf(?:\?[^"]*)?)"',html.text,re.I)
                if not links:
                    raise ValueError("No direct PDF found in MIT resource page")
                from urllib.parse import urljoin
                url=urljoin(url,links[0].replace("&amp;","&"))
                row["resolved_pdf"]=url
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
