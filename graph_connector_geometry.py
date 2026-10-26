"""Conservative instances for outlined arrows, backed by original contours.

Two parallel lines alone never establish an arrow instance. Both shaft walls,
two flanks sharing a tip, and the two shoulder links must be visible. The same
geometry is checked again against unsharpened-original evidence by the caller.
"""
from __future__ import annotations

import math
import cv2
import numpy as np

from graph_node_geometry import boundary_distance, circle_geometry, contains_points, ray_entry


def _samples(field, points):
    xy = np.rint(points).astype(int)
    valid = ((xy[..., 0] >= 0) & (xy[..., 0] < field.shape[1]) &
             (xy[..., 1] >= 0) & (xy[..., 1] < field.shape[0]))
    x = np.clip(xy[..., 0], 0, field.shape[1]-1)
    y = np.clip(xy[..., 1], 0, field.shape[0]-1)
    return np.where(valid, field[y, x], 1000.)


def _segment(field, a, b, tolerance=1.5):
    length = float(np.linalg.norm(np.asarray(b)-a))
    points = np.linspace(a, b, max(16, min(160, math.ceil(length))))
    hits = _samples(field, points) <= tolerance
    longest = run = 0
    for hit in hits:
        run = 0 if hit else run+1
        longest = max(longest, run)
    return float(np.mean(hits)), longest/len(hits)


def same_outlined_instance(first, second, ink, size, *, offset=(0,0)):
    """Both observed shaft ridges must coincide; white parallel gaps veto."""
    if first.get('head_vertex')!=second.get('head_vertex'):
        return False
    try:
        a=np.asarray(first['shaft_boundaries'],float)*np.asarray([size[0]-1,size[1]-1])-offset
        b=np.asarray(second['shaft_boundaries'],float)*np.asarray([size[0]-1,size[1]-1])-offset
        if a.shape!=(2,2,2) or b.shape!=(2,2,2):return False
    except (KeyError,ValueError,TypeError):return False
    def project(point):
        x,y=np.rint(point).astype(int)
        if 0<=x<ink.shape[1] and 0<=y<ink.shape[0] and ink[y,x]:return point
        lx,rx=max(0,x-2),min(ink.shape[1],x+3)
        ty,by=max(0,y-2),min(ink.shape[0],y+3)
        yy,xx=np.nonzero(ink[ty:by,lx:rx])
        if not len(xx):return None
        choices=np.column_stack([xx+lx,yy+ty])
        index=int(np.argmin(np.linalg.norm(choices-point,axis=1)))
        return choices[index].astype(float) if np.linalg.norm(choices[index]-point)<=2.4 else None
    def ridge(source,target):
        vector=target[1]-target[0];den=float(vector@vector)
        if den<1:return False
        inspected=matched=0
        for fraction in np.linspace(.12,.88,40):
            point=source[0]+fraction*(source[1]-source[0])
            t=float(np.clip((point-target[0])@vector/den,0,1))
            neighbour=target[0]+t*vector
            p,q=project(point),project(neighbour)
            if p is None or q is None:continue
            inspected+=1
            if np.linalg.norm(p-q)>5.:continue
            bridge=np.rint(np.linspace(p,q,13)).astype(int)
            if ((bridge[:,0]<0).any() or (bridge[:,0]>=ink.shape[1]).any() or
                    (bridge[:,1]<0).any() or (bridge[:,1]>=ink.shape[0]).any()):continue
            matched+=int(np.mean(ink[bridge[:,1],bridge[:,0]]>0)>=.90)
        return inspected>=22 and matched/max(1,inspected)>=.90
    return any(all(ridge(a[i],b[j]) and ridge(b[j],a[i]) for i,j in enumerate(order))
               for order in ((0,1),(1,0)))


