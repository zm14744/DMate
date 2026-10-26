"""Total counts must not conceal per-figure missing/imaginary vertices."""
import numpy as np
from PIL import Image,ImageDraw
from graph_schema import canonical_graph
from graph_qwen_components import reconcile_component_inventory,assign_components


def scene(extra_colored=False):
    image=Image.new('RGB',(600,300),'white');draw=ImageDraw.Draw(image)
    left=[(50,80),(200,80),(200,220),(50,220)]
    right=[(350,80),(500,80),(500,220),(350,220),(425,150)]
    draw.line(left+[left[0]],fill='black',width=3)
    draw.line(right[:4]+[right[0]],fill='black',width=3)
    draw.line([right[0],right[4],right[2]],fill='black',width=3)
    rgb=np.asarray(image).copy();yy,xx=np.mgrid[:300,:600]
    for x,y in left+right:
        inside=(xx-x)**2+(yy-y)**2<=21**2
        values=np.clip(130+(xx-x+yy-y)*3,20,229).astype('uint8')
        rgb[inside]=values[inside,None]
    image=Image.fromarray(rgb)
    if extra_colored:ImageDraw.Draw(image).ellipse((104,129,146,171),fill='red')
    graphs=[]
    for gi,points in enumerate([left+[(125,150)],right[:4]]):
        graphs.append(canonical_graph({'id':f'G{gi}','bbox':([0,.1,.43,.9] if gi==0 else [.5,.1,.95,.9]),
            'directed':bool(gi),'weighted':False,'vertices':[
                {'id':f'v{i}','label':f'label{i}','x':x/599,'y':y/299} for i,(x,y) in enumerate(points)],
            'edges':[{'id':'keep','from':'v0','to':'v1','direction':'forward' if gi else 'undirected',
                      'path':[[points[0][0]/599,points[0][1]/299],[points[1][0]/599,points[1][1]/299]]}]}))
    return image,graphs


def test_same_total_with_wrong_distribution_preserves_names_and_adds_only_measured_nodes():
    image,graphs=scene();output,notes=reconcile_component_inventory(image,graphs)
    assert [len(g['vertices']) for g in output]==[4,5]
    assert sum(len(g['vertices']) for g in output)==sum(len(g['vertices']) for g in graphs)
    assert output[0]['vertices'][0]['label']=='label0'
    assert all(v['id']!='v4' for v in output[0]['vertices'])
    assert sum(v['label'] is None for v in output[1]['vertices'])==1
    assert output[1]['directed'] is True and output[1]['edges'][0]['id']=='keep'
    assert len(notes)==2 and len(graphs[0]['vertices'])==5


def test_unmatched_filled_disk_prevents_dropping_a_real_colored_vertex():
    image,graphs=scene(extra_colored=True);output,notes=reconcile_component_inventory(image,graphs)
    assert output==graphs
    assert notes==['component_inventory_abstained:unmatched_filled_ink']


def test_spatially_tied_components_do_not_relabel_figures():
    _,graphs=scene()
    for graph in graphs:graph['bbox']=[0,0,1,1]
    groups={1:[{'x':x,'y':y} for x,y in [(.1,.2),(.3,.2),(.3,.8),(.1,.8)]],
            2:[{'x':x,'y':y} for x,y in [(.7,.2),(.9,.2),(.9,.8),(.7,.8)]]}
    assert assign_components(graphs,groups) is None


def test_duplicate_model_frames_are_only_a_provisional_measured_reading_order():
    image,graphs=scene();graphs[1]['bbox']=graphs[0]['bbox'][:]
    output,notes=reconcile_component_inventory(image,graphs)
    assert [len(g['vertices']) for g in output]==[4,5]
    assert 'component_frame_reading_order_provisional' in notes
    assert all(g['complete'] is False for g in output)


def test_a_smaller_filled_arrowhead_is_not_kept_as_a_shaded_disk_vertex():
    image,graphs=scene()
    ImageDraw.Draw(image).polygon([(125,136),(113,161),(137,161)],fill='black')
    output,notes=reconcile_component_inventory(image,graphs)
    assert [len(g['vertices']) for g in output]==[4,5]
    assert len(notes)==2


def test_flat_blob_filter_preserves_a_small_round_vertex():
    import cv2
    from graph_qwen_components import _small_flat_asymmetric_blob
    image=Image.new('L',(90,90),255)
    ImageDraw.Draw(image).ellipse((32,32,58,58),fill=0)
    gray=np.asarray(image)
    _,labels,stats,_=cv2.connectedComponentsWithStats(np.uint8(gray<230)*255,8)
    assert not _small_flat_asymmetric_blob(gray,labels,stats,45,45,24)


def test_flat_blob_filter_recognizes_a_small_asymmetric_head():
    import cv2
    from graph_qwen_components import _small_flat_asymmetric_blob
    image=Image.new('L',(90,90),255)
    ImageDraw.Draw(image).polygon([(45,27),(30,57),(60,57)],fill=0)
    gray=np.asarray(image)
    _,labels,stats,_=cv2.connectedComponentsWithStats(np.uint8(gray<230)*255,8)
    assert _small_flat_asymmetric_blob(gray,labels,stats,45,47,24)
