export type ClassValue = string | false | null | undefined | ClassValue[]

/** 轻量 className 合并，无第三方依赖 */
export function cn(...values: ClassValue[]): string {
  const out: string[] = []
  const walk = (v: ClassValue) => {
    if (!v) return
    if (Array.isArray(v)) v.forEach(walk)
    else out.push(v)
  }
  values.forEach(walk)
  return out.join(' ')
}
