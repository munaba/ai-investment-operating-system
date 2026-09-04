declare const process: any;
import { cn } from "@/lib/utils";

const Skiper65 = () => {
  return (
    <div className="flex h-full w-full flex-col items-center justify-center">
      <div className="mb-40 grid content-start justify-items-center gap-6 text-center">
        <span className="after:to-foreground relative max-w-[12ch] text-xs uppercase leading-tight opacity-40 after:absolute after:left-1/2 after:top-full after:h-16 after:w-px after:bg-gradient-to-b after:from-transparent after:content-['']">
          minimal Breakpoint indicator
        </span>
      </div>
      <BreakpointIndicator />
    </div>
  );
};

const BreakpointIndicator = ({ className }: { className?: string }) => {
  if (process.env.NODE_ENV === "production") return null;
  return (
    <div
      className={cn(
        "bottom-1 left-1 z-50 flex size-6 items-center justify-center rounded-full bg-black p-2 font-mono text-xs text-white",
        className,
      )}
    >
      <div className="block sm:hidden">xs</div>
      <div className="hidden sm:block md:hidden">sm</div>
      <div className="hidden md:block lg:hidden">md</div>
      <div className="hidden lg:block xl:hidden">lg</div>
      <div className="hidden xl:block 2xl:hidden">xl</div>
      <div className="hidden 2xl:block">2xl</div>
    </div>
  );
};

export { BreakpointIndicator, Skiper65 };
