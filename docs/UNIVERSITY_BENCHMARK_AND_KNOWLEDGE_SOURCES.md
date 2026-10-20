# DMate 高校课程题目验证与知识图谱学术来源说明

> **公开、可追溯的竞赛项目说明** · 证据快照截至 2026-10-20 · 汇编于 2026-10-21  
> 适用项目：**DMate — 离散数学智能辅学系统** · [GitHub 项目](https://github.com/zm14744/DMate) · [演示网站](https://dmate.zeabur.app)  
> 本文件依照仓库内测试题库、GitHub Actions **实际运行日志**和 `knowledge_graph.json` 编制。使用 MIT、斯坦福等高校**公开资料作为测试输入**，绝不表示这些高校认可、认证、联合研发或背书 DMate。

## 摘要：有依据的课程内容体系与可复现的高校题库

DMate 自主整理了一套参考中文高教社离散数学教材、MIT OpenCourseWare、Rosen 英文教材的课程知识图谱：**10 大模块、68 个知识节点（其中图论 21 节点）**。项目依据国内外高校公开作业、期末资料、讲义和课程习题做了**文本题与原始图片两种不同能力验证**，并在 GitHub Actions 保留可查看的真实线上接口日志、测试题源和失败记录。

| 独立题库（ID去重，不重复累计多次运行） | 本项目实际结果与验证程度 |
|---|---|
| 高校公开课程题对应的**中文改写/摘选文字子题**（南京大学、上海交通大学） | **27/28** 道至少一次 HTTP 200 且必要答案要点命中（B），其余一题没有获得可确认通过记录 |
| 中国科学技术大学真实**课程讲义例题** | **7/7** 道必要答案要点命中（B），**不是正式考试原题** |
| 美国高校官方公开题/解答来源的中文改写库（MIT、Cornell、UC Berkeley） | **33/40** 道至少一次与独立最终结果一致（A-最终值），其余7道未确认通过 |
| 基于大学题型自主生成的**参数变式** | **19/20** 道至少一次最终结果匹配（A-最终值）；非高校原题 |
| Columbia、MIT、Cambridge 等题型改写补测 | **8/8** 道初步要点命中（B），**不可称8道原版真题** |
| 原始 PDF 截图/实际带图图论题 | 有答案要点命中、安全拒猜、错误与题源失败；**不能计算经过核验的统一识图准确率** |

**判定口径**：**A-最终值**＝真实 `/chat` 返回的明确最终值匹配独立 oracle，**不等于证明每一步都正确**；**B-要点**＝HTTP 200 与必要答案关键词匹配，仍需审查完整推导；**C-安全复核**＝图片结构不确定时能提醒检查/停止猜测，算防错保护工作，不算解题成功；**D-未通过**＝已知答错、无法评分、HTTP故障或原始资料缺失。已通过一次仅指指定版本与运行，不保证之后每次完全正确。

---

## 一、知识图谱的学术与实现依据

### 1. 教材/课程来源（知识结构，不是高校官方认证）

1. **高等教育出版社《离散数学（第3版）》**：[出版社书目链接](https://xuanshu.hep.com.cn/front/book/findBookDetails?bookId=658daaba74ce561611bd9a4f)。参考中文课程术语、知识板块及基础先修顺序。
2. **MIT OpenCourseWare — Mathematics for Computer Science**：[MIT OCW 2024课程主页](https://ocw.mit.edu/courses/6-1200j-mathematics-for-computer-science-spring-2024/)。参考证明、数论、逻辑、组合、图论的公开课程体系。
3. **Kenneth H. Rosen — *Discrete Mathematics and Its Applications*（McGraw Hill）**：[出版社书目](https://www.mheducation.com/highered/product/discrete-mathematics-and-its-applications-rosen.html)。参考国际通行章节、概念与术语。

**仓库中可直接审阅的真实数据**：[知识图谱 JSON](https://github.com/zm14744/DMate/blob/main/knowledge_graph.json)（文件自带 `basis` 文献出处）、[完整知识图谱说明](https://github.com/zm14744/DMate/blob/main/docs/KNOWLEDGE_GRAPH.md)、[知识点识别及课程分类代码](https://github.com/zm14744/DMate/blob/main/teaching.py)、[参考文献总表](https://github.com/zm14744/DMate/blob/main/docs/REFERENCES.md)。

### 2. 真实图谱节点：10 个模块、68 个节点

| 模块 | 节点数 | 本版本实际知识点 |
|---|---:|---|
| 命题逻辑 | 6 | 命题与真值、逻辑联结词、真值表、逻辑等价、范式、命题推理 |
| 谓词逻辑 | 5 | 谓词与个体域、量词、变元与辖域、量词推理与否定、前束范式 |
| 证明与归纳 | 3 | 直接证明与反证法、数学归纳法、强归纳法 |
| 集合与关系 | 7 | 集合运算、笛卡尔积与关系、关系运算、关系性质、等价关系与划分、偏序关系、关系闭包 |
| 函数 | 4 | 函数与映射、单射满射双射、复合函数、逆函数 |
| 初等数论 | 7 | 整除与素数、最大公因数与欧几里得算法、同余与模运算、线性同余方程、模逆与中国剩余定理、欧拉定理与费马小定理、RSA公钥密码 |
| 计数与组合 | 6 | 基本计数原理、排列与组合、二项式定理、鸽巢原理、容斥原理、生成函数 |
| 递推关系 | 4 | 递推关系建模、线性齐次递推、非齐次递推、初始条件 |
| 图论 | 21 | 图的基本概念、图同构、邻接矩阵、图的矩阵表示、路径与连通性、割点与割边、带权图、欧拉图、哈密顿图、最短路、图着色、平面图、二部图、拓扑排序、支配集、覆盖集与独立集、图匹配、树的基本性质、根树、生成树、最小生成树、矩阵树定理 |
| 代数结构 | 5 | 代数系统、群与子群、同态与同构、环与域、格与布尔代数 |

**技术边界**：节点 `category`、`name` 与 `prerequisites` 来自仓库 `knowledge_graph.json`（version 3）；`prerequisites` 是**建议学习前置/依赖关系**，不是数学逻辑蕴含，也不直接记录每名学生的掌握程度。后端 `teaching.py` 关联课程模块、`knowledge_points`、`prerequisite_points` 和 `knowledge_path` 等学习提示。不存在“MIT 直接提供 DMate 的知识图谱”或“图谱获高校官方审核”这一结论。

### 3. 高校题目如何检验知识图谱覆盖

- **图论 21 节点**：MIT 直径/色数、Cornell 同构、ETH 重边、UNSW 二部图、NJU 连通性、Stanford 树的结构判断等。
- **集合与关系**：SJTU 逆关系/闭包/偏序，NJU 幂集与交、并关系。
- **逻辑及证明**：USTC 量词推理，MIT 逻辑等价，Cornell 数学归纳法。
- **组合与计数**：MIT 容斥、隔板法、排列，NJU 选派计数题。
- **初等数论**：USTC 同余论证、Cornell RSA、Berkeley 模逆。
- **函数/代数结构/递推关系**：NJU 单射满射、公开高校课程题型交叉映射；**有题目覆盖不意味着所有 68 个节点均经过同等深度的逐节点验证**。

---

## 二、中国高校：28 道真实作业对应的文字子题

题目是项目为了隔离题型与判断标准而作的**中文概要/改写及小问切分**；不等于“学校原题完整逐字重现”。来源来自学校实际公开 PDF。测试源代码 [`tests/chinese_university_regression.py`](https://github.com/zm14744/DMate/blob/main/tests/chinese_university_regression.py)；[2026-10-20完整实测记录](https://github.com/zm14744/DMate/actions/runs/39414956219)。其中 8 道上海交通大学题又在 [最新线上联合回归](https://github.com/zm14744/DMate/actions/runs/39454759405) 中全部返回 HTTP 200、必要要点匹配。

| 编号 | 高校 | 知识点 | 测试题概要（项目改写） | 有效证据状态 | 官方原题来源 |
|---|---|---|---|---|---|
| SJ01 | 上海交通大学 | 关系合成 | 已知关系 R={(1,1),(1,2),(1,3),(2,2),(2,3),(3,4)}，(2,4)是否属于 R∘R？请先写是/否并说明。 | B：HTTP 200/要点命中 | [来源](https://basics.sjtu.edu.cn/~yangqizhe/pdf/dm2024w/homework/DM-hw8sol.pdf) |
| SJ02 | 上海交通大学 | 逆关系 | R={(1,1),(1,2),(1,3),(2,2),(2,3),(3,4)}，其逆关系 R^(-1) 是否包含 (4,3)？说明。 | B：HTTP 200/要点命中 | [来源](https://basics.sjtu.edu.cn/~yangqizhe/pdf/dm2024w/homework/DM-hw8sol.pdf) |
| SJ03 | 上海交通大学 | 关系性质 | A={1,2,3,4}，R={(1,3),(1,4),(2,3),(3,4)}。R 是否为反对称关系？简要解释。 | B：HTTP 200/要点命中 | [来源](https://basics.sjtu.edu.cn/~yangqizhe/pdf/dm2024w/homework/DM-hw8sol.pdf) |
| SJ04 | 上海交通大学 | 传递闭包 | A={1,2,3,4}，R={(1,3),(1,4),(2,3),(3,4)}，求传递闭包中新增加而原关系没有的有序对。 | B：HTTP 200/要点命中 | [来源](https://basics.sjtu.edu.cn/~yangqizhe/pdf/dm2024w/homework/DM-hw8sol.pdf) |
| SJ05 | 上海交通大学 | 自反闭包 | A={1,2,3,4}，R={(1,3),(1,4),(2,3),(3,4)}，R 的自反闭包共有多少个有序对？ | B：HTTP 200/要点命中 | [来源](https://basics.sjtu.edu.cn/~yangqizhe/pdf/dm2024w/homework/DM-hw8sol.pdf) |
| SJ06 | 上海交通大学 | 等价关系 | 在 A={1,2,3} 上定义 xRy 当且仅当 x+y ≠ 3。它是不是等价关系？请给出反例。 | B：HTTP 200/要点命中 | [来源](https://basics.sjtu.edu.cn/~yangqizhe/pdf/dm2024w/homework/DM-hw8sol.pdf) |
| SJ07 | 上海交通大学 | 偏序与对称性 | 集合 S 至少含3个元素。在幂集P(S)上定义 XRY 当且仅当 X⊆Y。这是不是等价关系？指出不满足的性质。 | B：HTTP 200/要点命中 | [来源](https://basics.sjtu.edu.cn/~yangqizhe/pdf/dm2024w/homework/DM-hw8sol.pdf) |
| SJ08 | 上海交通大学 | 可比关系 | 集合S至少含3个元素。在P(S)上定义 XRY 当且仅当 X⊆Y 或 Y⊆X。这是不是等价关系？说明反例。 | B：HTTP 200/要点命中 | [来源](https://basics.sjtu.edu.cn/~yangqizhe/pdf/dm2024w/homework/DM-hw8sol.pdf) |
| NJG01 | 南京大学 | 握手定理 | 5名同学，每人恰好认识另外3人。如果认识必须相互，能否用无向简单图表示？说明。 | B：HTTP 200/要点命中 | [来源](https://cs.nju.edu.cn/_upload/tpl/01/53/339/template339/DM2019/parts/GraphPS1.pdf) |
| NJG02 | 南京大学 | 度数定理 | 判断：至少两个顶点的无向简单图能使所有顶点的度数各不相同吗？证明或反驳。 | B：HTTP 200/要点命中 | [来源](https://cs.nju.edu.cn/_upload/tpl/01/53/339/template339/DM2019/parts/GraphPS1.pdf) |
| NJG03 | 南京大学 | 完全图 | 求K5的顶点度序列（非递增）。 | B：HTTP 200/要点命中 | [来源](https://cs.nju.edu.cn/_upload/tpl/01/53/339/template339/DM2019/parts/GraphPS1.pdf) |
| NJG04 | 南京大学 | 环图 | 求C3的度序列。 | B：HTTP 200/要点命中 | [来源](https://cs.nju.edu.cn/_upload/tpl/01/53/339/template339/DM2019/parts/GraphPS1.pdf) |
| NJG05 | 南京大学 | 完全二部图 | 求K_{2,3}的度序列（非递增）。 | B：HTTP 200/要点命中 | [来源](https://cs.nju.edu.cn/_upload/tpl/01/53/339/template339/DM2019/parts/GraphPS1.pdf) |
| NJG06 | 南京大学 | 超立方体图 | 三维超立方体Q3有几个顶点？每个顶点度数是多少？ | B：HTTP 200/要点命中 | [来源](https://cs.nju.edu.cn/_upload/tpl/01/53/339/template339/DM2019/parts/GraphPS1.pdf) |
| NJG07 | 南京大学 | 图序列判定 | 判断度序列(5,4,3,2,1,0)能否对应某个无向简单图，并简要证明。 | B：HTTP 200/要点命中 | [来源](https://cs.nju.edu.cn/_upload/tpl/01/53/339/template339/DM2019/parts/GraphPS1.pdf) |
| NJG08 | 南京大学 | 图序列判定 | 度序列(2,2,2,2,2)能否由无向简单图实现？给出一个例子。 | B：HTTP 200/要点命中 | [来源](https://cs.nju.edu.cn/_upload/tpl/01/53/339/template339/DM2019/parts/GraphPS1.pdf) |
| NJG09 | 南京大学 | 图序列判定 | 度序列(5,3,3,3,3,3)能否由6个顶点的简单图实现？给出构造或反证。 | B：HTTP 200/要点命中 | [来源](https://cs.nju.edu.cn/_upload/tpl/01/53/339/template339/DM2019/parts/GraphPS1.pdf) |
| NJG10 | 南京大学 | 图序列判定 | 度序列(5,4,2,1,1,1)能否由6个顶点的无向简单图实现？ | B：HTTP 200/要点命中 | [来源](https://cs.nju.edu.cn/_upload/tpl/01/53/339/template339/DM2019/parts/GraphPS1.pdf) |
| NJL01 | 南京大学 | 命题逻辑等价 | 判断 (p→r)∨(q→r) 与 (p∧q)→r 是否逻辑等价，并说明。 | B：HTTP 200/要点命中 | [来源](https://cs.nju.edu.cn/yuanyao/course/dismath/hw1.pdf) |
| NJL02 | 南京大学 | 命题逻辑 | 命题p表示下雨，q表示带伞。将‘只有下雨我才带伞’符号化。 | B：HTTP 200/要点命中 | [来源](https://cs.nju.edu.cn/yuanyao/course/dismath/hw1.pdf) |
| NJL03 | 南京大学 | 命题逻辑与计数 | A、B、C、D中选2人出差。若A去，则C和D中至少去1人；B和C不能同时去；C去则D不去。共有多少种符合条件的选派？ | B：HTTP 200/要点命中 | [来源](https://cs.nju.edu.cn/yuanyao/course/dismath/hw1.pdf) |
| NJL04 | 南京大学 | 集合计数 | 有限集合A,B满足\|A\|=5, \|P(B)\|=512, \|P(A△B)\|=1024。求\|A∩B\|。 | B：HTTP 200/要点命中 | [来源](https://cs.nju.edu.cn/yuanyao/course/dismath/hw2.pdf) |
| NJL05 | 南京大学 | 集合计数 | 有限集合A,B满足\|A\|=5, \|P(B)\|=512, \|P(A△B)\|=1024。求\|A∪B\|。 | B：HTTP 200/要点命中 | [来源](https://cs.nju.edu.cn/yuanyao/course/dismath/hw2.pdf) |
| NJL06 | 南京大学 | 等价关系 | 整数集Z上定义aRb当且仅当5整除(a-b)。商集Z/R有多少个不同的等价类？ | B：HTTP 200/要点命中 | [来源](https://cs.nju.edu.cn/yuanyao/course/dismath/hw2.pdf) |
| NJL07 | 南京大学 | 函数单射满射 | 实数到实数的函数f(x)=x²是否双射？给出理由。 | B：HTTP 200/要点命中 | [来源](https://cs.nju.edu.cn/yuanyao/course/dismath/hw2.pdf) |
| NJL08 | 南京大学 | 函数单射满射 | 实数到实数的函数 f(x)=2x+1 是否双射？ | B：HTTP 200/要点命中 | [来源](https://cs.nju.edu.cn/yuanyao/course/dismath/hw2.pdf) |
| NJL09 | 南京大学 | 函数单射满射 | 实数到实数的函数 f(x)=x³ 是否双射？ | B：HTTP 200/要点命中 | [来源](https://cs.nju.edu.cn/yuanyao/course/dismath/hw2.pdf) |
| NJL10 | 南京大学 | 函数单射满射 | 实数到实数的函数 f(x)=x²/(1+x²) 是否是满射？给出值域。 | 旧版未确认正确（不可计通过） | [来源](https://cs.nju.edu.cn/yuanyao/course/dismath/hw2.pdf) |

**重要边界**：其中 **NJL10** 旧版有判分/请求异常，不写成通过；NJL02（额外虚构小问）、NJL03（选派计数）、NJL04（交集基数）的旧回答也曾暴露逻辑/结果问题，已加入后续数学核验回归，故以上 B 级“要点命中”绝不等于全部推导合格。

### 中国科学技术大学：7 道课程讲义原例（非真题卷）

来源：[USTC 官方教员公开讲义](https://faculty.ustc.edu.cn/_resources/group1/M00/00/47/wKhJFGT1pGSAfHlvAE0oo3Ug_0I994.pdf)；[7/7线上必要要点符合记录](https://github.com/zm14744/DMate/actions/runs/39416095215)。

| 编号 | 知识点 | 原公开讲义中对应的例题概要 | 结果 |
|---|---|---|---|
| UST01 | 嵌套量词 | 论域是所有实数，Q(x,y)表示x+y=0。命题∃y∀x Q(x,y)是真还是假？解释原因。 | B：HTTP 200/要点命中 |
| UST02 | 嵌套量词 | 论域是所有实数，Q(x,y)表示x+y=0。命题∀x∃y Q(x,y)是真还是假？给出y的取法。 | B：HTTP 200/要点命中 |
| UST03 | 模运算证明 | 证明：如果整数n不能被2或3整除，则n²−1能被24整除。 | B：HTTP 200/要点命中 |
| UST04 | 模运算反证 | 证明整数方程x²+3y²=8没有整数解，给出一个模3的理由。 | B：HTTP 200/要点命中 |
| UST05 | 立方数分解 | 给出整数1729的两组不同的正整数立方和表示（列出四个底数）。 | B：HTTP 200/要点命中 |
| UST06 | 反例构造 | 多项式f(n)=n²−n+41是否对每个正整数n都产生素数？请给出一个反例n。 | B：HTTP 200/要点命中 |
| UST07 | 棋盘染色 | 标准8×8国际象棋棋盘去掉两个对角的角格后，能否用31块1×2骨牌完全铺满？给出染色理由。 | B：HTTP 200/要点命中 |

---

## 三、美国高校公开试题/习题：有独立标准最终答案的 33 道

来源范围包括 MIT 公开课程作业，Cornell 公开课程考试及解答，UC Berkeley Math55 的公开期末解答。各题的原始大学链接均保存在 [`tests/university_verified_cases.json`](https://github.com/zm14744/DMate/blob/main/tests/university_verified_cases.json)；评分算法在 [`tests/university_answer_benchmark.py`](https://github.com/zm14744/DMate/blob/main/tests/university_answer_benchmark.py)。这些题属于**依据原课程题目的中文改写**，部分只取单独小问，不是纸质原卷图片 OCR。下面**只列出存在至少一轮 HTTP 200 + 最终结果精确匹配日志**的 33 道；重复测试不会重复计数。

| ID | 课程来源 | 模块 | 测试题（中文改写概要） | 独立期望结果 | 实际匹配记录 | 原始大学材料 |
|---|---|---|---|---|---|---|
| MIT7-1b | MIT | 组合计数 | 20本按顺序排放的书，选出6本且任意两本不相邻，一共有多少种选择？ | 5005 | [运行 #39407864222](https://github.com/zm14744/DMate/actions/runs/39407864222) | [原出处](https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/4791b8cd8b7a492119f5b67497490bcb_ps7.pdf) |
| MIT7-2a | MIT | 重复排列 | 单词BANANARAMA的10个字母可形成多少个不同排列？ | 15120 | [运行 #39407864222](https://github.com/zm14744/DMate/actions/runs/39407864222) | [原出处](https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/4791b8cd8b7a492119f5b67497490bcb_ps7.pdf) |
| MIT7-2d | MIT | 隔板法 | 非负整数x1至x8满足x1+x2+...+x8=100，一共有多少个有序解？ | C(107,7) | [运行 #39407864222](https://github.com/zm14744/DMate/actions/runs/39407864222) | [原出处](https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/4791b8cd8b7a492119f5b67497490bcb_ps7.pdf) |
| MIT7-2g | MIT | 组合计数 | 15个有序位置，一次选择0、1、2或3个不同位置，选择组合总数？ | 576 | [运行 #39407864222](https://github.com/zm14744/DMate/actions/runs/39407864222) | [原出处](https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/4791b8cd8b7a492119f5b67497490bcb_ps7.pdf) |
| MIT7-2h | MIT | 容斥原理 | 1至300的整数中，能被2或3或5整除的整数共有多少个？ | 220 | [运行 #39407864222](https://github.com/zm14744/DMate/actions/runs/39407864222) | [原出处](https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/4791b8cd8b7a492119f5b67497490bcb_ps7.pdf) |
| MIT7-3c | MIT | 抽屉原理 | 从整数中任选30个不同的整数，是否保证有两个整数的差或者和可以被51整除？ | 是 | [运行 #39408053599](https://github.com/zm14744/DMate/actions/runs/39408053599) | [原出处](https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/4791b8cd8b7a492119f5b67497490bcb_ps7.pdf) |
| MIT7-4a | MIT | 组合计数 | 七颗不同颜色的六面骰子同时掷出，出现7个面值两两不同的方法数是多少？ | 0 | [运行 #39408053599](https://github.com/zm14744/DMate/actions/runs/39408053599) | [原出处](https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/4791b8cd8b7a492119f5b67497490bcb_ps7.pdf) |
| MIT7-4d | MIT | 排列组合 | 7颗可区分六面骰，恰好出现3种点数且频数分别为3、2、2，结果数是多少？ | 12600 | [运行 #39407837691](https://github.com/zm14744/DMate/actions/runs/39407837691) | [原出处](https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/4791b8cd8b7a492119f5b67497490bcb_ps7.pdf) |
| MIT7-5g | MIT | 错排与概率 | n个元素随机排列，随着n增大，所有元素均不在原位置的概率趋于哪个常数？要求6位小数。 | 0.367879 | [运行 #39407864222](https://github.com/zm14744/DMate/actions/runs/39407864222) | [原出处](https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/4791b8cd8b7a492119f5b67497490bcb_ps7.pdf) |
| MIT4-3a | MIT | 图的直径 | 无向图顶点为A,B,C,D,E,F,G,H，边为AB,BC,BH,CD,CE,DE,EF,EH,FG。图的直径是几？ | 5 | [运行 #39407864222](https://github.com/zm14744/DMate/actions/runs/39407864222) | [原出处](https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/587366ef0ee07f57ed41715559224224_ps4.pdf) |
| MIT4-3b | MIT | 图着色 | 无向图顶点为A,B,C,D,E,F,G,H，边为AB,BC,BH,CD,CE,DE,EF,EH,FG。最小色数是多少？ | 3 | [运行 #39407864222](https://github.com/zm14744/DMate/actions/runs/39407864222) | [原出处](https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/587366ef0ee07f57ed41715559224224_ps4.pdf) |
| MIT4-4a | MIT | 图的连通性 | 无向简单图每个顶点都至少与另一个顶点相邻，但整个图不连通。满足条件的最少顶点数是多少？ | 4 | [运行 #39407864222](https://github.com/zm14744/DMate/actions/runs/39407864222) | [原出处](https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/587366ef0ee07f57ed41715559224224_ps4.pdf) |
| MIT4-5a | MIT | 平面图 | 对于一个至少具有3个顶点的简单平面图，是否必存在至少一个度数不超过5的顶点？ | 是 | [运行 #39407837691](https://github.com/zm14744/DMate/actions/runs/39407837691) | [原出处](https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/587366ef0ee07f57ed41715559224224_ps4.pdf) |
| MIT4-3c | MIT | 路径与直径 | 设无向连通图每个顶点到同一个固定顶点v的最短距离都不超过n。图的直径必不超过2n吗？ | 是 | [运行 #39408053599](https://github.com/zm14744/DMate/actions/runs/39408053599) | [原出处](https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/587366ef0ee07f57ed41715559224224_ps4.pdf) |
| MIT4-1a | MIT | 函数复合 | 若f:A到B及g:B到C均为双射，那么g∘f一定为双射吗？ | 是 | [运行 #39407864222](https://github.com/zm14744/DMate/actions/runs/39407864222) | [原出处](https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/587366ef0ee07f57ed41715559224224_ps4.pdf) |
| MIT4-1c | MIT | 等价关系 | 无向简单图的图同构关系（在所有有限简单图上）是否具有自反性、对称性、传递性？ | 是 | [运行 #39407864222](https://github.com/zm14744/DMate/actions/runs/39407864222) | [原出处](https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/587366ef0ee07f57ed41715559224224_ps4.pdf) |
| C-2c | Cornell | 数学归纳法 | 只知道对所有自然数k，P(k)→P(k+2)。是否能必然推出所有偶数n满足P(n)？ | 否 | [运行 #39407864222](https://github.com/zm14744/DMate/actions/runs/39407864222) | [原出处](https://www.cs.cornell.edu/courses/cs2802/2020fa/2800finalsol-16fa.pdf) |
| C-5a | Cornell | 期望 | 一枚硬币每次正面概率0.6，独立抛100次，正面出现次数期望是多少？ | 60 | [运行 #39408083627](https://github.com/zm14744/DMate/actions/runs/39408083627) | [原出处](https://www.cs.cornell.edu/courses/cs2802/2020fa/2800finalsol-16fa.pdf) |
| C-5b | Cornell | Markov不等式 | 抛100次独立硬币，每次正面概率0.6，Y为正面次数。Markov不等式对P(Y≥80)给出的上界是多少？ | 3/4 | [运行 #39407864222](https://github.com/zm14744/DMate/actions/runs/39407864222) | [原出处](https://www.cs.cornell.edu/courses/cs2802/2020fa/2800finalsol-16fa.pdf) |
| C-5c | Cornell | 方差 | 一枚硬币正面概率0.6，单次伯努利随机变量的方差是多少？ | 0.24 | [运行 #39407864222](https://github.com/zm14744/DMate/actions/runs/39407864222) | [原出处](https://www.cs.cornell.edu/courses/cs2802/2020fa/2800finalsol-16fa.pdf) |
| C-5d | Cornell | 方差 | 正面概率0.6，100次独立硬币正面次数的方差是多少？ | 24 | [运行 #39407864222](https://github.com/zm14744/DMate/actions/runs/39407864222) | [原出处](https://www.cs.cornell.edu/courses/cs2802/2020fa/2800finalsol-16fa.pdf) |
| C-5e | Cornell | Chebyshev不等式 | 正面概率0.6，100次独立硬币，Y为正面次数。Chebyshev不等式对偏差至少20的事件P(\|Y−60\|≥20)给出的上界是多少？ | 0.06 | [运行 #39408053599](https://github.com/zm14744/DMate/actions/runs/39408053599) | [原出处](https://www.cs.cornell.edu/courses/cs2802/2020fa/2800finalsol-16fa.pdf) |
| C-7a | Cornell | RSA | RSA模数21且公开指数5，私钥指数d取0≤d<12且5d≡1(mod12)，求d。 | 5 | [运行 #39408053599](https://github.com/zm14744/DMate/actions/runs/39408053599) | [原出处](https://www.cs.cornell.edu/courses/cs2802/2020fa/2800finalsol-16fa.pdf) |
| C-7c | Cornell | RSA | 模数21，RSA公开指数5，收到密文4，已知私钥指数5，则原始明文是什么？ | 16 | [运行 #39408053599](https://github.com/zm14744/DMate/actions/runs/39408053599)；历史另有评分异常 | [原出处](https://www.cs.cornell.edu/courses/cs2802/2020fa/2800finalsol-16fa.pdf) |
| C-12a | Cornell | 欧拉通路 | 是否可能沿立方体骨架的每一条边恰好行走一次（起点和终点可以不同）？ | 否 | [运行 #39408053599](https://github.com/zm14744/DMate/actions/runs/39408053599) | [原出处](https://www.cs.cornell.edu/courses/cs2802/2020fa/2800finalsol-16fa.pdf) |
| C-3 | Cornell | 最大公约数 | 斐波那契变体f0=f1=1，fn+2=fn+1+fn，对所有n，gcd(fn,fn+1)是否等于1？ | 是 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) | [原出处](https://www.cs.cornell.edu/courses/cs2802/2020fa/2800finalsol-16fa.pdf) |
| B-1a | UC Berkeley | 线性同余 | 已知1=121×18−7×311，求18x≡7(mod311)在0≤x<311范围内的唯一整数解。 | 225 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) | [原出处](https://math.berkeley.edu/~ribet/55/final_sols.pdf) |
| B-1b | UC Berkeley | 模运算 | 线性同余18x≡7(mod311)在模311意义下有几个不同的解？ | 1 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) | [原出处](https://math.berkeley.edu/~ribet/55/final_sols.pdf) |
| B-3 | UC Berkeley | 几何分布期望 | 反复掷公平六面骰直到出现两种不同点数，包含第一次掷出，所需掷骰次数期望是多少？ | 11/5 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) | [原出处](https://math.berkeley.edu/~ribet/55/final_sols.pdf) |
| B-4 | UC Berkeley | 组合概率 | 从52张标准扑克牌中无序抽5张，至少有2张J/Q/K人头牌的手牌共有多少种？（不是概率） | 844272 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) | [原出处](https://math.berkeley.edu/~ribet/55/final_sols.pdf) |
| B-6 | UC Berkeley | 隔板法 | (x+y+z+w)^100 合并同类项后，共有多少个不同单项式？ | 176851 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) | [原出处](https://math.berkeley.edu/~ribet/55/final_sols.pdf) |
| B-7 | UC Berkeley | 等价关系 | 任意含至少2个元素的有限集合上的等价关系，是否必存在不同元素，它们的等价类大小相同？ | 是 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) | [原出处](https://math.berkeley.edu/~ribet/55/final_sols.pdf) |
| B-9b | UC Berkeley | 集合恒等式 | 集合A,B,C满足A∩C=B∩C且A∪C=B∪C，是否一定A=B？ | 是 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) | [原出处](https://math.berkeley.edu/~ribet/55/final_sols.pdf) |

历史标准答案检测记录（部分运行曾出现 HTTP 429，不将其当作答对）：[运行 #39407864222](https://github.com/zm14744/DMate/actions/runs/39407864222)、[运行 #39407837691](https://github.com/zm14744/DMate/actions/runs/39407837691)、[运行 #39408053599](https://github.com/zm14744/DMate/actions/runs/39408053599)、[运行 #39408083627](https://github.com/zm14744/DMate/actions/runs/39408083627)、[运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952)。例如 `C-7c` 某次有评分异常，因此虽然另一次与参考最终值一致，**其证明与重复性仍应检查**。未在本表出现的另外7道并非自动认为错误，而是没有可据此宣布“最终结果通过”的证据。

### 19 道独立参数变式：验证泛化，**不是高校原考试题**

[20道变式及 oracle 数据集](https://github.com/zm14744/DMate/blob/main/tests/university_verified_cases.json)中，19道至少一次最终结果严格匹配；`V10` 未能完成自动评分。变式以公开课程知识点为参照而独立设置数字或条件，仅用于验证泛化能力，不计作“19道名校原题”。

| ID | 模块 | 独立练习问题概要 | 期望最终结果 | 运行记录 |
|---|---|---|---|---|
| V01 | 变式-间隔计数 | 把17本按顺序排放的书中选出5本且两两不相邻，选择方式有几种？ | 1287 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) |
| V02 | 变式-间隔计数 | 把12本书中选出4本且两两不相邻，选择方式有几种？ | 126 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) |
| V03 | 变式-容斥 | 1至500的整数中，至少能被2、3、5之一整除的有多少个？ | 366 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) |
| V04 | 变式-隔板法 | 非负整数x1到x5之和为10，共有几组有序解？ | 1001 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) |
| V05 | 变式-隔板法 | 正整数x1到x5之和为10，共有几组有序解？ | 126 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) |
| V06 | 变式-错排 | 5个人各有一顶不同的帽子，随机排帽子且无人拿自己帽子，有多少种分配方式？ | 44 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) |
| V07 | 变式-独立方差 | 正面概率0.3，独立抛200次硬币，正面次数方差是多少？ | 42 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) |
| V08 | 变式-Markov | 非负随机变量均值为12，Markov不等式对P(X≥48)给出的上界是多少？ | 1/4 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) |
| V09 | 变式-Chebyshev | 随机变量均值10、方差16，Chebyshev不等式对P(\|X−10\|≥8)给出的上界？ | 1/4 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) |
| V11 | 变式-同余 | 求17x≡5(mod31)在0≤x<31时的解。 | 24 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) |
| V12 | 变式-组合 | 展开(x+y+z)^20并合并同类项，共有多少项？ | 231 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) |
| V13 | 变式-图直径 | 路径图P_11有11个顶点，最长最短路长度（直径）为多少？ | 10 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) |
| V14 | 变式-图着色 | 轮图W_6（一个中心顶点和5个环上顶点）最小色数为多少？ | 4 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) |
| V15 | 变式-连通 | 无向图顶点a,b,c,d,e,f，边ab,bc,ca,de,ef,fd。图中连通分量数是多少？ | 2 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) |
| V16 | 变式-树 | 无向图顶点a,b,c,d,e，边ab,bc,cd,de。它是树吗？ | 是 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) |
| V17 | 变式-树 | 无向图顶点a,b,c,d,e，边ab,bc,ca,de。它是树吗？ | 否 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) |
| V18 | 变式-计数 | 6位可区分二元序列中恰有3个1的序列数？ | 20 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) |
| V19 | 变式-图计数 | 固定4个带标签顶点的简单无向图允许自环，每条无向边、自环至多出现一次，总图数？ | 1024 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) |
| V20 | 变式-初等数论 | gcd(987,610)是多少？ | 1 | [运行 #39407126952](https://github.com/zm14744/DMate/actions/runs/39407126952) |

---

## 四、其他大学来源题：关键词命中与八道补充样例

### Cornell / Berkeley / MIT 等 18 道文字任务

对应 [大学文字题基准脚本](https://github.com/zm14744/DMate/blob/main/tests/university_discrete_benchmark.py)，且 [运行 #39417009892](https://github.com/zm14744/DMate/actions/runs/39417009892) 记录18道均为 HTTP 200、**必要线索命中（B，需复核完整证明）**。部分题与上一节不同，是另一套独立中文题干。

| 编号 | 来源 | 模块 | 题目概要 | 实测口径 |
|---|---|---|---|---|
| C01 | Cornell | induction | 若对一切自然数k都有 P(k)=>P(k+2)，且P(1)为真，能否证明所有奇数位置P(2n+1)均真？给出证明。 | B：必要关键词命中，证明未完全核对 |
| C02 | Cornell | number-theory | 证明任意100个互不相同的整数中，存在两个数之差是37的倍数。 | B：必要关键词命中，证明未完全核对 |
| C03 | Cornell | logic | 用一阶逻辑形式化：每个学生都认识某位拥有手机的学生。请定义谓词。 | B：必要关键词命中，证明未完全核对 |
| C04 | Cornell | graph-Euler | 昆虫能否沿立方体骨架每条棱恰好走一次（起终点可不同）？说明依据。 | B：必要关键词命中，证明未完全核对 |
| C05 | Cornell | probability | 独立抛100次硬币，正面概率0.6。正面次数的方差是多少？ | B：必要关键词命中，证明未完全核对 |
| C06 | Cornell | modular-arithmetic | 模数21，RSA公钥指数5的解密指数d（模phi(21)）是多少？ | B：必要关键词命中，证明未完全核对 |
| C07 | Cornell | proof-checking | 有证明说某个特定函数 f:X->P(X) 不是满射，因此X与P(X)之间不存在任何满射。指出这一步推理的错误。 | B：必要关键词命中，证明未完全核对 |
| B01 | Berkeley | congruence | 已知 1=121×18−7×311，解 18x≡7 (mod 311)，给出一个整数解。 | B：必要关键词命中，证明未完全核对 |
| B02 | Berkeley | combinatorics | 展开 (x+y+z+w)^100 并合并同类项后一共有多少项？ | B：必要关键词命中，证明未完全核对 |
| B03 | Berkeley | probability | 朋友有30%概率忘记浇花；没浇花枯死率90%，浇了枯死率20%。一周后花枯死概率多少？ | B：必要关键词命中，证明未完全核对 |
| B04 | Berkeley | conditional-probability | 朋友有30%概率忘记浇花；没浇花枯死率90%，浇了枯死率20%。若花已枯死，则忘记浇花的条件概率？ | B：必要关键词命中，证明未完全核对 |
| B05 | Berkeley | graph-Euler | 完全图K_n（n>=2）在什么n下存在欧拉回路？说明为什么。 | B：必要关键词命中，证明未完全核对 |
| B06 | Berkeley | set-theory | 若A∩C=B∩C 且 A∪C=B∪C，能否推出A=B？证明或举反例。 | B：必要关键词命中，证明未完全核对 |
| B07 | Berkeley | equivalence-relation | 证明：有n>=2个元素的有限集合上的等价关系，必有两个不同元素所属等价类的大小相同。 | B：必要关键词命中，证明未完全核对 |
| M01 | MIT | graph-counting | n个带固定标签顶点的无向简单图共有多少种？给出公式。 | B：必要关键词命中，证明未完全核对 |
| M02 | MIT | graph-counting | n个带标签顶点的无环竞赛图共有多少种？给出公式。 | B：必要关键词命中，证明未完全核对 |
| M03 | MIT | stars-bars | 非负整数 x0,x1,...,xk 满足 x0+x1+...+xk=n，有多少组解？ | B：必要关键词命中，证明未完全核对 |
| M04 | MIT | graph-degree | 证明任意n>=2的有限连通无向简单图中，必有两个顶点度数相同。 | B：必要关键词命中，证明未完全核对 |

### 高校题型八道补测 X03—X10

以前因限流遗漏，后续 [运行 #39414956219](https://github.com/zm14744/DMate/actions/runs/39414956219) 均返回 HTTP 200、要点命中。这些是**按课程题型抽取/设计的独立题目**，不应称逐字高校原版真题。

| ID | 题型参考 | 模块 | 题目概要 | 结果 |
|---|---|---|---|---|
| X03 | Columbia题型参考（非逐字原题） | function | 设S=R\\{1}, f:S→R, f(x)=(x+1)/(x-1)。f是否满射到R？ | B：要点命中 |
| X04 | MIT题型参考（非逐字原题） | combinatorics | 从8个互不相同的人中选3人组成委员会，共有多少种？ | B：要点命中 |
| X05 | MIT题型参考（非逐字原题） | graph | 完全二分图K(3,3)是否存在欧拉回路？ | B：要点命中 |
| X06 | MIT题型参考（非逐字原题） | logic | 命题 (p→q) 与 (¬p∨q) 是否逻辑等价？ | B：要点命中 |
| X07 | MIT题型参考（非逐字原题） | probability | 独立公平硬币投掷10次，恰好5次正面的概率是多少？ | B：要点命中 |
| X08 | Cambridge题型参考（非逐字原题） | relations | 集合{1,2,3}上的等价关系共有多少个？ | B：要点命中 |
| X09 | Cambridge题型参考（非逐字原题） | graph | 路径P5有多少条边？ | B：要点命中 |
| X10 | MIT题型参考（非逐字原题） | counting | 5个不同元素的集合共有多少个子集？ | B：要点命中 |

---

## 五、原始高校 PDF 图片：OCR 与 AI 回答必须分开陈述

这是实际将大学公开原始题图裁切后输入 DMate 的测试，和把文字题干直接发给 `/chat` 完全不同。图片能被访问、HTTP 200、最后答案出现标准数字、**完整边集与箭头正确**分别属于不同证据，不能混为一个“识图成功”。

### 证实有过文字/公式图片识别→解答匹配的样例

- MIT 官方课程 PS7 PDF 题目裁剪 `MIT7-1b`、`MIT7-2a`、`MIT7-2d`、`MIT7-2g`、`MIT7-2h`：在 [运行 #39409933158](https://github.com/zm14744/DMate/actions/runs/39409933158) 中，五张真实 PDF 题目截图的 OCR HTTP 200、文字关键部分命中，后续答案的最终值与 oracle 一致。**这些是组合数学文字/公式截图，不是五道复杂图论图。**
- 瑞士 ETH Zürich 两道图论讲义图片（多重边、同构类），在 [运行 #39422204810](https://github.com/zm14744/DMate/actions/runs/39422204810) 中 OCR 和回答均 HTTP 200，答案要点初步吻合，**仍需复核完整边表**。
- 澳大利亚新南威尔士大学部分原始二部图、同构图、生成树图片曾出现答案符合必要预期，详见 [运行 #39419946690](https://github.com/zm14744/DMate/actions/runs/39419946690)，不计作全图逐边正确认证。

### 实际图论图片逐项结果，特别记录斯坦福

| ID | 原始高校资料 | 图形任务 | 已观察的真实状况 | 证据级别 | 运行 |
|---|---|---|---|---|---|
| CH_ETH_MULTIGRAPH | ETH Zurich（瑞士） | 讲义原图：四顶点多重图，含平行弧线，顶点/边数 | OCR 200、回答符合必要要点；原图拓扑未充分验证 | B | [运行 #39422204810](https://github.com/zm14744/DMate/actions/runs/39422204810) |
| CH_ETH_ISO_CLASSES | ETH Zurich（瑞士） | 讲义原图：八幅三顶点图按同构分4类 | 答案符合必要要点，仍需验证每幅图的边 | B | [运行 #39422204810](https://github.com/zm14744/DMate/actions/runs/39422204810) |
| AU_UNSW_STAR4 | UNSW（澳大利亚） | 原图：4顶点/3边/1棵生成树 | 答案要点相符；拓扑待复核 | B | [运行 #39419946690](https://github.com/zm14744/DMate/actions/runs/39419946690) |
| AU_UNSW_BIP_A | UNSW（澳大利亚） | 原图 a：判断二部图 | 答案要点相符；拓扑待复核 | B | [运行 #39419946690](https://github.com/zm14744/DMate/actions/runs/39419946690) |
| AU_UNSW_BIP_B | UNSW（澳大利亚） | 原图 b：奇环与二部图 | 答案要点相符；拓扑待复核 | B | [运行 #39419946690](https://github.com/zm14744/DMate/actions/runs/39419946690) |
| AU_UNSW_ISO_A | UNSW（澳大利亚） | 图15(a)图同构 | 答案要点相符；拓扑待复核 | B | [运行 #39419946690](https://github.com/zm14744/DMate/actions/runs/39419946690) |
| AU_UNSW_ISO_B | UNSW（澳大利亚） | 图15(b)图非同构 | 答案要点相符；拓扑待复核 | B | [运行 #39419946690](https://github.com/zm14744/DMate/actions/runs/39419946690) |
| AU_UNSW_LOOP_EDGE | UNSW（澳大利亚） | 无向图自环与孤立顶点 | 答案关键词相符；端点待核验 | B | [运行 #39419946690](https://github.com/zm14744/DMate/actions/runs/39419946690) |
| US_CORNELL_ISO | Cornell（美国） | 正式期末 Q10 双图同构 | 图片路径曾答出预期结论；多次仍出现无法验证，提供核对边集时可判定 | B/C | [运行 #39419946690](https://github.com/zm14744/DMate/actions/runs/39419946690) |
| MIT05_P3 | MIT（美国） | PS4 原始8顶点交叉边图：直径5、色数3 | 文字边集标准解答通过；图片OCR曾添加假边；最新安全提示核对 | C，图片未完全通过 | [运行 #39454759405](https://github.com/zm14744/DMate/actions/runs/39454759405) |
| MIT05_FOUR | MIT（美国） | 课程习题中的4幅平面图同构分组 | 早期答案要点符合；后续识别/源访问不稳定 | C | [运行 #39429345178](https://github.com/zm14744/DMate/actions/runs/39429345178) |
| STANFORD_TREE6 | Stanford（美国） | 6幅六顶点非同构树（教师题解图片） | 早期曾错误计算、擅自改题；修复后识别不确定会停止猜测。**防错机制通过≠正确解出了题** | C：安全防错通过 | [运行 #39454759405](https://github.com/zm14744/DMate/actions/runs/39454759405) |
| HKUST_PETERSEN | HKUST（中国香港） | Petersen 图顶点/边数/平面性 | 答案数字曾相符；历史边列表与自报边数矛盾 | C：未完成结构验收 | [运行 #39429345178](https://github.com/zm14744/DMate/actions/runs/39429345178) |
| HKUST_POLY | HKUST（中国香港） | 正多面体图：八面体/十二面体/二十面体 | 图形信息不充分时进入安全复核 | C：安全防错 | [运行 #39429345178](https://github.com/zm14744/DMate/actions/runs/39429345178) |
| INDIA_BITMESRA_ISO | BIT Mesra（印度） | 2018期末6(a)：两张K4同构与交叉点 | 图形不确定时提示人工核对，非完整作答通过 | C：安全防错 | [运行 #39441305701](https://github.com/zm14744/DMate/actions/runs/39441305701) |
| NJU_DIRECTED | 南京大学（中国） | 原始三幅有向图的强连通与弱连通 | 旧版曾误判图2；新版本不确定时会核对箭头 | C：安全防错 | [运行 #39454759405](https://github.com/zm14744/DMate/actions/runs/39454759405) |
| CAMBRIDGE_K6 | Cambridge（英国） | 讲义 K6 彩色着色图/15条边 | 必要答案数字曾命中；逐边仍需人工核对 | B/C | [运行 #39429345178](https://github.com/zm14744/DMate/actions/runs/39429345178) |
| CN_SJTU_EULER3 | 上海交通大学（中国） | 三幅欧拉图 | 旧版明确错误/新版不可评分；不纳入通过样本 | D：历史错误 | [运行 #39419946690](https://github.com/zm14744/DMate/actions/runs/39419946690) |
| JP_AIZU_ISO | 会津大学（日本） | 上下两图同构 | 旧版明确错误/新版不可评分；不纳入通过样本 | D：历史错误 | [运行 #39419946690](https://github.com/zm14744/DMate/actions/runs/39419946690) |
| SG_NUS_SPANNING | NUS（新加坡） | 原图生成树数目 | 原始文件取得失败，无有效OCR/答题验证 | D：题源失败 | [运行 #39419946690](https://github.com/zm14744/DMate/actions/runs/39419946690) |
| SG_NUS_MST_EXAM | NUS（新加坡） | 带权图最小生成树 | 原始文件取得失败，无有效OCR/答题验证 | D：题源失败 | [运行 #39419946690](https://github.com/zm14744/DMate/actions/runs/39419946690) |
| BR_UTFPR_ISO1、ISO2、BIPARTITE | UTFPR（巴西） | 同构/二部图三幅公开课程原图 | 来源文件无法获取，不计测试成功 | D：题源失败 | [运行 #39420969053](https://github.com/zm14744/DMate/actions/runs/39420969053) |

**Stanford 六顶点树特别说明**：曾有一次回答把图同构计数做错，甚至改变所求问题。之后 DMate 新增逐图顶点核验、边集双重核对与“图形不确定时不猜答案”的边界。最近的 [运行 #39454759405](https://github.com/zm14744/DMate/actions/runs/39454759405) 记录为 `SAFE_UNCERTAIN_REVIEW`，即**安全防错测试通过**，**不能把它写作“斯坦福六棵树全部准确解答通过”**。

图形测试源码与原始大学 URL、PDF 页码、裁剪框均可查：[全球原图清单](https://github.com/zm14744/DMate/blob/main/tests/global_graph_picture_benchmark.py)、[名校图形专测](https://github.com/zm14744/DMate/blob/main/tests/curated_university_graph_images.py)、[国内作业 OCR 清单](https://github.com/zm14744/DMate/blob/main/tests/chinese_university_regression.py)。图像、完整 OCR 和 AI 回复通常归档在上述工作流的 **Artifacts** 中；资料源失效和网络/配额问题也照实记录。

---

## 六、工程防错与质量验证：有发现、有修复、有边界

| 来自实际高校测试的故障 | 代码层面的修复/控制 | 证据 |
|---|---|---|
| MIT 图像将交叉边误识为新边，直径/色数随之错 | 单图逐边独立审图；度数和边表校验；只有核实完整边集才允许确定性图论求解 | [图形审查控制](https://github.com/zm14744/DMate/blob/main/graph_answer_integrity.py)、[确定性图算法](https://github.com/zm14744/DMate/blob/main/graph_exact_solver.py) |
| 南京大学有向图误把不连通图判弱连通 | 有向边方向二次校验、矛盾时暂停得出结论 | [图形历史回归](https://github.com/zm14744/DMate/blob/main/tests/test_historical_university_failures.py) |
| Stanford 六棵树顶点数/同构数量误读与“另出一道题” | 区分原题求解与练习生成；对多图完整边集未核实时谨慎回答 | [同上](https://github.com/zm14744/DMate/blob/main/tests/test_historical_university_failures.py) |
| HKUST Petersen 图宣称边数和边列表互相矛盾 | 结构数量不一致校验与人工复核提示 | [图形核验代码](https://github.com/zm14744/DMate/blob/main/graph_answer_integrity.py) |
| 南京大学幂集计数题曾把正确值2算为4；逻辑题生造子题 | 集合与逻辑的确定性边界审查 | [解答一致性校验](https://github.com/zm14744/DMate/blob/main/solution_integrity.py) |
| 普通 /chat 曾整体 HTTP 500 | 初始化当前请求问题，加入真实 Flask HTTP 路由回归 | [HTTP故障回归](https://github.com/zm14744/DMate/blob/main/tests/test_chat_http_regression.py) |

质量保障入口：[大学历史故障回归](https://github.com/zm14744/DMate/blob/main/tests/test_historical_university_failures.py)、[图像 CI 工作流](https://github.com/zm14744/DMate/blob/main/.github/workflows/test-image-recognition.yml)、[运行 #39452599511](https://github.com/zm14744/DMate/actions/runs/39452599511)、[运行 #39454759002](https://github.com/zm14744/DMate/actions/runs/39454759002)。最近一次 [运行 #39454759405](https://github.com/zm14744/DMate/actions/runs/39454759405) 为**当时部署版本**的联合通过记录（8道SJTU题与MIT/Stanford/NJU三张图片的安全核对）；不能将静态代码 CI 通过误读为生产OCR准确率证明。

### 推荐用于竞赛报名材料/路演的可引用文字

> DMate 基于高等教育出版社《离散数学（第3版）》、MIT OpenCourseWare 和 Rosen 离散数学教材等公开学术资源，自主构建覆盖命题逻辑、集合与关系、计数与组合、图论等领域的**10模块、68节点离散数学学习知识图谱**。项目建立具有来源溯源与自动化证据的国内外高校课程题库：在既有真实运行日志中，美国高校官方课程题中文改写样例有**33道**至少一次给出与独立标准结果一致的最终答案，南京大学与上海交通大学**28道**文字课程题中有**27道**通过必要答案要点检验，中国科学技术大学**7道**课程讲义例题也完成同级测试。针对交叉线、重边、有向箭头及多幅图同构等复杂图片，项目建立独立结构核验与不确定性保护，确保不能确认图形时尽量不产生无根据的确定性结论。课程依据、测试脚本、大学原始来源及 GitHub Actions 记录均公开可查。

**不能使用的表述**：“通过 MIT/斯坦福等高校官方认证”“100% 准确识别世界名校真题”“全部高校图形题解答正确”“所有题都来自真实期末试卷”。这些说法缺乏现有证据，不宜进入竞赛作品或答辩材料。

### 溯源索引

- [课程知识 JSON](https://github.com/zm14744/DMate/blob/main/knowledge_graph.json) · [图谱说明](https://github.com/zm14744/DMate/blob/main/docs/KNOWLEDGE_GRAPH.md) · [公开资料文献目录](https://github.com/zm14744/DMate/blob/main/docs/REFERENCES.md)
- [中文原课程题、USTC讲义和原始作业图片测试](https://github.com/zm14744/DMate/blob/main/tests/chinese_university_regression.py)
- [MIT/Cornell/Berkeley官方题改写与参数变式 oracle](https://github.com/zm14744/DMate/blob/main/tests/university_verified_cases.json)
- [美国高校数值精确判分代码](https://github.com/zm14744/DMate/blob/main/tests/university_answer_benchmark.py)
- [全球原题图像列表](https://github.com/zm14744/DMate/blob/main/tests/global_graph_picture_benchmark.py) · [斯坦福/MIT/NJU等原图案例](https://github.com/zm14744/DMate/blob/main/tests/curated_university_graph_images.py)
- [中国高校原始测试运行](https://github.com/zm14744/DMate/actions/runs/39414956219) · [中科大 7/7](https://github.com/zm14744/DMate/actions/runs/39416095215) · [联合线上复核](https://github.com/zm14744/DMate/actions/runs/39454759405)
- [ETH 原图测验](https://github.com/zm14744/DMate/actions/runs/39422204810) · [澳大利亚/日本等原图历史测试](https://github.com/zm14744/DMate/actions/runs/39419946690)

---

**记录性质与时间边界**：这是历史证据汇编，不是由所列高校出具的审查报告。2026-10-21 汇编时未再次执行所有题目的在线推理；统计仅对应明确的历史 GitHub Actions 日志及其固定题号。未来模型、环境、题图裁切变化时应重新核对结论。
