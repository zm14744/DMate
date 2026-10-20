# DMate 高校离散数学真题：分阶段回归测试与纠错报告

日期：2026-10-20。测试站点：https://dmate.zeabur.app

## 1. 试题来源与口径

新增 tests/university_verified_cases.json **60 个用例**：其中 40 个为 MIT 6.042J、Cornell CS2800、UC Berkeley Math55 公开试题的数学等价转述（official_paraphrase），20 个为明确标记的参数变式（derived_variant），绝不称全部60题为原卷。覆盖组合计数、重复排列、图论、证明与归纳、逻辑、数论、RSA、同余、等价关系和条件概率等；偏序、格、群与布尔代数覆盖还不充分。

官方来源：
- MIT PS7 原卷：https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/4791b8cd8b7a492119f5b67497490bcb_ps7.pdf
- MIT PS7 解答：https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/908f6c3c87842d1a47ded755a8a6f843_ps7sol.pdf
- MIT PS4 原卷：https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/587366ef0ee07f57ed41715559224224_ps4.pdf
- MIT PS4 解答：https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/56bb1f08b01137f2c65762752c629b20_ps4sol.pdf
- Cornell CS2800 2016 Fall final：https://www.cs.cornell.edu/courses/cs2802/2020fa/2800finalsol-16fa.pdf
- UC Berkeley Math55 final：https://math.berkeley.edu/~ribet/55/final_sols.pdf

## 2. 60 道文字题首轮运行

链接：https://github.com/zm14744/DMate/actions/runs/39407126952

首轮独立输入的60次 chat 均 HTTP 200；当时自动评分 54 个答案匹配、2个疑似错误、4个数学格式不识别。逐项复核得出：

- Berkeley Bayes 疑似错误：题库只发了“在上一题的条件下”，但是脚本独立对话没有前一题信息，DMate 竟自行编造概率，输出2/3。原输入缺条件，因此不能算正确输入下纯推理错误。已将本题改为自含0.3、0.9、0.2三个概率，重测正确返回27/41，并新增禁止无数据凭空补全上一题的 guard。
- Cornell RSA 原答案键错误：官方解答把 4^5 mod21 误算成4；独立复算 1024 mod21=16，DMate 当时回答16是**正确的**。标准答案已改16并新增复算单元测试。
- 四个“不可解析”其实是正确的 MathJax 分数形式，已修正自动判分；不能将数学格式的正确公式算作数学错误。
- 后续自动重复启动60题造成大量 HTTP429，故该昂贵工作流已改成**手动触发、单组并发、降速**；严格模式下漏测/429标为 INCONCLUSIVE，不允许以绿色运行代表60题全过。

说明：答案匹配不能保证证明严谨。60个样本也不能当成总体准确率。

## 3. 更重要的两处真实“识别正确，解题错误”

来自 MIT PS7 原始试卷图像：https://github.com/zm14744/DMate/actions/runs/39407397744 与 https://github.com/zm14744/DMate/actions/runs/39409251112 。

**MIT Problem 1(b)：20本排成一行的书选6本，任意两本不能相邻。** 正确公式 C(20-6+1,6)=C(15,6)=5005。实际一次使用人工核对的完全正确题干时，DMate 给出【结果】2002；同一道题其他次数又给出5005。这是推理随机不一致，不能归责于 OCR。

**MIT Problem 2(a)：BANANARAMA 重复字母排列。** 原图片中的单词 OCR 正确，但一次识别后解题将本来10个字母错认作11个，得出11!/(5!2!)=166320；正确是10!/(5!2!)=15120。已确认是求解计数错误而不是图像漏识别。

第三轮重复执行五张 MIT 原卷裁剪：OCR 请求 5/5 HTTP200，必要字符与部分关键语义初筛5/5，人工转录正确文字与 OCR 文字各5/5在本轮返回正确最终数值：https://github.com/zm14744/DMate/actions/runs/39409933158 。**请注意必要字符通过不等于完整 OCR 逐字精确，某次5/5也不能抹去前两次真正的数学错误。**

## 4. 已在代码中针对性修复

- math_answer_guard.py：在完全识别条件时独立计算不相邻选书的 C(n-k+1,k) 公式；若模型最后答案矛盾，直接替换错误推导与最终数字。
- 同一模块对明确的单个大写英文单词进行重复字母频率统计，独立计算 n!/product(m_i!)；即使最后数字正确，中间却声称BANANARAMA有11个字母，也会重写错误推导。
- 新增普通 DMate 末行“答案是……”“因此共有……种”等表达识别，不再局限测试专用的【结果】字样；不去搜索过程中偶然出现的数字充当正确最终值。
- 多题同卷用户只问第(a)/(b)小题时，不得让另一题的纠错代码覆盖正在回答的小题。
- answer_context_guard.py：仅一条问题引用缺失的上一题数据时不编造概率；真的存在上文或题目已完整给出数值，不拦截。
- app.py：调用上述确定性检查；/health 中的 answer_verification_version 用于验证 Zeabur 部署是否包含最新修改。
- tests/test_math_answer_guard.py 与 tests/test_answer_context_guard.py 持续防回归。对应 CI：https://github.com/zm14744/DMate/actions/runs/39410358814 及其更新版。
- tests/test_university_oracles.py 独立复算部分 gold，防止错误高校答案反过来污染软件。

## 5. 测试层次和剩余风险

不同阶段要独立看：原卷OCR/数学符号 -> 必要数学条件人工审校 -> 完全正确文字下解题 -> OCR结果下解题 -> 最终答案独立判分 -> 证明逻辑是否正确。识别成功、HTTP200、某次答案正确、CI绿色均不代表所有阶段完全正确。

本次证实并**在 GitHub 代码层针对性修复**了上述两处真正的求解错误，及一处缺条件臆造前提缺陷。仍须以 Zeabur 线上 /health 的版本标记确认部署，再实际复测新保护分支。复杂图结构、多小问、长证明、代数与格等仍不保证100%正确。

相关脚本：
- tests/university_verified_cases.json（60题）
- tests/university_answer_benchmark.py（独立答案oracle）
- tests/university_image_answer_benchmark.py（原卷图片OCR与解题对照）
- tests/test_university_oracles.py、tests/test_math_answer_guard.py、tests/test_answer_context_guard.py
- GitHub Actions University Verified Answer Benchmarks 与 University OCR versus Reasoning Benchmark：按需手动触发，避免连发带来的付费调用和HTTP429。
