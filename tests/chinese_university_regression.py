#!/usr/bin/env python3
"""Real Chinese-university discrete mathematics questions + eight missed cases.

Source type is explicit: SJTU graded homework/solutions; NJU real homework;
the earlier X03-X10 are independent university-style instances (not claimed
to be verbatim historical finals). Runs deployed DMate over HTTPS, no mock API.

A regex gold oracle is a NECESSARY ANSWER CHECK, not mathematical proof grading.
Keep all replies for human checking. HTTP 429 is an infrastructure failure,
not a wrong mathematical answer. Never give false confidence via a green CI.
"""
import argparse
import io
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

from university_discrete_benchmark import EXTRA_CASES, post_chat

SJTU = "https://basics.sjtu.edu.cn/~yangqizhe/pdf/dm2024w/homework/DM-hw8sol.pdf"
NJU_GRAPH = "https://cs.nju.edu.cn/_upload/tpl/01/53/339/template339/DM2019/parts/GraphPS1.pdf"
NJU_LOGIC = "https://cs.nju.edu.cn/yuanyao/course/dismath/hw1.pdf"
NJU_SET = "https://cs.nju.edu.cn/yuanyao/course/dismath/hw2.pdf"

# source_id, school, module, question, expected regexes, PDF, original question
# Exact question-derived statements, with a few subquestions isolated from
# multi-part problems. A successful numeric token check is NOT proof correctness.
CHINESE_CASES = [
 ("SJ01","上海交通大学","关系合成","已知关系 R={(1,1),(1,2),(1,3),(2,2),(2,3),(3,4)}，(2,4)是否属于 R∘R？请先写是/否并说明。",[r"(?<!不)属于|包含|存在.*2.*3.*4|答案.{0,8}是|结论.{0,8}是"],SJTU,"第2题"),
 ("SJ02","上海交通大学","逆关系","R={(1,1),(1,2),(1,3),(2,2),(2,3),(3,4)}，其逆关系 R^(-1) 是否包含 (4,3)？说明。",[r"\(4\s*,\s*3\)|（4\s*[,，]\s*3）"],SJTU,"第2题"),
 ("SJ03","上海交通大学","关系性质","A={1,2,3,4}，R={(1,3),(1,4),(2,3),(3,4)}。R 是否为反对称关系？简要解释。",[r"反对称|antisymmetric"],SJTU,"第3题"),
 ("SJ04","上海交通大学","传递闭包","A={1,2,3,4}，R={(1,3),(1,4),(2,3),(3,4)}，求传递闭包中新增加而原关系没有的有序对。",[r"\(2\s*,\s*4\)|（2\s*[,，]\s*4）"],SJTU,"第3题"),
 ("SJ05","上海交通大学","自反闭包","A={1,2,3,4}，R={(1,3),(1,4),(2,3),(3,4)}，R 的自反闭包共有多少个有序对？",[r"(?<!\d)8(?!\d)|八个"],SJTU,"第3题"),
 ("SJ06","上海交通大学","等价关系","在 A={1,2,3} 上定义 xRy 当且仅当 x+y ≠ 3。它是不是等价关系？请给出反例。",[r"不是等价|非等价|不满足传递|传递性不成立|不具传递"],SJTU,"第5题(1)"),
 ("SJ07","上海交通大学","偏序与对称性","集合 S 至少含3个元素。在幂集P(S)上定义 XRY 当且仅当 X⊆Y。这是不是等价关系？指出不满足的性质。",[r"不是等价|非等价|不对称|不是对称|不满足对称"],SJTU,"第5题(2)"),
 ("SJ08","上海交通大学","可比关系","集合S至少含3个元素。在P(S)上定义 XRY 当且仅当 X⊆Y 或 Y⊆X。这是不是等价关系？说明反例。",[r"不是等价|非等价|不传递|不是传递|不满足传递"],SJTU,"第5题(3)"),
 ("NJG01","南京大学","握手定理","5名同学，每人恰好认识另外3人。如果认识必须相互，能否用无向简单图表示？说明。",[r"不能|不可能|不存在|无法",r"奇数|15|握手"],NJU_GRAPH,"Problem 1(b)"),
 ("NJG02","南京大学","度数定理","判断：至少两个顶点的无向简单图能使所有顶点的度数各不相同吗？证明或反驳。",[r"不可能|不能|不存在|无法|不成立"],NJU_GRAPH,"Problem 2"),
 ("NJG03","南京大学","完全图","求K5的顶点度序列（非递增）。",[r"4.{0,8}4.{0,8}4.{0,8}4.{0,8}4"],NJU_GRAPH,"Problem 3(a)"),
 ("NJG04","南京大学","环图","求C3的度序列。",[r"2.{0,8}2.{0,8}2"],NJU_GRAPH,"Problem 3(b)"),
 ("NJG05","南京大学","完全二部图","求K_{2,3}的度序列（非递增）。",[r"3.{0,8}3.{0,8}2.{0,8}2.{0,8}2"],NJU_GRAPH,"Problem 3(d)"),
 ("NJG06","南京大学","超立方体图","三维超立方体Q3有几个顶点？每个顶点度数是多少？",[r"(?<!\d)8(?!\d)|八个",r"(?<!\d)3(?!\d)|三"],NJU_GRAPH,"Problem 3(e)"),
 ("NJG07","南京大学","图序列判定","判断度序列(5,4,3,2,1,0)能否对应某个无向简单图，并简要证明。",[r"不可能|不能|不存在|不合法|非图序列|不可实现"],NJU_GRAPH,"Problem 4(a)"),
 ("NJG08","南京大学","图序列判定","度序列(2,2,2,2,2)能否由无向简单图实现？给出一个例子。",[r"可以|能|存在|可实现",r"5|五|C_?\{?5\}?"],NJU_GRAPH,"Problem 4(b)"),
 ("NJG09","南京大学","图序列判定","度序列(5,3,3,3,3,3)能否由6个顶点的简单图实现？给出构造或反证。",[r"可以|能|存在|可实现",r"环|五边形|C_?\{?5\}?"],NJU_GRAPH,"Problem 4(d)"),
 ("NJG10","南京大学","图序列判定","度序列(5,4,2,1,1,1)能否由6个顶点的无向简单图实现？",[r"不能|不可能|不可实现|不合法|不存在"],NJU_GRAPH,"Problem 4(c)"),
 ("NJL01","南京大学","命题逻辑等价","判断 (p→r)∨(q→r) 与 (p∧q)→r 是否逻辑等价，并说明。",[r"等价|恒等"],NJU_LOGIC,"第3题"),
 ("NJL02","南京大学","命题逻辑","命题p表示下雨，q表示带伞。将‘只有下雨我才带伞’符号化。",[r"q\s*\\?to\s*p|q\s*→\s*p|q\s*⇒\s*p|q\s*\\?Rightarrow\s*p"],NJU_LOGIC,"第2题(4)"),
 ("NJL03","南京大学","命题逻辑与计数","A、B、C、D中选2人出差。若A去，则C和D中至少去1人；B和C不能同时去；C去则D不去。共有多少种符合条件的选派？",[r"(?<!\d)3(?!\d)|三种|3种"],NJU_LOGIC,"第8题"),
 ("NJL04","南京大学","集合计数","有限集合A,B满足|A|=5, |P(B)|=512, |P(A△B)|=1024。求|A∩B|。",[r"(?<!\d)2(?!\d)|两个"],NJU_SET,"第6题"),
 ("NJL05","南京大学","集合计数","有限集合A,B满足|A|=5, |P(B)|=512, |P(A△B)|=1024。求|A∪B|。",[r"(?<!\d)12(?!\d)|十二"],NJU_SET,"第6题"),
 ("NJL06","南京大学","等价关系","整数集Z上定义aRb当且仅当5整除(a-b)。商集Z/R有多少个不同的等价类？",[r"(?<!\d)5(?!\d)|五个"],NJU_SET,"第8题"),
 ("NJL07","南京大学","函数单射满射","实数到实数的函数f(x)=x²是否双射？给出理由。",[r"不是双射|非双射|不为双射|不是单射|不是满射"],NJU_SET,"第9题(3)"),
 ("NJL08","南京大学","函数单射满射","实数到实数的函数 f(x)=2x+1 是否双射？",[r"是双射|为双射|双射函数|既是单射又是满射"],NJU_SET,"第9题(1)"),
 ("NJL09","南京大学","函数单射满射","实数到实数的函数 f(x)=x³ 是否双射？",[r"是双射|为双射|双射函数|既是单射又是满射"],NJU_SET,"第9题(2)"),
 ("NJL10","南京大学","函数单射满射","实数到实数的函数 f(x)=x²/(1+x²) 是否是满射？给出值域。",[r"不是满射|不满射|非满射|不为满射",r"0|\\[0"],NJU_SET,"第9题(4)"),
]

