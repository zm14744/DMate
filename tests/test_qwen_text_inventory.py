"""Batched text parsing cannot change measured geometry or borrow old labels."""
import copy

import pytest

from graph_qwen_text_inventory import apply_text_inventory
from graph_schema import canonical_graph


def prepared():
    g=canonical_graph({'id':'G','directed':False,'weighted':True,'multigraph':False,
        'vertices':[{'id':'m1','label':None,'x':.1,'y':.2},
                    {'id':'m2','label':None,'x':.8,'y':.9}],
        'edges':[{'id':'stroke1','from':'m1','to':'m2','direction':'undirected',
                  'weight':None,'path':[[.1,.2],[.8,.9]],'style':'solid',
                  'evidence':[{'source':'pixels'}]}]})
    return {'graphs':[g],'items':[
        {'key':'A','kind':'vertex_label','graph_index':0,'id':'m1','rect':[1,2,10,20]},
        {'key':'B','kind':'vertex_label','graph_index':0,'id':'m2','rect':[11,12,20,30]},
        {'key':'C','kind':'weight','graph_index':0,'id':'stroke1','rect':[31,32,40,50]}]}


def test_unordered_text_reads_bind_to_measured_ids_without_rewriting_geometry():
    p=prepared();source=copy.deepcopy(p)
    graphs=apply_text_inventory(p,{'readings':[{'key':'C','text':'-2.5'},
        {'key':'B','text':'v7'},{'key':'A','text':'v1'}]})
    g=graphs[0]
    assert [(v['id'],v['label']) for v in g['vertices']]==[('m1','v1'),('m2','v7')]
    e=g['edges'][0]
    assert e['weight']==-2.5 and e['edge_label'] is None
    assert (e['id'],e['from'],e['to'],e['path'])==('stroke1','m1','m2',source['graphs'][0]['edges'][0]['path'])
    assert not g['complete']


@pytest.mark.parametrize('readings',[
    [{'key':'A','text':'v1'},{'key':'A','text':'v7'},{'key':'C','text':2}],
    [{'key':'A','text':'v1'},{'key':'B','text':'v7'},{'key':'foreign','text':2}],
    [{'key':'A','text':'v1'},{'key':'B','text':'v7'}],
    [{'key':'A','text':'v1'},{'key':'B','text':'v7'},{'key':'C','text':'NaN'}],
])
def test_duplicate_unknown_missing_or_nonfinite_readings_are_not_accepted(readings):
    with pytest.raises(ValueError):
        apply_text_inventory(prepared(),{'readings':readings})
