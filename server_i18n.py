"""Request-scoped wording only; never translate stored study content or IDs."""
from __future__ import annotations

import re


def normalize_language(value):
    return "en" if str(value or "").strip().lower().startswith("en") else "zh-CN"


def localized(chinese, english, language="zh-CN"):
    return english if normalize_language(language) == "en" else chinese


def request_language(request):
    """An explicit UI preference wins; browser language must not override it."""
    value = None
    try:
        payload = request.get_json(silent=True) if request.is_json else None
        value = payload.get("language") if isinstance(payload, dict) else None
        if not value and request.mimetype in ("multipart/form-data", "application/x-www-form-urlencoded"):
            value = request.form.get("language")
    except Exception:
        # A malformed or oversized body may already be an error response.
        # Looking up its language must never replace that response with a 500.
        pass
    return normalize_language(value or request.headers.get("X-DMate-Language"))


_ERRORS = {
    "操作过于频繁，请稍后再试": "Too many requests. Please try again later.",
    "当前请求过于频繁，请稍后再试": "Too many requests. Please try again later.",
    "当前回答请求较多，请稍后再试。": "Too many answers are being generated. Please try again shortly.",
    "请求格式不正确": "Invalid request format.",
    "请求格式不正确，请检查提交内容": "Invalid request format. Please check the submitted content.",
    "消息格式不正确，请重新发送": "Invalid message format. Please send the message again.",
    "没有检测到有效消息内容": "No valid message content was received.",
    "没有检测到有效的消息内容。": "No valid message content was received.",
    "请先登录": "Please sign in first.",
    "账号服务暂时不可用，请稍后重试": "The account service is unavailable. Please try again later.",
    "AI 请求内容有误，请稍后重新发送。": "The AI request could not be accepted. Please try sending it again.",
    "AI 服务配置异常，请联系管理员。": "The AI service is not configured correctly. Please contact the administrator.",
    "AI 服务当前不可用，请联系管理员检查账户状态。": "The AI service is unavailable. Please contact the administrator to check the service account.",
    "当前访问人数较多，请稍后再试。": "The service is busy. Please try again shortly.",
    "AI 服务暂时繁忙，请稍后再试。": "The AI service is busy. Please try again shortly.",
    "AI 服务暂时出现异常，请稍后再试。": "The AI service encountered an error. Please try again later.",
    "AI 服务暂时出现异常，请稍后重试": "The AI service encountered an error. Please try again later.",
    "AI 服务暂时出现异常": "The AI service encountered an error.",
    "AI 服务返回格式异常": "The AI service returned an invalid response.",
    "AI 服务尚未完成配置，请联系管理员。": "The AI service has not been configured. Please contact the administrator.",
    "AI 只生成了内部推理，未输出解答正文。": "The AI did not return an answer. Please try again.",
    "AI 服务响应时间过长，请稍后重新发送。": "The AI service took too long to respond. Please try again.",
    "暂时无法连接 AI 服务，请检查网络后重试。": "Could not connect to the AI service. Please check your connection and try again.",
    "AI 服务暂时不可用，请稍后重试。": "The AI service is unavailable. Please try again later.",
    "AI 服务暂时不可用，请稍后重试": "The AI service is unavailable. Please try again later.",
    "AI 回答未完整结束，请重新发送。": "The answer was incomplete. Please send your request again.",
    "AI 服务没有生成有效回答，请重新发送。": "The AI did not return a valid answer. Please send your request again.",
    "AI 服务没有生成有效回答，请重新发送": "The AI did not return a valid answer. Please send your request again.",
    "本次回答未能完成，请稍后重试。": "The answer could not be completed. Please try again.",
    "回答等待时间过长，已停止本次请求，请稍后重试。": "The answer took too long. This request has stopped; please try again.",
    "当前题目或本轮消息过长，请拆分后发送；系统没有截断题目条件。": "The current question or message is too long. Please split it into smaller requests; the question has not been truncated.",
    "当前题目及要求超出上下文容量，请拆分后发送。": "The question and instructions exceed the context limit. Please split the request.",
    "当前题目及必要上下文超过模型容量，请拆分题目后重试；系统未截断题目条件。": "The question and required context exceed the model's capacity. Please split the request; the question has not been truncated.",
    "当前消息提到了上一题的条件，但这次请求中没有该题的完整信息。请把已知条件一并发来，避免根据猜测得到错误答案": "This request refers to a previous question, but its full conditions are missing. Please include them so the answer does not rely on guesses.",
    "练习参照题格式不正确，请重新选择题目": "The reference question is invalid. Please select it again.",
    "缺少本次出题请求": "The exercise-generation request is missing.",
    "参照题和出题要求过长，请精简后重试": "The reference question and exercise requirements are too long. Please shorten them and try again.",
    "出题内容被截断，请重新生成。": "The exercise was truncated. Please generate it again.",
    "生成题目的数学格式不完整，请重新生成。": "The exercise contains incomplete mathematical formatting. Please generate it again.",
    "这次没有生成有效题目，请重试": "No valid exercise was generated. Please try again.",
    "这次没有生成有效题目，请重新出题": "No valid exercise was generated. Please request another exercise.",
    "请重新出题": "Please request another exercise.",
    "请从已确认的题目提出解题或讲解请求；生成新练习时不要沿用图片确认。": "Ask for a solution or explanation of the confirmed question. Do not reuse image confirmation when generating a new exercise.",
    "当前请求与已确认题目不一致，请从对应图片重新发起解题。": "This request does not match the confirmed question. Please start again from the corresponding image.",
    "暂时无法核对题目确认状态，请稍后再试。": "The question's confirmation status could not be checked. Please try again later.",
    "题目确认暂时无法保存，请稍后再试。": "The question confirmation could not be saved. Please try again later.",
    "请先确认图形结构。": "Please confirm the diagram structure first.",
    "图形已修改，请重新确认。": "The diagram has changed. Please confirm it again.",
    "图形描述数据过大": "The diagram description request is too large.",
    "图形描述请求过于频繁": "Too many diagram description requests. Please try again shortly.",
    "缺少已确认的图形": "The confirmed diagram is missing.",
    "已确认图形无法核验": "The confirmed diagram could not be verified.",
    "概念分析过于频繁，请稍后重试。": "Too many concept-analysis requests. Please try again shortly.",
    "画图指导过于频繁，请稍后重试。": "Too many drawing-guidance requests. Please try again shortly.",
    "画图内容过大，请分开咨询。": "The drawing is too large. Please ask about smaller parts separately.",
    "语音输入过于频繁，请稍后重试。": "Too many dictation requests. Please try again shortly.",
    "没有收到录音，请重新录音。": "No recording was received. Please record again.",
    "文字区域识别过于频繁，请稍后重试": "Too many text-recognition requests. Please try again shortly.",
    "图片识别请求过于频繁，请稍后再试。": "Too many image-recognition requests. Please try again shortly.",
    "缺少原图或识别任务": "The source image or recognition task is missing.",
    "缺少原图或识别任务。": "The source image or recognition task is missing.",
    "单张图片不能超过 20MB": "Each image must be no larger than 20 MB.",
    "单张图片不能超过 20MB。": "Each image must be no larger than 20 MB.",
    "文字识别服务异常，请重试。": "Text recognition failed. Please try again.",
    "选区轮廓过于复杂": "The selected outline is too complex.",
    "文字 OCR 暂不可用，可继续手动输入": "Text recognition is unavailable. You can still enter the text manually.",
    "选区文字识别未完成，可调整范围或手动输入": "Text recognition did not finish. Adjust the selection or enter the text manually.",
    "图形选区无效，请重新框选。": "The diagram selection is invalid. Please select it again.",
    "当前识别任务较多，请稍后重新识别此选区。": "Recognition is busy. Please try this selection again shortly.",
    "选区无法读取，请扩大或调整范围。": "The selected area could not be read. Please expand or adjust it.",
    "选区图形识别未完成，请重试。": "Diagram recognition did not finish. Please try again.",
    "图形类型扫描过于频繁，请稍后再试": "Too many diagram-type scans. Please try again shortly.",
    "缺少原图或图形识别任务": "The source image or diagram-recognition task is missing.",
    "图形轮廓过于复杂": "The diagram outline is too complex.",
    "所选区域不是可识别的图像": "The selected area is not a recognizable image.",
    "AI 没有返回题目文本": "The AI did not return a question.",
    "AI 返回的不是可作答的数学题": "The AI response is not an answerable mathematics question.",
    "生成题目没有有效的隐藏答案": "The exercise has no valid stored answer.",
    "题目与隐藏答案不一致": "The question and its stored answer are inconsistent.",
    "题目分析失败": "The question could not be analyzed.",
    "题目分类结果无效": "The question classification is invalid.",
    "生成题偏离指定学科": "The exercise does not match the requested subject.",
    "生成题未能确认指定知识点": "The requested topic could not be verified in the exercise.",
    "生成题偏离指定知识点": "The exercise does not match the requested topic.",
    "生成的题目条件不完整或隐藏答案缺少小问结果": "The exercise has incomplete conditions or its stored answer omits a subquestion.",
    "生成的练习偏离了参照题所属模块。": "The exercise does not match the reference question's subject.",
    "生成的练习偏离了参照题核心知识点。": "The exercise does not match the reference question's core topics.",
    "不支持强制覆盖云端数据，请合并后重试": "Cloud data cannot be forcibly overwritten. Please merge the changes and try again.",
    "云端数据已经被其他设备更新": "Another device has updated the cloud data.",
    "修改恢复码失败，请稍后再试": "The recovery code could not be changed. Please try again later.",
    "同步失败，请稍后再试": "Sync failed. Please try again later.",
    "同步数据无法序列化": "The sync data could not be encoded.",
    "同步数据格式不正确": "The sync data format is invalid.",
    "同步数据过大，请先清理部分历史记录": "The sync data is too large. Please remove some old records first.",
    "同步版本、分段或摘要无效": "The sync version, section, or digest is invalid.",
    "同步版本号不正确": "The sync version is invalid.",
    "同步版本号无效": "The sync version is invalid.",
    "图片任务与原图不匹配，请重新选择图片。": "The image task does not match the source image. Please select the image again.",
    "图片内容为空，请重新上传": "The image is empty. Please upload it again.",
    "图片复核暂时不可用": "Image verification is unavailable.",
    "图片无效或分辨率过大，请重新选择图片": "The image is invalid or its resolution is too large. Please choose another image.",
    "图片识别未完成，模型或网络请求失败，请重试或手动补充。": "Image recognition did not finish because the model or network request failed. Please retry or complete it manually.",
    "图片过大，请上传不超过 20MB 的图片": "The image is too large. Please upload an image no larger than 20 MB.",
    "密码不正确": "The password is incorrect.",
    "撤销请求无效": "The cancellation request is invalid.",
    "撤销请求过于频繁，请稍后再试": "Too many cancellation requests. Please try again shortly.",
    "新恢复码需为 8–64 个字符，且不能包含控制字符": "The new recovery code must contain 8–64 characters and no control characters.",
    "本次图形结构识别未完成，请核对原图。": "Diagram-structure recognition did not finish. Please check the original image.",
    "查询期间云端数据已更新，请重新获取版本": "The cloud data changed during this request. Please fetch the version again.",
    "检查云端版本失败": "The cloud version could not be checked.",
    "没有检测到图片，请重新上传": "No image was received. Please upload it again.",
    "注册失败，请稍后再试": "Registration failed. Please try again later.",
    "注销失败，请稍后再试": "Sign-out failed. Please try again later.",
    "注销账号失败，请稍后再试": "The account could not be deleted. Please try again later.",
    "用户名/邮箱或密码不正确": "The username, email, or password is incorrect.",
    "用户名或恢复码不正确": "The username or recovery code is incorrect.",
    "用户名或邮箱已经被使用": "The username or email is already in use.",
    "登录失败，请稍后再试": "Sign-in failed. Please try again later.",
    "绑定邮箱失败，请稍后再试": "The email could not be linked. Please try again later.",
    "识别到的主要是知识点说明或笔记，不是待解答的题目。请上传题目图片": "This image mainly contains explanations or notes rather than a question. Please upload an image of the question.",
    "请使用同一批图片发起解题，不要混用单图结构。": "Start the solution from the same image batch; do not mix it with a single-image structure.",
    "请输入当前密码": "Enter your current password.",
    "请输入恢复码": "Enter your recovery code.",
    "请输入正确的用户名": "Enter a valid username.",
    "读取云端数据失败": "The cloud data could not be loaded.",
    "读取云端更新失败": "Cloud updates could not be loaded.",
    "账号不存在或已被注销": "This account does not exist or has been deleted.",
    "账号服务暂时不可用，请稍后重试；登录状态和本机记录已保留": "The account service is unavailable. Please try again later; your sign-in session and local records have been kept.",
    "这不是可读取的图片，请重新上传。": "This image could not be read. Please upload it again.",
    "这个用户名已经被使用": "This username is already in use.",
    "这个邮箱已经绑定了其他账号": "This email is already linked to another account.",
    "这个邮箱已经绑定了账号": "This email is already linked to an account.",
    "这张图片看起来不是待解答的数学题目。请上传题目图片；如果只是想讨论知识点，可以直接在聊天框输入问题": "This image does not appear to contain a mathematics question. Please upload the question, or type in the chat to discuss a concept.",
    "邮箱或验证码不正确": "The email or verification code is incorrect.",
    "邮箱验证码服务尚未配置，请检查 Brevo 或 SMTP 环境变量": "Email verification is not configured. Please check the Brevo or SMTP environment settings.",
    "重置密码失败，请稍后再试": "The password could not be reset. Please try again later.",
    "题目列表格式不正确": "The question-list format is invalid.",
    "题目复核请求过于频繁，请稍后再试": "Too many question-verification requests. Please try again shortly.",
    "题目识别暂时失败，请稍后重试": "Question recognition failed. Please try again later.",
    "验证码发送失败，请稍后再试": "The verification code could not be sent. Please try again later.",
    "验证码用途不正确": "The verification-code purpose is invalid.",
    "原图任务已失效，请重新上传该图片。": "The source-image task has expired. Please upload the image again.",
    "原图标识无效，请重新选择原图。": "The source-image identifier is invalid. Please select the original image again.",
    "图结构包含无效数据。": "The diagram structure contains invalid data.",
    "结构检查未通过，请核对后再确认。": "The structure did not pass validation. Please review it before confirming.",
    "识别任务标识无效，请重新选择原图。": "The recognition-task identifier is invalid. Please select the original image again.",
    "该任务对应的原图已改变，请新建识别任务。": "The source image has changed. Please start a new recognition task.",
    "该原图任务已失效，请重新选择原图。": "The source-image task has expired. Please select the image again.",
    "请先修正题目结构。": "Please correct the question structure first.",
    "请先修正题目结构中标出的字段。": "Please correct the highlighted fields in the question structure first.",
    "请先核对并确认当前题目结构。": "Please review and confirm the current question structure first.",
    "请先核对并确认本张图片的题目结构。": "Please review and confirm this image's question structure first.",
    "请先补全题干与图结构。": "Please complete the question text and diagram structure first.",
    "这份确认已失效或不属于当前图片，请重新确认。": "This confirmation has expired or belongs to another image. Please confirm again.",
    "题干过长，请拆分后确认。": "The question text is too long. Please split it before confirming.",
    "题目文字已修改，请重新确认后解题。": "The question text has changed. Please confirm it again before requesting a solution.",
    "题目结构已修改，请重新确认后解题。": "The question structure has changed. Please confirm it again before requesting a solution.",
    "题目结构过大，请拆成较小的题目。": "The question structure is too large. Please split it into smaller questions.",
    "同一张图片不能在本次发送中重复出现。": "The same image cannot appear more than once in this request.",
    "请一次发送1至4张已保存的图片。": "Send 1–4 saved images at a time.",
    "请先逐张保存图片的题目结构。": "Please save each image's question structure first.",
    "这些图片的图例内容过长，请分批发送。": "The image legends are too long. Please send the images in smaller batches.",
    "这些图片的题目内容过长，请分批发送。": "The question content is too long. Please send the images in smaller batches.",
    "这些图片的题目结构过大，请分批发送。": "The question structures are too large. Please send the images in smaller batches.",
    "绘图上传过于频繁，请稍后重试。": "Too many drawing uploads. Please try again shortly.",
    "没有检测到绘图图片，请重试。": "No drawing image was received. Please try again.",
    "绘图图片为空或超过上传上限。": "The drawing image is empty or exceeds the upload limit.",
    "用户名需为 2–32 个字符，只使用文字、数字、下划线、点或短横线": "The username must contain 2–32 characters: letters, numbers, underscores, periods, or hyphens.",
    "用户名转换后的长度过长，请缩短用户名": "The normalized username is too long. Please choose a shorter one.",
    "请输入正确的邮箱地址": "Enter a valid email address.",
    "密码不能少于 8 位": "The password must contain at least 8 characters.",
    "密码不能超过 128 位": "The password cannot exceed 128 characters.",
    "请输入用户名或邮箱": "Enter your username or email.",
    "密码长度需为 6–128 个字符": "The password must contain 6–128 characters.",
    "请输入正确的用户名或邮箱": "Enter a valid username or email.",
    "请输入 6 位邮箱验证码": "Enter the 6-digit email verification code.",
    "请先发送邮箱验证码": "Request an email verification code first.",
    "验证码已过期，请重新发送": "The verification code has expired. Please request another one.",
    "验证码错误次数过多，请重新发送": "Too many incorrect verification attempts. Please request a new code.",
    "验证码不正确": "The verification code is incorrect.",
    "验证码发送次数过多，请稍后再试": "Too many verification codes have been requested. Please try again later.",
}


