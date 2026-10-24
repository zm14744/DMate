"""Bounded native cubic fits for measured large hollow-node diagrams.

Only original ink and measured endpoint tangents supply evidence. No graph
family, degree rule, reference answer, model call, or label completion is used.
"""
import itertools
import math
import cv2
import numpy as np


def native_cubic_paths(ink,graph,image_size):
    if (not graph.get('node_review',{}).get('native_full_marker_rims') or
            graph.get('directed') is not False or graph.get('weighted') is not False or
            not 4<=len(graph['vertices'])<=16):return []
    height,width=ink.shape
    proof={p['vertex']:p for p in graph['node_position_evidence']}
    positions={v['id']:np.array([v['x']*(width-1),v['y']*(height-1)]) for v in graph['vertices']}
    scale=min(width/image_size[0],height/image_size[1])
    radii={key:proof[key]['radius_pixels']*scale for key in positions}
    distance=cv2.distanceTransform(np.uint8(ink==0),cv2.DIST_L2,3)
    def read(xy):
        return cv2.remap(distance,xy[:,0].astype('float32').reshape(-1,1),xy[:,1].astype('float32').reshape(-1,1),
                         cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=100).ravel()
    def rays(point,radius):
        angles=np.arange(0,360,3)*np.pi/180;advance=np.linspace(radius+4,radius+24,20)
        xy=point+advance[:,None,None]*np.column_stack((np.cos(angles),np.sin(angles)))[None,:,:]
        support=np.mean(read(xy.reshape(-1,2)).reshape(20,-1)<=2.5,axis=0);chosen=[]
        for i in np.argsort(-support):
            if support[i]<.9:break
            angle=angles[i]
            if all(abs(math.atan2(math.sin(angle-b),math.cos(angle-b)))>math.radians(22) for b in chosen):chosen.append(angle)
            if len(chosen)==6:break
        return chosen
    angles={key:rays(point,radii[key]) for key,point in positions.items()}
    t=np.linspace(0,1,160)[:,None]
    b0=(1-t)**3;b1=3*(1-t)**2*t;b2=3*(1-t)*t*t;b3=t**3
    accepted=[]
    for a,b in itertools.combinations(positions,2):
        start,end=positions[a],positions[b];length=np.linalg.norm(end-start)
        if length<4*max(radii[a],radii[b]):continue
        def measure(parameters):
            l1,l2,theta,phi=parameters
            c1=start+length*l1*np.array([math.cos(theta),math.sin(theta)])
            c2=end+length*l2*np.array([math.cos(phi),math.sin(phi)])
            curve=b0*start+b1*c1+b2*c2+b3*end
            vectors=np.diff(curve,axis=0)
            invalid=np.min(vectors@(end-start))<=0
            second=np.diff(vectors,axis=0);first=(vectors[1:]+vectors[:-1])/2
            curvature=abs(first[:,0]*second[:,1]-first[:,1]*second[:,0])/np.maximum(np.linalg.norm(first,axis=1)**3,1e-9)
            if np.max(curvature)>1/(3*min(radii[a],radii[b])):invalid=True
            for key,point in positions.items():
                if key not in (a,b) and np.min(np.linalg.norm(curve-point,axis=1))<radii[key]+3:invalid=True
            valid=(np.linalg.norm(curve-start,axis=1)>radii[a]+3)&(np.linalg.norm(curve-end,axis=1)>radii[b]+3)
            values=read(curve[valid])
            cost=float(np.mean(np.minimum(values,12)**2)) if len(values)>30 else 1e9
            return (1e9 if invalid else cost),curve,values
        best=(1e9,None)
        for theta,phi in itertools.product(angles[a],angles[b]):
            for l1,l2 in itertools.product((.2,.4,.65,.95,1.3),repeat=2):
                parameters=[l1,l2,theta,phi];cost,_,_=measure(parameters)
                if cost<best[0]:best=(cost,parameters)
        if best[1] is None:continue
        cost,parameters=best
        for step in (.15,.08,.04,.02,.01,.005):
            for _ in range(3):
                improved=False
                for dim in range(4):
                    delta=step if dim<2 else step*.5
                    for sign in (-1,1):
                        proposal=list(parameters);proposal[dim]+=sign*delta
                        if dim<2 and not .05<=proposal[dim]<=1.5:continue
                        new,_,_=measure(proposal)
                        if new<cost:cost,parameters=new,proposal;improved=True
                if not improved:break
        cost,curve,values=measure(parameters)
        deviation=float(np.max(abs((end-start)[0]*(curve-start)[:,1]-(end-start)[1]*(curve-start)[:,0]))/length)
        if cost>2 or np.mean(values<=2.5)<.97 or deviation<15:continue
        trace={'from':a,'to':b,'path':(curve/[width-1,height-1]).tolist(),
               'pixel_length':float(np.linalg.norm(np.diff(curve,axis=0),axis=1).sum()),
               'score':.95,'method':'opencv_curved_ink_template','needs_review':True}
        from graph_qwen_geometry import validate_curve_tangents
        validated,_=validate_curve_tangents([trace],ink,strict_native_continuity=True)
        if not validated:continue
        # A short tangent can round a branch switch inside a thick crossing.
        # Both longer continuations must also lie on the actual same stroke.
        from graph_relation import _samples
        samples=np.asarray(_samples(curve.tolist(),160));vectors=samples[2:]-samples[:-2]
        vectors/=np.maximum(np.linalg.norm(vectors,axis=1),1e-9)[:,None]
        _,labels=cv2.distanceTransformWithLabels(np.uint8(ink==0),cv2.DIST_L2,5,labelType=cv2.DIST_LABEL_PIXEL)
        pixels=np.argwhere(ink>0)[:,::-1];at=np.rint(samples[1:-1]).astype('int32')
        if (at<0).any() or (at[:,0]>=width).any() or (at[:,1]>=height).any():continue
        nearest=pixels[labels[at[:,1],at[:,0]]-1]
        sides=[read(nearest+vectors*offset) for offset in (-20,20)]
        support=np.maximum(*sides)[12:-12]<=1.5
        if np.mean(support)<.9 or min(np.mean(support[i:i+10]) for i in range(len(support)-10))<.7:continue
        from graph_line_tracer import _sample_path
        trace['path']=_sample_path(curve.tolist(),width,height,max_error=.6)
        if not trace['path']:continue
        trace.update(method='opencv_native_cubic_fit',native_fit_cost=cost,
                     native_long_tangent_alignment=float(np.mean(support)),native_fit_parameters=parameters)
        accepted.append(trace)
    return accepted
