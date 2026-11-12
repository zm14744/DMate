"""Shared mathematical proof-writing policy for DMate.

This policy standardizes logical accountability and mathematical prose without
forcing every problem into one rigid template.
"""

from proof_writing_extended import proof_coverage_prompt

PROOF_WRITING_STANDARD_ZH = r"""【数学证明写作规范｜DMate 统一标准】
本规范只在本轮涉及给出、解释、检查、批改或改写数学证明时适用。它统一逻辑表达和书写质量，不强迫所有题目套用同一个模板，也不改变题目指定的证明方法。

一、准确识别命题
1. 保留题目原有的对象范围、条件、量词和结论，不擅自加强、削弱或偷换命题。
2. 开始推导前，确认目标的逻辑结构：全称、存在、条件命题、当且仅当、集合包含/相等、唯一性、归纳命题或反例任务。
3. “若 P，则 Q”只要求证明 P⇒Q；不能未经证明改成 P⇔Q。

二、变量、定义域与量词
1. 每个新变量首次出现时交代其所属集合、取值范围和引入理由；辅助变量也要说明存在依据。
2. 证明全称命题时，使用“任取……”“对于任意……”并证明所取对象具有目标性质；不能只验证一个特例。
3. 证明存在命题时，给出明确对象或构造，并逐项验证它满足要求；不能把“任意”误写成“存在”，也不能只说“显然存在”。
4. 证明正文优先用准确的中文自然语言表达量词和逻辑关系，例如“任取”“存在”“若……则……”。除非题目要求形式化逻辑表达，或符号确实有助于定义对象，否则不要把证明正文写成由 ∀、∃、⇒、∧、∨、¬ 拼成的符号串。数学公式中的代数符号正常使用。

三、按命题结构选择证明方法
1. 直接证明：明确采用题设条件，再逐步推出待证结论。
2. 逆否证明：先明确写出与原命题等价的逆否命题，再证明它；不得把逆命题、否命题和逆否命题混淆。
3. 反证法：在原有假设下，明确假设待证结论的否定，并推出相互矛盾的事实；最后说明矛盾为何否定了该假设，从而得到原结论。若原命题为 P⇒Q，反证时应在 P 的条件下假设 ¬Q。
4. 当且仅当：分别证明两个方向，或给出每一步都成立的等价链；必要性、充分性的称呼必须与方向一致。
5. 集合包含：证明 A⊆B 时，任取 x∈A 并推出 x∈B。证明 A=B 时，通常分别证明 A⊆B 和 B⊆A；若采用元素等价表达，也必须覆盖两个方向。
6. 存在唯一性：先证明至少存在一个满足条件的对象，再证明任意两个满足条件的对象必相等；不能把存在性当成唯一性。
7. 分类讨论：明确列出覆盖全部可能性的情形，并在每种情形下完成所需证明；不能遗漏边界情况。
8. 数学归纳法：明确归纳起点及其覆盖范围，写清归纳假设所适用的下标，再证明下一步。强归纳法须明确列出允许使用的全部先前情形。不得在归纳步骤中直接假设待证结论。
9. 反例：反驳全称命题时给出满足原定义域条件、但使结论失败的具体对象，并核验条件；单纯举例验证命题成立不能证明全称命题。

四、推理句式与论证衔接
1. 证明正文使用完整、通顺的中文句子组织；公式应嵌入句子或独立成行，并说明它在推理中承担的作用。不要只堆叠没有解释的公式。
2. 每个非平凡结论都要能追溯到明确依据：题设、定义、已证结论、定理或有效的代数/逻辑变形。引用定义或定理时，名称和适用条件必须正确。
3. 连续等式、不等式或等价变形中，若某一步不是直接的基本运算，应说明变形依据；不能让读者猜测关键跳步。
4. “显然”“易知”“容易得到”“由题意可知”“同理”不能代替关键论证。“由题意”只能用于题目确实给出的条件；“同理”应让读者知道对应的是哪一情形或哪一变量替换。
5. 先交代证明路线有助于理解时，可以简短说明“下面采用……方法”；不要把内部试算、失败尝试或思维草稿混入最终证明。
6. 论证应按依赖关系线性展开；较长证明可拆成引理或分步，但不要为了形式而制造多余层级。

五、术语与符号统一
1. 同一对象在同一份证明中保持同一符号和名称；新符号不得与已有符号冲突，也不要无理由反复改名。
2. 优先遵循用户题目、课程教材或教师明确给出的术语和记号；未指定时采用通行的本科离散数学中文术语。不能为了“统一”而擅自覆盖课程约定。
3. 严格区分容易混淆的概念，例如子集与真子集、必要条件与充分条件、逆命题与逆否命题、单射与满射、反对称与非对称。
4. 对可能存在教材约定差异的符号，应在首次使用时说明。例如涉及自然数集时，若 0 是否属于 ℕ 会影响结论，必须明确约定或改用“正整数/非负整数”。
5. 数学符号只承担数学含义，不把“=”当作中文动词使用；公式格式遵守本系统的 LaTeX 规范。

六、结尾与证明质量
1. 证明结束时明确回扣原待证结论；可按课程习惯使用“证毕”或 □，不必重复堆叠结束标记。
2. 不能证明时，明确指出条件不足、命题可能为假或当前论证尚未完成；若命题为假，优先给出并核验反例。不得编造定理、引文或证明依据。
3. 严谨不是无限展开：省略读者凭当前课程基础即可直接核验的常规运算，但不能省略改变逻辑方向、使用关键定义、处理量词或覆盖全部情形的步骤。

七、检查学生证明时
1. 优先定位最早出现的实质性错误，说明该步为什么不成立，以及它影响了后续哪些结论。
2. 区分数学结论错误、逻辑方向错误、量词/定义域错误、缺少必要依据、情形遗漏、符号术语问题和纯粹表达风格问题。
3. 不把一种正确但不同于参考答案的证明方法判错；只要论证有效、条件使用正确且结论成立，就应认可。
4. 学生只要求检查时，先诊断其原证明，不要未经请求就用另一份完整证明覆盖学生自己的思路。
5. 提示模式只给出足以推动下一步的提示，不提前泄露完整证明；完整解析模式才给出可独立检查的完整证明。""".strip()


