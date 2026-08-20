import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

/**
 * Tombol kaca, dengan versi terang dan gelap.
 *
 * ## Kenapa cva dipakai meski tanpa Tailwind
 *
 * Nilai utama cva — menggabungkan string kelas Tailwind sambil menangani
 * konflik antar kelas — memang tidak terpakai di sini; ukurannya hidup di CSS
 * sebagai `.glass-button-sm` dan seterusnya, bukan sebagai deretan kelas utility.
 *
 * Yang tetap berguna adalah tipenya. `VariantProps` menurunkan tipe prop `size`
 * langsung dari definisi varian, jadi menambah ukuran baru cukup di satu tempat
 * dan TypeScript ikut tahu. Ini juga bentuk yang sama dengan komponen shadcn
 * pada umumnya, sehingga komponen berikutnya bisa ditempel dengan lebih sedikit
 * penyesuaian.
 *
 * ## Kenapa efek kacanya bukan warna semata
 *
 * Kaca terbaca dari tiga hal sekaligus: latar di belakangnya yang buram,
 * pantulan tipis di tepi atas, dan bayangan yang jatuh terpisah di bawahnya.
 * Menghilangkan salah satunya membuat tombol terlihat seperti kotak
 * semitransparan biasa. Ketiganya ada di CSS-nya.
 *
 * Di mode terang, bahan kacanya dibalik: pantulan jadi putih pekat dan
 * bayangannya melembut. Nilai gelap yang sama di latar terang tampak kotor,
 * bukan berkilau.
 */

function cn(...bagian: (string | undefined | null | false)[]): string {
  return bagian.filter(Boolean).join(" ");
}

const glassButtonVariants = cva("glass-button", {
  variants: {
    size: {
      default: "glass-button-default",
      sm: "glass-button-sm",
      lg: "glass-button-lg",
      icon: "glass-button-icon",
    },
  },
  defaultVariants: { size: "default" },
});

export interface GlassButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof glassButtonVariants> {
  contentClassName?: string;
}

const GlassButton = React.forwardRef<HTMLButtonElement, GlassButtonProps>(
  ({ className, children, size, contentClassName, ...props }, ref) => {
    return (
      <div className={cn("glass-button-wrap", className)}>
        <button ref={ref} className={glassButtonVariants({ size })} {...props}>
          <span className={cn("glass-button-text", contentClassName)}>
            {children}
          </span>
        </button>
        {/* Bayangan sebagai elemen TERPISAH, bukan box-shadow pada tombol.
            Tombolnya tembus pandang; box-shadow di elemen yang sama akan
            terlihat menembus kacanya sendiri. */}
        <div className="glass-button-shadow" aria-hidden />
      </div>
    );
  },
);
GlassButton.displayName = "GlassButton";

export { GlassButton, glassButtonVariants };
export default GlassButton;
