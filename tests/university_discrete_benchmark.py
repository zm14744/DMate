#!/usr/bin/env python3
"""Attributed university exam benchmark for a running DMate instance.

Nothing is asserted to pass unless the deployed /chat or /ocr endpoint answered.
These items are paraphrased or shortened from the attributed official exam/solutions.
Heuristic grading is intentionally conservative; full proofs need human review.
"""
import argparse, io, json, os, re, subprocess, sys, time
from pathlib import Path
import requests

CORNELL = "https://www.cs.cornell.edu/courses/cs2802/2020fa/2800finalsol-16fa.pdf"
BERKELEY = "https://math.berkeley.edu/~ribet/55/final_sols.pdf"
MIT = "https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2010/634ff37bc1a5139ccdd58dc7494193f9_MIT6_042JF10_assn09.pdf"

# check: any listed regex must appear; this checks a necessary answer marker,
# NOT correctness of the explanation. 'review' deliberately has no auto verdict.
CASES = [
 ("C01","Cornell","induction","若对一切自然数k都有 P(k)=>P(k+2)，且P(1)为真，能否证明所有奇数位置P(2n+1)均真？给出证明。", [r"归纳|induct"], CORNELL),
 ("C02","Cornell","number-theory","证明任意100个互不相同的整数中，存在两个数之差是37的倍数。",[r"抽屉|鸽巢|鸽笼|余数|同余"],CORNELL),
 ("C03","Cornell","logic","用一阶逻辑形式化：每个学生都认识某位拥有手机的学生。请定义谓词。",[r"∀|\\forall"],CORNELL),
 ("C04","Cornell","graph-Euler","昆虫能否沿立方体骨架每条棱恰好走一次（起终点可不同）？说明依据。",[r"不可能|不能|无法|不存在"],CORNELL),
 ("C05","Cornell","probability","独立抛100次硬币，正面概率0.6。正面次数的方差是多少？",[r"(?<!\d)24(?:\.0+)?(?!\d)"],CORNELL),
 ("C06","Cornell","modular-arithmetic","模数21，RSA公钥指数5的解密指数d（模phi(21)）是多少？",[r"(?<!\d)5(?!\d)"],CORNELL),
 ("C07","Cornell","proof-checking","有证明说某个特定函数 f:X->P(X) 不是满射，因此X与P(X)之间不存在任何满射。指出这一步推理的错误。",[r"不能|不足|无法|不代表|不意味着|并不"],CORNELL),
 ("B01","Berkeley","congruence","已知 1=121×18−7×311，解 18x≡7 (mod 311)，给出一个整数解。",[r"(?<!\d)(?:847|225)(?!\d)"],BERKELEY),
 ("B02","Berkeley","combinatorics","展开 (x+y+z+w)^100 并合并同类项后一共有多少项？",[r"176[,\s]?851|\\binom\{103\}\{3\}|C[_^ ]?\{?103\}?[_^ ]?\{?3\}?"],BERKELEY),
 ("B03","Berkeley","probability","朋友有30%概率忘记浇花；没浇花枯死率90%，浇了枯死率20%。一周后花枯死概率多少？",[r"0\.41|41%|\\frac\{41\}\{100\}"],BERKELEY),
 ("B04","Berkeley","conditional-probability","朋友有30%概率忘记浇花；没浇花枯死率90%，浇了枯死率20%。若花已枯死，则忘记浇花的条件概率？",[r"27\s*/\s*41|\\frac\{27\}\{41\}|0\.6585|65\.85|65\.9|66%"],BERKELEY),
 ("B05","Berkeley","graph-Euler","完全图K_n（n>=2）在什么n下存在欧拉回路？说明为什么。",[r"奇数|奇数阶|n.*奇|n.*odd"],BERKELEY),
 ("B06","Berkeley","set-theory","若A∩C=B∩C 且 A∪C=B∪C，能否推出A=B？证明或举反例。",[r"A\s*=\s*B|A\s*\\?=\\?B|相等|可以推出|能推出"],BERKELEY),
 ("B07","Berkeley","equivalence-relation","证明：有n>=2个元素的有限集合上的等价关系，必有两个不同元素所属等价类的大小相同。",[r"抽屉|鸽巢|鸽笼|n-1|n−1"],BERKELEY),
 ("M01","MIT","graph-counting","n个带固定标签顶点的无向简单图共有多少种？给出公式。",[r"2\s*\^|2\s*\{?\^\}?|2\^\{"],MIT),
 ("M02","MIT","graph-counting","n个带标签顶点的无环竞赛图共有多少种？给出公式。",[r"n\s*!|n\s*\\!|阶乘"],MIT),
 ("M03","MIT","stars-bars","非负整数 x0,x1,...,xk 满足 x0+x1+...+xk=n，有多少组解？",[r"binom|C\s*\(|组合数|\\mathrm\{C\}"],MIT),
 ("M04","MIT","graph-degree","证明任意n>=2的有限连通无向简单图中，必有两个顶点度数相同。",[r"n-1|n−1|抽屉|鸽巢|鸽笼"],MIT),
]
GRAPH_TEXT = """下列无向简单图中哪些是树？请直接给答案。
图1（G1）：顶点 a、b、c、d，边：a-b,b-c,c-d。
图2（G2）：顶点 a、b、c、d，边：a-b,b-c,c-a。
图3（G3）：顶点 a、b、c、d，边：a-b,c-d。
"""
def check_local():
    from graph_consistency import analyze_labeled_graphs, summarize_tree_question
    graphs=analyze_labeled_graphs(GRAPH_TEXT)
    assert sorted(graphs)==[1,2,3],graphs
    assert [graphs[k]["tree"] for k in (1,2,3)]==[True,False,False],graphs
    assert "G1" in summarize_tree_question(GRAPH_TEXT)
    print("OFFLINE_CHECK PASS: complete edges, cycle, disconnected case")
