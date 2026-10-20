#!/usr/bin/env python3
"""Real, unchanged university graph-diagram OCR -> DMate solution benchmark.

Scope: original question DIAGRAMS from university-controlled URLs, not synthetic
graphs, and never include printed answer portions within image crops.
A matching answer is not a substitute for verifying OCR edge topology.
Separately compare an independently transcribed edge list where supplied.
Every failed HTTP, wrong answer, and unscorable interpretation is preserved.
"""
import argparse, hashlib, io, json, os, re, sys, time
from collections import Counter
from pathlib import Path

import requests

SJTU="https://basics.sjtu.edu.cn/~yangqizhe/pdf/dm2025w/homework/DM-homework-13-answer.pdf"
UNSW="https://www.coursearchive.unsw.edu.au/documents/science/MATH1081%20S1.pdf"
NUS="https://www.comp.nus.edu.sg/~cs1231s/tut/25s1/tut11qns.pdf"
AIZU="https://web-ext.u-aizu.ac.jp/~k-asai/classes/graph/g-graphth.pdf"
CORNELL="https://www.cs.cornell.edu/courses/cs2800/2016fa/handouts/2800final-16sp.pdf"
NJU="https://cs.nju.edu.cn/shiyh/DM2018/parts/h24.pdf"
# Canadian official mathematical enrichment exercises are visibly illustrated
# in source HTML; it is NOT a university exam.
WATERLOO="https://cemc.uwaterloo.ca/sites/default/files/documents/2024/Grade78_20220309_GraphTheory_ProblemSet.html"

