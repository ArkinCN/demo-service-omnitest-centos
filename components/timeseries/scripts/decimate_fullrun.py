"""Min/max decimate the 101 MB full-run oscilloscope capture down to a <2 MB demo CSV.

Source : archive-POC/40_工程/测试数据_20260627/fullrun_v2b_20260627.csv (3,000,000 samples)
Target : public/data/fullrun_v2b_decimated.csv

Min/max decimation is used instead of plain stride sampling because the signal carries
spikes (commutation edges on FG1/FG2, PWM transitions) that stride sampling would drop.
For every bucket the per-channel minimum and maximum are both kept, so the rendered
envelope still touches every extreme present in the raw data.
"""
import sys
import time

import numpy as np
import pandas as pd

SRC = "测试数据_20260627/fullrun_v2b_20260627.csv"
DST = "./data/fullrun_v2b_decimated.csv"
BUCKETS = 2000  # 2000 buckets x (min,max) = 4000 rendered points


def main() -> int:
    t0 = time.perf_counter()
    df = pd.read_csv(SRC, dtype=np.float32)
    t_read = time.perf_counter() - t0
    n = len(df)
    cols = list(df.columns)
    print(f"source rows      : {n:,}")
    print(f"source columns   : {cols}")
    print(f"read elapsed     : {t_read:.2f} s")

    t1 = time.perf_counter()
    usable = (n // BUCKETS) * BUCKETS
    idx = np.arange(usable).reshape(BUCKETS, -1)
    time_col = cols[0]
    value_cols = cols[1:]

    t = df[time_col].to_numpy()[:usable].reshape(BUCKETS, -1)
    # Anchor each emitted row on a real sample time: bucket start and bucket end.
    t_lo = t[:, 0]
    t_hi = t[:, -1]

    out = {time_col: np.empty(BUCKETS * 2, dtype=np.float64)}
    out[time_col][0::2] = t_lo
    out[time_col][1::2] = t_hi

    for c in value_cols:
        v = df[c].to_numpy()[:usable].reshape(BUCKETS, -1)
        lo = v.min(axis=1)
        hi = v.max(axis=1)
        col = np.empty(BUCKETS * 2, dtype=np.float64)
        # Emit min first then max; ordering by time keeps the envelope band readable.
        col[0::2] = lo
        col[1::2] = hi
        out[c] = col

    res = pd.DataFrame(out)
    t_dec = time.perf_counter() - t1
    res.to_csv(DST, index=False, float_format="%.6g")
    print(f"decimate elapsed : {t_dec:.3f} s")
    print(f"output rows      : {len(res):,}  (reduction {n / len(res):.0f}x)")
    print(f"output path      : {DST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
