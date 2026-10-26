"""Reuse the existing complete blue-line detector for anonymous grid drawings."""
from graph_schema import canonical_graph


def measured_anonymous_panels(raw,observed):
    if len(observed)<2:return None
    for graph in observed:
        if graph['directed'] is not False or graph['weighted'] is not False:return None
        if any(v['label'] for v in graph['vertices']):return None
        if any(e['weight'] is not None or e['edge_label'] for e in graph['edges']):return None
    from graph_sparse_panels import recognize_blue_outline_panels
    result=recognize_blue_outline_panels(raw)
    if result['status']!='detected' or len(result['graphs'])!=len(observed):return None
    graphs=[]
    for prior,measured in zip(observed,result['graphs']):
        graph=canonical_graph({**measured,'id':prior['id'],'name':prior['name'],
            'directed':False,'weighted':False,'multigraph':False,'complete':False,
            'node_complete':True,
            'edges':[{'id':f'line_{i+1}','from':a,'to':b,
                'direction':'undirected','style':'solid',
                'evidence':[{'source':'pixels','method':result['detector']}]} for i,(a,b) in enumerate(measured['edges'])]})
        graph['node_review']={'observed_vertices':prior['vertices'],
            'position_alignment':'complete_native_blue_endpoint_inventory'}
        graphs.append(graph)
    return graphs
