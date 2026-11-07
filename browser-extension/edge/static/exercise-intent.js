(function (root) {
    "use strict";

    // The server and browser consume the same ordered rules. No request or
    // model call is needed to distinguish a new exercise from a follow-up.
    function createClassifier(rules = {}) {
        const patterns = key => (rules[key] || []).map(pattern => new RegExp(pattern, "u"));
        const replacements = (rules.normalization?.replacements || []).map(item => ({
            pattern: new RegExp(item.pattern, "gu"), replacement: item.replacement
        }));
        const aliases = Object.entries(rules.normalization?.aliases || {})
            .sort((left, right) => right[0].length - left[0].length);
        const ignored = (rules.ignored_spans || []).map(pattern => new RegExp(pattern, "gu"));
        const separator = new RegExp(rules.clause_separator || "[\\n,;.!?]+", "u");
        const reject = patterns("reject");
        const wholeReject = patterns("whole_reject");
        const negative = patterns("negative");
        const positive = patterns("positive");
        const implicit = patterns("implicit");
        const maxLength = Number(rules.max_length || 20000);
        const matches = (list, text) => list.some(pattern => pattern.test(text));

        function normalize(text) {
            let value = String(text ?? "").normalize("NFKC").toLowerCase();
            for (const item of replacements) value = value.replace(item.pattern, item.replacement);
            for (const [before, after] of aliases) value = value.split(before).join(after);
            return value.trim();
        }

        function classify(text) {
            let value = String(text ?? "").normalize("NFKC").toLowerCase().trim();
            let result = {is_exercise:false, explicit:false, blocked:false};
            let blocked = false;
            if (!value || Array.from(value).length > maxLength) return result;
            value = normalize(value);
            for (const pattern of ignored) {
                const cleaned = value.replace(pattern, "");
                if (cleaned !== value) blocked = true;
                value = cleaned;
            }
            if (matches(wholeReject, value)) return {is_exercise:false, explicit:false, blocked:true};
            for (const part of value.split(separator)) {
                const clause = part.trim();
                if (!clause) continue;
                if (matches(reject, clause)) { blocked = true; continue; }
                if (matches(negative, clause)) {
                    result = {is_exercise:false, explicit:false};
                    blocked = true;
                }
                else if (matches(positive, clause)) result = {is_exercise:true, explicit:true};
                else if (matches(implicit, clause)) result = {is_exercise:true, explicit:false};
            }
            return {...result, blocked:!result.is_exercise && blocked};
        }

        return {classify, normalize};
    }

    const source = root.document?.getElementById("exerciseIntentRules");
    let rules = {};
    if (source) {
        try { rules = JSON.parse(source.textContent); }
        catch (error) { root.console?.warn("出题识别规则加载失败：", error); }
    }
    root.DMateExerciseIntent = {...createClassifier(rules), createClassifier};
})(typeof window !== "undefined" ? window : globalThis);