def localize_error(message, language="zh-CN"):
    """Translate known application errors, preserving unknown/provider details."""
    if normalize_language(language) != "en" or not isinstance(message, str):
        return message
    if message in _ERRORS:
        return _ERRORS[message]
    # Some callers add/remove the final full stop. Keep the useful message.
    stripped = message.rstrip("。.! ")
    for suffix in ("", "。"):
        if stripped + suffix in _ERRORS:
            return _ERRORS[stripped + suffix]
    if message.endswith("请重新出题"):
        return localize_error(message[:-5], language) + " Please request another exercise."
    if message.startswith("复测题遗漏核心知识点："):
        points = message.split("：", 1)[1].split("、")
        return "The retest exercise omits core topics: " + "; ".join(topic_label(point, language) for point in points)
    limit = re.fullmatch(r"单条消息过长，请控制在 (\d+) 个字符以内", message)
    if limit:
        return f"This message is too long. Please keep it within {limit.group(1)} characters."
    cooldown = re.fullmatch(r"请 (\d+) 秒后再发送验证码", message)
    if cooldown:
        return f"Please wait {cooldown.group(1)} seconds before requesting another verification code."
    return message


def localize_error_payload(payload, language="zh-CN"):
    if normalize_language(language) != "en" or not isinstance(payload, dict):
        return payload
    if not isinstance(payload.get("error"), str):
        return payload
    translated = localize_error(payload["error"], language)
    return {**payload, "error": translated} if translated != payload["error"] else payload


