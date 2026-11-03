from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei']
plt.rcParams['axes.unicode_minus']=False
P=Path(__file__).resolve().parent
INK='#163b33'; MUTED='#53615d'; GREEN='#24755c'; GOLD='#9c7422'; BLUE='#3476a0'; RED='#a14640'
def text(a,x,y,s,size=12,color=INK,ha='center',weight='normal'):
 a.text(x,y,s,fontsize=size,color=color,ha=ha,va='center',fontweight=weight)
def box(a,x,y,w,h,s,c=GREEN,size=12):
 a.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.004,rounding_size=0.01',lw=1.4,edgecolor=c,facecolor='#f6f9f7'))
 text(a,x+w/2,y+h/2,s,size,c)
def arrow(a,x1,y1,x2,y2,c=GREEN):
 a.add_patch(FancyArrowPatch((x1,y1),(x2,y2),arrowstyle='-|>',mutation_scale=17,lw=1.8,color=c))
def canvas(title,sub,h=7):
 f,a=plt.subplots(figsize=(12,h));a.set_xlim(0,1);a.set_ylim(0,1);a.axis('off')
 text(a,.03,.96,title,20,ha='left',weight='bold');text(a,.03,.9,sub,11,MUTED,ha='left');return f,a
def save(f,n):
 f.savefig(P/(n+'.png'),dpi=100,bbox_inches='tight',facecolor='white');f.savefig(P/(n+'.svg'),bbox_inches='tight',facecolor='white');plt.close(f)
f,a=canvas('B3 · 实物接线 → 示波器通道 → 系统数据','每条箭头表示信号进入下一环节；CH4型号已确认；输出电压与每转脉冲数仍待现场核对。',8)
for x,s in [(.15,'信号来源'),(.43,'接法'),(.68,'通道'),(.88,'得到的量')]:text(a,x,.82,s,12,MUTED)
rows=[(.68,'红色单根供电线','CPL8100A 钳口\nBNC OUT → CH1','CH1 · 1X\nDC / 1MΩ','实测输出 V\n确认后折算 A',GOLD),(.53,'红线 +5V\n黑线 GND','探头尖 → 红线\n地夹 → 黑线','CH2 · 倍率匹配\nDC','实测供电 V\n倍率待核对',BLUE),(.38,'蓝线 PWM\n黑线 GND','探头尖 → 蓝线\n地夹 → 黑线','CH3 · 倍率匹配\nDC','实测 PWM\n频率 / 占空比',GREEN),(.23,'LZ-MK10 · NPN\n棕供电 / 蓝0V / 黑OUT','黑OUT → 探头尖\n地夹 → 蓝0V（确认后）','CH4 · 暂OFF\n输出高态待测','未测 RPM\nPPR 待确认',RED)]
for y,s1,s2,s3,s4,c in rows:
 for x,w,s in [(.03,.23,s1),(.31,.24,s2),(.60,.16,s3),(.81,.17,s4)]:box(a,x,y,w,.105,s,c,11.5)
 for x1,x2 in [(.26,.31),(.55,.60),(.76,.81)]:arrow(a,x1,y+.0525,x2,y+.0525,c)
text(a,.03,.135,'控制线：UNO D9 → 蓝线；UNO 5V → 红线；UNO GND → 黑线。黄色FG单独绝缘。',11,ha='left')
text(a,.03,.09,'CH2 / CH3地夹均接黑色GND；CPL的DC12V口只给探头供电，风扇仍为5V。',11,ha='left')
text(a,.03,.045,'电流条件：L档0.1V/A、无流归零、只夹一根线；I = CH1输出V × 10 ÷ 同向穿孔次数。',11,ha='left')
save(f,'01_wiring')
f,a=canvas('一次周期 · 四档驻留与短窗口采集','30 → 50 → 70 → 100各目标10秒；无限循环直到停止，短窗口不等于连续40秒记录。',5.4)
xs=[.10,.31,.52,.73,.94]
for i,d in enumerate([30,50,70,100]):
 y=.62;box(a,xs[i],y,.195,.14,f'{d}%\n目标驻留10秒',GREEN,13)
 text(a,xs[i]+.0975,.46,'ACK后约2秒\n冻结 / 导出 / 恢复RUN',11)
 arrow(a,xs[i]+.0975,.60,xs[i]+.0975,.51)
 if i<3:arrow(a,xs[i]+.195,.69,xs[i+1],.69)
