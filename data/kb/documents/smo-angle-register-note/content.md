**SMO角度估算的原理介绍和部分寄存器说明**

峰岹科技(深圳)股份有限公司

## 目  录

**目  录	2**

**1 概述	3**

**2 数字化电机模型	5**

**3 电流观测器	9**

**4 反电动势估算	16**

**5 反电动势滤波和转速滤波	22**

**6 角度估算	17**

**7 修改记录	18**

## 1 概述

<!-- image -->

<!-- image -->

PMSM的无传感器FOC算法中最为重要的一部分就是如何计算FOC需要的换相角度。本应用笔记将说明使用SMO和PLL两种估算方式来估算换相角度（）和电机转速（）的过程，并详细说明FU68XX系列中跟估算器相关的寄存器表示的含义并推导出计算公式。

## 2 数字化电机模型

<!-- image -->

下面将建立PMSM在两相静止坐标系上的数学模型，并将其离散化，该数学模型适合于凸极性电机和非凸极性电机。

<!-- image -->

公式1为PMSM在两相旋转坐标系上的数学模型。

<!-- image -->

<!-- image -->

公式1：PMSM在坐标系上的数学模型

<!-- image -->

<!-- image -->

将公式1进行变换得到PMSM在两相静止坐标系上的数学模型，如公式2所示。

<!-- image -->

<!-- image -->

公式2：PMSM在坐标系上的数学模型

<!-- image -->

<!-- image -->

<!-- image -->

<!-- image -->

<!-- image -->

<!-- image -->

<!-- image -->

为了表示方便，将公式2中轴反电动势用表示，轴反电动势用表示，因此两相静止坐标系上的数学模型可改写为公式3。

<!-- image -->

<!-- image -->

公式3：PMSM在坐标系上的数学模型

将公式3进行移位处理得公式4。

<!-- image -->

<!-- image -->

公式4：PMSM在坐标系上的数学模型

<!-- image -->

将公式4中轴上的数学模型进行离散化处理得公式5。

$$\frac{I_{ \alpha }(n+1)-I_{ \alpha }(n)}{T_{s}}=(-\frac{R}{L_{d}})I_{ \alpha }(n)+\frac{(V_{ \alpha }(n)-e_{ \alpha }(n))}{L_{d}}-\frac{ \omega_{e}(L_{d}-L_{q})I_{ \beta }(n)}{L_{d}}$$

$$I_{ \alpha }(n+1)=(1-T_{s}\frac{R}{L_{d}})I_{ \alpha }(n)+\frac{T_{s}}{L_{d}}(V_{ \alpha }(n)-e_{ \alpha }(n))-\frac{ \omega_{e}T_{s}(L_{d}-L_{q})I_{ \beta }(n)}{L_{d}}$$

<!-- image -->

公式5：PMSM在轴上的离散化数学模型

<!-- image -->

将公式4中轴上的数学模型进行离散化处理得公式6。

$$\frac{I_{ \beta }(n+1)-I_{ \beta }(n)}{T_{s}}=(-\frac{R}{L_{d}})I_{ \beta }(n)+\frac{(V_{ \beta }(n)-e_{ \beta }(n))}{L_{d}}+\frac{ \omega_{e}(L_{d}-L_{q})I_{ \alpha }(n)}{L_{d}}$$

$$I_{ \beta }(n+1)=(1-T_{s}\frac{R}{L_{d}})I_{ \beta }(n)+\frac{T_{s}}{L_{d}}(V_{ \beta }(n)-e_{ \beta }(n))+\frac{ \omega_{e}T_{s}(L_{d}-L_{q})I_{ \alpha }(n)}{L_{d}}$$

<!-- image -->

公式6：PMSM在轴上的离散化数学模型

<!-- image -->

令，并对公式5和公式6进行标幺化处理得公式7和公式8。

$$\frac{I_{ \alpha }(n+1)}{I_{BASE}} * 32767=F * \frac{I_{ \alpha }\left(n\right)}{I_{BASE}} * 32767+G * \frac{V_{BASE}}{I_{BASE}} * \frac{V_{ \alpha }(n)}{V_{BASE}} * 32767-$$

