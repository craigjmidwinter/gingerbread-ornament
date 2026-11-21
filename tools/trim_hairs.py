"""
Remove thin hairs (grass blades, bush stubs) sticking out of a drawing's silhouette:
  python3 tools/trim_hairs.py <in.png> <out.png> <radius_px>
Fills the silhouette, opens it by radius_px (thin bits vanish, claws/ears stay) and keeps
only ink inside that.
"""
import os, sys, numpy as np
from PIL import Image
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'gingerbread_ornament'))
import core
a=np.asarray(Image.open(sys.argv[1]).convert('L')).astype(float)/255
ink=a<0.5
bg,_=core.label_components(~ink)
border=set(np.unique(np.concatenate([bg[0],bg[-1],bg[:,0],bg[:,-1]])).tolist())
fill=~np.isin(bg,list(border))|ink
r=int(sys.argv[3])
opened=core.dilate(~core.dilate(~fill,r),r)
keep=core.dilate(opened,2)
out=np.where(keep,a,1.0)
print('removed px', int((ink&~keep).sum()))
Image.fromarray((out*255).round().astype(np.uint8)).save(sys.argv[2])