# Every record must display exactly the relevant original diagram.
# PDF boxes are (left, top, right, bottom), relative to page size.
# Gold facts were checked against original rendered page, not Vision guesses.
CASES=[
 dict(id="CN_SJTU_EULER3",country="中国",uni="上海交通大学",kind="带参考解答的课程作业",
      url=SJTU,page=0,box=[.10,.202,.92,.437],
      ask='只根据图片中的三个图(a)(b)(c)判断哪些是欧拉图。第一行仅输出JSON：{"a":true或false,"b":true或false,"c":true或false}，下一行简要解释。',
      gold={"a":True,"b":False,"c":False},mode="boolean_map"),
 dict(id="CN_NJU_EULER3",country="中国",uni="南京大学",kind="正式课程作业",
      url=NJU,page=0,box=[.09,.13,.91,.53],
      ask='根据图中三个图(1)(2)(3)，哪些图有欧拉回路？请逐图说明理由。',
      gold=None,mode="manual_review"),
 dict(id="AU_UNSW_SIMPLE5",country="澳大利亚",uni="新南威尔士大学",kind="课程练习",
      url=UNSW,page=41,box=[.10,.07,.93,.30],
      ask='判断图中的G1至G5哪些是简单图。第一行仅输出JSON：{"G1":true或false,"G2":true或false,"G3":true或false,"G4":true或false,"G5":true或false}，下一行说明自环、平行边或交叉点的影响。',
      gold=None,mode="manual_review"), # do not falsely assert ambiguously drawn curves
 dict(id="AU_UNSW_STAR4",country="澳大利亚",uni="新南威尔士大学",kind="课程练习",
      url=UNSW,page=41,box=[.29,.675,.77,.83],
      ask="图中的无向简单图 G 一共有多少个顶点、多少条边、多少棵生成树？分别给出三个数值。",
      gold={"vertices":4,"edges":3,"spanning_trees":1},mode="numeric_map"),
 dict(id="AU_UNSW_BIP_A",country="澳大利亚",uni="新南威尔士大学",kind="课程练习",
      url=UNSW,page=42,box=[.085,.13,.49,.31],
      ask='图a（顶点A到H）是二部图吗？第一行仅输出JSON：{"result":true或false}，第二行说明是否有奇环。',
      gold=True,mode="boolean"),
 dict(id="AU_UNSW_BIP_B",country="澳大利亚",uni="新南威尔士大学",kind="课程练习",
      url=UNSW,page=42,box=[.47,.12,.94,.31],
      ask='图b是二部图吗？第一行仅输出JSON：{"result":true或false}，第二行简述奇环证据。',
      gold=False,mode="boolean"),
 dict(id="AU_UNSW_ISO_A",country="澳大利亚",uni="新南威尔士大学",kind="课程练习",
      url=UNSW,page=43,box=[.10,.515,.94,.722],
      ask='判断图15(a)的两张图G1、G2是否同构。第一行仅输出JSON：{"result":true或false}，然后给出一组顶点映射或反证。',
      gold=True,mode="boolean",
      # 依据原图手工逐边独立记录：
      canonical=("图1（左图）：无向图，顶点 a、b、c、d、e。边：a-b,a-d,a-c,b-e,d-e,d-c,c-e。"
                 "图2（右图）：无向图，顶点 x、y、z、t、u。边：x-y,y-z,z-u,u-t,t-x,x-z,y-t。")),
 dict(id="AU_UNSW_ISO_B",country="澳大利亚",uni="新南威尔士大学",kind="课程练习",
      url=UNSW,page=43,box=[.10,.718,.94,.902],
      ask='判断图15(b)的两张图G1、G2是否同构。第一行仅输出JSON：{"result":true或false}，然后证明。',
      gold=False,mode="boolean",
      canonical=("图1（左图）：无向图，顶点 a、b、c、d、e、f。边：a-b,b-e,b-c,b-d,e-d,d-c,c-f。"
                 "图2（右图）：无向图，顶点 x、y、z、t、u、v。边：x-y,y-z,y-t,z-t,t-u,z-v。")),
 dict(id="AU_UNSW_LOOP_EDGE",country="澳大利亚",uni="新南威尔士大学",kind="课程练习",
      url=UNSW,page=43,box=[.52,.155,.94,.34],
      ask='右侧这张有边标号的图中，是否存在自环？是否有孤立顶点？请分别指出顶点名称。',
      gold={"loop":"A","isolated":"E"},mode="named_vertices"),
 dict(id="JP_AIZU_ISO",country="日本",uni="会津大学",kind="图论教材练习",
      url=AIZU,page=1,box=[.375,.135,.635,.342],
      ask='图中的上下两幅带字母与数字顶点标号的无向图是否同构？第一行仅输出JSON：{"result":true或false}，并说明理由。',
      gold=True,mode="boolean"),
 dict(id="JP_AIZU_MULTIGRAPH",country="日本",uni="会津大学",kind="教材图形辨析",
      url=AIZU,page=1,box=[.635,.14,.925,.38],
      ask='右侧两幅图是否包含自环或重边？举例说明观察到的自环、重边。',
      gold=None,mode="manual_review"),
 dict(id="SG_NUS_SPANNING",country="新加坡",uni="新加坡国立大学",kind="课程练习（有官方解答）",
      url=NUS,page=1,box=[.12,.065,.91,.365],
      ask="根据原图 G，问有多少棵不同的生成树？只回答总数并说明推导依据。",
      gold=12,mode="numeric"),
 dict(id="SG_NUS_MST_EXAM",country="新加坡",uni="新加坡国立大学",kind="原期末考试题（教程收录）",
      url=NUS,page=2,box=[.11,.48,.91,.90],
      ask='原图为无向带权图。求最小生成树的总权重，以及非同构的最小生成树数量。第一行仅输出JSON：{"weight":整数,"count":整数}，后面说明。',
      gold={"weight":19,"count":5},mode="numeric_map"),
 dict(id="US_CORNELL_ISO",country="美国",uni="康奈尔大学",kind="原始期末考试试题",
      url=CORNELL,page=1,box=[.11,.17,.90,.4],
      ask='原图第10题中两张无向图是否同构？第一行仅输出JSON：{"result":true或false}，随后给出映射并对照实际边集。',
      gold=True,mode="boolean",
      canonical=("图1（左图）：无向图，顶点 a、b、c、d、e。"
                 "边：a-b,a-c,a-d,a-e,b-c,b-d,b-e,c-d,d-e。"
                 "图2（右图）：无向图，顶点 v、w、x、y、z。"
                 "边：v-w,v-x,v-y,v-z,w-y,w-z,x-y,x-z,y-z。")),
]

