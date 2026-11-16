/* Immediate offline-safe fallback; semantic conversation names come from /conversation/title. */
(function (root) {
    'use strict';

    // The labels are summaries of supported mathematical topics, rather than
    // excerpts from the beginning of a question. More specific matches win.
    const topics = [
        ['集合包含关系', 'Set inclusion', /包含关系|子集|真子集|\bsubsets?\b|set inclusion/i],
        ['幂集', 'Power sets', /幂集|power\s*sets?/i],
        ['集合运算', 'Set operations', /集合运算|集合.{0,6}(?:并|交|差|补)|并集|交集|补集|差集|set operations?|union|intersection/i],
        ['笛卡尔积', 'Cartesian products', /笛卡尔积|cartesian products?/i],
        ['等价关系', 'Equivalence relations', /等价关系|equivalence relations?/i],
        ['偏序关系', 'Partial orders', /偏序|哈斯图|partial orders?|hasse/i],
        ['关系闭包', 'Relation closures', /关系闭包|传递闭包|自反闭包|对称闭包|transitive closure|relation closures?/i],
        ['关系性质', 'Relation properties', /自反|反自反|对称性|反对称|传递性|reflexiv|antisymmetr|transitiv/i],
        ['单射', 'Injective functions', /单射|injectiv|one.to.one/i],
        ['满射', 'Surjective functions', /满射|surjectiv|\bonto\b/i],
        ['双射', 'Bijections', /双射|bijectiv|bijections?/i],
        ['复合函数', 'Function composition', /复合函数|函数复合|function composition|composite functions?/i],
        ['逆函数', 'Inverse functions', /逆函数|inverse functions?/i],
        ['真值表', 'Truth tables', /真值表|truth tables?/i],
        ['逻辑等价', 'Logical equivalence', /逻辑等价|逻辑等值|等价变形|重言式|logical equivalence|tautolog/i],
        ['逻辑联结词', 'Logical connectives', /联结词|连接词|合取|析取|蕴含|双条件|logical connectives?|conjunction|disjunction|implication/i],
        ['命题范式', 'Normal forms', /主析取范式|主合取范式|析取范式|合取范式|\b[dc]nf\b|normal forms?/i],
        ['前束范式', 'Prenex normal form', /前束范式|prenex/i],
        ['量词', 'Quantifiers', /量词|quantifiers?|\\forall|\\exists|[∀∃]/i],
        ['数学归纳法', 'Mathematical induction', /数学归纳法|归纳证明|mathematical induction|proof by induction/i],
        ['强归纳法', 'Strong induction', /强归纳法|strong induction/i],
        ['反证法', 'Proof by contradiction', /反证法|proof by contradiction/i],
        ['奇数平方的奇偶性', 'Parity of odd squares', /(?:奇数|odd).{0,28}(?:平方|squar)|(?:平方|squar).{0,28}(?:奇数|odd)/i],
        ['最大公因数', 'Greatest common divisors', /最大公[因约]数|欧几里得算法|辗转相除|greatest common divisor|euclidean algorithm|\bgcd\b/i],
        ['线性同余方程', 'Linear congruences', /线性同余|linear congruences?/i],
        ['中国剩余定理', 'Chinese remainder theorem', /中国剩余定理|孙子定理|chinese remainder/i],
        ['费马小定理', 'Fermat’s little theorem', /费马小定理|fermat.{0,5}little theorem/i],
        ['欧拉定理', 'Euler’s theorem', /欧拉定理|euler.{0,3}theorem/i],
        ['同余运算', 'Modular arithmetic', /同余|模运算|modular arithmetic|congruence/i],
        ['素数与整除', 'Primes and divisibility', /素数|质数|整除|prime numbers?|divisibility/i],
        ['排列与组合', 'Permutations and combinations', /排列|组合数|组合计数|permutations?|combinations?/i],
        ['容斥原理', 'Inclusion–exclusion', /容斥原理|inclusion.exclusion/i],
        ['鸽巢原理', 'Pigeonhole principle', /鸽巢原理|抽屉原理|pigeonhole/i],
        ['二项式定理', 'Binomial theorem', /二项式|binomial theorem/i],
        ['生成函数', 'Generating functions', /生成函数|generating functions?/i],
        ['递推关系', 'Recurrence relations', /递推|递归关系|recurrence|fibonacci|斐波那契/i],
        ['邻接矩阵', 'Adjacency matrices', /邻接矩阵|adjacency matr/i],
        ['图同构', 'Graph isomorphism', /图同构|graph isomorph/i],
        ['欧拉回路', 'Euler circuits', /欧拉.{0,3}(?:回路|通路)|euler(?:ian)?.{0,8}(?:circuits?|paths?|trails?)/i],
        ['哈密顿回路', 'Hamiltonian cycles', /哈密[顿尔].{0,3}(?:回路|通路)|hamilton(?:ian)?.{0,8}(?:cycles?|circuits?|paths?)/i],
        ['欧拉图', 'Eulerian graphs', /欧拉图|eulerian graphs?/i],
        ['哈密顿图', 'Hamiltonian graphs', /哈密[顿尔]图|hamiltonian graphs?/i],
        ['最短路径', 'Shortest paths', /最短路|dijkstra|迪[杰克]斯特拉|shortest paths?/i],
        ['图着色', 'Graph coloring', /图着色|顶点着色|色数|graph colou?ring|chromatic/i],
        ['平面图', 'Planar graphs', /平面图|planar graphs?/i],
        ['二部图', 'Bipartite graphs', /二部图|二分图|bipartite/i],
        ['拓扑排序', 'Topological sorting', /拓扑排序|topological sort/i],
        ['图匹配', 'Graph matching', /完美匹配|最大匹配|图匹配|graph matching|perfect matching/i],
        ['最小生成树', 'Minimum spanning trees', /最小生成树|minimum spanning|\bkruskal\b|\bprim\b/i],
        ['生成树', 'Spanning trees', /生成树|spanning trees?/i],
        ['树的性质', 'Tree properties', /树的性质|树的基本|树的边|tree propert/i],
        ['群与子群', 'Groups and subgroups', /子群|正规群|循环群|交换群|群论|subgroups?|cyclic groups?|group theory/i],
        ['环与域', 'Rings and fields', /环与域|整环|有限域|ring[s ]+and fields?|finite fields?/i],
        ['同态与同构', 'Homomorphisms and isomorphisms', /同态|homomorph/i],
        ['布尔代数', 'Boolean algebra', /布尔代数|boolean algebra/i],
        ['谓词逻辑', 'Predicate logic', /谓词|predicate logic/i],
        ['命题逻辑', 'Propositional logic', /命题|propositional logic/i],
        ['集合', 'Sets', /集合|\bsets?\b/i],
        ['函数与映射', 'Functions and mappings', /函数|映射|\bfunctions?\b|\bmappings?\b/i],
        ['图论', 'Graph theory', /图论|graph theory|\bgraphs?\b/i],
        ['离散数学', 'Discrete mathematics', /离散数学|discrete math/i]
    ];
    const broad = new Set(['谓词逻辑', '命题逻辑', '集合', '函数与映射', '图论', '离散数学']);

    function clean(text) {
        return String(text || '').slice(0, 28000)
            .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
            .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
            .replace(/【(?:题目文字|图形信息|学生作答|知识点|要求)】|\[(?:图片识题|Question|Topics)\]/gi, ' ')
            .replace(/^[\s#>*`_-]+/gm, '')
            .replace(/^(?:题目|问题|question)\s*[:：]\s*/gim, '')
            .replace(/\s+/g, ' ').trim();
    }

    function legacyName(text, source) {
        const lines = String(text || '').replace(/【题目文字】|【图形信息】|\[图片识题\]|[#*_`>]/g, '').trim().split(/\r?\n/);
        const value = (lines.find(line => line.trim() && !/^[-—=]{2,}$/.test(line.trim())) || '')
            .replace(/\s+/g, ' ').replace(/^题目[:：]\s*/, '').trim();
        return value ? value.length > 15 ? value.slice(0, 15) + '…' : value : source === 'ocr' ? '图片识题' : '新对话';
    }

    function intent(value) {
        const affirmative = pattern => pattern.test(value.replace(/(?:不要|不用|无需|不必|do not|don't)\s*(?:直接)?(?:比较|证明|计算|出题|练习|画图|compare|prove|calculate|draw)/gi, ''));
        if (affirmative(/区别|区分|比较|异同|有什么不同|difference|compare|versus|\bvs\b/i)) return ['比较', 'comparison'];
        if (affirmative(/证明|证实|求证|\bprove\b|\bproof\b|\bshow that\b/i)) return ['证明', 'proof'];
        if (affirmative(/复习计划|学习计划|复习安排|study plan|revision plan/i)) return ['复习计划', 'study plan'];
        if (affirmative(/(?:出|来|给|做|练).{0,8}(?:题|练习)|练习|训练|\bpractice\b|\bexercises?\b|\bquiz\b/i)) return ['练习', 'practice'];
        if (affirmative(/绘制|画出|画一个|画图|\bdraw\b|\bplot\b/i)) return ['绘制', 'diagram'];
        if (affirmative(/计算|求值|求解|化简|求出|解方程|\bcalculate\b|\bsolve\b|\bevaluate\b|\bsimplify\b/i)) return ['计算', 'calculation'];
        return ['解析', 'explained'];
    }

    function clip(value, english) {
        const limit = english ? 64 : 22, chars = Array.from(value);
        if (chars.length <= limit) return value;
        if (english) return chars.slice(0, limit + 1).join('').replace(/\s+\S*$/, '') + '…';
        return chars.slice(0, limit - 1).join('') + '…';
    }

    function legacySummary(text, options = {}) {
        const value = clean(text), english = !/[\u3400-\u9fff]/u.test(value) && /[a-z]{3}/i.test(value);
        const fallback = options.source === 'ocr' ? '图片识题' : '新对话';
        if (!value || /^(?:你好|您好|嗨|哈[喽啰]|谢谢|感谢|hello|hi|hey|thanks|thank you)[！!。.,，\s]*$/i.test(value)
            || options.source === 'ocr' && /^[^\s]+\.(?:png|jpe?g|webp|heic|pdf)$/i.test(value)) {
            return { title: fallback, specificity: 0, useful: false };
        }
        const action = intent(value);
        let found = topics.filter(topic => topic[2].test(value));
        if (found.some(topic => !broad.has(topic[0]))) found = found.filter(topic => !broad.has(topic[0]));
        if (found.some(topic => topic[0] === '最小生成树')) found = found.filter(topic => topic[0] !== '生成树');
        if (found.some(topic => ['生成树', '最小生成树'].includes(topic[0]))) found = found.filter(topic => topic[0] !== '树的性质');
        if (found.some(topic => topic[0] === '线性同余方程')) found = found.filter(topic => topic[0] !== '同余运算');
        if (found.some(topic => topic[0] === '前束范式')) found = found.filter(topic => topic[0] !== '命题范式');
        let label;
        if (action[0] === '比较' && found.some(topic => topic[0] === '单射') && found.some(topic => topic[0] === '满射')) label = english ? 'Injective and surjective functions' : '单射与满射';
        else if (action[0] === '比较' && /(?:欧拉|euler)/i.test(value) && /(?:哈密[顿尔]|hamilton)/i.test(value)) {
            label = english ? 'Euler and Hamiltonian circuits' : /回路|通路/.test(value) ? '欧拉与哈密顿回路' : '欧拉图与哈密顿图';
        } else if (found.length) {
            // Preserve order of the named subjects, then combine at most two.
            found.sort((a, b) => value.search(a[2]) - value.search(b[2]));
            const selected = found.slice(0, 2);
            if (selected.some(topic => topic[0] === '奇数平方的奇偶性')) label = english ? 'Parity of odd squares' : '奇数平方的奇偶性';
            else label = selected.map(topic => topic[english ? 1 : 0]).join(english ? ' and ' : '与');
        }
        // Existing teaching analysis may refine a vague first request, never an
        // already specific title. The caller supplies only the matching answer.
        if (!label && options.teaching) {
            const names = [options.teaching.focus_points, options.teaching.knowledge_points].flatMap(list => Array.isArray(list) ? list : [])
                .filter(name => typeof name === 'string' && name.trim() && name.length <= 32);
            if (names.length) {
                const name = names[0].trim(), known = topics.find(topic => topic[0] === name || topic[2].test(name));
                label = english && known ? known[1] : name;
            }
        }
        if (label) return { title: clip(english ? label + ' ' + action[1] : label + action[0], english), specificity: 2, useful: true };
        if (action[0] === '练习') return { title: english ? 'Practice questions' : '练习题', specificity: 0, useful: true };
        if (action[0] === '复习计划') return { title: english ? 'Study plan' : '复习计划', specificity: 0, useful: true };

        // Unknown topics still use all clauses: remove request scaffolding and
        // prefer the substantive phrase after “about/on/关于” over a greeting.
        let subject = value.replace(/^(?:你好|您好|hello|hi)[，,!！\s]*/i, '')
            .replace(/^(?:(?:请问|请|麻烦|能否|能不能|可以|我想了解|我想知道|我想要|我想|帮我|给我|为我|一下|详细|仔细|简单地|please|could you|can you|help me|i want to)\s*)+/i, '')
            .replace(/^(?:讲解|解释|介绍|说明|总结|了解|分析|看看|看一下|explain|describe|summarize|tell me about)\s*/i, '')
            .replace(/^(?:一下|一下子|这个|这道|下面的?)\s*/, '')
            .replace(/[。！？!?；;].*$/, '')
            .replace(/(?:是什么|怎么回事|如何理解|为什么|的?区别|有什么不同)[？?]*$/, '')
            .replace(/(?:谢谢|感谢|thanks).*$/i, '').trim();
        const about = value.match(/(?:关于|有关|\babout\b|\bon\b)\s*([^。！？!?；;]{3,80})/i);
        if (about) subject = about[1].trim();
        if (!subject || /^(?:看看|看一下|讲一下|详细一点|继续|这道题|题|题目|问题|我?有个问题|我?有一个问题|一下|help|continue|explain)$/i.test(subject)) {
            return { title: fallback, specificity: 0, useful: false };
        }
        return { title: clip(subject + (english ? ' discussion' : '讨论'), english), specificity: 0, useful: true };
    }

    function summarize(text, options = {}) {
        const value = clean(text);
        const legacy = legacySummary(text, options);
        if (!value || options.source === 'ocr' && /^[^\s]+\.(?:png|jpe?g|webp|heic|pdf)$/i.test(value)) return legacy;
        const english = !/[\u3400-\u9fff]/u.test(value) && /[a-z]{3}/i.test(value);
        if (/^(?:你好|您好|嗨|哈[喽啰]|hello|hi|hey)[！!。.,，\s]*$/i.test(value)) {
            return { title: english ? 'First conversation' : '初次交流', specificity: 0, useful: false };
        }
        if (/^(?:谢谢|感谢|thanks|thank you)[！!。.,，\s]*$/i.test(value)) {
            return { title: english ? 'Conversation and thanks' : '交流与致谢', specificity: 0, useful: false };
        }
        if (legacy.specificity > 0 || !legacy.useful || /练习题|复习计划|Practice questions|Study plan/.test(legacy.title)) return legacy;
        if (/渲染|render(?:ing)?/i.test(value) && /检查|测试|check|test/i.test(value)) {
            return { title: english ? 'Rendering test' : /长文本/.test(value) ? '长文本渲染测试' : '渲染效果测试', specificity: 1, useful: true };
        }
        // A provider failure must never turn a full copied request plus a suffix
        // into a supposedly summarized title. Keep an honest broad fallback.
        return { title: english ? 'Learning conversation' : '学习交流', specificity: 0, useful: true };
    }

    root.DMateConversationTitles = Object.freeze({ summarize, legacyName, legacySummary });
})(typeof window === 'undefined' ? globalThis : window);