# Stable machine-readable gold examples; human review remains necessary
# for formal proofs and whether explanations introduce false claims.

USTC = "https://faculty.ustc.edu.cn/_resources/group1/M00/00/47/wKhJFGT1pGSAfHlvAE0oo3Ug_0I994.pdf"
# USTC course slides include the *examples* (not historical finals). The
# propositions and numerical answers have independently verified gold facts.
USTC_CASES = [
 ("UST01","中国科学技术大学","嵌套量词","论域是所有实数，Q(x,y)表示x+y=0。命题∃y∀x Q(x,y)是真还是假？解释原因。",[r"假|不成立|为假|false|错误"],USTC,"课程讲义第112页"),
 ("UST02","中国科学技术大学","嵌套量词","论域是所有实数，Q(x,y)表示x+y=0。命题∀x∃y Q(x,y)是真还是假？给出y的取法。",[r"真|成立|为真|true|正确",r"[-−]x|负x|相反数"],USTC,"课程讲义第112页"),
 ("UST03","中国科学技术大学","模运算证明","证明：如果整数n不能被2或3整除，则n²−1能被24整除。",[r"24|二十四"],USTC,"课程讲义第146页"),
 ("UST04","中国科学技术大学","模运算反证","证明整数方程x²+3y²=8没有整数解，给出一个模3的理由。",[r"模.?3|mod\s*3|余数|平方",r"无整数解|不存在整数解|不可能|无解"],USTC,"课程讲义第146页"),
 ("UST05","中国科学技术大学","立方数分解","给出整数1729的两组不同的正整数立方和表示（列出四个底数）。",[r"(?<!\d)1(?!\d)|1\^3|1³",r"(?<!\d)12(?!\d)|12\^3|12³",r"(?<!\d)9(?!\d)|9\^3|9³",r"(?<!\d)10(?!\d)|10\^3|10³"],USTC,"课程讲义第148页"),
 ("UST06","中国科学技术大学","反例构造","多项式f(n)=n²−n+41是否对每个正整数n都产生素数？请给出一个反例n。",[r"(?<!\d)41(?!\d)|n\s*=\s*41",r"合数|不是素数|不总是|反例"],USTC,"课程讲义第154页"),
 ("UST07","中国科学技术大学","棋盘染色","标准8×8国际象棋棋盘去掉两个对角的角格后，能否用31块1×2骨牌完全铺满？给出染色理由。",[r"不能|不可能|无法|铺不满|不可",r"黑|白|颜色|染色"],USTC,"课程讲义第153页"),
]

