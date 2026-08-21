/**
 * Penanda proses berjalan: bola bercahaya dengan sorot yang berputar di
 * dalamnya, dan huruf yang berdenyut bergiliran di atasnya.
 *
 * ## Kenapa hurufnya dipecah per karakter di sini, bukan di CSS
 *
 * Tiap huruf butuh jeda animasi yang berbeda supaya denyutnya berjalan seperti
 * gelombang. CSS tidak bisa menomori anak elemen dengan cara yang menghasilkan
 * jeda bertahap tanpa menuliskan satu aturan per posisi; membangunnya dari
 * string membuat kata apa pun bisa dipakai tanpa menyentuh stylesheet.
 *
 * ## Kenapa katanya bisa diganti
 *
 * Supaya komponennya tidak terikat pada satu konteks. Halaman proses memakai
 * satu kata tetap ("editing") dan menyerahkan nama tahap ke label bilah
 * progres di bawahnya — kata yang berganti-ganti di dalam bola membuat
 * lebarnya berubah setiap beberapa menit, dan bolanya ikut terlihat berdenyut
 * ukuran.
 *
 * ## Yang diubah dari kode contohnya
 *
 * Kode aslinya memakai `class` (atribut HTML) alih-alih `className`, jadi React
 * akan mengabaikannya dan seluruh gayanya tidak pernah menempel. Ia juga
 * menyimpan `useState` yang tidak pernah dipakai, yang memaksa komponen ini
 * jadi komponen klien tanpa alasan. Keduanya dibuang.
 */
export function PemuatAI({
  kata = "Memproses",
  ukuran = 220,
  className = "",
}: {
  kata?: string;
  /** Diameter bolanya, dalam piksel. */
  ukuran?: number;
  className?: string;
}) {
  const huruf = [...kata];

  return (
    <div
      className={`pemuat-ai ${className}`}
      style={{ "--pemuat-d": `${ukuran}px` } as React.CSSProperties}
      role="status"
      aria-live="polite"
    >
      <div className="pemuat-ai-bola" aria-hidden />
      <p className="pemuat-ai-kata" aria-hidden>
        {huruf.map((h, i) => (
          <span
            key={`${h}-${i}`}
            className="pemuat-ai-huruf"
            style={{ animationDelay: `${i * 0.1}s` }}
          >
            {/* Spasi tetap butuh lebarnya sendiri; tanpa ini kata bersuku
                banyak menyatu jadi satu blok. */}
            {h === " " ? " " : h}
          </span>
        ))}
      </p>
      <span className="sr-only">{kata}</span>
    </div>
  );
}

export default PemuatAI;