def fetch_pdf_image(sess,c,cache,scale=2.6):
    import pymupdf
    from PIL import Image
    link=c["url"]
    if link not in cache:
        res=sess.get(link,timeout=(14,90),
          headers={"User-Agent":"Mozilla/5.0 (compatible; DMate University Research)"})
        res.raise_for_status()
        if not res.content.startswith(b"%PDF"):
            raise ValueError("source is not a PDF; may be an access-denied HTML page")
        if len(res.content)>34_000_000:
            raise ValueError("oversize source")
        cache[link]=res.content
    pdf=pymupdf.open(stream=cache[link],filetype="pdf")
    if c["page"]>=len(pdf):raise ValueError("page index exceeds actual source PDF")
    pix=pdf[c["page"]].get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=False)
    img=Image.frombytes("RGB",[pix.width,pix.height],pix.samples)
    left,top,right,bottom=c["box"]
    crop=img.crop(tuple(round(v*size) for v,size in
                        zip((left,top,right,bottom),(pix.width,pix.height,pix.width,pix.height))))
    if crop.width<150 or crop.height<100:raise ValueError("tiny source crop")
    data=io.BytesIO()
    crop.save(data,format="PNG",optimize=True)
    return data.getvalue(),(crop.width,crop.height)


def as_json(response):
    try:return response.json()
    except Exception:return {"non_json":response.text[:1500]}


def call_ocr(sess,base,raw,id,timeout):
    resp=sess.post(base+"/ocr",files={"image":(id+".png",raw,"image/png")},
                  timeout=(10,timeout))
    return resp.status_code,as_json(resp)


def call_chat(sess,base,prompt,timeout):
    resp=sess.post(base+"/chat",json={"messages":[{"role":"user","content":prompt}]},
                   timeout=(10,timeout))
    return resp.status_code,as_json(resp)


def extract_object(text):
    text=str(text or "")
    # Look for the first JSON object, allowing code fences and natural language.
    for value in re.findall(r"\{[^\{\}\n]{0,400}\}",text):
        try:return json.loads(value.replace("True","true").replace("False","false"))
        except (TypeError,ValueError):pass
    return None


def bool_from_text(text):
    val=str(text or "")
    head=val[:700]
    # Distinguish negation, avoid treating "isomorphic" in a negative phrase
    # as proof of a positive answer. If both appear, abstain.
    no=bool(re.search(r"不同构|非同构|不是同构|非二部图|不是二部图|非偶图|不属于二部图|not\s+(?:a\s+)?(?:bipartite|isomorphic)|不满足二部|存在奇环",head,re.I))
    yes=bool(re.search(r"(?<!不)(?<!非)同构|是二部图|二分图|bipartite|isomorphic|不存在奇环|无奇环",head,re.I))
    return False if no and not yes else True if yes and not no else None


def score_answer(c,answer):
    """Scoring is strict; if uncertain, REVIEW instead of a fake PASS."""
    mode=c["mode"];gold=c["gold"]
    if mode=="manual_review":return "NEEDS_HUMAN_REVIEW",{}
    obj=extract_object(answer)
    if mode=="boolean":
        guess=obj.get("result") if isinstance(obj,dict) else None
        if not isinstance(guess,bool):guess=bool_from_text(answer)
        return ("ANSWER_MATCH_NEEDS_PROOF_REVIEW" if guess==gold else
                "ANSWER_WRONG" if isinstance(guess,bool) else "ANSWER_UNSCORABLE"),{"parsed":guess}
    if mode=="boolean_map":
        if not isinstance(obj,dict):return "ANSWER_UNSCORABLE",{"parsed":None}
        got={name:obj.get(name) for name in gold}
        if not all(isinstance(v,bool) for v in got.values()):
            return "ANSWER_UNSCORABLE",{"parsed":got}
        return ("ANSWER_MATCH_NEEDS_PROOF_REVIEW" if got==gold else "ANSWER_WRONG"),{"parsed":got}
    if mode=="numeric_map":
        if not isinstance(obj,dict):return "ANSWER_UNSCORABLE",{"parsed":None}
        got={name:obj.get(name) for name in gold}
        if not all(type(v) is int for v in got.values()):
            return "ANSWER_UNSCORABLE",{"parsed":got}
        return ("ANSWER_MATCH_NEEDS_PROOF_REVIEW" if got==gold else "ANSWER_WRONG"),{"parsed":got}
    if mode=="numeric":
        if not isinstance(gold,int):return "ANSWER_UNSCORABLE",{}
        relevant=answer[:900]
        # Numeric answer must explicitly include the correct number.
        # If there are several numbers and no final-result marker, abstain.
        nums=re.findall(r"(?<!\d)\d{1,7}(?!\d)",relevant)
        last_num=int(nums[-1]) if nums else None
        if last_num==gold:return "ANSWER_MATCH_NEEDS_PROOF_REVIEW",{"last_number":last_num}
        return "ANSWER_UNSCORABLE",{"last_number":last_num}
    if mode=="named_vertices":
        if all(re.search(r"\b"+re.escape(v)+r"\b",answer,re.I) for v in gold.values()):
            return "ANSWER_MATCH_NEEDS_PROOF_REVIEW",{"tokens":gold}
        return "ANSWER_UNSCORABLE",{"tokens":gold}
    return "NEEDS_HUMAN_REVIEW",{}