$$G * \frac{E_{BASE}}{I_{BASE}} * \frac{e_{ \alpha }\left(n\right)}{E_{BASE}} * 32767-\frac{ \omega_{BASE}T_{s}\left(L_{d}-L_{q}\right)}{L_{d}} * \frac{ \omega e}{ \omega_{BASE}} * \frac{I_{ \beta }\left(n\right)}{I_{BASE}} * 32767$$

<!-- image -->

公式7：PMSM在轴上标幺化的离散化数学模型

$$\frac{I_{ \beta }(n+1)}{I_{BASE}} * 32767=F * \frac{I_{ \beta }\left(n\right)}{I_{BASE}} * 32767+G * \frac{V_{BASE}}{I_{BASE}} * \frac{V_{ \beta }(n)}{V_{BASE}} * 32767-$$

$$G * \frac{E_{BASE}}{I_{BASE}} * \frac{e_{ \beta }\left(n\right)}{E_{BASE}} * 32767+\frac{ \omega_{BASE}T_{s}\left(L_{d}-L_{q}\right)}{L_{d}} * \frac{ \omega e}{ \omega_{BASE}} * \frac{I_{ \alpha }(n)}{I_{BASE}} * 32767$$

<!-- image -->

公式8：PMSM在轴上标幺化的离散化数学模型

公式7和公式8中：

<!-- image -->

<!-- image -->

- 1、 ：坐标系上的电流，对应寄存器FOC\_\_IA、FOC\_\_IBET，单位为A；
<!-- image -->

<!-- image -->
- 2、 ：坐标系上的电压，对应寄存器FOC\_\_VALP、FOC\_\_VBET与母线相乘得到，单位为V；
<!-- image -->

<!-- image -->
- 3、 ：坐标系上的反电动势，对应寄存器FOC\_\_EALP、FOC\_\_EBET，单位为V；
<!-- image -->

<!-- image -->
- 4、 ：电机相绕组电阻，单位为；
<!-- image -->

<!-- image -->

<!-- image -->
- 5、 ：分别为轴电感和轴电感，单位为H；
<!-- image -->
- 6、 ：载波周期，单位为s；对应头文件Parameter.h里的宏定义TPWM\_VALUE；
- 7、 ：电流基准，单位为A；对应头文件Parameter.h里的宏定义HW\_BOARD\_CURR\_BASE，其值为最大采样电流的两倍，最大采样电流HW\_BOARD\_CURR\_MAX在头文件Parameter.h里的宏定义为HW\_ADC\_REF/2/HW\_AMPGAIN/HW\_RSHUNT，其中HW\_ADC\_REF在头文件Customer.h里宏定义为ADC的参考电压，除2是因为在电流为0时运放的输出电压为ADC参考电压的一半，HW\_AMPGAIN在头文件Customer.h里宏定义为运放的放大倍数，HW\_RSHUNT在头文件Customer.h里宏定义为采样电阻；
<!-- image -->

<!-- image -->

<!-- image -->

<!-- image -->
- 8、 ：电压基准，单位为V；对应头文件Parameter.h里的宏定义HW\_BOARD\_VOLT\_BASE，其值为，HW\_BOARD\_VOLT\_MAX为ADC可测得的最大母线电压，在头文件Customer.h里宏定义为HW\_ADC\_REF*RV，除于是因为逆变器最大输出电压为母线电压除于，RV在头文件Customer.h里宏定义为（RV1+RV2+RV3）/RV3，其中RV1、RV2、RV3在头文件Customer.h里宏定义为三个母线分压电阻，其中RV3为接地端的电阻；
<!-- image -->
- 9、 ：反电动势基准，单位为V；对应头文件Parameter.h里的宏定义MAX\_BEMF\_VOLTAGE，其值为(MOTOR\_SPEED\_BASE*KE)/1000，基准转速MOTOR\_SPEED\_BASE在头文件Customer.h里宏定义为电机最大转速的两倍，KE在头文件Customer.h里宏定义为电机的反电动势常数，除于1000是因为KE的值为1000RPM对应的反电动势电压值；
<!-- image -->
- 10、 ：角速度基准，单位为rad/s；对应头文件Parameter.h里的宏定义MAX\_OMEG\_RAD\_SEC，其值为2PI*BASE\_FREQ，基准频率BASE\_FREQ在头文件Customer.h里宏定义为MOTOR\_SPEED\_BASE/60*Pole\_Pairs，基准转速MOTOR\_SPEED\_BASE在头文件Customer.h里宏定义为电机最大转速的两倍，Pole\_Pairs在头文件Customer.h里宏定义为电机的极对数；

