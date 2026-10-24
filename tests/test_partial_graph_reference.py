"""A cropped/ambiguous reference is not a model recognition failure."""
from nextgen_browser import grade


def test_partial_reference_never_grades_unseen_original_edges_as_wrong():
    case={'expected':{'graphs':[]},'reference_status':'partial','expected_question_text':''}
    record={'rendered':{'graph':'图1；顶点a、b；边a—b'},'operational_ok':True}
    result=grade(case,{'text':'','graph_display_data':[{'directed':False,'vertices':[], 'edges':[]}]},record)
    assert result['点和边']=='无法核实'
    assert result['图形分隔']=='无法核实' and result['图形描述']=='无法核实'
    # Independent text/format evidence remains usable.
    assert result['题目文字']=='通过' and result['描述统一']=='通过'
