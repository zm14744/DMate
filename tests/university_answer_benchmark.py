#!/usr/bin/env python3
"""University discrete-math benchmark with provenance and exact final-answer oracles.
Correct final value != validated proof. Always distinguish HTTP, OCR, format, math.
"""
import argparse, json, math, os, re, sys, time
from fractions import Fraction
from pathlib import Path
import requests

BANK=Path(__file__).with_name("university_verified_cases.json")
def gold(c):
    kind=c["oracle"]["kind"]
    value=c["oracle"]["value"]
    if kind=="binomial":
        a,b=map(int,value.split(","))
        return Fraction(math.comb(a,b))
    return value if kind=="boolean" else Fraction(value)

def validate_bank():
    data=json.loads(BANK.read_text(encoding="utf-8"))["cases"]
    ids=set()
    for c in data:
        assert c["id"] not in ids
        ids.add(c["id"])
        assert c["category"] in ("official_paraphrase","derived_variant")
        assert c.get("source") and c.get("question")
        gold(c)
    indexed={c["id"]:c for c in data}
    assert gold(indexed["MIT7-1b"])==5005
    assert gold(indexed["MIT7-2d"])==math.comb(107,7)
    assert gold(indexed["V03"])==366
    assert gold(indexed["V11"])==24
    return data

def extract(reply):
    lines=[l.strip() for l in str(reply or "").strip().replace("**","").splitlines() if l.strip()]
    # Only a terminal explicit result marker; never mine a convenient number
    # from an incorrect proof or from question restatement.
    m=re.findall(r"【结果】\s*([^\n]+)","\n".join(lines[-2:]))
    return m[-1].strip().rstrip("。；;") if m else None

def parse_number(raw):
    t=raw.replace("$","").replace(" ","").replace("，",",").strip()
    t=re.sub(r"\\boxed\{([^{}]*)\}",r"\1",t)
    latex=re.fullmatch(r"\\frac\{(-?\d+)\}\{(\d+)\}",t)
    if latex:
        return Fraction(int(latex.group(1)),int(latex.group(2)))
    if re.fullmatch(r"-?\d{1,3}(?:,\d{3})+",t):
        t=t.replace(",","")
    if re.fullmatch(r"-?\d+(?:\.\d+)?(?:/-?\d+(?:\.\d+)?)?",t):
        try:
            if "/" in t:
                n,d=t.split("/",1)
                return Fraction(n)/Fraction(d)
            return Fraction(t)
        except (ValueError,ZeroDivisionError):
            pass
    return None

def judge(c,reply):
    t=extract(reply)
    if t is None:
        return "FORMAT_UNSCORABLE",None
    wanted=gold(c)
    if c["oracle"]["kind"]=="boolean":
        stripped=t.strip(" *$\\ ")
        got=("是" if stripped in ("是","对","正确","成立","真","yes","Yes")
             else "否" if stripped in ("否","错","错误","不成立","假","no","No")
             else None)
        if got is None:
            return "FORMAT_UNSCORABLE",t
        return ("ANSWER_MATCH_NEEDS_PROOF_REVIEW" if got==wanted
                else "ANSWER_WRONG"),t
    got=parse_number(t)
    if got is None:
        return "FORMAT_UNSCORABLE",t
    if c["oracle"]["kind"]=="decimal":
        same=abs(float(got)-float(wanted))<1e-6
    else:
        same=got==wanted
    return ("ANSWER_MATCH_NEEDS_PROOF_REVIEW" if same else "ANSWER_WRONG"),t

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base",default=os.getenv("DMATE_BENCH_URL","https://dmate.zeabur.app"))
    p.add_argument("--max-cases",type=int,default=40)
    p.add_argument("--official-only",action="store_true")
    p.add_argument("--start",type=int,default=0)
    p.add_argument("--timeout",type=int,default=65)
    p.add_argument("--delay",type=float,default=2.0)
    p.add_argument("--results",default="university_answer_benchmark_results.json")
    p.add_argument("--strict",action="store_true")
    o=p.parse_args()
    cases=validate_bank()
    if o.official_only:
        cases=[c for c in cases if c["category"]=="official_paraphrase"]
    cases=cases[o.start:o.start+o.max_cases]
    s=requests.Session()
    try: health=s.get(o.base.rstrip("/")+"/health",timeout=10).json()
    except Exception as exc:health={"error":str(exc)}
    report={"health":health,"started":time.time(),"cases":[],"selected":len(cases)}
    output=Path(o.results)
    for c in cases:
        row={k:c[k] for k in ("id","category","topic","source","oracle")}
        kind=c["oracle"]["kind"]
        note=("只能写'是'或'否'" if kind=="boolean"
              else "写整数或最简分数，不能用组合数符号或乘法表达式")
        question=(c["question"]+
                  "\n请独立解答并写出必要的计算或证明，最后一行必须严格写作"
                  "【结果】答案，结果之后不要写文字。"+note+"。")
        row["question"]=question
        try:
            response=s.post(o.base.rstrip("/")+"/chat",
                json={"messages":[{"role":"user","content":question}]},
                timeout=(10,o.timeout))
            row["http"]=response.status_code
            try: body=response.json()
            except ValueError: body={"error":"INVALID_JSON"}
            row["reply"]=str(body.get("reply",""))[:7000]
            row["error"]=body.get("error")
            if response.status_code==200 and row["reply"].strip():
                row["verdict"],row["final"]=judge(c,row["reply"])
            else: row["verdict"]="REQUEST_FAILED"
        except Exception as exc:
            row["verdict"]="REQUEST_FAILED"
            row["error"]=repr(exc)
        report["cases"].append(row)
        print("CASE",row["id"],row["verdict"],"final",row.get("final"),
              "HTTP",row.get("http"),flush=True)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        time.sleep(o.delay)
    report["finished"]=time.time()
    summary={v:sum(c["verdict"]==v for c in report["cases"]) for v in
        ["ANSWER_MATCH_NEEDS_PROOF_REVIEW","ANSWER_WRONG","FORMAT_UNSCORABLE","REQUEST_FAILED"]}
    report["summary"]=summary
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("SUMMARY",summary,flush=True)
    if o.strict and summary["ANSWER_WRONG"]:
        sys.exit(1)

if __name__=="__main__":
    main()
