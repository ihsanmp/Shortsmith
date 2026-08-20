"use client";

/**
 * Tombol kembali berbentuk lingkaran, dengan bahan kaca yang sama seperti
 * tombol lain di aplikasi ini.
 *
 * ## Ke mana ia membawa
 *
 * Ke halaman yang BENAR-BENAR dibuka sebelumnya, mengikuti riwayat browser —
 * bukan ke satu tujuan tetap. Jadi `/projects` -> `/project/123` -> tombol ini
 * mendarat kembali di `/projects`, sedangkan `/profile` -> `/profile/edit` ->
 * tombol ini mendarat di `/profile`.
 *
 * ## Kenapa tetap `<a href>` dan bukan tombol murni
 *
 * `history.back()` sendirian punya satu lubang: kalau halaman ini adalah yang
 * PERTAMA dibuka di tab itu — ditempel dari chat, dibuka di tab baru, atau
 * hasil muat ulang setelah login — tidak ada riwayat untuk dimundurkan.
 * Tombolnya akan diam, atau lebih buruk, melempar keluar ke situs sebelumnya.
 *
 * Karena itu tujuannya tetap ditulis di `href`, dan riwayat hanya dipakai kalau
 * terbukti berasal dari dalam aplikasi ini. Efek sampingnya bagus: klik tengah
 * dan "buka di tab baru" tetap bekerja seperti tautan biasa, dan tombolnya
 * tetap punya tujuan yang sah kalau JavaScript gagal dimuat.
 *
 * ## Kenapa labelnya wajib meski tidak terlihat
 *
 * Isinya hanya panah. Tanpa nama yang terbaca mesin, pembaca layar hanya
 * mengumumkan "tautan" — tanpa petunjuk ke mana ia menuju.
 */
export function TombolKembali({
  href,
  label,
  className = "",
}: {
  href: string;
  /** Tujuan cadangan, sekaligus nama yang dibacakan. Mis. "Kembali ke profil". */
  label: string;
  className?: string;
}) {
  function klik(e: React.MouseEvent<HTMLAnchorElement>) {
    // Klik tengah, Ctrl/Cmd-klik, dan Shift-klik dibiarkan apa adanya — ketiganya
    // berarti "buka di tempat lain", dan memundurkan riwayat bukan itu.
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;

    let dariDalam = false;
    try {
      dariDalam =
        !!document.referrer &&
        new URL(document.referrer).origin === window.location.origin &&
        // Muat ulang halaman yang sama membuat referrer menunjuk ke dirinya
        // sendiri; memundurkannya tidak akan ke mana-mana.
        new URL(document.referrer).pathname !== window.location.pathname;
    } catch {
      // Referrer yang bentuknya tidak sah diperlakukan sebagai "bukan dari
      // dalam", jadi tautannya jalan seperti biasa.
    }

    if (dariDalam && window.history.length > 1) {
      e.preventDefault();
      window.history.back();
    }
  }

  return (
    <a
      href={href}
      onClick={klik}
      className={`kembali-bulat ${className}`}
      aria-label={label}
      title={label}
    >
      <svg
        viewBox="0 0 24 24"
        width="22"
        height="22"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden
      >
        <path d="M14.5 6.5 9 12l5.5 5.5" />
      </svg>
    </a>
  );
}

export default TombolKembali;
