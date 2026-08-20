/**
 * Penanda proses berjalan: bentuk yang berputar sambil berubah dari persegi
 * membulat menjadi lingkaran, lalu kembali.
 *
 * ## Kenapa bukan spinner biasa
 *
 * Render satu video makan menit, bukan detik. Spinner lingkaran yang berputar
 * tetap terlihat sama di detik pertama dan menit kelima — ia tidak memberi
 * kesan ada yang berkembang. Bentuk yang bermetamorfosis punya siklus yang bisa
 * diikuti mata, sehingga menunggu lama terasa berjalan, bukan menggantung.
 *
 * ## Kenapa labelnya bisa diganti
 *
 * Pipeline punya tahap yang namanya berarti bagi pengguna — "transkrip",
 * "render", "mengunggah hasil". Menampilkan tahap yang sebenarnya jauh lebih
 * menenangkan daripada kata "Loading" yang sama selama lima belas menit.
 */
export function Memuat({
  label = "Memproses",
  size = 44,
  className = "",
}: {
  label?: string;
  size?: number;
  className?: string;
}) {
  return (
    <div className={`memuat ${className}`} role="status" aria-live="polite">
      <span
        className="memuat-bentuk"
        style={{ width: size, height: size }}
        aria-hidden
      />
      {label ? <span className="memuat-label">{label}</span> : null}
      <span className="sr-only">{label || "Memproses"}</span>
    </div>
  );
}

export default Memuat;