def post_slow(sess,base,kind,payload,id,timeout,retries=2):
    for attempt in range(retries+1):
        try:
            code,body=(call_ocr(sess,base,payload,id,timeout) if kind=="ocr"
                       else call_chat(sess,base,payload,timeout))
            if code in (429,502,503,504) and attempt<retries:
                delay=25*(attempt+1)
                print("RETRY",id,kind,code,delay,flush=True);time.sleep(delay);continue
            return code,body
        except requests.RequestException as err:
            if attempt==retries:raise
            print("RETRY_NET",id,kind,type(err).__name__,flush=True)
            time.sleep(25*(attempt+1))


def review_ocr(vision,c):
    if not vision or not isinstance(vision,dict):
        return "OCR_UNAVAILABLE"
    text=str(vision.get("text") or "")
    diagram=str(vision.get("visual_text") or "")
    structures=vision.get("graph_structures")
    # Presence of some graph-related text doesn't establish correct topology.
    if not text and not diagram:return "OCR_EMPTY"
    if c.get("canonical"):
        # Use graph's verified edge labels as audit target. The generic OCR's
        # prose is often partial; never assume absence = confirmed no-edge.
        try:
            from graph_integrity import parse_diagrams
            gold=parse_diagrams(c["canonical"])
            detected=parse_diagrams(diagram)
            if set(gold)==set(detected) and all(
                Counter(gold[k]["edges"])==Counter(detected[k]["edges"])
                and set(gold[k]["vertices"])==set(detected[k]["vertices"])
                for k in gold
            ):
                return "TOPOLOGY_MATCH_TEXT"
        except Exception:pass
        return "TOPOLOGY_NOT_VERIFIED"
    if structures:return "PARTIAL_MACHINE_GRAPH_AUDIT_AVAILABLE"
    return "TEXT_PRESENT_TOPOLOGY_NOT_VERIFIED"


