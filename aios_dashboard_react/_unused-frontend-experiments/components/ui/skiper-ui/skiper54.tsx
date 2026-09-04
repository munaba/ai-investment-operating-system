"use client";

import Autoplay from "embla-carousel-autoplay";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronLeft, ChevronRight } from "lucide-react";
import React, { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

import {
  Carousel,
  CarouselApi,
  CarouselContent,
  CarouselItem,
} from "@/components/ui/carousel";

const Skiper54 = () => {
  const images = [
    {
      src: "/images/x.com/13.jpeg",
      alt: "Illustrations by ©AarzooAly",
      title: "Block Reader",
    },
    {
      src: "/images/x.com/9.jpeg",
      alt: "Illustrations by ©AarzooAly",
      title: "Forest Fungi",
    },
    {
      src: "/images/x.com/20.jpeg",
      alt: "Illustrations by ©AarzooAly",
      title: "Golden Dusk",
    },
    {
      src: "/images/x.com/21.jpeg",
      alt: "Illustrations by ©AarzooAly",
      title: "Silent Peaks",
    },
    {
      src: "/images/x.com/25.jpeg",
      alt: "Illustrations by ©AarzooAly",
      title: "Emerald Woods",
    },
    {
      src: "/images/x.com/32.jpeg",
      alt: "Illustrations by ©AarzooAly",
      title: "Falling Mist",
    },
    {
      src: "/images/x.com/19.jpeg",
      alt: "Illustrations by ©AarzooAly",
      title: "Midnight Veil",
    },
    {
      src: "/images/x.com/3.jpeg",
      alt: "Illustrations by ©AarzooAly",
      title: "Azure Ridge",
    },
    {
      src: "/images/x.com/2.jpeg",
      alt: "Illustrations by ©AarzooAly",
      title: "Cloud Summit",
    },
  ];
  return (
    <div className="flex h-full w-screen items-center justify-center overflow-hidden bg-[#f5f4f3]">
      <Carousel_006
        images={images}
        className=""
        loop={true}
        showNavigation={true}
        showPagination={true}
      />
    </div>
  );
};

interface Carousel_006Props {
  images: { src: string; alt: string; title: string }[];
  className?: string;
  autoplay?: boolean;
  loop?: boolean;
  showNavigation?: boolean;
  showPagination?: boolean;
}

const Carousel_006 = ({
  images,
  className,
  autoplay = false,
  loop = true,
  showNavigation = true,
  showPagination = true,
}: Carousel_006Props) => {
  const [api, setApi] = useState<CarouselApi>();
  const [current, setCurrent] = useState(0);

  useEffect(() => {
    if (!api) return;

    api.on("select", () => {
      setCurrent(api.selectedScrollSnap());
    });
  }, [api]);

  return (
    <Carousel
      setApi={setApi}
      className={cn("w-full", className)}
      opts={{
        loop,
        slidesToScroll: 1,
      }}
      plugins={
        autoplay
          ? [
              Autoplay({
                delay: 2000,
                stopOnInteraction: true,
                stopOnMouseEnter: true,
              }),
            ]
          : []
      }
    >
      <CarouselContent className="flex h-[500px] w-full">
        {images.map((img, index) => (
          <CarouselItem
            key={index}
            className="relative flex h-[81.5%] w-full basis-[73%] items-center justify-center sm:basis-[50%] md:basis-[30%] lg:basis-[25%] xl:basis-[21%]"
          >
            <motion.div
              initial={false}
              animate={{
                clipPath:
                  current !== index
                    ? "inset(15% 0 15% 0 round 2rem)"
                    : "inset(0 0 0 0 round 2rem)",
              }}
              className="h-full w-full overflow-hidden rounded-3xl"
            >
              <div className="relative h-full w-full border">
                <img
                  src={img.src}
                  alt={img.alt}
                  className="h-full w-full scale-105 object-cover"
                />
              </div>
            </motion.div>
            <AnimatePresence mode="wait">
              {current === index && (
                <motion.div
                  initial={{ opacity: 0, filter: "blur(10px)" }}
                  animate={{ opacity: 1, filter: "blur(0px)" }}
                  transition={{ duration: 0.5 }}
                  className="absolute bottom-0 left-2 flex h-[14%] w-full translate-y-full items-center justify-center p-2 text-center font-medium tracking-tight text-black/20"
                >
                  {img.title}
                </motion.div>
              )}
            </AnimatePresence>
          </CarouselItem>
        ))}
      </CarouselContent>

      {showNavigation && (
        <div className="absolute -bottom-4 right-0 flex w-full items-center justify-between gap-2 px-4">
          <button
            aria-label="Previous slide"
            onClick={() => api?.scrollPrev()}
            className="rounded-full bg-black/10 p-2"
          >
            <ChevronLeft className="text-white" />
          </button>
          <button
            aria-label="Next slide"
            onClick={() => api?.scrollNext()}
            className="rounded-full bg-black/10 p-2"
          >
            <ChevronRight className="text-white" />
          </button>
        </div>
      )}

      {showPagination && (
        <div className="flex w-full items-center justify-center">
          <div className="flex items-center justify-center gap-2">
            {Array.from({ length: images.length }).map((_, index) => (
              <button
                key={index}
                onClick={() => api?.scrollTo(index)}
                className={cn(
                  "h-2 w-2 cursor-pointer rounded-full transition-all",
                  current === index ? "bg-black" : "bg-[#D9D9D9]",
                )}
                aria-label={`Go to slide ${index + 1}`}
              />
            ))}
          </div>
        </div>
      )}
    </Carousel>
  );
};

export { Skiper54 };

/**
 * Skiper 54 Carousel_006 — React + Framer Motion
 * Built with shadcn/ui And Embla Carousel - Read docs to learn more https://ui.shadcn.com/docs/components/carousel https://embla-carousel.com/
 *
 * Illustrations by AarzooAly - https://x.com/AarzooAly
 *
 * License & Usage:
 * - Free to use and modify in both personal and commercial projects.
 * - Attribution to Skiper UI is required when using the free version.
 * - No attribution required with Skiper UI Pro.
 *
 * Feedback and contributions are welcome.
 *
 * Author: @gurvinder-singh02
 * Website: https://gxuri.me
 * Twitter: https://x.com/Gur__vi
 */
