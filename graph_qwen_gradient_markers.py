"""Native pixel candidates for shaded circular markers in lecture diagrams.

These are position observations. They never supply labels or inferred edges.
"""
import cv2
import numpy as np
import math

def gradient_markers(image,*,include_uniform=False,highlight=False):
 """Observe similarly sized shaded disks; thin strokes and small arrows abstain."""
 rgb=np.asarray(image);gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY);h,w=gray.shape
 opening=9 if highlight else 13
 opened=cv2.morphologyEx(np.uint8(gray<230)*255,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(opening,opening)))
 count,labels,stats,centers=cv2.connectedComponentsWithStats(opened,8)
 points=[];gradient=[]
 for i in range(1,count):
  x,y,bw,bh,area=map(int,stats[i]);cx=x+(bw-1)/2;cy=y+(bh-1)/2
  if not(12<=bw<=65 and 12<=bh<=65 and .8<=bw/bh<=1.4 and .6<=area/(bw*bh)<=.9):continue
  local=np.uint8(labels[y:y+bh,x:x+bw]==i);contours,_=cv2.findContours(local,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE);c=max(contours,key=cv2.contourArea);hull=cv2.convexHull(c);p=cv2.arcLength(c,True);ca=cv2.contourArea(c);ha=cv2.contourArea(hull)
  if 4*math.pi*ca/max(p*p,1)<.7 or ca/max(ha,1)<.9:continue
  yy,xx=np.ogrid[y:y+bh,x:x+bw];core=((xx-cx)/(bw*.3))**2+((yy-cy)/(bh*.3))**2<=1
  values=gray[y:y+bh,x:x+bw][core]
  if np.mean(np.ptp(rgb[y:y+bh,x:x+bw][core].astype(float),axis=1))>20:continue
  shaded=40<=np.median(values)<=(235 if highlight else 210) and np.std(values)>=(16 if highlight else 18) and np.percentile(values,75)-np.percentile(values,25)>=25
  if not shaded and not np.median(values)<80:continue
  if shaded:gradient.append((bw+bh)/4)
  points.append({'x':cx/(w-1),'y':cy/(h-1),'radius_pixels':(bw+bh)/4,'median':float(np.median(values)),'std':float(np.std(values))})
 if len(gradient)<4:
  if not include_uniform or len(points)<4:return []
  common=float(np.median([p['radius_pixels'] for p in points]))
 else:common=float(np.median(gradient))
 selected=[p for p in points if .8*common<=p['radius_pixels']<=1.5*common]
 if len(gradient)<4 and len(selected)<max(4,len(points)*.85):return []
 from graph_line_tracer import _foreground
 # The lighter highlight on a filled marker is still visible original ink.
 # Keep it when grouping the already measured shaded circles with their lines.
 ink=_foreground(rgb) | (np.uint8(gray<230)*255)
 _,components,component_stats,_=cv2.connectedComponentsWithStats(ink,8)
 for point in selected:
  xx,yy=round(point['x']*(w-1)),round(point['y']*(h-1));pad=max(3,round(point['radius_pixels']*.4))
  values=components[max(0,yy-pad):yy+pad+1,max(0,xx-pad):xx+pad+1].ravel()
  nonzero=values[values>0]
  if nonzero.size:
   component=int(np.bincount(nonzero).argmax());_,_,cw,ch,_=component_stats[component]
   if cw>=80 and ch>=50:point['component']=component
 return selected