def heuristic_valid(reply, patterns):
    return bool(reply.strip()) and all(re.search(p, reply, re.I|re.S) for p in patterns)


def call_with_retry(sess, base, question, timeout, pause, attempts=3):
    for idx in range(attempts):
        try:
            status, body=post_chat(sess,base,question,timeout)
            if status in (429, 502, 503, 504) and idx+1<attempts:
                wait = max(20, pause*3)*(idx+1)
                print("WAIT_TRANSIENT", status, wait, flush=True)
                time.sleep(wait)
                continue
            return status, body
        except (requests.Timeout, requests.ConnectionError) as exc:
            if idx+1 == attempts: raise
            wait = max(20,pause*3)*(idx+1)
            print("WAIT_NETWORK",type(exc).__name__,wait,flush=True)
            time.sleep(wait)
    raise RuntimeError("no HTTP response")


def image_examples():
    # Crops of original university worksheets, containing questions (not solutions).
    # Bounding boxes are fractions [left, top, right, bottom] of the PDF page.
    return [
      {"id":"CNIMG01","school":"南京大学","source":NJU_GRAPH,
       "page":0,"crop":(.08,.48,.92,.72),"expected_tokens":["证明","简单图"],
       "description":"GraphPS1 Problem 2: graph degree proof",
       "solve_request":"只回答图中Problem2的真假，并给出证明，不要回答其他问题。",
       "answer_tokens":[r"成立|正确|真命题|不可能|不能存在"]},
      {"id":"CNIMG02","school":"南京大学","source":NJU_LOGIC,
       "page":1,"crop":(.12,.06,.93,.27),"expected_tokens":["命题","等价"],
       "description":"HW1 Problem 3: propositional equivalence",
       "solve_request":"只解Problem3，判断两个公式是否逻辑等价并证明。",
       "answer_tokens":[r"逻辑等价|是等价|等价的|等值"]},
      {"id":"CNIMG03","school":"南京大学","source":NJU_SET,
       "page":2,"crop":(.10,.48,.94,.85),"expected_tokens":["512","1024"],
       "description":"HW2 Problem 6: powerset symmetric difference",
       "solve_request":"只解第6题：求 |A∩B|，给出最终数值并说明计算依据。",
       "answer_tokens":[r"(?<!\d)2(?!\d)|两个"]},
    ]


