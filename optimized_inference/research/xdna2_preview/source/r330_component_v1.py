"""True untraced H-only GRU: no weight/frame/quant/affine host echoes or clocks."""
from pathlib import Path
import numpy as np
import aie.iron as iron
from aie.iron import In,Out,ObjectFifo,Program,Runtime,Worker,Kernel,TaskGroup
from aie.iron.controlflow import range_
from aie.iron.device import Tile
from aie.dialects.arith import index_cast
from aie.extras.types import i32
from aie.helpers.taplib import TensorAccessPattern
P=Path(__file__).resolve().parent
def ft(n):return np.ndarray[(n,),np.dtype[np.float32]]
def bt(n):return np.ndarray[(n,),np.dtype[np.uint8]]
def resident_compute():
 from r210_gru_flows_v1 import quant_and_relay, finish_and_feedback
 from r328_neighbor_weights_v1 import matrix_graph
 frame_tile=ObjectFifo(ft(544),name='r210_finish_frames',depth=1)
 feedback=ObjectFifo(ft(256),name='r210_first_hidden',depth=1)
 q=ObjectFifo(ft(320),name='r97_quant',depth=1)
 q_shared=q.cons().forward(tile=Tile(4,1),name='r97_quant_shared',depth=1)
 allg=ObjectFifo(ft(1920),name='r97_all_gates',depth=1)
 matrix_gates=allg.prod().join([0,960],tile=Tile(0,1),obj_types=[ft(960)]*2,names=['r97_gi','r97_gh'],depths=[1,1])
 output=ObjectFifo(ft(320),name='r97_H',depth=1)
 host_output=output.cons().forward(tile=Tile(7,1),name='r97_H_host',depth=1)
 workers=[];matrices=[];receivers=[];support=str(P/'r123_gru_crt_objects_v1/finish.o')
 def support_fn(name,args):return Kernel('r97_'+name,support,args)
 def project_support_fn(name,args):return Kernel('r97_'+name,str(P/'r123_gru_crt_objects_v1/projection.o'),args)
 def project(qh,weights,empty,full,gh,fn,init,after,restored,actor):
  qq=qh.acquire(1);gg=gh.acquire(1);init(gg,qq,actor)
  for stripe in range_(4):
   full.acquire();fn(qq,weights,gg,index_cast(i32(),stripe));empty.release()
  after(gg);restored(gg);qh.release(1);gh.release(1)
 for matrix in range(2):
  resident,inputs=matrix_graph(matrix,bt)
  matrices.append(resident)
  gp=matrix_gates[matrix].prod().join([0,320,640],tile=Tile(0 if matrix==0 else 7,1),obj_types=[ft(320)]*3,names=[f'r97_g_{matrix}_{gate}' for gate in range(3)],depths=[1]*3)
  for gate,(tile,weights,empty,full,dma) in enumerate(inputs):
   receivers.append(dma)
   fn=Kernel('r88_project_'+('ih' if matrix==0 else 'hh'),str(P/'r123_gru_crt_objects_v1/projection.o'),[ft(320),bt(17152),ft(320),np.int32])
   calls=[project_support_fn('project_init',[ft(320),ft(320),np.int32]),project_support_fn('project_after',[ft(320)]),project_support_fn('project_restored',[ft(320)])]
   workers.append(Worker(project,[q_shared.cons(),weights,empty,full,gp[gate].prod(),fn,*calls,matrix*3+gate],tile=tile,name=f'r97_project_{matrix}_{gate}'))
 quant=Kernel('r88_quantize2',str(P/'r123_gru_crt_objects_v1/quant.o'),[ft(544),ft(320)])
 relay,one,two,qctrl=quant_and_relay(q.prod(),frame_tile.prod(),feedback.cons(),quant)
 workers.append(relay)
 finish=Kernel('r97_finish_h256',str(P/'r123_gru_crt_objects_v1/finish.o'),[ft(544),ft(1920),ft(320)])
 calls=[support_fn('main_init',[ft(320),ft(544)]),support_fn('main_check_gates',[ft(544),ft(1920),ft(320)]),finish,support_fn('main_after',[ft(320)]),support_fn('main_restored',[ft(320)])]
 final,fctrl=finish_and_feedback(frame_tile.cons(),output.prod(),allg.cons(),feedback.prod(),
                                 *calls)
 workers.append(final)
 assert len(workers)==8
 return workers,one,two,host_output.cons(tile=Tile(7,0)),matrices,(qctrl,fctrl),receivers