<!-- image -->

程序中宏定义常量OBS\_K1T、OBS\_K2T、OBS\_K3T、OBS\_K4T用于在FOC初始化时分别给寄存器FOC\_EK1、FOC\_EK2、FOC\_EK3、FOC\_EK4进行初始化，宏定义常量OBS\_K1T、OBS\_K2T、OBS\_K3T、OBS\_K4T值的计算公式分别为公式9、公式10、公式11、公式12，这四个宏定义常量的值要在-32768~32767的范围之内，如果超出该范围，估算器将出现异常，可以通过修改电机参数、采样电阻、运放放大倍数、母线分压电阻、转速基准、载波频率等相关参数来确保不溢出。

$$OBS \_ K1T=F * 32767=\frac{\left(L_{d}-T_{s}R\right)\left(L_{d}+T_{s}R\right)}{L_{d}\left(L_{d}+T_{s}R\right)} * 32767 \approx \frac{Ld}{L_{d}+T_{s}R} * 32767$$

公式9：宏定义常量OBS\_K1T的计算公式

$$OBS \_ K2T=G * \frac{V_{BASE}}{I_{BASE}} * 8192=\frac{T_{s}\left(L_{d}+T_{s}R\right)}{L_{d}\left(L_{d}+T_{s}R\right)} * \frac{V_{BASE}}{I_{BASE}} * 8192 \approx \frac{T_{s}}{L_{d}+T_{s}R} * \frac{V_{BASE}}{I_{BASE}} * 8192$$

公式10：宏定义常量OBS\_K2T的计算公式

$$OBS \_ K3T=G * \frac{E_{BASE}}{I_{BASE}} * 32767=\frac{T_{s}(L_{d}+T_{s}R)}{L_{d}(L_{d}+T_{s}R)} * \frac{E_{BASE}}{I_{BASE}} * 32767 \approx \frac{T_{s}}{L_{d}+T_{s}R} * \frac{E_{BASE}}{I_{BASE}} * 32767$$

公式11：宏定义常量OBS\_K3T的计算公式

$$OBS \_ K4T=\frac{ \omega_{BASE}T_{s}(L_{d}-L_{q})}{L_{d}} * 32767=\frac{ \omega_{BASE}Ts(L_{d}-L_{q})(L_{d}+T_{s}R)}{Ld(L_{d}+TsR)} * 32767 \approx \frac{ \omega_{BASE}Ts(L_{d}-L_{q})}{L_{d}+T_{s}R} * 32767$$

公式12：宏定义常量OBS\_K4T的计算公式

## 3 电流观测器

<!-- image -->

<!-- image -->

<!-- image -->

<!-- image -->

<!-- image -->

位置和速度估算器是基于电流观测器而构建的。该观测器是电机的一个数字化模型，该数字化模型是在坐标系上实现的，该模型一个载波周期需要被执行两次，轴和轴分开执行，所需的变量和常量也分轴上的和轴上的，包括：

<!-- image -->

<!-- image -->

<!-- image -->

<!-- image -->

<!-- image -->

1、电机轴和轴上的电流，这两个电流是通过采三相静止坐标系上的电流通过等幅变换得到。

<!-- image -->

<!-- image -->

<!-- image -->

2、电机轴和轴上的电压，这两个电压值是根据母线电压和MOS的占空比计算得到的，其计算方法将在后面做出说明。

<!-- image -->

<!-- image -->

<!-- image -->

3、电机轴和轴上的反电动势。

<!-- image -->

4、电机绕组相电阻。

<!-- image -->

<!-- image -->

<!-- image -->

