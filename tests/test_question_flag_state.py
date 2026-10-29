"""Explicit question choices survive history and legacy learning-state recovery.

Production state selectors run in Node with synthetic messages; no model is called.
"""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')


PROGRAM = r"""
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/script.js','utf8');
const messages=JSON.parse(fs.readFileSync(0,'utf8'));
function actual(name) {
  const match=new RegExp('(?:async )?function '+name+'\\(').exec(source);
  if(!match)throw Error('Missing production function: '+name);
  const following=source.slice(match.index+match[0].length);
  const next=/\n(?:async )?function [A-Za-z_$]/.exec(following);
  return source.slice(match.index,next?match.index+match[0].length+next.index:source.length);
}
const sandbox={
  sanitizeStoredWrongQuestionText:text=>String(text||'').trim(),
  cutQuestionAfterMetaSections:text=>String(text||'').split('【我的要求】')[0].trim(),
  isExerciseRequestText:text=>/给我出题/.test(text||''),
  isShortLearningFollowUp:text=>String(text||'').length<=6,
  looksLikeChatQuestionText:text=>/^求|计算/.test(text||''),
  countTopLevelQuestionParts:()=>0,
  wrongQuestionFingerprint:text=>String(text||''),
  normalizeTeaching:value=>value||null,
  recoverGeneratedQuestionFromAssistant:()=>''
};
vm.createContext(sandbox);
const names=['extractOcrQuestionPayload','extractQuestionOnlyFromMessage',
  'extractOcrPrintedQuestionText','looksLikeFormalPureImageRequest',
  'isRecordableOcrQuestionMessage','looksLikeActualLearningProblem',
  'buildLearningQuestionFromSession','isHistorySystemMetaText',
  'looksLikeFormalStudyQuestionForHistory','collectConversationQuestionCandidates'];
vm.runInContext(names.map(actual).join('\n'),sandbox);
const session={id:'s',messages};
process.stdout.write(JSON.stringify({
  history:sandbox.collectConversationQuestionCandidates(session),
  fallback:sandbox.buildLearningQuestionFromSession(session,null),
  standalone:messages.map(message=>sandbox.looksLikeActualLearningProblem(message))
}));
"""


def state(messages):
    if NODE is None:
        raise unittest.SkipTest('Node unavailable')
    process = subprocess.run([NODE, '-e', PROGRAM], cwd=ROOT,
                             input=json.dumps(messages, ensure_ascii=False),
                             text=True, capture_output=True, check=True)
    return json.loads(process.stdout)


class QuestionFlagStateTests(unittest.TestCase):
    def test_explicit_choices_control_mixed_manual_and_image_question_history(self):
        result = state([
            {'role': 'user', 'text': '求下面代码对应图的边数', 'manualIsQuestion': True},
            {'role': 'user', 'text': '求服务器连接图的度数', 'manualIsQuestion': False},
            {'role': 'user', 'source': 'ocr', 'text': '计算背景图的生成树', 'ocrIsQuestion': True},
            {'role': 'user', 'source': 'ocr', 'text': '计算代码调用图的边数', 'ocrIsQuestion': False},
            {'role': 'user', 'text': '给我出题', 'manualIsQuestion': True},
            {'role': 'user', 'source': 'ocr', 'text': '【题目文字】\n计算背景图的生成树'},
        ])
        self.assertEqual([candidate['index'] for candidate in result['history']], [0, 2])

    def test_explicit_chat_cannot_become_fallback_question_but_keeps_answer_routing(self):
        message = {'role': 'user', 'text': '求下面代码调用图的边数', 'manualIsQuestion': False}
        result = state([message, {'role': 'ai', 'text': '共有三条边'}])
        self.assertEqual(result['history'], [])
        self.assertIsNone(result['fallback'])
        self.assertIs(result['standalone'][0], True)
        # Recovery for older messages without an explicit choice stays compatible.
        legacy = {key: value for key, value in message.items() if key != 'manualIsQuestion'}
        self.assertEqual(state([legacy])['fallback']['text'], legacy['text'])