def extract_image(sess, obj):
    import pymupdf
    from PIL import Image
    url=obj["source"]
    reply=sess.get(url,timeout=40)
    reply.raise_for_status()
    pdf=pymupdf.open(stream=reply.content,filetype="pdf")
    page=pdf[obj["page"]]
    pix=page.get_pixmap(matrix=pymupdf.Matrix(2,2),alpha=False)
    image=Image.frombytes("RGB",(pix.width,pix.height),pix.samples)
    x1,y1,x2,y2=obj["crop"]
    cut=image.crop((int(x1*pix.width),int(y1*pix.height),
                    int(x2*pix.width),int(y2*pix.height)))
    out=io.BytesIO()
    cut.save(out,format="PNG")
    return out.getvalue()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--url",default=os.getenv("DMATE_BENCH_URL","https://dmate.zeabur.app"))
    parser.add_argument("--output",default="chinese_university_results.json")
    parser.add_argument("--delay",type=float,default=7.0)
    parser.add_argument("--timeout",type=float,default=70)
    parser.add_argument("--slice",default="all",help="all, missed8, or chinese")
    parser.add_argument("--limit",type=int,default=0)
    parser.add_argument("--images",action="store_true")
    parser.add_argument("--images-only",action="store_true")
    parser.add_argument("--start-index",type=int,default=0)
    parser.add_argument("--require-current",action="store_true")
    parser.add_argument("--strict",action="store_true")
    args=parser.parse_args()
    sess=requests.Session()
    base=args.url.rstrip("/")
    output={"target":base,"started_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
            "version_check":None,"text":[],"images":[]}
    try:
        h=sess.get(base+"/health",timeout=12)
        health=h.json()
        output["version_check"]=health
        if args.require_current and not health.get("graph_integrity_version"):
            print("DEPLOYMENT_VERSION_NOT_VERIFIED",health,flush=True)
            Path(args.output).write_text(json.dumps(output,indent=2,ensure_ascii=False),encoding="utf-8")
            return 2
    except Exception as exc:
        output["version_check"]={"error":repr(exc)}
        if args.require_current:
            return 2
    old=[
        (id,school,topic,prompt,checks,source,"Follow-up X03-X10")
        for id,school,topic,prompt,checks,source in EXTRA_CASES if id in
        ("X03","X04","X05","X06","X07","X08","X09","X10")
    ]
    chinese=[(*case[:6],case[6]) for case in CHINESE_CASES]
    selected=(old if args.slice=="missed8" else
              [(*case[:6],case[6]) for case in USTC_CASES] if args.slice=="ustc" else
              chinese if args.slice=="chinese" else old+chinese)
    if args.images_only:
        selected=[]
    else:
        selected=selected[args.start_index:]
    if args.limit:
        selected=selected[:args.limit]
    for i,(id,school,topic,prompt,checks,source,original_id) in enumerate(selected):
        try:
            status,result=call_with_retry(sess,base,prompt,args.timeout,args.delay)
            answer=str(result.get("reply",""))
            outcome=("TOKEN_MATCH_PROOF_REVIEW" if status==200 and heuristic_valid(answer,checks)
                     else "SUSPECT" if status==200 and answer.strip()
                     else "HTTP_FAILURE")
            row={"id":id,"school":school,"module":topic,"source":source,
                 "original_question":original_id,"prompt":prompt,"status":status,
                 "verdict":outcome,"gold_markers":checks,"answer":answer,
                 "error":result.get("error")}
        except Exception as exc:
            row={"id":id,"school":school,"module":topic,"verdict":"HTTP_FAILURE",
                 "error":repr(exc)}
        output["text"].append(row)
        print("CASE",id,row["verdict"],row.get("status",""),flush=True)
        # Separate calls to respect real production rate limiting.
        if i+1<len(selected):time.sleep(args.delay)
    if args.images:
        for example in image_examples():
            row=dict(example)
            try:
                raw=extract_image(sess,example)
                import hashlib
                row["image_sha256"]=hashlib.sha256(raw).hexdigest()
                saved=Path("chinese_university_ocr_samples")
                saved.mkdir(exist_ok=True)
                (saved/(example["id"]+".png")).write_bytes(raw)
                response=sess.post(base+"/ocr",files={"image":(example["id"]+".png",raw,"image/png")},
                                   timeout=args.timeout+45)
                data=response.json()
                text=str(data.get("text",""))
                visual=str(data.get("visual_text",""))
                row.update({"status":response.status_code,"text":text,
                            "visual_text":visual,
                            "review":data.get("review"),
                            "warning":data.get("warning"),"error":data.get("error"),
                            "vision_used":data.get("vision_used"),
                            "tokens_present":{token:token in (text+visual)
                                              for token in example["expected_tokens"]}})
                row["verdict"]=("OCR_TOKENS_MATCH_NEEDS_REVIEW"
                                if response.status_code==200 and all(row["tokens_present"].values())
                                else "OCR_SUSPECT_OR_FAILED")
                if row["verdict"]=="OCR_TOKENS_MATCH_NEEDS_REVIEW":
                    # A separate end-to-end answer call uses exactly what the OCR
                    # returned, rather than a manually corrected question.
                    question=("【题目文字】\n"+text+"\n【图形信息】\n"+visual+
                              "\n【我的要求】\n"+example["solve_request"])
                    try:
                        chat_status,chat_body=call_with_retry(
                            sess,base,question,args.timeout,args.delay)
                        answer=str(chat_body.get("reply",""))
                        row["answer_status"]=chat_status
                        row["answer"]=answer
                        row["solution_verdict"]=(
                            "ANSWER_MARKER_MATCH_NEEDS_PROOF_REVIEW"
                            if chat_status==200 and heuristic_valid(answer,example["answer_tokens"])
                            else "ANSWER_SUSPECT" if chat_status==200 and answer.strip()
                            else "ANSWER_REQUEST_FAILED")
                    except Exception as exc:
                        row["solution_verdict"]="ANSWER_REQUEST_FAILED"
                        row["answer_error"]=repr(exc)
                else:
                    row["solution_verdict"]="NOT_TESTED_OCR_NOT_CONFIRMED"
            except Exception as exc:
                row["verdict"]="OCR_SUSPECT_OR_FAILED"
                row["error"]=repr(exc)
            output["images"].append(row)
            print("IMAGE",row["id"],row["verdict"],row.get("status",""),flush=True)
            time.sleep(args.delay)
    output["finished_at"]=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())
    Path(args.output).write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")
    summary={kind:sum(x["verdict"]==kind for x in output["text"]+output["images"])
             for kind in ("TOKEN_MATCH_PROOF_REVIEW","SUSPECT","HTTP_FAILURE",
                          "OCR_TOKENS_MATCH_NEEDS_REVIEW","OCR_SUSPECT_OR_FAILED")}
    print("FINAL_COUNTS",json.dumps(summary,ensure_ascii=False),flush=True)
    print("ARTIFACT",args.output,flush=True)
    image_answer_failures=[row["id"] for row in output["images"]
                           if row.get("solution_verdict") in ("ANSWER_SUSPECT","ANSWER_REQUEST_FAILED")]
    print("IMAGE_ANSWER_FAILURES",image_answer_failures,flush=True)
    if args.strict and (summary["SUSPECT"] or summary["HTTP_FAILURE"] or
                        summary["OCR_SUSPECT_OR_FAILED"] or image_answer_failures):
        return 1
    return 0


if __name__=="__main__":
    sys.exit(main())
