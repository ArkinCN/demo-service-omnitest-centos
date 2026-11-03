## SMO 估算器和 PLL 估算器

<!-- image -->

## 估算反电动势

## PLL估算反电动势

PI输入值：估算电流-实际采样得到的电流

PI输出值：反电动势

## 2.1 PLL估算反电动势

<!-- image -->

<!-- image -->

## SMO估算反电动势

<!-- image -->

<!-- formula-not-decoded -->

<!-- formula-not-decoded -->

<!-- formula-not-decoded -->

## 滑膜控制函数为

<!-- formula-not-decoded -->

式（2.7）中的k₃决定了式（2.5）中的 是否能夠收敛到 lα 和 β ，以及以多快的速度收敛。 p R 1 (ux − =α) 根据式(2.5)可得a轴上的电压方程： ip α L α L (2.8)

¹α大，那么根据式（2.7）可得²α取值为正ks，只要k选取合适可以使 I 得式（2.8）小于0，也就是观测电流¹α的导数小于0， 会随着时间的推移逐渐减小；当k取值越大， 式（2.8）的值负的越大，观测电流减小的速度就越快。同样的，当观测电流比实际电流小，那么²α 取值为负k，，只要选取合适可以使得式（2.8）大于0，那么观测电流的导数就大于0，随着时间的

推移观测电流会逐渐变大。因此如果滑膜增益Ks选取合适，那za就能是观测电流 α收敛到实际的电流 也就是让两个电流变量达到并保持在滑膜面上。

由于控制输入²α因电流误差 差α有正负的变化，因此它的值不是连续的，也伴随正负符号的突然切换。在²α 的控制下，观测电流 x1 会趋近实际电流α，等到观测器稳定后电流会在实际电流的附近小幅波动。只要电流 误差不为0，哪怕一点点的误差， zα都会有较大的输出。

<!-- image -->

滑膜增益k，取值太大会导致观测电流剧烈抖动，导致估计误差增加。具体滑膜增益k，该如何确定？ 为了方便计算，选择s1进行分析。

x − ix = 0 ，如果 根据李亚普洛夫稳定性判据，定义李亚普洛夫函数为：

<!-- formula-not-decoded -->

<!-- formula-not-decoded -->

将式（2.6）的第一行带入计算得：

<!-- formula-not-decoded -->

t ks &gt; −R|is|+ Eβsign(is) 综合所得： 2

<!-- formula-not-decoded -->

也就是说如果ks满足了式（3.0)，那么αβ轴观测电流就会收敛到实际电流，状态(αx）和（i达到并保持在滑膜面上， 那么s1便收敛到0并保持为0；

如果选取的k过大会有什么影响?

l 根据式（2.9)当α

<!-- formula-not-decoded -->

<!-- formula-not-decoded -->

当Bx&gt;0,那式（3.0）右边的最大绝对值，处于&lt;0的情况下，此时k越大那么这个绝对值就越大，也就是电流误差的绝对值最大； 也就是说如果k。越大，则观测电流偏离实际电流的最大距离也越大，状态变量(αi)偏离滑膜面s1的最大距离就越大，稳态后再滑膜面附近抖动

的幅度就越大。

<!-- image -->

## 低通滤波

<!-- image -->

<!-- formula-not-decoded -->

为了对 Z 滤波以获得e*，用 TPWM\_VALUE 替换公式中的 T，可得到：

<!-- formula-not-decoded -->

其中,Z(n)为没有进过滤波的反电动势，为滑动模式控制器的输出，

e(n)为下一个估算反电动势

1n1L 个什管的后由执

<!-- formula-not-decoded -->

OBS FBASE用来表示转速转换为角度增量的系数，计算公式

FOC\_FBASE = OBS\_FBASE = fBASE · TPWM\_VALUE * 32767

0

#define OBS\_FBASE

BASE FREQ*TPWM VALUE*32768

// Fbase*Tpwm*32768

1

#define OBS KLPF