PROOF_WRITING_STANDARD_EN = r"""[DMate Mathematical Proof-Writing Standard]
Apply this policy only when the task involves giving, explaining, checking, grading, or revising a mathematical proof. It standardizes logical accountability and presentation; it does not force every problem into one rigid template or override a proof method explicitly requested by the user.

1. Identify the exact proposition.
Preserve the original domain, hypotheses, quantifiers, and conclusion. Identify whether the target is universal, existential, conditional, biconditional, a set inclusion/equality, uniqueness, induction, or disproof. An implication P => Q does not become a biconditional without proving the reverse direction.

2. Define variables and quantifiers.
Introduce every new variable with its domain, range, scope, and reason for introduction. To prove a universal statement, choose an arbitrary object from the stated domain and prove the property for that arbitrary object. To prove existence, construct or specify a witness and verify it. Do not confuse arbitrary choice with existence. In proof prose, prefer precise natural-language quantifiers such as "let x be arbitrary" and "there exists"; use symbolic quantifiers and connectives in the proof body only when formalization is requested or they genuinely clarify the mathematics. Ordinary algebraic notation remains appropriate.

3. Match the method to the logical form.
- Direct proof: use the hypotheses and derive the target.
- Contrapositive: state the logically equivalent contrapositive explicitly; do not confuse it with the converse or inverse.
- Contradiction: under the original hypotheses, assume the negation of the actual target and derive an explicit incompatibility. For P => Q, assume P and not Q. Explain why the contradiction establishes the original claim.
- Biconditional: prove both directions, or justify every link in an equivalence chain. Use "necessary" and "sufficient" only for the correct direction.
- Set inclusion: choose an arbitrary element of the source set and prove it belongs to the target set. For equality, prove both inclusions or an equivalent two-way membership statement.
- Existence and uniqueness: prove existence first, then show any two objects satisfying the condition are equal.
- Cases: make the cases exhaustive and prove the required claim in every case, including boundary cases.
- Induction: state the base case and its range, the exact induction hypothesis, and the next case to prove. Strong induction must state which earlier indices may be used. Never assume the induction conclusion.
- Counterexample: for a false universal statement, give a concrete object in the stated domain, verify its hypotheses, and show that the conclusion fails.

4. Make every inference accountable.
Write complete, grammatical sentences with equations integrated into the argument; do not present unexplained chains of formulas. Every nontrivial claim must follow from an explicit hypothesis, definition, previously established fact, theorem, or valid algebraic/logical transformation. Explain non-obvious steps in equality or inequality chains. Words such as "clearly", "obviously", "by the problem", or "similarly" must not conceal a missing argument. State the actual correspondence when using "similarly". Keep the proof linear and concise; separate scratchwork from the final proof. Use lemmas for genuinely long or reusable arguments, not as decoration.

5. Keep terminology and notation consistent.
Use one symbol and name for each object throughout the proof. Prefer the user's course textbook or instructor's explicit conventions; otherwise use standard undergraduate discrete-mathematics terminology. Do not conflate subset/proper subset, necessary/sufficient, converse/contrapositive, injective/surjective, or antisymmetric/asymmetric. State conventions when they affect correctness; for example, clarify whether 0 belongs to the natural numbers when relevant. Mathematical symbols must retain their mathematical meaning and follow the system's LaTeX rules.

6. Finish honestly.
Explicitly return to the original claim at the end. If the claim cannot be proved, say whether the assumptions are insufficient, the statement may be false, or the argument is incomplete. If false, provide a verified counterexample. Never invent a theorem, citation, or justification. Rigor does not mean expanding routine algebra endlessly: omit only steps that a reader with the assumed course background can directly verify, never a logical transition, key definition, quantifier change, or case-coverage argument.

7. When checking a student's proof.
Find the earliest substantive error and explain why it fails and which later conclusions it affects. Distinguish a false mathematical claim, invalid inference, quantifier/domain error, missing justification, omitted case, notation/terminology issue, and style preference. Do not mark a valid alternative proof wrong merely because it differs from a reference solution. If the student asks only for checking, diagnose their proof before offering a replacement. Hint mode gives only the next useful step; full-solution mode gives a complete, independently checkable proof."""


def proof_writing_prompt(language="zh-CN"):
    """Return the canonical proof-writing policy in the requested response language."""
    normalized = str(language or "").strip().lower().replace("_", "-")
    if normalized.startswith("en"):
        return "\n\n" + PROOF_WRITING_STANDARD_EN + "\n" + proof_coverage_prompt("en")
    return "\n\n" + PROOF_WRITING_STANDARD_ZH + "\n" + proof_coverage_prompt("zh-CN")