def post_chat(sess,base,question,timeout):
    r=sess.post(base+"/chat",json={"messages":[{"role":"user","content":"请直接给出最终答案并简要解释。"+question}]},timeout=timeout)
    try: result=r.json()
    except ValueError: result={"raw":r.text[:200]}
    return r.status_code,result
def post_image(sess,base,image_bytes,timeout):
    r=sess.post(base+"/ocr",files={"image":("university_exam.png",image_bytes,"image/png")},timeout=timeout)
    try: result=r.json()
    except ValueError: result={"raw":r.text[:200]}
    return r.status_code,result
def pdf_crop(sess,url,page,box):
    from PIL import Image
    r=sess.get(url,timeout=50);r.raise_for_status()
    # PyMuPDF: local render of untouched public university examination PDF.
    import fitz
    doc=fitz.open(stream=r.content,filetype="pdf")
    pageobj=doc[page]
    pic=pageobj.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
    image=Image.frombytes("RGB",[pic.width,pic.height],pic.samples)
    w,h=image.size
    cropped=image.crop((int(w*box[0]),int(h*box[1]),int(w*box[2]),int(h*box[3])))
    out=io.BytesIO();cropped.save(out,format="PNG");return out.getvalue()
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--base",default=os.getenv("DMATE_BENCH_URL","https://dmate.zeabur.app"))
    ap.add_argument("--max-chat",type=int,default=18)
    ap.add_argument("--timeout",type=int,default=105)
    ap.add_argument("--delay",type=int,default=5)
    ap.add_argument("--output",default="university_benchmark_results.json")
    ap.add_argument("--skip-images",action="store_true")
    opts=ap.parse_args()
    check_local()
    base=opts.base.rstrip("/")
    data={"target":base,"started_utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"purpose":"university exam verification, no fake mocks","cases":[],"images":[]}
    session=requests.Session()
    for id,school,topic,prompt,checks,source in CASES[:opts.max_chat]:
        try:
            status,result=post_chat(session,base,prompt,opts.timeout)
            reply=str(result.get("reply",""))
            markers=[bool(re.search(pattern,reply,re.I|re.S)) for pattern in checks]
            verdict=("NEEDS_REVIEW" if status==200 and reply and all(markers)
                     else "ANSWER_SUSPECT" if status==200 and reply else "REQUEST_FAILED")
            row={"id":id,"school":school,"topic":topic,"source":source,"http":status,
                 "verdict":verdict,"heuristic_markers":markers,"reply":reply[:6000],
                 "error":result.get("error")}
        except Exception as e:
            row={"id":id,"topic":topic,"verdict":"REQUEST_FAILED","error":repr(e)}
        data["cases"].append(row)
        print("CHAT",id,row["verdict"],str(row.get("http","")),str(row.get("error",""))[:100],flush=True)
        time.sleep(opts.delay)
    # Two *original* university exam-image crops, not synthetic PIL graphs.
    if not opts.skip_images:
        images=[
          ("I01","Cornell CS2800 2016 final: relation directed graph",CORNELL,4,(.12,.09,.88,.32)),
          ("I02","Berkeley Math55 2019 final: modular arithmetic/recurrence notation",BERKELEY,0,(.11,.09,.91,.45)),
        ]
        for id,caption,url,page,box in images:
            try:
                raw=pdf_crop(session,url,page,box)
                status,result=post_image(session,base,raw,opts.timeout)
                # Preserve image output and review fields for human graph-edge verification.
                row={"id":id,"caption":caption,"source":url,"http":status,
                  "verdict":"NEEDS_REVIEW" if status==200 else "REQUEST_FAILED",
                  "text":str(result.get("text",""))[:4500],
                  "visual_text":str(result.get("visual_text",""))[:4500],
                  "review":result.get("review"),
                  "warnings":result.get("warnings"),"error":result.get("error"),
                  "graph_structures":result.get("graph_structures")}
            except Exception as e:
                row={"id":id,"caption":caption,"source":url,
                     "verdict":"REQUEST_FAILED","error":repr(e)}
            data["images"].append(row)
            print("IMAGE",id,row["verdict"],row.get("http",""),str(row.get("error",""))[:100],flush=True)
            time.sleep(opts.delay)
    data["completed_utc"]=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())
    Path(opts.output).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    print("COUNTS:",{v:sum(x["verdict"]==v for x in data["cases"]+data["images"])
                     for v in ["NEEDS_REVIEW","ANSWER_SUSPECT","REQUEST_FAILED"]},flush=True)
    print("OUTPUT",opts.output)
if __name__=="__main__":main()
