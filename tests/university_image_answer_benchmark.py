#!/usr/bin/env python3
"""Real exam PDF page crop -> DMate OCR -> DMate answer, compared separately.

OCR math tokens matching only means critical numerals match: text fidelity
and image interpretation still require a human review. The independently
transcribed official question is ALSO asked via chat, isolating reasoning bugs.
"""
import io,json,os,re,time,sys
from pathlib import Path
import requests
import fitz
from PIL import Image
from university_answer_benchmark import validate_bank,judge

PS7="https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/4791b8cd8b7a492119f5b67497490bcb_ps7.pdf"
EXAMS=[
    {"id":"MIT7-1b","page":0,"box":[.10,.33,.93,.50],"tokens":["20","6"],"section":"1b"},
    {"id":"MIT7-2a","page":0,"box":[.10,.63,.92,.70],"tokens":["BANANARAMA"],"section":"2a"},
    {"id":"MIT7-2d","page":0,"box":[.10,.72,.92,.96],"tokens":["100","8"],"section":"2d"},
    {"id":"MIT7-2g","page":1,"box":[.10,.16,.91,.38],"tokens":["15","0","1","2","3"],"section":"2g"},
    {"id":"MIT7-2h","page":1,"box":[.10,.36,.91,.59],"tokens":["300","3","5"],"section":"2h"}
]

def screenshot(doc,page,box):
    pix=doc[page].get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
    full=Image.frombytes("RGB",[pix.width,pix.height],pix.samples)
    x1,y1,x2,y2=box
    crop=full.crop((int(x1*full.width),int(y1*full.height),
                    int(x2*full.width),int(y2*full.height)))
    buf=io.BytesIO()
    crop.save(buf,format="PNG")
    return buf.getvalue()

def ask(session,base,prompt,timeout):
    r=session.post(base+"/chat",
        json={"messages":[{"role":"user","content":prompt}]},timeout=(10,timeout))
    try:d=r.json()
    except ValueError:d={}
    return r.status_code,str(d.get("reply","")),d.get("error")

def main():
    s=requests.Session()
    base=os.getenv("DMATE_BENCH_URL","https://dmate.zeabur.app").rstrip("/")
    path=Path("university_ocr_answer_results.json")
    bank={c["id"]:c for c in validate_bank()}
    report={"base":base,"started":time.time(),"cases":[],"source":PS7}
    pdf=s.get(PS7,timeout=60);pdf.raise_for_status()
    doc=fitz.open(stream=pdf.content,filetype="pdf")
    for row in EXAMS:
        c=bank[row["id"]]
        image=screenshot(doc,row["page"],row["box"])
        record={"id":row["id"],"gold_question":c["question"],
                "gold_oracle":c["oracle"],"crop":row["box"],"page":row["page"]}
        try:
            r=s.post(base+"/ocr",files={"image":("exam_question.png",image,"image/png")},
                     timeout=(10,95))
            try:payload=r.json()
            except ValueError:payload={}
            record["ocr_http"]=r.status_code
            record["ocr_text"]=str(payload.get("text",""))[:5500]
            record["ocr_graph"]=str(payload.get("visual_text",""))[:2500]
            record["ocr_review"]=payload.get("review")
            record["ocr_warning"]=payload.get("warning")
            record["ocr_error"]=payload.get("error")
            plain=re.sub(r"\s+","",record["ocr_text"]+"\n"+record["ocr_graph"]).lower()
            record["critical_token_checks"]={t:t.lower() in plain for t in row["tokens"]}
            record["ocr_critical_match"]=r.status_code==200 and all(record["critical_token_checks"].values())
            semantic=record["ocr_text"].lower()
            required={
                "MIT7-1b":("adjacent","相邻"),
                "MIT7-2d":("natural","nonnegative","自然数","非负"),
                "MIT7-2g":("15","fifteen"),
            }.get(row["id"])
            if required and not any(token in semantic for token in required):
                record["ocr_critical_match"]=False
                record["ocr_semantic_warning"]="关键计数条件没有完整识别，不能认定OCR正确"
            record["ocr_critical_match_note"]="数值及关键语义初筛，不等于经人工逐字核对"
            # Always test independently transcribed gold: this is the user's
            # priority case where recognition is known correct but solving fails.
            suffix="\n请直接给出最终答案及必要的完整推导，不要只给提示。末行只能写【结果】整数，不要在结果后写其他字符。"
            status,reply,error=ask(s,base,c["question"]+suffix,95)
            record["gold_text_http"]=status
            record["gold_text_reply"]=reply[:5000]
            record["gold_text_verdict"]=judge(c,reply)[0] if status==200 else "REQUEST_FAILED"
            record["gold_text_error"]=error
            if record["ocr_critical_match"] and not record.get("ocr_error"):
                # This is a distinct end-to-end image -> text -> answer path.
                # Do not claim OCR fully correct from partial critical tokens.
                parsed=(record["ocr_text"]+"\n"+record["ocr_graph"]).strip()
                selected={
                    "MIT7-1b":"只解Problem 1的(b)小问：选6本书不相邻的方案数。",
                    "MIT7-2a":"只解Problem 2的(a)小问：BANANARAMA字母排列数。",
                    "MIT7-2d":"只解Problem 2的(d)小问：8个非负整数变量和为100。",
                    "MIT7-2g":"只解Problem 2的(g)小问：15个位置选择0到3处。",
                    "MIT7-2h":"只解Problem 2的(h)小问：300天中至少被2、3、5之一整除。",
                }[row["id"]]
                status,reply,error=ask(s,base,parsed+"\n【我的要求】"+selected+suffix,95)
                record["image_answer_http"]=status
                record["image_answer_reply"]=reply[:5000]
                record["image_answer_verdict"]=judge(c,reply)[0] if status==200 else "REQUEST_FAILED"
                record["image_answer_error"]=error
        except Exception as e:record["error"]=repr(e)
        report["cases"].append(record)
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print("OCR_CASE",row["id"],"OCR",record.get("ocr_http"),
              "TOKENS",record.get("ocr_critical_match"),
              "GOLD_ANSWER",record.get("gold_text_verdict"),
              "IMAGE_ANSWER",record.get("image_answer_verdict"),flush=True)
        time.sleep(2)
    report["completed"]=time.time()
    report["summary"] = {
        "ocr_http_ok": sum(c.get("ocr_http")==200 for c in report["cases"]),
        "ocr_critical_token_match": sum(c.get("ocr_critical_match") is True for c in report["cases"]),
        "gold_text_answer_wrong": sum(c.get("gold_text_verdict")=="ANSWER_WRONG" for c in report["cases"]),
        "image_answer_wrong": sum(c.get("image_answer_verdict")=="ANSWER_WRONG" for c in report["cases"]),
        "image_answer_unscorable": sum(c.get("image_answer_verdict") in (None,"FORMAT_UNSCORABLE","REQUEST_FAILED") for c in report["cases"]),
    }
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("OCR_DIFFERENTIAL_SUMMARY",report["summary"],flush=True)
    if report["summary"]["gold_text_answer_wrong"] or report["summary"]["image_answer_wrong"]:
        print("CONFIRMED WRONG MATHEMATICAL RESULT; investigate OCR and reasoning separately",flush=True)
        sys.exit(1)
if __name__=="__main__":
    main()
