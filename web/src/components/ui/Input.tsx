import type { InputHTMLAttributes, TextareaHTMLAttributes } from 'react'
import { cn } from './cn'

const field =
  'w-full rounded-tps border border-line bg-white px-2.5 text-[13px] text-t1 placeholder:text-t3 ' +
  'transition-colors duration-150 hover:border-p300 focus:border-p500 focus:outline-none'

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(field, 'h-[32px]', className)} {...rest} />
}

export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(field, 'resize-none py-2 leading-6', className)} {...rest} />
}
