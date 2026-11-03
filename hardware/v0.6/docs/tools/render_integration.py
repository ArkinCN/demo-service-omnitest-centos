from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
plt.rcParams['font.sans-serif']=['Microsoft YaHei']
plt.rcParams['axes.unicode_minus']=False
out=Path(__file__).resolve().parents[1]/'assets'
def box(ax,x,y,w,h,s):
 ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.02',facecolor='#EDF4F0',edgecolor='#285C48',linewidth=1.6))
 ax.text(x+w/2,y+h/2,s,ha='center',va='center',fontsize=13,color='#173B2E')
def arrow(ax,a,b,label=''):
 ax.annotate('',xy=b,xytext=a,arrowprops=dict(arrowstyle='->',lw=1.6,color='#285C48'))
 if label:ax.text((a[0]+b[0])/2,(a[1]+b[1])/2+.13,label,ha='center',fontsize=11)
f,ax=plt.subplots(figsize=(12,5));ax.set(xlim=(0,12),ylim=(0,5));ax.axis('off')
ax.text(.3,4.65,'数据流：设备只由执行器访问，前端只向后端取数据',fontsize=17,weight='bold')
box(ax,.35,3,2.1,.75,'浏览器 / uPlot');box(ax,3.6,3,2.1,.75,'常驻后端');box(ax,7,3,2.2,.75,'PowerShell执行器');box(ax,9.8,3,1.7,.75,'UNO + 示波器')
arrow(ax,(2.45,3.65),(3.6,3.65),'开始 / 停止');arrow(ax,(5.7,3.4),(7,3.4),'启动唯一子进程');arrow(ax,(9.2,3.4),(9.8,3.4))
box(ax,7,1.5,2.2,.75,'事件 + 采集文件');arrow(ax,(8.1,3),(8.1,2.25),'写出');arrow(ax,(7,1.9),(5.7,3),'读文件')
arrow(ax,(3.6,3.12),(2.45,3.12));ax.text(2.55,2.75,'增量 JSON',fontsize=11)
box(ax,.35,1.3,2.1,.75,'整段趋势图');box(ax,3.6,1.3,2.1,.75,'短窗口波形 / 原件')
arrow(ax,(1.4,3),(1.4,2.05));arrow(ax,(4.65,3),(4.65,2.05))
ax.text(.35,.55,'趋势横轴：实验秒数     波形横轴：单窗口秒数     同一示波器只有一个 VISA owner',fontsize=12)
f.tight_layout();f.savefig(out/'08_data_flow.png',dpi=160);f.savefig(out/'08_data_flow.svg');plt.close(f)
f,axes=plt.subplots(3,1,figsize=(12,6),sharex=True)
for ax in axes:ax.set_xlim(0,40);ax.grid(alpha=.18);ax.set_yticks([])
axes[0].step([0,10,20,30,40],[30,50,70,100,100],where='post',color='#285C48',lw=2);axes[0].set_ylabel('PWM目标 %');axes[0].set_yticks([30,70,100]);axes[0].set_title('概念示意：开始即铺满0～40秒，采集点按实际时间逐步填入',fontsize=16)
axes[1].plot([.8,1.8,2.8,3.8,4.8],[4.96,4.95,4.96,4.94,4.95],marker='o',color='#285C48');axes[1].set_ylabel('采集中');axes[1].axvspan(5,40,color='#EEF1EF');axes[1].text(21,4.95,'尚未采集：保持空白',ha='center',fontsize=13)
axes[2].plot([1,5,9,11,15,19,21,25,29,31,35,39],[1,1.1,1,1.8,1.7,1.8,2.3,2.4,2.3,3,2.9,3],marker='o',color='#285C48');axes[2].set_ylabel('结束后');axes[2].set_xlabel('本次运行实际经过时间 (s)');axes[2].text(3,2.6,'示意点，非实测',fontsize=12)
f.tight_layout();f.savefig(out/'09_fixed_axis.png',dpi=160);f.savefig(out/'09_fixed_axis.svg');plt.close(f)
