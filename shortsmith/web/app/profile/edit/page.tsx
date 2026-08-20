import { redirect } from "next/navigation";

import { akunSekarang } from "@/lib/akun";
import { TombolKembali } from "@/components/ui/tombol-kembali";

import { FormProfil } from "./form-profil";

export const dynamic = "force-dynamic";

/**
 * Halaman edit profil.
 *
 * Datanya dibaca di server lalu diserahkan ke form sebagai nilai awal, bukan
 * diambil form lewat fetch setelah tampil. Kolom yang mulai kosong lalu terisi
 * sendiri sepersekian detik kemudian membuat orang mengira ia harus mengetik —
 * dan sebagian sudah mulai mengetik sebelum nilainya datang menimpa.
 */
export default async function EditProfil() {
  const akun = await akunSekarang();

  // Tamu dan sesi kata sandi bersama tidak punya akun untuk disunting. Dialihkan
  // ke halaman profil, yang menjelaskan keadaannya — bukan ke form yang setiap
  // tombolnya akan ditolak server.
  if (!akun) redirect("/profile");

  return (
    <section className="profil-halaman profil-halaman-sempit">
      <TombolKembali href="/profile" label="Kembali ke profil" className="profil-halaman-kembali-bulat" />

      <h1 className="profil-halaman-judul">
        <span>EDIT </span>
        <strong>PROFILE</strong>
      </h1>

      <FormProfil
        username={akun.username}
        email={akun.email}
        avatarUrl={akun.avatarUrl}
      />
    </section>
  );
}