5、电机轴和轴上的电感。

<!-- image -->

6、控制周期。

<!-- image -->

<!-- image -->

<!-- image -->

7、输出轴和轴上的校正因子电压。

<!-- image -->

8、最大电流误差值，该参数在硬件中是固定的参数。

<!-- image -->

<!-- image -->

9、滑膜增益值，参数的大小是可以通过寄存器FOC\_KSLIDE进行修改的，程序使用宏定义OBS\_KSLIDE对寄存器FOC\_KSLIDE进行初始化，OBS\_KSLIDE的典型值为0.85，用Q15格式表示为\_Q15(0.85)。

该数字化模型对硬件使用了软件表示方式。然而，为了使测量电流和估算电流相匹配，数字化电机模型需要使用闭环来进行校正，如图1所示。

考虑用两种方式表示电机，一种是硬件方式（阴影区），一种是软件方式，两个系统中使用相同的输入电压（V s ）,使用模型中的估算电流（i s *）来匹配测量电流（i s ）,我们假设数字化模型的反电动势（e s * ）与电机的反电动势（e s ）相同。

<!-- image -->

图1 电流观测器框图

滑动模式控制器（SMC）在电流误差值小于MaxSMCError时，滑动模式控制器的输出工作在图2中PMSM框下的公式所给定的线性范围内。对于线性范围外的误差值，滑动模式控制器的输出为（+K slide ）或（-K slide ），取决于误差的符号。

滑动模式控制器或称SMC用来对数字化电机模型进行补偿。SMC包含一个求和结点，用于计算电机上的测量电流与数字化电机模型上的估算电流之差的符号。计算出的差值符号（+1或-1）乘以SMC增益（K slide ）。SMC控制器的输出就是校正因子（Z）。该增益被加到数字化模型的电压项，在每个控制周期中都重复执行该过程直到测量电流（i s ）和估算电流（i s *）的差值为零（即，直到测量电流与估算电流相同为止）。

## 4 反电动势估算

<!-- image -->

<!-- image -->

对数字化模型进行补偿后，电机模型的输入电压（V s ）和电流（i s *）与数字化模型中的值相同。一旦对数字化模型补偿完后，下一步就要通过对校正因子（Z）滤波来估算反电动势（e s *）,如图2所示。随后反电动势的估算值（e s *）反馈给数字化电机模型，以在每个控制周期之后对变量e s *进行更新。的值用于估算。

<!-- image -->

图2 反电动势估算模型

## 5 反电动势滤波和转速滤波

公式13给出的一阶数字低通滤波器提供滤波功能。

$$y\left(n\right)=y\left(n-1\right)+T2 \pi fc * \left(x\left(n\right)-y\left(n\right)\right)$$

<!-- image -->

为了对Z滤波以获得，用TPWM\_VALUE替换公式中的T，可得到：

$$e\left(n\right)=e\left(n-1\right)+TPWM \_ VALUE * 2 \pi fc * \left(z\left(n\right)-e\left(n\right)\right)$$

其中：

<!-- image -->

为不可滤波的反电动势，为滑动模式控制器的输出

<!-- image -->

为下一个估算的反电动势

<!-- image -->

为上一个估算的反电动势

<!-- image -->

为载波周期

<!-- image -->

为滤波器的截止频率

公式13、一阶低通滤波器的数学模型

<!-- image -->

<!-- image -->

截止频率的值被设置为等于驱动电流和电机电压的频率，该频率等于每秒的电气旋转圈数。用于值适应低通滤波器的实现方式会有一个固定的相位延迟，用于所有转速范围内的补偿，因为截止频率会随着电机提速而改变，这里的自适应截止频率固定为驱动电流频率的两倍，因此其固定延迟角度为26度33分56秒，式14为一阶低通滤波器截止频率计算公式，式15为一阶低通滤波器滤波系数计算公式。在程序中，自适应低通滤波器滤波系数的系数的Q15格式在头文件Parameter.h用宏定义OBS\_KLPF表示，自适应低通滤波器滤波系数等于OBS\_KLPF乘以两倍估算转速，式16为OBS\_KLPF的表达式。