def difficulty_label(value, language="zh-CN"):
    if normalize_language(language) != "en":
        return value
    return {"简单": "easy", "中等": "medium", "困难": "hard", "未确定": "undetermined"}.get(value, value)


_TOPICS = {
    "命题逻辑": "Propositional logic", "谓词逻辑": "Predicate logic",
    "集合论": "Set theory", "集合": "Sets", "关系": "Relations", "函数": "Functions",
    "数论": "Number theory", "计数与组合": "Counting and combinatorics", "组合计数": "Combinatorics",
    "递推关系": "Recurrence relations", "递推": "Recurrences", "图论": "Graph theory",
    "树": "Trees", "代数结构": "Algebraic structures", "证明方法": "Proof methods",
    "证明与归纳": "Proof and induction", "集合与关系": "Sets and relations",
    "初等数论": "Elementary number theory", "递推与生成函数": "Recurrences and generating functions",
    "命题与真值": "Propositions and truth values", "逻辑联结词": "Logical connectives",
    "真值表": "Truth tables", "逻辑等价": "Logical equivalence", "范式": "Normal forms",
    "命题推理": "Propositional inference", "谓词与个体域": "Predicates and domains",
    "量词": "Quantifiers", "变元与辖域": "Variables and scope",
    "量词推理与否定": "Quantifier inference and negation", "前束范式": "Prenex normal form",
    "直接证明与反证法": "Direct proof and proof by contradiction", "数学归纳法": "Mathematical induction",
    "强归纳法": "Strong induction", "集合运算": "Set operations", "笛卡尔积与关系": "Cartesian products and relations",
    "关系运算": "Operations on relations", "关系性质": "Properties of relations",
    "等价关系与划分": "Equivalence relations and partitions", "偏序关系": "Partial orders",
    "关系闭包": "Closures of relations", "函数与映射": "Functions and mappings",
    "单射满射双射": "Injections, surjections, and bijections", "复合函数": "Function composition",
    "逆函数": "Inverse functions", "整除与素数": "Divisibility and primes",
    "最大公因数与欧几里得算法": "Greatest common divisors and the Euclidean algorithm",
    "同余与模运算": "Congruences and modular arithmetic", "线性同余方程": "Linear congruences",
    "模逆与中国剩余定理": "Modular inverses and the Chinese remainder theorem",
    "欧拉定理与费马小定理": "Euler's theorem and Fermat's little theorem", "RSA公钥密码": "RSA public-key cryptography",
    "基本计数原理": "Basic counting principles", "排列与组合": "Permutations and combinations",
    "二项式定理": "The binomial theorem", "鸽巢原理": "The pigeonhole principle",
    "容斥原理": "Inclusion–exclusion", "生成函数": "Generating functions",
    "递推关系建模": "Modeling with recurrences", "线性齐次递推": "Linear homogeneous recurrences",
    "非齐次递推": "Nonhomogeneous recurrences", "初始条件": "Initial conditions",
    "图的基本概念": "Basic graph concepts", "图同构": "Graph isomorphism",
    "邻接矩阵": "Adjacency matrices", "图的矩阵表示": "Matrix representations of graphs",
    "路径与连通性": "Paths and connectivity", "割点与割边": "Cut vertices and bridges",
    "带权图": "Weighted graphs", "欧拉图": "Eulerian graphs", "哈密顿图": "Hamiltonian graphs",
    "最短路": "Shortest paths", "图着色": "Graph coloring", "平面图": "Planar graphs",
    "二部图": "Bipartite graphs", "拓扑排序": "Topological sorting",
    "支配集、覆盖集与独立集": "Dominating sets, vertex covers, and independent sets", "图匹配": "Graph matchings",
    "树的基本性质": "Basic properties of trees", "根树": "Rooted trees", "生成树": "Spanning trees",
    "最小生成树": "Minimum spanning trees", "矩阵树定理": "The matrix-tree theorem",
    "代数系统": "Algebraic systems", "群与子群": "Groups and subgroups", "同态与同构": "Homomorphisms and isomorphisms",
    "环与域": "Rings and fields", "格与布尔代数": "Lattices and Boolean algebra",
}


def topic_label(value, language="zh-CN"):
    """Display labels only: the corresponding metadata IDs remain unchanged."""
    return _TOPICS.get(value, value) if normalize_language(language) == "en" else value