def _outlined_candidates_for_axis(ink, local, geometry, radii, default_radius,
                                 *, offset, full_size, diagnostics=None,
                                 axis_override=None, shift_extent=2., distance_field=None, ridge_field=None):
    """Find bounded straight outlined-arrow hypotheses between known nodes.

    This does not infer arbitrary missing lines or all arrow drawing styles.
    Paths retain both walls and the head/shoulder evidence as an instance.
    """
    if len(local) > 30:
        return []
    field = (distance_field if distance_field is not None else
             cv2.distanceTransform(np.uint8(ink == 0), cv2.DIST_L2, 3))
    ridge_cost=(ridge_field if ridge_field is not None else
                field-.35*cv2.distanceTransform(np.uint8(ink>0),cv2.DIST_L2,3))
    w, h = full_size
    def normalized(point):
        return [round(float((point[0]+offset[0])/max(1,w-1)),6),
                round(float((point[1]+offset[1])/max(1,h-1)),6)]
    output = []
    for i, (first, ax, ay) in enumerate(local):
        for second, bx, by in local[i+1:]:
            origin = np.asarray([ax,ay],float)
            target = np.asarray([bx,by],float)
            length = float(np.linalg.norm(target-origin))
            if length < 55:
                continue
            axis = (target-origin)/length
            if axis_override is not None:
                axis=np.asarray(axis_override[1],float)
            normal = np.asarray([-axis[1],axis[0]])
            ga = geometry.get(first) or circle_geometry(origin,radii.get(first,default_radius))
            gb = geometry.get(second) or circle_geometry(target,radii.get(second,default_radius))
            midpoint=(origin+target)/2
            if axis_override is not None:
                midpoint=np.asarray(axis_override[0],float)
            port_a=ray_entry(midpoint,-axis,ga,margin=1.)
            port_b=ray_entry(midpoint,axis,gb,margin=1.)
            if port_a is None or port_b is None:
                continue
            visible=float((port_b-port_a)@axis)
            if visible<38:
                continue
            # Other known nodes block a connecting instance even when its
            # visible walls happen to form a plausible outline.
            middle=np.linspace(port_a+axis*3,port_b-axis*3,64)
            if any(name not in (first,second) and np.any(contains_points(middle,g,margin=1.))
                   for name,g in geometry.items()):
                continue
            ts=np.linspace(3.,visible-3.,160)
            base=port_a+ts[:,None]*axis
            cross_extent=math.ceil(shift_extent+12.)
            offsets=np.arange(-cross_extent,cross_extent+.01,.5)
            sampled=_samples(field,base[:,None,:]+offsets[None,:,None]*normal)
            sampled_cost=_samples(ridge_cost,base[:,None,:]+offsets[None,:,None]*normal)
            coverage=np.mean(sampled<=1.3,axis=0)
            hypotheses=[]
            for shift in np.arange(-shift_extent,shift_extent+.1,1.):
                centre_index=int(round((shift+cross_extent)*2))
                white=float(np.mean(sampled[:,centre_index]>1.8))
                if white<.60:
                    continue
                for half in np.arange(2.,min(12.,visible*.08)+.1,.5):
                    low=int(round((shift-half+cross_extent)*2));high=int(round((shift+half+cross_extent)*2))
                    strength=min(float(coverage[low]),float(coverage[high]))
                    if strength>=.63:
                        alignment=float(np.mean(np.clip(sampled_cost[:,[low,high]],-2.,2.)))
                        hypotheses.append((strength-.08*alignment-.015*abs(shift),shift,half))
            selected=[]
            for value in sorted(hypotheses,reverse=True):
                if any(abs(value[1]-old[1])<1.1 and abs(value[2]-old[2])<1.1 for old in selected):
                    continue
                selected.append(value)
                if len(selected)==3:break
            best=None
            max_flank_score=max_shoulder_score=0.
            head_trials=0
            for _,shift,half in selected:
                shifted_a=ray_entry(midpoint+normal*shift,-axis,ga,margin=1.)
                shifted_b=ray_entry(midpoint+normal*shift,axis,gb,margin=1.)
                if shifted_a is None or shifted_b is None:
                    continue
                for reverse in (False,True):
                    direction=-axis if reverse else axis
                    head_node,tail_node=(first,second) if reverse else (second,first)
                    head_geometry,tail_geometry=(ga,gb) if reverse else (gb,ga)
                    near_tip=shifted_a if reverse else shifted_b
                    tail=(shifted_b if reverse else shifted_a)+direction*2.
                    for tip_offset in (-3.,-1.,1.,3.):
                        tip=near_tip+direction*tip_offset
                        if abs(float(boundary_distance(tip,head_geometry)))>4.5:
                            continue
                        for head_length in np.arange(max(12.,half*2.4),min(42.,visible*.24)+.1,2.):
                            shoulder_centre=tip-direction*head_length
                            shaft=[(tail-normal*half,shoulder_centre-normal*half),
                                   (tail+normal*half,shoulder_centre+normal*half)]
                            shaft_scores=[_segment(field,*line) for line in shaft]
                            if any(score<.73 or gap>.20 for score,gap in shaft_scores):
                                continue
                            for head_half in np.arange(max(half+5.,half*1.8),min(26.,half*3.6)+.1,2.):
                                if not 1.05<=head_length/head_half<=3.5:
                                    continue
                                wings=[shoulder_centre-normal*head_half,shoulder_centre+normal*head_half]
                                if any(contains_points(wing,head_geometry,margin=1.) for wing in wings):
                                    continue
                                flanks=[(wings[0],tip),(wings[1],tip)]
                                flank_scores=[_segment(field,*line)[0] for line in flanks]
                                head_trials+=1
                                max_flank_score=max(max_flank_score,min(flank_scores))
                                if min(flank_scores)<.80:
                                    continue
                                shoulders=[(shaft[0][1],wings[0]),(shaft[1][1],wings[1])]
                                shoulder_scores=[_segment(field,*line,tolerance=.9)[0] for line in shoulders]
                                max_shoulder_score=max(max_shoulder_score,min(shoulder_scores))
                                if min(shoulder_scores)<.75:
                                    continue
                                score=min([value[0] for value in shaft_scores]+flank_scores+shoulder_scores)
                                cost=float(np.mean([np.mean(np.clip(_samples(ridge_cost,np.linspace(*line,32)),-2.,2.))
                                                    for line in shaft+flanks+shoulders]))
                                rank=score-.08*cost
                                if best is not None and rank<=best[0]:
                                    continue
                                meta={'kind':'outlined_arrow','pairing':'shared_tip_and_shoulders',
                                      'shaft_boundaries':[[normalized(p) for p in line] for line in shaft],
                                      'head_flanks':[[normalized(p) for p in line] for line in flanks],
                                      'shoulders':[[normalized(p) for p in line] for line in shoulders],
                                      'tip':normalized(tip),'tail':normalized(tail),
                                      'head_vertex':head_node,'tail_vertex':tail_node,'proposal_only':True}
                                best=(rank,meta,score)
            if best:
                rank,meta,score=best
                output.append({'from':first,'to':second,'path':[meta['tail'],meta['tip']],
                               'pixel_length':round(visible),'score':round(score,3),
                               '_fit_rank':round(rank,5),
                               'style':'solid','method':'opencv_outlined_arrow_instance',
                               'needs_review':True,'connector_evidence':meta})
            if diagnostics is not None and selected:
                diagnostics.append({'endpoints':[first,second],'shaft_hypotheses':selected,
                                    'head_trials':head_trials,'maximum_flank_support':max_flank_score,
                                    'maximum_shoulder_support_after_flanks':max_shoulder_score,
                                    'instance_found':bool(best)})
    return output