def run_case(sess,base,c,cache,outdir,timeout,ocr_only=False):
    row={k:v for k,v in c.items() if k not in ("canonical",)}
    row["requested_at"]=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())
    try:
        raw,dims=fetch_pdf_image(sess,c,cache)
        Path(outdir).mkdir(exist_ok=True,parents=True)
        Path(outdir,c["id"]+".png").write_bytes(raw)
        row["image_sha256"]=hashlib.sha256(raw).hexdigest()
        row["image_resolution"]=dims
    except Exception as exc:
        row["status"]="SOURCE_FAILED"
        row["error"]=repr(exc)
        return row
    try:
        code,vision=post_slow(sess,base,"ocr",raw,c["id"],timeout)
        row["ocr_http"]=code
        row["ocr"]={k:vision.get(k) for k in
                     ("text","visual_text","graph_structures","review","warnings",
                      "vision_used","image_kind","error")}
        row["recognition_verdict"]=review_ocr(vision,c) if code==200 else "OCR_HTTP_FAILED"
        if code!=200 or not (vision.get("text") or vision.get("visual_text")):
            row["status"]="OCR_FAILED"
            return row
    except Exception as exc:
        row["status"]="OCR_FAILED"
        row["ocr_error"]=repr(exc)
        return row
    if ocr_only:
        row["status"]="OCR_ONLY"
        return row
    text=str(vision.get("text") or "")
    visual=str(vision.get("visual_text") or "")
    prompt=("【题目文字】\n"+text+"\n【图形信息】\n"+visual+
            "\n【我的要求】\n"+c["ask"])
    row["chat_input"]=prompt[:12000]
    try:
        code,answer=post_slow(sess,base,"chat",prompt,c["id"],timeout)
        row["chat_http"]=code
        row["answer"]=str(answer.get("reply") or "")
        row["chat_error"]=answer.get("error")
        if code!=200 or not row["answer"]:
            row["status"]="ANSWER_REQUEST_FAILED"
        else:
            row["status"],row["score_detail"]=score_answer(c,row["answer"])
    except Exception as exc:
        row["status"]="ANSWER_REQUEST_FAILED"
        row["chat_error"]=repr(exc)
    # Ground-truth transcription is a separate, independent input:
    # if it is wrong while the correctly-identified edges are supplied, this
    # is a reasoning error, independent of OCR.
    if c.get("canonical"):
        prompt_gt=("请直接给出最终答案并简要解释。"+
                   c["canonical"]+"\n【我的要求】\n"+c["ask"])
        try:
            code,result=post_slow(sess,base,"chat",prompt_gt,c["id"]+"_GOLD",timeout)
            row["gold_text_http"]=code
            row["gold_text_reply"]=str(result.get("reply") or "")
            row["gold_text_status"],row["gold_text_scoring"]=(score_answer(c,row["gold_text_reply"])
                              if code==200 and row["gold_text_reply"]
                              else ("GOLD_TEXT_REQUEST_FAILED",{}))
        except Exception as exc:
            row["gold_text_status"]="GOLD_TEXT_REQUEST_FAILED"
            row["gold_text_error"]=repr(exc)
    return row


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--base",default=os.getenv("DMATE_BENCH_URL","https://dmate.zeabur.app"))
    ap.add_argument("--output",default="global_graph_picture_results.json")
    ap.add_argument("--directory",default="global_graph_original_crops")
    ap.add_argument("--start",type=int,default=0)
    ap.add_argument("--count",type=int,default=0)
    ap.add_argument("--pause",type=int,default=6)
    ap.add_argument("--timeout",type=int,default=100)
    ap.add_argument("--ocr-only",action="store_true")
    ap.add_argument("--strict",action="store_true")
    args=ap.parse_args()
    cases=CASES[args.start:args.start+args.count if args.count else None]
    out={"started_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
         "source_type":"original university diagrams; raw PDF cropped without re-drawing",
         "target":args.base,"cases":[]}
    sess=requests.Session()
    cache={}
    try:
        response=sess.get(args.base.rstrip("/")+"/health",timeout=15)
        out["health"]=as_json(response)
    except Exception as err:
        out["health"]={"error":repr(err)}
    for idx,c in enumerate(cases):
        row=run_case(sess,args.base.rstrip("/"),c,cache,args.directory,args.timeout,args.ocr_only)
        out["cases"].append(row)
        Path(args.output).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
        print("CASE",row["id"],row["status"],"OCR",row.get("ocr_http"),"CHAT",row.get("chat_http"),
              "GOLD",row.get("gold_text_status"),"RECOGNITION",row.get("recognition_verdict"),flush=True)
        if idx+1<len(cases):time.sleep(args.pause)
    out["completed_at"]=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())
    counts=dict(Counter(row["status"] for row in out["cases"]))
    out["counts"]=counts
    Path(args.output).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    print("SUMMARY",counts,"COUNTRIES",list(dict.fromkeys(c["country"] for c in cases)),flush=True)
    if args.strict and any(row["status"] in ("SOURCE_FAILED","OCR_FAILED",
                       "ANSWER_WRONG","ANSWER_REQUEST_FAILED") or
                       row.get("gold_text_status")=="ANSWER_WRONG" for row in out["cases"]):
        return 1
    return 0


if __name__=="__main__":sys.exit(main())
