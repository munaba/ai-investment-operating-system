"use client"

import * as React from "react"
import useEmblaCarousel from "embla-carousel-react"
import { cn } from "@/lib/utils"

type CarouselContextProps = { carouselRef: any; api: any; opts?: any; orientation?: string }
const CarouselContext = React.createContext<CarouselContextProps | null>(null)
export function Carousel({ opts, orientation="horizontal", children, className, ...props }: any) {
  const [carouselRef, api] = useEmblaCarousel({ loop: false, axis: orientation === 'horizontal' ? 'x' : 'y', ...opts })
  return <CarouselContext.Provider value={{ carouselRef, api, opts, orientation }}><div ref={carouselRef} className={cn('overflow-hidden', className)} {...props}>{children}</div></CarouselContext.Provider>
}
export type CarouselApi = any
export function CarouselContent({ children, className, ...props }: any) { return <div className={cn('flex', className)} {...props}>{children}</div> }
export function CarouselItem({ children, className, ...props }: any) { return <div className={cn('min-w-0 shrink-0 grow-0 basis-full', className)} {...props}>{children}</div> }
export function CarouselPrevious(props: any) { return <button {...props}>Prev</button> }
export function CarouselNext(props: any) { return <button {...props}>Next</button> }