def outlined_arrow_candidates(ink, local, geometry, radii, default_radius,
                              *, offset, full_size, diagnostics=None):
    """Use observed line orientations, not a forced node-centre direction.

    At most five line-axis hypotheses per endpoint pair are searched. Each
    retained instance is distinguished by its walls and head, allowing more
    than one connector for the same pair of nodes.
    """
    if len(local)>30:return []
    field=cv2.distanceTransform(np.uint8(ink==0),cv2.DIST_L2,3)
    ridge_field=field-.35*cv2.distanceTransform(np.uint8(ink>0),cv2.DIST_L2,3)
    detected=cv2.HoughLinesP(cv2.Canny(ink,55,145),1,math.pi/720,
                             threshold=18,minLineLength=28,maxLineGap=7)
    segments=[]
    if detected is not None:
        for x,y,xx,yy in np.asarray(detected).reshape(-1,4)[:400]:
            vector=np.asarray([xx-x,yy-y],float);length=float(np.linalg.norm(vector))
            if length>=28:
                segments.append((length,(np.asarray([x,y])+np.asarray([xx,yy]))/2,vector/length))
    segments.sort(key=lambda row:-row[0])
    output=[]
    scale=np.asarray([full_size[0]-1,full_size[1]-1])
    for i,first in enumerate(local):
        for second in local[i+1:]:
            origin=np.asarray(first[1:],float);target=np.asarray(second[1:],float)
            distance=float(np.linalg.norm(target-origin))
            if distance<55:continue
            direction=(target-origin)/distance
            ga=geometry.get(first[0]) or circle_geometry(origin,radii.get(first[0],default_radius))
            gb=geometry.get(second[0]) or circle_geometry(target,radii.get(second[0],default_radius))
            axes=[((origin+target)/2,direction)]
            for length,anchor,vector in segments:
                if abs(float(vector@direction))<.94:continue
                if float(vector@direction)<0:vector=-vector
                if not .02<=float((anchor-origin)@direction/distance)<=.98:continue
                if ray_entry(anchor,-vector,ga,margin=1.) is None or ray_entry(anchor,vector,gb,margin=1.) is None:
                    continue
                if any(abs(float(vector@old_direction))>.9996 and
                       abs(float(np.cross(vector,anchor-old_anchor)))<3.
                       for old_anchor,old_direction in axes):continue
                axes.append((anchor,vector))
                if len(axes)==5:break
            instances=[]
            extent=float(max(2,min(10,math.floor(min(radii.get(first[0],default_radius),radii.get(second[0],default_radius))*.25))))
            for axis in axes:
                found=_outlined_candidates_for_axis(ink,[first,second],geometry,radii,default_radius,
                                                      offset=offset,full_size=full_size,
                                                      diagnostics=diagnostics,axis_override=axis,
                                                      shift_extent=extent,distance_field=field,ridge_field=ridge_field)
                for candidate in found:
                    meta=candidate['connector_evidence']
                    tip=np.asarray(meta['tip'])*scale
                    middle=np.mean(np.asarray(meta['shaft_boundaries'])*scale,axis=(0,1))
                    match=None
                    for k,old in enumerate(instances):
                        oldmeta=old['connector_evidence']
                        oldtip=np.asarray(oldmeta['tip'])*scale
                        oldmiddle=np.mean(np.asarray(oldmeta['shaft_boundaries'])*scale,axis=(0,1))
                        if (np.linalg.norm(tip-oldtip)<=10. and
                                same_outlined_instance(meta,oldmeta,ink,full_size,offset=offset)):
                            match=k;break
                    if match is None:instances.append(candidate)
                    elif candidate.get('_fit_rank',candidate['score'])>instances[match].get('_fit_rank',instances[match]['score']):instances[match]=candidate
            instances.sort(key=lambda row:-row['score'])
            for instance in instances[:4]:
                instance['connector_evidence']['limits']={'axis_hypotheses':len(axes),'axis_cap':5,
                                                          'instance_cap_reached':len(instances)>4}
            output.extend(instances[:4])
    return output