自适应低通滤波器的滤波系数需要设置一个最小滤波系数，该最小滤波系数通过修改头文件Customer.h里的宏定义MOTOR\_SPEED\_SMOMIN\_RPM进行调整，MOTOR\_SPEED\_SMOMIN\_RPM表示SMO的最小运行转速，其值应设置小于电机要求的最小转速，自适应低通滤波器的最小滤波系数在头文件Parameter.h里用宏定义OBS\_EA\_ES表示，对应寄存器FOC\_EKLPFMIN，其与MOTOR\_SPEED\_SMOMIN\_RPM的关系如公式17所示。

$$fc=\frac{p * 2 * n}{60}=\frac{p}{60} * MOTOR \_ SPEED \_ BASE * \frac{2 * n}{MOTOR \_ SPEED \_ BASE}$$

$$=BASE \_ FREQ * \frac{2 * n}{MOTOR \_ SPEED \_ BASE}$$

公式14、反电动势自适应一阶低通滤波器截止频率计算公式

$$2 \pi  * fc * TPWM \_ VALUE=2 \pi  * BASE \_ FREQ * TPWM \_ VALUE * \frac{2 * n}{MOTOR \_ SPEED \_ BASE}$$

公式15、反电动势自适应一阶低通滤波器滤波系数计算公式

$$OBS \_ KLPF=2 \pi  * BASE \_ FREQ * TPWM \_ VALUE * 32767$$

公式16、反电动势自适应一阶低通滤波器滤波系数的系数OBS\_KLPF的计算公式

$$OBS \_ EA \_ ES=2 \pi  * BASE \_ FREQ * TPWM \_ VALUE * \frac{2 * MOTOR \_ SPEED \_ SMOMIN \_ RPM}{MOTOR \_ SPEED \_ BASE} * 32767$$

公式17、反电动势自适应一阶低通滤波器最小滤波系数OBS\_EA\_ES的计算公式

为了得到更加稳定的转速信号，需要对估算器的估算转速进行低通滤波，其滤波系数在头文件Parameter.h里用宏定义SPEED\_KLPF表示，对应寄存器FOC\_OMEKLPF；该滤波系数通过修改头文件Customer.h里的宏定义SPD\_BW进行调整，调整宏定义SPD\_BW就是在调整低通滤波器的截止频率；式18为系数SPEED\_KLPF和系数SPD\_BW的关系式。

$$SPEED \_ KLPF=2 \pi  * SPD \_ BW * TPWM \_ VALUE * 32767$$

公式18、系数SPEED\_KLPF和系数SPD\_BW的关系式

## 6 角度估算

<!-- image -->

图3 基于PLL的SMO实现框图

<!-- image -->

假设，当 $\left|\overset{ \wedge}{ \theta }_{e}- \theta_{e}\right| < \frac{ \pi }{6}$ 时，认为 $\sin(\left( \theta_{e}-\overset{ \wedge}{ \theta }_{e}\right))= \theta_{e}-\overset{ \wedge}{ \theta }_{e}$ 成立。

线性化推导

<!-- image -->

<!-- image -->

函数在附近泰勒展开为：

<!-- image -->

<!-- image -->

<!-- image -->

若，在0附近的泰勒展开为：

<!-- image -->

根据图3可以得到的关系式如公式19所示。

$$\bigtriangleup e=-\overset{ \wedge}{e}_{ \alpha }\cos(\overset{ \wedge}{ \theta }_{e})-\overset{ \wedge}{e}_{ \beta }\sin(\overset{ \wedge}{ \theta }_{e})=$$

$$k\sin( \theta_{e})\cos(\overset{ \wedge}{ \theta }_{e})-k\cos( \theta_{e})\sin(\overset{ \wedge}{ \theta }_{e})=$$

$$k\sin(\left( \theta_{e}-\overset{ \wedge}{ \theta }_{e}\right)) \approx k\left( \theta_{e}-\overset{ \wedge}{ \theta }_{e}\right)$$

公式19

<!-- image -->

<!-- image -->

<!-- image -->

<!-- image -->

