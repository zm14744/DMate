"""Keyed reads of identical edge IDs in different figures cannot cross-bind."""
import copy
import pytest
from graph_schema import canonical_graph
from graph_qwen_local_text import apply_local_text


def prepared():
    graph=canonical_graph({'id':'G','vertices':[{'id':'a'},{'id':'b'}],
        'edges':[{'id':'e','from':'a','to':'b','direction':'undirected','style':'dashed'}]})
    second=copy.deepcopy(graph);second['id']='H'
    return {'graphs':[graph,second],'items':[
        {'key':key,'graph_index':i,'kind':'edge_label','id':'e','rect':[0,0,20,20]}
        for i,key in enumerate(('A','B'))]}


def test_identical_local_ids_are_bound_by_figure_and_exact_key():
    plan=prepared();before=copy.deepcopy(plan)
    output=apply_local_text(plan,{'readings':[{'key':'B','text':'second'},
                                           {'key':'A','text':'first'}]})
    assert [g['edges'][0]['edge_label'] for g in output]==['first','second']
    assert all(g['edges'][0]['style']=='dashed' for g in output)
    assert plan==before


@pytest.mark.parametrize('second',[{'key':'A','text':'duplicate'},{'key':'unknown','text':'x'},
                                  {'key':'B','text':123}])
def test_cross_figure_bad_reads_are_atomic(second):
    plan=prepared();before=copy.deepcopy(plan)
    with pytest.raises(ValueError):apply_local_text(plan,{'readings':[{'key':'A','text':'first'},second]})
    assert plan==before


def test_native_caption_read_updates_name_without_renaming_graph_or_edge_ids():
    plan=prepared();plan['items'].append({'key':'C','graph_index':1,'kind':'figure_name',
        'id':'H','rect':[100,100,200,150]})
    output=apply_local_text(plan,{'readings':[{'key':'A','text':'first'},
        {'key':'B','text':'second'},{'key':'C','text':'G\\e5'}]})
    assert output[1]['id']=='H' and output[1]['name']=='G\\e5'
    assert output[1]['edges'][0]['id']=='e'
    assert output[1]['figure_name_evidence'][0]['prior_name']=='G'


def test_combined_native_sheets_survive_the_existing_two_image_transport():
    import base64,io
    from PIL import Image
    from vision_provider import VisionProvider
    from graph_qwen_local_text import pack_uncertainty_sheets
    def url(colour):
        data=io.BytesIO();Image.new('RGB',(80,60),colour).save(data,format='PNG')
        return 'data:image/png;base64,'+base64.b64encode(data.getvalue()).decode()
    overview=url('white');text=url('red');arrow=url('blue')
    packed=pack_uncertainty_sheets({'image_url':text},{'image_url':arrow})
    payload=VisionProvider('qwen').payload('read both independent key namespaces',[overview,packed['image_url']])
    content=payload['messages'][0]['content'];images=[row['image_url']['url'] for row in content if row['type']=='image_url']
    assert len(images)==2
    delivered=Image.open(io.BytesIO(base64.b64decode(images[1].split(',',1)[1])))
    assert delivered.getpixel((20,packed['text_region'][1]+20))==(255,0,0)
    assert delivered.getpixel((20,packed['arrow_region'][1]+20))==(0,0,255)


def test_touching_word_expansion_preserves_existing_full_word_and_ambiguity():
    from graph_qwen_local_text import _refine_touching_glyph
    partial={'box':[30,30,36,40],'parts':1}
    complete={'box':[20,20,38,42],'parts':2}
    unrelated={'box':[80,20,98,42],'parts':2}
    result=_refine_touching_glyph(partial,[complete,unrelated])
    assert result['box']==complete['box'] and result['native_line_separated']
    assert _refine_touching_glyph(complete,[unrelated]) is complete
    assert _refine_touching_glyph(partial,[complete,dict(complete)]) is partial
