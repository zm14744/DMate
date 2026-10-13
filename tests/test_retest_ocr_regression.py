"""Fast, offline regression of DMate request semantics; no API/model/DB needed.

Only extracts pure helpers from the Flask module so the tests remain runnable
without PaddleOCR, Flask or production secrets.
"""
import ast
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def app_helper(name):
    module = ast.parse((ROOT / 'app.py').read_text('utf-8'))
    fn = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = {'re': re}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), 'app.py', 'exec'), namespace)
    return namespace[name]

class RetestAndOCRRegression(unittest.TestCase):
    def test_ocr_text_override_requires_question_evidence(self):
        detect = app_helper('_ocr_has_exercise_evidence')
        self.assertTrue(detect('在下面的无向图 G 中，回答下列问题\n(1) 写出邻接矩阵。\n(2) 判断是否有欧拉通路。'))
        self.assertTrue(detect('求3^2024除以17的余数。数学同余计算题目。'))
        self.assertFalse(detect('知识点总结：邻接矩阵，顶点和边的定义。'))
        self.assertFalse(detect('这是一张普通的生活照片。'))

    def test_retest_keeps_full_core_coverage_check(self):
        check = app_helper('_exercise_reference_matches')
        ref = {'category': '图论', 'retest_core_points': ['邻接矩阵', '欧拉图']}
        good = {'category': '图论', 'knowledge_points': ['邻接矩阵', '欧拉图']}
        partial = {'category': '图论', 'knowledge_points': ['邻接矩阵']}
        self.assertTrue(check(ref,good)[0])
        self.assertFalse(check(ref,partial)[0])
        self.assertTrue(check({'category': '图论', 'knowledge_points': ['邻接矩阵']},partial)[0])

    @unittest.skipUnless(shutil.which('node'), 'Node.js not available')
    def test_retest_prompt_inherits_saved_difficulty(self):
        js = (ROOT / 'static/script.js').read_text('utf-8')
        # Extract the real functions with a small Node script (no browser APIs needed).
        start = js.index('function buildRetestPrompt(entry) {')
        end = js.index('\nfunction startWrongQuestionRetest(', start)
        fn = js[start:end]
        harness = '''function wrongBookLearningPoints(e) {return e.knowledgePoints || [];}
''' + fn + '''
for (const d of ['简单','中等','困难','']) {
  const prompt=buildRetestPrompt({knowledgePoints:['邻接矩阵','欧拉图'], difficulty:d});
  if(!prompt.includes('全部核心知识点')) throw Error('missing all points');
  if (d && !prompt.includes('（'+d+'）')) throw Error('not inherited: '+d);
  if(!d && !prompt.includes('以系统复核的原题难度为准')) throw Error('missing fallback');
  if(d==='简单' && prompt.includes('目标难度明确为中等')) throw Error('old fixed medium');
}
'''
        result = subprocess.run(['node','-e',harness],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_ocr_retry_is_bounded_and_non_destructive(self):
        source=(ROOT/'ocr.py').read_text('utf-8')
        self.assertIn('_ocr_text_strength(enhanced_items) > _ocr_text_strength(text_items)', source)
        self.assertIn('except Exception as exc:\n                    print(f"低对比度文字 OCR 补救失败',source)
        self.assertEqual(source.count('_extract_text_items(_enhance_faded_photo(image))'), 1)

    def test_valid_question_no_longer_rejected_by_difficulty_only(self):
        s=(ROOT/'app.py').read_text('utf-8')
        self.assertIn('练习有效但难度估计存在偏差',s)
        self.assertNotIn('本次没有生成符合{target_difficulty}难度的题目，请重新出题',s)
        self.assertIn('is_wrongbook_retest = reference.get("retest") is True',s)
        self.assertIn('(is_wrongbook_retest or bool(explicit_exercise_difficulty))',s)
        self.assertIn('generation_note = (',s)

if __name__=='__main__':
    unittest.main()
