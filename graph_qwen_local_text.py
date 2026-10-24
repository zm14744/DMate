"""One keyed native glyph sheet for measured unweighted graph attributes."""
import base64,copy,io,math
import networkx as nx
from PIL import Image,ImageDraw,ImageFont
from graph_qwen_edge_text import _glyphs,_projection
from graph_qwen_text_inventory import _key
from graph_qwen_edge_text import EDGE_TEXT_PROMPT
from graph_qwen_coordinates import graph_name

LOCAL_TEXT_PROMPT=EDGE_TEXT_PROMPT+'\nkind=figure_name 时完整抄写图名和运算符、集合、下标；原图斜杠与反斜杠必须区分，不替换成理论中的其他记法。'


def pack_uncertainty_sheets(text_plan,arrow_plan):
    """Keep both native sheets inside the provider's two-image transport."""
    texts=Image.open(io.BytesIO(base64.b64decode(text_plan['image_url'].split(',',1)[1]))).convert('RGB')
    arrows=Image.open(io.BytesIO(base64.b64decode(arrow_plan['image_url'].split(',',1)[1]))).convert('RGB')
    width=max(texts.width,arrows.width);height=texts.height+arrows.height+64
    if width*height>8_000_000:raise ValueError('combined_uncertainty_sheet_budget')
    sheet=Image.new('RGB',(width,height),'white');draw=ImageDraw.Draw(sheet);font=ImageFont.load_default(size=20)
    draw.text((8,5),'TEXT / readings',fill='black',font=font);sheet.paste(texts,(0,32))
    bottom=texts.height+32;draw.text((8,bottom+5),'ARROWS / arrows',fill='black',font=font);sheet.paste(arrows,(0,bottom+32))
    stream=io.BytesIO();sheet.save(stream,format='PNG')
    return {'image_url':'data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode(),
            'sheet_size':list(sheet.size),'text_region':[0,32,texts.width,texts.height+32],
            'arrow_region':[0,bottom+32,arrows.width,height]}


def _match_edge_glyphs(image,graph,glyphs):
    matching=nx.Graph()
    for ei,edge in enumerate(graph['edges']):
        for ti,glyph in enumerate(glyphs):
            projected=_projection(glyph['center'],edge['path'],image.size)
            if projected is None:continue
            distance,along=projected;h=glyph['box'][3]-glyph['box'][1]
            if .15<=along<=.85 and distance<=max(28,h*1.5):
                matching.add_edge(('e',ei),('t',ti),weight=distance/max(10,h))
    best=nx.min_weight_matching(matching)
    if len(best)!=len(graph['edges']):return None
    total=sum(matching[a][b]['weight'] for a,b in best)
    for a,b in best:
        cost=matching[a][b]['weight'];matching.remove_edge(a,b)
        alternative=nx.min_weight_matching(matching)
        ambiguous=(len(alternative)==len(graph['edges']) and sum(matching[u][v]['weight'] for u,v in alternative)-total<.15)
        matching.add_edge(a,b,weight=cost)
        if ambiguous:return None
    pairs=[]
    for a,b in best:
        if a[0]=='t':a,b=b,a
        pairs.append((a[1],b[1]))
    return pairs


def _assigned_script_fragments(glyphs,pairs):
    """Two edge reads must not consume the body and subscript of ONE word."""
    selected=[glyphs[ti] for _,ti in pairs]
    for body in selected:
        if body['parts']!=1:continue
        x,y,r,b=body['box'];h=b-y
        if h<15:continue
        for script in selected:
            if script is body or script['parts']!=1:continue
            xx,yy,rr,bb=script['box'];hh=bb-yy
            if (h*.98<hh<=h*1.1 and rr-xx<=hh*.85 and -.25*h<=xx-r<=.55*h
                    and yy>=y+h*.1 and b+h*.2<=bb<=b+h*.7):return True
    return False