(UE

2

A

3

#define SPEED KLPF

#define OBS EA KS

UUE

P //M

\_Q15((2*MOTOR\_SPEED\_SMOMIN\_RPM*\_2PI*BASE\_FREQ*TPWM\_VALUE)/MOTOR\_SPEED\_BASE)

// SMO的最小速度

## 一阶低通滤波器最小滤波系数OBS\_EA\_ES的计算

<!-- formula-not-decoded -->

FOC\_EKLPFMIN = OBS\_EA\_ES

## 为了得到更加稳定的转速信号，需要对估算器的估算转速进行低通滤波，速度低通滤波系数计算：

SPEED\_KLPF = 2π * f*TPWM\_VALUE*32767

## 估算器里由速度OMEGA算出角度增量4θ的计算公式

∆θ = ω * TPWM\_VALUE↓

对40进行标幺化并用Q15格式表示↓

<!-- formula-not-decoded -->

= 2 * (fBASE * TPWM\_VALUE) *

32767)

ω

ωBASE

OBS\_FBASE用来表示转速转换为角度增量的系数，计算公式

FOC\_FBASE = OBS\_FBASE = fBASE * TPWM\_VALUE * 32767 4

0

#define OBS FBASE

BASE FREQ*TPWM\_VALUE*32768

// Fbase*Tpwm*32768

1

#define OBS KLPF

\_Q15(\_2PI*BASE\_FREQ*TPWM\_VALUE)

2

#define SPEED KLPF

\_Q15(\_2PI*SPD\_BW*TPWM\_VALUE)

BP  //

3

#define OBS EA\_KS

\_Q15((2*MOTOR\_SPEED\_SMOMIN\_RPM*\_2PI*BASE\_FREQ*TPWM\_VALUE)/MOTOR\_SPEED\_BASE)

// SMO的最小速度

A

<!-- image -->

SPD\_BW = fc

<!-- image -->

根据控制框图可得方程：

<!-- formula-not-decoded -->

系统传递函数：

<!-- formula-not-decoded -->

根据典型二阶系统传递函数表达式

<!-- formula-not-decoded -->

系统传递函数与典型二阶系统传递函数对比得：

<!-- formula-not-decoded -->

<!-- formula-not-decoded -->

<!-- formula-not-decoded -->

<!-- formula-not-decoded -->

<!-- formula-not-decoded -->

离散化后：

<!-- formula-not-decoded -->

KP标幺化后转换为Q12格式得：

<!-- formula-not-decoded -->

KI标幺化后转换为Q15格式得：

FOC \_KI = 2π f *2π f · Ts/ fbase ·32767

C

7

#define OBSW KP GAIN

#define OBSW KI GAIN

6

## 4.2 sincos

\_Q12(2*\_2PI*ATT\_COEF*ATO\_BW/BASE\_FREQ)

4

\_Q15(\_2PI*ATO\_BW*ATO\_BW*TPWM\_VALUE/BASE\_FREQ)

<!-- image -->

<!-- formula-not-decoded -->

PLL系统的等效框图：

<!-- image -->

由此可以得到方程

<!-- formula-not-decoded -->

进一步可得到系统的传递函数

<!-- formula-not-decoded -->

根据典型二阶系统传递函数表达式

<!-- formula-not-decoded -->

系统传递函数与典型二阶系统传递函数对比得：

<!-- formula-not-decoded -->

<!-- formula-not-decoded -->

求解得：

<!-- image -->

其中ξ为阻尼比， ωn 为自然角频率，它可以被看作系统的带宽。实际上系统的带宽是描述伯德图上增益衰减到-3dB所对应的频 率。

自然角频率和这个频率很接近。

根据式（4.1）我们发现系统的带宽是变化的，因为k中包含了电角速度。为了跟踪电角度的变化，一般要求系统的带宽足够大。假 如电机的

电角度以50Hz的频率在变化，那么我们只需要将带宽设定比50HZ大就好了。但是由于k是变化的，因此在计算kp和ki的时候，我们 必须选取k

的最小值来进行计算。当k变大后，带宽会变大，依然满足要求。