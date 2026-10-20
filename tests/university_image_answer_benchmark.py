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
    {"id":"MIT7-2d","page":0,"box":[.10,.79,.92,.95],"tokens":["100","8"],"section":"2d"},
    {"id":"MIT7-2g","page":1,"box":[.10,.22,.91,.38],"tokens":["15","0","1","2","3"],"section":"2g"},
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
            # Always test independently transcribed gold: this is the user's
            # priority case where recognition is known correct but solving fails.
            suffix="\n请独立解答。末行只能写【结果】整数，不要在结果后写其他字符。"
            status,reply,error=ask(s,base,c["question"]+suffix,95)
            record["gold_text_http"]=status
            record["gold_text_reply"]=reply[:5000]
            record["gold_text_verdict"]=judge(c,reply)[0] if status==200 else "REQUEST_FAILED"
            record["gold_text_error"]=error
            if record["ocr_critical_match"] and not record.get("ocr_error"):
                # This is a distinct end-to-end image -> text -> answer path.
                # Do not claim OCR fully correct from partial critical tokens.
                parsed=(record["ocr_text"]+"\n"+record["ocr_graph"]).strip()
                status,reply,error=ask(s,base,parsed+suffix,95)
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
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
if __name__=="__main__":
    main()