def _outline_route_binding(path, size, shaft, tip, geometries):
    """Bind the proposed route to this white-centred instance, not its pair.

    The route need not contain ink. Its portion outside the endpoint markers
    must traverse this measured shaft/head centreline through the same ports.
    Samples are bounded and retain short detours and retracing, which an
    endpoint-only or average-overlap check would miss.
    """
    result={'valid':False,'source':'measured_outline_centreline'}
    try:
        if not isinstance(path,list) or not 2<=len(path)<=128:
            raise ValueError('invalid_outline_route')
        points=np.asarray(path,float)
        if points.shape!=(len(path),2) or not np.isfinite(points).all() or (points<0).any() or (points>1).any():
            raise ValueError('invalid_outline_route')
        points*=np.asarray([size[0]-1,size[1]-1])
        lengths=np.linalg.norm(np.diff(points,axis=0),axis=1)
        cumulative=np.r_[0.,np.cumsum(lengths)]
        if cumulative[-1]<2:raise ValueError('invalid_outline_route')
        samples=np.linspace(0,cumulative[-1],min(4096,max(24,math.ceil(cumulative[-1]/1.5))))
        route=np.stack([np.interp(samples,cumulative,points[:,i]) for i in range(2)],axis=1)
        keep=np.ones(len(route),bool)
        for geometry in geometries:keep &= ~contains_points(route,geometry,margin=1.)
        route=route[keep]
        if len(route)<6:raise ValueError('outline_route_missing_span')
        tail=np.mean(shaft[:,0],axis=0)
        base=np.mean(shaft[:,1],axis=0)
        axis=tip-tail;length=float(np.linalg.norm(axis));axis/=max(length,1e-6)
        if length<25:raise ValueError('outline_route_missing_span')
        if np.linalg.norm(route[-1]-tail)<np.linalg.norm(route[0]-tail):route=route[::-1]
        projection=(route-tail)@axis
        # The fitted tip can be a few pixels inside the measured marker wall.
        # Permit that finite port uncertainty without widening the whole shaft.
        port_tolerance=6.5
        width=float(np.mean(np.linalg.norm(shaft[0]-shaft[1],axis=1)))
        tolerance=max(1.75,min(3.,width*.20))
        distance=np.full(len(route),np.inf)
        for start,end in ((tail,base),(base,tip)):
            vector=end-start;den=float(vector@vector)
            fraction=np.clip((route-start)@vector/max(den,1e-6),0,1)
            distance=np.minimum(distance,np.linalg.norm(route-(start+fraction[:,None]*vector),axis=1))
        core=(projection>port_tolerance)&(projection<length-port_tolerance)
        near_port=np.minimum(np.linalg.norm(route-tail,axis=1),np.linalg.norm(route-tip,axis=1))
        bounded=(distance<=tolerance)|(near_port<=port_tolerance)
        backtrack=float(-np.sum(np.minimum(np.diff(projection),0)))
        result.update(maximum_centreline_distance_pixels=round(float(np.max(distance[core])) if np.any(core) else 0.,3),
                      maximum_port_zone_distance_pixels=round(float(np.max(near_port[~core])) if np.any(~core) else 0.,3),
                      centreline_tolerance_pixels=round(tolerance,3),
                      tail_port_error_pixels=round(float(np.linalg.norm(route[0]-tail)),3),
                      head_port_error_pixels=round(float(np.linalg.norm(route[-1]-tip)),3),
                      projection_span_fraction=round(float((projection[-1]-projection[0])/length),4),
                      backtrack_pixels=round(backtrack,3))
        if (not np.all(bounded) or not np.any(core) or np.max(distance[core])>tolerance or
                np.min(projection)<-port_tolerance or np.max(projection)>length+port_tolerance or
                np.linalg.norm(route[0]-tail)>port_tolerance or
                np.linalg.norm(route[-1]-tip)>port_tolerance or
                projection[-1]-projection[0]<length-2*port_tolerance or
                backtrack>max(3.,length*.02)):
            raise ValueError('outline_route_instance_mismatch')
        result['valid']=True
    except (ValueError,TypeError,KeyError,IndexError) as error:
        result['reason']=str(error)
    return result