for x,t in zip(xs,['0','10','20','30','40秒目标']):text(a,x,.83,t,11,MUTED)
arrow(a,.83,.30,.16,.30);text(a,.50,.24,'下一周期从30%重新开始；命令与采集开销会影响实际切档时刻。',11,MUTED)
text(a,.03,.08,'每档数据：CH1 / CH2 / CH3 NORM显示波形 + 屏幕BMP + 元数据；转速另用较慢时基短采。',11,ha='left')
save(f,'02_timing')
f,a=canvas('系统开始 → 运行进程 → 数据接入 → 停止确认','前端通过自己的后端启动本机脚本；运行状态由事件与summary读取。',7)
box(a,.03,.67,.19,.13,'系统“开始”\n应用后端',GREEN);box(a,.30,.67,.20,.13,'start.ps1\n返回 runId / 路径',GREEN);box(a,.59,.67,.20,.13,'后台实验进程\n独占串口 / VISA',GREEN)
arrow(a,.22,.735,.30,.735);arrow(a,.50,.735,.59,.735)
box(a,.59,.42,.20,.13,'数据文件\nCSV / BMP / JSON',BLUE);arrow(a,.69,.67,.69,.55,BLUE)
box(a,.30,.42,.20,.13,'capture_completed\n事件 / 文件路径',BLUE);arrow(a,.59,.485,.50,.485,BLUE)
box(a,.03,.42,.19,.13,'应用后端读取\n校验并展示数据',BLUE);arrow(a,.30,.485,.22,.485,BLUE)
box(a,.03,.16,.19,.13,'系统“停止”\nstop.ps1 -RunId',RED);box(a,.30,.16,.20,.13,'stop.request\n运行进程读请求',RED);box(a,.59,.16,.20,.13,'SET 0 / ACK\n最终summary',RED)
arrow(a,.22,.225,.30,.225,RED);arrow(a,.50,.225,.59,.225,RED)
text(a,.87,.81,'状态事件\nJSONL',11);arrow(a,.79,.735,.93,.735)
text(a,.84,.485,'波形采集\n完成才发布',11)
text(a,.85,.225,'stopped /\ncompleted /\nfailed',11)
text(a,.03,.06,'软件停机ACK表示控制器接受0%；叶片停转仍需现场观察，未接测速时没有实测RPM。',11,ha='left')
save(f,'03_integration')

f,a=canvas('LZ-MK10 · 供电与信号分别接线','铭牌已确认NPN；内部上拉、黑线高态与每转脉冲数仍需现场核验。',7.2)
box(a,.03,.67,.21,.13,'独立12–24V电源\n按铭牌供电',RED,12)
box(a,.35,.67,.26,.13,'棕 BN → +12–24V\n蓝 BU → 电源0V',RED,12)
arrow(a,.24,.735,.35,.735,RED)
box(a,.03,.39,.21,.13,'LZ-MK10\n黑 BK = OUT',GREEN,12)
box(a,.35,.39,.26,.13,'CH4探头尖 → 黑\nCH4地夹 → 蓝0V',GREEN,12)
box(a,.73,.39,.24,.13,'实测输出脉冲\n确认PPR后换算RPM',GREEN,11)
arrow(a,.24,.455,.35,.455);arrow(a,.61,.455,.73,.455)
text(a,.35,.29,'先单独测黑对蓝：最高电压、低态、光学触发。',11,ha='left')
box(a,.03,.105,.25,.12,'若需UNO提供5V上拉\n先确认开集电极兼容',BLUE,11)
box(a,.37,.105,.30,.12,'黑OUT → D2 INPUT_PULLUP\n蓝0V → UNO / 风扇公共GND',BLUE,10.8)
box(a,.76,.105,.21,.12,'须安全检查通过\n并另刷可选固件',BLUE,10.8)
arrow(a,.28,.165,.37,.165,BLUE);arrow(a,.67,.165,.76,.165,BLUE)
text(a,.03,.04,'传感器棕接12–24V；风扇红接5V；蓝0V与风扇黑GND共地。现v0.2未配置D2上拉。',11,ha='left')
save(f,'07_sensor_wiring')


