"""Full native figure rereads never rename nodes or erase a measured chord."""
import copy
import pytest
from graph_schema import canonical_graph
from graph_qwen_figure_review import apply_figure_review


def example():
    graph=canonical_graph({'id':'G','directed':False,'weighted':False,
        'vertices':[{'id':key} for key in ('a','b','c')],
        'edges':[{'id':'straight','from':'a','to':'b','direction':'undirected','style':'solid',
                  'evidence':[{'source':'pixels','method':'opencv_straight_line_coverage'}]},
                 {'id':'curve','from':'b','to':'c','direction':'undirected','style':'solid','edge_label':'x',
                  'evidence':[{'source':'pixels','method':'opencv_native_boundary_trace'}]},
                 {'id':'arc','from':'a','to':'c','direction':'undirected','style':'dashed',
                  'evidence':[{'source':'pixels','method':'opencv_curved_ink_template'}]}]})
    second=copy.deepcopy(graph);second['id']='H'
    return {'graphs':[graph,second],'graph_index':1,'graph_id':'H','vertices':['a','b','c'],'items':[],'rect':[0,0,100,100]}


def test_complete_figure_rejection_is_scoped_and_preserves_native_chord():
    prepared=example();before=copy.deepcopy(prepared)
    output,notes=apply_figure_review(prepared,{'graph_id':'H','edges':[['a','c']],'readings':[]})
    assert prepared==before and output[0]['edges']==before['graphs'][0]['edges']
    assert [e['id'] for e in output[1]['edges']]==['straight','arc']
    assert output[1]['edges'][1]['style']=='dashed'
    rejected=output[1]['node_review']['native_figure_review']['rejected']
    assert rejected[0]['edge']['edge_label']=='x'
    assert notes==['figure_review_denial_conflicts_with_native_chord:straight']


def test_unseen_endpoint_in_whole_figure_read_is_rejected_atomically():
    prepared=example();before=copy.deepcopy(prepared)
    with pytest.raises(ValueError):apply_figure_review(prepared,{'graph_id':'H','edges':[['a','invented']],'readings':[]})
    assert prepared==before