def validate_outlined_arrow(meta, edge, size, distance, strong_distance, geometries, *, all_distance=None):
    """Check shape and every constituent against original evidence fields."""
    result={'valid':False,'reasons':[],'source':'original_outline_boundaries'}
    w,h=size
    try:
        if not isinstance(meta,dict) or meta.get('kind')!='outlined_arrow':
            return result
        arrays={name:np.asarray(meta[name],float) for name in ('shaft_boundaries','head_flanks','shoulders')}
        if any(value.shape!=(2,2,2) or not np.isfinite(value).all() or
               (value<0).any() or (value>1).any() for value in arrays.values()):
            raise ValueError('invalid_outline_coordinates')
        arrays={name:value*np.asarray([w-1,h-1]) for name,value in arrays.items()}
        shaft,flanks,shoulders=(arrays[name] for name in ('shaft_boundaries','head_flanks','shoulders'))
        head,tail=meta.get('head_vertex'),meta.get('tail_vertex')
        if head==tail or {head,tail}!={edge['from'],edge['to']} or head not in geometries or tail not in geometries:
            raise ValueError('outline_endpoint_identity')
        vectors=shaft[:,1]-shaft[:,0]
        lengths=np.linalg.norm(vectors,axis=1)
        if min(lengths)<25 or float(vectors[0]@vectors[1]/np.prod(lengths))<.995:
            raise ValueError('outline_nonparallel_shaft')
        widths=np.linalg.norm(shaft[0]-shaft[1],axis=1)
        if not 3.5<=float(np.mean(widths))<=26 or abs(float(widths[0]-widths[1]))>2.:
            raise ValueError('outline_width_inconsistent')
        if np.max(np.linalg.norm(shoulders[:,0]-shaft[:,1],axis=1))>1. or np.max(np.linalg.norm(shoulders[:,1]-flanks[:,0],axis=1))>1.:
            raise ValueError('outline_disconnected_shoulders')
        if np.linalg.norm(flanks[0,1]-flanks[1,1])>1.:
            raise ValueError('outline_no_common_tip')
        tip=np.mean(flanks[:,1],axis=0)
        base=np.mean(shaft[:,1],axis=0)
        direction=np.mean(vectors/lengths[:,None],axis=0)
        head_length=float((tip-base)@direction)
        lateral=abs(float(np.cross(direction,tip-base)))
        head_width=float(np.linalg.norm(flanks[0,0]-flanks[1,0]))
        if (not widths.mean()*.8<=head_length<=50 or lateral>widths.mean()*.2+1
                or head_width<widths.mean()+9.):
            raise ValueError('outline_head_shape')
        if abs(float(boundary_distance(tip,geometries[head])))>4.5 or abs(float(boundary_distance(np.mean(shaft[:,0],axis=0),geometries[tail])))>4.5:
            raise ValueError('outline_port_attachment')
        binding=_outline_route_binding(edge.get('path'),size,shaft,tip,
                                       [geometries[head],geometries[tail]])
        result['route_binding']=binding
        if not binding['valid']:
            raise ValueError(binding.get('reason','outline_route_instance_mismatch'))
        scores={};strong=[];strong_by_component={};gaps=[]
        original_field=all_distance if all_distance is not None else distance
        for name,segments in arrays.items():
            tolerance=.9 if name=='shoulders' else 1.5
            metrics=[_segment(original_field,*line,tolerance=tolerance) for line in segments]
            scores[name]=[score for score,_ in metrics]
            current_strong=[_segment(strong_distance,*line,tolerance=tolerance)[0] for line in segments]
            strong_by_component[name]=current_strong
            strong.extend(current_strong)
            gaps.extend(gap for _,gap in metrics)
        result.update(component_coverage=scores,component_strong_coverage=strong_by_component,
                      longest_gap_fraction=max(gaps))
        if min(scores['shaft_boundaries'])<.73 or min(scores['head_flanks'])<.80 or min(scores['shoulders'])<.75 or max(gaps)>.20:
            raise ValueError('outline_missing_original_boundary')
        # One faint wall may be supported by its clear companion and a
        # shared, strongly inked head. Entirely faint/bleed-through arrows
        # remain uncertain; enhancement never supplies the missing evidence.
        if (max(strong_by_component['shaft_boundaries'])<.65 or
                np.mean(strong_by_component['shaft_boundaries'])<.45 or
                min(strong_by_component['head_flanks'])<.55 or
                min(strong_by_component['shoulders'])<.55):
            raise ValueError('outline_weak_or_bleedthrough_ambiguity')
        result.update(valid=True,coverage=min(x for row in scores.values() for x in row),
                      strong_coverage=float(np.mean(strong)),
                      weak_wall=bool(min(strong_by_component['shaft_boundaries'])<.40),
                      head_vertex=head,tail_vertex=tail)
    except (ValueError,TypeError,KeyError,IndexError) as error:
        result['reasons'].append(str(error))
    return result