此时，图3的等效框图如图4所示，图中的通过寄存器FOC\_EKP、FOC\_EKI进行修改，在电机转速比较低时，寄存器FOC\_EKP、FOC\_EKI的值可以给小些；在电机转速比较高时，寄存器FOC\_EKP、FOC\_EKI的值可以给大些，在头文件Parameter.h里定义了几组常量用于给寄存器FOC\_EKP、FOC\_EKI赋值，这几组常量的大小受头文件Customer.h里的一组ATO影响，ATO值越大，这几组常量的值就越大，寄存器FOC\_EKP、FOC\_EKI得到的值越大，角度响应就越快。

<!-- image -->

图4 基于PLL系统的SMO的等效框图

PI调节器参数确定：

<!-- image -->

图5

<!-- image -->

公式20

$$k\left( \theta e-\hat{ \theta }e\right)\left(Kp+\frac{Ki}{s}\right)\frac{K}{s}=\hat{ \theta }e$$

公式21

<!-- image -->

公式22

$$\frac{\hat{ \theta }_{e}}{ \theta_{e}}=\frac{kK_{p}Ks+kK_{i}K}{s^{2}+kK_{p}Ks+kK_{i}K}$$

公式23

典型二阶系统传递函数：

<!-- image -->

<!-- image -->

公式24

<!-- image -->

公式25

<!-- image -->

公式26

<!-- image -->

公式27

$$Ki=\frac{ \omega^{2}n}{Kk}$$

公式28

<!-- image -->

<!-- image -->

<!-- image -->

<!-- image -->

<!-- image -->

<!-- image -->

<!-- image -->

<!-- image -->

为了跟踪电角度，需要的变化速度，电角度的变化率就是电角速度。如果电机的电角度频率50HZ，也就是说电机的电角度以50HZ的频率发生变化，那么只要将带宽设定的大于 50HZ 就好。但在式（24）和（26）中就算确定了阻尼和带宽我们还有一个在变化，需要的控制器比例积分增益是固定。如果在式（24）里按  最大值计算（计算好就不变了），那么当减小后可能式（26）带宽就比50HZ小了。所以我们按照最小值来计算，变大时带宽会变得比50HZ更大，依然满足条件。在带宽频率处系统响应为-3dB的频率，-3dB是0.707，意思就是系统的响应幅度被削弱到了原来的0.707倍，认为这种情况下系统响应被衰减了。

## 7 修改记录

| 版本号   | 修改详细内容说明   | 生效日期       | 修订者   |
|-------|------------|------------|-------|
| V1.0  | 初版         | 2024年4月30日 | 许伟林   |
|       |            |            |       |
|       |            |            |       |
|       |            |            |       |
|       |            |            |       |
|       |            |            |       |
|       |            |            |       |
|       |            |            |       |
|       |            |            |       |
|       |            |            |       |
|       |            |            |       |
|       |            |            |       |
|       |            |            |       |
|       |            |            |       |
|       |            |            |       |
|       |            |            |       |

**版权说明**

版权所有©峰岹科技（深圳）股份有限公司（以下简称：峰岹科技）。

为改进设计和/或性能，峰岹科技保留对本文档所描述或包含的产品（包括电路、标准元件和/或软件）进行更改的权利。本文档中包含的信息供峰岹科技的客户进行一般性使用。峰岹科技的客户应确保采取适当行动，以使其对峰岹科技产品的使用不侵犯任何专利。峰岹科技尊重第三方的有效专利权，不侵犯或协助他人侵犯该等权利。

本文档版权归峰岹科技所有，未经峰岹科技明确书面许可，任何单位及个人不得以任何形式或方式（如电子、机械、磁性、光学、化学、手工操作或其他任何方式），对本文档任何内容进行复制、传播、抄录、存储于检索系统或翻译为任何语种，亦不得更改或删除本内容副本中的任何版权或其他声明信息。

峰岹科技（深圳）股份有限公司

深圳市南山区科技中二路深圳软件园二期11栋2楼203

邮编：518057

电话：0755-26867710

传真：0755-26867715

网址：www.fortiortech.com

本文件所载内容

**峰岹科技（深圳）股份有限公司版权所有，保留一切权力。**