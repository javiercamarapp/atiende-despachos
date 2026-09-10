import { cva } from "class-variance-authority";

export const buttonVariants = cva(
  // Pill anatomy ported from Likida's real button/pill language
  // (proyect-x-/src/app/globals.css .pildora, already ported once for
  // login.css .login-btn) — full 999px radius, semibold, generous
  // padding via the size variants below. The press-feedback scale
  // (:active { scale(.97) }) is applied globally in index.css so it
  // covers every <button> in the app, not just this component.
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full text-sm font-semibold tracking-[0.005em] ring-offset-background transition-all duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        // .pildora-tinta: filled, no idle shadow beyond the app's own
        // card shadow, hover lifts 1px and gains a soft shadow tinted
        // with the button's own background color via color-mix.
        default:
          "bg-primary text-primary-foreground hover:bg-primary/90 shadow-card motion-safe:hover:-translate-y-px motion-safe:hover:shadow-[0_10px_26px_hsl(var(--primary)/0.26)]",
        destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        // .pildora-borde: transparent/neutral, border darkens on hover
        // (same color-mix mechanism as login.css .login-btn-borde) —
        // recolored here to this project's neutral tokens rather than
        // primary blue, matching Likida's restrained accent usage.
        outline:
          "border border-border bg-card text-foreground hover:border-[color-mix(in_srgb,hsl(var(--foreground))_26%,transparent)] motion-safe:hover:-translate-y-px",
        secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
        hero: "bg-[image:var(--gradient-gold)] text-foreground font-semibold shadow-elevated hover:shadow-glow hover:scale-105 active:scale-100",
        terracotta: "bg-terracotta text-white font-semibold shadow-card hover:shadow-elevated hover:-translate-y-1",
        gold: "bg-gold text-gold-foreground font-semibold shadow-card hover:shadow-elevated hover:-translate-y-1",
      },
      size: {
        // No per-size rounded-* here on purpose: the base class's
        // rounded-full (999px pill) must win at every size, matching
        // Likida's .pildora, which is pill-shaped regardless of padding.
        default: "h-10 px-5 py-2",
        sm: "h-9 px-4",
        lg: "h-12 px-8 text-base",
        xl: "h-14 px-10 text-lg",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);