def prepare_local_text(image,graphs,*,force=False):
    if (not graphs or any(type(g['directed']) is not bool or g['weighted'] is not False for g in graphs)
            or (not force and not any(e['edge_label'] is None for g in graphs for e in g['edges']))):
        return None
    items=[];width,height=image.size
    for gi,g in enumerate(graphs):
        if g.get('node_review',{}).get('native_candidate_missing_labels'):continue
        if not any(e['edge_label'] is None for e in g['edges']):continue
        rebind=bool(g.get('node_review',{}).get('unsupported_edge_proposals')) and any(e['edge_label'] is not None for e in g['edges'])
        anchors=g.get('node_position_evidence',[])
        if len(anchors)!=len(g['vertices']) or any('partial' in p['source'] for p in anchors):return None
        if not g['edges'] or any(not e['path'] for e in g['edges']):return None
        radii={p['vertex']:p['radius_pixels'] for p in anchors if p.get('radius_pixels')}
        glyphs=_glyphs(image,g['bbox'],g['vertices'],join_scripts=True,node_radii=radii)
        separated=_glyphs(image,g['bbox'],g['vertices'],join_scripts=True,node_radii=radii,
            line_paths=[e['path'] for e in g['edges']])
        pairs=_match_edge_glyphs(image,g,glyphs)
        if pairs is None:return None
        repaired=False
        if _assigned_script_fragments(glyphs,pairs):
            alternate=_glyphs(image,g['bbox'],g['vertices'],join_scripts=True,node_radii=radii,allow_equal_scripts=True)
            alternate_pairs=_match_edge_glyphs(image,g,alternate)
            if alternate_pairs is not None and not _assigned_script_fragments(alternate,alternate_pairs):
                glyphs=alternate;pairs=alternate_pairs;repaired=True
                separated=_glyphs(image,g['bbox'],g['vertices'],join_scripts=True,node_radii=radii,
                    line_paths=[e['path'] for e in g['edges']],allow_equal_scripts=True)
        for ei,ti in sorted(pairs):
            # A rejected model stroke can leave its name on another route.
            # Recheck edge text in that affected figure, without re-reading
            # already grounded node labels or touching other figures.
            if g['edges'][ei]['edge_label'] is not None and not rebind:continue
            glyph=_refine_touching_glyph(glyphs[ti],separated)
            x,y,r,bottom=glyph['box']
            if glyph['parts']==1:
                # A thin subscript can be a separate fragment; the letter may
                # itself touch the diagram stroke. Preserve the native word
                # neighbourhood instead of presenting an isolated digit.
                h=bottom-y
                x-=math.ceil(h*1.6);r+=math.ceil(h*.9)
                y-=math.ceil(h*1.2);bottom+=math.ceil(h*.4)
            items.append({'key':_key(len(items)),'kind':'edge_label','graph_index':gi,
                'id':g['edges'][ei]['id'],'rect':[max(0,x-2),max(0,y-2),min(width,r+2),min(height,bottom+2)],
                'native_line_separated':bool(glyph.get('native_line_separated')),
                **({'native_competing_script_fragments_repaired':True} if repaired else {})})
    # Keep the complete native name around its measured marker, including
    # thin subscripts which connected-component cleanup can discard.
    for gi,g in enumerate(graphs):
        if not force and not any(v['label'] is not None for v in g['vertices']):continue
        for v in g['vertices']:
            if v['label'] is not None:continue
            x,y=v['x']*(width-1),v['y']*(height-1)
            nearest=min((math.hypot((v['x']-u['x'])*(width-1),(v['y']-u['y'])*(height-1))
                for u in g['vertices'] if u['id']!=v['id']),default=150.)
            pad=max(34,min(55,nearest*.36))
            rect=[max(0,math.floor(x-pad)),max(0,math.floor(y-pad)),
                  min(width,math.ceil(x+pad)),min(height,math.ceil(y+pad))]
            items.append({'key':_key(len(items)),'kind':'vertex_label','graph_index':gi,'id':v['id'],'rect':rect})
    needs_captions=any(g.get('node_review',{}).get('component_inventory_observations',{}).get('frame_reading_order_provisional') for g in graphs)
    caption_items=_caption_items(image,graphs,len(items)) if needs_captions else []
    if not items:return None
    columns=min(9,len(items));sheet_width=max(columns*160,1440 if caption_items else 0)
    text_height=math.ceil(len(items)/columns)*160
    caption_height=math.ceil(len(caption_items)/3)*160
    if text_height+caption_height>1600:return None
    sheet=Image.new('RGB',(sheet_width,text_height+caption_height),'white')
    draw=ImageDraw.Draw(sheet);font=ImageFont.load_default(size=18)
    for i,item in enumerate(items+caption_items):
        is_caption=i>=len(items)
        if is_caption:
            index=i-len(items);x,y=index%3*480,text_height+index//3*160;cell_width=480
        else:x,y=i%columns*160,i//columns*160;cell_width=160
        draw.rectangle((x,y,x+cell_width-1,y+23),fill='#dddddd');draw.text((x+6,y+2),item['key'],font=font,fill='black')
        crop=image.crop(item['rect']);zoom=max(1,min(3,(cell_width-12)//crop.width,128//crop.height))
        if zoom>1:crop=crop.resize((crop.width*zoom,crop.height*zoom),Image.Resampling.NEAREST)
        if crop.width>cell_width-12 or crop.height>128:return None
        sheet.paste(crop,(x+(cell_width-crop.width)//2,y+25+(132-crop.height)//2))
    stream=io.BytesIO();sheet.save(stream,format='PNG')
    return {'graphs':graphs,'items':items+caption_items,'image_url':'data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode(),'sheet_size':list(sheet.size)}


def _refine_touching_glyph(original,separated):
    """Expand only an assigned partial word; keep global glyph matching stable."""
    if original['parts']!=1:return original
    x,y,r,b=original['box'];candidates=[]
    for glyph in separated:
        a,top,c,d=glyph['box']
        overlap=max(0,min(c,r)-max(a,x))*max(0,min(d,b)-max(top,y))
        if (d-top)>1.3*(b-y) and overlap>=.5*min((c-a)*(d-top),(r-x)*(b-y)):
            candidates.append(glyph)
    if len(candidates)!=1:return original
    return {**candidates[0],'native_line_separated':True}


def _caption_items(image,graphs,offset):
    """Observe solid coloured caption rectangles below measured figure hulls."""
    import cv2,numpy as np
    hsv=cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2HSV)
    mask=cv2.inRange(hsv,(0,80,80),(179,255,255))
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    rects=[];width,height=image.size
    for contour in contours:
        x,y,w,h=cv2.boundingRect(contour)
        if 100<=w<=466 and 35<=h<=120 and w/h>2 and cv2.contourArea(contour)/(w*h)>.75:
            rects.append([x,y,x+w,y+h])
    matching=nx.Graph()
    for gi,g in enumerate(graphs):
        center=(min(v['x'] for v in g['vertices'])+max(v['x'] for v in g['vertices']))/2*(width-1)
        bottom=max(v['y'] for v in g['vertices'])*(height-1)
        for ri,(a,b,c,d) in enumerate(rects):
            dx=abs((a+c)/2-center)/width;dy=(b-bottom)/height
            if dx<.12 and .01<dy<.18:matching.add_edge(('g',gi),('r',ri),weight=dx+dy*.5)
    selected=nx.min_weight_matching(matching)
    if len(selected)!=len(graphs):return []
    items=[]
    for a,b in sorted(selected,key=str):
        if a[0]=='r':a,b=b,a
        gi,ri=a[1],b[1]
        items.append({'key':_key(offset+len(items)),'kind':'figure_name','graph_index':gi,
                      'id':graphs[gi]['id'],'rect':rects[ri]})
    return items


def apply_local_text(prepared,response):
    from graph_qwen_edge_text import apply_edge_text_inventory
    graphs=copy.deepcopy(prepared['graphs'])
    # Reuse the same strict keyed decoder; remap keys per selected figure.
    if not isinstance(response,dict) or not isinstance(response.get('readings'),list):
        raise ValueError('invalid_local_text_envelope')
    expected={item['key'] for item in prepared['items']}
    readings=response['readings']
    keys=[r.get('key') for r in readings if isinstance(r,dict)]
    if len(keys)!=len(readings) or len(keys)!=len(set(keys)) or set(keys)!=expected:
        raise ValueError('invalid_local_text_keys')
    for reading in readings:
        value=reading.get('text')
        if value is not None and (not isinstance(value,str) or len(value)>64):raise ValueError('invalid_local_text_value')
    for gi,g in enumerate(graphs):
        items=[item for item in prepared['items'] if item['graph_index']==gi and item['kind']!='figure_name']
        allowed={item['key'] for item in items}
        graphs[gi]=apply_edge_text_inventory({'graphs':[g],'items':items},
            {'readings':[r for r in readings if r['key'] in allowed]})[0]
    values={r['key']:r.get('text') for r in readings}
    for item in prepared['items']:
        if item['kind']!='figure_name':continue
        graph=graphs[item['graph_index']];text=values[item['key']]
        graph.setdefault('figure_name_evidence',[]).append({'source':'qwen_native_figure_caption','observed':text,'region':item['rect'],'prior_name':graph['name']})
        if text is not None and text.strip() not in ('','null','NULL'):graph['name']=graph_name(text.strip())
    return graphs
