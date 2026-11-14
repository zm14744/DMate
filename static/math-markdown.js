(function (root) {
    'use strict';
    let mathQueue = Promise.resolve();
    // One Markdown/LaTeX pipeline for online replies and offline study content.
    function escapeRawHtml(text) {
        return String(text ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");
    }

    // 用 Markdown 不会拆分的专用私有字符保存公式，只在解析本次消息期间使用。
    // 旧的 MATHPROTECTTOKEN 文本占位符容易泄漏到页面或被再次解析成公式。
    function protectMathForMarkdown(source) {
        const mathSegments = [];
        const prefix = "\uE000DMATE_MATH_";
        const suffix = "_END\uE001";
        const stash = match => {
            const key = prefix + mathSegments.length + suffix;
            mathSegments.push([key, match]);
            return key;
        };

        // 仅保护有效成对的定界符；换行公式优先于单行公式。
        // 保留原始字符供 MathJax 使用，不把 LaTeX 提前转成 HTML。
        let protectedText = String(source ?? "");
        protectedText = protectedText.replace(/\$\$[\s\S]*?\$\$/g, stash);
        protectedText = protectedText.replace(/\\\[[\s\S]*?\\\]/g, stash);
        protectedText = protectedText.replace(/\\\([\s\S]*?\\\)/g, stash);
        protectedText = protectedText.replace(/(?<!\\)\$(?!\$)(?:\\.|[^$\n])+\$/g, stash);
        return { protectedText, mathSegments };
    }

    function restoreMathAfterMarkdown(html, mathSegments) {
        let restored = String(html ?? "");
        for (const [token, math] of mathSegments) {
            restored = restored.split(token).join(escapeRawHtml(math));
        }
        return restored;
    }

    function repairBareLatexTextSegment(segment) {
        const source = String(segment || "");

        if (!source) return "";

        return source
            .split("\n")
            .map(line => {
                const trimmed = line.trim();

                if (!trimmed) return line;

                // 对“整行几乎就是公式”的裸 LaTeX 先做块级包裹。
                // 先处理这一层，避免后面的单命令修复把一个完整公式拆成很多小块。
                if (
                    !trimmed.includes("$")
                    && !/[\u4e00-\u9fff]/.test(trimmed)
                    && /\\(?:frac|binom|sqrt|sum|prod|cup|cap|lor|land|neg|operatorname|to|rightarrow|Rightarrow)\b/.test(trimmed)
                    && /^[A-Za-z0-9\s\\{}()[\]|=+\-*/!,.^_:<>]+$/.test(trimmed)
                ) {
                    const indent = line.match(/^\s*/)?.[0] || "";
                    return `${indent}$$${trimmed}$$`;
                }

                let value = line;

                // 正文里偶尔会出现单独裸露的 LaTeX 运算符。只包裹命令本身，
                // 避免把旁边的中文一起塞进 MathJax。
                value = value.replace(
                    /(?<![$\\])\\(lor|land|neg|cup|cap|in|notin|subseteq|subset|supseteq|supset|leq|le|geq|ge|neq|to|rightarrow|Rightarrow)(?![A-Za-z])/g,
                    match => `$${match}$`
                );

                // 路径类表达式：v_1 \to v_2 \to v_3
                value = value.replace(
                    /((?:[A-Za-z]_(?:\{[^}\n]+\}|[A-Za-z0-9]+)|[A-Za-z][0-9]+)(?:\s*\\(?:to|rightarrow|Rightarrow|xrightarrow\{[^}\n]+\})\s*(?:[A-Za-z]_(?:\{[^}\n]+\}|[A-Za-z0-9]+)|[A-Za-z][0-9]+))+)/g,
                    match => `$${match}$`
                );

                // 单个常见上下标/幂表达式低风险包裹。
                value = value.replace(
                    /(?<![$A-Za-z0-9])([A-Za-z](?:_\{[^}\n]{1,30}\}|_[A-Za-z0-9]{1,12}|\^\{[^}\n]{1,30}\}|\^[A-Za-z0-9]{1,8}))(?![$A-Za-z0-9])/g,
                    match => `$${match}$`
                );

                return value;
            })
            .join("\n");
    }

    function stripProofEndMarker(source) {
        // Omit decorative QED squares after an explicit proof ending, while
        // retaining squares used in mathematical expressions, code or questions.
        const square = String.raw`(?:[□∎■◻◼]|\\(?:square|blacksquare|Box|qedhere|qed)(?![A-Za-z]))`;
        const marker = String.raw`(?:${square}|\${1,2}\s*${square}\s*\${1,2}|\\\(\s*${square}\s*\\\)|\\\[\s*${square}\s*\\\])`;
        const ending = new RegExp(String.raw`((?:证毕|得证|证明完毕|证明完成|\bQ\.?\s*E\.?\s*D\.?)[。.!！]?(?:\*\*|__)?[。.!！]?)\s*(?:${marker}\s*)+((?:\*\*|__)?\s*)$`, 'i');
        return source.replace(ending, '$1$2');
    }

    function prepareAiDisplayText(text) {
        // 老会话中已损坏的占位符没有保留对应公式，无法凭空恢复原式。
        // 显示明确提示而不是把内部字串当成数学式再次渲染。
        let value = String(text ?? "").replace(
            /MATHPROTECTTOKEN\d+ENDTOKEN/g,
            "【原公式缺失，请重新生成该题】"
        );

        if (!value) return "";
        value = stripProofEndMarker(value);

        // Keep code and already-delimited math opaque before repairing prose.
        // Complete bare environments also need protection: otherwise Markdown
        // consumes their row separators and bare-symbol repair inserts dollars
        // inside the matrix. Only wrap environments outside existing code/math.
        const protectedSegments = /```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`|\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$[^$\n]*\$|\\begin\{(bmatrix|pmatrix|matrix|cases|aligned)\}[\s\S]*?\\end\{\1\}/g;
        let result = "", offset = 0;
        for (const match of value.matchAll(protectedSegments)) {
            result += repairBareLatexTextSegment(value.slice(offset, match.index));
            result += match[1] ? `$$\n${match[0]}\n$$` : match[0];
            offset = match.index + match[0].length;
        }
        return result + repairBareLatexTextSegment(value.slice(offset));
    }


    function markdownToHtml(text) {
        const source = String(text ?? "");

        const {
            protectedText,
            mathSegments
        } = protectMathForMarkdown(source);

        const rawHtml = root.marked.parse(protectedText);
        // Restore before the final sanitization. A placeholder can occur inside
        // an HTML attribute, where restored quotes must not create new attributes
        // after DOMPurify has already finished checking the markup.
        const restoredHtml = restoreMathAfterMarkdown(rawHtml, mathSegments);
        const result = root.DOMPurify
            ? root.DOMPurify.sanitize(restoredHtml)
            : escapeRawHtml(source).replace(/\n/g, "<br>");
        // 不能把内部占位符漏到用户界面。极少数解析器异常时，
        // 宁可原样显示完整源码，也不能显示残缺公式或错误连接结果。
        if (result.includes("\uE000DMATE_MATH_")
            || /MATHPROTECTTOKEN\d+ENDTOKEN/.test(result)) {
            console.warn("数学公式 Markdown 保护/还原异常，使用可读回退显示");
            return '<div class="math-render-fallback" style="white-space:pre-wrap">'
                + escapeRawHtml(source).replace(/MATHPROTECTTOKEN\d+ENDTOKEN/g,
                    "【原公式缺失，请重新生成该题】") + '</div>';
        }
        return result;
    }

    function renderMath(target) {
        // Startup may still be loading TeX extensions on the first reply.
        // History, streamed previews and answer panels share one MathJax
        // document, so they must not typeset it concurrently.
        const render = async () => {
            try {
                await root.MathJax?.startup?.promise;
                if (typeof root.MathJax?.typesetPromise !== 'function') return;
                await root.MathJax.typesetPromise(target ? [target] : undefined);
            } catch (error) {
                // A presentation failure must not discard a completed answer
                // or be reported as a failed network connection.
                console.warn("MathJax 渲染失败：", error);
            }
        };
        const pending = mathQueue.then(render, render);
        mathQueue = pending;
        return pending;
    }

    // The authored study packs also contain literal Unicode mathematics.
    // Adapt only recognizable expressions; prose, links and code remain text.
    const studyFunctions = new Set(['gcd','lcm','log','ln','exp','min','max','sin','cos','tan','det','ker','dim','im','Im','rank','ord','deg','dist','id','dom','cod','Pr','Var','Cov','Tr','Hom','Aut','End','GL','SL','GF','mod']);
    const studyCommands = new Set(['frac','binom','sqrt','mathbb','mathcal','mathsf','mathrm','text','operatorname','overline','bar','gcd','log','ln','exp','min','max','sin','cos','tan','det','ker','dim','Pr','bmod','pmod','forall','exists','in','notin','subset','subseteq','supset','supseteq','cup','cap','setminus','to','rightarrow','Rightarrow','leftrightarrow','Leftrightarrow','neg','land','lor','sum','prod','alpha','beta','gamma','delta','epsilon','theta','lambda','mu','pi','sigma','phi','psi','omega','Gamma','Delta','Theta','Lambda','Pi','Sigma','Phi','Psi','Omega','infty','emptyset','times','cdot','circ','le','leq','ge','geq','ne','neq','equiv','approx','oplus','otimes']);
    const studyOperators = {
        '¬':'\\neg','∧':'\\land','∨':'\\lor','→':'\\to','↔':'\\leftrightarrow','⇒':'\\Rightarrow','⇔':'\\Leftrightarrow',
        '∈':'\\in','∉':'\\notin','⊂':'\\subset','⊆':'\\subseteq','⊄':'\\nsubseteq','⊃':'\\supset','⊇':'\\supseteq',
        '∪':'\\cup','∩':'\\cap','∖':'\\setminus','×':'\\times','÷':'\\div','±':'\\pm','≤':'\\leq','≥':'\\geq','≠':'\\neq','≈':'\\approx','≡':'\\equiv',
        '⊕':'\\oplus','⊗':'\\otimes','⋅':'\\cdot','⋆':'\\star','∘':'\\circ','∀':'\\forall','∃':'\\exists','∑':'\\sum','∏':'\\prod','√':'\\sqrt','∞':'\\infty','∅':'\\emptyset',
        'ℕ':'\\mathbb{N}','ℤ':'\\mathbb{Z}','ℚ':'\\mathbb{Q}','ℝ':'\\mathbb{R}','ℂ':'\\mathbb{C}',
        '−':'-','·':'\\cdot','∣':'\\mid','∤':'\\nmid','｜':'\\vert','∥':'\\parallel','′':"'",'ℓ':'\\ell',
        '↦':'\\mapsto','←':'\\leftarrow','⇝':'\\rightsquigarrow','⊨':'\\models','⊢':'\\vdash','⊤':'\\top','⊥':'\\bot',
        '∼':'\\sim','≅':'\\cong','≃':'\\simeq','⊊':'\\subsetneq','≺':'\\prec','⋯':'\\cdots','⋃':'\\bigcup',
        '△':'\\triangle','⊔':'\\sqcup','⊙':'\\odot','…':'\\ldots','⟨':'\\langle','⟩':'\\rangle',
        '⌊':'\\lfloor','⌋':'\\rfloor','⌈':'\\lceil','⌉':'\\rceil','½':'\\frac{1}{2}'
    };
    const superDigits = {'⁰':'0','¹':'1','²':'2','³':'3','⁴':'4','⁵':'5','⁶':'6','⁷':'7','⁸':'8','⁹':'9','ⁿ':'n','ⁱ':'i','ᵃ':'a','ᵇ':'b','ᶜ':'c','ᵈ':'d','ᵉ':'e','ᵏ':'k','ᵖ':'p','ᵗ':'t','ᵘ':'u','ᵛ':'v','ˣ':'x','ʸ':'y','ʲ':'j','ʳ':'r','ᵀ':'T','ᴿ':'R','⁺':'+','⁻':'-','⁼':'=','⁽':'(','⁾':')'};
    // The existing packs use ᵩ and 𝚌 as typographic q/c indices in K_p,q
    // and matrix entries; retain those authored index names when typesetting.
    const subDigits = {'₀':'0','₁':'1','₂':'2','₃':'3','₄':'4','₅':'5','₆':'6','₇':'7','₈':'8','₉':'9','ₙ':'n','ᵢ':'i','ⱼ':'j','ₖ':'k','ₚ':'p','ᵣ':'r','ᵥ':'v','ᵤ':'u','ₘ':'m','ₑ':'e','ₐ':'a','ₛ':'s','ₜ':'t','ᵩ':'q','𝚌':'c','₊':'+','₋':'-','₌':'=','₍':'(','₎':')'};
    const characterClass = value => value.replace(/[\\\]\[\^-]/g, '\\$&');
    const operatorChars = characterClass(Object.keys(studyOperators).join(''));
    const superChars = characterClass(Object.keys(superDigits).join(''));
    const subChars = characterClass(Object.keys(subDigits).join(''));
    const studyOperatorPattern = new RegExp('[' + operatorChars + ']', 'g');
    const studyAnchorPattern = new RegExp('[α-ωΑ-Ω' + operatorChars + superChars + subChars + ']');
    const studyTokenSource = String.raw`\*\*|__|\\(?:text|operatorname|mathrm|mathbb|mathcal|mathsf|overline|bar)\{(?:[^{}\n]|\{[^{}\n]*\})*\}|\\[A-Za-z]+|[A-Za-z][A-Za-z0-9]*|\d+(?:\.\d+)?|[`
        + 'α-ωΑ-Ω' + operatorChars + superChars + subChars + characterClass("=<>+*/^_!%()[]{},.:;|'-") + String.raw`]|[ \t]+`;
    for (const tex of Object.values(studyOperators)) {
        for (const match of tex.matchAll(/\\([A-Za-z]+)/g)) studyCommands.add(match[1]);
    }

    function studyExpressionTex(value) {
        const opaque = [];
        // Existing TeX arguments are grouping, whereas bare authored braces
        // are set delimiters and must remain visible in the rendered formula.
        let result = value.replace(/\\(?:frac|binom)\{(?:[^{}]|\{[^{}]*\})*\}\{(?:[^{}]|\{[^{}]*\})*\}|\\(?:sqrt(?:\[[^\]\n]*\])?|text|operatorname|mathrm|mathbb|mathcal|mathsf|overline|bar)\{(?:[^{}]|\{[^{}]*\})*\}|[_^]\{[^{}]*\}/g, match => {
            const token = '\uE100STUDY' + opaque.length + '\uE101'; opaque.push([token,match]); return token;
        });
        result = result.replace(/[{}]/g, char => '\\' + char)
            .replace(new RegExp('[' + superChars + ']+', 'g'), chars => '^{' + [...chars].map(char => superDigits[char]).join('') + '}')
            .replace(new RegExp('[' + subChars + ']+(?:,[' + subChars + ']+)*', 'g'), chars => '_{' + [...chars].map(char => char === ',' ? ',' : subDigits[char]).join('') + '}')
            .replace(/([_^])\(([^()]*)\)/g, '$1{$2}')
            .replace(/([_^])(\d{2,})/g, '$1{$2}')
            // In p₁^α₁ or id_N₀ the last index belongs to the script's
            // symbol, rather than creating a second subscript on p or id.
            .replace(/([_^])([A-Za-zα-ωΑ-Ω])([_^]\{[^{}]*\})/g, '$1{$2$3}')
            .replace(studyOperatorPattern, char => studyOperators[char] + ' ')
            .replace(/%/g, '\\%')
            .replace(/(?<![A-Za-z\\])(gcd|lcm|log|ln|exp|min|max|sin|cos|tan|det|ker|dim|im|rank|ord|deg|dist|id|dom|cod|Pr|Var|Cov|Tr|mod)(?![A-Za-z])/g, name => {
                const native = new Set(['gcd','log','ln','exp','min','max','sin','cos','tan','det','ker','dim','deg']);
                return name === 'mod' ? '\\bmod ' : native.has(name) ? '\\' + name + ' ' : '\\operatorname{' + name + '}';
            });
        for (const [token, original] of opaque) result = result.split(token).join(original);
        return result.trim();
    }

    function studyMathCandidate(value, wholeValue) {
        const whitespace = value.match(/^(\s*)([\s\S]*?)(\s*)$/);
        let [, before, content, after] = whitespace;
        const punctuation = content.match(/^(.*?)([.,;:]+)$/);
        if (punctuation) { content = punctuation[1]; after = punctuation[2] + after; }
        const emphasis = content.match(/^([*_])(.+)\1$/);
        if (emphasis) { before += emphasis[1]; content = emphasis[2]; after = emphasis[1] + after; }
        const clearMath = studyAnchorPattern.test(content)
            || /[A-Za-z0-9)}]\s*(?:=|<|>|\+|-|\*|\/|\^|_)\s*[A-Za-z0-9({+-]/.test(content)
            || /[A-Za-z0-9)]!|\d+%/.test(content)
            || /\b(?:gcd|lcm|log|ln|exp|min|max|sin|cos|tan|det|ker|dim|im|rank|ord|deg|dist|id|dom|cod|Pr|Var|Cov|Tr|O|o|Ω|Θ)\s*\(/.test(content)
            || /\b[A-Za-z]\s*\([^()\n]+\)/.test(content)
            || /\\[A-Za-z]+/.test(content)
            || /^\{[^{}]+\}$/.test(content)
            || /^\|[^|]+\|$/.test(content)
            || /^-?\d+(?:\s*[-+*/]\s*-?\d+)+$/.test(content)
            || (wholeValue && /^(?:[A-Za-z]\d*|-?\d+(?:\.\d+)?)$/.test(content));
        return clearMath && content ? before + '$' + studyExpressionTex(content) + '$' + after : value;
    }

    function studyPlainLine(line, wholeValue) {
        // Preserve Markdown list/quotation structure, including ordered lists.
        const prefix = line.match(/^(\s*(?:>\s*)*(?:(?:[-+*]|\d+[.)])\s+)?)/)?.[0] || '';
        const source = line.slice(prefix.length).replace(/(?<![A-Za-z\\])([A-Z])\s*\\\s*([A-Z])(?![A-Za-z])/g, '$1∖$2');
        const token = new RegExp(studyTokenSource, 'y');
        let result = prefix, pending = '', offset = 0;
        const flush = () => { result += studyMathCandidate(pending, wholeValue && !prefix && pending === source); pending = ''; };
        while (offset < source.length) {
            token.lastIndex = offset;
            const match = token.exec(source);
            if (!match) { flush(); result += source[offset++]; continue; }
            const part = match[0]; offset += part.length;
            // Short juxtaposed factors such as ac≡bd and a∣bc are math
            // only when they touch an explicit operator. Whitespace never
            // turns an adjacent English word into an algebraic factor.
            const betweenOperators = /[=<>+*^_|-]/.test(source[match.index - 1] || '')
                && /[=<>+*^_|-]/.test(source[offset] || '');
            const shortProduct = /^[A-Za-z]{2,3}$/.test(part)
                && (betweenOperators || !/^(?:a[nst]|and|are|as|at|be|but|by|can|do|for|has|if|in|is|it|its|let|no|not|of|on|or|so|the|to|was|we|yes)$/i.test(part))
                && (studyAnchorPattern.test(source[offset] || '')
                    || studyAnchorPattern.test(source[match.index - 1] || '')
                    || /[=<>+*^_|]/.test(source[offset] || '')
                    || /[=<>+*^_|]/.test(source[match.index - 1] || ''));
            const allowed = !['**','__'].includes(part)
                && (!/^[A-Za-z]/.test(part) || /^[A-Za-z]\d*$/.test(part) || studyFunctions.has(part) || shortProduct)
                && (!/^\\[A-Za-z]+$/.test(part) || studyCommands.has(part.slice(1)));
            if (allowed) pending += part;
            else { flush(); result += part; }
        }
        flush(); return result;
    }

    function prepareStudyText(text) {
        const source = String(text ?? '');
        const protectedSegments = /```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`|\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$[^$\n]*\$|\\begin\{(bmatrix|pmatrix|matrix|cases|aligned)\}[\s\S]*?\\end\{\1\}|!?\[[^\]\n]*\]\([^\s)]*(?:\s+"[^"]*")?\)|<\/?[A-Za-z][A-Za-z0-9:-]*(?:\s+[^>\n]*)?\s*\/?>|https?:\/\/[^\s<]+|^\s*\|(?:[^\n]*\|){2,}\s*$/gm;
        let result = '', offset = 0;
        const adapt = value => value.split('\n').map(line => studyPlainLine(line, source.trim() === line.trim())).join('\n');
        for (const match of source.matchAll(protectedSegments)) {
            result += adapt(source.slice(offset, match.index)) + (match[1] ? '$$\n' + match[0] + '\n$$' : match[0]);
            offset = match.index + match[0].length;
        }
        // Adapt a whole Unicode expression before the existing AI repair
        // handles remaining bare LaTeX. This keeps n_i² in one math run.
        return prepareAiDisplayText(result + adapt(source.slice(offset)));
    }

    root.DMateMathMarkdown = Object.freeze({escapeRawHtml, protectMathForMarkdown, restoreMathAfterMarkdown, repairBareLatexTextSegment, prepareAiDisplayText, prepareStudyText, markdownToHtml, renderMath});
})(typeof window !== 'undefined' ? window : globalThis);
